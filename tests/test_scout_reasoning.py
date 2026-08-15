"""Unit tests for the scout node's LLM annotation (DB-free)."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _pf():
    from engine.autonomy.policy import PortfolioState
    return PortfolioState(equity=1000.0, open_positions=0, gross_exposure=0.0)


def _cands():
    from engine.autonomy.policy import Candidate
    return [Candidate(symbol="AAPL", strategy_slug="btd", intended_notional=100.0)]


def test_scout_node_annotates_with_llm_when_available():
    from engine.autonomy import graph

    with patch("engine.autonomy.scout.portfolio_state", return_value=_pf()), \
         patch("engine.autonomy.scout.scan", return_value=_cands()), \
         patch("engine.autonomy.graph.store.append_event") as ev, \
         patch("engine.autonomy.reason.reason",
               return_value="AAPL fine; no binary events this week") as r:
        out = graph.scout_node({"config": {}, "run_id": "run-x"})
        assert out["scouted"] == 1
        r.assert_called_once()
        assert any("scout reasoning" in (c.args[1] if len(c.args) > 1 else "")
                   for c in ev.call_args_list)


def test_scout_node_silent_when_reason_returns_empty():
    from engine.autonomy import graph

    with patch("engine.autonomy.scout.portfolio_state", return_value=_pf()), \
         patch("engine.autonomy.scout.scan", return_value=_cands()), \
         patch("engine.autonomy.graph.store.append_event") as ev, \
         patch("engine.autonomy.reason.reason", return_value=""):
        out = graph.scout_node({"config": {}, "run_id": "run-x"})
        assert out["scouted"] == 1
        assert not any("scout reasoning" in (c.args[1] if len(c.args) > 1 else "")
                       for c in ev.call_args_list)


def test_scout_node_survives_reason_exception():
    from engine.autonomy import graph

    with patch("engine.autonomy.scout.portfolio_state", return_value=_pf()), \
         patch("engine.autonomy.scout.scan", return_value=_cands()), \
         patch("engine.autonomy.graph.store.append_event"), \
         patch("engine.autonomy.reason.reason", side_effect=RuntimeError("boom")):
        out = graph.scout_node({"config": {}, "run_id": "run-x"})
        assert out["scouted"] == 1  # node never crashes on LLM failure
