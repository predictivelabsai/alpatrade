"""External cash flows (deposits / withdrawals) for P&L.

Equity differences include money moved in or out of the account; that is not profit.
Every equity-based P&L figure (day, MTD, YTD, since live start) is therefore

    P&L = (equity_end - equity_base) - net_deposits(base_date, end_date]

and net deposits are shown separately. Cash-flow activities on Alpaca's trading API:
CSD (cash deposit, incl. ACH / instant ACH), CSW (cash withdrawal), JNLC (cash journal
between accounts). Their ``net_amount`` is signed (+ in / - out); ``date`` is the ET
trade date the flow is booked on. A flow dated on the baseline date itself is already in
the baseline equity (end-of-day points), so the window is (base_date, end_date].

Percent return = P&L / (equity_base + max(0, net_deposits)), i.e. new money counts as
capital at risk and a deposit can never inflate the return.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterable, Optional

log = logging.getLogger(__name__)

CASH_FLOW_TYPES = ("CSD", "CSW", "JNLC")


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _day(a: dict) -> Optional[date]:
    raw = str(a.get("date") or a.get("transaction_time") or "")[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def flow_rows(activities: Iterable[dict]) -> list[dict]:
    """Normalise activities to [{date, amount, type, description}] (cash flows only)."""
    out = []
    for a in activities or []:
        if str(a.get("activity_type") or "").upper() not in CASH_FLOW_TYPES:
            continue
        if str(a.get("status") or "executed").lower() in ("canceled", "cancelled", "rejected"):
            continue
        d = _day(a)
        if d is None:
            continue
        out.append({"date": d, "amount": _num(a.get("net_amount")),
                    "type": str(a.get("activity_type")).upper(),
                    "description": str(a.get("description") or "")})
    return out


def net_flows(rows: Iterable[dict], after: Optional[date], through: date) -> float:
    """Sum of flows booked in (after, through]; after=None -> everything up to through."""
    return round(sum(r["amount"] for r in rows or []
                     if (after is None or r["date"] > after) and r["date"] <= through), 2)


def prev_weekday(d: date) -> date:
    """Previous Mon-Fri date (the prior close a day P&L is measured against; holidays ignored,
    a flow on a holiday is then simply attributed to the next session)."""
    from datetime import timedelta
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def adjust_day(summary: dict, rows: Optional[list], today: date) -> dict:
    """Day P&L (equity - last_equity) net of flows booked since the prior close."""
    out = dict(summary or {})
    if rows is None:
        out["cash_flows_ok"] = False
        return out
    dep = net_flows(rows, prev_weekday(today), today)
    pnl, pct = adjusted_pnl(out.get("equity"), out.get("last_equity"), dep)
    if pnl is not None:
        out["day_pl"], out["day_pl_pct"] = pnl, pct
    out["day_net_deposits"] = dep
    out["cash_flows_ok"] = True
    return out


def adjusted_pnl(equity_end: Optional[float], equity_base: Optional[float],
                 deposits: float = 0.0) -> tuple[Optional[float], Optional[float]]:
    """(P&L $, P&L %) net of external cash flows."""
    if equity_end is None or not equity_base:
        return None, None
    pnl = float(equity_end) - float(equity_base) - float(deposits or 0)
    denom = float(equity_base) + max(0.0, float(deposits or 0))
    return pnl, (pnl / denom * 100 if denom else None)


def fetch_flows(client: Any, since: date) -> Optional[list[dict]]:
    """Cash-flow rows since ``since`` via the client's ``get_cash_flows``; None if unavailable."""
    try:
        fn = getattr(client, "get_cash_flow_activities", None) or client.get_cash_flows
        return flow_rows(fn(after=since.isoformat()))
    except Exception as exc:  # noqa: BLE001
        log.warning("cash-flow activities unavailable: %s", type(exc).__name__)
        return None


def twr_pct(start: date, start_eq: float, points: Iterable, rows: Optional[list]) -> tuple[float, float]:
    """(time-weighted return %, net deposits) from ascending [(day, equity)] session closes
    after ``start`` (whose close is ``start_eq``). Each segment's return is
    (E_k - flows in (prev_day, k]) / E_prev - 1, i.e. a flow is booked at the end of its day,
    so a deposit is never performance and never dilutes the return."""
    growth, prev_eq, prev_day, dep = 1.0, float(start_eq), start, 0.0
    for d, e in points:
        if d <= start:
            continue
        f = net_flows(rows or [], prev_day, d)
        if prev_eq > 0:
            growth *= (float(e) - f) / prev_eq
        prev_eq, prev_day, dep = float(e), d, dep + f
    return (growth - 1) * 100, round(dep, 2)
