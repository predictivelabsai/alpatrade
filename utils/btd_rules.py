"""Buy-the-dip RULES — the single source of truth (v0.50.0).

Every decision the strategy makes lives here as a pure function (no I/O) and is consumed by
ALL execution paths with the SAME params dict (``alpatrade.strategy_configs.params`` resolved by
``utils.live_btd_config.resolve_config``):

* live runner      utils/live_btd_runner.Runner (operator Mag-7 / Semi-7 sleeves, user-live)
* paper            utils/user_live_runner.UserRunner(paper=True) and scripts/run_paper_strategy.py
                   (PaperRunner = the live Runner on paper keys)
* backtest         utils/btd_event_backtest.py (event-driven replay of the runner's schedule)

``tests/test_btd_parity.py`` replays one price history through the backtester AND the real live
Runner against a mocked Alpaca and fails CI on any difference in trades.

Params (percent units as stored in strategy_configs): dip, tp, sl, min_hold, max_hold (calendar
days), pos_frac, max_exposure ($, 0 = off), ref (high20 | prev_close), regime_filter ("" | "SPY,SMH"),
plus the v0.51.0 user-editable keys (stop_mode/stop_k/tp_mult, stop_timing, vol_filter/vol_max,
regime_mode/regime_sma, max_exposure_pct) documented and validated in PARAM_SPEC below.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_SLIPPAGE_BPS = 10.0       # market-ish fills (entries, stops, market exits), both paths
REGIME_LOOKBACK = 5
HIGH_LOOKBACK = 20


# ---------------------------------------------------------------- entry
def dip_signal(last: float, prev_close: float, highs: Iterable[float], P: Dict[str, Any]
               ) -> Tuple[bool, float, float, float]:
    """(signal, dip %, ref, high20). high20 = max high of the last 20 daily bars (incl. today's
    bar so far); dip vs ``ref`` (high20 or prev_close) must be >= P['dip'] %."""
    hs = list(highs)[-HIGH_LOOKBACK:]
    high20 = max(hs or [0])
    ref = prev_close if P.get("ref") == "prev_close" else high20
    dip = (ref - last) / ref * 100 if ref else 0.0
    return dip >= float(P["dip"]), dip, ref, high20


def entry_target(base_value: float, P: Dict[str, Any]) -> float:
    """Notional per new position = equity (or sleeve value) x pos_frac, rounded to the cent."""
    return round(float(base_value) * float(P["pos_frac"]), 2)


def entry_block(notional: float, exposure: float, avail: float, P: Dict[str, Any],
                base_value: Optional[float] = None) -> Optional[str]:
    """Reason a sized entry may not be sent (exposure cap, cash only), else None. ``base_value``
    (the sizing base: equity or sleeve) enables the % cap ``max_exposure_pct`` (v0.51.0)."""
    cap = exposure_cap(P, base_value) if base_value is not None else float(P.get("max_exposure") or 0)
    if cap and exposure + notional > cap:
        return f"would exceed exposure cap ${cap:.0f}"
    if notional > avail:
        return f"notional ${notional:.2f} > available cash ${avail:.2f} (no margin)"
    return None


def regime_symbols(P: Dict[str, Any]) -> List[str]:
    return [x.strip().upper() for x in str(P.get("regime_filter") or "").split(",") if x.strip()]


def regime_block(bars: Dict[str, List[Dict[str, Any]]], last: Dict[str, float], today: date,
                 lookback: int = REGIME_LOOKBACK) -> Optional[str]:
    """Skip new entries when any index trades below its prior N-session low (completed daily
    bars before ``today``). Missing data -> block (fail closed)."""
    for sym, px in last.items():
        prior = [b for b in bars.get(sym, []) if str(b.get("t", ""))[:10] < today.isoformat()][-lookback:]
        if len(prior) < lookback or not px:
            return f"{sym}: no data for the {lookback}-day-low regime check (fail closed)"
        low = min(float(b["l"]) for b in prior)
        if float(px) < low:
            return f"{sym} {float(px):.2f} < {lookback}-day low {low:.2f}"
    return None


# ---------------------------------------------------------------- exits
def exit_prices(entry_price: float, tp_pct: float, sl_pct: float) -> Tuple[float, float]:
    """TP limit rounded UP to the cent (never below the target), stop rounded DOWN."""
    tp = math.ceil(entry_price * (1 + tp_pct / 100.0) * 100 - 1e-6) / 100
    sl = math.floor(entry_price * (1 - sl_pct / 100.0) * 100 + 1e-6) / 100
    return round(tp, 2), round(sl, 2)


def split_qty(qty: Any) -> Tuple[int, float]:
    q = float(qty)
    whole = int(math.floor(q + 1e-9))
    frac = round(q - whole, 9)
    return whole, (frac if frac > 1e-9 else 0.0)


def exit_eligible(entry_date: date, today: date, min_hold_days: int) -> bool:
    """Target (OCO) exits exist only from the first ET date >= min-hold calendar days after the
    buy AND strictly after the buy date (never a same-day round trip)."""
    return entry_date < today and (today - entry_date).days >= max(0, int(min_hold_days))


def stop_active(entry_date: date, session_day: date) -> bool:
    """Protective stop works from the session AFTER the buy (placed post-close; PDT guard),
    every session, also during the min-hold (v0.47.0)."""
    return entry_date < session_day


def time_exit_due(entry_date: date, today: date, max_hold_days: int) -> bool:
    """Max-hold exit at the close window once >= max_hold calendar days old (never same day)."""
    return entry_date < today and (today - entry_date).days >= int(max_hold_days)


def open_exit_action(plpc_pct: Optional[float], P: Dict[str, Any]) -> Optional[str]:
    """At the open event on an exit-eligible day: already beyond TP or SL -> market sell."""
    if plpc_pct is None:
        return None
    if plpc_pct >= float(P["tp"]):
        return "tp"
    if plpc_pct <= -float(P["sl"]):
        return "sl"
    return None


def stop_exemptions(spec: Optional[str], today: date) -> Dict[str, date]:
    """BTD_STOP_EXEMPT="AMD:2026-10-19,INTC:2026-10-19" -> {sym: until} still in force today.
    Exempt: no protective stop, no below-stop sell, no open-event TP/SL; time exit only."""
    out: Dict[str, date] = {}
    for part in (spec or "").replace(";", ",").split(","):
        sym, _, d = part.strip().partition(":")
        try:
            until = date.fromisoformat(d.strip())
        except ValueError:
            continue
        if sym.strip() and today <= until:
            out[sym.strip().upper()] = until
    return out


# ---------------------------------------------------------------- market model (fills)
# Not strategy logic: how the broker fills orders. Shared by the backtester and the mocked
# Alpaca in the parity test so both see the same fills.
def slip_buy(px: float, bps: float = DEFAULT_SLIPPAGE_BPS) -> float:
    return px * (1 + max(0.0, bps) / 10000)


def slip_sell(px: float, bps: float = DEFAULT_SLIPPAGE_BPS) -> float:
    return px * (1 - max(0.0, bps) / 10000)


def stop_fill_at_open(stop: float, open_px: float) -> Optional[float]:
    """Resting sell stop at the opening print: gapped through -> fills at the open."""
    return open_px if open_px <= stop else None


def stop_fill_intraday(stop: float, low: float) -> Optional[float]:
    return stop if low <= stop else None


def limit_fill_intraday(limit: float, high: float) -> Optional[float]:
    return limit if high >= limit else None


def sell_fees(qty: float) -> float:
    """FINRA TAF + CAT on a sell (fractional qty counted as is)."""
    from utils.fees import calculate_cat_fee, calculate_finra_taf_fee
    return float(calculate_finra_taf_fee(qty)) + float(calculate_cat_fee(qty))


def buy_fees(qty: float) -> float:
    from utils.fees import calculate_cat_fee
    return float(calculate_cat_fee(qty))


# ================================================================ v0.51.0: user-editable params
# Every key below is read by the backtester, the paper runner and the live runner through the
# functions in this section, so an edited version behaves the same on all three paths.
#
#   stop_mode     pct (sl/tp %) | atr (stop_k x ATR(14)) | stdev (stop_k x 20-day stdev of returns)
#   tp_mult       atr/stdev only: target = tp_mult x stop distance (0 = keep the fixed tp %)
#   stop_timing   always (stop from the session after the buy) | exit_day (stop only once the
#                 min-hold is met, together with the target)
#   vol_filter    off | atr (skip a symbol when its ATR(14)% > vol_max) | spy_atr (no new entries
#                 when SPY's ATR(14)% > vol_max)
#   regime_filter "" | SPY | SMH | SPY,SMH (no new entries while any is below its reference)
#   regime_mode   low5 (prior 5-session low) | sma (SMA(regime_sma) of prior closes)
#   max_exposure_pct  gross exposure cap as % of the sizing base (equity or sleeve), 0 = off
# All indicators use COMPLETED daily bars before the entry day (no look-ahead), the same bars
# in backtest and live. Missing data fails closed (no entry).

ATR_LOOKBACK = 14
STDEV_LOOKBACK = 20
REGIME_SYMBOLS = ("SPY", "SMH", "QQQ")
MAX_SYMBOLS = 25


class ParamError(ValueError):
    """Validation failed; ``errors`` lists every problem (field -> message)."""

    def __init__(self, errors: Dict[str, str]):
        self.errors = dict(errors)
        super().__init__("; ".join(f"{k}: {v}" for k, v in self.errors.items()))


# key -> spec. Units are the STORED units (percent for dip/tp/sl, fraction for pos_frac).
PARAM_SPEC: Dict[str, Dict[str, Any]] = {
    "symbols": {"type": "symbols", "default": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"],
                "group": "Universe", "label": "Symbols",
                "help": f"Comma-separated tickers the strategy may buy (1-{MAX_SYMBOLS})."},
    "dip": {"type": float, "default": 3.0, "min": 0.5, "max": 25.0, "group": "Entry", "label": "Dip threshold %",
            "help": "Buy when the price is at least this % below the reference."},
    "ref": {"type": str, "default": "high20", "choices": ["high20", "prev_close"], "group": "Entry",
            "label": "Dip reference", "help": "high20 = 20-day high; prev_close = yesterday's close."},
    "pos_frac": {"type": float, "default": 0.10, "min": 0.01, "max": 1.0, "group": "Sizing",
                 "label": "Position size (fraction)", "help": "Each new position = this fraction of equity (or the sleeve). 0.10 = 10%."},
    "max_exposure_pct": {"type": float, "default": 0.0, "min": 0.0, "max": 100.0, "group": "Sizing",
                         "label": "Exposure cap %", "help": "No new buys above this % of equity invested. 0 = off."},
    "max_exposure": {"type": float, "default": 0.0, "min": 0.0, "max": 10_000_000.0, "group": "Sizing",
                     "label": "Exposure cap $", "help": "No new buys above this many dollars invested. 0 = off."},
    "min_hold": {"type": int, "default": 3, "min": 0, "max": 30, "group": "Holding",
                 "label": "Min hold (days)", "help": "Calendar days before the take-profit can fill."},
    "max_hold": {"type": int, "default": 3, "min": 1, "max": 60, "group": "Holding",
                 "label": "Max hold (days)", "help": "Sell at the close once a position is this many calendar days old."},
    "stop_mode": {"type": str, "default": "pct", "choices": ["pct", "atr", "stdev"], "group": "Stop & target",
                  "label": "Stop mode", "help": "pct = fixed %; atr = stop_k x ATR(14); stdev = stop_k x 20-day stdev."},
    "sl": {"type": float, "default": 1.5, "min": 0.1, "max": 50.0, "group": "Stop & target", "label": "Stop loss %",
           "help": "pct mode: stop this % below the entry."},
    "tp": {"type": float, "default": 8.0, "min": 0.1, "max": 100.0, "group": "Stop & target", "label": "Take profit %",
           "help": "Target this % above the entry (atr/stdev mode with tp_mult 0 too)."},
    "stop_k": {"type": float, "default": 2.0, "min": 0.25, "max": 10.0, "group": "Stop & target",
               "label": "Stop multiple (k)", "help": "atr/stdev mode: stop distance = k x ATR(14) or k x stdev."},
    "tp_mult": {"type": float, "default": 0.0, "min": 0.0, "max": 20.0, "group": "Stop & target",
                "label": "Target multiple", "help": "atr/stdev mode: target = this x the stop distance. 0 = use Take profit %."},
    "stop_timing": {"type": str, "default": "always", "choices": ["always", "exit_day"], "group": "Stop & target",
                    "label": "Stop timing", "help": "always = stop from the session after the buy; exit_day = only once the min hold is met."},
    "vol_filter": {"type": str, "default": "off", "choices": ["off", "atr", "spy_atr"], "group": "Filters",
                   "label": "Volatility filter", "help": "atr = skip a symbol whose ATR(14) is above the limit; spy_atr = no buys while SPY's ATR(14) is above it."},
    "vol_max": {"type": float, "default": 4.0, "min": 0.2, "max": 30.0, "group": "Filters",
                "label": "Volatility limit (ATR %)", "help": "ATR(14) as % of the price."},
    "regime_filter": {"type": "regime", "default": "", "group": "Filters", "label": "Regime filter",
                      "choices": ["", "SPY", "SMH", "SPY,SMH"],
                      "help": "No new buys while SPY / SMH trade below their reference. Empty = off."},
    "regime_mode": {"type": str, "default": "low5", "choices": ["low5", "sma"], "group": "Filters",
                    "label": "Regime reference", "help": "low5 = prior 5-day low; sma = moving average below."},
    "regime_sma": {"type": int, "default": 200, "min": 10, "max": 250, "group": "Filters",
                   "label": "Regime SMA (days)", "help": "sma mode: the moving-average length."},
}
EDITABLE_KEYS = tuple(PARAM_SPEC)
PARAM_GROUPS = ("Universe", "Entry", "Sizing", "Holding", "Stop & target", "Filters")


def param_defaults() -> Dict[str, Any]:
    return {k: (list(v["default"]) if isinstance(v["default"], list) else v["default"]) for k, v in PARAM_SPEC.items()}


def _symbols(v: Any) -> List[str]:
    items = v.replace(";", ",").replace(" ", ",").split(",") if isinstance(v, str) else list(v or [])
    out: List[str] = []
    for s in items:
        s = str(s).strip().upper()
        if s and s not in out:
            out.append(s)
    return out


def validate_params(raw: Dict[str, Any], *, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Server-side validation of an editable param set. ``base`` (the current version) fills
    keys ``raw`` omits; code defaults fill the rest. Fractions for dip/tp/sl (0.03) are read as
    percent (3.0) like the user runner does. Unknown keys are kept untouched (execution plumbing
    such as feed / entry_window). Raises ParamError with every problem at once."""
    merged = {**param_defaults(), **(base or {}), **{k: v for k, v in (raw or {}).items() if v is not None}}
    out: Dict[str, Any] = {k: v for k, v in merged.items() if k not in PARAM_SPEC}
    errs: Dict[str, str] = {}
    for k, spec in PARAM_SPEC.items():
        v = merged.get(k)
        t = spec["type"]
        try:
            if t == "symbols":
                syms = _symbols(v)
                bad = [s for s in syms if not all(c.isalnum() or c in ".-" for c in s) or len(s) > 10]
                if not syms:
                    raise ValueError("pick at least one symbol")
                if len(syms) > MAX_SYMBOLS:
                    raise ValueError(f"at most {MAX_SYMBOLS} symbols")
                if bad:
                    raise ValueError(f"not a ticker: {', '.join(bad)}")
                out[k] = syms
            elif t == "regime":
                syms = _symbols(v)
                bad = [s for s in syms if s not in REGIME_SYMBOLS]
                if bad:
                    raise ValueError(f"use {', '.join(REGIME_SYMBOLS)} (got {', '.join(bad)})")
                out[k] = ",".join(syms)
            elif t is str:
                s = str(v).strip().lower() if k != "ref" else str(v).strip()
                if s not in spec["choices"]:
                    raise ValueError(f"one of {', '.join(spec['choices'])}")
                out[k] = s
            else:
                if isinstance(v, bool) or v in ("", None):
                    raise ValueError("a number is required")
                x = float(str(v).replace("%", "").replace("$", "").replace(",", "").strip()) if isinstance(v, str) else float(v)
                if not math.isfinite(x):
                    raise ValueError("a number is required")
                if t is int:
                    if abs(x - round(x)) > 1e-9:
                        raise ValueError("a whole number is required")
                    x = int(round(x))
                if k in ("dip", "tp", "sl") and 0 < x < 0.5:
                    x = round(x * 100, 6)
                if not spec["min"] <= x <= spec["max"]:
                    raise ValueError(f"between {spec['min']:g} and {spec['max']:g}")
                out[k] = x
        except (TypeError, ValueError) as exc:
            errs[k] = str(exc)
    if not errs and out["max_hold"] < out["min_hold"]:
        errs["max_hold"] = "must be at least the min hold"
    if errs:
        raise ParamError(errs)
    return out


