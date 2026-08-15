"""Unit tests for the backtest node's LLM rationale (DB-free)."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_backtest_node_logs_llm_rationale_for_best_config():
    from engine.autonomy import graph

    bt = {"best_config": {"params": {"dip_threshold": 0.05}, "sharpe_ratio": 1.8},
          "total_variations": 27}
    with patch("agents.orchestrator.Orchestrator.run_backtest", return_value=bt), \
         patch("engine.autonomy.graph.store.append_event") as ev, \
         patch("engine.autonomy.reason.reason",
               return_value="shallow dips win in high-vol chop") as r:
        nodes = dict(graph.default_pipeline().nodes)
        out = nodes["backtest"]({"config": {"strategy": "buy_the_dip"}, "run_id": "run-x"})
        assert out["has_strategy"] is True
        r.assert_called_once()
        assert any("backtest reasoning" in (c.args[1] if len(c.args) > 1 else "")
                   for c in ev.call_args_list)


def test_backtest_node_skips_llm_when_no_viable_strategy():
    from engine.autonomy import graph

    bt = {"best_config": {}, "total_variations": 27}
    with patch("agents.orchestrator.Orchestrator.run_backtest", return_value=bt), \
         patch("engine.autonomy.graph.store.append_event") as ev, \
         patch("engine.autonomy.reason.reason") as r:
        nodes = dict(graph.default_pipeline().nodes)
        out = nodes["backtest"]({"config": {"strategy": "buy_the_dip"}, "run_id": "run-x"})
        assert out["has_strategy"] is False
        r.assert_not_called()
        assert not any("backtest reasoning" in (c.args[1] if len(c.args) > 1 else "")
                       for c in ev.call_args_list)


def test_backtest_node_survives_reason_exception():
    from engine.autonomy import graph

    bt = {"best_config": {"params": {"dip_threshold": 0.05}, "sharpe_ratio": 1.8},
          "total_variations": 27}
    with patch("agents.orchestrator.Orchestrator.run_backtest", return_value=bt), \
         patch("engine.autonomy.graph.store.append_event"), \
         patch("engine.autonomy.reason.reason", side_effect=RuntimeError("boom")):
        nodes = dict(graph.default_pipeline().nodes)
        out = nodes["backtest"]({"config": {"strategy": "buy_the_dip"}, "run_id": "run-x"})
        assert out["has_strategy"] is True  # LLM failure never breaks the node
