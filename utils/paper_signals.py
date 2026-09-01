"""Pure entry-signal helpers for the paper strategies.

These mirror the backtest signal logic (``utils/momentum.py``,
``utils/box_wedge.py``) so paper trading and backtesting agree on what an
entry is. The module is deliberately free of Alpaca/network imports except
:func:`fetch_vix_close` (yfinance only) — everything else takes DataFrames
and scalars so it is unit-testable with synthetic frames.

VIX note: ``^VIX`` is an index, not a tradable symbol — Alpaca's
``StockBarsRequest`` cannot serve it. :func:`fetch_vix_close` therefore
always uses yfinance, a deliberate documented exception to
``MARKET_DATA_PROVIDER``.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple


def momentum_entry_signal(daily_df, lookback_period: int,
                          momentum_threshold: float) -> Tuple[bool, Optional[float], str]:
    """Momentum entry: % gain of the latest close over ``lookback_period`` closes.

    Mirrors ``utils/momentum.py``'s per-bar computation
    (``((close_now - close_lookback) / close_lookback) * 100 >= threshold``).
    Returns ``(signal, momentum_pct, reason)``.
    """
    if daily_df is None or getattr(daily_df, "empty", True):
        return False, None, "no_data"
    if len(daily_df) <= lookback_period or lookback_period < 1:
        return False, None, "insufficient_history"
    try:
        lookback_start_price = float(daily_df["Close"].iloc[-1 - lookback_period])
        current_price = float(daily_df["Close"].iloc[-1])
    except (KeyError, IndexError, TypeError, ValueError):
        return False, None, "bad_frame"
    if lookback_start_price <= 0:
        return False, None, "bad_frame"
    momentum_pct = ((current_price - lookback_start_price) / lookback_start_price) * 100
    if momentum_pct >= momentum_threshold:
        return True, momentum_pct, f"+{momentum_pct:.2f}% over {lookback_period}d"
    return False, momentum_pct, ""


def fetch_vix_close() -> Tuple[Optional[float], str]:
    """Latest available VIX close, always via yfinance.

    ``^VIX`` is an index — Alpaca cannot serve it, so this ignores
    ``MARKET_DATA_PROVIDER`` on purpose. Returns ``(close, reason)``;
    ``close is None`` on any failure (caller should skip, never crash).
    """
    try:
        import yfinance as yf

        hist = yf.Ticker("^VIX").history(period="5d")
    except Exception as exc:  # network/API errors must not kill a session
        return None, f"vix_fetch_error: {exc}"
    if hist is None or getattr(hist, "empty", True) or "Close" not in hist:
        return None, "vix_no_data"
    series = hist["Close"].dropna()
    if series.empty:
        return None, "vix_no_data"
    close = float(series.iloc[-1])
    if close <= 0:
        return None, "vix_bad_value"
    return close, "ok"


def vix_entry_signal(vix_close: Optional[float], vix_threshold: float) -> Tuple[bool, str]:
    """VIX fear entry: the index closed above ``vix_threshold`` (points)."""
    if vix_close is None:
        return False, "no vix data"
    if vix_close > vix_threshold:
        return True, f"VIX {vix_close:.1f} > {vix_threshold:g}"
    return False, f"VIX {vix_close:.1f} <= {vix_threshold:g}"


def box_wedge_entry_signal(intraday_df, box_lookback: int = 100, wedge_lookback: int = 20,
                           contraction_threshold: float = 0.7) -> Tuple[bool, str, Dict]:
    """Box & wedge breakout entry on the latest bar of a 5-minute frame.

    Wraps the ``utils/box_wedge.py`` helpers: bullish SMA200 regime →
    contracting box → tighter wedge → latest bar's high broke above
    ``wedge_high``. The wedge is measured on the window ending at the
    previous bar — a window that includes the breakout bar itself makes
    ``current_high > wedge_high`` impossible (this also silently disables
    the backtest loop, fixed alongside). Returns
    ``(signal, reason, levels)`` where ``levels`` carries the box/wedge
    geometry (and ``wedge_low`` — the stop — on a signal).
    """
    from utils.box_wedge import (
        calculate_indicators,
        find_box_contraction,
        find_wedge_within_box,
        is_bullish_regime,
    )

    levels: Dict[str, float] = {}
    if intraday_df is None or getattr(intraday_df, "empty", True):
        return False, "no_data", levels
    if len(intraday_df) < box_lookback + 2 or box_lookback < 2:
        return False, "insufficient_history", levels
    df = calculate_indicators(intraday_df.copy())
    i = len(df) - 1
    if not is_bullish_regime(df, i):
        return False, "bearish_regime", levels
    contracting, box_high, box_low = find_box_contraction(
        df, i, box_lookback, contraction_threshold
    )
    if not contracting:
        return False, "no_box_contraction", levels
    # Wedge on the window ending at the previous bar, so the breakout bar's
    # own high cannot satisfy (and thereby veto) its own breakout condition.
    has_wedge, wedge_high, wedge_low = find_wedge_within_box(
        df, i - 1, box_high, box_low, wedge_lookback
    )
    if not has_wedge:
        return False, "no_wedge", levels
    levels = {"box_high": float(box_high), "box_low": float(box_low),
              "wedge_high": float(wedge_high), "wedge_low": float(wedge_low)}
    try:
        current_high = float(df["High"].iloc[i])
    except (TypeError, ValueError):
        return False, "bad_frame", levels
    if current_high <= wedge_high:
        return False, "awaiting_breakout", levels
    return True, "wedge_breakout", levels


def box_wedge_stop_target(entry_price: float, stop_price: float) -> Tuple[Optional[float], Optional[float]]:
    """R-multiple targets from the wedge-low stop: ``(target_1_5r, target_3r)``."""
    r_value = float(entry_price) - float(stop_price)
    if r_value <= 0:
        return None, None
    return (entry_price + 1.5 * r_value, entry_price + 3.0 * r_value)