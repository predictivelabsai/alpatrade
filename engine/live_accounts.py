"""Per-user READ-ONLY live broker account links (``alpatrade.user_live_broker_accounts``).

Deliberately a separate table from ``alpatrade.user_accounts``: every paper
trading path (chat tools, paper jobs, reconcile, cleanup) reads
``user_accounts`` only, so a live account linked here is structurally invisible
to them. The Portfolio P&L dashboard (``/dashboard``) may *list* these rows in
its account dropdown and load them through the read-only live client with
synthetic ids ``live:<account_number>`` — it never places orders. Rows carry
``read_only = TRUE`` (enforced by a CHECK constraint) and keys are
Fernet-encrypted with the app's ENCRYPTION_KEY via
:func:`engine.auth.encrypt_key`, exactly like ``user_accounts``.

Importers: :mod:`engine.web.ph_live_account`, :mod:`engine.reporting.pnl_dashboard`
(display only), and the operator CLI ``scripts/link_live_account.py``.
"""
from __future__ import annotations

from typing import Optional

from engine.auth import decrypt_key, encrypt_key

TABLE = "alpatrade.user_live_broker_accounts"


def _pool():
    from engine.db.pool import DatabasePool
    return DatabasePool()


def _b(v):
    return bytes(v) if isinstance(v, memoryview) else v


def _hint(api_key: str) -> str:
    return f"{api_key[:4]}…{api_key[-2:]}" if len(api_key) >= 8 else "configured"


def store_live_account(user_id: str, account_number: str, api_key: str, secret_key: str,
                       label: str = "Alpaca live") -> None:
    """Encrypt and upsert a read-only live account link for one user."""
    account_number = (account_number or "").strip()
    if not user_id or not account_number or not api_key or not secret_key:
        raise ValueError("user_id, account_number, api_key and secret_key are required")
    from sqlalchemy import text
    with _pool().get_session() as session:
        session.execute(text(f"""
            INSERT INTO {TABLE}
                (user_id, account_number, label, api_key_enc, secret_key_enc,
                 api_key_hint, read_only, is_active)
            VALUES (:uid, :acct, :label, :k, :s, :hint, TRUE, TRUE)
            ON CONFLICT (user_id, account_number) DO UPDATE SET
                label = EXCLUDED.label, api_key_enc = EXCLUDED.api_key_enc,
                secret_key_enc = EXCLUDED.secret_key_enc, api_key_hint = EXCLUDED.api_key_hint,
                read_only = TRUE, is_active = TRUE, updated_at = NOW()
        """), {"uid": user_id, "acct": account_number, "label": label,
                "k": encrypt_key(api_key), "s": encrypt_key(secret_key),
                "hint": _hint(api_key)})


def list_live_accounts(user_id: str) -> list[dict]:
    """Display-safe list of the user's active live links (no key material)."""
    if not user_id:
        return []
    from sqlalchemy import text
    with _pool().get_session() as session:
        rows = session.execute(text(f"""
            SELECT account_number, label, api_key_hint, updated_at
            FROM {TABLE}
            WHERE user_id = :uid AND is_active AND read_only
            ORDER BY created_at ASC
        """), {"uid": user_id}).mappings().all()
    return [dict(r) for r in rows]


def get_live_account_credentials(user_id: str,
                                 account_number: Optional[str] = None) -> Optional[dict]:
    """Decrypted credentials for the user's own live link, or None.

    Scoped by ``user_id`` so one user can never read another's link. Only the
    read-only live view may call this; never log the result.
    """
    if not user_id:
        return None
    from sqlalchemy import text
    sql = f"""
        SELECT account_number, label, api_key_enc, secret_key_enc, read_only
        FROM {TABLE}
        WHERE user_id = :uid AND is_active AND read_only
          {"AND account_number = :acct" if account_number else ""}
        ORDER BY created_at ASC LIMIT 1
    """
    params = {"uid": user_id}
    if account_number:
        params["acct"] = account_number
    with _pool().get_session() as session:
        row = session.execute(text(sql), params).mappings().first()
    if not row or not row["read_only"]:
        return None
    return {
        "account_number": str(row["account_number"]),
        "label": row["label"],
        "api_key": decrypt_key(_b(row["api_key_enc"])),
        "secret_key": decrypt_key(_b(row["secret_key_enc"])),
    }


