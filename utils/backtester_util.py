"""
Backtesting Utility for Strategy Simulator
Core utilities and backward-compatible wrappers for trading strategies
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import yfinance as yf

# Import strategies from modular files
from utils.buy_the_dip import backtest_buy_the_dip as _backtest_buy_the_dip
from utils.momentum import backtest_momentum_strategy as _backtest_momentum_strategy
from utils.vix_strategy import backtest_vix_strategy as _backtest_vix_strategy
from utils.box_wedge import backtest_box_wedge_strategy


def get_intraday_data(ticker: str, interval: str = '1d', period: str = '30d') -> pd.DataFrame:
    """
    Fetch intraday or daily data from yfinance
    
    Args:
        ticker: Stock symbol
        interval: Data interval ('1d', '60m', '30m', '15m', '5m')
        period: Time period ('30d', '7d', '1d')
    
    Returns:
        DataFrame with OHLCV data
    """
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval=interval)
        
        if df.empty:
            print(f"Warning: No data returned for {ticker} with interval {interval}")
            return pd.DataFrame()
        
        # Ensure timezone-aware datetime index
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        else:
            df.index = df.index.tz_convert('UTC')
        
        return df
    except Exception as e:
        print(f"Error fetching data for {ticker}: {str(e)}")
        return pd.DataFrame()


def calculate_metrics(trades_df: pd.DataFrame, initial_capital: float, 
                     start_date: datetime, end_date: datetime) -> Dict:
    """Calculate backtest performance metrics"""
    
    if trades_df.empty:
        return {
            'total_return': 0.0,
            'total_pnl': 0.0,
            'win_rate': 0.0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'annualized_return': 0.0,
            'max_drawdown': 0.0,
            'sharpe_ratio': 0.0
        }
    
    final_capital = trades_df['capital_after'].iloc[-1]
    total_pnl = final_capital - initial_capital
    total_return = (total_pnl / initial_capital) * 100
    
    winning_trades = len(trades_df[trades_df['pnl'] > 0])
    losing_trades = len(trades_df[trades_df['pnl'] < 0])
    total_trades = len(trades_df)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    # Calculate annualized return (simple arithmetic annualisation)
    days = (end_date - start_date).days
    annualized_return = (total_return * 365.25 / days) if days > 0 else 0
    
    # Calculate max drawdown
    equity_curve = trades_df['capital_after'].values
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - running_max) / running_max
    max_drawdown = abs(drawdown.min()) * 100 if len(drawdown) > 0 else 0
    
    # Calculate Sharpe ratio (simplified)
    returns = trades_df['pnl_pct'].values
    sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
    
    return {
        'total_return': total_return,
        'total_pnl': total_pnl,
        'win_rate': win_rate,
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'annualized_return': annualized_return,
        'max_drawdown': max_drawdown,
        'sharpe_ratio': sharpe_ratio
    }


def get_historical_data(symbols: List[str], start_date: datetime, 
                       end_date: datetime) -> Dict[str, pd.DataFrame]:
    """Fetch historical price data for multiple symbols"""
    data = {}
    for symbol in symbols:
        try:
            df = yf.download(symbol, start=start_date, end=end_date, progress=False)
            if not df.empty:
                data[symbol] = df
        except Exception as e:
            print(f"Error fetching data for {symbol}: {e}")
    return data


def calculate_buy_and_hold(symbols: List[str], start_date: datetime, end_date: datetime,
                          initial_capital: float = 10000) -> Tuple[pd.Series, pd.Series]:
    """
    Calculate buy-and-hold returns for a portfolio of symbols
    
    Args:
        symbols: List of stock symbols
        start_date: Start date for buy-and-hold
        end_date: End date for buy-and-hold
        initial_capital: Starting capital
    
    Returns:
        Tuple of (dates, portfolio_values) as pandas Series
    """
    # Fetch historical data
    price_data = get_historical_data(symbols, start_date, end_date)
    
    if not price_data:
        return pd.Series(), pd.Series()
    
    # Get all unique dates across all symbols
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    
    all_dates = sorted([d for d in all_dates if start_date <= d <= end_date])
    
    if not all_dates:
        return pd.Series(), pd.Series()
    
    # Calculate equal-weighted portfolio
    portfolio_values = []
    dates = []
    
    # Allocate capital equally across symbols
    capital_per_symbol = initial_capital / len(symbols) if symbols else initial_capital
    
    for date in all_dates:
        total_value = 0
        valid_date = False
        
        for symbol in symbols:
            if symbol not in price_data:
                continue
            
            df = price_data[symbol]
            # Get data up to current date
            historical = df[df.index <= date]
            
            if len(historical) == 0:
                continue
            
            # Get entry price (first available price)
            entry_data = df[df.index >= start_date]
            if len(entry_data) == 0:
                continue
            
            entry_price = float(entry_data['Close'].iloc[0])
            entry_date = entry_data.index[0]
            
            # Only calculate if we've passed entry date
            if date >= entry_date:
                current_price = float(historical['Close'].iloc[-1])
                shares = capital_per_symbol / entry_price
                total_value += shares * current_price
                valid_date = True
        
        if valid_date:
            dates.append(date)
            portfolio_values.append(total_value)
    
    if not dates:
        return pd.Series(), pd.Series()
    
    return pd.Series(dates), pd.Series(portfolio_values, index=dates)


def calculate_single_buy_and_hold(symbol: str, start_date: datetime, end_date: datetime,
                                 initial_capital: float = 10000) -> Tuple[pd.Series, pd.Series]:
    """
    Calculate buy-and-hold returns for a single symbol
    
    Args:
        symbol: Stock symbol
        start_date: Start date for buy-and-hold
        end_date: End date for buy-and-hold
        initial_capital: Starting capital
    
    Returns:
        Tuple of (dates, portfolio_values) as pandas Series
    """
    return calculate_buy_and_hold([symbol], start_date, end_date, initial_capital)


def calculate_finra_taf_fee(shares: int) -> float:
    """
    Calculate FINRA Trading Activity Fee (TAF) for a sell order
    
    TAF: $0.000166 per share (sells only)
    - Rounded up to nearest penny
    - Capped at $8.30 per trade
    
    Args:
        shares: Number of shares being sold
    
    Returns:
        Fee amount in dollars
    """
    if shares <= 0:
        return 0.0
    
    fee_per_share = 0.000166
    raw_fee = shares * fee_per_share
    
    # Round up to nearest penny
    fee = np.ceil(raw_fee * 100) / 100
    
    # Cap at $8.30
    fee = min(fee, 8.30)
    
    return fee


def calculate_cat_fee(shares: int) -> float:
    """
    Calculate Consolidated Audit Trail (CAT) fee for a trade
    
    CAT Fee: $0.0000265 per share (applies to both buys and sells)
    - For NMS Equities: 1:1 ratio
    - For OTC Equities: 1:0.01 ratio (we assume NMS for regular stocks)
    - No cap mentioned
    
    Args:
        shares: Number of shares being traded
    
    Returns:
        Fee amount in dollars
    """
    if shares <= 0:
        return 0.0
    
    # CAT Fee Rate for NMS Equities: $0.0000265 per share
    fee_per_share = 0.0000265
    fee = shares * fee_per_share
    
    return fee


def backtest_buy_the_dip(symbols: List[str], start_date: datetime, end_date: datetime,
                        initial_capital: float = 10000, position_size: float = 0.1,
                        dip_threshold: float = 0.02, hold_days: int = 1,
                        take_profit: float = 0.01, stop_loss: float = 0.005,
                        interval: str = '1d', data_source: str = 'massive',
                        include_taf_fees: bool = False, include_cat_fees: bool = False,
                        pdt_protection: Optional[bool] = None,
                        extended_hours: bool = False,
                        intraday_exit: bool = False) -> Tuple[pd.DataFrame, Dict, pd.DataFrame]:
    """
    Backtest buy-the-dip strategy (wrapper for backward compatibility)

    Strategy: Buy when stock drops by dip_threshold from recent high,
              hold for hold_days or until take_profit/stop_loss hit

    Args:
        symbols: List of stock symbols to trade
        start_date: Backtest start date
        end_date: Backtest end date
        initial_capital: Starting capital
        position_size: Fraction of capital to use per trade
        dip_threshold: Percentage drop to trigger buy (e.g., 0.02 = 2%)
        hold_days: Days/periods to hold position
        take_profit: Take profit percentage (e.g., 0.01 = 1%)
        stop_loss: Stop loss percentage (e.g., 0.005 = 0.5%)
        interval: Data interval ('1d', '60m', '30m', '15m', '5m')
        data_source: Data source ('yfinance' or 'massive')
        include_taf_fees: Include FINRA TAF fees
        include_cat_fees: Include Consolidated Audit Trail fees
        pdt_protection: If True, prevents same-day exits
        extended_hours: If True, allow trades during 4AM-8PM ET
        intraday_exit: If True, use 5-min bars for precise TP/SL exit timing

    Returns:
        Tuple of (trades_df, metrics_dict)
    """
    return _backtest_buy_the_dip(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        position_size=position_size,
        dip_threshold=dip_threshold,
        hold_days=hold_days,
        take_profit=take_profit,
        stop_loss=stop_loss,
        interval=interval,
        data_source=data_source,
        include_taf_fees=include_taf_fees,
        include_cat_fees=include_cat_fees,
        pdt_protection=pdt_protection,
        extended_hours=extended_hours,
        intraday_exit=intraday_exit,
    )



def backtest_vix_strategy(symbols: List[str], start_date: datetime, end_date: datetime,
                         initial_capital: float = 10000, position_size: float = 0.1,
                         vix_threshold: float = 20, hold_overnight: bool = True) -> Tuple[pd.DataFrame, Dict]:
    """
    Backtest VIX fear index strategy (wrapper for backward compatibility)
    
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
    return _backtest_vix_strategy(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        position_size=position_size,
        vix_threshold=vix_threshold,
        hold_overnight=hold_overnight
    )



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
    Backtest momentum trading strategy (wrapper for backward compatibility)
    
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
    return _backtest_momentum_strategy(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        position_size_pct=position_size_pct,
        lookback_period=lookback_period,
        momentum_threshold=momentum_threshold,
        hold_days=hold_days,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        interval=interval,
        data_source=data_source,
        include_taf_fees=include_taf_fees,
        include_cat_fees=include_cat_fees
    )

