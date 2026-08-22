"""
Backtesting Agent

Runs parameterized backtests with systematic variation of portfolios,
time intervals, and strategy parameters. Stores results to DB and
reports the best-performing configuration.
"""

import sys
import uuid
import logging
import itertools
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

# Ensure project root is importable
project_root = Path(__file__).parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from utils.backtester_util import (
    backtest_buy_the_dip,
    backtest_momentum_strategy,
    backtest_vix_strategy,
)
from utils.agent_storage import store_backtest_results
from engine.objective import ObjectiveWeights, select_best, rank_variations

logger = logging.getLogger(__name__)

# Default parameter grids
DEFAULT_VARIATIONS = {
    "buy_the_dip": {
        "dip_threshold": [0.03, 0.05, 0.07],
        "take_profit": [0.01, 0.015],
        "hold_days": [1, 2, 3],
        "stop_loss": [0.005],
        "position_size": [0.10],
    },
}

DEFAULT_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]

LOOKBACK_PERIODS = {
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
}


class BacktestAgent:
    """Agent that runs parameterized backtests and finds optimal configurations."""

    def __init__(self, message_bus=None, state=None, user_id=None, account_id=None):
        self.message_bus = message_bus
        self.state = state
        self.user_id = user_id
        self.account_id = account_id
        self.results: List[Dict[str, Any]] = []

    def run(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run backtests based on a request payload.

        Args:
            request: Dict with keys:
                - strategy: str (default "buy_the_dip")
                - symbols: list of str
                - lookback: str ("1m", "3m", "6m", "1y") or start_date/end_date
                - initial_capital: float
                - variations: dict of param -> list of values
                - data_source: str (default "yfinance")

        Returns:
            Dict with run_id, total_variations, best_config, all_results_summary
        """
        strategy = request.get("strategy", "buy_the_dip")
        symbols = request.get("symbols", DEFAULT_SYMBOLS)
        initial_capital = request.get("initial_capital", 10000.0)
        data_source = request.get("data_source", "yfinance")
        extended_hours = request.get("extended_hours", True)
        intraday_exit = request.get("intraday_exit", False)
        pdt_protection = request.get("pdt_protection")
        conservative_metrics = bool(request.get("conservative_metrics", False))
        conservative_execution = bool(request.get("conservative_execution", False))
        include_taf_fees = bool(request.get("include_taf_fees", False))
        include_cat_fees = bool(request.get("include_cat_fees", False))
        slippage_bps = float(request.get("slippage_bps", 0.0) or 0.0)

        # Determine date range
        end_date = datetime.now()
        if "start_date" in request and "end_date" in request:
            start_date = datetime.fromisoformat(request["start_date"])
            end_date = datetime.fromisoformat(request["end_date"])
        else:
            lookback = request.get("lookback", "3m")
            days = LOOKBACK_PERIODS.get(lookback, 90)
            start_date = end_date - timedelta(days=days)

        full_end_date = end_date
        validation_start = None
        validation_fraction = float(request.get("validation_fraction", 0.0) or 0.0)
        if strategy == "buy_the_dip" and 0.0 < validation_fraction < 0.5:
            span = full_end_date - start_date
            validation_start = start_date + span * (1.0 - validation_fraction)
            end_date = validation_start - timedelta(seconds=1)

        run_id = request.get("run_id", str(uuid.uuid4()))

        # Variations precedence: explicit request > regime preset > static default.
        # When the autonomy pipeline detects a regime (Phase 2a) and sets
        # request['regime'], we pull the per-regime grid from engine.regime.
        variations = request.get("variations")
        if not variations:
            regime_state = request.get("regime")
            if regime_state:
                try:
                    from engine.regime import regime_variations
                    variations = regime_variations(strategy, regime_state)
                except Exception:  # noqa: BLE001
                    pass
        if not variations:
            variations = DEFAULT_VARIATIONS.get(strategy, {})

        # Extract scalar regime flags (vol_target, atr_exit_mult) that ride
        # alongside the grid lists in the regime preset. They're not swept —
        # they're mode flags applied to every variation in the grid.
        vol_target = request.get("vol_target")
        atr_exit_mult = request.get("atr_exit_mult")
        if isinstance(variations.get("vol_target"), (int, float)):
            if vol_target is None:
                vol_target = float(variations["vol_target"])
            variations = {k: v for k, v in variations.items() if k != "vol_target"}
        if isinstance(variations.get("atr_exit_mult"), (int, float)):
            if atr_exit_mult is None:
                atr_exit_mult = float(variations["atr_exit_mult"])
            variations = {k: v for k, v in variations.items() if k != "atr_exit_mult"}

        logger.info(f"Backtest agent starting run {run_id}")
        logger.info(f"Strategy: {strategy}, Symbols: {symbols}")
        logger.info(f"Date range: {start_date.date()} to {end_date.date()}")
        if request.get("regime"):
            logger.info(f"Regime: {request['regime']}")

        # Adaptive search: when request['adaptive'] is true (buy_the_dip),
        # run a random-search + elite-refinement loop against the Phase-1
        # objective instead of the static itertools.product grid. Falls back
        # to the static grid if the adaptive path fails or is disabled.
        adaptive = request.get("adaptive", False)

        if strategy == "buy_the_dip":
            if adaptive:
                try:
                    results = self._run_adaptive_buy_the_dip(
                        symbols=symbols, start_date=start_date, end_date=end_date,
                        initial_capital=initial_capital, data_source=data_source,
                        seed_variations=variations, run_id=run_id,
                        extended_hours=extended_hours, intraday_exit=intraday_exit,
                        pdt_protection=pdt_protection,
                        objective=request.get("objective") or {},
                        n_iter=int(request.get("adaptive_iterations", 40)),
                        vol_target=vol_target, atr_exit_mult=atr_exit_mult,
                        conservative_metrics=conservative_metrics,
                        conservative_execution=conservative_execution,
                        include_taf_fees=include_taf_fees,
                        include_cat_fees=include_cat_fees,
                        slippage_bps=slippage_bps,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Adaptive search failed ({e}); falling back to static grid.")
                    results = self._run_buy_the_dip_grid(
                        symbols=symbols, start_date=start_date, end_date=end_date,
                        initial_capital=initial_capital, data_source=data_source,
                        variations=variations, run_id=run_id,
                        extended_hours=extended_hours, intraday_exit=intraday_exit,
                        pdt_protection=pdt_protection,
                        vol_target=vol_target, atr_exit_mult=atr_exit_mult,
                        conservative_metrics=conservative_metrics,
                        conservative_execution=conservative_execution,
                        include_taf_fees=include_taf_fees,
                        include_cat_fees=include_cat_fees,
                        slippage_bps=slippage_bps,
                    )
            else:
                results = self._run_buy_the_dip_grid(
                    symbols=symbols,
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=initial_capital,
                    data_source=data_source,
                    variations=variations,
                    run_id=run_id,
                    extended_hours=extended_hours,
                    intraday_exit=intraday_exit,
                    pdt_protection=pdt_protection,
                    vol_target=vol_target,
                    atr_exit_mult=atr_exit_mult,
                    conservative_metrics=conservative_metrics,
                    conservative_execution=conservative_execution,
                    include_taf_fees=include_taf_fees,
                    include_cat_fees=include_cat_fees,
                    slippage_bps=slippage_bps,
                )
        elif strategy == "momentum":
            results = self._run_momentum(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                data_source=data_source,
                run_id=run_id,
            )
        elif strategy == "vix":
            results = self._run_vix(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                run_id=run_id,
            )
        elif strategy == "box_wedge":
            results = self._run_box_wedge(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                run_id=run_id,
            )
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        self.results = results

        # Select best by the PnL-maximising composite objective
        # (annualised return − drawdown penalty − vol penalty, with a
        # min-trades gate). Falls back to max-Sharpe only if all rows
        # are disqualified. Objective weights are configurable per-run.
        obj_cfg = request.get("objective") or {}
        weights = ObjectiveWeights.from_config(obj_cfg)
        maximize = obj_cfg.get("maximize")
        best = select_best(results, weights, maximize=maximize)
        ranked = rank_variations(results, weights, maximize=maximize)

        validation = None
        if validation_start is not None and best.get("params"):
            params = best["params"]
            validation_grid = {
                "dip_threshold": [params["dip_threshold"]],
                "take_profit": [params["take_profit"]],
                "hold_days": [params["hold_days"]],
                "stop_loss": [params["stop_loss"]],
                "position_size": [params["position_size"]],
            }
            validation_rows = self._run_buy_the_dip_grid(
                symbols=symbols, start_date=validation_start, end_date=full_end_date,
                initial_capital=initial_capital, data_source=data_source,
                variations=validation_grid, run_id=run_id,
                extended_hours=extended_hours, intraday_exit=intraday_exit,
                pdt_protection=pdt_protection, vol_target=vol_target,
                atr_exit_mult=atr_exit_mult,
                conservative_metrics=conservative_metrics,
                conservative_execution=conservative_execution,
                include_taf_fees=include_taf_fees,
                include_cat_fees=include_cat_fees,
                slippage_bps=slippage_bps,
            )
            validation = next(
                (row for row in validation_rows if not row.get("error")), {}
            )
            reasons = []
            if int(validation.get("total_trades", 0) or 0) < 20:
                reasons.append("validation has fewer than 20 closed trades")
            if float(validation.get("total_return", 0) or 0) <= 0:
                reasons.append("validation total return is not positive")
            if float(validation.get("sharpe_ratio", 0) or 0) < 0.5:
                reasons.append("validation Sharpe is below 0.50")
            validation_drawdown = validation.get("max_drawdown")
            if validation_drawdown is None or float(validation_drawdown) > 10:
                reasons.append("validation drawdown exceeds 10%")
            top_sharpes = [float(row.get("sharpe_ratio", 0) or 0) for row in ranked[:3]]
            if len(top_sharpes) < 3 or statistics.median(top_sharpes) <= 0:
                reasons.append("top training variations are not stable")
            best = {
                **best,
                "promotion_eligible": not reasons,
                "promotion_reasons": reasons,
                "training_period": {
                    "start": start_date.isoformat(), "end": end_date.isoformat(),
                },
                "validation_period": {
                    "start": validation_start.isoformat(),
                    "end": full_end_date.isoformat(),
                },
                "validation_metrics": {
                    key: validation.get(key) for key in (
                        "total_return", "annualized_return", "max_drawdown",
                        "sharpe_ratio", "sortino_ratio", "calmar_ratio",
                        "win_rate", "total_trades", "total_pnl", "equity_days",
                    )
                },
            }

        # Store results to DB if available
        lookback = request.get("lookback", "3m")
        self._store_results(run_id, best, results,
                            strategy=strategy, lookback=lookback)

        best_trades = best.get("trades", [])

        output = {
            "run_id": run_id,
            "strategy": strategy,
            "total_variations": len(results),
            "best_config": best,
            "methodology": {
                "conservative_execution": conservative_execution,
                "portfolio_daily_metrics": conservative_metrics,
                "slippage_bps": slippage_bps,
                "taf_fees": include_taf_fees,
                "cat_fees": include_cat_fees,
                "validation_fraction": validation_fraction,
            },
            "trades": best_trades,
            "all_results_summary": [
                {
                    "params": r.get("params"),
                    "sharpe_ratio": r.get("sharpe_ratio", 0),
                    "sortino_ratio": r.get("sortino_ratio", 0),
                    "calmar_ratio": r.get("calmar_ratio", 0),
                    "total_return": r.get("total_return", 0),
                    "annualized_return": r.get("annualized_return", 0),
                    "max_drawdown": r.get("max_drawdown", 0),
                    "win_rate": r.get("win_rate", 0),
                    "total_trades": r.get("total_trades", 0),
                    "score": r.get("_score"),
                }
                for r in ranked
            ],
        }

        # Publish result if message bus available
        if self.message_bus:
            self.message_bus.publish(
                from_agent="backtester",
                to_agent="portfolio_manager",
                msg_type="backtest_result",
                payload=output,
            )

        logger.info(
            f"Backtest run {run_id} complete: {len(results)} variations, "
            f"best score={best.get('_score')}, "
            f"ann_ret={best.get('annualized_return', 0):.2f}%, "
            f"max_dd={best.get('max_drawdown', 0):.2f}%, "
            f"trades={best.get('total_trades', 0)}"
        )
        return output

    def _run_buy_the_dip_grid(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        data_source: str,
        variations: Dict,
        run_id: str,
        extended_hours: bool = True,
        intraday_exit: bool = False,
        pdt_protection: Optional[bool] = None,
        vol_target: Optional[float] = None,
        atr_exit_mult: Optional[float] = None,
        conservative_metrics: bool = False,
        conservative_execution: bool = False,
        include_taf_fees: bool = False,
        include_cat_fees: bool = False,
        slippage_bps: float = 0.0,
    ) -> List[Dict]:
        """Run buy-the-dip backtests across a parameter grid."""
        dip_thresholds = variations.get("dip_threshold", [0.05])
        take_profits = variations.get("take_profit", [0.01])
        hold_days_list = variations.get("hold_days", [2])
        stop_losses = variations.get("stop_loss", [0.005])
        position_sizes = variations.get("position_size", [0.10])

        grid = list(itertools.product(
            dip_thresholds, take_profits, hold_days_list, stop_losses, position_sizes
        ))

        logger.info(f"Parameter grid: {len(grid)} combinations")
        results = []

        for i, (dip, tp, hd, sl, ps) in enumerate(grid):
            logger.info(
                f"  [{i + 1}/{len(grid)}] dip={dip}, tp={tp}, hold={hd}, sl={sl}, ps={ps}"
            )
            try:
                bt_result = backtest_buy_the_dip(
                    symbols=symbols,
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=initial_capital,
                    position_size=ps,
                    dip_threshold=dip,
                    hold_days=hd,
                    take_profit=tp,
                    stop_loss=sl,
                    data_source=data_source,
                    extended_hours=extended_hours,
                    intraday_exit=intraday_exit,
                    pdt_protection=pdt_protection,
                    vol_target=vol_target,
                    atr_exit_mult=atr_exit_mult,
                    conservative_metrics=conservative_metrics,
                    conservative_execution=conservative_execution,
                    include_taf_fees=include_taf_fees,
                    include_cat_fees=include_cat_fees,
                    slippage_bps=slippage_bps,
                )

                # backtest_buy_the_dip returns None when no price data available
                if bt_result is None:
                    logger.warning(f"  Variation {i}: no price data returned")
                    results.append({
                        "run_id": run_id,
                        "variation_index": i,
                        "params": {"dip_threshold": dip, "take_profit": tp,
                                   "hold_days": hd, "stop_loss": sl, "position_size": ps},
                        "error": "no_price_data",
                        "sharpe_ratio": 0,
                    })
                    continue

                trades_df, metrics, _ = bt_result

                # Convert trades DataFrame to list of dicts for storage
                trades_list = []
                if trades_df is not None and not trades_df.empty:
                    trades_list = trades_df.to_dict(orient="records")

                result = {
                    "run_id": run_id,
                    "variation_index": i,
                    "params": {
                        "dip_threshold": dip,
                        "take_profit": tp,
                        "hold_days": hd,
                        "stop_loss": sl,
                        "position_size": ps,
                        "symbols": symbols,
                    },
                    "total_return": metrics.get("total_return", 0),
                    "total_pnl": metrics.get("total_pnl", 0),
                    "win_rate": metrics.get("win_rate", 0),
                    "total_trades": metrics.get("total_trades", 0),
                    "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                    "sortino_ratio": metrics.get("sortino_ratio", 0),
                    "calmar_ratio": metrics.get("calmar_ratio", 0),
                    "max_drawdown": metrics.get("max_drawdown", 0),
                    "annualized_return": metrics.get("annualized_return", 0),
                    "trades_count": len(trades_df) if trades_df is not None else 0,
                    "trades": trades_list,
                }
                results.append(result)

            except Exception as e:
                logger.error(f"  Variation {i} failed: {e}")
                results.append({
                    "run_id": run_id,
                    "variation_index": i,
                    "params": {"dip_threshold": dip, "take_profit": tp,
                               "hold_days": hd, "stop_loss": sl, "position_size": ps},
                    "error": str(e),
                    "sharpe_ratio": 0,
                })

        return results

    def _run_adaptive_buy_the_dip(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        data_source: str,
        seed_variations: Dict,
        run_id: str,
        extended_hours: bool = True,
        intraday_exit: bool = False,
        pdt_protection=None,
        objective: Optional[Dict] = None,
        n_iter: int = 40,
        vol_target: Optional[float] = None,
        atr_exit_mult: Optional[float] = None,
        conservative_metrics: bool = False,
        conservative_execution: bool = False,
        include_taf_fees: bool = False,
        include_cat_fees: bool = False,
        slippage_bps: float = 0.0,
    ) -> List[Dict]:
        """Adaptive random-search + elite refinement against the Phase-1 objective.

        Instead of exhaustively enumerating a static grid, samples parameter
        combinations from the ranges implied by ``seed_variations`` (or regime
        presets), evaluates each via ``backtest_buy_the_dip``, scores with the
        composite objective, and refines around the top-K elite. This scales
        to the larger regime-conditional parameter space without running 1000s
        of variations, and it directly optimises the PnL-maximising objective.

        No new dependencies — uses stdlib ``random``. Deterministic with
        ``random.seed(42)``.
        """
        import random
        from engine.objective import ObjectiveWeights, score_variation

        rng = random.Random(42)
        weights = ObjectiveWeights.from_config(objective)

        # Build sampling ranges from the seed variations
        def _range(key, lo_default, hi_default, is_int=False):
            vals = seed_variations.get(key)
            if vals:
                lo, hi = float(min(vals)), float(max(vals))
            else:
                lo, hi = lo_default, hi_default
            if is_int:
                return (int(round(lo)), int(round(hi)))
            return (lo, hi)

        dip_r = _range("dip_threshold", 0.02, 0.10)
        tp_r = _range("take_profit", 0.005, 0.04)
        sl_r = _range("stop_loss", 0.003, 0.02)
        hd_r = _range("hold_days", 1, 5, is_int=True)
        ps_r = _range("position_size", 0.05, 0.12)

        def _sample():
            return {
                "dip_threshold": round(rng.uniform(*dip_r), 4),
                "take_profit": round(rng.uniform(*tp_r), 4),
                "stop_loss": round(rng.uniform(*sl_r), 4),
                "hold_days": rng.randint(*hd_r),
                "position_size": round(rng.uniform(*ps_r), 3),
            }

        def _perturb(base, frac=0.15):
            p = {}
            for k, v in base.items():
                if isinstance(v, int):
                    p[k] = max(1, v + rng.choice([-1, 0, 1]))
                else:
                    lo = max(0.001, v * (1 - frac))
                    hi = v * (1 + frac)
                    p[k] = round(rng.uniform(lo, hi), 4)
            return p

        def _eval(params, idx):
            try:
                bt_result = backtest_buy_the_dip(
                    symbols=symbols, start_date=start_date, end_date=end_date,
                    initial_capital=initial_capital,
                    position_size=params["position_size"],
                    dip_threshold=params["dip_threshold"],
                    hold_days=params["hold_days"],
                    take_profit=params["take_profit"],
                    stop_loss=params["stop_loss"],
                    data_source=data_source,
                    extended_hours=extended_hours, intraday_exit=intraday_exit,
                    pdt_protection=pdt_protection,
                    vol_target=vol_target, atr_exit_mult=atr_exit_mult,
                    conservative_metrics=conservative_metrics,
                    conservative_execution=conservative_execution,
                    include_taf_fees=include_taf_fees,
                    include_cat_fees=include_cat_fees,
                    slippage_bps=slippage_bps,
                )
                if bt_result is None:
                    return {"run_id": run_id, "variation_index": idx, "params": params,
                            "error": "no_price_data", "sharpe_ratio": 0}
                trades_df, metrics, _ = bt_result
                trades_list = trades_df.to_dict(orient="records") if trades_df is not None and not trades_df.empty else []
                return {
                    "run_id": run_id, "variation_index": idx, "params": {**params, "symbols": symbols},
                    "total_return": metrics.get("total_return", 0),
                    "total_pnl": metrics.get("total_pnl", 0),
                    "win_rate": metrics.get("win_rate", 0),
                    "total_trades": metrics.get("total_trades", 0),
                    "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                    "max_drawdown": metrics.get("max_drawdown", 0),
                    "annualized_return": metrics.get("annualized_return", 0),
                    "trades_count": len(trades_df) if trades_df is not None else 0,
                    "trades": trades_list,
                }
            except Exception as e:  # noqa: BLE001
                return {"run_id": run_id, "variation_index": idx, "params": params,
                        "error": str(e), "sharpe_ratio": 0}

        results: List[Dict] = []
        # Phase 1: random exploration (half the budget)
        n_explore = n_iter // 2
        for i in range(n_explore):
            params = _sample()
            logger.info(f"  [adaptive {i + 1}/{n_iter}] {params}")
            results.append(_eval(params, i))

        # Phase 2: elite refinement around the top-K scored results
        scored = [(r, score_variation(r, weights)) for r in results]
        elites = [r for r, s in sorted(scored, key=lambda x: x[1] or -1e9, reverse=True)
                  if s is not None][:5]
        for j in range(n_iter - n_explore):
            if not elites:
                params = _sample()
            else:
                base = rng.choice(elites).get("params", {})
                params = _perturb({k: v for k, v in base.items() if k != "symbols"})
            idx = n_explore + j
            logger.info(f"  [refine {idx}/{n_iter}] {params}")
            results.append(_eval(params, idx))

        logger.info(f"Adaptive search: {len(results)} variations evaluated")
        return results

    def _run_momentum(self, symbols, start_date, end_date, initial_capital,
                      data_source, run_id) -> List[Dict]:
        """Run momentum backtest (single configuration)."""
        try:
            result = backtest_momentum_strategy(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                data_source=data_source,
            )
            metrics = result if isinstance(result, dict) else {}
            return [{
                "run_id": run_id,
                "variation_index": 0,
                "params": {"strategy": "momentum"},
                "total_return": metrics.get("total_return", 0),
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "win_rate": metrics.get("win_rate", 0),
                "total_trades": metrics.get("total_trades", 0),
            }]
        except Exception as e:
            logger.error(f"Momentum backtest failed: {e}")
            return [{"run_id": run_id, "error": str(e), "sharpe_ratio": 0}]

    def _run_vix(self, symbols, start_date, end_date, initial_capital,
                 run_id) -> List[Dict]:
        """Run VIX backtest (single configuration)."""
        try:
            trades_df, metrics = backtest_vix_strategy(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
            )
            return [{
                "run_id": run_id,
                "variation_index": 0,
                "params": {"strategy": "vix"},
                "total_return": metrics.get("total_return", 0),
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "sortino_ratio": metrics.get("sortino_ratio", 0),
                "calmar_ratio": metrics.get("calmar_ratio", 0),
                "win_rate": metrics.get("win_rate", 0),
                "total_trades": metrics.get("total_trades", 0),
                "max_drawdown": metrics.get("max_drawdown", 0),
                "annualized_return": metrics.get("annualized_return", 0),
            }]
        except Exception as e:
            logger.error(f"VIX backtest failed: {e}")
            return [{"run_id": run_id, "error": str(e), "sharpe_ratio": 0}]

    def _run_box_wedge(self, symbols, start_date, end_date, initial_capital,
                       run_id) -> List[Dict]:
        """Run box-wedge backtest (single configuration).

        Phase 4e: box_wedge was previously unreachable from the orchestrator
        dispatch. It's the most vol-aware strategy in the repo (R-based
        scale-out, SMA200 regime gate, ATR computed — though the ATR is
        currently dead code). Wiring it in makes it available via
        ``agent:backtest strategy:box_wedge`` and the autonomy pipeline.
        """
        try:
            from utils.box_wedge import backtest_box_wedge_strategy
            trades_df, metrics = backtest_box_wedge_strategy(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
            )
            return [{
                "run_id": run_id,
                "variation_index": 0,
                "params": {"strategy": "box_wedge"},
                "total_return": metrics.get("total_return", 0),
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "sortino_ratio": metrics.get("sortino_ratio", 0),
                "calmar_ratio": metrics.get("calmar_ratio", 0),
                "win_rate": metrics.get("win_rate", 0),
                "total_trades": metrics.get("total_trades", 0),
                "max_drawdown": metrics.get("max_drawdown", 0),
                "annualized_return": metrics.get("annualized_return", 0),
            }]
        except Exception as e:
            logger.error(f"Box-wedge backtest failed: {e}")
            return [{"run_id": run_id, "error": str(e), "sharpe_ratio": 0}]

    def _store_results(self, run_id: str, best: Dict, all_results: List[Dict],
                        strategy: str = None, lookback: str = None):
        """Store backtest results using the configured backend (file or DB)."""
        try:
            best_trades = best.get("trades", [])
            store_backtest_results(run_id, best, all_results, best_trades,
                                   strategy=strategy, lookback=lookback,
                                   user_id=self.user_id,
                                   account_id=self.account_id)
        except Exception as e:
            logger.warning(f"Could not store results: {e}")
