"""Valuation contract tests with fake fundamentals, prices, broker and storage."""
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from engine.feeds.fundamentals import CachedFundamentals, daily_valuation
from utils.strategy_slug import build_slug, parse_slug
from utils.valuation import backtest_valuation, select_symbols


@pytest.fixture(autouse=True)
def no_external_access(monkeypatch):
    import requests
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("External access is forbidden in valuation unit tests")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def earnings(eps=None):
    periods = pd.date_range("2022-03-31", periods=8, freq="QE")
    return {"Earnings": {"History": {
        str(period.date()): {"date": str(period.date()),
                            "reportDate": str((period + pd.Timedelta(days=30)).date()),
                            "epsActual": (eps or [1] * 4 + [2] * 4)[i]}
        for i, period in enumerate(periods)
    }}}


def test_report_date_lag_and_trailing_peg():
    close = pd.Series(80.0, index=pd.to_datetime(["2023-12-31", "2024-01-30", "2024-01-31"]))
    result = daily_valuation(earnings(), close)
    assert result.iloc[0].ttm_eps == 7  # Q4 actual is not yet published
    assert result.iloc[1].ttm_eps == 7  # publication day is conservatively excluded
    assert result.iloc[2].ttm_eps == 8
    assert result.iloc[2].pe == 10
    assert result.iloc[2].growth_pct == 100
    assert result.iloc[2].peg == 0.1


@pytest.mark.parametrize("eps", [[-1] * 8, [0] * 8])
def test_nonpositive_eps_excludes_pe_and_peg(eps):
    close = pd.Series([20], index=pd.to_datetime(["2024-02-01"]))
    row = daily_valuation(earnings(eps), close).iloc[0]
    assert pd.isna(row.pe) and pd.isna(row.peg)


def test_missing_report_dates_and_quarters_never_use_period_end():
    payload = earnings()
    for item in payload["Earnings"]["History"].values():
        item.pop("reportDate")
    with pytest.raises(ValueError, match="publication dates"):
        daily_valuation(payload, pd.Series([40], index=pd.to_datetime(["2024-02-01"])))
    payload = earnings()
    del payload["Earnings"]["History"]["2023-09-30"]
    result = daily_valuation(payload, pd.Series([40], index=pd.to_datetime(["2024-02-01"])))
    assert pd.isna(result.iloc[0].pe)


@pytest.mark.parametrize("mode, expected", [
    ("low_pe", ["A", "B"]), ("high_pe", ["D", "C"]),
    ("below_median", ["A", "B"]), ("peg_under_1", ["B", "D"]),
])
def test_each_mode(mode, expected):
    values = {"A": {"pe": 5, "peg": -0.5}, "B": {"pe": 10, "peg": 0.5},
              "C": {"pe": 20, "peg": 1}, "D": {"pe": 30, "peg": 0.99},
              "LOSS": {"pe": float("nan"), "peg": 0.1}}
    assert select_symbols(values, mode, 2) == expected


def frames(dates=None):
    dates = pd.to_datetime(dates or ["2024-02-01", "2024-02-02", "2024-02-05", "2024-02-06"])
    prices = {s: pd.DataFrame({"Open": [100, 110, 120, 130], "Close": [90, 100, 110, 120]}, index=dates)
              for s in ("A", "B")}
    values = {s: pd.DataFrame({"pe": pe, "peg": 0.5}, index=dates)
              for s, pe in (("A", 10), ("B", 20))}
    return prices, values


def run(prices=None, values=None, **params):
    if prices is None:
        prices, values = frames()
    return backtest_valuation(prices, values, prices["A"].index[0].to_pydatetime(),
                              prices["A"].index[-1].to_pydatetime(), **params)


def test_next_open_entry_exit_and_costs():
    trades, metrics = run(top_n=1, slippage_bps=10, include_taf_fees=True, include_cat_fees=True)
    trade = trades.iloc[0]
    assert trade.ticker == "A"
    assert trade.signal_time == pd.Timestamp("2024-02-01")
    assert trade.entry_time == pd.Timestamp("2024-02-02")
    assert trade.entry_price == pytest.approx(110 * 1.001)
    assert trade.exit_price == pytest.approx(130 * 0.999)
    assert trade.exit_signal_time < trade.exit_time
    assert trade.total_fees > 0
    assert metrics["total_pnl"] == pytest.approx(trade.pnl)
    assert trade.capital_after == pytest.approx(10000 + trade.pnl)


def test_equal_allocation_and_no_overlapping_capital():
    trades, metrics = run(top_n=2, slippage_bps=0)
    assert len(trades) == 2
    assert list(trades.shares * trades.entry_price) == pytest.approx([5000, 5000])
    assert metrics["total_pnl"] == pytest.approx(trades.pnl.sum())
    assert metrics["equity_curve"][-1]["equity"] == pytest.approx(10000 + trades.pnl.sum())


def test_stop_is_close_signal_filled_at_following_open():
    prices, values = frames()
    prices["A"].loc["2024-02-02", "Close"] = 50
    trades, _ = run(prices, values, top_n=1, stop_loss=0.05, slippage_bps=0)
    assert trades.iloc[0].exit_time == pd.Timestamp("2024-02-05")
    assert trades.iloc[0].exit_price == 120
    assert trades.iloc[0].reason == "stop_loss"


