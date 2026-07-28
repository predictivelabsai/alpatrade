"""Market regime classifier — rule-based, provider-neutral.

Single entry point: ``classify_regime(date) -> RegimeLabel``. Deterministic
given the same market data; cached per-day in-process.

Combines three signals into a 3-state label:
  1. **Realised volatility** (21d annualised stdev of daily returns on SPY),
     bucketed into percentiles from a trailing 63d window.
  2. **VIX level** (yfinance ``^VIX`` close) — implied-vol confirmation.
  3. **Trend** — SPY close vs 200-day SMA (bull / chop / bear).

States:
  - ``low_vol``    : realised-vol percentile ≤ 33 AND trend not bear
  - ``normal``     : middle tercile OR mixed signals
  - ``high_vol``   : realised-vol percentile > 67 OR VIX > 30 OR bear trend

This is deliberately lightweight (no HMM dependency). An HMM/GMM can later
replace the internals behind the same ``classify_regime`` interface.

Used by:
  - Phase 2b/2c regime-conditional grid (``BacktestAgent`` / adaptive search)
  - Phase 2d vol-scaled sizing
  - Phase 4 regime-conditional walk-forward and promotion gates
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger("engine.regime")

VOL_LOOKBACK = 21          # 1 trading month
VOL_PERCENTILE_WINDOW = 63 # 3 months
SMA_PERIOD = 200
VIX_HIGH_THRESHOLD = 30.0
BENCHMARK = "SPY"
VIX_SYMBOL = "^VIX"

# Tercile cut points for realised-vol percentile
LOW_VOL_PCTILE = 33
HIGH_VOL_PCTILE = 67


@dataclass(frozen=True)
class RegimeLabel:
    state: str            # "low_vol" | "normal" | "high_vol"
    trend: str            # "bull" | "chop" | "bear"
    vol_percentile: float  # 0-100
    vix: Optional[float]
    realised_vol: Optional[float]  # annualised, decimal
    as_of: str            # ISO date

    def __str__(self) -> str:
        return f"{self.state}/{self.trend} (vol%={self.vol_percentile:.0f}, vix={self.vix})"


def _fetch_history(symbol: str, days: int, end: datetime) -> pd.DataFrame:
    """Fetch `days` of daily OHLC ending at `end` via the shared feed."""
    start = end - timedelta(days=int(days * 1.6))  # buffer for weekends/holidays
    try:
        from engine.feeds.massive import get_historical_data
        df = get_historical_data(symbol, start, end, timeframe="day", interval=1)
        if df is not None and not df.empty:
            return df
    except Exception as e:  # noqa: BLE001
        log.debug("massive feed failed for %s: %s", symbol, e)
    # yfinance fallback (used by the feed internally, but be explicit)
    try:
        import yfinance as yf
        df = yf.download(symbol, start=start, end=end + timedelta(days=1),
                         progress=False, auto_adjust=False)
        if df is not None and not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
    except Exception as e:  # noqa: BLE001
        log.debug("yfinance fallback failed for %s: %s", symbol, e)
    return pd.DataFrame()


def _realised_vol(closes: pd.Series, lookback: int = VOL_LOOKBACK) -> Optional[float]:
    """Annualised realised vol (daily stdev × sqrt(252)) over the last `lookback` returns."""
    if len(closes) < lookback + 1:
        return None
    rets = closes.iloc[-(lookback + 1):].pct_change().dropna()
    if len(rets) < 5:
        return None
    return float(rets.std() * math.sqrt(252))


def _vol_percentile(closes: pd.Series,
                    lookback: int = VOL_LOOKBACK,
                    window: int = VOL_PERCENTILE_WINDOW) -> float:
    """Percentile (0-100) of today's realised vol vs the trailing `window` days."""
    if len(closes) < lookback + window:
        # Not enough history — assume median (50th percentile)
        return 50.0
    rets = closes.pct_change().dropna()
    vols = rets.rolling(lookback).std() * math.sqrt(252)
    vols = vols.dropna()
    if len(vols) < 5:
        return 50.0
    today_vol = vols.iloc[-1]
    historical = vols.iloc[-window:]
    return float((historical < today_vol).sum() / len(historical) * 100)


