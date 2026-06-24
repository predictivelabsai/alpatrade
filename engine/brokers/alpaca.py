"""
Alpaca API Utility Functions using Alpaca Python SDK

This module provides comprehensive functions for interacting with the Alpaca Trading API,
including order management, account information, positions, and market data.

Based on Alpaca Python SDK: https://github.com/alpacahq/alpaca-py
"""

import os
import logging
from typing import Dict, List, Optional, Union, Any, TypedDict, Annotated
from datetime import datetime, timedelta, timezone
import time
from dotenv import load_dotenv
import requests
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# Alpaca SDK imports
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopOrderRequest,
    StopLimitOrderRequest,
    TrailingStopOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import (
    OrderSide, 
    TimeInForce, 
    AssetClass, 
    QueryOrderStatus,
    OrderType,
    OrderClass
)
from alpaca.data.requests import StockBarsRequest, StockTradesRequest, StockQuotesRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment

# Load environment variables
load_dotenv()


class AlpacaState(TypedDict):
    """State type for Alpaca operations"""
    messages: Annotated[list, "add_messages"]
    thread_id: Optional[str]


class AlpacaAPI:
    """Main class for Alpaca API interactions using the Python SDK"""
    
    def __init__(self, api_key=None, secret_key=None, paper=True):
        """
        Initialize Alpaca API client
        
        Args:
            api_key: Alpaca API key (defaults to ALPACA_PAPER_API_KEY env var)
            secret_key: Alpaca secret key (defaults to ALPACA_PAPER_SECRET_KEY env var)
            paper: Whether to use paper trading (default True)
        """
        self.api_key = api_key or os.getenv("ALPACA_PAPER_API_KEY")
        self.secret_key = secret_key or os.getenv("ALPACA_PAPER_SECRET_KEY")
        self.paper = paper
        if not self.api_key or not self.secret_key:
            raise ValueError("API key and secret key are required")
        self.trading_client = TradingClient(
            self.api_key,
            self.secret_key,
            paper=self.paper
        )

    @property
    def is_paper(self):
        return self.paper

    @property
    def base_url(self):
        return "https://paper-api.alpaca.markets" if self.paper else "https://api.alpaca.markets"

    def get_account(self):
        try:
            account = self.trading_client.get_account()
            return account.dict()
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}

    def create_order(self, symbol, qty=None, side='buy', type='market', time_in_force='day', notional=None, **kwargs):
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        try:
            # Enforce market orders only
            if type != 'market':
                raise ValueError(f"Only market orders are allowed. Requested type: {type}")
            
            side_enum = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL
            tif_enum = TimeInForce.DAY if time_in_force.lower() == 'day' else TimeInForce.GTC
            
            # Only create market orders
            if notional is not None:
                req = MarketOrderRequest(symbol=symbol, notional=notional, side=side_enum, time_in_force=tif_enum)
            else:
                req = MarketOrderRequest(symbol=symbol, qty=qty, side=side_enum, time_in_force=tif_enum)
                
            order = self.trading_client.submit_order(req)
            order_dict = order.dict()
            
            # Store order either in DB (if available) or fallback to local JSONL
            stored = False
            try:
                from utils.db.orders_db_util import store_order_fixed  # type: ignore
                stored = bool(store_order_fixed(order_dict, is_paper=self.paper))
                if stored:
                    logger.info(f"Order {order_dict.get('id')} stored in database")
            except Exception as db_error:
                # DB module not available or failed; fallback to local storage
                try:
                    orders_dir = Path("data") / "orders"
                    orders_dir.mkdir(parents=True, exist_ok=True)
                    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    outfile = orders_dir / f"orders-{date_str}.jsonl"
                    with outfile.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({
                            **order_dict,
                            "_stored_at": datetime.now(timezone.utc).isoformat(),
                            "_paper": self.paper
                        }, default=str) + "\n")
                    stored = True
                    logger.info(f"Order {order_dict.get('id')} stored locally at {outfile}")
                except Exception as file_err:
                    stored = False
                    logger.error(f"Failed to persist order {order_dict.get('id')} locally: {file_err}")
            
            if not stored:
                logger.warning(f"Order {order_dict.get('id')} not persisted to DB or local file")
            
            return order_dict
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}

    def get_orders(self, status: Optional[str] = None,
                   after: Optional[str] = None,
                   until: Optional[str] = None,
                   limit: Optional[int] = None,
                   **kwargs):
        """
        Get orders with optional filters.

        Args:
            status: 'open', 'closed', or 'all'
            after: ISO datetime string — only return orders after this time
            until: ISO datetime string — only return orders before this time
            limit: Max number of orders to return
        """
        try:
            req_kwargs = {}

            if status:
                if status == 'open':
                    req_kwargs['status'] = QueryOrderStatus.OPEN
                elif status == 'closed':
                    req_kwargs['status'] = QueryOrderStatus.CLOSED
                # 'all' — omit status to get all

            if after:
                req_kwargs['after'] = datetime.fromisoformat(after.replace('Z', '+00:00'))
            if until:
                req_kwargs['until'] = datetime.fromisoformat(until.replace('Z', '+00:00'))
            if limit:
                req_kwargs['limit'] = limit

            if req_kwargs:
                request = GetOrdersRequest(**req_kwargs)
                orders = self.trading_client.get_orders(request)
            else:
                orders = self.trading_client.get_orders()

            return [o.dict() for o in orders]
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}

    def get_order(self, order_id: str) -> Dict:
        """
        Get a specific order by ID
        
        Args:
            order_id: Order ID to retrieve
            
        Returns:
            Order dictionary or error
        """
        try:
            order = self.trading_client.get_order_by_id(order_id)
            return order.dict()
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    def cancel_order(self, order_id: str) -> Dict:
        """
        Cancel a specific order by ID
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            Cancellation result or error
        """
        try:
            self.trading_client.cancel_order_by_id(order_id)
            logger.info(f"Order {order_id} canceled successfully")
            return {"status": "canceled", "order_id": order_id}
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}

    def cancel_all_orders(self):
        try:
            self.trading_client.cancel_orders()
            return {"status": "all_orders_cancelled"}
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}

    def get_positions(self):
        try:
            positions = self.trading_client.get_all_positions()
            return [p.dict() for p in positions]
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    def get_position(self, symbol: str) -> Dict:
        """Get position for a specific symbol"""
        try:
            positions = self.trading_client.get_all_positions()
            for position in positions:
                if position.symbol == symbol.upper():
                    return position.dict()
            # Return None if position not found (not an error)
            return None
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    def close_position(self, symbol: str, qty: Optional[Union[int, float]] = None,
                      percentage: Optional[float] = None) -> Dict:
        """Close a position"""
        try:
            if qty is not None:
                self.trading_client.close_position(symbol, qty=qty)
            elif percentage is not None:
                self.trading_client.close_position(symbol, percentage=percentage)
            else:
                self.trading_client.close_position(symbol)
            
            return {"status": "position_closed", "symbol": symbol}
            
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    def close_all_positions(self, cancel_orders: bool = False) -> Dict:
        """Close all positions"""
        try:
            self.trading_client.close_all_positions(cancel_orders=cancel_orders)
            return {"status": "all_positions_closed"}
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    # Assets
    def get_assets(self, status: Optional[str] = None, asset_class: Optional[str] = None,
                   exchange: Optional[str] = None) -> Dict:
        """
        Get assets
        
        Args:
            status: 'active' or 'inactive'
            asset_class: 'us_equity', 'us_crypto', etc.
            exchange: Exchange name
        """
        try:
            # Convert asset_class string to enum if provided
            asset_class_enum = None
            if asset_class:
                if asset_class.lower() == 'us_equity':
                    asset_class_enum = AssetClass.US_EQUITY
                elif asset_class.lower() == 'us_crypto':
                    asset_class_enum = AssetClass.US_CRYPTO
            
            request = GetAssetsRequest(
                status=status,
                asset_class=asset_class_enum,
                exchange=exchange
            )
            
            assets = self.trading_client.get_all_assets(request)
            return [asset.dict() for asset in assets]
            
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    def get_asset(self, symbol: str) -> Dict:
        """Get asset information for a specific symbol"""
        try:
            asset = self.trading_client.get_asset(symbol)
            return asset.dict()
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    # Market Data (requires market data subscription)
    def get_bars(self, symbols: Union[str, List[str]], timeframe: str = '1Day',
                 start: Optional[str] = None, end: Optional[str] = None,
                 limit: Optional[int] = None, adjustment: str = 'raw') -> Dict:
        """
        Get historical bar data
        
        Args:
            symbols: Single symbol or list of symbols
            timeframe: '1Min', '5Min', '15Min', '30Min', '1Hour', '1Day', '1Week', '1Month'
            start: Start time (ISO format)
            end: End time (ISO format)
            limit: Maximum number of bars
            adjustment: 'raw', 'split', 'dividend', 'all'
        """
        try:
            # Convert timeframe string to TimeFrame enum
            timeframe_map = {
                '1Min': TimeFrame.Minute,
                '5Min': TimeFrame.Minute_5,
                '15Min': TimeFrame.Minute_15,
                '30Min': TimeFrame.Minute_30,
                '1Hour': TimeFrame.Hour,
                '1Day': TimeFrame.Day,
                '1Week': TimeFrame.Week,
                '1Month': TimeFrame.Month
            }
            timeframe_enum = timeframe_map.get(timeframe, TimeFrame.Day)
            
            # Convert adjustment string to Adjustment enum
            adjustment_map = {
                'raw': Adjustment.RAW,
                'split': Adjustment.SPLIT,
                'dividend': Adjustment.DIVIDEND,
                'all': Adjustment.ALL
            }
            adjustment_enum = adjustment_map.get(adjustment, Adjustment.RAW)
            
            # Convert start/end strings to datetime if provided
            start_dt = None
            end_dt = None
            if start:
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            if end:
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            
            request = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=timeframe_enum,
                start=start_dt,
                end=end_dt,
                limit=limit,
                adjustment=adjustment_enum
            )
            
            bars = self.trading_client.get_stock_bars(request)
            return bars.dict()
            
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    def get_latest_price(self, symbol: str, use_alpaca: bool = False) -> Optional[float]:
        """Get the latest price for a symbol using Massive API (default) or Alpaca."""
        try:
            if use_alpaca:
                # Use Alpaca data API
                from alpaca.data.historical import StockHistoricalDataClient
                from alpaca.data.requests import StockLatestQuoteRequest
                data_client = StockHistoricalDataClient(self.api_key, self.secret_key)
                request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
                quote = data_client.get_stock_latest_quote(request)
                if symbol in quote:
                    return float(quote[symbol].ask_price)
                return None
            else:
                # Use Massive API (default)
                massive_api_key = os.getenv('MASSIVE_API_KEY') or os.getenv('POLYGON_API_KEY')
                if not massive_api_key:
                    logger.warning("MASSIVE_API_KEY not found, falling back to Alpaca")
                    return self.get_latest_price(symbol, use_alpaca=True)
                
                # Massive API call for latest price
                url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}"
                params = {'apikey': massive_api_key}
                
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                
                data = response.json()
                if 'results' in data and data['results']:
                    # Get the latest price from the snapshot
                    result = data['results']
                    if 'lastTrade' in result and result['lastTrade']:
                        return float(result['lastTrade']['p'])  # Last trade price
                    elif 'min' in result and result['min']:
                        return float(result['min']['c'])  # Current day's close
                
                logger.warning(f"No price data found for {symbol} in Massive response")
                return None
                
        except Exception as e:
            logger.error(f"Failed to get latest price for {symbol}: {e}")
            if not use_alpaca:
                logger.info("Falling back to Alpaca API")
                return self.get_latest_price(symbol, use_alpaca=True)
            return None
    
    def get_trades(self, symbol: str, start: Optional[str] = None, end: Optional[str] = None,
                   limit: Optional[int] = None) -> Dict:
        """Get historical trade data"""
        try:
            # Convert start/end strings to datetime if provided
            start_dt = None
            end_dt = None
            if start:
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            if end:
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            
            request = StockTradesRequest(
                symbol=symbol,
                start=start_dt,
                end=end_dt,
                limit=limit
            )
            
            trades = self.trading_client.get_stock_trades(request)
            return trades.dict()
            
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    def get_latest_trades(self, symbols: Union[str, List[str]]) -> Dict:
        """Get latest trade data"""
        try:
            request = StockTradesRequest(
                symbol_or_symbols=symbols,
                limit=1
            )
            
            trades = self.trading_client.get_stock_trades(request)
            return trades.dict()
            
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    def get_quotes(self, symbol: str, start: Optional[str] = None, end: Optional[str] = None,
                   limit: Optional[int] = None) -> Dict:
        """Get historical quote data"""
        try:
            # Convert start/end strings to datetime if provided
            start_dt = None
            end_dt = None
            if start:
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            if end:
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            
            request = StockQuotesRequest(
                symbol=symbol,
                start=start_dt,
                end=end_dt,
                limit=limit
            )
            
            quotes = self.trading_client.get_stock_quotes(request)
            return quotes.dict()
            
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    def get_latest_quotes(self, symbols: Union[str, List[str]]) -> Dict:
        """Get latest quote data"""
        try:
            request = StockQuotesRequest(
                symbol_or_symbols=symbols,
                limit=1
            )
            
            quotes = self.trading_client.get_stock_quotes(request)
            return quotes.dict()
            
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    # Calendar
    def get_calendar(self, start: Optional[str] = None, end: Optional[str] = None) -> Dict:
        """Get market calendar"""
        try:
            # Convert start/end strings to datetime if provided
            start_dt = None
            end_dt = None
            if start:
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            if end:
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
            
            calendar = self.trading_client.get_calendar(start=start_dt, end=end_dt)
            return [day.dict() for day in calendar]
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}
    
    # Clock
    def get_clock(self) -> Dict:
        """Get market clock"""
        try:
            clock = self.trading_client.get_clock()
            return clock.dict()
        except Exception as e:
            logger.error(f"API request failed: {e}")
            return {"error": str(e)}


