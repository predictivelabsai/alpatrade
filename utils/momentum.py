"""
Momentum Trading Strategy
Buys when stock shows strong upward momentum over lookback period
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

from utils.massive_util import MassiveUtil
from utils.data_loader import get_intraday_data
from utils.fees import calculate_finra_taf_fee, calculate_cat_fee
massive_util = MassiveUtil()


def backtest_momentum_strategy(
    symbols: List[str],
    start_date: datetime,
    end_date: datetime,
    initial_capital: float = 10000,
    position_size_pct: float = 10.0,
    lookback_period: int = 20,
    momentum_threshold: float = 5.0,
    hold_days: int = 5,
    take_profit_pct: Optional[float] = 10.0,
    stop_loss_pct: Optional[float] = 5.0,
    interval: str = '1d',
    data_source: str = 'massive',
    include_taf_fees: bool = False,
    include_cat_fees: bool = False
) -> Dict:
    """
    Backtest momentum trading strategy
    
    Strategy Logic:
    - Buy when stock shows strong upward momentum (price increase > threshold over lookback period)
    - Hold for specified number of days or until take profit/stop loss hit
    - Exit at take profit or stop loss if set
    
    Args:
        symbols: List of stock symbols to trade
        start_date: Backtest start date
        end_date: Backtest end date
        initial_capital: Starting capital
        position_size_pct: Percentage of capital per trade
        lookback_period: Days to look back for momentum calculation
        momentum_threshold: Minimum momentum percentage to trigger buy
        hold_days: Number of days to hold position
        take_profit_pct: Take profit percentage (optional)
        stop_loss_pct: Stop loss percentage (optional)
        
    Returns:
        Dictionary with backtest results and metrics
    """
    
    # Import calculate_metrics from backtester_util
    from utils.backtester_util import calculate_metrics
    
    trades = []
    capital = initial_capital
    
    for symbol in symbols:
        try:
            # Download historical data based on source
            if data_source == 'massive':
                # Use Massive (with yf fallback)
                # Estimate start date for intraday if needed
                data_start = start_date - timedelta(days=60)
                historical = massive_util.get_historical_data(symbol, data_start, end_date, timeframe='minute' if interval != '1d' else 'day', interval=1)
                
            elif data_source == 'yfinance' and interval != '1d':
                historical = get_intraday_data(symbol, interval=interval, period='30d')
            else:
                ticker_obj = yf.Ticker(symbol)
                historical = ticker_obj.history(start=start_date, end=end_date)
            
            if historical is None or (isinstance(historical, pd.DataFrame) and historical.empty):
                continue
            
            # Iterate through dates
            for i in range(lookback_period, len(historical)):
                current_date = historical.index[i]
                
                # Calculate momentum
                lookback_start_price = float(historical['Close'].iloc[i - lookback_period])
                current_price = float(historical['Close'].iloc[i])
                momentum_pct = ((current_price - lookback_start_price) / lookback_start_price) * 100
                
                # Check if momentum threshold is met
                if momentum_pct >= momentum_threshold:
                    # Calculate position size
                    position_value = capital * (position_size_pct / 100)
                    shares = int(position_value / current_price)
                    
                    if shares > 0:
                        entry_price = current_price
                        entry_date = current_date
                        
                        # Calculate exit levels
                        target_price = entry_price * (1 + take_profit_pct / 100) if take_profit_pct else None
                        stop_price = entry_price * (1 - stop_loss_pct / 100) if stop_loss_pct else None
                        
                        # Look for exit
                        exit_date = None
                        exit_price = None
                        exit_reason = 'hold_period'
                        
                        # Check future prices for exit
                        future_data = historical.iloc[i+1:min(i+1+hold_days, len(historical))]
                        
                        for j, row in enumerate(future_data.iterrows()):
                            date, data = row
                            
                            # Check take profit
                            if target_price and float(data['High']) >= target_price:
                                exit_date = date
                                exit_price = target_price
                                exit_reason = 'take_profit'
                                break
                            
                            # Check stop loss
                            if stop_price and float(data['Low']) <= stop_price:
                                exit_date = date
                                exit_price = stop_price
                                exit_reason = 'stop_loss'
                                break
                        
                        # If no exit triggered, exit at end of hold period
                        if exit_date is None and len(future_data) > 0:
                            exit_date = future_data.index[-1]
                            exit_price = float(future_data['Close'].iloc[-1])
                        
                        # Record trade if exit found
                        if exit_date and exit_price:
                            pnl = (exit_price - entry_price) * shares
                            
                            # Calculate fees
                            taf_fee = 0.0
                            cat_fee_buy = 0.0
                            cat_fee_sell = 0.0
                            total_fees = 0.0
                            
                            # CAT fee on buy (entry)
                            if include_cat_fees:
                                cat_fee_buy = calculate_cat_fee(shares)
                                total_fees += cat_fee_buy
                            
                            # TAF fee on sell (exit only)
                            if include_taf_fees:
                                taf_fee = calculate_finra_taf_fee(shares)
                                total_fees += taf_fee
                            
                            # CAT fee on sell (exit)
                            if include_cat_fees:
                                cat_fee_sell = calculate_cat_fee(shares)
                                total_fees += cat_fee_sell
                            
                            # Subtract all fees from P&L
                            pnl -= total_fees
                            
                            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                            capital += pnl
                            
                            # Align columns to UI expectations (ticker/entry_time/exit_time/pnl_pct etc.)
                            trades.append({
                                'ticker': symbol,
                                'entry_time': entry_date,
                                'exit_time': exit_date,
                                'entry_price': entry_price,
                                'exit_price': exit_price,
                                'shares': shares,
                                'pnl': pnl,
                                'pnl_pct': pnl_pct,
                                'capital_after': capital,
                                # Momentum-specific fields
                                'exit_reason': exit_reason,
                                'momentum_pct': momentum_pct,
                                # Placeholder fields used by UI for other strategies
                                'hit_target': exit_reason == 'take_profit',
                                'hit_stop': exit_reason == 'stop_loss',
                                'dip_pct': np.nan,
                                'taf_fee': taf_fee,
                                'cat_fee': cat_fee_buy + cat_fee_sell,
                                'total_fees': total_fees
                            })
        
        except Exception as e:
            print(f"Error processing {symbol}: {str(e)}")
            continue
    
    # Convert trades to DataFrame
    if not trades:
        return None
    
    trades_df = pd.DataFrame(trades).sort_values('exit_time')
    
    # Calculate metrics
    metrics = calculate_metrics(trades_df, initial_capital, start_date, end_date)
    
    # Return in (trades_df, metrics) format to match UI expectations
    return trades_df, metrics
