#!/usr/bin/env python3
"""
Command-Line Trading Script
Execute trading strategies from the command line for scheduled/automated trading
"""

import argparse
import os
import sys
import csv
import yaml
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import logging
import json
import pandas as pd
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv()

# Setup logging (before config loading so we can log config loading)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Load configuration
def load_config():
    """Load configuration from parameters.yaml"""
    config_path = Path(__file__).parent.parent / "config" / "parameters.yaml"
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"Loaded configuration from {config_path}")
            return config
        except Exception as e:
            logger.warning(f"Could not load config from {config_path}: {e}")
            logger.info("Using default configuration")
    else:
        logger.warning(f"Config file not found at {config_path}, using defaults")
    
    # Default configuration
    return {
        'buy_the_dip': {
            'symbols': 'AAPL,MSFT,GOOGL,AMZN,META,TSLA,NVDA',
            'dip_threshold': 5.0,
            'take_profit_threshold': 1.0,
            'stop_loss_threshold': 0.5,
            'hold_days': 2,
            'capital_per_trade': 1000.0,
            'max_position_pct': 5.0
        },
        'vix': {
            'symbols': 'AAPL,MSFT,GOOGL,AMZN,META,TSLA,NVDA',
            'vix_threshold': 20.0,
            'capital_per_trade': 1000.0
        },
        'general': {
            'check_order_status_interval': 60,
            'polling_interval': 300
        }
    }

# Import utilities
from utils.alpaca_util import AlpacaAPI
from utils.massive_util import is_market_open as market_open, get_historical_data, get_intraday_prices
from utils.backtester_util import backtest_buy_the_dip
import time
from datetime import datetime, timedelta, timezone
import pytz


def load_tracked_positions():
    """Load tracked positions from local JSONL file"""
    positions = {}
    path = Path("data/tracked_positions.jsonl")
    if path.exists():
        try:
            with open(path, "r") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        symbol = data.get("symbol")
                        if symbol:
                            positions[symbol] = data
        except Exception as e:
            logger.error(f"Error loading tracked positions: {e}")
    return positions


