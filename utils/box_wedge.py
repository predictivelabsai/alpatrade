"""
Box & Wedge Trading Strategy
Based on Christian Carion's methodology for index futures trading

Strategy Overview:
- Identifies price contraction periods (boxes) where market is range-bound
- Finds tighter contractions within boxes (wedges) - lower highs and higher lows
- Enters on wedge breakout (not full box breakout) for tighter stop-loss
- Aligns with hourly trend using EMAs
- Scales out: 50% at 1.5R, 25% at 3R, 25% runner
- Risk management: 1% account risk per trade
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import pytz

from utils.data_loader import get_intraday_data


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate technical indicators for Box & Wedge strategy
    
    Args:
        df: OHLCV DataFrame
    
    Returns:
        DataFrame with added indicators
    """
    df = df.copy()
    
    # EMAs for trend detection
    df['EMA9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['SMA200'] = df['Close'].rolling(window=200).mean()
    
    # ATR for volatility
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['ATR'] = true_range.rolling(window=14).mean()
    
    return df


def is_bullish_regime(df: pd.DataFrame, index: int) -> bool:
    """
    Check if market is in bullish regime (above 200 SMA)
    
    Args:
        df: DataFrame with indicators
        index: Current index position
    
    Returns:
        True if bullish, False otherwise
    """
    if index < 200 or pd.isna(df['SMA200'].iloc[index]):
        return True  # Default to True if not enough data
    
    return df['Close'].iloc[index] > df['SMA200'].iloc[index]


def find_box_contraction(df: pd.DataFrame, index: int, lookback: int = 100, 
                         contraction_threshold: float = 0.7) -> Tuple[bool, float, float]:
    """
    Identify if price is in a box (contraction period)
    
    Args:
        df: OHLCV DataFrame
        index: Current index position
        lookback: Periods to look back for range calculation
        contraction_threshold: Threshold for contraction (0.7 = 70% of average range)
    
    Returns:
        Tuple of (is_contracting, box_high, box_low)
    """
    if index < lookback:
        return False, 0, 0
    
    # Calculate recent range
    recent_data = df.iloc[max(0, index - lookback):index + 1]
    recent_high = recent_data['High'].max()
    recent_low = recent_data['Low'].min()
    recent_range = recent_high - recent_low
    
    # Calculate average historical range
    historical_data = df.iloc[max(0, index - lookback * 2):index + 1]
    avg_range = (historical_data['High'].rolling(lookback).max() - 
                 historical_data['Low'].rolling(lookback).min()).mean()
    
    # Check if contracting
    is_contracting = recent_range < (avg_range * contraction_threshold)
    
    return is_contracting, recent_high, recent_low


def find_wedge_within_box(df: pd.DataFrame, index: int, box_high: float, box_low: float,
                          wedge_lookback: int = 20) -> Tuple[bool, float, float]:
    """
    Identify wedge pattern within box (tighter contraction)
    
    Args:
        df: OHLCV DataFrame
        index: Current index position
        box_high: Box high price
        box_low: Box low price
        wedge_lookback: Periods to look back for wedge
    
    Returns:
        Tuple of (has_wedge, wedge_high, wedge_low)
    """
    if index < wedge_lookback:
        return False, 0, 0
    
    # Get recent data for wedge
    wedge_data = df.iloc[max(0, index - wedge_lookback):index + 1]
    wedge_high = wedge_data['High'].max()
    wedge_low = wedge_data['Low'].min()
    wedge_range = wedge_high - wedge_low
    
    box_range = box_high - box_low
    
    # Wedge should be tighter than box
    has_wedge = wedge_range < (box_range * 0.6) and wedge_range > 0
    
    return has_wedge, wedge_high, wedge_low


def calculate_position_size(capital: float, risk_pct: float, entry_price: float, 
                           stop_price: float) -> int:
    """
    Calculate position size based on risk percentage (Christian's "All-In" concept)
    
    Args:
        capital: Account capital
        risk_pct: Risk percentage (e.g., 0.01 for 1%)
        entry_price: Entry price
        stop_price: Stop loss price
    
    Returns:
        Number of shares/contracts
    """
    risk_amount = capital * risk_pct
    risk_per_share = abs(entry_price - stop_price)
    
    if risk_per_share == 0:
        return 0
    
    shares = int(risk_amount / risk_per_share)
    return shares


from utils.fees import calculate_finra_taf_fee, calculate_cat_fee


def backtest_box_wedge_strategy(
    symbols: List[str],
    start_date: datetime,
    end_date: datetime,
    initial_capital: float = 10000,
    risk_per_trade_pct: float = 1.0,
    contraction_threshold: float = 0.7,
    wedge_lookback: int = 20,
    box_lookback: int = 100,
    scale_out_1_5r_pct: float = 50.0,
    scale_out_3r_pct: float = 25.0,
    runner_pct: float = 25.0,
    interval: str = '5m',
    data_source: str = 'yfinance',
    include_taf_fees: bool = False,
    include_cat_fees: bool = False
) -> Tuple[pd.DataFrame, Dict]:
    """
    Backtest Box & Wedge strategy based on Christian Carion's methodology
    
    Strategy:
    1. Identify box (price contraction period)
    2. Find wedge within box (tighter contraction)
    3. Enter on wedge breakout (not full box breakout)
    4. Stop loss at wedge low
    5. Scale out: 50% at 1.5R, 25% at 3R, 25% runner
    
    Args:
        symbols: List of symbols (ES=F, NQ=F for futures)
        start_date: Backtest start date
        end_date: Backtest end date
        initial_capital: Starting capital
        risk_per_trade_pct: Risk per trade as percentage (default 1%)
        contraction_threshold: Box contraction threshold (default 0.7 = 70%)
        wedge_lookback: Periods to look back for wedge (default 20)
        box_lookback: Periods to look back for box (default 100)
        scale_out_1_5r_pct: Percentage to exit at 1.5R (default 50%)
        scale_out_3r_pct: Percentage to exit at 3R (default 25%)
        runner_pct: Percentage to keep as runner (default 25%)
        interval: Data interval ('2m', '5m', '15m', '1h')
        data_source: Data source ('yfinance')
        include_taf_fees: Include FINRA TAF fees
        include_cat_fees: Include CAT fees
    
    Returns:
        Tuple of (trades_df, metrics_dict)
    """
    
    # Import calculate_metrics from backtester_util
    from utils.backtester_util import calculate_metrics
    
    # Fetch data
    price_data = {}
    for symbol in symbols:
        df = get_intraday_data(symbol, interval=interval, period='30d')
        if not df.empty:
            # Calculate indicators
            df = calculate_indicators(df)
            price_data[symbol] = df
    
    if not price_data:
        return None
    
    trades = []
    capital = initial_capital
    
    # Make dates timezone-aware
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=pytz.UTC)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=pytz.UTC)
    
    # Iterate through each symbol
    for symbol in symbols:
        if symbol not in price_data:
            continue
        
        df = price_data[symbol]
        
        # Iterate through time periods
        for i in range(box_lookback, len(df)):
            current_time = df.index[i]
            
            # Skip if outside date range
            if current_time < start_date or current_time > end_date:
                continue
            
            # Check bullish regime (optional filter)
            if not is_bullish_regime(df, i):
                continue
            
            # Find box contraction
            is_contracting, box_high, box_low = find_box_contraction(
                df, i, box_lookback, contraction_threshold
            )
            
            if not is_contracting:
                continue
            
            # Find wedge within box
            has_wedge, wedge_high, wedge_low = find_wedge_within_box(
                df, i, box_high, box_low, wedge_lookback
            )
            
            if not has_wedge:
                continue
            
            # Check for wedge breakout
            current_price = float(df['Close'].iloc[i])
            current_high = float(df['High'].iloc[i])
            
            if current_high > wedge_high:
                # Entry signal - wedge breakout
                entry_price = current_price
                entry_time = current_time
                stop_price = wedge_low
                
                # Calculate position size based on risk
                shares = calculate_position_size(
                    capital, 
                    risk_per_trade_pct / 100, 
                    entry_price, 
                    stop_price
                )
                
                if shares == 0:
                    continue
                
                # Calculate R (risk per share)
                r_value = entry_price - stop_price
                
                # Calculate targets
                target_1_5r = entry_price + (1.5 * r_value)
                target_3r = entry_price + (3 * r_value)
                
                # Track position
                remaining_shares = shares
                total_pnl = 0
                exits = []
                
                # Look for exits in future data
                future_data = df.iloc[i + 1:min(i + 200, len(df))]  # Look ahead up to 200 periods
                
                for j, (future_time, row) in enumerate(future_data.iterrows()):
                    if remaining_shares == 0:
                        break
                    
                    # Check stop loss
                    if float(row['Low']) <= stop_price:
                        # Stop out entire remaining position
                        exit_pnl = (stop_price - entry_price) * remaining_shares
                        total_pnl += exit_pnl
                        exits.append({
                            'exit_time': future_time,
                            'exit_price': stop_price,
                            'shares': remaining_shares,
                            'reason': 'stop_loss',
                            'r_multiple': -1.0
                        })
                        remaining_shares = 0
                        break
                    
                    # Check 1.5R target
                    if float(row['High']) >= target_1_5r and scale_out_1_5r_pct > 0:
                        shares_to_exit = int(shares * (scale_out_1_5r_pct / 100))
                        if shares_to_exit > 0 and shares_to_exit <= remaining_shares:
                            exit_pnl = (target_1_5r - entry_price) * shares_to_exit
                            total_pnl += exit_pnl
                            exits.append({
                                'exit_time': future_time,
                                'exit_price': target_1_5r,
                                'shares': shares_to_exit,
                                'reason': '1.5R_target',
                                'r_multiple': 1.5
                            })
                            remaining_shares -= shares_to_exit
                            scale_out_1_5r_pct = 0  # Only exit once at this level
                    
                    # Check 3R target
                    if float(row['High']) >= target_3r and scale_out_3r_pct > 0:
                        shares_to_exit = int(shares * (scale_out_3r_pct / 100))
                        if shares_to_exit > 0 and shares_to_exit <= remaining_shares:
                            exit_pnl = (target_3r - entry_price) * shares_to_exit
                            total_pnl += exit_pnl
                            exits.append({
                                'exit_time': future_time,
                                'exit_price': target_3r,
                                'shares': shares_to_exit,
                                'reason': '3R_target',
                                'r_multiple': 3.0
                            })
                            remaining_shares -= shares_to_exit
                            scale_out_3r_pct = 0  # Only exit once at this level
                    
                    # Move stop to breakeven after 1.5R hit
                    if len(exits) > 0 and exits[-1]['reason'] == '1.5R_target':
                        stop_price = entry_price
                
                # If position still open at end, close at current price
                if remaining_shares > 0 and len(future_data) > 0:
                    final_price = float(future_data['Close'].iloc[-1])
                    final_time = future_data.index[-1]
                    exit_pnl = (final_price - entry_price) * remaining_shares
                    total_pnl += exit_pnl
                    exits.append({
                        'exit_time': final_time,
                        'exit_price': final_price,
                        'shares': remaining_shares,
                        'reason': 'runner_close',
                        'r_multiple': (final_price - entry_price) / r_value if r_value > 0 else 0
                    })
                
                # Calculate fees
                taf_fee = 0.0
                cat_fee_total = 0.0
                
                if include_cat_fees:
                    cat_fee_total += calculate_cat_fee(shares)  # Entry
                
                for exit in exits:
                    if include_taf_fees:
                        taf_fee += calculate_finra_taf_fee(exit['shares'])
                    if include_cat_fees:
                        cat_fee_total += calculate_cat_fee(exit['shares'])
                
                total_fees = taf_fee + cat_fee_total
                total_pnl -= total_fees
                
                capital += total_pnl
                pnl_pct = (total_pnl / (entry_price * shares)) * 100 if shares > 0 else 0
                
                # Record trade
                if exits:
                    final_exit = exits[-1]
                    trades.append({
                        'entry_time': entry_time,
                        'exit_time': final_exit['exit_time'],
                        'ticker': symbol,
                        'direction': 'long',
                        'shares': shares,
                        'entry_price': entry_price,
                        'exit_price': final_exit['exit_price'],  # Last exit price
                        'target_price': target_3r,
                        'stop_price': wedge_low,
                        'hit_target': any(e['reason'] in ['1.5R_target', '3R_target'] for e in exits),
                        'hit_stop': any(e['reason'] == 'stop_loss' for e in exits),
                        'pnl': total_pnl,
                        'pnl_pct': pnl_pct,
                        'capital_after': capital,
                        'box_high': box_high,
                        'box_low': box_low,
                        'wedge_high': wedge_high,
                        'wedge_low': wedge_low,
                        'num_exits': len(exits),
                        'taf_fee': taf_fee,
                        'cat_fee': cat_fee_total,
                        'total_fees': total_fees
                    })
    
    if not trades:
        return None
    
    # Create trades dataframe
    trades_df = pd.DataFrame(trades)
    
    # Calculate metrics
    metrics = calculate_metrics(trades_df, initial_capital, start_date, end_date)
    
    return trades_df, metrics
