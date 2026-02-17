"""
Test script to compare strategy performance across different intervals
"""

import sys
sys.path.append('/home/ubuntu/strategy-simulator')

from datetime import datetime, timedelta
from utils.backtester_util import backtest_buy_the_dip, backtest_momentum_strategy
import pandas as pd

# Test configuration
SYMBOLS = ['AAPL', 'MSFT', 'NVDA']
INITIAL_CAPITAL = 10000
END_DATE = datetime.now()
START_DATE = END_DATE - timedelta(days=30)

# Test intervals
INTERVALS = ['1d', '60m', '30m', '15m', '5m']

def test_buy_the_dip():
    """Test buy-the-dip strategy across intervals"""
    print("\n" + "="*80)
    print("TESTING BUY-THE-DIP STRATEGY")
    print("="*80)
    
    results = []
    
    for interval in INTERVALS:
        print(f"\nTesting interval: {interval}")
        print("-" * 40)
        
        try:
            result = backtest_buy_the_dip(
                symbols=SYMBOLS,
                start_date=START_DATE,
                end_date=END_DATE,
                initial_capital=INITIAL_CAPITAL,
                position_size=0.1,
                dip_threshold=0.02,
                hold_days=1,
                take_profit=0.01,
                stop_loss=0.005,
                interval=interval,
                data_source='yfinance'
            )
            
            if result:
                trades_df, metrics = result
                results.append({
                    'interval': interval,
                    'total_return': metrics['total_return'],
                    'win_rate': metrics['win_rate'],
                    'total_trades': metrics['total_trades'],
                    'sharpe_ratio': metrics['sharpe_ratio'],
                    'max_drawdown': metrics['max_drawdown']
                })
                print(f"✓ Total Return: {metrics['total_return']:.2f}%")
                print(f"✓ Win Rate: {metrics['win_rate']:.2f}%")
                print(f"✓ Total Trades: {metrics['total_trades']}")
                print(f"✓ Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
            else:
                print("✗ No trades generated")
                results.append({
                    'interval': interval,
                    'total_return': 0,
                    'win_rate': 0,
                    'total_trades': 0,
                    'sharpe_ratio': 0,
                    'max_drawdown': 0
                })
        except Exception as e:
            print(f"✗ Error: {str(e)}")
            results.append({
                'interval': interval,
                'total_return': 0,
                'win_rate': 0,
                'total_trades': 0,
                'sharpe_ratio': 0,
                'max_drawdown': 0
            })
    
    return pd.DataFrame(results)

def test_momentum():
    """Test momentum strategy across intervals"""
    print("\n" + "="*80)
    print("TESTING MOMENTUM STRATEGY")
    print("="*80)
    
    results = []
    
    for interval in INTERVALS:
        print(f"\nTesting interval: {interval}")
        print("-" * 40)
        
        try:
            result = backtest_momentum_strategy(
                symbols=SYMBOLS,
                start_date=START_DATE,
                end_date=END_DATE,
                initial_capital=INITIAL_CAPITAL,
                position_size_pct=10.0,
                lookback_period=20,
                momentum_threshold=5.0,
                hold_days=5,
                take_profit_pct=10.0,
                stop_loss_pct=5.0,
                interval=interval,
                data_source='yfinance'
            )
            
            if result:
                # Result is now a tuple (trades_df, metrics)
                trades_df, metrics = result
                results.append({
                    'interval': interval,
                    'total_return': metrics['total_return'],
                    'win_rate': metrics['win_rate'],
                    'total_trades': metrics['total_trades'],
                    'sharpe_ratio': metrics['sharpe_ratio'],
                    'max_drawdown': metrics['max_drawdown']
                })
                print(f"✓ Total Return: {metrics['total_return']:.2f}%")
                print(f"✓ Win Rate: {metrics['win_rate']:.2f}%")
                print(f"✓ Total Trades: {metrics['total_trades']}")
                print(f"✓ Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
            else:
                print("✗ No trades generated")
                results.append({
                    'interval': interval,
                    'total_return': 0,
                    'win_rate': 0,
                    'total_trades': 0,
                    'sharpe_ratio': 0,
                    'max_drawdown': 0
                })
        except Exception as e:
            print(f"✗ Error: {str(e)}")
            results.append({
                'interval': interval,
                'total_return': 0,
                'win_rate': 0,
                'total_trades': 0,
                'sharpe_ratio': 0,
                'max_drawdown': 0
            })
    
    return pd.DataFrame(results)

if __name__ == "__main__":
    print("\nStrategy Interval Performance Test")
    print(f"Symbols: {SYMBOLS}")
    print(f"Period: {START_DATE.date()} to {END_DATE.date()}")
    print(f"Initial Capital: ${INITIAL_CAPITAL:,}")
    
    # Test buy-the-dip
    btd_results = test_buy_the_dip()
    
    # Test momentum
    momentum_results = test_momentum()
    
    # Display summary
    print("\n" + "="*80)
    print("SUMMARY - BUY-THE-DIP STRATEGY")
    print("="*80)
    print(btd_results.to_string(index=False))
    
    print("\n" + "="*80)
    print("SUMMARY - MOMENTUM STRATEGY")
    print("="*80)
    print(momentum_results.to_string(index=False))
    
    # Save results
    btd_results.to_csv('/home/ubuntu/strategy-simulator/tests/btd_interval_results.csv', index=False)
    momentum_results.to_csv('/home/ubuntu/strategy-simulator/tests/momentum_interval_results.csv', index=False)
    
    print("\n✓ Results saved to tests/ directory")
