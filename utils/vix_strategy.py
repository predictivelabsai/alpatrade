"""
VIX Fear Index Trading Strategy
Buys when VIX exceeds threshold (high fear), holds overnight or same day
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

from utils.data_loader import get_historical_data


def backtest_vix_strategy(symbols: List[str], start_date: datetime, end_date: datetime,
                         initial_capital: float = 10000, position_size: float = 0.1,
                         vix_threshold: float = 20, hold_overnight: bool = True) -> Tuple[pd.DataFrame, Dict]:
    """
    Backtest VIX fear index strategy
    
    Strategy: Buy when VIX > threshold (high fear), hold overnight or until next day
    
    Args:
        symbols: List of stock symbols to trade
        start_date: Backtest start date
        end_date: Backtest end date
        initial_capital: Starting capital
        position_size: Fraction of capital to use per trade
        vix_threshold: VIX level to trigger buy
        hold_overnight: Whether to hold overnight (True) or sell same day (False)
    
    Returns:
        Tuple of (trades_df, metrics_dict)
    """
    
    # Import calculate_metrics from backtester_util
    from utils.backtester_util import calculate_metrics
    
    # Fetch VIX data
    vix_data = yf.download('^VIX', start=start_date, end=end_date, progress=False)
    
    if vix_data.empty:
        return None
    
    # Fetch stock data
    price_data = get_historical_data(symbols, start_date, end_date)
    
    if not price_data:
        return None
    
    trades = []
    capital = initial_capital
    
    # Iterate through VIX data
    for idx, vix_row in vix_data.iterrows():
        vix_close = float(vix_row['Close'])
        
        # Check if VIX exceeds threshold
        if vix_close > vix_threshold:
            trade_date = idx
            
            for symbol in symbols:
                if symbol not in price_data:
                    continue
                
                df = price_data[symbol]
                
                # Get entry price
                if trade_date not in df.index:
                    continue
                
                entry_price = float(df.loc[trade_date, 'Close'])
                entry_time = trade_date
                shares = int((capital * position_size) / entry_price)
                
                if shares == 0:
                    continue
                
                # Determine exit time
                if hold_overnight:
                    exit_time = entry_time + timedelta(days=1)
                else:
                    exit_time = entry_time
                
                # Get exit price
                future_data = df[df.index > entry_time]
                if future_data.empty:
                    continue
                
                exit_row = future_data.iloc[0]
                exit_price = float(exit_row['Close'])
                actual_exit_time = exit_row.name
                
                # Calculate P&L
                pnl = (exit_price - entry_price) * shares
                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                capital += pnl
                
                # Record trade
                trades.append({
                    'entry_time': entry_time,
                    'exit_time': actual_exit_time,
                    'ticker': symbol,
                    'direction': 'long',
                    'shares': shares,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'target_price': 0,
                    'stop_price': 0,
                    'hit_target': False,
                    'hit_stop': False,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'capital_after': capital,
                    'vix_level': vix_close
                })
    
    if not trades:
        return None
    
    # Create trades dataframe
    trades_df = pd.DataFrame(trades)
    
    # Calculate metrics
    metrics = calculate_metrics(trades_df, initial_capital, start_date, end_date)
    
    return trades_df, metrics
