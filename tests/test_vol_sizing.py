"""Unit tests for vol-scaled sizing + ATR exit logic in buy_the_dip (DB-free).

Tests the pure helper functions and the regime-preset wiring without needing
market data or a DB.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import numpy as np

from utils.buy_the_dip import _atr, _realised_vol_annualised
from engine.regime import REGIME_PARAMS, regime_variations


def _ohlc(n=30, start=100.0, vol=0.01):
    rng = np.random.default_rng(42)
    rets = rng.normal(0.001, vol, n)
    close = start * np.cumprod(1 + rets)
    high = close * (1 + rng.uniform(0, 0.005, n))
    low = close * (1 - rng.uniform(0, 0.005, n))
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close}, index=idx)


def test_atr_returns_positive_series():
    df = _ohlc(30)
    atr = _atr(df, period=14)
    assert (atr.dropna() > 0).all()
    assert len(atr) == len(df)


def test_atr_higher_for_volatile_series():
    calm = _ohlc(30, vol=0.002)
    wild = _ohlc(30, vol=0.03)
    assert _atr(wild, 14).iloc[-1] > _atr(calm, 14).iloc[-1]


def test_realised_vol_none_for_short_series():
    assert _realised_vol_annualised(_ohlc(2)) is None


def test_realised_vol_none_for_insufficient_returns():
    # 3 bars → 2 returns → below the min-3 guard
    assert _realised_vol_annualised(_ohlc(3)) is None


def test_realised_vol_positive_and_annualised():
    rv = _realised_vol_annualised(_ohlc(60), lookback=21)
    assert rv is not None and rv > 0
    # Annualised vol for daily 1% stdev ≈ 0.01 * sqrt(252) ≈ 0.159
    assert 0.05 < rv < 0.30


def test_high_vol_regime_preset_has_vol_target_and_atr_exit():
    hv = REGIME_PARAMS["buy_the_dip"]["high_vol"]
    assert "vol_target" in hv and isinstance(hv["vol_target"], (int, float))
    assert "atr_exit_mult" in hv and isinstance(hv["atr_exit_mult"], (int, float))
    assert hv["vol_target"] > 0 and hv["atr_exit_mult"] > 0


def test_low_vol_regime_preset_does_not_force_vol_scaling():
    lv = REGIME_PARAMS["buy_the_dip"]["low_vol"]
    # low_vol uses fixed-fraction sizing by default (no vol_target / atr_exit_mult)
    assert "vol_target" not in lv
    assert "atr_exit_mult" not in lv