PAPER_BASE_URL = "https://paper-api.alpaca.markets"


class KeyValidationError(ValueError):
    """User-facing reason a key pair was refused (never contains key material)."""


def validate_live_keys(api_key: str, secret_key: str, http=None) -> dict:
    """Check a LIVE key pair with ONE read-only GET /v2/account on api.alpaca.markets.
    Returns {account_number, status, equity, cash}; raises KeyValidationError."""
    from engine.brokers.alpaca_live_readonly import LiveReadOnlyClient, LiveReadOnlyError
    api_key, secret_key = (api_key or "").strip(), (secret_key or "").strip()
    if not api_key or not secret_key:
        raise KeyValidationError("Both the live API key and secret are required.")
    if api_key.upper().startswith("PK"):
        raise KeyValidationError("These are PAPER keys (they start with PK). Save them under Paper.")
    try:
        acct = LiveReadOnlyClient(api_key, secret_key, http=http).get_account()
    except LiveReadOnlyError as exc:
        msg = str(exc)
        if "unauthorized" in msg.lower():
            msg = "Alpaca rejected these live keys (unauthorized). Check the key and secret, or regenerate them."
        raise KeyValidationError(msg) from None
    number = str(acct.get("account_number") or "").strip()
    if not number:
        raise KeyValidationError("Alpaca did not return an account number for these keys.")
    return {"account_number": number, "status": acct.get("status"),
            "equity": acct.get("equity"), "cash": acct.get("cash")}


def validate_paper_keys(api_key: str, secret_key: str, http=None) -> dict:
    """Check a PAPER key pair with ONE read-only GET /v2/account on paper-api.alpaca.markets."""
    import requests
    api_key, secret_key = (api_key or "").strip(), (secret_key or "").strip()
    if not api_key or not secret_key:
        raise KeyValidationError("Both the paper API key and secret are required.")
    if api_key.upper().startswith("AK"):
        raise KeyValidationError("These are LIVE keys (they start with AK). Save them under Live.")
    try:
        r = (http or requests).get(PAPER_BASE_URL + "/v2/account", timeout=15,
                                   headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key})
    except Exception as exc:  # noqa: BLE001
        raise KeyValidationError(f"Alpaca paper API unreachable ({type(exc).__name__}).") from None
    if r.status_code in (401, 403):
        raise KeyValidationError("Alpaca rejected these paper keys (unauthorized). Check the key and secret.")
    if r.status_code != 200:
        raise KeyValidationError(f"Alpaca paper API returned HTTP {r.status_code}.")
    a = r.json() or {}
    return {"account_number": str(a.get("account_number") or ""), "status": a.get("status")}


def deactivate_live_account(user_id: str, account_number: str) -> None:
    """Unlink (soft-delete) one of the user's own live links; keys are wiped."""
    from sqlalchemy import text
    with _pool().get_session() as session:
        session.execute(text(f"""
            UPDATE {TABLE} SET is_active = FALSE, api_key_enc = :z, secret_key_enc = :z, updated_at = NOW()
            WHERE user_id = :uid AND account_number = :acct
        """), {"uid": user_id, "acct": str(account_number), "z": encrypt_key("revoked")})
        try:   # its live strategies stop too (the user runner also refuses without an active link)
            session.execute(text("""UPDATE alpatrade.user_strategy_activations SET status = 'deactivated',
                                    updated_at = NOW() WHERE user_id = CAST(:uid AS UUID) AND account_ref = :acct
                                    AND mode = 'live'"""), {"uid": user_id, "acct": str(account_number)})
        except Exception:  # noqa: BLE001 -- table may not exist yet
            pass
