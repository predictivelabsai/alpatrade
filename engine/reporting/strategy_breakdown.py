"""Per-strategy P&L breakdown for one account (dashboard, live + paper). Read-only.

Attribution of every fill, in order:
  1. ``client_order_id`` prefix owned by a strategy sleeve (``utils.strategy_allocation``:
     entries ``<p>-SYM-YYYYMMDD``, exits ``<p>tp-/sl-/x-/ps-``);
  2. otherwise the symbol universe of a sleeve (universes are disjoint per account);
  3. otherwise **Other**. Nothing is invented: excluded symbols (BNBX, see
     ``engine.reporting.exclusions``) are dropped before attribution.

Figures per strategy for the period:
  * realised P&L = FIFO (per symbol, full fill history) on sells filled in the period;
  * unrealised P&L / open positions = current broker positions in the strategy universe
    (or held by its last attributed buy);
  * return on allocated capital = (realised + unrealised) / sleeve value (allocation, or the
    rest of the account for the primary sleeve);
  * trades = sells (closing fills, per order) in the period; win rate = winners / trades
    with a known cost basis;
  * ``cum`` = cumulative realised P&L by ET date (small chart).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
OTHER = "Other"


def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _s(v: Any) -> str:
    v = getattr(v, "value", v)
    return "" if v is None else str(v)


def _ts(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_fills(rows: Iterable[dict]) -> list[dict]:
    """FILL activities or filled orders → ``{order_id, symbol, side, qty, price, time, cid}``."""
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        qty = _f(r.get("qty") if r.get("price") is not None else r.get("filled_qty"))
        px = _f(r.get("price") if r.get("price") is not None else r.get("filled_avg_price"))
        t = _ts(r.get("transaction_time") or r.get("filled_at"))
        if qty <= 0 or px <= 0 or t is None:
            continue
        out.append({"order_id": _s(r.get("order_id") or r.get("id")),
                    "symbol": _s(r.get("symbol")).upper(), "side": _s(r.get("side")).lower(),
                    "qty": qty, "price": px, "time": t,
                    "cid": _s(r.get("client_order_id"))})
    out.sort(key=lambda x: x["time"])
    return out


def _owner(fill: dict, sleeves: list[dict]) -> str:
    cid = fill.get("cid") or ""
    for s in sleeves:
        if cid and s["sleeve"].owns_cid(cid):
            return s["name"]
    for s in sleeves:
        if fill["symbol"] in {x.upper() for x in s.get("symbols") or []}:
            return s["name"]
    return OTHER


def breakdown(fills: list[dict], positions: list[dict], sleeves: list[dict],
              start: datetime, equity: float, excluded: Iterable[str] = ()) -> list[dict]:
    """Pure: per-strategy rows (sleeves first, then ``Other`` when it has activity)."""
    from utils.strategy_allocation import sleeve_value
    ex = {str(x).upper() for x in excluded}
    allsl = [s["sleeve"] for s in sleeves]
    rows: dict[str, dict] = {}
    for s in sleeves:
        rows[s["name"]] = {"name": s["name"], "display": s.get("display") or s["name"],
                           "prefix": s["sleeve"].cid_prefix, "symbols": list(s.get("symbols") or []),
                           "allocation": s["sleeve"].allocation_usd,
                           "capital": sleeve_value(s["sleeve"], equity or 0.0, allsl)}
    rows[OTHER] = {"name": OTHER, "display": OTHER, "prefix": "", "symbols": [],
                   "allocation": None, "capital": None}
    for r in rows.values():
        r.update(realized=0.0, realized_known=0, unknown_basis=0, trades=0, wins=0,
                 unrealized=0.0, market_value=0.0, positions=[], buys=0, _cum={})
    lots: dict[str, list[list[float]]] = {}
    last_buy_owner: dict[str, str] = {}
    sells: dict[tuple, dict] = {}       # (owner, order_id) → {"pnl", "known", "day"}
    for f in fills:
        sym = f["symbol"]
        if sym in ex:
            continue
        own = _owner(f, sleeves)
        book = lots.setdefault(sym, [])
        if f["side"] == "buy":
            book.append([f["qty"], f["price"]])
            last_buy_owner[sym] = own
            if f["time"] >= start:
                rows[own]["buys"] += 1
            continue
        realised, rem = 0.0, f["qty"]
        while rem > 1e-9 and book:
            lot = book[0]
            take = min(lot[0], rem)
            realised += take * (f["price"] - lot[1])
            lot[0] -= take
            rem -= take
            if lot[0] <= 1e-9:
                book.pop(0)
        if f["time"] < start:
            continue
        key = (own, f["order_id"] or id(f))
        e = sells.setdefault(key, {"pnl": 0.0, "known": True,
                                   "day": f["time"].astimezone(ET).date().isoformat()})
        e["pnl"] += realised
        if rem > 1e-6:
            e["known"] = False
    for (own, _), e in sells.items():
        r = rows[own]
        r["trades"] += 1
        if not e["known"]:
            r["unknown_basis"] += 1
            continue
        r["realized"] += e["pnl"]
        r["realized_known"] += 1
        r["wins"] += 1 if e["pnl"] > 0 else 0
        r["_cum"][e["day"]] = r["_cum"].get(e["day"], 0.0) + e["pnl"]
    for p in positions or []:
        sym = _s(p.get("symbol")).upper()
        if sym in ex:
            continue
        own = next((s["name"] for s in sleeves if sym in {x.upper() for x in s.get("symbols") or []}),
                   last_buy_owner.get(sym, OTHER))
        r = rows[own]
        r["unrealized"] += _f(p.get("unrealized_pl"))
        r["market_value"] += _f(p.get("market_value"))
        r["positions"].append(sym)
    out = []
    for name, r in rows.items():
        if name == OTHER and not (r["trades"] or r["buys"] or r["positions"]):
            continue
        r.pop("_cum")
        r["win_rate"] = (r["wins"] / r["realized_known"] * 100) if r["realized_known"] else None
        r["total_pnl"] = r["realized"] + r["unrealized"]
        cap = r.get("capital")
        r["return_pct"] = (r["total_pnl"] / cap * 100) if cap else None
        out.append(r)
    # cumulative realised by day (recomputed cleanly from the sells map)
    for r in out:
        days: dict[str, float] = {}
        for (own, _), e in sells.items():
            if own == r["name"] and e["known"]:
                days[e["day"]] = days.get(e["day"], 0.0) + e["pnl"]
        run, cum = 0.0, []
        for d in sorted(days):
            run += days[d]
            cum.append([d, round(run, 2)])
        r["cum"] = cum
    return out


# ------------------------------------------------------------------ loaders (I/O)
def _paper_sleeves(user_id: str, refs: Iterable[str]) -> list[dict]:
    from utils.strategy_allocation import Sleeve
    refs = [str(r) for r in refs if r]
    if not refs:
        return []
    try:
        from sqlalchemy import text
        from engine.db.pool import DatabasePool
        with DatabasePool().get_session() as session:
            rows = session.execute(text("""
                SELECT a.cid_prefix, a.allocation_usd, s.name, c.params
                FROM alpatrade.user_strategy_activations a
                JOIN alpatrade.user_strategies s ON s.id = a.user_strategy_id AND s.user_id = a.user_id
                LEFT JOIN alpatrade.user_strategy_configs c ON c.user_strategy_id = a.user_strategy_id
                                                          AND c.user_id = a.user_id
                WHERE a.user_id = CAST(:u AS UUID) AND a.mode = 'paper'
                  AND a.account_ref = ANY(:refs) AND a.status <> 'deactivated'
                  AND a.cid_prefix IS NOT NULL ORDER BY a.id"""),
                {"u": str(user_id), "refs": refs}).all()
    except Exception as exc:  # noqa: BLE001
        log.warning("paper activations unavailable: %s", type(exc).__name__)
        return []
    out = []
    for prefix, alloc, name, params in rows:
        params = params if isinstance(params, dict) else json.loads(params or "{}")
        out.append({"name": f"user:{prefix}", "display": name or prefix,
                    "sleeve": Sleeve(f"user:{prefix}", prefix, None if alloc is None else float(alloc)),
                    "symbols": [str(x).upper() for x in params.get("symbols") or []]})
    return out


def live_sleeves(user_id: str, account_number: str) -> list[dict]:
    from scripts.daily_live_report import live_run, strategy_sleeves, user_sleeves
    own = user_sleeves(user_id, account_number)
    if own is not None:
        return own
    sl = strategy_sleeves(account_number)
    if sl and not sl[0]["symbols"]:
        try:
            run = live_run(user_id, account_number)
            sl[0]["symbols"] = list((run.get("config") or {}).get("symbols") or [])
        except Exception:  # noqa: BLE001
            pass
    return sl


def _cids(orders: Iterable[dict]) -> dict[str, str]:
    return {_s(o.get("id")): _s(o.get("client_order_id")) for o in orders or [] if isinstance(o, dict)}


def for_live(user_id: str, client, account_number: str, positions: list[dict],
             start: datetime, end: datetime, equity: float, excluded: Iterable[str]) -> dict:
    iso = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    hist = client.get_fills(after="2015-01-01T00:00:00Z", until=iso(end), max_pages=50)
    orders, after = [], start - timedelta(days=7)
    for _ in range(10):  # page closed orders (500 each) over the period
        page = client.get_order_history(iso(after), iso(end))
        orders += page
        if len(page) < 500:
            break
        nxt = _ts(page[-1].get("submitted_at"))
        if not nxt or nxt <= after:
            break
        after = nxt
    cids = _cids(orders)
    fills = normalize_fills(hist)
    for f in fills:
        f["cid"] = cids.get(f["order_id"], "")
    sleeves = live_sleeves(user_id, account_number)
    return {"rows": breakdown(fills, positions, sleeves, start, equity, excluded), "ok": True}


def for_paper(user_id: str, client, refs: Iterable[str], positions: list[dict],
              start: datetime, end: datetime, equity: float, excluded: Iterable[str]) -> dict:
    orders = client.get_orders(status="closed", after="2015-01-01T00:00:00Z", limit=500)
    if not isinstance(orders, list):
        return {"rows": [], "ok": False}
    filled = [o for o in orders if _f(o.get("filled_qty")) > 0]
    fills = normalize_fills(filled)
    sleeves = _paper_sleeves(user_id, refs)
    return {"rows": breakdown(fills, positions, sleeves, start, equity, excluded), "ok": True,
            "truncated": len(orders) >= 500}
