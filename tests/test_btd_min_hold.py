"""min_hold_days in utils.buy_the_dip: TP/SL may not fire before N calendar days (DB/network-free)."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import inspect
import pandas as pd

import utils.buy_the_dip as btd


def _frame():
    idx = pd.date_range("2025-03-03", "2025-04-18", freq="B", tz="UTC")
    close = pd.Series(100.0, index=idx)
    entry = pd.Timestamp("2025-04-07", tz="UTC")          # Monday: 4% dip -> entry at 96
    close[entry] = 96.0
    close[idx > entry] = 96.0
    df = pd.DataFrame({"Open": close, "High": close + 0.2, "Low": close - 0.2, "Close": close,
                       "Volume": 1_000_000}, index=idx)
    df.loc[pd.Timestamp("2025-04-08", tz="UTC"), "Low"] = 90.0   # day+1: through the 1.5% stop
    return df


class _FakeMD:
    def __init__(self, *a, **k):
        pass

    def get_historical_data(self, symbol, *a, **k):
        return _frame()


def _run(monkeypatch, min_hold):
    monkeypatch.setattr(btd, "MarketDataUtil", _FakeMD)
    res = btd.backtest_buy_the_dip(
        ["TEST"], datetime(2025, 4, 1), datetime(2025, 4, 18), initial_capital=2700,
        position_size=0.1, dip_threshold=0.03, hold_days=10, take_profit=0.08,
        stop_loss=0.015, data_source="yfinance", min_hold_days=min_hold)
    trades = res[0]
    assert trades is not None and len(trades) >= 1
    return trades.iloc[0]


def test_default_min_hold_is_zero_backcompat():
    assert inspect.signature(btd.backtest_buy_the_dip).parameters["min_hold_days"].default == 0


def test_without_min_hold_stop_fires_next_day(monkeypatch):
    t = _run(monkeypatch, 0)
    assert bool(t["hit_stop"])
    assert pd.Timestamp(t["exit_time"]).date().isoformat() == "2025-04-08"


def test_min_hold_blocks_early_stop(monkeypatch):
    t = _run(monkeypatch, 3)
    assert not bool(t["hit_stop"])            # the day+1 plunge is ignored
    assert pd.Timestamp(t["exit_time"]).date() >= pd.Timestamp("2025-04-10").date()
