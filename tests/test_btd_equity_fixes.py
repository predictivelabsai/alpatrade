"""utils.buy_the_dip fixes (v0.33.6), DB/network-free:
1. several positions closing on the same bar: capital_after / total_return were inflated because
   positions closed earlier in the bar were counted again at market value;
2. stop-before-target when one daily bar touches both, and 10 bps slippage per side by default."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import inspect
import pandas as pd
import pytest

import utils.buy_the_dip as btd


def _frame(next_high, next_low):
    idx = pd.date_range("2025-03-03", "2025-04-18", freq="B", tz="UTC")
    close = pd.Series(100.0, index=idx)
    entry = pd.Timestamp("2025-04-07", tz="UTC")              # 4% dip -> entry at the close (96)
    close[idx >= entry] = 96.0
    df = pd.DataFrame({"Open": close, "High": close + 0.1, "Low": close - 0.1, "Close": close,
                       "Volume": 1_000_000}, index=idx)
    nxt = pd.Timestamp("2025-04-08", tz="UTC")
    df.loc[nxt, "High"], df.loc[nxt, "Low"] = next_high, next_low
    return df


def _patch(monkeypatch, frames):
    class _MD:
        def __init__(self, *a, **k):
            pass

        def get_historical_data(self, symbol, *a, **k):
            return frames[symbol].copy()
    monkeypatch.setattr(btd, "MarketDataUtil", _MD)


def _run(symbols, **kw):
    args = dict(initial_capital=10_000, position_size=0.1, dip_threshold=0.03, hold_days=10,
                take_profit=0.02, stop_loss=0.01, data_source="yfinance")
    args.update(kw)
    return btd.backtest_buy_the_dip(symbols, datetime(2025, 4, 1), datetime(2025, 4, 18), **args)


def test_same_bar_exits_not_double_counted(monkeypatch):
    # 4 symbols dip together and all hit the target on the next bar
    syms = ["A", "B", "C", "D"]
    _patch(monkeypatch, {s: _frame(99.0, 95.9) for s in syms})
    trades, m, eq = _run(syms, slippage_bps=0)
    first = trades[trades["exit_time"].astype(str).str.startswith("2025-04-08")]
    assert len(first) == 4 and first["TP"].sum() == 4
    true_pnl = trades["pnl"].sum()
    # after the 4 same-bar exits all capital is cash again: capital_after = 10k + their pnl
    assert first["capital_after"].max() == pytest.approx(10_000 + first["pnl"].sum())
    assert m["total_pnl"] == pytest.approx(true_pnl)
    assert m["total_return"] == pytest.approx(true_pnl / 10_000 * 100)
    assert m["total_return"] == pytest.approx((eq["equity"].iloc[-1] / 10_000 - 1) * 100)
    # the old code counted up to 3 already-closed $1k positions again (~+30%)
    assert m["total_return"] < 2.0


def test_stop_before_target_by_default(monkeypatch):
    _patch(monkeypatch, {"A": _frame(99.0, 94.0)})           # bar touches both 97.92 TP and 95.04 SL
    t, m, _ = _run(["A"], slippage_bps=0)
    assert t.iloc[0]["SL"] == 1 and t.iloc[0]["TP"] == 0 and m["total_return"] < 0
    t2, m2, _ = _run(["A"], slippage_bps=0, conservative_execution=False)   # old optimistic order
    assert t2.iloc[0]["TP"] == 1 and m2["total_return"] > 0


def test_default_slippage_10bps_per_side(monkeypatch):
    sig = inspect.signature(btd.backtest_buy_the_dip).parameters
    assert sig["slippage_bps"].default == 10.0 and sig["conservative_execution"].default is True
    _patch(monkeypatch, {"A": _frame(99.0, 95.9)})
    t = _run(["A"])[0].iloc[0]
    assert t["entry_price"] == pytest.approx(96.0 * 1.001)
    assert t["exit_price"] == pytest.approx(96.0 * 1.001 * 1.02 * 0.999)


def test_agent_defaults_realistic():
    src = inspect.getsource(__import__("agents.backtest_agent", fromlist=["x"]))
    assert 'request.get("conservative_execution", True)' in src


def test_stop_fills_at_open_when_gapped_below(monkeypatch):
    f = _frame(96.5, 90.0)
    f.loc[pd.Timestamp("2025-04-08", tz="UTC"), "Open"] = 91.0      # gap far below the 95.04 stop
    _patch(monkeypatch, {"A": f})
    t = _run(["A"], slippage_bps=0).__getitem__(0).iloc[0]
    assert t["SL"] == 1 and t["exit_price"] == pytest.approx(91.0)   # not 95.04
