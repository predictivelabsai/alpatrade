"""Paper signal helper tests — synthetic frames only, no network.

Covers ``utils/paper_signals``: momentum and VIX entry signals, the box &
wedge breakout wrapper over the backtest helpers, and ``fetch_vix_close``
with a stubbed yfinance module.
"""
import importlib
import sys
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest

from utils.paper_signals import (
    box_wedge_entry_signal,
    box_wedge_stop_target,
    fetch_vix_close,
    momentum_entry_signal,
    vix_entry_signal,
)


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------

def test_momentum_signal_flat_market_no_signal():
    df = pd.DataFrame({"Close": [100.0] * 30})
    sig, pct, _ = momentum_entry_signal(df, 20, 5.0)
    assert not sig and pct == 0.0


def test_momentum_signal_triggers_on_gain():
    df = pd.DataFrame({"Close": [100.0] * 20 + [110.0]})
    sig, pct, reason = momentum_entry_signal(df, 20, 5.0)
    assert sig
    assert pct == pytest.approx(10.0)
    assert "10.00%" in reason


def test_momentum_signal_insufficient_history():
    df = pd.DataFrame({"Close": [100.0] * 10})
    assert not momentum_entry_signal(df, 20, 5.0)[0]
    assert not momentum_entry_signal(None, 20, 5.0)[0]
    empty = pd.DataFrame()
    assert not momentum_entry_signal(empty, 20, 5.0)[0]


# ---------------------------------------------------------------------------
# VIX
# ---------------------------------------------------------------------------

def test_vix_signal_threshold_semantics():
    assert vix_entry_signal(22.0, 20.0)[0] is True
    assert vix_entry_signal(20.0, 20.0)[0] is False  # strictly above
    assert vix_entry_signal(18.0, 20.0)[0] is False
    ok, reason = vix_entry_signal(None, 20.0)
    assert not ok and "no vix data" in reason


class _StubTicker:
    def __init__(self, frame):
        self._frame = frame

    def history(self, period=None):
        return self._frame


def _patch_yfinance(monkeypatch, frame):
    stub = ModuleType("yfinance")
    stub.Ticker = lambda symbol: _StubTicker(frame)
    monkeypatch.setitem(sys.modules, "yfinance", stub)


def test_fetch_vix_close_returns_last_close(monkeypatch):
    _patch_yfinance(monkeypatch, pd.DataFrame({"Close": [18.0, 19.5, 21.3]}))
    close, reason = fetch_vix_close()
    assert close == pytest.approx(21.3)
    assert reason == "ok"


def test_fetch_vix_close_failure_modes(monkeypatch):
    # empty frame
    _patch_yfinance(monkeypatch, pd.DataFrame())
    assert fetch_vix_close()[0] is None

    # fetch raises
    class _Boom:
        def __init__(self, symbol):
            pass

        def history(self, period=None):
            raise ConnectionError("down")

    stub = ModuleType("yfinance")
    stub.Ticker = _Boom
    monkeypatch.setitem(sys.modules, "yfinance", stub)
    assert fetch_vix_close()[0] is None


# ---------------------------------------------------------------------------
# Box & wedge
# ---------------------------------------------------------------------------

def _box_wedge_frame(breakout=True):
    """Wide range → tight box → tighter wedge, with an optional breakout bar.

    First 60 bars: 90-110 range. Next 40: 99-101 (contracting box).
    Last 12: 99.6-100.4 (wedge — the 10-bar window ending at the previous
    bar must sit fully inside it). Final bar's high pierces the wedge high.
    """
    n_wide, n_box, n_wedge = 60, 40, 12
    rows = []
    for i in range(n_wide):
        rows.append({"High": 110.0, "Low": 90.0, "Close": 100.0})
    for i in range(n_box):
        rows.append({"High": 101.0, "Low": 99.0, "Close": 100.0})
    for i in range(n_wedge - 1):
        rows.append({"High": 100.4, "Low": 99.6, "Close": 100.0})
    last_high = 102.0 if breakout else 100.3
    rows.append({"High": last_high, "Low": 99.7, "Close": 101.0})
    return pd.DataFrame(rows)


def test_box_wedge_signal_triggers_on_breakout():
    sig, reason, levels = box_wedge_entry_signal(
        _box_wedge_frame(breakout=True), box_lookback=40, wedge_lookback=10,
        contraction_threshold=0.7,
    )
    assert sig and reason == "wedge_breakout"
    assert levels["wedge_low"] == pytest.approx(99.6)
    assert levels["wedge_high"] == pytest.approx(100.4)
    assert levels["box_low"] == pytest.approx(99.0)


def test_box_wedge_signal_waits_without_breakout():
    sig, reason, levels = box_wedge_entry_signal(
        _box_wedge_frame(breakout=False), box_lookback=40, wedge_lookback=10,
        contraction_threshold=0.7,
    )
    assert not sig and reason == "awaiting_breakout"
    assert levels["wedge_low"] == pytest.approx(99.6)


def test_box_wedge_signal_insufficient_history():
    assert box_wedge_entry_signal(pd.DataFrame({"High": [1], "Low": [1],
                                                "Close": [1]}))[0] is False
    assert box_wedge_entry_signal(None)[0] is False


def test_box_wedge_stop_target():
    t15, t3 = box_wedge_stop_target(105.0, 100.0)
    assert t15 == pytest.approx(112.5)   # entry + 1.5R
    assert t3 == pytest.approx(120.0)    # entry + 3R
    # inverted (stop above entry) has no valid targets
    assert box_wedge_stop_target(100.0, 105.0) == (None, None)