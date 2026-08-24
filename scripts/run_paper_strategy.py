#!/usr/bin/env python3
"""Paper-trade a FIXED strategy config live on the Alpaca paper account.

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


def main() -> int:
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

    symbols = [s.strip().upper() for s in os.getenv(
        "PAPER_SYMBOLS", "AAPL,MSFT,GOOGL,AMZN,META,TSLA,NVDA").split(",") if s.strip()]
    params = {
        "dip_threshold": _env_f("PAPER_DIP", 7.0),
        "take_profit_threshold": _env_f("PAPER_TP", 6.0),
        "stop_loss_threshold": _env_f("PAPER_SL", 10.0),
        "hold_days": int(_env_f("PAPER_HOLD", 20)),
        "min_hold_days": int(_env_f("PAPER_MIN_HOLD", 3)),
        "capital_per_trade": _env_f("PAPER_CAPITAL_PER_TRADE", 1000.0),
    }
    request = {
        "strategy": "buy_the_dip", "symbols": symbols, "params": params,
        "duration_seconds": int(_env_f("PAPER_DURATION_SECONDS", 604800)),
        "poll_interval_seconds": int(_env_f("PAPER_POLL_SECONDS", 300)),
        "extended_hours": False, "email_notifications": False,
    }
    print(f"Paper-trading buy_the_dip on {symbols}")
    print(f"  dip {params['dip_threshold']}% / TP {params['take_profit_threshold']}% / "
          f"SL {params['stop_loss_threshold']}% / hold {params['min_hold_days']}-{params['hold_days']}d "
          f"(min-hold {params['min_hold_days']}d = PDT-safe) / ${params['capital_per_trade']:.0f}/trade")
    print(f"  duration {request['duration_seconds']}s, poll {request['poll_interval_seconds']}s\n")

    # Register a run so paper trades persist to alpatrade.runs/trades (avoids the FK).
    import uuid
    run_id = str(uuid.uuid4())
    try:
        from utils.agent_storage import store_run
        from utils.strategy_slug import build_slug
        lookback = os.getenv("PAPER_SOURCE_LOOKBACK", "1y")
        slug_params = {
            "dip_threshold": params["dip_threshold"] / 100,
            "take_profit": params["take_profit_threshold"] / 100,
            "stop_loss": params["stop_loss_threshold"] / 100,
            "hold_days": params["hold_days"],
            "min_hold_days": params["min_hold_days"],
        }
        store_run(
            run_id,
            "paper",
            strategy="buy_the_dip",
            config={"params": params, "symbols": symbols, "lookback": lookback},
            strategy_slug=build_slug("buy_the_dip", slug_params, lookback),
            user_id=user_id,
            account_id=account_id,
        )
    except Exception as e:  # noqa: BLE001
        print(f"  (run registration skipped: {type(e).__name__})")
        if user_id:
            print("  refusing to trade because the tenant-scoped run was not persisted")
            return 2

    from agents.paper_trade_agent import PaperTradeAgent
    from utils.agent_storage import update_run
    if not user_id:
        print("  note: unscoped legacy run; set PAPER_USER_ID/PAPER_ACCOUNT_ID for advisor attribution")
    try:
        result = PaperTradeAgent(
            user_id=user_id,
            account_id=account_id,
            account_name=account_name,
            alpaca_api_key=owned_keys[0] if owned_keys else None,
            alpaca_secret_key=owned_keys[1] if owned_keys else None,
        ).run(request, run_id=run_id)
        update_run(run_id, "failed" if result.get("error") else "completed", results=result)
    except BaseException as exc:
        update_run(run_id, "stopped" if isinstance(exc, KeyboardInterrupt) else "failed",
                   results={"error": str(exc)})
        raise
    print(f"  run_id: {run_id}")
    print("\nSESSION SUMMARY:")
    for k in ("session_id", "total_trades", "buy_trades", "sell_trades", "total_pnl", "final_equity"):
        if k in result:
            print(f"  {k}: {result[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