def diff_params(old: Dict[str, Any], new: Dict[str, Any]) -> List[Tuple[str, Any, Any]]:
    """[(key, old, new)] for editable keys that changed, in PARAM_SPEC order."""
    out = []
    for k in PARAM_SPEC:
        a, b = (old or {}).get(k, PARAM_SPEC[k]["default"]), (new or {}).get(k, PARAM_SPEC[k]["default"])
        if a != b:
            out.append((k, a, b))
    return out


def _completed(bars: Iterable[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    t = today.isoformat()
    return [b for b in bars if str(b.get("t", ""))[:10] < t]


def atr(bars: List[Dict[str, Any]], n: int = ATR_LOOKBACK) -> Optional[float]:
    """Simple-average true range of the last ``n`` bars (needs n+1 bars)."""
    if len(bars) < n + 1:
        return None
    w = bars[-(n + 1):]
    trs = [max(float(b["h"]) - float(b["l"]), abs(float(b["h"]) - float(a["c"])), abs(float(b["l"]) - float(a["c"])))
           for a, b in zip(w, w[1:])]
    return sum(trs) / n


def ret_stdev(bars: List[Dict[str, Any]], n: int = STDEV_LOOKBACK) -> Optional[float]:
    """Sample stdev of the last ``n`` daily close-to-close returns (needs n+1 bars)."""
    if len(bars) < n + 1:
        return None
    c = [float(b["c"]) for b in bars[-(n + 1):]]
    r = [b / a - 1 for a, b in zip(c, c[1:]) if a]
    if len(r) < 2:
        return None
    mu = sum(r) / len(r)
    return math.sqrt(sum((x - mu) ** 2 for x in r) / (len(r) - 1))


def position_exit_pcts(P: Dict[str, Any], bars: List[Dict[str, Any]], px: float, today: date
                       ) -> Optional[Tuple[float, float]]:
    """(tp %, sl %) fixed for a position at its entry. pct mode -> P's tp/sl; atr/stdev mode ->
    sl = stop_k x ATR(14) / price (or stop_k x stdev), tp = tp_mult x sl (or the fixed tp).
    None = not enough history (the entry is skipped: fail closed)."""
    mode = P.get("stop_mode") or "pct"
    if mode == "pct":
        return float(P["tp"]), float(P["sl"])
    hist = _completed(bars, today)
    k = float(P.get("stop_k") or 2.0)
    if mode == "atr":
        a = atr(hist)
        if a is None or not px:
            return None
        sl = k * a / float(px) * 100
    else:
        s = ret_stdev(hist)
        if s is None:
            return None
        sl = k * s * 100
    sl = round(min(50.0, max(0.1, sl)), 4)
    m = float(P.get("tp_mult") or 0)
    tp = round(m * sl, 4) if m > 0 else float(P["tp"])
    return tp, sl


def pos_pcts(P: Dict[str, Any], meta: Optional[Dict[str, Any]]) -> Tuple[float, float]:
    """The (tp %, sl %) a held position uses: the values fixed at its entry, else P's."""
    m = meta or {}
    return float(m.get("tp_pct") or P["tp"]), float(m.get("sl_pct") or P["sl"])


def atr_pct(bars: List[Dict[str, Any]], today: date) -> Optional[float]:
    hist = _completed(bars, today)
    a = atr(hist)
    return a / float(hist[-1]["c"]) * 100 if a is not None and float(hist[-1]["c"]) else None


def vol_market_block(P: Dict[str, Any], spy_bars: List[Dict[str, Any]], today: date) -> Optional[str]:
    """spy_atr filter: no entries at all while SPY's ATR(14)% > vol_max (missing data -> block)."""
    if (P.get("vol_filter") or "off") != "spy_atr":
        return None
    v = atr_pct(spy_bars or [], today)
    if v is None:
        return "SPY: no data for the volatility filter (fail closed)"
    return f"SPY ATR {v:.2f}% > {float(P['vol_max']):g}%" if v > float(P["vol_max"]) else None


def vol_symbol_block(P: Dict[str, Any], sym_bars: List[Dict[str, Any]], today: date) -> Optional[str]:
    """atr filter: skip this symbol while its ATR(14)% > vol_max (missing data -> skip)."""
    if (P.get("vol_filter") or "off") != "atr":
        return None
    v = atr_pct(sym_bars or [], today)
    if v is None:
        return "no data for the volatility filter (fail closed)"
    return f"ATR {v:.2f}% > {float(P['vol_max']):g}%" if v > float(P["vol_max"]) else None


def regime_check(P: Dict[str, Any], bars: Dict[str, List[Dict[str, Any]]], last: Dict[str, float],
                 today: date) -> Optional[str]:
    """Regime filter per P: low5 (prior 5-session low, == regime_block) or sma (last price below
    the SMA(regime_sma) of prior completed closes). Missing data -> block."""
    if (P.get("regime_mode") or "low5") != "sma":
        return regime_block(bars, last, today)
    n = int(P.get("regime_sma") or 200)
    for sym, px in last.items():
        prior = _completed(bars.get(sym, []), today)[-n:]
        if len(prior) < n or not px:
            return f"{sym}: no data for the SMA({n}) regime check (fail closed)"
        sma = sum(float(b["c"]) for b in prior) / n
        if float(px) < sma:
            return f"{sym} {float(px):.2f} < SMA{n} {sma:.2f}"
    return None


def regime_history_days(P: Dict[str, Any]) -> int:
    """Calendar days of daily bars the regime check needs."""
    if (P.get("regime_mode") or "low5") == "sma":
        return int(int(P.get("regime_sma") or 200) * 1.6) + 10
    return 15


def exposure_cap(P: Dict[str, Any], base_value: float) -> float:
    """Effective $ cap (0 = none): the tighter of max_exposure $ and max_exposure_pct x base."""
    caps = [float(P.get("max_exposure") or 0)]
    pct = float(P.get("max_exposure_pct") or 0)
    if pct:
        caps.append(float(base_value) * pct / 100)
    caps = [c for c in caps if c > 0]
    return min(caps) if caps else 0.0


def stop_live(entry_date: date, session_day: date, P: Dict[str, Any]) -> bool:
    """Is the protective stop working on ``session_day``? always -> from the session after the
    buy (stop_active); exit_day -> only once the min-hold is met (exit_eligible)."""
    if (P.get("stop_timing") or "always") == "exit_day":
        return exit_eligible(entry_date, session_day, int(P.get("min_hold") or 0))
    return stop_active(entry_date, session_day)
