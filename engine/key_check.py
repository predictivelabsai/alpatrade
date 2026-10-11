"""Settings > Integrations "Check": decrypt a saved Alpaca key pair and make ONE read-only
GET /v2/account on the matching endpoint (paper -> paper-api, live -> api). Stores and returns
the result. Never logs or returns key material."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)
PAPER = "https://paper-api.alpaca.markets"
LIVE = "https://api.alpaca.markets"
_SQL = Path(__file__).resolve().parents[1] / "sql" / "50_key_check_columns.sql"
_ready = False


def _pool():
    from engine.auth import _get_pool
    return _get_pool()


def ensure_schema() -> None:
    global _ready
    if _ready:
        return
    from sqlalchemy import text
    with _pool().get_session() as s:
        for stmt in [x.strip() for x in _SQL.read_text().split(";")]:
            body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
            if body:
                s.execute(text(body))
    _ready = True


def _b(v):
    return v.encode() if isinstance(v, str) else bytes(v)


def inspect_pair(api_key: str, secret: str, mode: str) -> list[str]:
    """Problems on OUR side with a decrypted pair (no values in the output)."""
    out = []
    for name, v in (("key", api_key), ("secret", secret)):
        if v != v.strip():
            out.append(f"stored {name} has leading/trailing whitespace")
        if any(c.isspace() for c in v.strip()):
            out.append(f"stored {name} contains whitespace/newline")
        if any(ord(c) > 126 or ord(c) < 32 for c in v):
            out.append(f"stored {name} contains non-printable characters")
    k = api_key.strip().upper()
    if mode == "paper" and k.startswith("AK"):
        out.append("wrong environment: this is a LIVE key (AK…) saved as paper")
    if mode == "live" and k.startswith("PK"):
        out.append("wrong environment: this is a PAPER key (PK…) saved as live")
    return out


def call_account(base: str, api_key: str, secret: str, http=None) -> dict:
    """One read-only GET /v2/account. Returns {ok, http, text, account_number, status}."""
    import requests
    try:
        r = (http or requests).get(base + "/v2/account", timeout=15,
                                   headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "http": None, "text": f"Alpaca unreachable ({type(exc).__name__})"}
    if r.status_code == 200:
        a = r.json() or {}
        return {"ok": True, "http": 200, "account_number": str(a.get("account_number") or ""),
                "status": a.get("status"),
                "text": f"OK · account {a.get('account_number')} · status {a.get('status')}"}
    try:
        msg = (r.json() or {}).get("message") or r.text
    except Exception:  # noqa: BLE001
        msg = r.text
    msg = " ".join(str(msg or "").split())[:200]
    return {"ok": False, "http": r.status_code, "text": f"HTTP {r.status_code} from {base.split('//')[1]}: {msg}"}


def _row(mode: str, user_id: str, ref: str):
    from sqlalchemy import text
    if mode == "paper":
        q = ("SELECT alpaca_api_key_enc, alpaca_secret_key_enc FROM alpatrade.user_accounts "
             "WHERE user_id = CAST(:u AS UUID) AND account_id = CAST(:r AS UUID) AND is_active")
    else:
        q = ("SELECT api_key_enc, secret_key_enc FROM alpatrade.user_live_broker_accounts "
             "WHERE user_id = CAST(:u AS UUID) AND account_number = :r AND is_active")
    with _pool().get_session() as s:
        return s.execute(text(q), {"u": str(user_id), "r": str(ref)}).first()


def _save(mode: str, user_id: str, ref: str, result: str) -> None:
    from sqlalchemy import text
    tbl, col, cast = (("user_accounts", "account_id", "CAST(:r AS UUID)") if mode == "paper"
                      else ("user_live_broker_accounts", "account_number", ":r"))
    with _pool().get_session() as s:
        s.execute(text(f"UPDATE alpatrade.{tbl} SET last_checked_at = NOW(), last_check_result = :res "
                       f"WHERE user_id = CAST(:u AS UUID) AND {col} = {cast}"),
                  {"res": result, "u": str(user_id), "r": str(ref)})


def check(mode: str, user_id: str, ref: str, http=None, save: bool = True) -> dict:
    """Check one saved key pair (mode 'paper' by account_id, 'live' by account_number)."""
    if mode not in ("paper", "live"):
        raise ValueError("mode")
    ensure_schema()
    row = _row(mode, user_id, ref)
    if not row or not row[0] or not row[1]:
        res = {"ok": False, "text": "No saved key found for this account."}
    else:
        from engine.auth import decrypt_key
        try:
            k, s_ = decrypt_key(_b(row[0])), decrypt_key(_b(row[1]))
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "text": f"Our side: stored key could not be decrypted ({type(exc).__name__}). "
                                         "Please re-enter the keys."}
        else:
            issues = inspect_pair(k, s_, mode)
            res = call_account(PAPER if mode == "paper" else LIVE, k, s_, http=http)
            if mode == "live" and res.get("ok") and str(res.get("account_number")) != str(ref):
                res = {"ok": False, "text": f"Keys work but belong to account {res.get('account_number')}, "
                                             f"not {ref}."}
            if issues:
                res["text"] += " · our side: " + "; ".join(issues)
    if save:
        try:
            _save(mode, user_id, ref, json.dumps({"ok": bool(res.get("ok")), "text": res["text"]}))
        except Exception as exc:  # noqa: BLE001
            log.warning("key check save failed: %s", type(exc).__name__)
    return res


def last_results(user_id: str) -> dict:
    """{('paper', account_id) | ('live', account_number): {at, ok, text}}."""
    out: dict = {}
    try:
        ensure_schema()
        from sqlalchemy import text
        with _pool().get_session() as s:
            for mode, q in (("paper", "SELECT account_id::text, last_checked_at, last_check_result FROM "
                                      "alpatrade.user_accounts WHERE user_id = CAST(:u AS UUID) AND is_active"),
                            ("live", "SELECT account_number, last_checked_at, last_check_result FROM "
                                     "alpatrade.user_live_broker_accounts WHERE user_id = CAST(:u AS UUID) AND is_active")):
                for ref, at, raw in s.execute(text(q), {"u": str(user_id)}).all():
                    if at and raw:
                        d = json.loads(raw)
                        out[(mode, str(ref))] = {"at": at, "ok": d.get("ok"), "text": d.get("text")}
    except Exception as exc:  # noqa: BLE001
        log.warning("key check load failed: %s", type(exc).__name__)
    return out
