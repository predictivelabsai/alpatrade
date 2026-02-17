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

    def __init__(self, message_bus=None, state=None):
        self.message_bus = message_bus
        self.state = state
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
                - data_source: str (default "massive")

        Returns:
            Dict with run_id, total_variations, best_config, all_results_summary
        """
        strategy = request.get("strategy", "buy_the_dip")
        symbols = request.get("symbols", DEFAULT_SYMBOLS)
        initial_capital = request.get("initial_capital", 10000.0)
        data_source = request.get("data_source", "massive")
        variations = request.get("variations") or DEFAULT_VARIATIONS.get(strategy, {})
        extended_hours = request.get("extended_hours", False)
        intraday_exit = request.get("intraday_exit", False)
        pdt_protection = request.get("pdt_protection")

        # Determine date range
        end_date = datetime.now()
        if "start_date" in request and "end_date" in request:
            start_date = datetime.fromisoformat(request["start_date"])
            end_date = datetime.fromisoformat(request["end_date"])
        else:
            lookback = request.get("lookback", "3m")
            days = LOOKBACK_PERIODS.get(lookback, 90)
            start_date = end_date - timedelta(days=days)

        run_id = request.get("run_id", str(uuid.uuid4()))

        logger.info(f"Backtest agent starting run {run_id}")
        logger.info(f"Strategy: {strategy}, Symbols: {symbols}")
        logger.info(f"Date range: {start_date.date()} to {end_date.date()}")

        if strategy == "buy_the_dip":
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
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        self.results = results

        # Find best configuration by Sharpe ratio
        best = max(results, key=lambda r: r.get("sharpe_ratio", 0)) if results else {}

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
            "trades": best_trades,
            "all_results_summary": [
                {
                    "params": r.get("params"),
                    "sharpe_ratio": r.get("sharpe_ratio", 0),
                    "total_return": r.get("total_return", 0),
                    "win_rate": r.get("win_rate", 0),
                    "total_trades": r.get("total_trades", 0),
                }
                for r in results
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
            f"best Sharpe={best.get('sharpe_ratio', 0):.2f}"
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
        extended_hours: bool = False,
        intraday_exit: bool = False,
        pdt_protection: Optional[bool] = None,
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
                "win_rate": metrics.get("win_rate", 0),
                "total_trades": metrics.get("total_trades", 0),
            }]
        except Exception as e:
            logger.error(f"VIX backtest failed: {e}")
            return [{"run_id": run_id, "error": str(e), "sharpe_ratio": 0}]

    def _store_results(self, run_id: str, best: Dict, all_results: List[Dict],
                        strategy: str = None, lookback: str = None):
        """Store backtest results using the configured backend (file or DB)."""
        try:
            best_trades = best.get("trades", [])
            store_backtest_results(run_id, best, all_results, best_trades,
                                   strategy=strategy, lookback=lookback)
        except Exception as e:
            logger.warning(f"Could not store results: {e}")