# Convenience functions for common operations
def create_market_order(symbol: str, qty: Union[int, float], side: str, 
                       client_order_id: Optional[str] = None) -> Dict:
    """Create a simple market order"""
    api = AlpacaAPI()
    return api.create_order(
        symbol=symbol,
        qty=qty,
        side=side,
        type='market',
        client_order_id=client_order_id
    )


def create_limit_order(symbol: str, qty: Union[int, float], side: str, 
                      limit_price: float, client_order_id: Optional[str] = None) -> Dict:
    """Create a simple limit order"""
    api = AlpacaAPI()
    return api.create_order(
        symbol=symbol,
        qty=qty,
        side=side,
        type='limit',
        limit_price=limit_price,
        client_order_id=client_order_id
    )


def create_stop_order(symbol: str, qty: Union[int, float], side: str, 
                     stop_price: float, client_order_id: Optional[str] = None) -> Dict:
    """Create a simple stop order"""
    api = AlpacaAPI()
    return api.create_order(
        symbol=symbol,
        qty=qty,
        side=side,
        type='stop',
        stop_price=stop_price,
        client_order_id=client_order_id
    )


def create_bracket_order(symbol: str, qty: Union[int, float], side: str,
                        take_profit_price: float, stop_loss_price: float,
                        limit_price: Optional[float] = None) -> Dict:
    """Create a bracket order with take profit and stop loss"""
    api = AlpacaAPI()
    
    take_profit = {'limit_price': take_profit_price}
    stop_loss = {'stop_price': stop_loss_price}
    if limit_price:
        stop_loss['limit_price'] = limit_price
    
    return api.create_order(
        symbol=symbol,
        qty=qty,
        side=side,
        type='limit' if limit_price else 'market',
        limit_price=limit_price,
        order_class='bracket',
        take_profit=take_profit,
        stop_loss=stop_loss
    )


