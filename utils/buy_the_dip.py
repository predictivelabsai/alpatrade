"""
Buy-The-Dip Trading Strategy
Buys when stock drops by threshold from recent high, holds for specified days or until take profit/stop loss
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import pytz
from utils.massive_util import is_market_open, MassiveUtil
from utils.pdt_tracker import PDTTracker
from utils.data_loader import get_intraday_data, get_historical_data
from utils.fees import calculate_finra_taf_fee, calculate_cat_fee
massive_util = MassiveUtil()


def _check_intraday_exit(symbol: str, trade: Dict, current_date,
                         intraday_data: Dict[str, pd.DataFrame],
                         pdt_tracker: Optional[PDTTracker]) -> Optional[Dict]:
    """
    Check intraday bars for TP/SL exit within a single day.

    Returns dict with exit_price, exit_time, hit_tp, hit_sl if triggered,
    or None if neither TP nor SL was hit intraday.
    """
    if symbol not in intraday_data:
        return None

    idf = intraday_data[symbol]
    if idf.empty:
        return None

    # Filter to bars on this calendar day
    day_date = current_date.date() if hasattr(current_date, 'date') else current_date
    day_bars = idf[idf.index.date == day_date]
    if day_bars.empty:
        return None

    # PDT check: block same-day exit if tracker says we can't day trade
    is_same_day = day_date == trade['entry_date_raw']
    if is_same_day and pdt_tracker and not pdt_tracker.can_day_trade(day_date):
        return None

    for bar_time, bar in day_bars.iterrows():
        bar_low = float(bar['Low'])
        bar_high = float(bar['High'])

        # Check SL first (more conservative — assume adverse move happens first)
        if bar_low <= trade['stop_price']:
            return {
                'exit_price': trade['stop_price'],
                'exit_time': bar_time,
                'hit_tp': False,
                'hit_sl': True,
            }
        if bar_high >= trade['target_price']:
            return {
                'exit_price': trade['target_price'],
                'exit_time': bar_time,
                'hit_tp': True,
                'hit_sl': False,
            }

    return None


def backtest_buy_the_dip(symbols: List[str], start_date: datetime, end_date: datetime,
                        initial_capital: float = 10000, position_size: float = 0.1,
                        dip_threshold: float = 0.02, hold_days: int = 2,
                        take_profit: float = 0.01, stop_loss: float = 0.005,
                        interval: str = '1d', data_source: str = 'massive',
                        include_taf_fees: bool = False, include_cat_fees: bool = False,
                        pdt_protection: Optional[bool] = None,
                        extended_hours: bool = False,
                        intraday_exit: bool = False) -> Tuple[pd.DataFrame, Dict]:
    """
    Backtest buy-the-dip strategy
    
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
        pdt_protection: If True, prevents same-day exits. Defaults to True if initial_capital < $25k.
        extended_hours: If True, allow trades during 4AM-8PM ET (pre-market + after-hours).
        intraday_exit: If True, use 5-min intraday bars to determine exact TP/SL exit
                       within the day (determines which hits first). No same-day re-entry.

    Returns:
        Tuple of (trades_df, metrics_dict, equity_df)
    """
    
    # Import calculate_metrics from backtester_util
    from utils.backtester_util import calculate_metrics
    
    # Set PDT status and create tracker
    if pdt_protection is None:
        pdt_active = initial_capital < 25000
    else:
        pdt_active = pdt_protection

    pdt_tracker = PDTTracker() if pdt_active else None
    
    # Determine lookback_periods based on interval
    # We want approx 20 trading days of lookback
    if interval == '1d':
        lookback_periods = 20
        period = '40d' # Fetch enough data for lookback
    else:
        # For intraday, we need many more bars to cover 20 trading days
        # E.g., for 60m data, there are 16 bars per day (4am-8pm)
        # 20 days * 16 bars = 320 periods
        bars_per_day = 16 if interval == '60m' else 192 if interval == '5m' else 960 if interval == '1m' else 20
        lookback_periods = 20 * bars_per_day
        period = '60d'
    
    # Fetch data based on source
    price_data = {}
    if data_source == 'massive':
        # Use Massive (with yf fallback)
        from datetime import datetime
        # Estimate start date for intraday if needed
        data_start = start_date - timedelta(days=60)
        for symbol in symbols:
            # For backtesting, we might need a range of dates. 
            # MassiveUtil._get_massive_historical returns a range.
            df = massive_util.get_historical_data(symbol, data_start, end_date, timeframe='minute' if interval != '1d' else 'day', interval=1)
            if not df.empty:
                # Ensure timezone aware
                if df.index.tz is None:
                    df.index = df.index.tz_localize('UTC')
                price_data[symbol] = df
                
    elif (data_source == 'yfinance' and interval != '1d'):
        # Use intraday data from yfinance
        for symbol in symbols:
            df = get_intraday_data(symbol, interval=interval, period=period)
            if not df.empty:
                price_data[symbol] = df
    else:
        # Use daily data from yfinance
        price_data = get_historical_data(symbols, start_date - timedelta(days=40), end_date)
    
    if not price_data:
        return None

    # Pre-fetch intraday data for exit precision when intraday_exit is enabled
    intraday_data = {}
    if intraday_exit and interval == '1d':
        data_start_intra = start_date - timedelta(days=5)
        for symbol in symbols:
            try:
                idf = massive_util.get_historical_data(
                    symbol, data_start_intra, end_date,
                    timeframe='minute', interval=5,
                )
                if not idf.empty:
                    if idf.index.tz is None:
                        idf.index = idf.index.tz_localize('UTC')
                    intraday_data[symbol] = idf
            except Exception:
                pass

    trades = []
    available_capital = initial_capital
    active_trades = {} # ticker: trade_info
    exited_today = set()  # symbols exited today (no same-day re-entry)
    
    # Standardize timezones
    is_aware = False
    for symbol in symbols:
        if symbol in price_data and not price_data[symbol].empty:
            if price_data[symbol].index.tz is not None:
                is_aware = True
                break
    
    if is_aware:
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=pytz.UTC)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=pytz.UTC)
    else:
        if start_date.tzinfo is not None:
            start_date = start_date.replace(tzinfo=None)
        if end_date.tzinfo is not None:
            end_date = end_date.replace(tzinfo=None)
    
    # Get all unique timestamps from the data within range
    all_timestamps = set()
    for df in price_data.values():
        all_timestamps.update(df.index)
    
    sorted_timestamps = sorted([t for t in all_timestamps if start_date <= t <= end_date])
    
    equity_curve = []
    prev_date = None

    for current_date in sorted_timestamps:
        # Adjust time for daily data reporting
        display_time = current_date
        if interval == '1d':
            eastern = pytz.timezone('US/Eastern')
            if display_time.tzinfo is None:
                display_time = pytz.utc.localize(display_time).astimezone(eastern)
            else:
                display_time = display_time.astimezone(eastern)
            display_time = display_time.replace(hour=9, minute=30)

        # Reset daily exit tracking on date change
        if prev_date is None or current_date.date() != prev_date.date():
            exited_today = set()
        prev_date = current_date

        # 1. PROCESS EXITS FIRST (Chronological order)
        closed_this_tick = []
        for symbol, trade in active_trades.items():
            df = price_data[symbol]
            current_bar = df.loc[current_date]

            # Default exit display time
            exit_display_time = current_date
            if interval == '1d':
                eastern = pytz.timezone('US/Eastern')
                if exit_display_time.tzinfo is None:
                    exit_display_time = pytz.utc.localize(exit_display_time).astimezone(eastern)
                else:
                    exit_display_time = exit_display_time.astimezone(eastern)
                exit_display_time = exit_display_time.replace(hour=16, minute=0)

            # PDT Check using tracker
            is_same_day = current_date.date() == trade['entry_date_raw']
            can_day_trade = not is_same_day or (pdt_tracker is None or pdt_tracker.can_day_trade(current_date))

            # Try intraday exit first for precise TP/SL ordering
            intraday_result = None
            if intraday_exit and can_day_trade and intraday_data:
                intraday_result = _check_intraday_exit(
                    symbol, trade, current_date, intraday_data, pdt_tracker
                )

            if intraday_result:
                hit_tp = intraday_result['hit_tp']
                hit_sl = intraday_result['hit_sl']
                exit_price = intraday_result['exit_price']
                exit_display_time = intraday_result['exit_time']
                if hasattr(exit_display_time, 'astimezone'):
                    exit_display_time = exit_display_time.astimezone(pytz.timezone('US/Eastern'))
            else:
                hit_tp = can_day_trade and float(current_bar['High']) >= trade['target_price']
                hit_sl = can_day_trade and float(current_bar['Low']) <= trade['stop_price']
                hit_end = current_date >= trade['max_exit_time']

                if not (hit_tp or hit_sl or hit_end):
                    continue

                exit_price = trade['target_price'] if hit_tp else trade['stop_price'] if hit_sl else float(current_bar['Close'])

            # Record the closed trade
            pnl = (exit_price - trade['entry_price']) * trade['shares']

            taf_fee = calculate_finra_taf_fee(trade['shares']) if include_taf_fees else 0.0
            cat_fee_buy = calculate_cat_fee(trade['shares']) if include_cat_fees else 0.0
            cat_fee_sell = calculate_cat_fee(trade['shares']) if include_cat_fees else 0.0
            total_fees = taf_fee + cat_fee_buy + cat_fee_sell

            pnl -= total_fees
            available_capital += (trade['entry_price'] * trade['shares']) + pnl
            pnl_pct = ((exit_price - trade['entry_price']) / trade['entry_price']) * 100

            # Calculate total equity (Cash + Market Value of REMAINING positions)
            total_market_value = 0
            for open_symbol, open_trade in active_trades.items():
                if open_symbol == symbol:
                    continue
                try:
                    cur_p = float(price_data[open_symbol].loc[current_date, 'Close'])
                except KeyError:
                    cur_p = float(price_data[open_symbol][:current_date]['Close'].iloc[-1])
                total_market_value += open_trade['shares'] * cur_p

            total_equity = available_capital + total_market_value

            trades.append({
                'entry_time': trade['entry_time'],
                'exit_time': exit_display_time,
                'ticker': symbol,
                'direction': 'long',
                'shares': trade['shares'],
                'entry_price': trade['entry_price'],
                'exit_price': exit_price,
                'target_price': trade['target_price'],
                'stop_price': trade['stop_price'],
                'hit_target': hit_tp,
                'hit_stop': hit_sl and not hit_tp,
                'TP': 1 if hit_tp else 0,
                'SL': 1 if hit_sl and not hit_tp else 0,
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'capital_after': total_equity,
                'dip_pct': trade['dip_pct'] * 100,
                'taf_fee': taf_fee,
                'cat_fee': cat_fee_buy + cat_fee_sell,
                'total_fees': total_fees
            })
            closed_this_tick.append(symbol)
            exited_today.add(symbol)

            # Record day trade in PDT tracker if same-day exit
            if is_same_day and pdt_tracker:
                pdt_tracker.record_day_trade(current_date, symbol)

        for symbol in closed_this_tick:
            del active_trades[symbol]

        # 2. PROCESS ENTRIES
        if not is_market_open(display_time, extended_hours=extended_hours):
            continue

        for symbol in symbols:
            if symbol not in price_data or symbol in active_trades:
                continue
            
            df = price_data[symbol]
            historical = df[df.index <= current_date]
            if len(historical) < lookback_periods:
                continue
            
            recent_high = float(historical['High'].tail(lookback_periods).max())
            current_price = float(historical['Close'].iloc[-1])
            dip_pct = (recent_high - current_price) / recent_high
            
            if dip_pct >= dip_threshold:
                # Enter trade
                shares = int((available_capital * position_size) / current_price)
                if shares <= 0:
                    continue
                
                # Check for enough capital
                cost = current_price * shares
                if cost > available_capital:
                    shares = int(available_capital / current_price)
                    cost = current_price * shares
                    if shares <= 0: continue
                
                available_capital -= cost
                
                active_trades[symbol] = {
                    'entry_time': display_time,
                    'entry_date_raw': current_date.date(),
                    'entry_price': current_price,
                    'shares': shares,
                    'target_price': current_price * (1 + take_profit),
                    'stop_price': current_price * (1 - stop_loss),
                    'max_exit_time': current_date + timedelta(days=hold_days),
                    'dip_pct': dip_pct
                }
        
        # 3. RECORD EQUITY AT END OF TICK
        total_open_value = 0
        for open_symbol, open_trade in active_trades.items():
            try:
                cur_p = float(price_data[open_symbol].loc[current_date, 'Close'])
            except KeyError:
                cur_p = float(price_data[open_symbol][:current_date]['Close'].iloc[-1])
            total_open_value += open_trade['shares'] * cur_p
        
        tick_equity = available_capital + total_open_value
        equity_curve.append({
            'timestamp': display_time,
            'equity': tick_equity
        })
    
    if not trades:
        return None
    
    trades_df = pd.DataFrame(trades).sort_values('exit_time')
    equity_df = pd.DataFrame(equity_curve)
    
    # Calculate metrics using equity curve for drawdown for better accuracy
    metrics = calculate_metrics(trades_df, initial_capital, start_date, end_date)
    
    # Override max drawdown from equity curve (more accurate than trade-only)
    if not equity_df.empty:
        ec = equity_df['equity'].values
        running_max = np.maximum.accumulate(ec)
        drawdown = (ec - running_max) / running_max
        metrics['max_drawdown'] = abs(drawdown.min()) * 100
        
    return trades_df, metrics, equity_df
