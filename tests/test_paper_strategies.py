"""Paper strategy schema tests — no DB, no network.

Covers the deploy-to-paper contract across all four strategies: parameter
resolution (precedence + the ratio/percent/points translation rules), the
``paper_deploy_command`` UI wrapper, non-degenerate slugs, the
``agent:paper`` command round-trip, and the PaperTradeAgent strategy
dispatch with a stubbed broker client.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from utils.paper_strategies import (
    PARAM_SCHEMA,
    canonical_strategy,
    resolve_paper_params,
    slug_params,
    storage_params,
    strategy_command,
    parse_command_params,
    ratio_to_percent,
)
from utils.strategy_slug import build_slug


STRATEGIES = ("buy_the_dip", "momentum", "vix", "box_wedge")


# ---------------------------------------------------------------------------
# Alias + ratio conventions
# ---------------------------------------------------------------------------

def test_canonical_aliases():
    assert canonical_strategy("btd") == "buy_the_dip"
    assert canonical_strategy("mom") == "momentum"
    assert canonical_strategy("bwg") == "box_wedge"
    assert canonical_strategy("vix") == "vix"
    assert canonical_strategy("buy_the_dip") == "buy_the_dip"


def test_ratio_to_percent_only_scales_fractions():
    assert ratio_to_percent(0.05) == 5.0
    assert ratio_to_percent(0.005) == 0.5
    assert ratio_to_percent(5.0) == 5.0        # already percent
    assert ratio_to_percent(0) == 0
    assert ratio_to_percent(20.0) == 20.0      # points stay points
    assert ratio_to_percent("0.05") == 5.0
    assert ratio_to_percent(None) is None


# ---------------------------------------------------------------------------
# resolve_paper_params — precedence + translation
# ---------------------------------------------------------------------------

def test_resolve_precedence_explicit_beats_yaml_beats_default():
    yaml = {"momentum": {"momentum_threshold": 3.0, "hold_days": 4}}
    r = resolve_paper_params("momentum", {"momentum_threshold": 7.0}, yaml)
    assert r["momentum_threshold"] == 7.0
    assert r["hold_days"] == 4
    r = resolve_paper_params("momentum", {}, yaml)
    assert r["momentum_threshold"] == 3.0
    r = resolve_paper_params("momentum", {}, {})
    assert r["momentum_threshold"] == 5.0  # schema default


def test_resolve_translation_rules():
    # percent kind: stored ratios scale, percents pass through
    r = resolve_paper_params("momentum", {"momentum_threshold": 0.05}, None)
    assert r["momentum_threshold"] == 5.0
    # points kind: VIX level is never scaled
    r = resolve_paper_params("vix", {"vix_threshold": 20.0}, None)
    assert r["vix_threshold"] == 20.0
    # ratio kind: contraction threshold is dimensionless, never scaled
    r = resolve_paper_params("box_wedge", {"contraction_threshold": 0.7}, None)
    assert r["contraction_threshold"] == 0.7
    # Under the storage/orchestrator convention 0.5 IS a ratio (50%) — that is
    # what the backtest stores. Percent-unit callers (the agent, direct
    # callers) resolve with translate=False instead; see
    # test_agent_side_resolution_translates_nothing.
    r = resolve_paper_params("buy_the_dip", {"stop_loss_threshold": 0.5}, None)
    assert r["stop_loss_threshold"] == 50.0


def test_storage_params_renames_and_hold_type():
    p = storage_params("vix", {"vix_threshold": 20.0, "hold_type": "on"})
    assert p == {"vix_threshold": 20.0, "hold_overnight": True}
    p = storage_params("vix", {"hold_type": "eod"})
    assert p["hold_overnight"] is False
    p = storage_params("buy_the_dip", {"take_profit": 0.01, "stop_loss": 0.005})
    assert p == {"take_profit_threshold": 0.01, "stop_loss_threshold": 0.005}
    p = storage_params("box_wedge", {"risk_pct": 0.01, "junk": 1})
    assert p == {"risk_per_trade_pct": 0.01}


def test_agent_side_resolution_translates_nothing():
    """The agent receives percent-unit params (orchestrator already
    translated DB ratios; yaml and direct callers use percents) and must not
    re-translate — a 0.5% stop_loss would otherwise become 50%."""
    yaml = {"buy_the_dip": {"dip_threshold": 1.0, "take_profit_threshold": 1.0,
                            "stop_loss_threshold": 0.5, "hold_days": 0,
                            "min_hold_days": 0, "capital_per_trade": 1000.0}}
    r = resolve_paper_params("buy_the_dip", {}, yaml, translate=False)
    assert r == {
        "dip_threshold": 1.0,
        "take_profit_threshold": 1.0,
        "stop_loss_threshold": 0.5,
        "hold_days": 0,
        "min_hold_days": 0,
        "capital_per_trade": 1000.0,
        "position_size": None,
    }


# ---------------------------------------------------------------------------
# paper_deploy_command — the UI CTA
# ---------------------------------------------------------------------------

def test_deploy_command_all_four_strategies():
    from engine.web.onboarding import paper_deploy_command

    btd = paper_deploy_command({"strategy": "buy_the_dip", "params": {
        "dip_threshold": 0.05, "take_profit": 0.01, "stop_loss": 0.005,
        "hold_days": 2, "symbols": ["AAPL", "MSFT"]}})
    assert btd and btd.startswith("agent:paper strategy:buy_the_dip")
    assert "dip_threshold:5" in btd and "take_profit_threshold:1" in btd
    assert "stop_loss_threshold:0.5" in btd and "hold_days:2" in btd
    assert "symbols:AAPL,MSFT" in btd

    mom = paper_deploy_command({"strategy": "momentum", "params": {
        "lookback_period": 20, "momentum_threshold": 0.05, "hold_days": 5,
        "take_profit": 0.10, "stop_loss": 0.05, "position_size_pct": 0.10}})
    assert mom and "momentum_threshold:5" in mom and "lookback_period:20" in mom

    vix = paper_deploy_command({"strategy": "vix", "params": {
        "vix_threshold": 20.0, "hold_type": "on", "position_size": 0.1}})
    assert vix and "vix_threshold:20" in vix and "hold_overnight:true" in vix

    bwg = paper_deploy_command({"strategy": "box_wedge", "params": {
        "risk_pct": 0.01, "contraction_threshold": 0.7, "box_lookback": 100,
        "wedge_lookback": 20, "scale_out_1_5r_pct": 0.50, "scale_out_3r_pct": 0.25}})
    assert bwg and "risk_per_trade_pct:1" in bwg
    assert "contraction_threshold:0.7" in bwg and "scale_out_1_5r_pct:50" in bwg


def test_deploy_command_none_cases():
    from engine.web.onboarding import paper_deploy_command

    assert paper_deploy_command(None) is None
    assert paper_deploy_command({}) is None
    assert paper_deploy_command({"strategy": "nonsense", "params": {}}) is None
    assert paper_deploy_command({"strategy": "momentum", "params": "not-a-dict"}) is None
    assert paper_deploy_command({"strategy": "momentum"}) is None


def test_deploy_command_accepts_json_params_string():
    from engine.web.onboarding import paper_deploy_command

    cfg = {"strategy": "vix",
           "params": json.dumps({"vix_threshold": 22.0, "hold_type": "eod"})}
    cmd = paper_deploy_command(cfg)
    assert cmd and "vix_threshold:22" in cmd and "hold_overnight:false" in cmd


# ---------------------------------------------------------------------------
# Slugs + command round-trip
# ---------------------------------------------------------------------------

def test_slugs_are_non_degenerate_for_all_strategies():
    expected_prefix = {"buy_the_dip": "btd-", "momentum": "mom-",
                       "vix": "vix-", "box_wedge": "bwg-"}
    for strategy in STRATEGIES:
        resolved = resolve_paper_params(strategy, {}, None)
        slug = build_slug(strategy, slug_params(strategy, resolved), "3m")
        assert slug.startswith(expected_prefix[strategy]), (strategy, slug)
        assert slug != strategy and slug != f"{expected_prefix[strategy]}3m", slug

    assert build_slug("momentum", slug_params(
        "momentum", resolve_paper_params("momentum", {}, None)), "3m") == \
        "mom-20lb-5mt-5d-10tp-5sl-3m"
    assert build_slug("vix", slug_params(
        "vix", resolve_paper_params("vix", {}, None)), "3m") == "vix-20t-on-3m"
    assert build_slug("box_wedge", slug_params(
        "box_wedge", resolve_paper_params("box_wedge", {}, None)), "3m") == \
        "bwg-1r-70ct-3m"
    assert build_slug("buy_the_dip", slug_params(
        "buy_the_dip", resolve_paper_params("buy_the_dip", {}, None)), "3m") == \
        "btd-5dp-50sl-1tp-2d-3m"


def test_strategy_command_and_parse_round_trip():
    for strategy in STRATEGIES:
        cmd = strategy_command(strategy, {}, symbols=["AAPL", "MSFT"])
        assert cmd.startswith(f"agent:paper strategy:{strategy}")
        tokens = cmd.removeprefix("agent:paper").strip().split()
        raw = {}
        for token in tokens:
            key, _, value = token.partition(":")
            if key != "strategy" and key != "symbols":
                raw[key] = value
        parsed = parse_command_params(strategy, raw)
        resolved = resolve_paper_params(strategy, parsed, None)
        assert parsed.keys() >= {p.key for p in PARAM_SCHEMA[strategy]
                                 if p.required}, (strategy, parsed)


def test_strategy_command_raises_on_unknown_strategy():
    with pytest.raises(ValueError):
        strategy_command("nonsense", {})


# ---------------------------------------------------------------------------
# PaperTradeAgent strategy dispatch — stubbed client, no DB/network
# ---------------------------------------------------------------------------

class StubClient:
    """Minimal Alpaca client stub: one AAPL position, no orders."""

    def __init__(self, entry_time=None, qty=10, entry_price=100.0, plpc=0.05):
        self.entry_time = entry_time
        self.position = {"symbol": "AAPL", "qty": str(qty),
                         "qty_available": str(qty),
                         "avg_entry_price": str(entry_price),
                         "current_price": str(entry_price * (1 + plpc)),
                         "unrealized_plpc": str(plpc)}
        self.closes = []
        self.orders = []

    def get_positions(self):
        return [dict(self.position)]

    def get_position(self, symbol):
        return {"error": "not found"}

    def close_position(self, symbol, qty=None):
        self.closes.append((symbol, qty))
        return {"id": "x", "status": "closed"}

    def create_order(self, **kwargs):
        self.orders.append(kwargs)
        return {"id": "y", "status": "filled"}

    def get_account(self):
        return {"buying_power": "50000", "equity": "50000"}

    def get_orders(self, **kwargs):
        return []


def _agent(monkeypatch, client, entry_time):
    from agents.paper_trade_agent import PaperTradeAgent
    agent = PaperTradeAgent()
    agent.client = client
    monkeypatch.setattr(agent, "_store_trade", lambda trade: None)
    monkeypatch.setattr(agent, "_publish_trade_update", lambda trade: None)
    agent._tracked_positions["AAPL"] = {"entry_time": entry_time,
                                        "entry_price": 100.0, "qty": 10}
    return agent


def test_dispatch_btd_uses_generic_exit_machinery(monkeypatch):
    yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    client = StubClient(entry_time=yesterday)
    agent = _agent(monkeypatch, client, yesterday)
    agent._run_strategy_cycle("buy_the_dip", ["AAPL"],
                              {"dip_threshold": 5.0, "take_profit_threshold": 1.0,
                               "stop_loss_threshold": 0.5, "hold_days": 2,
                               "capital_per_trade": 1000.0})
    assert client.closes and client.closes[0][0] == "AAPL"
    assert "TAKE_PROFIT" in agent.trades[-1]["reason"]


def test_dispatch_vix_overnight_exit_never_tp_sl(monkeypatch):
    yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    client = StubClient(entry_time=yesterday)
    agent = _agent(monkeypatch, client, yesterday)
    agent._run_strategy_cycle("vix", ["AAPL"],
                              {"vix_threshold": 20.0, "hold_overnight": True,
                               "capital_per_trade": 1000.0})
    assert client.closes and client.closes[0][0] == "AAPL"
    assert "OVERNIGHT_HOLD" in agent.trades[-1]["reason"]
    assert "TAKE_PROFIT" not in agent.trades[-1]["reason"]


def test_dispatch_vix_same_day_position_held(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    client = StubClient(entry_time=now)
    agent = _agent(monkeypatch, client, now)
    agent._run_strategy_cycle("vix", ["AAPL"],
                              {"vix_threshold": 20.0, "hold_overnight": True,
                               "capital_per_trade": 1000.0})
    assert not client.closes


def test_dispatch_unknown_strategy_no_ops(monkeypatch):
    client = StubClient(entry_time=datetime.now(timezone.utc).isoformat())
    agent = _agent(monkeypatch, client, None)
    agent._run_strategy_cycle("nonsense", ["AAPL"], {})
    assert not client.closes and not client.orders


def test_run_rejects_unknown_strategy(monkeypatch):
    from agents.paper_trade_agent import PaperTradeAgent
    agent = PaperTradeAgent()
    result = agent.run({"strategy": "nonsense", "params": {}})
    assert "error" in result