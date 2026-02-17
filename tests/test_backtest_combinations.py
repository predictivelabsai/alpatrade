#!/usr/bin/env python3
"""
Test script to run different backtest combinations as described in TUI_README.md
"""
import os
import sys
from datetime import datetime, timedelta
import pandas as pd
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from utils.backtester_util import backtest_buy_the_dip, backtest_momentum_strategy

def run_test_combinations():
    print("Starting backtest combinations test...")
    
    # Ensure results directory exists
    results_dir = Path("backtest-results")
    results_dir.mkdir(exist_ok=True)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=60)
    
    test_cases = [
        {
            "name": "Buy-The-Dip (1d)",
            "fn": backtest_buy_the_dip,
            "params": {
                "symbols": ["AAPL", "MSFT"],
                "start_date": start_date,
                "end_date": end_date,
                "initial_capital": 10000,
                "position_size": 0.1,
                "dip_threshold": 0.02,
                "hold_days": 1,
                "interval": "1d",
                "include_taf_fees": True,
                "include_cat_fees": True,
                "pdt_protection": True
            }
        },
        {
            "name": "Buy-The-Dip (60m)",
            "fn": backtest_buy_the_dip,
            "params": {
                "symbols": ["AAPL", "MSFT", "TSLA", "NVDA"],
                "start_date": end_date - timedelta(days=30),
                "end_date": end_date,
                "initial_capital": 10000,
                "position_size": 0.1,
                "dip_threshold": 0.002,
                "hold_days": 1,
                "interval": "60m",
                "include_taf_fees": True,
                "include_cat_fees": True,
                "pdt_protection": True
            }
        }
    ]
    
    summary_data = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for case in test_cases:
        print(f"\nRunning test case: {case['name']}")
        try:
            results = case["fn"](**case["params"])
            if results:
                trades_df, metrics = results[0], results[1]
                print(f"Success! {len(trades_df)} trades generated.")
                print(f"Total Return: {metrics['total_return']:.2f}%")
                
                # Save to backtest-results
                case_name_slug = case["name"].lower().replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_")
                filename = f"backtests_details_{case_name_slug}_{timestamp}.csv"
                trades_df.to_csv(results_dir / filename, index=False)
                print(f"Results saved to {results_dir / filename}")
                
                summary_data.append({
                    "name": case["name"],
                    "trades": len(trades_df),
                    "return": f"{metrics['total_return']:.2f}%",
                    "win_rate": f"{metrics['win_rate']:.2f}%",
                    "pnl": f"${metrics['total_pnl']:.2f}",
                    "file": filename
                })
            else:
                print("No trades generated for this case.")
        except Exception as e:
            print(f"Error running case {case['name']}: {e}")

    # Generate Markdown Summary
    if summary_data:
        summary_filename = f"backtest_summary_{timestamp}.md"
        summary_path = results_dir / summary_filename
        
        md_content = f"# Backtest Summary - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        md_content += "| Strategy Name | Trades | Total Return | Win Rate | Total P&L | CSV Result |\n"
        md_content += "|---------------|--------|--------------|----------|-----------|------------|\n"
        
        for s in summary_data:
            md_content += f"| {s['name']} | {s['trades']} | {s['return']} | {s['win_rate']} | {s['pnl']} | [{s['file']}]({s['file']}) |\n"
        
        with open(summary_path, "w") as f:
            f.write(md_content)
        
        print(f"\nSummary report generated: {summary_path}")

if __name__ == "__main__":
    run_test_combinations()
