"""Excluded ("junk") securities — ONE helper for every P&L / position report.

Rules (sql/53_excluded_securities.sql):
  * manual rows in ``alpatrade.excluded_securities`` (global, or per account_ref);
  * auto: the Alpaca asset is inactive or not tradable (cached in
    ``alpatrade.asset_status_cache``, refreshed daily);
  * optional dust: |market value| < ``EXCLUSION_DUST_USD`` (env, default 0 = off).

How excluded positions affect figures (``apply``): they are removed from position
tables / unrealised P&L, and their *current* market value is subtracted from current
equity AND from every historical equity point / baseline. Subtracting the same amount
from both ends means adding an exclusion never creates a fake P&L jump: period P&L
(equity − baseline − net deposits) is unchanged, while equity and the % denominators
reflect the tradable book only.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

log = logging.getLogger(__name__)

# Used only when the DB is unreachable, so BNBX never leaks back into reports.
FALLBACK_RULES = [{"symbol": "BNBX", "scope": "global", "account_ref": None,
                   "reason": "Leftover dust (zombie OTC position)", "auto": False}]
_RULES_TTL = 60.0
_ASSET_TTL = timedelta(days=1)
_lock = threading.Lock()
_rules_cache: dict = {"at": 0.0, "rows": None}
_asset_mem: dict[str, tuple[float, Optional[dict]]] = {}


def _pool():
    from engine.auth import _get_pool
    return _get_pool()


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def dust_threshold() -> float:
    return max(0.0, _num(os.getenv("EXCLUSION_DUST_USD", "0")))


def auto_enabled() -> bool:
    return os.getenv("EXCLUSION_AUTO_ASSET_STATUS", "1").strip().lower() not in ("0", "false", "no")


# ------------------------------------------------------------------ manual rules
def list_rules(force: bool = False) -> list[dict]:
    now = time.time()
    with _lock:
        if not force and _rules_cache["rows"] is not None and now - _rules_cache["at"] < _RULES_TTL:
            return list(_rules_cache["rows"])
    try:
        from sqlalchemy import text
        with _pool().get_session() as s:
            rows = s.execute(text(
                "SELECT id, symbol, scope, account_ref, reason, auto, created_at "
                "FROM alpatrade.excluded_securities ORDER BY symbol, scope")).mappings().all()
        out = [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001 — table missing / DB down
        log.warning("excluded_securities unavailable: %s", type(exc).__name__)
        out = [dict(r) for r in FALLBACK_RULES]
    with _lock:
        _rules_cache.update(at=now, rows=out)
    return list(out)


def set_rules_for_tests(rows: Optional[list[dict]]) -> None:
    """Pin the rule set (tests); ``None`` clears the cache."""
    with _lock:
        _rules_cache.update(at=time.time() + (1e9 if rows is not None else -1e9), rows=rows)
        _asset_mem.clear()


def add_rule(symbol: str, account_ref: Optional[str], reason: str, auto: bool = False) -> None:
    from sqlalchemy import text
    sym = (symbol or "").strip().upper()
    ref = (account_ref or "").strip() or None
    if not sym or len(sym) > 20:
        raise ValueError("symbol required")
    with _pool().get_session() as s:
        s.execute(text(
            "INSERT INTO alpatrade.excluded_securities (symbol, scope, account_ref, reason, auto) "
            "VALUES (:s, :sc, :a, :r, :au) ON CONFLICT DO NOTHING"),
            {"s": sym, "sc": "account" if ref else "global", "a": ref,
             "r": (reason or "").strip()[:300], "au": bool(auto)})
        s.commit()
    list_rules(force=True)


def remove_rule(rule_id: int) -> None:
    from sqlalchemy import text
    with _pool().get_session() as s:
        s.execute(text("DELETE FROM alpatrade.excluded_securities WHERE id = :i"), {"i": int(rule_id)})
        s.commit()
    list_rules(force=True)


def _manual_reason(symbol: str, refs: set[str]) -> Optional[str]:
    for r in list_rules():
        if str(r.get("symbol") or "").upper() != symbol:
            continue
        if r.get("scope") == "global" or str(r.get("account_ref") or "").upper() in refs:
            return r.get("reason") or "excluded"
    return None


# ------------------------------------------------------------------ asset status
def _default_lookup(symbol: str) -> Optional[dict]:
    """Asset metadata is global on Alpaca: use the platform paper keys."""
    from engine.brokers.alpaca import AlpacaAPI
    a = AlpacaAPI(paper=True).get_asset(symbol)
    if not isinstance(a, dict) or "error" in a:
        return None
    st = a.get("status")
    st = getattr(st, "value", st)
    return {"status": str(st or "").lower().replace("assetstatus.", ""),
            "tradable": bool(a.get("tradable"))}


def asset_status(symbol: str, lookup: Optional[Callable[[str], Optional[dict]]] = None) -> Optional[dict]:
    """{status, tradable} for ``symbol``; memory → DB cache (≤1 day) → Alpaca."""
    now = time.time()
    hit = _asset_mem.get(symbol)
    if hit and now - hit[0] < _ASSET_TTL.total_seconds():
        return hit[1]
    info = None
    from sqlalchemy import text
    if lookup is None:
        try:
            with _pool().get_session() as s:
                row = s.execute(text("SELECT status, tradable, checked_at FROM alpatrade.asset_status_cache "
                                     "WHERE symbol = :s"), {"s": symbol}).fetchone()
            if row and row[2] and datetime.now(timezone.utc) - row[2] < _ASSET_TTL:
                info = {"status": row[0], "tradable": row[1]}
        except Exception:  # noqa: BLE001
            pass
    if info is None:
        try:
            info = (lookup or _default_lookup)(symbol)
        except Exception as exc:  # noqa: BLE001
            log.warning("asset status lookup failed for %s: %s", symbol, type(exc).__name__)
            info = None
        if info is not None and lookup is None:
            try:
                with _pool().get_session() as s:
                    s.execute(text(
                        "INSERT INTO alpatrade.asset_status_cache (symbol, status, tradable, checked_at) "
                        "VALUES (:s, :st, :t, now()) ON CONFLICT (symbol) DO UPDATE SET "
                        "status = EXCLUDED.status, tradable = EXCLUDED.tradable, checked_at = now()"),
                        {"s": symbol, "st": info.get("status"), "t": info.get("tradable")})
                    s.commit()
            except Exception:  # noqa: BLE001
                pass
    _asset_mem[symbol] = (now, info)
    return info


# ------------------------------------------------------------------ core API
def exclusion_reason(position: dict, account_refs: Iterable[Optional[str]] = (),
                     lookup: Optional[Callable] = None) -> Optional[str]:
    sym = str(position.get("symbol") or "").upper()
    if not sym:
        return None
    refs = {str(r).upper() for r in account_refs if r}
    reason = _manual_reason(sym, refs)
    if reason:
        return reason
    dust = dust_threshold()
    if dust and abs(_num(position.get("market_value"))) < dust:
        return f"dust (< ${dust:,.0f})"
    if auto_enabled():
        info = asset_status(sym, lookup)
        if info and (str(info.get("status") or "").lower() == "inactive" or info.get("tradable") is False):
            return "auto: not active/tradable on Alpaca"
    return None


def split_positions(positions: Optional[list], account_refs: Iterable[Optional[str]] = (),
                    lookup: Optional[Callable] = None) -> tuple[list[dict], list[dict]]:
    """(kept, excluded). Excluded rows get ``exclusion_reason``."""
    refs = list(account_refs)
    kept, excluded = [], []
    for p in positions if isinstance(positions, list) else []:
        why = exclusion_reason(p, refs, lookup)
        if why:
            excluded.append({**p, "exclusion_reason": why})
        else:
            kept.append(p)
    return kept, excluded


def excluded_value(excluded: Iterable[dict]) -> float:
    return sum(_num(p.get("market_value")) for p in excluded or [])


def adjust_history(equity_points: list, ex_mv: float) -> list:
    """Shift a whole equity series by the excluded MV (no fake jump)."""
    if not ex_mv:
        return list(equity_points or [])
    return [(_num(e) - ex_mv) if e is not None else None for e in equity_points or []]


def adjust_account(account: dict, ex_mv: float,
                   keys: tuple = ("equity", "last_equity", "portfolio_value", "long_market_value")) -> dict:
    """Copy of an Alpaca account / summary dict with excluded MV removed from equity fields."""
    out = dict(account or {})
    if not ex_mv:
        return out
    for k in keys:
        if out.get(k) not in (None, ""):
            out[k] = _num(out[k]) - ex_mv
    return out


def footnote(excluded: Iterable[dict]) -> str:
    syms = sorted({str(p.get("symbol")) for p in excluded or []})
    if not syms:
        return ""
    return (", ".join(syms) + (" is" if len(syms) == 1 else " are")
            + " held at the broker but excluded from P&L and positions (junk / untradable).")


def excluded_symbols(account_refs: Iterable[Optional[str]] = ()) -> set[str]:
    """Manual exclusions applying to these accounts (for SQL-side filters)."""
    refs = {str(r).upper() for r in account_refs if r}
    return {str(r["symbol"]).upper() for r in list_rules()
            if r.get("scope") == "global" or str(r.get("account_ref") or "").upper() in refs}
