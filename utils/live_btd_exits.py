"""Broker-side exits for the live BTD runner (pure helpers, no I/O).

Once a position has passed its calendar min-hold (and never on its buy date: PDT-safe),
the runner places REAL Alpaca exit orders at the market-open event so the broker executes
TP/SL instantly, instead of the runner polling prices every few minutes:

* whole-share part  -> one OCO: TP limit at entry x (1 + tp%) + stop at entry x (1 - sl%)
* fractional part   -> a stop at entry x (1 - sl%) (Alpaca rejects OCO/bracket for fractional
                       qty; a second sell for the same shares would be rejected for
                       insufficient qty, so the fraction gets the protective leg only — its
                       upside is realised by the max-hold exit at the close event)
* OCO rejected      -> fallback: one stop for the full qty
* P&L already beyond TP or SL at the open -> immediate market sell (what the old poller did)

All orders are DAY (fractional orders must be DAY), so they expire at the close and are
re-placed at the next open while the position is still held. Client order ids are
deterministic per symbol and ET date, which makes re-runs and failover takeovers idempotent.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, List, Optional

# single source of truth for the rules (v0.50.0); re-exported for existing importers
from utils.btd_rules import exit_eligible, exit_prices, split_qty, stop_exemptions  # noqa: F401

OWN_EXIT_PREFIXES = ("btdtp-", "btdsl-", "btdx-", "btdps-")
# Operator-placed emergency stops (e.g. 2026-10-16 manual fix) are treated as the runner's own
# exits so the time exit / target logic cancels them before selling (no qty conflict).
MANUAL_STOP_PREFIX = "manual-stop-"








def cids(sym: str, today: date, prefix: str = "btd") -> Dict[str, str]:
    """Deterministic exit client ids; ``prefix`` = the strategy's cid prefix (primary: btd)."""
    d = f"{today:%Y%m%d}"
    return {"oco": f"{prefix}tp-{sym}-{d}", "stop": f"{prefix}sl-{sym}-{d}", "market": f"{prefix}x-{sym}-{d}"}


def plan_broker_exits(sym: str, qty: Any, entry_price: float, tp_pct: float, sl_pct: float,
                      today: date, plpc_pct: Optional[float] = None, prefix: str = "btd") -> Dict[str, Any]:
    """Return {"action": "market"|"orders", "reason", "orders": [bodies], "tp", "sl"}.
    plpc_pct = Alpaca's unrealized P&L %% (current vs entry) used for the at-open TP/SL check."""
    tp, sl = exit_prices(entry_price, tp_pct, sl_pct)
    c = cids(sym, today, prefix)
    q = float(qty)
    from utils.btd_rules import open_exit_action
    act = open_exit_action(plpc_pct, {"tp": tp_pct, "sl": sl_pct})
    if act:
        return {"action": "market", "reason": f"{act.upper()} {plpc_pct:.2f}% at open", "tp": tp, "sl": sl,
                "orders": [_market(sym, qty, c["market"])]}
    whole, frac = split_qty(q)
    orders: List[Dict[str, Any]] = []
    if whole >= 1:
        orders.append(oco_order(sym, whole, tp, sl, c["oco"]))
        if frac:
            orders.append(stop_order(sym, f"{frac:.9f}".rstrip("0").rstrip("."), sl, c["stop"]))
    else:
        orders.append(stop_order(sym, qty, sl, c["stop"]))
    return {"action": "orders", "reason": "broker TP/SL", "tp": tp, "sl": sl, "orders": orders}


def oco_order(sym: str, whole: int, tp: float, sl: float, cid: str) -> Dict[str, Any]:
    return {"symbol": sym, "qty": str(int(whole)), "side": "sell", "type": "limit", "time_in_force": "day",
            "order_class": "oco", "take_profit": {"limit_price": f"{tp:.2f}"},
            "stop_loss": {"stop_price": f"{sl:.2f}"}, "client_order_id": cid}


def stop_order(sym: str, qty: Any, sl: float, cid: str) -> Dict[str, Any]:
    return {"symbol": sym, "qty": str(qty), "side": "sell", "type": "stop", "stop_price": f"{sl:.2f}",
            "time_in_force": "day", "client_order_id": cid}