@pytest.mark.parametrize("frequency, count", [("monthly", 3), ("quarterly", 2)])
def test_periodic_rebalance(frequency, count):
    dates = ["2024-02-28", "2024-02-29", "2024-03-01", "2024-03-04", "2024-04-01", "2024-04-02", "2024-04-03"]
    index = pd.to_datetime(dates)
    prices = {"A": pd.DataFrame({"Open": 100.0, "Close": 100.0}, index=index)}
    values = {"A": pd.DataFrame({"pe": 10.0, "peg": 0.1}, index=index)}
    trades, _ = run(prices, values, rebalance=frequency)
    assert len(trades) == count
    assert all(trades.signal_time < trades.entry_time)
    assert all(trades.exit_signal_time < trades.exit_time)


def test_missing_price_bar_fails_instead_of_inventing_fill():
    prices, values = frames()
    prices["B"] = prices["B"].iloc[1:]
    with pytest.raises(ValueError, match="sessions do not align"):
        run(prices, values)


def test_empty_eligible_basket_retains_cash():
    prices, values = frames()
    for frame in values.values():
        frame["pe"] = float("nan")
    trades, metrics = run(prices, values)
    assert trades.empty and metrics["total_return"] == 0


@pytest.mark.parametrize("mode", ["low_pe", "high_pe", "below_median", "peg_under_1"])
def test_slug_roundtrip(mode):
    params = {"mode": mode, "top_n": 2, "rebalance": "quarterly", "stop_loss": 0.005}
    slug = build_slug("valuation", params, "12m")
    assert slug.startswith("val-")
    assert parse_slug(slug) == {"strategy": "valuation", "params": params, "lookback": "12m"}


def test_cache_ttl_and_missing_credentials(tmp_path, monkeypatch):
    calls = []
    provider = SimpleNamespace(get_fundamentals=lambda symbol: calls.append(symbol) or earnings())
    cached = CachedFundamentals(provider, tmp_path, ttl_seconds=60)
    assert cached.get_fundamentals("A") == cached.get_fundamentals("A")
    assert calls == ["A"]
    cached.ttl_seconds = 0
    cached.get_fundamentals("A")
    assert calls == ["A", "A"]
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    with pytest.raises(ValueError, match="EODHD_API_KEY"):
        CachedFundamentals(cache_dir=tmp_path)


def test_provider_error_does_not_expose_token(monkeypatch):
    import requests
    from engine.feeds.eodhd import EODHD_API

    def broken(*args, **kwargs):
        raise requests.RequestException("url?api_token=sensitive-test-value")

    monkeypatch.setattr(requests, "get", broken)
    with pytest.raises(RuntimeError, match="fundamentals unavailable") as exc:
        EODHD_API(api_key="unit-test").get_fundamentals("AAPL")
    assert "sensitive-test-value" not in str(exc.value)


@pytest.mark.asyncio
async def test_cli_parsing_forwards_valuation_params(monkeypatch):
    from tui.command_processor import CommandProcessor

    captured = []
    processor = CommandProcessor.__new__(CommandProcessor)
    processor.app = SimpleNamespace()
    processor.user_id = None
    processor.default_capital = 10000
    processor.default_symbols = ["AAPL"]
    monkeypatch.setattr(processor, "_new_orchestrator", lambda: SimpleNamespace(
        run_backtest=lambda cfg: captured.append(cfg) or {"error": "test-complete"}))
    command = "strategy:valuation mode:low_pe symbols:AAPL,MSFT lookback:12m top_n:2 rebalance:quarterly stop_loss:0.05"
    params = processor._parse_kv_params(command.split())
    await processor._agent_backtest(params)
    assert captured[0]["strategy"] == "valuation"
    assert captured[0]["lookback"] == "12m"
    assert captured[0]["params"] == {"mode": "low_pe", "top_n": 2, "rebalance": "quarterly", "stop_loss": 0.05}


def test_agent_grid_and_storage_handoff(monkeypatch):
    from agents.backtest_agent import BacktestAgent
    import agents.backtest_agent as module
    import utils.valuation as valuation

    prices, values = frames()
    monkeypatch.setattr(valuation, "load_valuation_data", lambda *args: (prices, values))
    monkeypatch.setattr(module, "_benchmark_return", lambda *args: 1.5)
    stored = []
    monkeypatch.setattr(module, "store_backtest_results", lambda *args, **kw: stored.append((args, kw)))
    agent = BacktestAgent(user_id="owner", account_id="account")
    result = agent.run({"strategy": "valuation", "symbols": ["A", "B"], "lookback": "12m",
                        "params": {"top_n": 1}, "variations": {"mode": ["low_pe", "high_pe"]}})
    assert result["total_variations"] == 2
    assert len(stored[0][0][2]) == 2
    assert stored[0][0][3]  # trades handed to existing storage
    assert stored[0][1] == {"strategy": "valuation", "lookback": "12m", "user_id": "owner", "account_id": "account"}
    assert result["best_config"]["benchmark"]["total_return"] == 1.5


