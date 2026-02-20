#!/usr/bin/env python3
"""
Portfolio Manager / Orchestrator

Main entry point for the multi-agent trading system.
Coordinates Backtester, Paper Trader, and Validator agents.

Usage:
    python agents/orchestrator.py --mode full
    python agents/orchestrator.py --mode backtest
    python agents/orchestrator.py --mode validate --run-id <uuid>
    python agents/orchestrator.py --mode paper --duration 1h
"""

import sys
import uuid
import argparse
import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

# Ensure project root is importable
project_root = Path(__file__).parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from agents.shared.message_bus import MessageBus
from agents.shared.state import PortfolioState
from utils.config import load_parameters
from agents.backtest_agent import BacktestAgent
from agents.paper_trade_agent import PaperTradeAgent
from agents.validate_agent import ValidateAgent
from agents.reconcile_agent import ReconcileAgent
from utils.agent_storage import store_run, update_run, store_validation
from utils.strategy_slug import build_slug

logger = logging.getLogger(__name__)


def parse_duration(s: str) -> int:
    """Parse duration string to seconds: '1h', '30m', '7d', '300s'."""
    s = s.strip().lower()
    if s.endswith("d"):
        return int(s[:-1]) * 86400
    elif s.endswith("h"):
        return int(s[:-1]) * 3600
    elif s.endswith("m"):
        return int(s[:-1]) * 60
    elif s.endswith("s"):
        return int(s[:-1])
    else:
        return int(s)


