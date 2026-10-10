"""Parametrised daily-bar strategy templates for the Chat With Traders pipeline.

Templates (``TEMPLATES``):
* ``breakout``           — momentum + tight consolidation + buy-stop breakout
                           (:mod:`engine.backtest.breakout`, the pilot engine).
* ``dip``                — mean reversion: buy the next open after the close is ``dip`` below
                           the ``ref_days`` high (optionally RSI(2) < ``rsi_max`` and close >
                           SMA``trend_ma``); exit on +``target`` / −``stop`` / close > SMA5 /
                           ``max_hold`` days.
* ``trend_ma``           — trend following: buy the next open after SMA``fast`` crosses above
                           SMA``slow`` (close > SMA``slow``); exit at the first close below
                           SMA``exit_ma`` or an ATR stop.
* ``gap``                — gap continuation: buy at the open when it gaps ≥ ``gap_min`` above
                           the prior close (prior close > SMA50); stop ``stop`` below the open,
                           exit after ``max_hold`` days or on a close below SMA``trail_ma``.
* ``volume_spike``       — unusual-volume momentum (Marsten Parker): after a close-to-close
                           gain ≥ ``ret_min`` on volume ≥ ``vol_mult`` × its 50-day average,
                           out of a non-extended base (prior ``cons_days`` range ≤ ``cons_max``),
                           buy the next open with a +``target`` / −``stop`` bracket and a
                           ``max_hold``-session time stop.
* ``donchian``           — 52-week-high trend following (John Walsh): after a close at a
                           ``high_days`` high in a stock higher than a year ago, buy the next
                           open; initial and trailing stop = lowest low of the prior
                           ``donchian_days`` sessions (only ever raised); size by ``risk_pct``.
* ``trend_template``     — Minervini-style trend template + pivot breakout (Mark Ritchie II):
                           close > SMA50 > SMA150 > SMA200, SMA200 rising, within 25% of the
                           52-week high and ≥ 30% above the low; buy-stop at the prior
                           ``ref_days`` high; ``stop`` below the fill; exit on a close below
                           SMA``trail_ma``; size by ``risk_pct``.
* ``relative_strength``  — rotation: every ``rebalance_days`` (≥ 5, i.e. at most weekly) hold
                           the ``top_n`` strongest names by ``lookback``-day return (close >
                           SMA``trend_ma``), equal weight; cash when SPY < SMA200. Hysteresis:
                           a holding is kept while it still ranks within ``top_n ×
                           hold_buffer`` (default 2×), so names near the cut-off don't churn.

Shared rules: signals use data up to the prior close (gap uses the day's open, known at the
open), fills at the open (or stop / target level) with ``slippage_bps`` per side via
:class:`engine.backtest.fills.Friction`, cash only (no margin, no shorting), one position per
symbol, stop checked before target on the same bar (conservative). Train / test figures are
slices of one full-period equity curve (positions carry over the boundary).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Dict

import numpy as np
import pandas as pd

from engine.backtest.fills import Friction

TEMPLATES = ("breakout", "dip", "trend_ma", "gap", "relative_strength", "volume_spike",
             "donchian", "trend_template")


@dataclass
class RuleParams:
    template: str = "dip"
    # dip
    dip: float = 0.05
    ref_days: int = 20
    rsi_max: float = 0.0          # 0 = no RSI filter
    # trend_ma
    fast: int = 20
    slow: int = 50
    exit_ma: int = 50
    atr_stop: float = 3.0
    # gap
    gap_min: float = 0.04
    # relative strength
    lookback: int = 126
    top_n: int = 10
    rebalance_days: int = 21
    hold_buffer: float = 2.0      # keep a holding while its rank <= top_n * hold_buffer
    # volume_spike
    ret_min: float = 0.04
    vol_mult: float = 2.0
    cons_days: int = 20
    cons_max: float = 0.25
    # donchian
    high_days: int = 252
    donchian_days: int = 20
    # shared
    risk_pct: float = 0.0         # >0: size = risk_pct x equity / stop distance (capped by pos_pct)
    trend_ma: int = 200           # 0 = no trend filter
    trail_ma: int = 0             # 0 = no MA trail
    target: float = 0.0           # 0 = no profit target
    stop: float = 0.0             # 0 = no fixed % stop
    max_hold: int = 0             # 0 = no time stop (sessions)
    sma5_exit: bool = False
    pos_pct: float = 0.10
    max_positions: int = 10
    min_price: float = 5.0
    market_filter: bool = True    # SPY SMA10 > SMA20 (dip: SPY > SMA200)
    slippage_bps: float = 10.0
    include_taf_fees: bool = True  # FINRA TAF on sells (utils.fees, same as buy_the_dip)
    include_cat_fees: bool = True  # CAT fee on buys and sells

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RuleParams":
        names = {f.name: f.type for f in fields(cls)}
        out = {}
        for k, v in (d or {}).items():
            if k in names and v is not None:
                out[k] = v
        p = cls(**out)
        return p.clamped()

    def clamped(self) -> "RuleParams":
        c = lambda v, lo, hi: min(max(v, lo), hi)  # noqa: E731
        self.dip = c(float(self.dip), 0.01, 0.5)
        self.ref_days = int(c(int(self.ref_days), 2, 252))
        self.rsi_max = c(float(self.rsi_max), 0, 50)
        self.fast = int(c(int(self.fast), 2, 100))
        self.slow = int(c(int(self.slow), self.fast + 1, 250))
        self.exit_ma = int(c(int(self.exit_ma), 5, 250))
        self.atr_stop = c(float(self.atr_stop), 0, 10)
        self.gap_min = c(float(self.gap_min), 0.01, 0.5)
        self.lookback = int(c(int(self.lookback), 10, 252))
        self.top_n = int(c(int(self.top_n), 1, 50))
        # daily rotation (1) churned ~10k round trips in 10 years: at most weekly
        self.rebalance_days = int(c(int(self.rebalance_days), 5, 126))
        self.hold_buffer = c(float(self.hold_buffer), 1.0, 5.0)
        self.trend_ma = int(c(int(self.trend_ma), 0, 250))
        self.ret_min = c(float(self.ret_min), 0.01, 0.5)
        self.vol_mult = c(float(self.vol_mult), 1.0, 20.0)
        self.cons_days = int(c(int(self.cons_days), 5, 120))
        self.cons_max = c(float(self.cons_max), 0.02, 1.0)
        self.high_days = int(c(int(self.high_days), 20, 252))
        self.donchian_days = int(c(int(self.donchian_days), 5, 100))
        self.risk_pct = c(float(self.risk_pct), 0.0, 0.05)
        self.trail_ma = int(c(int(self.trail_ma), 0, 250))
        self.target = c(float(self.target), 0, 2.0)
        self.stop = c(float(self.stop), 0, 0.5)
        self.max_hold = int(c(int(self.max_hold), 0, 252))
        self.pos_pct = c(float(self.pos_pct), 0.02, 0.25)
        self.max_positions = int(c(int(self.max_positions), 1, 50))
        self.slippage_bps = c(float(self.slippage_bps), 5, 50)
        return self


def _rsi2(c: pd.Series) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 2, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def _feat(df: pd.DataFrame, p: RuleParams) -> pd.DataFrame:
    c, h, l, o = df["c"], df["h"], df["l"], df["o"]
    f = pd.DataFrame(index=df.index)
    trend_ok = c > c.rolling(p.trend_ma).mean() if p.trend_ma else pd.Series(True, index=df.index)
    ok = (c >= p.min_price) & trend_ok
    if p.template == "dip":
        depth = c / h.rolling(p.ref_days).max() - 1
        sig = ok & (depth <= -p.dip)
        if p.rsi_max:
            sig &= _rsi2(c) < p.rsi_max
        f["score"] = (-depth).shift(1)
        f["sig"] = sig.shift(1)
    elif p.template == "trend_ma":
        fa, sl = c.rolling(p.fast).mean(), c.rolling(p.slow).mean()
        sig = (c >= p.min_price) & (fa > sl) & (fa.shift(1) <= sl.shift(1)) & (c > sl)
        f["score"] = (c / c.shift(p.slow) - 1).shift(1)
        f["sig"] = sig.shift(1)
    elif p.template == "gap":
        prev_ok = ((c >= p.min_price) & (c > c.rolling(50).mean())).shift(1)
        gap = o / c.shift(1) - 1
        f["sig"] = prev_ok & (gap >= p.gap_min)   # known at the open of the day
        f["score"] = gap
    elif p.template == "volume_spike":
        v = df["v"]
        ret1 = c / c.shift(1) - 1
        vavg = v.rolling(50).mean().shift(1)            # average of the 50 sessions BEFORE the day
        base = (h.rolling(p.cons_days).max() / l.rolling(p.cons_days).min() - 1).shift(1)
        sig = (c >= p.min_price) & (ret1 >= p.ret_min) & (v >= p.vol_mult * vavg) & (base <= p.cons_max)
        f["score"] = (v / vavg).shift(1)
        f["sig"] = sig.shift(1)
    elif p.template == "donchian":
        # closing 52-week high in a stock above its close a year ago
        sig = (c >= p.min_price) & (c >= c.rolling(p.high_days).max()) & (c > c.shift(p.high_days))
        f["score"] = (c / c.shift(p.high_days) - 1).shift(1)
        f["sig"] = sig.shift(1)
    elif p.template == "trend_template":
        s50, s150, s200 = c.rolling(50).mean(), c.rolling(150).mean(), c.rolling(200).mean()
        hi, lo = h.rolling(252).max(), l.rolling(252).min()
        tt = ((c >= p.min_price) & (c > s50) & (s50 > s150) & (s150 > s200)
              & (s200 > s200.shift(21)) & (c >= 0.75 * hi) & (c >= 1.30 * lo))
        f["sig"] = tt.shift(1)
        f["lvl"] = h.rolling(p.ref_days).max().shift(1)  # pivot = prior ref_days high (buy-stop)
        f["score"] = (c / c.shift(126) - 1).shift(1)
    f["dlow"] = l.rolling(p.donchian_days).min().shift(1)  # lowest low of the PRIOR N sessions
    f["sig"] = f["sig"].fillna(False).astype(bool)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    f["atr_prev"] = tr.rolling(14).mean().shift(1)
    f["sma5"] = c.rolling(5).mean()
    f["trail"] = c.rolling(p.trail_ma).mean() if p.trail_ma else np.nan
    f["exit_ma"] = c.rolling(p.exit_ma).mean()
    return f


def reg_fee(shares: float, side: str, p) -> float:
    """Regulatory fees per order (utils.fees): TAF on sells, CAT on both sides."""
    from utils.fees import calculate_cat_fee, calculate_finra_taf_fee
    n = int(round(shares))
    f = calculate_cat_fee(n) if getattr(p, "include_cat_fees", False) else 0.0
    if side == "sell" and getattr(p, "include_taf_fees", False):
        f += calculate_finra_taf_fee(n)
    return float(f)


def _buy_cost(value: float, fill: float, cash: float, p) -> tuple[float, float, float]:
    """(shares, gross value, fee) with value + fee <= cash (never negative cash)."""
    fee = reg_fee(value / fill, "buy", p)
    if value + fee > cash:
        value = cash - fee
    return value / fill, value, fee


def _open_mark(df: pd.DataFrame, d) -> float:
    """Mark a holding for sizing decisions taken at the OPEN of day d: today's open, else the last
    known close BEFORE d (never the close of d, which is not known yet; v0.33.6 parity)."""
    if d in df.index:
        return float(df.at[d, "o"])
    prev = df["c"].loc[:d]
    return float(prev.iloc[-1]) if len(prev) else 0.0


def run(bars: Dict[str, pd.DataFrame], spy: pd.DataFrame, start, end, p: RuleParams,
        capital: float = 100_000.0) -> dict:
    if p.template == "relative_strength":
        return run_rotation(bars, spy, start, end, p, capital)
    if p.template == "breakout":
        raise ValueError("use engine.backtest.breakout for the breakout template")
    fr = Friction(slippage_bps=p.slippage_bps)
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    feats = {s: _feat(df, p) for s, df in bars.items() if len(df) > 260}
    spy_c = spy["c"]
    if p.template == "dip":
        mkt = (spy_c > spy_c.rolling(200).mean()).shift(1)
    else:
        mkt = (spy_c.rolling(10).mean() > spy_c.rolling(20).mean()).shift(1)
    mkt = mkt.fillna(False).astype(bool)
    days = spy.index[(spy.index >= start) & (spy.index <= end)]
    cash, pos, trips, curve = capital, {}, [], []

    def sell(sym, px, d, why):
        nonlocal cash
        q = pos.pop(sym)
        fill = fr.sell(px)
        rf = reg_fee(q["sh"], "sell", p)
        cash += q["sh"] * fill - rf
        pnl = q["sh"] * fill - rf - q["cost"]
        trips.append({"symbol": sym, "entry_date": str(q["d"].date()), "exit_date": str(d.date()),
                      "entry_px": round(q["px"], 4), "exit_px": round(px, 4), "days": q["n"],
                      "pnl": pnl, "ret": pnl / q["cost"], "fees": q["sh"] * px * fr.pct * 2 + rf + q.get("rf", 0.0),
                      "exit": why})

    for d in days:
        for sym in list(pos):
            df = bars[sym]
            if d not in df.index:
                continue
            q, b, f = pos[sym], df.loc[d], feats[sym]
            if q["d"] == d:
                continue
            q["n"] += 1
            o, h, l, c = float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"])
            if p.template == "donchian":
                dl = f.at[d, "dlow"]
                if dl == dl:
                    q["stop"] = max(q["stop"], float(dl))  # trailing channel stop, only raised
            if q["stop"] and l <= q["stop"]:
                sell(sym, min(o, q["stop"]), d, "stop"); continue
            if q["tgt"] and h >= q["tgt"]:
                sell(sym, max(o, q["tgt"]), d, "target"); continue
            if p.sma5_exit and c > f.at[d, "sma5"]:
                sell(sym, c, d, "close>SMA5"); continue
            if p.trail_ma and c < f.at[d, "trail"]:
                sell(sym, c, d, f"close<SMA{p.trail_ma}"); continue
            if p.template == "trend_ma" and c < f.at[d, "exit_ma"]:
                sell(sym, c, d, f"close<SMA{p.exit_ma}"); continue
            if p.max_hold and q["n"] >= p.max_hold:
                sell(sym, c, d, "time"); continue
        if (not p.market_filter or mkt.get(d, False)) and len(pos) < p.max_positions:
            eq = cash + sum(q["sh"] * _open_mark(bars[s], d) for s, q in pos.items())
            cands = []
            for sym, f in feats.items():
                if sym in pos or d not in f.index or not f.at[d, "sig"]:
                    continue
                cands.append((f.at[d, "score"], sym))
            for _, sym in sorted(cands, reverse=True):
                if len(pos) >= p.max_positions:
                    break
                b = bars[sym].loc[d]
                px = float(b["o"])
                if p.template == "trend_template":  # buy-stop at the pivot (prior N-day high)
                    lvl = feats[sym].at[d, "lvl"]
                    if not lvl == lvl or float(b["h"]) < lvl:
                        continue
                    px = max(px, float(lvl))
                if px <= 0:
                    continue
                atr = feats[sym].at[d, "atr_prev"]
                stop = px * (1 - p.stop) if p.stop else 0.0
                if p.template == "trend_ma" and p.atr_stop and atr == atr:
                    stop = max(stop, px - p.atr_stop * atr)
                if p.template == "donchian":
                    dl = feats[sym].at[d, "dlow"]
                    if not dl == dl or dl >= px:
                        continue
                    stop = float(dl)
                value = min(eq * p.pos_pct, cash)
                if p.risk_pct and stop:
                    value = min(eq * p.risk_pct / max((px - stop) / px, 1e-4), eq * p.pos_pct, cash)
                if value < 100:
                    continue
                fill = fr.buy(px)
                sh, value, bf = _buy_cost(value, fill, cash, p)
                cash -= value + bf
                pos[sym] = {"d": d, "px": fill, "sh": sh, "cost": value + bf, "rf": bf, "n": 0,
                            "stop": stop, "tgt": px * (1 + p.target) if p.target else 0.0}
                # same-day (entry bar) stop check: the open is the entry, so only the low matters
                if stop and float(b["l"]) <= stop:
                    sell(sym, stop, d, "stop (entry day)")
        curve.append((d, cash + sum(q["sh"] * float(bars[s]["c"].asof(d)) for s, q in pos.items()),
                       len(pos)))
    for sym in list(pos):
        sell(sym, float(bars[sym]["c"].asof(days[-1])), days[-1], "end of test")
    if curve:
        curve[-1] = (curve[-1][0], cash, curve[-1][2])
    return _finish(curve, trips, spy_c, p, capital)


def run_rotation(bars, spy, start, end, p: RuleParams, capital: float = 100_000.0) -> dict:
    fr = Friction(slippage_bps=p.slippage_bps)
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    spy_c = spy["c"]
    risk_on = (spy_c > spy_c.rolling(200).mean()).shift(1).fillna(False).astype(bool)
    close = pd.DataFrame({s: df["c"] for s, df in bars.items()}).reindex(spy.index)
    opn = pd.DataFrame({s: df["o"] for s, df in bars.items()}).reindex(spy.index)
    mom = (close / close.shift(p.lookback) - 1).shift(1)
    ok = ((close > close.rolling(p.trend_ma).mean()) if p.trend_ma else close.notna()).shift(1)
    ok &= (close.shift(1) >= p.min_price)
    days = spy.index[(spy.index >= start) & (spy.index <= end)]
    cash, pos, trips, curve = capital, {}, [], []
    for i, d in enumerate(days):
        if i % p.rebalance_days == 0:
            want = []
            if not p.market_filter or risk_on.get(d, False):
                m = mom.loc[d].where(ok.loc[d].fillna(False).astype(bool)).dropna()
                ranked = list(m.sort_values(ascending=False).index)
                # hysteresis: keep holdings still ranked inside the buffer, fill the rest
                keep_n = max(p.top_n, int(round(p.top_n * p.hold_buffer)))
                keep = [s for s in ranked[:keep_n] if s in pos]
                fresh = [s for s in ranked if s not in pos][:max(0, p.top_n - len(keep))]
                want = keep + fresh
            for sym in [s for s in pos if s not in want]:
                px = opn.at[d, sym]
                px = float(px) if px == px else float(close[sym].asof(d))
                q = pos.pop(sym)
                fill = fr.sell(px)
                rf = reg_fee(q["sh"], "sell", p)
                cash += q["sh"] * fill - rf
                pnl = q["sh"] * fill - rf - q["cost"]
                trips.append({"symbol": sym, "entry_date": str(q["d"].date()), "exit_date": str(d.date()),
                              "entry_px": q["px"], "exit_px": px, "days": i - q["i"], "pnl": pnl,
                              "ret": pnl / q["cost"], "fees": q["sh"] * px * fr.pct * 2 + rf + q.get("rf", 0.0), "exit": "rotation"})
            eq = cash + sum(q["sh"] * _open_mark(bars[s], d) for s, q in pos.items())
            for sym in [s for s in want if s not in pos]:
                px = opn.at[d, sym]
                if not px == px or px <= 0:
                    continue
                value = min(eq / p.top_n, cash)
                if value < 100:
                    continue
                fill = fr.buy(float(px))
                sh, value, bf = _buy_cost(value, fill, cash, p)
                cash -= value + bf
                pos[sym] = {"d": d, "i": i, "px": fill, "sh": sh, "cost": value + bf, "rf": bf}
        curve.append((d, cash + sum(q["sh"] * float(close[s].asof(d)) for s, q in pos.items()), len(pos)))
    for sym, q in list(pos.items()):
        px = float(close[sym].asof(days[-1]))
        fill = fr.sell(px)
        rf = reg_fee(q["sh"], "sell", p)
        cash += q["sh"] * fill - rf
        pnl = q["sh"] * fill - rf - q["cost"]
        trips.append({"symbol": sym, "entry_date": str(q["d"].date()), "exit_date": str(days[-1].date()),
                      "entry_px": q["px"], "exit_px": px, "days": len(days) - q["i"], "pnl": pnl,
                      "ret": pnl / q["cost"], "fees": q["sh"] * px * fr.pct * 2 + rf + q.get("rf", 0.0), "exit": "end of test"})
    if curve:
        curve[-1] = (curve[-1][0], cash, curve[-1][2])
    return _finish(curve, trips, spy_c, p, capital)


def _finish(curve, trips, spy_c, p, capital):
    from engine.backtest.breakout import summarise
    eq = pd.Series([c[1] for c in curve], index=[c[0] for c in curve])
    spy_eq = spy_c.reindex(eq.index) / spy_c.reindex(eq.index).iloc[0] * capital
    return summarise(eq, spy_eq, trips, curve, p, eq.index[0], eq.index[-1])


def slice_metrics(full: dict, spy: pd.DataFrame, start, end, capital: float = 100_000.0) -> dict:
    """Train / test figures as a slice of the full-period equity curve and trades."""
    from engine.backtest.breakout import summarise
    eq = full["equity"]
    eq = eq[(eq.index >= pd.Timestamp(start)) & (eq.index <= pd.Timestamp(end))]
    eq = eq / eq.iloc[0] * capital
    spy_eq = spy["c"].reindex(eq.index) / spy["c"].reindex(eq.index).iloc[0] * capital
    trips = [t for t in full["trips"] if str(start) <= t["exit_date"] <= str(end)]
    curve = [(d, v, 1) for d, v in eq.items()]
    out = summarise(eq, spy_eq, trips, curve, _P(full["params"]), eq.index[0], eq.index[-1])
    out.pop("exposure_pct", None)
    return out


class _P:
    def __init__(self, d):
        self.d = d

    def to_dict(self):
        return self.d
