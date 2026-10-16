#!/usr/bin/env python3
"""Paper-trade a strategy config on the Alpaca paper account with the LIVE runner (v0.50.0).

Since v0.50.0 this runs utils/btd_paper_runner.PaperRunner = utils/live_btd_runner.Runner on paper
keys, reading the SAME alpatrade.strategy_configs row as live (PAPER_STRATEGY_CONFIG, default the
operator Mag-7 config), so paper and live cannot diverge. The PAPER_DIP/TP/SL/HOLD env knobs below
are no longer used (edit the strategy config instead).


For *observing a specific strategy in the wild* (as opposed to the autonomy loop, which
re-optimises each cycle). Defaults to the walk-forward/methodology-validated PDT-safe
swing: buy 7% dips, 6% take-profit, 10% stop, hold 3-20 days (min-hold 3 = never a
same-day round trip). All env-overridable.

Env (percents; days):
  PAPER_DIP=7  PAPER_TP=6  PAPER_SL=10  PAPER_HOLD=20  PAPER_MIN_HOLD=3
  PAPER_SOURCE_LOOKBACK=1y
  PAPER_USER_ID=<user UUID>  PAPER_ACCOUNT_ID=<linked account UUID>  # recommended
  PAPER_CAPITAL_PER_TRADE=1000  PAPER_SYMBOLS=AAPL,MSFT,GOOGL,AMZN,META,TSLA,NVDA
  PAPER_DURATION_SECONDS=604800  PAPER_POLL_SECONDS=300

Run:  python scripts/run_paper_strategy.py           # runs for PAPER_DURATION_SECONDS
      PAPER_DURATION_SECONDS=30 python scripts/run_paper_strategy.py   # quick smoke
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass


def _env_f(k, d):
    try:
        return float(os.getenv(k, d))
    except ValueError:
        return float(d)


def enabled() -> bool:
    """Off unless PAPER_STRATEGY_ENABLED is truthy (paused 2026-10-12 at Julian's request)."""
    return os.getenv("PAPER_STRATEGY_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


def idle_forever() -> int:
    """Disabled: register no run and place no orders, but stay up so the compose
    healthcheck passes and `restart: unless-stopped` doesn't loop (each restart used
    to leave another orphaned 'running' paper run)."""
    import time
    print("paper-strategy disabled (PAPER_STRATEGY_ENABLED is not set); idling, no runs, no orders.")
    while True:
        time.sleep(3600)


def main() -> int:
    if not enabled():
        return idle_forever()
    user_id = os.getenv("PAPER_USER_ID", "").strip() or None
    account_id = os.getenv("PAPER_ACCOUNT_ID", "").strip() or None
    if bool(user_id) != bool(account_id):
        print("PAPER_USER_ID and PAPER_ACCOUNT_ID must be configured together.")
        return 2
    account_name = ""
    owned_keys = None
    if user_id and account_id:
        try:
            from engine.auth import get_alpaca_keys, get_user_accounts

            owned_keys = get_alpaca_keys(user_id, account_id)
            account = next(
                (item for item in get_user_accounts(user_id)
                 if item["account_id"] == account_id),
                None,
            )
            if not owned_keys or not account:
                print("Configured paper account is inactive, unavailable, or not owned by the user.")
                return 2
            account_name = str(account.get("account_name") or "")
        except Exception:  # noqa: BLE001
            print("Configured tenant paper credentials could not be resolved.")
            return 2

    # v0.50.0: paper = the LIVE runner on paper keys (utils/btd_paper_runner.PaperRunner): same
    # rules module (utils/btd_rules), same strategy_configs row, same schedule and broker orders.
    from utils.btd_paper_runner import PaperRunner, paper_config, run_paper
    from utils.live_btd_config import DEFAULT_STRATEGY
    from utils.live_btd_runner import PassStop, setup_logging
    strategy = os.getenv("PAPER_STRATEGY_CONFIG", DEFAULT_STRATEGY)
    key, secret = (owned_keys[0], owned_keys[1]) if owned_keys else (
        os.getenv("ALPACA_PAPER_API_KEY"), os.getenv("ALPACA_PAPER_SECRET_KEY"))
    db_url = os.getenv("DATABASE_URL")
    try:
        runner = PaperRunner(key, secret, strategy=strategy, database_url=db_url, log=setup_logging())
    except PassStop as exc:
        print(f"paper runner refused: {exc.code}")
        return 2
    print(f"Paper-trading strategy config {strategy!r} with the live runner on the paper account"
          f"{' ' + account_name if account_name else ''}")
    out = run_paper(runner, lambda: paper_config(strategy, db_url),
                    duration_s=_env_f("PAPER_DURATION_SECONDS", 10 * 365 * 86400))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