def _market(sym: str, qty: Any, cid: str) -> Dict[str, Any]:
    return {"symbol": sym, "qty": str(qty), "side": "sell", "type": "market", "time_in_force": "day",
            "client_order_id": cid}


def fallback_full_stop(sym: str, qty: Any, sl: float, today: date, prefix: str = "btd") -> Dict[str, Any]:
    """OCO rejected: protect the whole position with one stop (same deterministic stop id)."""
    return stop_order(sym, qty, sl, cids(sym, today, prefix)["stop"])


def own_open_exits(open_orders: List[Dict[str, Any]], sym: str, prefix: str = "btd") -> List[Dict[str, Any]]:
    own = OWN_EXIT_PREFIXES if prefix == "btd" else (f"{prefix}tp-", f"{prefix}sl-", f"{prefix}x-", f"{prefix}ps-")
    own = own + (MANUAL_STOP_PREFIX,)
    return [o for o in open_orders if o.get("symbol") == sym and o.get("side") == "sell"
            and str(o.get("client_order_id") or "").startswith(own)]


# ---------------------------------------------------------------- protective stops (v0.47.0)
# Every open strategy position carries a broker-side stop at entry x (1 - sl%) from the session
# after its buy until it is sold -- also during the min-hold (before v0.47.0 stops existed only
# from the min-hold day, i.e. only on the time-exit day itself). Alpaca rejects GTC for
# fractional stops, so these are DAY orders re-placed every session: at the post-close event
# (queued for the next open), at a pre-open check (08:45 ET), at the open and hourly checks.
# Same-day entries get their stop after the close (PDT guard: no same-day round trip).

def protective_stop_cid(sym: str, session_day: date, prefix: str = "btd", attempt: int = 1) -> str:
    base = f"{prefix}ps-{sym}-{session_day:%Y%m%d}"
    return base if attempt <= 1 else f"{base}-{attempt}"


def is_stop_only(o: Dict[str, Any]) -> bool:
    """A plain protective stop (not an OCO / market / limit exit)."""
    return o.get("type") == "stop" and not o.get("order_class") in ("oco", "bracket", "oto")


def open_sells(open_orders: List[Dict[str, Any]], sym: str) -> List[Dict[str, Any]]:
    return [o for o in open_orders if o.get("symbol") == sym and o.get("side") == "sell"]