def get_account_summary() -> Dict:
    """Get a summary of account information"""
    api = AlpacaAPI()
    account = api.get_account()
    
    if 'error' in account:
        return account
    
    return {
        'account_id': account.get('id'),
        'status': account.get('status'),
        'currency': account.get('currency'),
        'buying_power': account.get('buying_power'),
        'regt_buying_power': account.get('regt_buying_power'),
        'daytrading_buying_power': account.get('daytrading_buying_power'),
        'cash': account.get('cash'),
        'portfolio_value': account.get('portfolio_value'),
        'pattern_day_trader': account.get('pattern_day_trader'),
        'trading_blocked': account.get('trading_blocked'),
        'transfers_blocked': account.get('transfers_blocked'),
        'account_blocked': account.get('account_blocked'),
        'created_at': account.get('created_at'),
        'trade_suspended_by_user': account.get('trade_suspended_by_user'),
        'multiplier': account.get('multiplier'),
        'shorting_enabled': account.get('shorting_enabled'),
        'equity': account.get('equity'),
        'last_equity': account.get('last_equity'),
        'long_market_value': account.get('long_market_value'),
        'short_market_value': account.get('short_market_value'),
        'initial_margin': account.get('initial_margin'),
        'maintenance_margin': account.get('maintenance_margin'),
        'last_maintenance_margin': account.get('last_maintenance_margin'),
        'sma': account.get('sma'),
        'daytrade_count': account.get('daytrade_count')
    }


