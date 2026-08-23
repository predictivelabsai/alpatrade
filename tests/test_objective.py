"""Unit tests for the PnL-maximising objective function (DB-free)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.objective import ObjectiveWeights, score_variation, rank_variations, select_best


def test_score_rewards_annualised_return_and_penalises_drawdown():
    w = ObjectiveWeights(lambda_drawdown=1.0, lambda_vol=0.0, min_trades=5)
    high_ret_low_dd = {
        "annualized_return": 50.0, "max_drawdown": 5.0,
        "total_trades": 100, "sharpe_ratio": 2.0,
    }
    low_ret_high_dd = {
        "annualized_return": 10.0, "max_drawdown": 40.0,
        "total_trades": 100, "sharpe_ratio": 0.5,
    }
    s1 = score_variation(high_ret_low_dd, w)
    s2 = score_variation(low_ret_high_dd, w)
    assert s1 is not None and s2 is not None
    assert s1 > s2, f"high-ret/low-dd should score higher: {s1} vs {s2}"
    # Score = ann_ret - 1.0 * max_dd
    assert abs(s1 - (50.0 - 5.0)) < 1e-9
    assert abs(s2 - (10.0 - 40.0)) < 1e-9


def test_min_trades_gate_disqualifies_flukes():
    w = ObjectiveWeights(min_trades=20)
    fluke = {"annualized_return": 999.0, "max_drawdown": 0.0,
             "total_trades": 1, "sharpe_ratio": 99.0}
    robust = {"annualized_return": 20.0, "max_drawdown": 10.0,
              "total_trades": 100, "sharpe_ratio": 1.5}
    assert score_variation(fluke, w) is None, "1-trade fluke must be gated out"
    assert score_variation(robust, w) is not None
    best = select_best([fluke, robust], w)
    assert best.get("annualized_return") == 20.0


def test_error_rows_disqualified():
    w = ObjectiveWeights(min_trades=1)
    errored = {"error": "no_price_data", "sharpe_ratio": 999}
    ok = {"annualized_return": 5.0, "max_drawdown": 2.0,
          "total_trades": 50, "sharpe_ratio": 1.0}
    assert score_variation(errored, w) is None
    assert score_variation(ok, w) is not None
    assert select_best([errored, ok], w) is ok or select_best([errored, ok], w).get("annualized_return") == 5.0


def test_rank_variations_sorts_descending_and_injects_score():
    w = ObjectiveWeights(lambda_drawdown=1.0, lambda_vol=0.0, min_trades=10)
    results = [
        {"annualized_return": 30.0, "max_drawdown": 10.0, "total_trades": 50, "sharpe_ratio": 1.0},
        {"annualized_return": 40.0, "max_drawdown": 5.0,  "total_trades": 50, "sharpe_ratio": 2.0},
        {"annualized_return": 999.0, "max_drawdown": 0.0, "total_trades": 1,  "sharpe_ratio": 99.0},  # gated
    ]
    ranked = rank_variations(results, w)
    assert len(ranked) == 2, "fluke should be excluded"
    assert ranked[0]["_score"] >= ranked[1]["_score"]
    assert ranked[0]["annualized_return"] == 40.0


def test_select_best_falls_back_when_all_disqualified():
    w = ObjectiveWeights(min_trades=100)
    results = [
        {"error": "no_price_data", "sharpe_ratio": 0},
        {"annualized_return": 5.0, "max_drawdown": 2.0, "total_trades": 10, "sharpe_ratio": 0.8},
    ]
    # All gated (10 < 100), so fallback to max-Sharpe among non-error
    best = select_best(results, w)
    assert best.get("sharpe_ratio") == 0.8


def test_select_best_returns_empty_when_all_errored():
    w = ObjectiveWeights()
    results = [{"error": "x"}, {"error": "y"}]
    assert select_best(results, w) == {}


def test_explicit_sharpe_objective_selects_highest_eligible_sharpe():
    w = ObjectiveWeights(min_trades=20)
    pnl_winner = {
        "annualized_return": 120.0, "max_drawdown": 1.0,
        "total_trades": 100, "sharpe_ratio": 4.0,
    }
    sharpe_winner = {
        "annualized_return": 80.0, "max_drawdown": 1.0,
        "total_trades": 100, "sharpe_ratio": 7.5,
    }
    fluke = {
        "annualized_return": 999.0, "max_drawdown": 0.0,
        "total_trades": 1, "sharpe_ratio": 99.0,
    }
    best = select_best(
        [pnl_winner, sharpe_winner, fluke], w, maximize="sharpe_ratio"
    )
    assert best["sharpe_ratio"] == 7.5
    assert best["_score"] == 7.5


def test_objective_weights_from_config():
    w = ObjectiveWeights.from_config({"lambda_drawdown": 2.5, "min_trades": 50})
    assert w.lambda_drawdown == 2.5
    assert w.min_trades == 50
    assert w.lambda_vol == ObjectiveWeights().lambda_vol  # default kept


def test_vol_penalty_hurts_low_sharpe():
    w = ObjectiveWeights(lambda_drawdown=0.0, lambda_vol=1.0, min_trades=10)
    # Same return/dd, different Sharpe
    hi_sharpe = {"annualized_return": 20.0, "max_drawdown": 0.0, "total_trades": 50, "sharpe_ratio": 3.0}
    lo_sharpe = {"annualized_return": 20.0, "max_drawdown": 0.0, "total_trades": 50, "sharpe_ratio": 0.2}
    s_hi = score_variation(hi_sharpe, w)
    s_lo = score_variation(lo_sharpe, w)
    assert s_hi > s_lo, "higher Sharpe (less vol drag) should score higher"


def test_sortino_bonus_rewards_high_sortino():
    w = ObjectiveWeights(lambda_drawdown=0.0, lambda_vol=0.0, lambda_sortino=1.0, min_trades=10)
    hi_sortino = {"annualized_return": 20.0, "max_drawdown": 0.0, "total_trades": 50,
                  "sharpe_ratio": 2.0, "sortino_ratio": 5.0}
    lo_sortino = {"annualized_return": 20.0, "max_drawdown": 0.0, "total_trades": 50,
                  "sharpe_ratio": 2.0, "sortino_ratio": 0.5}
    s_hi = score_variation(hi_sortino, w)
    s_lo = score_variation(lo_sortino, w)
    assert s_hi > s_lo, "higher Sortino should score higher"
    assert abs(s_hi - s_lo - (5.0 - 0.5)) < 1e-9, f"bonus diff should be 4.5: {s_hi - s_lo}"


def test_calmar_implicit_in_drawdown_penalty():
    """Calmar = ann_ret / max_dd is captured via the drawdown penalty term."""
    w = ObjectiveWeights(lambda_drawdown=1.0, lambda_vol=0.0, min_trades=10)
    # Two strategies with the same Calmar (10/5 == 20/10) should score
    # differently because the objective is PnL-first, not Calmar-first.
    a = {"annualized_return": 10.0, "max_drawdown": 5.0, "total_trades": 50, "sharpe_ratio": 1.0}
    b = {"annualized_return": 20.0, "max_drawdown": 10.0, "total_trades": 50, "sharpe_ratio": 1.0}
    sa = score_variation(a, w)
    sb = score_variation(b, w)
    # b has higher return and proportionally higher dd → PnL-first → b wins
    assert sb > sa
