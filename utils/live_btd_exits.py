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

OWN_EXIT_PREFIXES = ("btdtp-", "btdsl-", "btdx-", "btdps-")
# Operator-placed emergency stops (e.g. 2026-10-16 manual fix) are treated as the runner's own
# exits so the time exit / target logic cancels them before selling (no qty conflict).
MANUAL_STOP_PREFIX = "manual-stop-"


def exit_eligible(entry_date: date, today: date, min_hold_days: int) -> bool:
    """Broker exits may exist only from the first ET date that is >= min-hold calendar days
    after the buy AND strictly after the buy date (never a same-day round trip)."""
    return entry_date < today and (today - entry_date).days >= max(0, int(min_hold_days))


def split_qty(qty: Any) -> tuple[int, float]:
    q = float(qty)
    whole = int(math.floor(q + 1e-9))
    frac = round(q - whole, 9)
    return whole, (frac if frac > 1e-9 else 0.0)


def exit_prices(entry_price: float, tp_pct: float, sl_pct: float) -> tuple[float, float]:
    """TP limit rounded UP to the cent (never below the target), stop rounded DOWN."""
    tp = math.ceil(entry_price * (1 + tp_pct / 100.0) * 100 - 1e-6) / 100
    sl = math.floor(entry_price * (1 - sl_pct / 100.0) * 100 + 1e-6) / 100
    return round(tp, 2), round(sl, 2)


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
    if plpc_pct is not None and plpc_pct >= tp_pct:
        return {"action": "market", "reason": f"TP {plpc_pct:.2f}% at open", "tp": tp, "sl": sl,
                "orders": [_market(sym, qty, c["market"])]}
    if plpc_pct is not None and plpc_pct <= -sl_pct:
        return {"action": "market", "reason": f"SL {plpc_pct:.2f}% at open", "tp": tp, "sl": sl,
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
                          expect_live_stops: Optional[bool] = None) -> List[Dict[str, Any]]:
    """Positions this strategy tracks that have NO working sell order at the broker.

    Returns [{"sym", "body", "sl", "overdue", "skip"}]: ``overdue`` = the position should already
    have had a stop (bought before ``session_day``) -> alert; ``skip`` = reason not to place now
    (same-day entry while the market is open: PDT guard, placed after the close)."""
    out = []
    for sym, meta in sorted(tracked.items()):
        pos = positions.get(sym)
        if not pos or open_sells(open_orders, sym):
            continue
        qty = pos.get("qty_available") or pos.get("qty")
        if not qty or float(qty) <= 0:
            continue
        entry_px = float(pos.get("avg_entry_price") or 0)
        if entry_px <= 0:
            out.append({"sym": sym, "body": None, "sl": None, "overdue": True, "skip": "no avg_entry_price"})
            continue
        _, sl = exit_prices(entry_px, 0.0, sl_pct)
        entry_d = date.fromisoformat(str(meta.get("entry_date") or today.isoformat()))
        skip = "same-day entry, stop after the close (PDT guard)" if (market_open and entry_d >= today) else None
        # alert only when a stop should be working now (pre-open / session) on an older position;
        # after the close the DAY stops have simply expired and are re-placed for the next session
        live = market_open if expect_live_stops is None else expect_live_stops
        overdue = bool(live and entry_d < today and not skip)
        body = stop_order(sym, qty, sl, protective_stop_cid(sym, session_day, prefix))
        out.append({"sym": sym, "body": body, "sl": sl, "overdue": overdue, "skip": skip})
    return out


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
