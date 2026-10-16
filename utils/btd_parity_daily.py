"""Daily backtest-vs-live parity check (v0.50.0).

After the post-close event, replay the session that just ended through the parity backtester
(utils/btd_event_backtest, same rules module) starting from the positions the account held at the
open, and compare its decisions with the real Alpaca fills of every strategy on the account:

* entries: symbols bought live vs symbols the backtest buys (near-threshold dips are labelled,
  because the backtest uses the daily close as the 15:45 price)
* exits:   symbols sold live vs sold by the backtest, and the exit kind (stop / target / time)
* prices:  live vs model exit price beyond 0.5 %

Results go to ``alpatrade.btd_parity_daily`` (shown on /admin/metrics) and, when there are
divergences, by email to BTD_ALERT_EMAIL. Read-only against the broker; never places orders.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

import utils.btd_rules as R
from utils import btd_event_backtest as BT

ET = ZoneInfo("America/New_York")
log = logging.getLogger("btd.parity")
DATA_URL = "https://data.alpaca.markets"
_ENTRY = re.compile(r"^([a-z0-9]*btd|u[0-9a-f]{6})-([A-Z.]+)-(\d{8})$")

DDL = """CREATE TABLE IF NOT EXISTS alpatrade.btd_parity_daily (
  id BIGSERIAL PRIMARY KEY, day DATE NOT NULL, account TEXT NOT NULL, strategy TEXT NOT NULL,
  ok BOOLEAN NOT NULL, divergences JSONB NOT NULL DEFAULT '[]'::jsonb, summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (day, account, strategy))"""


def kind_of(o: Dict[str, Any]) -> str:
    t, cid = o.get("type"), str(o.get("client_order_id") or "")
    if t == "stop" or "ps-" in cid or cid.endswith("-sl") or "sl-" in cid:
        return "stop"
    if t == "limit" and not o.get("extended_hours"):
        return "target"
    return "market"            # time exit, at-open TP/SL, below-stop sell


def compare(day: str, P: Dict[str, Any], live_orders: List[Dict[str, Any]], bars: Dict[str, List[Dict[str, Any]]],
            open_positions: Dict[str, Dict[str, Any]], equity: float, cash: float,
            exempt_spec: Optional[str] = None, regime_bars=None) -> Dict[str, Any]:
    """Pure: model the day from the open positions and compare with live fills (this strategy's symbols)."""
    syms = set(P["symbols"])
    filled = [o for o in live_orders if o.get("symbol") in syms and float(o.get("filled_qty") or 0) > 0
              and str(o.get("filled_at") or "")[:10] and _et_day(o.get("filled_at")) == day]
    live_buys = sorted({o["symbol"] for o in filled if o["side"] == "buy"})
    live_sells = {o["symbol"]: kind_of(o) for o in filled if o["side"] == "sell"}
    live_px = {o["symbol"]: float(o.get("filled_avg_price") or 0) for o in filled if o["side"] == "sell"}
    res = BT.run(bars, P, day, day, equity, exempt_spec=exempt_spec, regime_bars=regime_bars,
                 initial_positions=open_positions, initial_cash=cash)
    bt_buys = sorted({t.sym for t in res.trades if t.entry_date == day} |
                     {s for s, p in res.open_positions.items() if p["entry"] == day})
    bt_sells = {t.sym: t for t in res.trades if t.exit_date == day and t.sym in open_positions}
    div = []
    for s in sorted(set(live_buys) ^ set(bt_buys)):
        b = {x["t"][:10]: x for x in bars.get(s, [])}.get(day)
        note = ""
        if b:
            hs = [float(x["h"]) for x in bars[s] if x["t"][:10] <= day][-R.HIGH_LOOKBACK:]
            _, dip, _, _ = R.dip_signal(float(b["c"]), 0.0, hs, P)
            if abs(dip - float(P["dip"])) < 0.3:
                note = f" (dip at close {dip:.2f}% vs {P['dip']}% threshold: 15:45 vs close price)"
        div.append({"type": "entry", "symbol": s, "live": s in live_buys, "backtest": s in bt_buys,
                    "msg": f"{s}: bought {'live only' if s in live_buys else 'in backtest only'}{note}"})
    for s in sorted(set(live_sells) | set(bt_sells)):
        if s not in bt_sells:
            div.append({"type": "exit", "symbol": s, "msg": f"{s}: sold live ({live_sells[s]}) but not in backtest"})
        elif s not in live_sells:
            div.append({"type": "exit", "symbol": s, "msg": f"{s}: backtest exit {bt_sells[s].reason} but no live sell"})
        else:
            mp, lp = float(bt_sells[s].exit_px or 0), live_px.get(s, 0.0)
            if mp and lp and abs(lp / mp - 1) > 0.005:
                div.append({"type": "price", "symbol": s, "msg": f"{s}: live exit {lp:.2f} vs model {mp:.2f} "
                            f"({(lp / mp - 1) * 100:+.2f}%, {live_sells[s]} vs {bt_sells[s].reason})"})
    return {"day": day, "ok": not div, "divergences": div,
            "summary": {"live_buys": live_buys, "bt_buys": bt_buys, "live_sells": live_sells,
                        "bt_sells": {s: t.reason for s, t in bt_sells.items()}, "regime_blocked": res.blocked.get(day)}}


def _et_day(ts) -> str:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(ET).date().isoformat()
    except ValueError:
        return str(ts)[:10]


def gather(get: Callable[..., Any], base: str, day: str, P: Dict[str, Any], tracked: Dict[str, Dict[str, Any]],
           feed: str = "iex") -> Dict[str, Any]:
    """Broker reads (GET only) for ``compare``: the day's orders, bars, open positions at the open."""
    d0 = date.fromisoformat(day)
    after = datetime.combine(d0 - timedelta(days=10), time(0), ET).isoformat()
    until = datetime.now(ET).isoformat()            # through now: reconstruct holdings at D's open
    raw = get(f"{base}/v2/orders", status="closed", after=after, until=until, limit=500, nested="true") or []
    orders = []
    for o in raw:                       # OCO / bracket legs fill inside "legs"
        orders.append(o); orders.extend(o.get("legs") or [])
    syms = list(P["symbols"])
    bars = get(f"{DATA_URL}/v2/stocks/bars", symbols=",".join(syms), timeframe="1Day", feed=feed, limit=10000,
               start=(d0 - timedelta(days=45)).isoformat(), end=day, adjustment="split")["bars"]
    bars = {s: [{"t": b["t"][:10], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"]} for b in v] for s, v in bars.items()}
    positions = {p["symbol"]: p for p in get(f"{base}/v2/positions")}
    since = [o for o in orders if float(o.get("filled_qty") or 0) > 0 and _et_day(o.get("filled_at")) >= day]
    today = since
    held: Dict[str, Dict[str, Any]] = {}
    for s in syms:   # position at D's open = now - buys filled since D + sells filled since D
        q = float((positions.get(s) or {}).get("qty") or 0)
        q -= sum(float(o["filled_qty"]) for o in today if o["symbol"] == s and o["side"] == "buy")
        q += sum(float(o["filled_qty"]) for o in today if o["symbol"] == s and o["side"] == "sell")
        if q <= 1e-9:
            continue
        buys = sorted([o for o in orders if o["symbol"] == s and o["side"] == "buy" and _et_day(o.get("filled_at")) < day
                       and float(o.get("filled_qty") or 0) > 0], key=lambda o: o.get("filled_at") or "")
        entry, avg = None, 0.0
        if buys:     # the lot held at D's open = the last buy filled BEFORE D (state/positions may be a newer lot)
            m = _ENTRY.match(buys[-1].get("client_order_id") or "")
            entry = f"{m.group(3)[:4]}-{m.group(3)[4:6]}-{m.group(3)[6:]}" if m else _et_day(buys[-1]["filled_at"])
            avg = float(buys[-1].get("filled_avg_price") or 0)
        else:
            entry = (tracked.get(s) or {}).get("entry_date")
            avg = float((positions.get(s) or {}).get("avg_entry_price") or 0)
        if entry and avg:
            held[s] = {"qty": q, "avg": avg, "entry": entry}
    return {"orders": orders, "bars": bars, "open_positions": held}


def record(db_url: Optional[str], account: str, strategy: str, out: Dict[str, Any]) -> None:
    if not db_url:
        return
    from sqlalchemy import create_engine, text
    eng = create_engine(db_url, pool_pre_ping=True)
    with eng.begin() as c:
        c.execute(text(DDL))
        c.execute(text("""INSERT INTO alpatrade.btd_parity_daily (day, account, strategy, ok, divergences, summary)
                          VALUES (:d, :a, :s, :ok, CAST(:dv AS jsonb), CAST(:sm AS jsonb))
                          ON CONFLICT (day, account, strategy) DO UPDATE SET ok = EXCLUDED.ok,
                          divergences = EXCLUDED.divergences, summary = EXCLUDED.summary, created_at = now()"""),
                  {"d": out["day"], "a": account, "s": strategy, "ok": out["ok"],
                   "dv": json.dumps(out["divergences"]), "sm": json.dumps(out["summary"], default=str)})


def recent(db_url: Optional[str], limit: int = 30) -> List[Dict[str, Any]]:
    if not db_url:
        return []
    from sqlalchemy import create_engine, text
    try:
        with create_engine(db_url, pool_pre_ping=True).connect() as c:
            rows = c.execute(text("SELECT day, account, strategy, ok, divergences, created_at FROM "
                                  "alpatrade.btd_parity_daily ORDER BY day DESC, strategy LIMIT :n"), {"n": limit}).mappings()
            return [{**dict(r), "day": str(r["day"]), "created_at": str(r["created_at"])} for r in rows]
    except Exception:  # noqa: BLE001  (table not created yet)
        return []


def run_for_runner(runner, cfg, day: Optional[str] = None) -> List[Dict[str, Any]]:
    """Primary strategy + every sleeve on the runner's account. Best-effort; never raises."""
    outs = []
    try:
        day = day or datetime.now(ET).date().isoformat()
        acct = runner.get(f"{runner.base}/v2/account")
        account = acct.get("account_number") or runner.account_no
        st = runner.store(account)
        lr = st.peek() if st else None
        state = (lr.state if lr and lr.ok else None) or {}
        strategies = [(cfg.name or runner.strategy, cfg.params, state.get("positions") or {})]
        try:
            _, extra = runner.load_sleeves(account, cfg.name or runner.strategy)
            for sl, scfg in extra:
                strategies.append((sl.strategy_name, scfg.params,
                                   ((state.get("sleeves") or {}).get(sl.strategy_name) or {}).get("positions") or {}))
        except Exception as exc:  # noqa: BLE001
            log.warning("parity: sleeves unavailable: %s", exc)
        lines = []
        for name, P, tracked in strategies:
            g = gather(runner.get, runner.base, day, P, tracked, P.get("feed", "iex"))
            sleeve_eq = float(acct["equity"])
            out = compare(day, P, g["orders"], g["bars"], g["open_positions"], sleeve_eq, float(acct["cash"]),
                          exempt_spec=os.environ.get("BTD_STOP_EXEMPT"))
            out["strategy"] = name
            outs.append(out)
            record(runner.db_url, account, name, out)
            lines += [f"{name}: {d['msg']}" for d in out["divergences"]]
            log.info("parity %s %s: %s", day, name, "OK" if out["ok"] else f"{len(out['divergences'])} divergence(s)")
        if lines:
            runner.alert(f"backtest/live parity {day} {account}", lines)
    except Exception as exc:  # noqa: BLE001
        log.warning("parity check failed: %s", exc)
    return outs