def test_paper_refusal_and_no_deploy_cta(monkeypatch):
    from agents.paper_trade_agent import PaperTradeAgent
    from engine.web.onboarding import paper_deploy_command

    agent = PaperTradeAgent.__new__(PaperTradeAgent)
    agent.session_id = "test"
    result = agent.run({"strategy": "val"})
    assert "backtest only" in result["error"]
    assert paper_deploy_command({"strategy": "valuation", "params": {"mode": "low_pe"}}) is None

@pytest.mark.parametrize("stop", [0, 0.123456789, 1e-8])
def test_slug_keeps_stop_precision(stop):
    params = {"mode": "low_pe", "top_n": 3, "rebalance": "monthly", "stop_loss": stop}
    assert parse_slug(build_slug("valuation", params))["params"] == params


@pytest.mark.parametrize("growth_eps", [[2] * 4 + [1] * 4, [1] * 8])
def test_peg_excludes_flat_or_negative_growth(growth_eps):
    row = daily_valuation(earnings(growth_eps), pd.Series(
        [80], index=pd.to_datetime(["2024-02-01"]))).iloc[0]
    assert row.pe > 0
    assert pd.isna(row.peg)


def test_future_actual_does_not_change_earlier_valuation():
    payload = earnings()
    close = pd.Series([80], index=pd.to_datetime(["2024-01-30"]))
    before = daily_valuation(payload, close)
    payload["Earnings"]["History"]["2023-12-31"]["epsActual"] = 999
    pd.testing.assert_frame_equal(before, daily_valuation(payload, close))


def test_load_data_uses_historical_actuals_and_keeps_loss_makers(monkeypatch):
    import engine.feeds.market_data as market
    import utils.valuation as valuation
    prices, _ = frames()
    calls = []
    monkeypatch.setattr(valuation, "CachedFundamentals", lambda: SimpleNamespace(
        get_fundamentals=lambda s: calls.append(s) or earnings([-1] * 8)))
    monkeypatch.setattr(market, "MarketDataUtil", lambda **kw: SimpleNamespace(
        get_historical_data=lambda *args: prices["A"]))
    bars, values = valuation.load_valuation_data(["A", "A"], datetime(2024, 2, 1), datetime(2024, 2, 6))
    assert calls == ["A"]
    assert set(bars) == {"A"}
    assert values["A"].pe.isna().all()


def test_eodhd_endpoint_and_fields(monkeypatch):
    import requests
    from engine.feeds.eodhd import EODHD_API
    captured = []

    def fake_get(url, **kwargs):
        captured.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=earnings)

    monkeypatch.setattr(requests, "get", fake_get)
    assert EODHD_API(api_key="unit-test").get_fundamentals("AAPL") == earnings()
    assert captured[0][0] == "https://eodhd.com/api/fundamentals/AAPL.US"
    assert captured[0][1]["timeout"] == 30


def test_bad_payload_not_cached(tmp_path):
    cached = CachedFundamentals(SimpleNamespace(get_fundamentals=lambda s: {}), tmp_path)
    with pytest.raises(ValueError, match="publication dates"):
        cached.get_fundamentals("A")
    assert list(tmp_path.iterdir()) == []


def test_orchestrator_forwards_strategy_params(monkeypatch):
    import agents.orchestrator as module
    from agents.orchestrator import Orchestrator

    captured = []
    orch = Orchestrator.__new__(Orchestrator)
    orch.user_id, orch.account_id = None, None
    orch.run_id, orch._mode = "test-run", "backtest"
    monkeypatch.setattr(orch, "_attribute", lambda config: config)
    monkeypatch.setattr(module, "update_run", lambda *args, **kw: None)
    state_agent = SimpleNamespace(set_running=lambda *args: None, set_completed=lambda: None)
    orch.state = SimpleNamespace(get_agent=lambda *args: state_agent, save=lambda: None,
                                 backtest_results=[], best_config=None)
    orch.bus = SimpleNamespace(publish=lambda **kw: None)
    orch.backtester = SimpleNamespace(run=lambda req: captured.append(req) or {"best_config": {}})
    params = {"mode": "low_pe", "top_n": 2}
    orch.run_backtest({"strategy": "valuation", "lookback": "12m", "params": params})
    assert captured[0]["params"] == params


def test_count_parser_rejects_fractional_top_n():
    from utils.paper_strategies import canonical_strategy, parse_command_params
    assert canonical_strategy("val") == "valuation"
    with pytest.raises(ValueError, match="positive integer"):
        parse_command_params("valuation", {"top_n": "1.5"})


def test_chat_valuation_strategy_and_params():
    from engine.web.ph_chat import _hermes_backtest_config, _hermes_clarification
    message = "run backtest valuation AAPL MSFT lookback:12m mode:high_pe top_n:1 rebalance:quarterly"
    config = _hermes_backtest_config(message)
    assert config["strategy"] == "valuation"
    assert config["params"] == {"mode": "high_pe", "top_n": 1, "rebalance": "quarterly"}
    assert _hermes_clarification(message) is None
