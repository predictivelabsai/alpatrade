"""Daily-bar momentum-breakout backtest (Qullamaggie-style), cash-only, no look-ahead.

Used by ``scripts/cwt_pipeline.py backtest`` for strategies extracted from Chat With Traders
episodes. Reuses the core engine's friction model (:class:`engine.backtest.fills.Friction`)
and metric definitions (:func:`engine.backtest.metrics.equity_metrics` /
:func:`round_trip_metrics`) so figures are comparable with the Mag-7 BTD walk-forward.

Timing (all decisions use data known at the time):
* Setup is evaluated on the CLOSE of day t-1: prior momentum (return over ``mom_days``
  ≥ ``mom_min``), a tight consolidation (high-low range of the last ``cons_days`` bars
  ≤ ``cons_max_range``), close above its ``trail_ma`` SMA, and the market filter (SPY SMA10 >
  SMA20 on day t-1).
* Entry on day t is a buy-stop at the consolidation high H (daily stand-in for the
  opening-range-high breakout): fill = max(open_t, H) + slippage if high_t ≥ H.
* Initial stop = low of the entry day, capped at ``max_stop_adr`` × ADR(20) below the entry
  ("never risk more than the ADR"), set at the close of day t and active from t+1; a close
  at/below that stop on the entry day exits at the close.
* Stop fills at min(open, stop) − slippage when low ≤ stop (gaps fill at the open).
* After ``partial_days`` sessions, sell ``partial_frac`` at that close if in profit and
  move the stop to break-even. The rest exits at the close when close < SMA(trail_ma).
* Sizing: ``risk_pct`` of equity / stop distance, capped at ``max_pos_pct`` of equity and
  by available cash (no margin, no shorting), at most ``max_positions`` open.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List

import numpy as np
import pandas as pd

from engine.backtest.fills import Friction
from engine.backtest.metrics import equity_metrics, round_trip_metrics


@dataclass
class BreakoutParams:
    mom_days: int = 63
    mom_min: float = 0.30
    cons_days: int = 15
    cons_max_range: float = 0.15
    trail_ma: int = 20
    partial_days: int = 4
    partial_frac: float = 0.33
    max_stop_adr: float = 1.0
    risk_pct: float = 0.01
    max_pos_pct: float = 0.20
    max_positions: int = 10
    min_price: float = 5.0
    market_filter: bool = True
    slippage_bps: float = 10.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Pos:
    sym: str
    entry_date: pd.Timestamp
    entry_px: float
    shares: float
    stop: float
    cost: float
    days: int = 0
    partial_done: bool = False
    realized: float = 0.0
    fees: float = 0.0
    checked: bool = False


def _features(df: pd.DataFrame, p: BreakoutParams) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    c, h, l = df["c"], df["h"], df["l"]
    f["mom"] = c / c.shift(p.mom_days) - 1
    f["hh"] = h.rolling(p.cons_days).max()
    f["ll"] = l.rolling(p.cons_days).min()
    f["rng"] = (f["hh"] - f["ll"]) / f["hh"]
    f["sma"] = c.rolling(p.trail_ma).mean()
    f["adr"] = (h / l - 1).rolling(20).mean()
    # setup known at the close of t-1, traded on day t
    setup = (f["mom"] >= p.mom_min) & (f["rng"] <= p.cons_max_range) & (c > f["sma"]) & (c >= p.min_price)
    f["setup_prev"] = setup.shift(1).fillna(False).astype(bool)
    f["H_prev"] = f["hh"].shift(1)
    f["mom_prev"] = f["mom"].shift(1)
    f["adr_prev"] = f["adr"].shift(1)
    return f


def run(bars: Dict[str, pd.DataFrame], spy: pd.DataFrame, start, end, params: BreakoutParams,
        capital: float = 100_000.0) -> dict:
    p = params
    fr = Friction(slippage_bps=p.slippage_bps)
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    feats = {s: _features(df, p) for s, df in bars.items() if len(df) > p.mom_days + 30}
    spy_c = spy["c"]
    mkt_ok = ((spy_c.rolling(10).mean() > spy_c.rolling(20).mean()).shift(1)
              .reindex(spy.index).fillna(False).astype(bool))
    days = spy.index[(spy.index >= start) & (spy.index <= end)]
    cash, open_pos, trips, curve = capital, {}, [], []

    def close_out(pos: _Pos, px: float, d, frac: float = 1.0, why: str = ""):
        nonlocal cash
        sh = pos.shares * frac
        fill = fr.sell(px)
        fee = sh * px * fr.pct
        cash += sh * fill
        pos.realized += sh * fill
        pos.fees += fee
        pos.shares -= sh
        if pos.shares <= 1e-9:
            pnl = pos.realized - pos.cost
            trips.append({"symbol": pos.sym, "entry_date": str(pos.entry_date.date()),
                          "exit_date": str(d.date()), "entry_px": round(pos.entry_px, 4),
                          "exit_px": round(px, 4), "days": pos.days, "pnl": pnl,
                          "ret": pnl / pos.cost, "fees": pos.fees, "exit": why})
            open_pos.pop(pos.sym, None)

    for d in days:
        # 1) manage open positions on day d
        for sym, pos in list(open_pos.items()):
            df = bars[sym]
            if d not in df.index:
                continue
            b = df.loc[d]
            pos.days += 1
            if b["l"] <= pos.stop:
                close_out(pos, min(float(b["o"]), pos.stop), d, why="stop")
                continue
            sma = feats[sym].at[d, "sma"]
            if not pos.partial_done and pos.days >= p.partial_days:
                pos.partial_done = True
                if b["c"] > pos.entry_px:
                    close_out(pos, float(b["c"]), d, frac=p.partial_frac, why="partial")
                    pos.stop = max(pos.stop, pos.entry_px)
            if sym in open_pos and pos.partial_done and b["c"] < sma:
                close_out(pos, float(b["c"]), d, why=f"close<SMA{p.trail_ma}")
        # 2) new entries (buy-stop at the prior consolidation high)
        equity_open = cash + sum(o.shares * float(bars[o.sym].at[d, "o"]) if d in bars[o.sym].index
                                 else 0 for o in open_pos.values())
        if not p.market_filter or mkt_ok.get(d, False):
            cands = []
            for sym, f in feats.items():
                if sym in open_pos or d not in f.index or not f.at[d, "setup_prev"]:
                    continue
                b = bars[sym].loc[d]
                H = f.at[d, "H_prev"]
                if b["h"] >= H:
                    cands.append((f.at[d, "mom_prev"], sym, max(float(b["o"]), float(H))))
            for _, sym, px in sorted(cands, reverse=True):
                if len(open_pos) >= p.max_positions:
                    break
                fill = fr.buy(px)
                adr = feats[sym].at[d, "adr_prev"] or 0.05
                risk_per_share = max(fill * adr, 1e-6)  # expected stop distance ~ 1 ADR
                value = min(equity_open * p.risk_pct / risk_per_share * fill,
                            equity_open * p.max_pos_pct, cash)
                if value < 100:
                    continue
                sh = value / fill
                cash -= value
                open_pos[sym] = _Pos(sym, d, fill, sh, stop=0.0, cost=value,
                                     fees=sh * px * fr.pct)
                # same-day check happens on the close pass below
            for sym in [s for s, o in open_pos.items() if o.entry_date == d]:
                pos = open_pos[sym]
                b = bars[sym].loc[d]
                pos.checked = True
                adr = feats[sym].at[d, "adr_prev"] or 0.05
                # low of the entry day, but never wider than max_stop_adr x ADR below entry
                pos.stop = max(float(b["l"]), pos.entry_px * (1 - p.max_stop_adr * adr))
                if b["c"] <= pos.stop:  # closed through the stop on the entry day
                    close_out(pos, float(b["c"]), d, why="stop (entry day)")
        mtm = cash + sum(o.shares * float(bars[o.sym]["c"].asof(d)) for o in open_pos.values())
        curve.append((d, mtm, len(open_pos)))
    for pos in list(open_pos.values()):  # mark open positions out at the last close
        close_out(pos, float(bars[pos.sym]["c"].asof(days[-1])), days[-1], why="end of test")
    if curve:  # final point net of the closing costs, so equity and trade P&L reconcile
        curve[-1] = (curve[-1][0], cash, curve[-1][2])
    eq = pd.Series([c[1] for c in curve], index=[c[0] for c in curve])
    spy_eq = spy_c.reindex(eq.index) / spy_c.reindex(eq.index).iloc[0] * capital
    return summarise(eq, spy_eq, trips, curve, p, start, end)


def summarise(eq, spy_eq, trips, curve, p, start, end) -> dict:
    sm, bm, rt = equity_metrics(eq), equity_metrics(spy_eq), round_trip_metrics(trips)
    dr, br = eq.pct_change().dropna(), spy_eq.pct_change().dropna()
    beta = float(np.cov(dr, br)[0, 1] / np.var(br, ddof=1)) if len(br) > 2 else 0.0
    alpha_ann = float(((dr - beta * br).mean()) * 252)
    exposure = float(np.mean([c[2] > 0 for c in curve])) if curve else 0.0
    wins = [t["ret"] for t in trips if t["pnl"] > 0]
    losses = [t["ret"] for t in trips if t["pnl"] <= 0]
    return {
        "period_start": str(eq.index[0].date()), "period_end": str(eq.index[-1].date()),
        "trading_days": sm["trading_days"],
        "total_return_pct": sm["total_return"] * 100, "annualised_pct": sm["annualized_return"] * 100,
        "sharpe": sm["sharpe"], "max_drawdown_pct": sm["max_drawdown"] * 100,
        "spy_return_pct": bm["total_return"] * 100, "spy_annualised_pct": bm["annualized_return"] * 100,
        "spy_sharpe": bm["sharpe"], "spy_max_drawdown_pct": bm["max_drawdown"] * 100,
        "alpha_pct": (sm["total_return"] - bm["total_return"]) * 100,
        "alpha_annualised_pct": (sm["annualized_return"] - bm["annualized_return"]) * 100,
        "capm_alpha_ann_pct": alpha_ann * 100, "beta": beta,
        "trades": rt["trades"], "win_rate_pct": rt["win_rate"] * 100,
        "profit_factor": rt["profit_factor"], "avg_win_pct": float(np.mean(wins) * 100) if wins else 0.0,
        "avg_loss_pct": float(np.mean(losses) * 100) if losses else 0.0,
        "avg_days_held": float(np.mean([t["days"] for t in trips])) if trips else 0.0,
        "exposure_pct": exposure * 100, "fees_paid": rt["fees_paid"],
        "params": p.to_dict(), "equity": eq, "trips": trips,
    }