def save_tracked_position(symbol, entry_data):
    """Save or update a tracked position"""
    positions = load_tracked_positions()
    positions[symbol] = {
        "symbol": symbol,
        "entry_time": entry_data.get("entry_time"),
        "entry_price": entry_data.get("entry_price"),
        "qty": float(entry_data.get("qty", 0)),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    path = Path("data/tracked_positions.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w") as f:
            for pos in positions.values():
                f.write(json.dumps(pos) + "\n")
    except Exception as e:
        logger.error(f"Error saving tracked positions: {e}")


def remove_tracked_position(symbol):
    """Remove a position from tracking after exit"""
    positions = load_tracked_positions()
    if symbol in positions:
        del positions[symbol]
        path = Path("data/tracked_positions.jsonl")
        try:
            with open(path, "w") as f:
                for pos in positions.values():
                    f.write(json.dumps(pos) + "\n")
            logger.info(f"Removed {symbol} from local tracking")
        except Exception as e:
            logger.error(f"Error updating tracked positions after removal: {e}")


def get_alpaca_client(mode='paper'):
    """Initialize Alpaca client"""
    if mode == 'paper':
        api_key = os.getenv('ALPACA_PAPER_API_KEY')
        secret_key = os.getenv('ALPACA_PAPER_SECRET_KEY')
    else:
        api_key = os.getenv('ALPACA_LIVE_API_KEY')
        secret_key = os.getenv('ALPACA_LIVE_SECRET_KEY')
    
    if not api_key or not secret_key:
        raise ValueError(f"{mode.upper()} API keys not found in environment")
    
    return AlpacaAPI(api_key=api_key, secret_key=secret_key, paper=(mode == 'paper'))


def log_trade_to_csv(trade_data: dict, csv_path: str = 'reports/sample-back-testing-report.csv'):
    """
    Log a trade to CSV file in backtesting report format
    
    Args:
        trade_data: Dictionary with trade information
        csv_path: Path to CSV file
    """
    # Ensure reports directory exists
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Define CSV columns matching backtesting report format
    fieldnames = [
        'entry_time', 'exit_time', 'ticker', 'shares', 'entry_price', 'exit_price',
        'pnl', 'pnl_pct', 'hit_target', 'hit_stop', 'capital_after',
        'taf_fee', 'cat_fee', 'total_fees', 'dip_pct'
    ]
    
    # Check if file exists to determine if we need to write header
    file_exists = Path(csv_path).exists()
    
    try:
        with open(csv_path, 'a', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            # Write header if file is new
            if not file_exists:
                writer.writeheader()
            
            # Format the trade data
            formatted_trade = {
                'entry_time': trade_data.get('entry_time', ''),
                'exit_time': trade_data.get('exit_time', 'OPEN'),
                'ticker': trade_data.get('ticker', ''),
                'shares': float(trade_data.get('shares', 0)),
                'entry_price': f"${float(trade_data.get('entry_price', 0)):.2f}",
                'exit_price': f"${float(trade_data.get('exit_price', 0)):.2f}" if trade_data.get('exit_price') else 'PENDING',
                'pnl': f"${float(trade_data.get('pnl', 0)):.2f}" if trade_data.get('pnl') is not None else 'PENDING',
                'pnl_pct': f"{float(trade_data.get('pnl_pct', 0)):.2f}%" if trade_data.get('pnl_pct') is not None else 'PENDING',
                'hit_target': str(trade_data.get('hit_target', False)).lower(),
                'hit_stop': str(trade_data.get('hit_stop', False)).lower(),
                'capital_after': f"${float(trade_data.get('capital_after', 0)):,.2f}" if trade_data.get('capital_after') else 'PENDING',
                'taf_fee': f"${float(trade_data.get('taf_fee', 0)):.2f}",
                'cat_fee': f"${float(trade_data.get('cat_fee', 0)):.2f}",
                'total_fees': f"${float(trade_data.get('total_fees', 0)):.2f}",
                'dip_pct': f"{float(trade_data.get('dip_pct', 0)):.2f}%"
            }
            
            writer.writerow(formatted_trade)
            logger.info(f"Trade logged to {csv_path}: {trade_data.get('ticker')} - {formatted_trade['shares']} shares")
            
    except Exception as e:
        logger.error(f"Error logging trade to CSV: {str(e)}")



def execute_buy_the_dip_strategy(client, symbols, capital_per_trade=1000, dip_threshold=1.0, 
                                 take_profit_threshold=1.0, stop_loss_threshold=0.5, 
                                 hold_days=2, use_intraday=True, dry_run=False):
    """
    Execute buy-the-dip strategy with entry and exit logic
    
    Args:
        client: AlpacaAPI client
        symbols: List of stock symbols
        capital_per_trade: Capital to allocate per trade
        dip_threshold: Percentage dip to trigger buy
        take_profit_threshold: Percentage gain to take profit
        stop_loss_threshold: Percentage loss to stop out
        hold_days: Minimum days to hold position (PDT/Safety)
    """
    logger.info(f"Executing buy-the-dip strategy for {len(symbols)} symbols")
    logger.info(f"Parameters: dip={dip_threshold}%, tp={take_profit_threshold}%, sl={stop_loss_threshold}%, hold={hold_days}d")
    
    trades_executed = 0
    
    # 1. PROCESS EXITS (Check existing positions)
    existing_symbols = set()
    tracked_positions = load_tracked_positions()
    
    if client:
        try:
            positions = client.get_positions()
            for pos in positions:
                symbol = pos.get('symbol')
                existing_symbols.add(symbol)
                logger.info(f"  📝 Detected existing position for {symbol}")
                if symbol not in symbols: continue
                
                qty = float(pos.get('qty', 0))
                entry_price = float(pos.get('avg_entry_price', 0))
                current_price = float(pos.get('current_price', 0))
                unrealized_pl_pct = (float(pos.get('unrealized_intraday_plpc', 0)) * 100) if 'unrealized_intraday_plpc' in pos else ((current_price - entry_price) / entry_price * 100)
                
                # Check hold period (Safety/PDT) using local tracking first
                last_fill_date = None
                if symbol in tracked_positions:
                    try:
                        last_fill_date = datetime.fromisoformat(tracked_positions[symbol]['entry_time'])
                        logger.info(f"  📂 Using tracked entry date for {symbol}: {last_fill_date}")
                    except Exception as e:
                        logger.warning(f"Error parsing tracked entry time for {symbol}: {e}")
                
                if not last_fill_date:
                    # Fallback to API if not in local tracking
                    try:
                        orders = client.get_orders(status='filled', symbols=[symbol], limit=1)
                        if orders:
                            last_fill_date = datetime.fromisoformat(orders[0]['filled_at'].replace('Z', '+00:00'))
                            # Save to tracking for next time
                            save_tracked_position(symbol, {
                                'entry_time': last_fill_date.isoformat(),
                                'entry_price': entry_price,
                                'qty': qty
                            })
                    except Exception as e:
                        logger.debug(f"Could not fetch last fill for {symbol}: {e}")
                
                if last_fill_date:
                    days_held = (datetime.now(timezone.utc) - last_fill_date).days
                    is_same_day = last_fill_date.date() == datetime.now(timezone.utc).date()
                else:
                    days_held = 99 # Assume safe if we can't find it
                    is_same_day = False

                # PDT Protection: Mandatory overnight hold if account < $25k
                account = client.get_account()
                equity = float(account.get('equity', 0))
                pdt_restricted = equity < 25000
                
                can_exit = True
                if pdt_restricted and is_same_day:
                    can_exit = False
                    logger.info(f"  🛑 PDT Protection: {symbol} must be held overnight (Entry: {last_fill_date})")
                
                if can_exit:
                    exit_reason = None
                    if unrealized_pl_pct >= take_profit_threshold:
                        exit_reason = f"TAKE PROFIT ({unrealized_pl_pct:.2f}%)"
                    elif unrealized_pl_pct <= -stop_loss_threshold:
                        exit_reason = f"STOP LOSS ({unrealized_pl_pct:.2f}%)"
                    elif days_held >= hold_days:
                        exit_reason = f"HOLD PERIOD EXPIRED ({days_held} days)"
                    
                    if exit_reason:
                        logger.info(f"  🚀 EXIT SIGNAL: {symbol} - {exit_reason}")
                        if dry_run:
                            logger.info(f"  DRY RUN: Would place EXIT order for {symbol}")
                            trades_executed += 1
                            remove_tracked_position(symbol)
                        else:
                            res = client.close_position(symbol=symbol)
                            if 'error' in res:
                                logger.error(f"  ❌ Exit failed for {symbol}: {res['error']}")
                            else:
                                logger.info(f"  ✅ Exit order placed for {symbol}")
                                trades_executed += 1
                                remove_tracked_position(symbol)
        except Exception as e:
            logger.error(f"Error processing exits: {e}", exc_info=True)

    # 2. PROCESS ENTRIES
    if client:
        account = client.get_account()
        if 'error' in account:
            logger.error(f"Cannot get account info: {account['error']}")
            return 0, []
        
    if dry_run:
        buying_power = 100000.0 # Virtual for dry-run
        max_position_value = 5000.0
        logger.info(f"DRY RUN: Using virtual buying power ${buying_power:,.2f}")
    else:
        buying_power = float(account.get('buying_power', 0))
        if buying_power <= 0:
            logger.warning(f"Insufficient buying power: ${buying_power:.2f}")
            return 0, []
        
        logger.info(f"Available buying power: ${buying_power:,.2f}")
        
        # Calculate max position size (5% of buying power)
        max_position_value = buying_power * 0.05
    
    logger.info(f"Max position size (5% of buying power): ${max_position_value:,.2f}")
    
    order_ids = []  # Track order IDs for status checking
    
    for symbol in symbols:
        # Skip if position already exists
        if symbol in existing_symbols:
            logger.info(f"  ⏭️  Skipping {symbol}: Position already exists")
            continue
            
        # Rate limit protection (avoid hitting Massive/Alpaca limits)
        time.sleep(0.5)
        try:
            # Match backtester logic: Get recent high over 20 periods
            end_date = datetime.now()
            start_date = end_date - timedelta(days=40)
            
            # Fetch historical data (daily bars for recent high)
            hist = get_historical_data(symbol, start_date=start_date, end_date=end_date)
            
            if hist.empty:
                logger.warning(f"No data for {symbol}, skipping")
                continue
            
            # Calculate recent high over 20-period lookback
            lookback_periods = 20
            high_series = hist['High'].tail(lookback_periods)
            max_val = high_series.max()
            recent_high = float(max_val.iloc[0]) if hasattr(max_val, 'iloc') else float(max_val)
            
            # Get current price
            current_price = None
            if use_intraday:
                today_data = get_intraday_prices(symbol, date=end_date, interval='1')
                if not today_data.empty:
                    val = today_data['Close'].iloc[-1]
                    current_price = float(val.item()) if hasattr(val, 'item') else float(val)
            
            if current_price is None:
                val = hist['Close'].iloc[-1]
                current_price = float(val.iloc[0]) if hasattr(val, 'iloc') else float(val)
            dip_pct = ((recent_high - current_price) / recent_high) * 100
            
            logger.info(f"{symbol}: Recent high ${recent_high:.2f}, Current ${current_price:.2f}, Dip {dip_pct:.2f}%")
            
            # Check if dip threshold met
            if dip_pct < dip_threshold:
                logger.info(f"  ⏭️  Skipping {symbol}: Dip {dip_pct:.2f}% < Threshold {dip_threshold}%")
                continue
            
            if dip_pct >= dip_threshold:
                # Always check for existing position before executing order
                if client:
                    try:
                        pos = client.get_position(symbol)
                        if pos and isinstance(pos, dict) and 'error' not in pos:
                            logger.info(f"Skipping {symbol}: existing position detected ({pos.get('qty', 0)} shares)")
                            continue
                    except Exception as pos_err:
                        logger.warning(f"Error checking position for {symbol}: {pos_err}")
                
                # Calculate quantity based on capital_per_trade, but cap at 5% of buying power
                position_value = min(capital_per_trade, max_position_value)
                
                # Verify we don't exceed buying power (redundant with min but safe)
                if position_value > buying_power:
                    logger.warning(f"Cannot place order for {symbol}: value ${position_value:.2f} exceeds buying power ${buying_power:.2f}")
                    continue
                
                # Calculate full shares (paper trading doesn't support fractional)
                qty = int(position_value / current_price)
                
                if qty == 0:
                    logger.warning(f"Cannot place order for {symbol}: position value ${position_value:.2f} too small for current price ${current_price:.2f}")
                    continue
                
                # Place order
                if not dry_run and client:
                    result = client.create_order(
                        symbol=symbol,
                        qty=qty,
                        side='buy',
                        type='market',
                        time_in_force='day'
                    )
                    
                    if 'error' in result:
                        logger.error(f"Order failed for {symbol}: {result['error']}")
                    else:
                        order_id = result.get('id')
                        order_status = result.get('status', 'unknown')
                        actual_value = qty * current_price
                        logger.info(f"✅ Order placed: BUY {qty} shares of {symbol} @ market (~${actual_value:.2f})")
                        logger.info(f"   Order ID: {order_id}, Status: {order_status}")
                        
                        if order_id:
                            order_ids.append({
                                'order_id': str(order_id),
                                'symbol': symbol,
                                'qty': qty,
                                'status': str(order_status) if order_status else 'unknown',
                                'timestamp': datetime.now(timezone.utc).isoformat()
                            })
                            # Local tracking
                            save_tracked_position(symbol, {
                                'entry_time': datetime.now(timezone.utc).isoformat(),
                                'entry_price': current_price,
                                'qty': qty
                            })
                        
                        trades_executed += 1
                else:
                    logger.info(f"DRY RUN: Would place BUY order for ${position_value:.2f} of {symbol} (~{position_value/current_price:.2f} shares) @ ~${current_price:.2f}")
                    trades_executed += 1
                    
                    # Update local tracking for dry run
                    save_tracked_position(symbol, {
                        'entry_time': datetime.now(timezone.utc).isoformat(),
                        'entry_price': current_price,
                        'qty': position_value / current_price
                    })

                    # Update buying power after successful order
                    buying_power -= position_value
                    max_position_value = buying_power * 0.05
                    logger.info(f"Remaining buying power: ${buying_power:,.2f}")
                    
                    # Log trade to CSV
                    trade_data = {
                        'entry_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
                        'exit_time': None,
                        'ticker': symbol,
                        'shares': position_value / current_price,
                        'entry_price': current_price,
                        'exit_price': None,
                        'pnl': None,
                        'pnl_pct': None,
                        'hit_target': False,
                        'hit_stop': False,
                        'capital_after': None,
                        'taf_fee': 0.0,
                        'cat_fee': 0.0,
                        'total_fees': 0.0,
                        'dip_pct': dip_pct
                    }
                    log_trade_to_csv(trade_data)
                
        except Exception as e:
            logger.error(f"Error processing {symbol}: {str(e)}")
    
    logger.info(f"Strategy execution complete. Trades executed: {trades_executed}")
    return trades_executed, order_ids


def close_all_positions(client):
    """Close all open positions"""
    logger.info("Closing all positions")
    
    try:
        result = client.close_all_positions(cancel_orders=True)
        
        if 'error' in result:
            logger.error(f"Error closing positions: {result['error']}")
            return False
        else:
            logger.info("✅ All positions closed")
            return True
            
    except Exception as e:
        logger.error(f"Error closing positions: {str(e)}")
        return False




def get_account_status(client):
    """Get and log account status"""
    try:
        account = client.get_account()
        
        if 'error' in account:
            logger.error(f"Error fetching account: {account['error']}")
            return None
        
        logger.info("=== Account Status ===")
        logger.info(f"Portfolio Value: ${float(account.get('portfolio_value', 0)):,.2f}")
        logger.info(f"Cash: ${float(account.get('cash', 0)):,.2f}")
        logger.info(f"Buying Power: ${float(account.get('buying_power', 0)):,.2f}")
        logger.info(f"Equity: ${float(account.get('equity', 0)):,.2f}")
        logger.info("=====================")
        
        return account
        
    except Exception as e:
        logger.error(f"Error getting account status: {str(e)}")
        return None


def check_order_status(client, order_ids):
    """Check status of orders and report to console"""
    logger.info("="*60)
    logger.info("ORDER STATUS CHECK")
    logger.info("="*60)
    
    # Also check recent orders from API
    try:
        recent_orders = client.get_orders(status='open')
        if isinstance(recent_orders, list) and len(recent_orders) > 0:
            logger.info(f"Found {len(recent_orders)} open orders from API:")
            for order in recent_orders:
                order_id = order.get('id')
                symbol = order.get('symbol')
                status = order.get('status', 'unknown')
                logger.info(f"  {str(order_id)}: {symbol} - {str(status)}")
    except Exception as e:
        logger.debug(f"Could not fetch recent orders: {e}")
    
    if not order_ids:
        logger.info("No tracked orders to check")
        logger.info("="*60)
        return
    
    for order_info in order_ids:
        order_id = order_info['order_id']
        symbol = order_info['symbol']
        
        try:
            order = client.get_order(order_id)
            
            if 'error' in order:
                logger.warning(f"Order {order_id} ({symbol}): Error checking status - {order['error']}")
                continue
            
            status = order.get('status', 'unknown')
            filled_qty = float(order.get('filled_qty', 0))
            qty = float(order.get('qty', 0))
            filled_avg_price = order.get('filled_avg_price')
            
            status_str = str(status) if status else 'unknown'
            
            # Update order status in tracked list
            order_info['status'] = status_str
            order_info['filled_qty'] = filled_qty
            order_info['filled_avg_price'] = float(filled_avg_price) if filled_avg_price else None
            
            logger.info(f"Order {order_id} ({symbol}):")
            logger.info(f"  Status: {status_str}")
            logger.info(f"  Quantity: {qty} shares")
            logger.info(f"  Filled: {filled_qty} shares")
            
            if filled_avg_price:
                logger.info(f"  Avg Fill Price: ${float(filled_avg_price):.2f}")
            
            if status_str.lower() in ['filled', 'partially_filled']:
                logger.info(f"  ✅ Order executed successfully")
            elif status_str.lower() in ['pending_new', 'accepted', 'pending_replace']:
                logger.info(f"  ⏳ Order still pending")
            elif status_str.lower() in ['rejected', 'expired', 'canceled']:
                logger.warning(f"  ❌ Order {status_str}")
                if order.get('reject_reason'):
                    logger.warning(f"  Reject Reason: {order.get('reject_reason')}")
            
        except Exception as e:
            logger.error(f"Error checking order {order_id} ({symbol}): {str(e)}")
    
    logger.info("="*60)


def main():
    # Load configuration first
    config = load_config()
    
    parser = argparse.ArgumentParser(description='Command-line trading script for automated strategy execution')
    
    parser.add_argument('--strategy', type=str, required=True,
                       choices=['buy-the-dip', 'close-all', 'status'],
                       help='Strategy to execute')
    
    parser.add_argument('--mode', type=str, default='paper',
                       choices=['paper', 'live'],
                       help='Trading mode (paper or live)')
    
    parser.add_argument('--symbols', type=str,
                       default=config.get('buy_the_dip', {}).get('symbols', 'AAPL,MSFT,GOOGL,AMZN,META,TSLA,NVDA'),
                       help='Comma-separated list of stock symbols')
    
    parser.add_argument('--capital', type=float, 
                       default=config.get('buy_the_dip', {}).get('capital_per_trade', 1000.0),
                       help='Capital per trade in dollars')
    
    parser.add_argument('--dip-threshold', type=float,
                       default=config.get('buy_the_dip', {}).get('dip_threshold', 1.0),
                       help='Dip threshold percentage for buy-the-dip strategy')
    
    parser.add_argument('--take-profit-threshold', type=float,
                       default=config.get('buy_the_dip', {}).get('take_profit_threshold', 1.0),
                       help='Take profit threshold percentage for buy-the-dip strategy')
    
    parser.add_argument('--vix-threshold', type=float,
                       default=config.get('vix', {}).get('vix_threshold', 20.0),
                       help='VIX threshold for VIX strategy')
    
    parser.add_argument('--dry-run', action='store_true',
                       help='Dry run mode (no actual trades)')
    
    parser.add_argument('--once', action='store_true',
                       help='Run once and exit (default: run continuously)')
    
    
    parser.add_argument('--hold-days', type=int,
                       default=config.get('buy_the_dip', {}).get('hold_days', 2),
                       help='Minimum days to hold position (default: 2)')
    
    parser.add_argument('--stop-loss-threshold', type=float,
                       default=config.get('buy_the_dip', {}).get('stop_loss_threshold', 0.5),
                       help='Stop loss threshold percentage for buy-the-dip strategy')
    
    parser.add_argument('--interval', type=int,
                       default=config.get('general', {}).get('polling_interval', 300),
                       help='Polling interval in seconds for continuous mode')
    
    args = parser.parse_args()
    
    # Parse symbols
    symbols = [s.strip().upper() for s in args.symbols.split(',')]
    
    logger.info("="*60)
    logger.info(f"CLI Trader Started - {datetime.now()}")
    logger.info(f"Strategy: {args.strategy}")
    logger.info(f"Mode: {args.mode.upper()}")
    
    # Data source logging
    data_source = config.get('general', {}).get('market_data_source', 'massive').lower()
    source_display = "Massive" if data_source in ['massive', 'polygon'] else data_source.capitalize()
    logger.info(f"Data Source: {source_display}")
    
    logger.info(f"Symbols: {', '.join(symbols)}")
    logger.info(f"Dry Run: {args.dry_run}")
    logger.info("="*60)
    
    # Warning for live trading
    if args.mode == 'live' and not args.dry_run:
        logger.warning("⚠️  LIVE TRADING MODE - REAL MONEY WILL BE USED!")
        logger.warning("Press Ctrl+C within 5 seconds to cancel...")
        time.sleep(5)
    
    try:
        # Initialize client (required for position/account info even in dry-run)
        try:
            client = get_alpaca_client(args.mode)
            account = client.get_account()
            if 'error' in account:
                if not args.dry_run:
                    logger.error(f"❌ API Key Validation Failed: {account['error']}")
                    sys.exit(1)
                else:
                    logger.warning(f"⚠️  Dry run: Could not validate keys, position check will be skipped: {account['error']}")
                    client = None
            else:
                logger.info(f"✅ Connected to Alpaca ({args.mode.upper()} mode) - Keys Validated")
        except Exception as e:
            if not args.dry_run:
                logger.error(f"❌ Failed to initialize Alpaca client: {e}")
                sys.exit(1)
            else:
                logger.warning(f"⚠️  Dry run: Client init failed, position check will be skipped: {e}")
                client = None
        
        # Execute strategy (single-run or loop)
        def run_once():
            order_ids = []
            
            if args.strategy == 'status':
                if client:
                    get_account_status(client)
                else:
                    logger.info("Cannot get status in dry-run mode")
                    
            elif args.strategy == 'close-all':
                if client:
                    close_all_positions(client)
                else:
                    logger.info("DRY RUN: Would close all positions")
                    
            elif args.strategy == 'buy-the-dip':
                trades_executed, order_ids = execute_buy_the_dip_strategy(
                    client,
                    symbols,
                    capital_per_trade=args.capital,
                    dip_threshold=args.dip_threshold,
                    take_profit_threshold=args.take_profit_threshold,
                    stop_loss_threshold=args.stop_loss_threshold,
                    hold_days=args.hold_days,
                    use_intraday=True,
                    dry_run=args.dry_run
                )
            
            return order_ids
        
        if args.once:
            logger.info("Running once and exiting")
            run_once()
        else:
            logger.info("Entering continuous mode (runs indefinitely)")
            tracked_orders = []  # Track orders across iterations
            last_status_check = datetime.now(timezone.utc)
            
            while True:
                try:
                    now = datetime.now()
                    if args.dry_run or market_open(now):
                        new_order_ids = run_once()
                        if new_order_ids:
                            tracked_orders.extend(new_order_ids)
                            logger.info(f"Tracking {len(tracked_orders)} orders")
                    else:
                        logger.info("Market is closed; sleeping until next interval")
                    
                    # Check order status at configured interval
                    check_interval = config.get('general', {}).get('check_order_status_interval', 60)
                    current_time = datetime.now(timezone.utc)
                    time_since_check = (current_time - last_status_check).total_seconds()
                    
                    if time_since_check >= check_interval and tracked_orders and client:
                        check_order_status(client, tracked_orders)
                        last_status_check = current_time
                        
                        # Remove filled/canceled orders from tracking
                        tracked_orders = [o for o in tracked_orders if o.get('status', '').lower() not in ['filled', 'canceled', 'expired', 'rejected']]
                        
                except Exception as loop_err:
                    logger.error(f"Error in loop: {loop_err}", exc_info=True)
                time.sleep(max(5, args.interval))
        
        logger.info("="*60)
        logger.info(f"CLI Trader Completed - {datetime.now()}")
        logger.info("="*60)
        
    except KeyboardInterrupt:
        logger.info("Execution cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
