#!/usr/bin/env python3
"""
Headless Agent Runner

Executes the AlpaTrade orchestrator in a background process.
Designed to be spawned by utils/agent_runner.py.

Usage:
  python run_agent.py --run-id UUID --mode paper --user-id UUID [--account-id UUID] --config '{"strategy": "buy_the_dip", ...}'
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Ensure we can import from the project root
sys.path.insert(0, str(Path(__file__).parent.absolute()))

from agents.orchestrator import Orchestrator

# Set up logging to a general paper trade log (or separate file if needed)
LOG_FILE = Path(__file__).parent / "data" / "paper_trade.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("headless_agent")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", required=True, choices=["backtest", "paper", "full", "validate", "reconcile"])
    parser.add_argument("--user-id", required=False, default=None)
    parser.add_argument("--account-id", required=False, default=None)
    parser.add_argument("--config", required=True, help="JSON string config")
    
    args = parser.parse_args()

    try:
        config = json.loads(args.config)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse config JSON: {e}")
        sys.exit(1)

    logger.info(f"Starting headless agent: mode={args.mode}, run_id={args.run_id}, user={args.user_id}, account={args.account_id}")

    # Instantiate Orchestrator
    orch = Orchestrator(user_id=args.user_id, account_id=args.account_id)
    # Override the generated run_id with the one provided by the runner
    # so we can track it from the database immediately.
    orch.run_id = args.run_id
    orch.state.run_id = args.run_id

    # Execute based on mode
    if args.mode == "paper":
        # Create an event that never sets, so paper trading runs for the duration specified in config
        stop_event = asyncio.Event() 
        orch.run_paper_trade(config, stop_event=stop_event)
    elif args.mode == "backtest":
        orch.run_backtest(config)
    elif args.mode == "full":
        orch.run_full(config)
    elif args.mode == "reconcile":
        orch.run_reconciliation(config)
    elif args.mode == "validate":
        # Validate requires source_run_id and source parameters
        orch.run_validation(run_id=config.get("source_run_id"), source=config.get("source", "backtest"))

    logger.info(f"Headless agent {args.run_id} completed successfully.")

if __name__ == "__main__":
    main()