def _trend(closes: pd.Series, period: int = SMA_PERIOD) -> str:
    """bull if close > SMA200, bear if close < SMA200, chop if within ±2%."""
    if len(closes) < period:
        return "chop"
    sma = closes.iloc[-period:].mean()
    close = closes.iloc[-1]
    pct_diff = (close / sma - 1) * 100
    if pct_diff > 2:
        return "bull"
    if pct_diff < -2:
        return "bear"
    return "chop"


def _vix_close(end: datetime) -> Optional[float]:
    df = _fetch_history(VIX_SYMBOL, 5, end)
    if df.empty:
        return None
    col = "Close" if "Close" in df.columns else df.columns[-1]
    try:
        return float(df[col].iloc[-1])
    except Exception:  # noqa: BLE001
        return None


def classify_regime(date: Optional[datetime] = None) -> RegimeLabel:
    """Classify the market regime as of `date` (defaults to now UTC).

    Pure given the same data + date. Best-effort: on any data failure,
    returns a ``normal/chop`` label so callers degrade gracefully.
    """
    as_of = (date or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    end = date or datetime.now(timezone.utc)

    # Need ~SMA_PERIOD + window of history for a robust percentile
    days_needed = max(SMA_PERIOD, VOL_PERCENTILE_WINDOW) + VOL_LOOKBACK + 20
    df = _fetch_history(BENCHMARK, days_needed, end)
    if df.empty:
        log.warning("regime: no benchmark data for %s — defaulting to normal/chop", as_of)
        return RegimeLabel(state="normal", trend="chop", vol_percentile=50.0,
                           vix=None, realised_vol=None, as_of=as_of)
    close_col = "Close" if "Close" in df.columns else df.columns[-1]
    closes = df[close_col].dropna()
    if closes.empty:
        return RegimeLabel(state="normal", trend="chop", vol_percentile=50.0,
                           vix=None, realised_vol=None, as_of=as_of)

    rv = _realised_vol(closes)
    vp = _vol_percentile(closes)
    trend = _trend(closes)
    vix = _vix_close(end)

    # Decision logic
    if trend == "bear" or (vix is not None and vix > VIX_HIGH_THRESHOLD) or vp > HIGH_VOL_PCTILE:
        state = "high_vol"
    elif vp <= LOW_VOL_PCTILE and trend != "bear":
        state = "low_vol"
    else:
        state = "normal"

    return RegimeLabel(
        state=state, trend=trend, vol_percentile=round(vp, 1),
        vix=round(vix, 2) if vix is not None else None,
        realised_vol=round(rv, 4) if rv is not None else None,
        as_of=as_of,
    )


# Per-process cache: regime doesn't change intraday for our cadence.
@lru_cache(maxsize=8)
def classify_regime_cached(date_key: str) -> RegimeLabel:
    """Cached version — key is a YYYY-MM-DD string."""
    dt = datetime.strptime(date_key, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return classify_regime(dt)


def current_regime() -> RegimeLabel:
    """Convenience: today's regime (cached)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return classify_regime_cached(today)


# --- Parameter presets per regime --------------------------------------------

REGIME_PARAMS = {
    "buy_the_dip": {
        "low_vol": {
            "dip_threshold": [0.03, 0.04, 0.05],
            "take_profit": [0.01, 0.012, 0.015],
            "stop_loss": [0.004, 0.005],
            "hold_days": [1, 2],
            "position_size": [0.10],
        },
        "normal": {
            "dip_threshold": [0.04, 0.05, 0.06],
            "take_profit": [0.012, 0.015, 0.02],
            "stop_loss": [0.005, 0.008],
            "hold_days": [2, 3],
            "position_size": [0.08, 0.10],
        },
        "high_vol": {
            "dip_threshold": [0.06, 0.08, 0.10],
            "take_profit": [0.02, 0.03, 0.04],
            "stop_loss": [0.01, 0.015],
            "hold_days": [3, 5],
            "position_size": [0.05, 0.06],
            # Future: vol_scale_position: true, atr_exit: {mult: [1.5, 2.0, 3.0]}
        },
    },
}


def regime_variations(strategy: str, state: str) -> dict:
    """Return the grid variations for a strategy in a given regime state.

    Falls back to the DEFAULT_VARIATIONS in BacktestAgent if no regime preset.
    """
    return REGIME_PARAMS.get(strategy, {}).get(state, {})
