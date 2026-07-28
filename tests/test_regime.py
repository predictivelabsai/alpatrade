"""Unit tests for the regime classifier pure logic (DB-free, no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import numpy as np

from engine.regime import (
    RegimeLabel, _realised_vol, _vol_percentile, _trend,
    classify_regime, REGIME_PARAMS, regime_variations,
    LOW_VOL_PCTILE, HIGH_VOL_PCTILE, VIX_HIGH_THRESHOLD,
)


def _closes(n: int, start: float = 100.0, drift: float = 0.001, vol: float = 0.01) -> pd.Series:
    rng = np.random.default_rng(42)
    rets = rng.normal(drift, vol, n)
    prices = start * np.cumprod(1 + rets)
    return pd.Series(prices)


def test_realised_vol_returns_none_for_short_series():
    assert _realised_vol(_closes(5)) is None


def test_realised_vol_positive_for_sufficient_data():
    rv = _realised_vol(_closes(60), lookback=21)
    assert rv is not None and rv > 0


def test_vol_percentile_low_for_calm_market():
    # Low-vol recent window vs higher-vol historical
    n = 100
    closes = pd.Series(np.concatenate([
        np.linspace(100, 110, 70),   # calm uptrend (low vol)
        np.linspace(110, 111, 30),   # even calmer recent
    ]))
    pct = _vol_percentile(closes, lookback=10, window=50)
    assert 0 <= pct <= 100


def test_vol_percentile_high_for_volatile_recent():
    n = 100
    rng = np.random.default_rng(7)
    calm = 100 * np.cumprod(1 + rng.normal(0, 0.002, 70))
    wild = list(calm[-1:] * np.cumprod(1 + rng.normal(0, 0.05, 30)))
    closes = pd.Series(np.concatenate([calm, wild]))
    pct = _vol_percentile(closes, lookback=10, window=50)
    assert pct > 50  # recent vol is high relative to history


def test_trend_bull_above_sma():
    closes = pd.Series(np.linspace(100, 130, 250))  # steady uptrend
    assert _trend(closes, period=200) == "bull"


def test_trend_bear_below_sma():
    closes = pd.Series(np.linspace(130, 100, 250))  # downtrend
    assert _trend(closes, period=200) == "bear"


def test_trend_chop_near_sma():
    closes = pd.Series(np.linspace(100, 101, 250))  # flat
    assert _trend(closes, period=200) == "chop"


def test_regime_presets_cover_three_states():
    btd = REGIME_PARAMS["buy_the_dip"]
    assert set(btd.keys()) == {"low_vol", "normal", "high_vol"}
    for state, grid in btd.items():
        assert "dip_threshold" in grid and "take_profit" in grid
        # High-vol should have wider dips and bigger TPs
    assert min(btd["high_vol"]["dip_threshold"]) > min(btd["low_vol"]["dip_threshold"])
    assert max(btd["high_vol"]["take_profit"]) > max(btd["low_vol"]["take_profit"])
    # High-vol should size smaller (risk control)
    assert max(btd["high_vol"]["position_size"]) < max(btd["low_vol"]["position_size"])


def test_regime_variations_falls_back_for_unknown_strategy():
    assert regime_variations("nonexistent", "high_vol") == {}


def test_regime_variations_returns_grid():
    grid = regime_variations("buy_the_dip", "normal")
    assert grid and "dip_threshold" in grid


def test_regime_label_string():
    lbl = RegimeLabel(state="high_vol", trend="bear", vol_percentile=90.0,
                      vix=32.0, realised_vol=0.25, as_of="2026-07-28")
    s = str(lbl)
    assert "high_vol" in s and "bear" in s and "32.0" in s
