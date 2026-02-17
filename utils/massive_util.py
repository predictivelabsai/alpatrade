#!/usr/bin/env python3
"""
Massive API Utility

Provides access to Massive (Polygon.io) API for intraday price data with fallback to yfinance.
Requires MASSIVE_API_KEY environment variable to be set.
"""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf
import pytz
from dotenv import load_dotenv
from typing import Optional, Dict, Any, List
import logging

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class MassiveUtil:
    """Utility class for accessing Massive (Polygon.io) API with yfinance fallback"""
    
    def __init__(self):
        """Initialize Massive utility"""
        self.api_key = os.getenv('MASSIVE_API_KEY')
        self.base_url = "https://api.polygon.io"
        self.use_massive = bool(self.api_key)
        
        if self.use_massive:
            logger.info("Massive API key found, will use Massive for price data")
        else:
            logger.info("No Massive API key found, will use yfinance for price data")
    
    def get_intraday_prices(self, symbol: str, date: datetime, interval: str = '5') -> pd.DataFrame:
        """
        Get intraday price data for a specific date
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            date: Date to get data for
            interval: Time interval in minutes (default: '5' for 5-minute bars)
        
        Returns:
            DataFrame with OHLCV data
        """
        if self.use_massive:
            df = self._get_massive_intraday(symbol, date, interval)
            if not df.empty:
                return df
            logger.info(f"Massive returned no data for {symbol}, falling back to yfinance")
            
        return self._get_yfinance_intraday(symbol, date, interval)
    
    def _get_massive_intraday(self, symbol: str, date: datetime, interval: str) -> pd.DataFrame:
        """Get intraday data from Massive (Polygon.io) API"""
        try:
            # Format date for Polygon API
            date_str = date.strftime('%Y-%m-%d')
            
            # Massive API endpoint for intraday data
            url = f"{self.base_url}/v2/aggs/ticker/{symbol}/range/{interval}/minute/{date_str}/{date_str}"
            
            params = {
                'apiKey': self.api_key,
                'adjusted': 'true',
                'sort': 'asc'
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('resultsCount', 0) == 0:
                status = data.get('status', 'Unknown')
                count = data.get('resultsCount', 0)
                logger.debug(f"Massive: {symbol} on {date_str} -> status={status}, count={count}")
                return pd.DataFrame()
            
            # Convert to DataFrame
            df = pd.DataFrame(data['results'])
            
            # Rename columns to match yfinance format
            df = df.rename(columns={
                'o': 'Open',
                'h': 'High', 
                'l': 'Low',
                'c': 'Close',
                'v': 'Volume',
                't': 'timestamp'
            })
            
            # Convert timestamp to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Select only OHLCV columns
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
            
            logger.info(f"Retrieved {len(df)} bars from Massive for {symbol} on {date_str}")
            return df
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Massive API request failed for {symbol}: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error getting Massive data for {symbol}: {e}")
            return pd.DataFrame()
    
    def _get_yfinance_intraday(self, symbol: str, date: datetime, interval: str) -> pd.DataFrame:
        """Get intraday data from yfinance (fallback)"""
        try:
            start_date = date.strftime('%Y-%m-%d')
            end_date = (date + timedelta(days=1)).strftime('%Y-%m-%d')
            
            # Convert interval to yfinance format
            yf_interval = f"{interval}m"
            
            data = yf.download(symbol, start=start_date, end=end_date, interval=yf_interval, progress=False)
            
            if data.empty:
                logger.warning(f"No yfinance data available for {symbol} on {start_date}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error getting yfinance data for {symbol}: {e}")
            return pd.DataFrame()
            
    def get_historical_data(self, symbol: str, start_date: datetime, end_date: datetime, timeframe: str = 'day', interval: int = 1) -> pd.DataFrame:
        """
        Get historical price data for a range of dates
        
        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'
            interval: Number of timeframes per bar
            
        Returns:
            DataFrame with OHLCV data
        """
        if self.use_massive:
            df = self._get_massive_historical(symbol, start_date, end_date, timeframe, interval)
            if not df.empty:
                return df
            logger.info(f"Massive returned no historical data for {symbol}, falling back to yfinance")
            
        return self._get_yfinance_historical(symbol, start_date, end_date, timeframe, interval)

    def _get_massive_historical(self, symbol: str, start_date: datetime, end_date: datetime, timeframe: str, interval: int) -> pd.DataFrame:
        """Get historical data from Massive API across a range"""
        try:
            start_str = start_date.strftime('%Y-%m-%d')
            end_str = end_date.strftime('%Y-%m-%d')
            
            url = f"{self.base_url}/v2/aggs/ticker/{symbol}/range/{interval}/{timeframe}/{start_str}/{end_str}"
            params = {
                'apiKey': self.api_key,
                'adjusted': 'true',
                'sort': 'asc'
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('resultsCount', 0) == 0:
                return pd.DataFrame()
            
            df = pd.DataFrame(data['results'])
            df = df.rename(columns={'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume', 't': 'timestamp'})
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            return df[['Open', 'High', 'Low', 'Close', 'Volume']]
            
        except Exception as e:
            logger.error(f"Error getting Massive historical for {symbol}: {e}")
            return pd.DataFrame()

    def _get_yfinance_historical(self, symbol: str, start_date: datetime, end_date: datetime, timeframe: str, interval: int) -> pd.DataFrame:
        """Get historical data from yfinance fallback"""
        try:
            start_str = start_date.strftime('%Y-%m-%d')
            end_str = end_date.strftime('%Y-%m-%d')
            
            yf_interval = '1d'
            if timeframe == 'minute':
                yf_interval = f'{interval}m'
            elif timeframe == 'hour':
                yf_interval = f'{interval}h'
            elif timeframe == 'day':
                yf_interval = f'{interval}d'
            
            data = yf.download(symbol, start=start_str, end=end_str, interval=yf_interval, progress=False)
            return data
        except Exception as e:
            logger.error(f"Error getting yfinance historical for {symbol}: {e}")
            return pd.DataFrame()
    
    def get_ticker_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get basic ticker information
        
        Args:
            symbol: Stock symbol
        
        Returns:
            Dictionary with ticker info or None if not found
        """
        if self.use_massive:
            return self._get_massive_ticker_info(symbol)
        else:
            return self._get_yfinance_ticker_info(symbol)
    
    def _get_massive_ticker_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get ticker info from Massive (Polygon) API"""
        try:
            url = f"{self.base_url}/v3/reference/tickers/{symbol}"
            params = {'apiKey': self.api_key}
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if data['status'] == 'OK':
                return {
                    'symbol': data['results']['ticker'],
                    'name': data['results']['name'],
                    'market': data['results']['market'],
                    'locale': data['results']['locale'],
                    'primary_exchange': data['results']['primary_exchange'],
                    'type': data['results']['type'],
                    'active': data['results']['active']
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting Massive ticker info for {symbol}: {e}")
            return None
    
    def _get_yfinance_ticker_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get ticker info from yfinance"""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            return {
                'symbol': symbol,
                'name': info.get('longName', ''),
                'market': info.get('market', ''),
                'exchange': info.get('exchange', ''),
                'sector': info.get('sector', ''),
                'industry': info.get('industry', ''),
                'market_cap': info.get('marketCap', 0)
            }
            
        except Exception as e:
            logger.error(f"Error getting yfinance ticker info for {symbol}: {e}")
            return None
    
    def is_market_open(self, date: datetime, extended_hours: bool = False) -> bool:
        """
        Check if market is open on given date.

        Args:
            date: Date to check
            extended_hours: If True, use 4:00 AM - 8:00 PM ET window.
                            If False (default), use 9:30 AM - 4:00 PM ET.

        Returns:
            True if market is open, False otherwise
        """
        if self.use_massive:
            return self._check_massive_market_status(date, extended_hours)
        else:
            return self._check_yfinance_market_status(date, extended_hours)

    def _check_massive_market_status(self, date: datetime, extended_hours: bool = False) -> bool:
        """Check market status using Massive API"""
        try:
            eastern = pytz.timezone('US/Eastern')
            if date.tzinfo is not None:
                date_et = date.astimezone(eastern)
            else:
                date_et = pytz.utc.localize(date).astimezone(eastern)

            if date_et.weekday() >= 5:
                return False

            hour_float = date_et.hour + date_et.minute / 60.0
            if extended_hours:
                return 4.0 <= hour_float < 20.0
            else:
                return 9.5 <= hour_float < 16.0

        except Exception as e:
            logger.error(f"Error checking Massive market status: {e}")
            return False

    def _check_yfinance_market_status(self, date: datetime, extended_hours: bool = False) -> bool:
        """Check market status using yfinance"""
        try:
            eastern = pytz.timezone('US/Eastern')
            if date.tzinfo is not None:
                date_et = date.astimezone(eastern)
            else:
                date_et = pytz.utc.localize(date).astimezone(eastern)

            if date_et.weekday() >= 5:
                return False

            hour_float = date_et.hour + date_et.minute / 60.0
            if extended_hours:
                return 4.0 <= hour_float < 20.0
            else:
                return 9.5 <= hour_float < 16.0

        except Exception as e:
            logger.error(f"Error checking yfinance market status: {e}")
            return False

# Global instance
massive_util = MassiveUtil()

# Convenience functions
def get_intraday_prices(symbol: str, date: datetime, interval: str = '5') -> pd.DataFrame:
    """Get intraday price data with automatic fallback"""
    return massive_util.get_intraday_prices(symbol, date, interval)

def get_ticker_info(symbol: str) -> Optional[Dict[str, Any]]:
    """Get ticker information with automatic fallback"""
    return massive_util.get_ticker_info(symbol)

def is_market_open(date: datetime, extended_hours: bool = False) -> bool:
    """Check if market is open with automatic fallback"""
    return massive_util.is_market_open(date, extended_hours=extended_hours)

def get_historical_data(symbol: str, start_date: datetime, end_date: datetime, timeframe: str = 'day', interval: int = 1) -> pd.DataFrame:
    """Get historical price data with automatic fallback"""
    return massive_util.get_historical_data(symbol, start_date, end_date, timeframe, interval)
