#!/usr/bin/env python3
"""
Backtest Validator - Criticizes Buy-The-Dip backtest results
Checks for market hours, weekend trades, and logic consistency.
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
from pathlib import Path

def validate_results():
    results_dir = Path("backtest-results")
    if not results_dir.exists():
        print(f"Error: {results_dir} does not exist.")
        return

    csv_files = list(results_dir.glob("backtests_details_*.csv"))
    if not csv_files:
        print("No Buy-The-Dip backtest results found to validate.")
        return

    for csv_file in csv_files:
        print(f"\n--- Validating {csv_file.name} ---")
        try:
            df = pd.read_csv(csv_file)
            if df.empty:
                print("  Empty file.")
                continue

            # Convert times to aware datetimes and localize to US/Eastern
            df['entry_time'] = pd.to_datetime(df['entry_time'])
            df['exit_time'] = pd.to_datetime(df['exit_time'])
            
            eastern = pytz.timezone('US/Eastern')

            anomalies = []

            for idx, row in df.iterrows():
                # Get times in Eastern
                entry_et = row['entry_time']
                if entry_et.tzinfo is not None:
                    entry_et = entry_et.astimezone(eastern)
                else:
                    entry_et = pytz.utc.localize(entry_et).astimezone(eastern)
                    
                exit_et = row['exit_time']
                if exit_et.tzinfo is not None:
                    exit_et = exit_et.astimezone(eastern)
                else:
                    exit_et = pytz.utc.localize(exit_et).astimezone(eastern)

                # 1. Weekend check
                if entry_et.weekday() >= 5:
                    anomalies.append(f"Row {idx}: Entry on weekend ({entry_et.strftime('%A')} ET)")
                if exit_et.weekday() >= 5:
                    anomalies.append(f"Row {idx}: Exit on weekend ({exit_et.strftime('%A')} ET)")

                # 2. Market hours check (4 AM - 8 PM EST)
                entry_hour = entry_et.hour
                exit_hour = exit_et.hour
                
                if not (4 <= entry_hour < 20):
                    anomalies.append(f"Row {idx}: Entry hour {entry_hour} ET is outside 4 AM - 8 PM window")
                if not (4 <= exit_hour < 20):
                    # Exit can be exactly 20:00 if it's the last bar of the day
                    if not (exit_hour == 20 and exit_et.minute == 0):
                        anomalies.append(f"Row {idx}: Exit hour {exit_hour} ET is outside 4 AM - 8 PM window")

                # 3. P&L Logic check
                expected_pnl = (row['exit_price'] - row['entry_price']) * row['shares'] - row['total_fees']
                if not np.isclose(row['pnl'], expected_pnl, atol=0.01):
                    anomalies.append(f"Row {idx}: P&L mismatch. Expected ${expected_pnl:.2f}, got ${row['pnl']:.2f}")

                # 4. TP/SL check (if columns exist)
                if 'TP' in row and 'SL' in row:
                    if row['TP'] == 1 and row['SL'] == 1:
                        anomalies.append(f"Row {idx}: Both TP and SL marked as hit!")
                    
                    if row['TP'] == 1 and not np.isclose(row['exit_price'], row['target_price'], atol=0.01):
                        anomalies.append(f"Row {idx}: TP hit but exit price ${row['exit_price']:.2f} != target price ${row['target_price']:.2f}")
                    
                    if row['SL'] == 1 and not np.isclose(row['exit_price'], row['stop_price'], atol=0.01):
                        anomalies.append(f"Row {idx}: SL hit but exit price ${row['exit_price']:.2f} != stop price ${row['stop_price']:.2f}")

            if anomalies:
                print(f"  Found {len(anomalies)} anomalies:")
                for a in anomalies[:10]: # Show first 10
                    print(f"    - {a}")
                if len(anomalies) > 10:
                    print(f"    ... and {len(anomalies) - 10} more.")
            else:
                print("  ✅ No anomalies found. Logic looks consistent with parameters.")

        except Exception as e:
            print(f"  Error validating file: {e}")

if __name__ == "__main__":
    validate_results()