def plan_protective_stops(tracked: Dict[str, Dict[str, Any]], positions: Dict[str, Dict[str, Any]],
                          open_orders: List[Dict[str, Any]], *, today: date, session_day: date,
                          market_open: bool, sl_pct: float, prefix: str = "btd",
                          expect_live_stops: Optional[bool] = None,
                          P: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Positions this strategy tracks that have NO working sell order at the broker.

    Returns [{"sym", "body", "sl", "overdue", "skip"}]: ``overdue`` = the position should already
    have had a stop (bought before ``session_day``) -> alert; ``skip`` = reason not to place now
    (same-day entry while the market is open: PDT guard, placed after the close).

    v0.51.0: with ``P`` each position uses the stop % fixed at its entry (meta ``sl_pct``, ATR /
    stdev stop modes) and ``stop_timing=exit_day`` leaves positions without a stop until their
    min-hold is met on ``session_day`` (btd_rules.stop_live, same rule as the backtester)."""
    from utils.btd_rules import pos_pcts, stop_live
    out = []
    for sym, meta in sorted(tracked.items()):
        pos = positions.get(sym)
        if not pos:
            continue
        qty = uncovered_qty(pos, open_sells(open_orders, sym))
        if qty <= 0:
            continue
        entry_px = float(pos.get("avg_entry_price") or 0)
        if entry_px <= 0:
            out.append({"sym": sym, "body": None, "sl": None, "overdue": True, "skip": "no avg_entry_price"})
            continue
        entry_d = date.fromisoformat(str(meta.get("entry_date") or today.isoformat()))
        if P is not None and not stop_live(entry_d, session_day, P) and entry_d < session_day:
            continue                                   # exit_day timing: no stop before the min-hold
        _, sl = exit_prices(entry_px, 0.0, pos_pcts({"tp": 0.0, "sl": sl_pct}, meta)[1])
        skip = "same-day entry, stop after the close (PDT guard)" if (market_open and entry_d >= today) else None
        # alert only when a stop should be working now (pre-open / session) on an older position;
        # after the close the DAY stops have simply expired and are re-placed for the next session
        live = market_open if expect_live_stops is None else expect_live_stops
        overdue = bool(live and entry_d < today and not skip)
        qs = f"{qty:.9f}".rstrip("0").rstrip(".")
        body = stop_order(sym, qs, sl, protective_stop_cid(sym, session_day, prefix))
        out.append({"sym": sym, "body": body, "sl": sl, "overdue": overdue, "skip": skip,
                    "bodies": protective_stop_bodies(sym, qty, sl, session_day, prefix)})
    return out


def uncovered_qty(pos: Dict[str, Any], sells: List[Dict[str, Any]]) -> float:
    """Shares of a position not yet covered by an open sell (v0.49.0). Alpaca's qty_available
    already excludes shares held for open sells; a sell order without a qty counts as covering
    the whole position (conservative: never stack a second sell on unknown coverage)."""
    total = float(pos.get("qty") or 0)
    avail = float(pos.get("qty_available") if pos.get("qty_available") not in (None, "") else total)
    if sells:
        if any(not o.get("qty") for o in sells):
            return 0.0
        covered = sum(float(o.get("qty") or 0) - float(o.get("filled_qty") or 0) for o in sells)
        avail = min(avail, total - covered)
    return round(avail, 9) if avail > 1e-9 else 0.0


def protective_stop_bodies(sym: str, qty: Any, sl: float, session_day: date, prefix: str = "btd",
                           attempt: int = 1) -> List[Dict[str, Any]]:
    """v0.49.0: whole shares -> ONE GTC stop (survives a runner outage / the overnight session
    boundary; Alpaca only rejects GTC for fractional qty); fractional remainder -> DAY stop,
    re-placed every session as before. Client ids: ``<prefix>ps-SYM-YYYYMMDD[g][-n]``."""
    whole, frac = split_qty(qty)
    cid = protective_stop_cid(sym, session_day, prefix, attempt)
    out: List[Dict[str, Any]] = []
    if whole >= 1:
        gcid = f"{prefix}ps-{sym}-{session_day:%Y%m%d}g" + ("" if attempt <= 1 else f"-{attempt}")
        b = stop_order(sym, str(whole), sl, gcid)
        b["time_in_force"] = "gtc"
        out.append(b)
    if frac:
        out.append(stop_order(sym, f"{frac:.9f}".rstrip("0").rstrip("."), sl, cid))
    return out


def below_stop(pos: Dict[str, Any], sl: Optional[float]) -> bool:
    """Last price at/under the stop level (gap-down open or a stop that never triggered)."""
    try:
        px = float(pos.get("current_price") or 0)
    except (TypeError, ValueError):
        return False
    return bool(sl) and 0 < px <= float(sl)


def tif_rejected(exc_text: str) -> bool:
    """Alpaca 422 for a time_in_force it won't take on this order (fallback: DAY)."""
    t = (exc_text or "").lower()
    return "time_in_force" in t or "time in force" in t or "gtc" in t


def stop_rejected_below(exc_text: str) -> bool:
    """Alpaca's 422 when the market is already below the stop level."""
    t = (exc_text or "").lower()
    return "stop price must be less than current price" in t or "stop_price must be less" in t


def order_fill(o: Dict[str, Any]) -> tuple[float, float, bool]:
    """(filled_qty, vwap, final) across an order and its legs (OCO stop leg fills there)."""
    final_st = ("filled", "canceled", "expired", "rejected", "done_for_day", "replaced")
    parts = [o] + list(o.get("legs") or [])
    qty = sum(float(p.get("filled_qty") or 0) for p in parts)
    notional = sum(float(p.get("filled_qty") or 0) * float(p.get("filled_avg_price") or 0) for p in parts)
    final = all(p.get("status") in final_st for p in parts)
    return qty, (notional / qty if qty else 0.0), final

