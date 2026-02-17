"""
Lightweight test runner to exercise backtest_buy_the_dip similarly to Streamlit.
Writes results (trades CSV and metrics JSON) to test-results/ for multiple parameter sets.
"""

import os
import sys
import json
from datetime import datetime, timedelta

# Ensure project root is on sys.path so we can import utils.*
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.backtester_util import backtest_buy_the_dip


def ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def run_case(case_name: str,
             symbols,
             start_date: datetime,
             end_date: datetime,
             initial_capital: float,
             position_size_pct: float,
             dip_threshold_pct: float,
             hold_days: int,
             take_profit_pct: float,
             stop_loss_pct: float,
             out_dir: str) -> None:
    """
    Run a single backtest case and write outputs.
    """
    print(f"Running case: {case_name}")
    results = backtest_buy_the_dip(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        position_size=position_size_pct / 100.0,
        dip_threshold=dip_threshold_pct / 100.0,
        hold_days=hold_days,
        take_profit=take_profit_pct / 100.0,
        stop_loss=stop_loss_pct / 100.0
    )

    case_dir = os.path.join(out_dir, case_name)
    ensure_dir(case_dir)

    if results is None:
        print(f"  No trades generated for case: {case_name}")
        with open(os.path.join(case_dir, "no_trades.txt"), "w") as f:
            f.write("No trades were generated for this case.\n")
        return

    trades_df, metrics = results

    trades_csv_path = os.path.join(case_dir, "trades.csv")
    metrics_json_path = os.path.join(case_dir, "metrics.json")

    trades_df.to_csv(trades_csv_path, index=False)
    with open(metrics_json_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    print(f"  Wrote: {trades_csv_path}")
    print(f"  Wrote: {metrics_json_path}")


def main() -> None:
    out_dir = os.path.join(os.getcwd(), "test-results")
    ensure_dir(out_dir)

    # Use a modest window to keep runtime down and reduce API calls
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)

    # A small set of symbols to test quickly
    symbols = ["AAPL", "MSFT", "NVDA", "SPY"]

    param_grid = [
        {
            "name": "default",
            "initial_capital": 10000,
            "position_size_pct": 10.0,
            "dip_threshold_pct": 2.0,
            "hold_days": 1,
            "take_profit_pct": 1.0,
            "stop_loss_pct": 0.5,
        },
        {
            "name": "deeper_dip_longer_hold",
            "initial_capital": 10000,
            "position_size_pct": 10.0,
            "dip_threshold_pct": 5.0,
            "hold_days": 3,
            "take_profit_pct": 2.0,
            "stop_loss_pct": 1.0,
        },
        {
            "name": "smaller_positions_tighter_stops",
            "initial_capital": 5000,
            "position_size_pct": 5.0,
            "dip_threshold_pct": 3.0,
            "hold_days": 2,
            "take_profit_pct": 1.0,
            "stop_loss_pct": 0.3,
        },
    ]

    summary = []
    errors_path = os.path.join(out_dir, "errors.log")
    with open(errors_path, "w") as err_log:
        for params in param_grid:
            case_name = params["name"]
            try:
                run_case(
                    case_name=case_name,
                    symbols=symbols,
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=params["initial_capital"],
                    position_size_pct=params["position_size_pct"],
                    dip_threshold_pct=params["dip_threshold_pct"],
                    hold_days=params["hold_days"],
                    take_profit_pct=params["take_profit_pct"],
                    stop_loss_pct=params["stop_loss_pct"],
                    out_dir=out_dir,
                )
                summary.append({"case": case_name, "status": "ok"})
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                err_msg = f"Case {case_name} failed: {e}\n{tb}\n"
                print("  ERROR:", err_msg.strip())
                err_log.write(err_msg)
                summary.append({"case": case_name, "status": "error", "error": str(e)})

    # Write summary JSON
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print("Done. Summary written to test-results/summary.json")
    print(f"Any errors were recorded in: {errors_path}")


if __name__ == "__main__":
    main()


