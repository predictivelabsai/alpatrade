"""Per-user READ-ONLY live broker account links (``alpatrade.user_live_broker_accounts``).

Deliberately a separate table from ``alpatrade.user_accounts``: every paper
trading path (chat tools, paper jobs, reconcile, cleanup, P&L dashboard, the
account switcher) reads ``user_accounts`` only, so a live account linked here is
structurally invisible to them. Rows carry ``read_only = TRUE`` (enforced by a
CHECK constraint) and keys are Fernet-encrypted with the app's ENCRYPTION_KEY via
:func:`engine.auth.encrypt_key`, exactly like ``user_accounts``.

Only :mod:`engine.web.ph_live_account` (the GET-only view) and the operator CLI
``scripts/link_live_account.py`` import this module.
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
