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
days), pos_frac, max_exposure ($, 0 = off), ref (high20 | prev_close), regime_filter ("" | "SPY,SMH").
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


def entry_block(notional: float, exposure: float, avail: float, P: Dict[str, Any]) -> Optional[str]:
    """Reason a sized entry may not be sent (exposure cap, cash only), else None."""
    cap = float(P.get("max_exposure") or 0)
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
