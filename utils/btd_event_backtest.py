"""Event-driven buy-the-dip backtester that replays the LIVE runner's schedule (v0.50.0).

Decisions come only from ``utils.btd_rules`` (same params dict as live / paper). Per session:

  09:30 open print   resting protective stops (placed post-close the day before; GTC whole +
                     DAY fraction) fill at the open when it gapped through (stop_fill_at_open)
  09:31 open event   exit-eligible positions (min-hold met): beyond TP/SL at the open -> market;
                     else OCO (TP limit + stop) on whole shares, stop on the fraction
  intraday           stops (low <= stop) first, then TP limits (high >= tp) on whole shares
  15:45 entry        dip signal at the 15:45 price; notional = equity x pos_frac (fractional
                     qty), cash only, exposure cap, regime filter; same-day buys have NO stop
                     until the post-close event (PDT guard)
  15:58 close event  max-hold time exit at market
  16:03 post         stops queued for the next session (DAY fraction expires each session)

Exempt symbols (BTD_STOP_EXEMPT) get no stop / no TP, time exit only. Fills use the shared
market model (slippage on market-ish fills, TAF + CAT fees). ``price_at_entry`` defaults to the
daily close as the 15:45 proxy when no intraday bar is supplied.

Input bars: {sym: [{"t": "YYYY-MM-DD", "o", "h", "l", "c"}, ...]} (sorted, split-adjusted).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Dict, List, Optional

import utils.btd_rules as R


@dataclass
class Trade:
    sym: str
    entry_date: str
    qty: float
    entry_px: float
    notional: float
    exit_date: Optional[str] = None
    exit_px: Optional[float] = None
    reason: str = ""
    pnl: float = 0.0
    sold: float = 0.0
    proceeds: float = 0.0


@dataclass
class Result:
    trades: List[Trade] = field(default_factory=list)
    equity: List[tuple] = field(default_factory=list)       # (date, equity at close)
    blocked: Dict[str, str] = field(default_factory=dict)    # date -> regime/halt reason
    open_positions: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def _d(t) -> str:
    return str(t)[:10]


def run(bars: Dict[str, List[Dict[str, Any]]], P: Dict[str, Any], start: str, end: str,
        capital: float = 10_000.0, *, exempt_spec: Optional[str] = None,
        regime_bars: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        slippage_bps: float = R.DEFAULT_SLIPPAGE_BPS, fees: bool = True,
        price_at_entry: Optional[Callable[[str, str], Optional[float]]] = None,
        halt_daily: float = 0.0, halt_weekly: float = 0.0,
        initial_positions: Optional[Dict[str, Dict[str, Any]]] = None,
        initial_cash: Optional[float] = None,
        vol_bars: Optional[List[Dict[str, Any]]] = None) -> Result:
    """Replay [start, end]. ``halt_daily`` / ``halt_weekly`` are RESEARCH overlays (fractions,
    0 = off): not live rules, only used by scripts/btd_risk_overlay_wf.py."""
    syms = list(P["symbols"])
    by = {s: {_d(b["t"]): b for b in bars.get(s, [])} for s in syms}
    days = sorted({d for s in syms for d in by[s] if start <= d <= end})
    hist = {s: sorted(by[s]) for s in syms}
    rb = {k: [dict(b, t=_d(b["t"])) for b in v] for k, v in (regime_bars or {}).items()}
    vb = [dict(b, t=_d(b["t"])) for b in (vol_bars if vol_bars is not None else rb.get("SPY", []))]
    cash = float(capital if initial_cash is None else initial_cash)
    pos: Dict[str, Dict[str, Any]] = {}
    for s0, p0 in (initial_positions or {}).items():      # {sym: {qty, avg, entry}} (daily parity replay)
        tpp0, slp0 = R.pos_pcts(P, p0)
        tp0, sl0 = R.exit_prices(float(p0["avg"]), tpp0, slp0)
        pos[s0] = {"qty": float(p0["qty"]), "avg": float(p0["avg"]), "entry": str(p0["entry"]), "tp": tp0,
                   "sl": sl0, "oco": False, "tp_pct": tpp0, "sl_pct": slp0}
    last_entry: Dict[str, str] = {}
    res = Result()
    open_tr: Dict[str, Trade] = {s0: Trade(s0, p0["entry"], p0["qty"], p0["avg"], p0["qty"] * p0["avg"])
                                 for s0, p0 in pos.items()}

    def sell(sym, qty, px, d, why, split=False):
        """split=True: the protective stops are two broker orders (GTC whole + DAY fraction),
        so fees are charged per order exactly like the live fills."""
        nonlocal cash
        p = pos[sym]
        w, f = R.split_qty(qty)
        fee = (sum(R.sell_fees(x) for x in (w, f) if x) if split else R.sell_fees(qty)) if fees else 0.0
        cash += qty * px - fee
        t = open_tr[sym]
        t.pnl += qty * (px - p["avg"]) - fee
        p["qty"] = round(p["qty"] - qty, 9)
        t.sold += qty; t.proceeds += qty * px; t.exit_px = t.proceeds / t.sold
        if p["qty"] <= 1e-9:
            t.exit_date, t.reason = d, (t.reason + "+" if t.reason else "") + why
            res.trades.append(t); del open_tr[sym]; del pos[sym]
        else:
            t.reason = (t.reason + "+" if t.reason else "") + why

    for d in days:
        today = date.fromisoformat(d)
        exempt = R.stop_exemptions(exempt_spec, today)
        bar = {s: by[s].get(d) for s in syms}
        # 09:30 open print: resting stops gapped through
        for s in list(pos):
            b = bar.get(s)
            if not b or s in exempt or not R.stop_live(date.fromisoformat(pos[s]["entry"]), today, P):
                continue
            f = R.stop_fill_at_open(pos[s]["sl"], float(b["o"]))
            if f is not None:
                # The broker rejects a stop above the last price: when the FIRST stop session's
                # previous close was already below the stop, nothing rests overnight and the runner
                # sells the whole position with one market order at the open (one order's fees).
                i0 = hist[s].index(d)
                pd = hist[s][i0 - 1] if i0 > 0 else None
                first = pd is not None and not R.stop_live(date.fromisoformat(pos[s]["entry"]), date.fromisoformat(pd), P)
                rested = not (first and float(by[s][pd]["c"]) <= pos[s]["sl"])
                sell(s, pos[s]["qty"], R.slip_sell(f, slippage_bps), d, "SL_gap" if rested else "SL_open", split=rested)
        # 09:31 open event: exit-eligible -> market if beyond TP/SL, else OCO on whole shares
        for s in list(pos):
            b = bar.get(s); p = pos[s]
            p["oco"] = False
            if not b or s in exempt or not R.exit_eligible(date.fromisoformat(p["entry"]), today, P["min_hold"]):
                continue
            act = R.open_exit_action((float(b["o"]) / p["avg"] - 1) * 100, {"tp": p["tp_pct"], "sl": p["sl_pct"]})
            if act:
                sell(s, p["qty"], R.slip_sell(float(b["o"]), slippage_bps), d, f"{act.upper()}_open")
            elif R.split_qty(p["qty"])[0] >= 1:
                p["oco"] = True
        # intraday: stops first (conservative), then TP limit on whole shares
        for s in list(pos):
            b = bar.get(s); p = pos[s]
            if not b or s in exempt or not R.stop_live(date.fromisoformat(p["entry"]), today, P):
                continue
            f = R.stop_fill_intraday(p["sl"], float(b["l"]))
            if f is not None:
                sell(s, p["qty"], R.slip_sell(f, slippage_bps), d, "SL", split=True); continue
            if p.get("oco"):
                f = R.limit_fill_intraday(p["tp"], float(b["h"]))
                if f is not None:
                    sell(s, float(R.split_qty(p["qty"])[0]), f, d, "TP")
        # 15:45 entry
        px_e = {s: (price_at_entry(s, d) if price_at_entry else None) or (float(bar[s]["c"]) if bar.get(s) else None)
                for s in syms}
        block = None
        rsyms = R.regime_symbols(P)
        if rsyms:
            last = {x: next((float(b["c"]) for b in rb.get(x, []) if b["t"] == d), 0.0) for x in rsyms}
            block = R.regime_check(P, rb, last, today)
        if not block:
            block = R.vol_market_block(P, vb, today)
        mv = sum(p["qty"] * (px_e.get(s) or p["avg"]) for s, p in pos.items())
        equity = cash + mv
        if not block and (halt_daily or halt_weekly) and res.equity:
            eqs = [e for _, e in res.equity]
            if halt_daily and equity / eqs[-1] - 1 <= -halt_daily:
                block = "daily loss halt"
            elif halt_weekly and equity / max(eqs[-5:]) - 1 <= -halt_weekly:
                block = "weekly drawdown halt"
        if block:
            res.blocked[d] = block
        else:
            target = R.entry_target(equity, P)
            avail, exposure = cash, mv
            for s in syms:
                b = bar.get(s); px = px_e.get(s)
                if not b or not px:
                    continue
                i = hist[s].index(d)
                prev_close = float(by[s][hist[s][i - 1]]["c"]) if i > 0 else 0.0
                highs = [float(by[s][k]["h"]) for k in hist[s][max(0, i - R.HIGH_LOOKBACK + 1):i + 1]]
                sig, dip, ref, _ = R.dip_signal(px, prev_close, highs, P)
                if not sig or s in pos or last_entry.get(s) == d:
                    continue
                recent = [by[s][k] for k in hist[s][max(0, i - 40):i]]     # completed bars before today
                if R.vol_symbol_block(P, recent, today):
                    continue
                pcts = R.position_exit_pcts(P, recent, px, today)
                if pcts is None or R.entry_block(target, exposure, avail, P, base_value=equity):
                    continue
                fill = R.slip_buy(px, slippage_bps)
                qty = round(target / fill, 9)
                cash -= target + (R.buy_fees(qty) if fees else 0.0)
                avail -= target; exposure += target
                tp, sl = R.exit_prices(fill, *pcts)
                pos[s] = {"qty": qty, "avg": fill, "entry": d, "tp": tp, "sl": sl, "oco": False,
                          "tp_pct": pcts[0], "sl_pct": pcts[1]}
                open_tr[s] = Trade(s, d, qty, fill, target, pnl=-(R.buy_fees(qty) if fees else 0.0))
                last_entry[s] = d
        # 15:58 close event: max-hold time exit
        for s in list(pos):
            b = bar.get(s)
            if b and R.time_exit_due(date.fromisoformat(pos[s]["entry"]), today, P["max_hold"]):
                sell(s, pos[s]["qty"], R.slip_sell(float(b["c"]), slippage_bps), d, "MAX_HOLD")
        mv = sum(p["qty"] * float((bar.get(s) or {"c": p["avg"]})["c"]) for s, p in pos.items())
        res.equity.append((d, cash + mv))
    res.open_positions = {s: dict(p) for s, p in pos.items()}
    return res