class Orchestrator:
    """Portfolio Manager that coordinates all agents."""

    def __init__(self):
        self.run_id = str(uuid.uuid4())
        self.bus = MessageBus()
        self.state = PortfolioState.load()
        self.state.run_id = self.run_id
        self.state.started_at = datetime.now(timezone.utc).isoformat()

        # Initialize agents
        self.backtester = BacktestAgent(message_bus=self.bus, state=self.state)
        self.paper_trader = PaperTradeAgent(message_bus=self.bus, state=self.state)
        self.validator = ValidateAgent(message_bus=self.bus, state=self.state)
        self.reconciler = ReconcileAgent(message_bus=self.bus, state=self.state)

        # Initialize agent states
        for name in ["backtester", "paper_trader", "validator", "reconciler"]:
            self.state.get_agent(name).set_idle()

        self._mode = None  # set by run_* methods
        self._config = None
        logger.info(f"Orchestrator initialized. Run ID: {self.run_id}")

    def run_backtest(self, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """Run backtesting phase."""
        config = config or {}
        self._config = config
        if self._mode is None:
            self._mode = "backtest"
            self.state.mode = "backtest"
            store_run(self.run_id, "backtest",
                      strategy=config.get("strategy", "buy_the_dip"),
                      config=config)
        agent_state = self.state.get_agent("backtester")
        agent_state.set_running("parameterized_backtest")
        self.state.save()

        logger.info("=" * 60)
        logger.info("PHASE 1: BACKTESTING")
        logger.info("=" * 60)

        request = {
            "strategy": config.get("strategy", "buy_the_dip"),
            "symbols": config.get("symbols", ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"]),
            "lookback": config.get("lookback", "3m"),
            "initial_capital": config.get("initial_capital", 10000),
            "data_source": config.get("data_source", "massive"),
            "variations": config.get("variations"),
            "run_id": self.run_id,
            "extended_hours": config.get("extended_hours", True),
            "intraday_exit": config.get("intraday_exit", False),
            "pdt_protection": config.get("pdt_protection"),
        }

        # Publish request to bus
        self.bus.publish(
            from_agent="portfolio_manager",
            to_agent="backtester",
            msg_type="backtest_request",
            payload=request,
        )

        try:
            result = self.backtester.run(request)
            agent_state.set_completed()
            self.state.backtest_results.append(result)
            self.state.best_config = result.get("best_config")
            self.state.save()
            if self._mode == "backtest":
                update_run(self.run_id, "completed", results=result)

            best = result.get("best_config", {})
            logger.info(
                f"Backtest complete: {result.get('total_variations', 0)} variations, "
                f"best Sharpe={best.get('sharpe_ratio', 0):.2f}, "
                f"return={best.get('total_return', 0):.1f}%"
            )
            return result

        except Exception as e:
            agent_state.set_error(str(e))
            self.state.save()
            if self._mode == "backtest":
                update_run(self.run_id, "failed", results={"error": str(e)})
            logger.error(f"Backtest failed: {e}")
            return {"error": str(e)}

    def run_validation(self, run_id: str = None, source: str = "backtest",
                       trades: list = None) -> Dict[str, Any]:
        """Run validation phase."""
        if self._mode is None:
            self._mode = "validate"
            self.state.mode = "validate"
            store_run(self.run_id, "validate", config={"source_run_id": run_id})
        agent_state = self.state.get_agent("validator")
        agent_state.set_running("trade_validation")
        self.state.save()

        logger.info("=" * 60)
        logger.info(f"PHASE: VALIDATION (source={source})")
        logger.info("=" * 60)

        # Pass extended_hours from stored config if available
        ext_hours = True
        if self._config:
            ext_hours = self._config.get("extended_hours", True)

        request = {
            "run_id": run_id or self.run_id,
            "source": source,
            "trades": trades,
            "extended_hours": ext_hours,
        }

        self.bus.publish(
            from_agent="portfolio_manager",
            to_agent="validator",
            msg_type="validation_request",
            payload=request,
        )

        try:
            result = self.validator.run(request)
            agent_state.set_completed()
            agent_state.iteration_count = result.get("iterations_used", 0)
            self.state.validation_results.append(result)
            self.state.save()
            store_validation(request.get("run_id", self.run_id), result)

            status = result.get("status", "unknown")
            anomalies = result.get("anomalies_found", 0)
            logger.info(f"Validation {status}: {anomalies} anomalies found")

            if status == "failed":
                logger.warning("Validation FAILED. Suggestions:")
                for s in result.get("suggestions", []):
                    logger.warning(f"  - {s}")

            if self._mode == "validate":
                update_run(self.run_id, status, results=result)
            return result

        except Exception as e:
            agent_state.set_error(str(e))
            self.state.save()
            if self._mode == "validate":
                update_run(self.run_id, "failed", results={"error": str(e)})
            logger.error(f"Validation failed: {e}")
            return {"error": str(e)}

    def run_paper_trade(self, config: Dict[str, Any] = None, stop_event=None) -> Dict[str, Any]:
        """Run paper trading phase."""
        config = config or {}
        self._config = config
        if self._mode is None:
            self._mode = "paper"
            self.state.mode = "paper"
            # Build slug from best config params or paper config
            best = self.state.best_config or {}
            paper_params = best.get("params", {})
            paper_slug = build_slug(
                config.get("strategy", "buy_the_dip"),
                paper_params,
                config.get("lookback", ""),
            ) if paper_params else None
            store_run(self.run_id, "paper",
                      strategy=config.get("strategy", "buy_the_dip"),
                      config=config,
                      strategy_slug=paper_slug)
        agent_state = self.state.get_agent("paper_trader")
        agent_state.set_running("paper_trading")
        self.state.save()

        logger.info("=" * 60)
        logger.info("PHASE: PAPER TRADING")
        logger.info("=" * 60)

        # Use best config from backtest if available
        best = self.state.best_config or {}
        params = best.get("params", {})

        # Load defaults from parameters.yaml
        yaml_params = load_parameters()
        yaml_cfg = yaml_params.get("buy_the_dip", {})
        yaml_general = yaml_params.get("general", {})
        yaml_symbols = [s.strip() for s in yaml_cfg.get("symbols", "").split(",") if s.strip()]

        request = {
            "strategy": config.get("strategy", "buy_the_dip"),
            "symbols": params.get("symbols", config.get("symbols",
                       yaml_symbols or ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"])),
            "params": {
                "dip_threshold": params.get("dip_threshold", yaml_cfg.get("dip_threshold", 5.0)) * 100 if params.get("dip_threshold", 1) < 1 else params.get("dip_threshold", yaml_cfg.get("dip_threshold", 5.0)),
                "take_profit_threshold": params.get("take_profit", yaml_cfg.get("take_profit_threshold", 1.0)) * 100 if params.get("take_profit", 1) < 1 else params.get("take_profit", yaml_cfg.get("take_profit_threshold", 1.0)),
                "stop_loss_threshold": params.get("stop_loss", yaml_cfg.get("stop_loss_threshold", 0.5)) * 100 if params.get("stop_loss", 1) < 1 else params.get("stop_loss", yaml_cfg.get("stop_loss_threshold", 0.5)),
                "hold_days": params.get("hold_days", yaml_cfg.get("hold_days", 2)),
                "capital_per_trade": config.get("capital_per_trade", yaml_cfg.get("capital_per_trade", 1000.0)),
            },
            "duration_seconds": config.get("duration_seconds", 604800),
            "poll_interval_seconds": config.get("poll_interval_seconds", yaml_general.get("polling_interval", 300)),
            "extended_hours": config.get("extended_hours", True),
            "email_notifications": config.get("email_notifications", True),
            "pdt_protection": config.get("pdt_protection"),
        }

        self.bus.publish(
            from_agent="portfolio_manager",
            to_agent="paper_trader",
            msg_type="paper_trade_start",
            payload=request,
        )

        try:
            result = self.paper_trader.run(request, stop_event=stop_event)
            agent_state.set_completed()
            self.state.paper_trade_session = result
            self.state.save()
            if self._mode == "paper":
                update_run(self.run_id, "completed", results=result)

            logger.info(
                f"Paper trading complete: {result.get('total_trades', 0)} trades, "
                f"P&L: ${result.get('total_pnl', 0):.2f}"
            )
            return result

        except Exception as e:
            agent_state.set_error(str(e))
            self.state.save()
            if self._mode == "paper":
                update_run(self.run_id, "failed", results={"error": str(e)})
            logger.error(f"Paper trading failed: {e}")
            return {"error": str(e)}

    def run_full(self, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Run full cycle: Backtest -> Validate -> Paper Trade -> Validate.
        """
        config = config or {}
        self._mode = "full"
        self._config = config
        store_run(self.run_id, "full",
                  strategy=config.get("strategy", "buy_the_dip"),
                  config=config)
        self.state.mode = "full"
        self.state.save()

        logger.info("=" * 60)
        logger.info("FULL CYCLE: BT -> Validate -> PT -> Validate")
        logger.info(f"Run ID: {self.run_id}")
        logger.info("=" * 60)

        results = {"run_id": self.run_id, "phases": {}}

        # Phase 1: Backtest
        bt_result = self.run_backtest(config)
        results["phases"]["backtest"] = bt_result
        if "error" in bt_result:
            results["status"] = "failed_at_backtest"
            self._save_final(results)
            return results

        # Phase 2: Validate backtest (pass trades directly so validator doesn't need DB)
        bt_trades = bt_result.get("trades", [])
        val1_result = self.run_validation(source="backtest", trades=bt_trades)
        results["phases"]["backtest_validation"] = val1_result
        if val1_result.get("status") == "failed":
            logger.warning("Backtest validation failed. Continuing with caution.")

        # Phase 3: Paper trade
        pt_result = self.run_paper_trade(config)
        results["phases"]["paper_trade"] = pt_result
        if "error" in pt_result:
            results["status"] = "failed_at_paper_trade"
            self._save_final(results)
            return results

        # Phase 4: Validate paper trades
        val2_result = self.run_validation(source="paper_trade")
        results["phases"]["paper_trade_validation"] = val2_result

        # Final status
        if val2_result.get("status") == "failed":
            results["status"] = "completed_with_warnings"
        else:
            results["status"] = "completed"

        self._save_final(results)

        logger.info("=" * 60)
        logger.info(f"FULL CYCLE COMPLETE: {results['status']}")
        logger.info("=" * 60)

        return results

    def run_reconciliation(self, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """Run reconciliation against Alpaca actual holdings."""
        config = config or {}
        if self._mode is None:
            self._mode = "reconcile"
            self.state.mode = "reconcile"
            store_run(self.run_id, "reconcile", config=config)
        agent_state = self.state.get_agent("reconciler")
        agent_state.set_running("reconciliation")
        self.state.save()

        logger.info("=" * 60)
        logger.info("PHASE: RECONCILIATION")
        logger.info("=" * 60)

        request = {
            "run_id": self.run_id,
            "window_days": config.get("window_days", 7),
        }

        self.bus.publish(
            from_agent="portfolio_manager",
            to_agent="reconciler",
            msg_type="reconciliation_request",
            payload=request,
        )

        try:
            result = self.reconciler.run(request)
            agent_state.set_completed()
            self.state.save()
            if self._mode == "reconcile":
                update_run(self.run_id,
                           status=result.get("status", "completed"),
                           results=result)

            total = result.get("total_issues", 0)
            logger.info(f"Reconciliation complete: {total} issues found")
            return result

        except Exception as e:
            agent_state.set_error(str(e))
            self.state.save()
            if self._mode == "reconcile":
                update_run(self.run_id, "failed", results={"error": str(e)})
            logger.error(f"Reconciliation failed: {e}")
            return {"error": str(e)}

    def _save_final(self, results: Dict):
        """Save final results and state."""
        self.state.completed_at = datetime.now(timezone.utc).isoformat()
        self.state.run_history.append({
            "run_id": self.run_id,
            "status": results.get("status"),
            "started_at": self.state.started_at,
            "completed_at": self.state.completed_at,
        })
        self.state.save()
        update_run(self.run_id,
                   status=results.get("status", "completed"),
                   results=results)

        # Also save results to a report file
        report_path = Path("data") / f"agent_run_{self.run_id}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(results, indent=2, default=str))
        logger.info(f"Report saved to {report_path}")

    def print_status(self):
        """Print current state summary."""
        print(f"\nRun ID: {self.state.run_id}")
        print(f"Mode: {self.state.mode}")
        print(f"Started: {self.state.started_at}")
        print(f"\nAgent Status:")
        for name, agent in self.state.agents.items():
            print(f"  {name}: {agent.status} (task: {agent.current_task})")
        if self.state.best_config:
            print(f"\nBest Config: {json.dumps(self.state.best_config, indent=2, default=str)}")
        if self.state.validation_results:
            last = self.state.validation_results[-1]
            print(f"\nLast Validation: {last.get('status')} ({last.get('anomalies_found', 0)} anomalies)")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="AlpaTrade Multi-Agent Orchestrator"
    )
    parser.add_argument(
        "--mode",
        choices=["backtest", "validate", "paper", "full", "reconcile", "status"],
        default="full",
        help="Execution mode",
    )
    parser.add_argument("--run-id", help="Run ID for validation mode")
    parser.add_argument("--duration", default="7d", help="Paper trading duration (e.g. 1h, 7d)")
    parser.add_argument("--window", type=int, default=7, help="Reconciliation window in days")
    parser.add_argument("--strategy", default="buy_the_dip", help="Strategy name")
    parser.add_argument(
        "--symbols",
        default="AAPL,MSFT,GOOGL,AMZN,META,TSLA,NVDA",
        help="Comma-separated symbols",
    )
    parser.add_argument("--lookback", default="3m", help="Backtest lookback (1m, 3m, 6m, 1y)")
    parser.add_argument("--capital", type=float, default=10000, help="Initial capital")
    parser.add_argument("--poll-interval", type=int, default=300, help="Paper trade poll interval (seconds)")
    parser.add_argument("--log-level", default="INFO", help="Log level")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("agent_orchestrator.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    symbols = [s.strip().upper() for s in args.symbols.split(",")]

    config = {
        "strategy": args.strategy,
        "symbols": symbols,
        "lookback": args.lookback,
        "initial_capital": args.capital,
        "duration_seconds": parse_duration(args.duration),
        "poll_interval_seconds": args.poll_interval,
    }

    orch = Orchestrator()

    if args.mode == "status":
        orch.print_status()
        return

    if args.mode == "backtest":
        result = orch.run_backtest(config)
    elif args.mode == "validate":
        result = orch.run_validation(run_id=args.run_id)
    elif args.mode == "paper":
        result = orch.run_paper_trade(config)
    elif args.mode == "full":
        result = orch.run_full(config)
    elif args.mode == "reconcile":
        result = orch.run_reconciliation({"window_days": args.window})
    else:
        parser.print_help()
        return

    print(f"\nResult: {json.dumps(result, indent=2, default=str)[:2000]}")


if __name__ == "__main__":
    main()