def is_market_open() -> bool:
    """Check if the market is currently open"""
    api = AlpacaAPI()
    clock = api.get_clock()
    
    if 'error' in clock:
        return False
    
    return clock.get('is_open', False)


def get_next_market_open() -> Optional[str]:
    """Get the next market open time"""
    api = AlpacaAPI()
    clock = api.get_clock()
    
    if 'error' in clock:
        return None
    
    return clock.get('next_open')


def get_next_market_close() -> Optional[str]:
    """Get the next market close time"""
    api = AlpacaAPI()
    clock = api.get_clock()
    
    if 'error' in clock:
        return None
    
    return clock.get('next_close')


# Example usage and testing
if __name__ == "__main__":
    # Example: Get account information
    print("Account Summary:")
    print(json.dumps(get_account_summary(), indent=2))
    
    # Example: Check market status
    print(f"\nMarket is open: {is_market_open()}")
    
    # Example: Get next market open/close
    print(f"Next market open: {get_next_market_open()}")
    print(f"Next market close: {get_next_market_close()}")
    
    # Example: Get positions
    api = AlpacaAPI()
    positions = api.get_positions()
    print(f"\nCurrent positions: {json.dumps(positions, indent=2)}")
    
    # Example: Get open orders
    orders = api.get_orders(status='open')
    print(f"\nOpen orders: {json.dumps(orders, indent=2)}")
