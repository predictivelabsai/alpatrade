"""
EODHD API Utility Functions
Real-time and historical market data from EODHD (End of Day Historical Data)
"""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class EODHD_API:
    """EODHD API client for real-time and historical market data"""
    
    def __init__(self, api_key=None):
        """
        Initialize EODHD API client
        
        Args:
            api_key: EODHD API key (defaults to EODHD_API_KEY env var)
        """
        self.api_key = api_key or os.getenv('EODHD_API_KEY')
        if not self.api_key:
            raise ValueError("EODHD API key is required")
        
        self.base_url = "https://eodhd.com/api"
    
    def get_real_time_price(self, symbol, exchange='US'):
        """
        Get real-time price for a symbol
        
        Args:
            symbol: Stock ticker symbol
            exchange: Exchange code (default: US)
            
        Returns:
            dict: Real-time price data
        """
        try:
            url = f"{self.base_url}/real-time/{symbol}.{exchange}"
            params = {
                'api_token': self.api_key,
                'fmt': 'json'
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            return {
                'symbol': symbol,
                'price': data.get('close', 0),
                'open': data.get('open', 0),
                'high': data.get('high', 0),
                'low': data.get('low', 0),
                'volume': data.get('volume', 0),
                'timestamp': data.get('timestamp', datetime.now().timestamp()),
                'change': data.get('change', 0),
                'change_p': data.get('change_p', 0)
            }
            
        except Exception as e:
            logger.error(f"Error fetching real-time price for {symbol}: {str(e)}")
            return {'error': str(e)}
    
    def get_intraday_data(self, symbol, interval='1m', exchange='US'):
        """
        Get intraday data (minute-by-minute)
        
        Args:
            symbol: Stock ticker symbol
            interval: Time interval (1m, 5m, 1h)
            exchange: Exchange code (default: US)
            
        Returns:
            pandas.DataFrame: Intraday price data
        """
        try:
            url = f"{self.base_url}/intraday/{symbol}.{exchange}"
            params = {
                'api_token': self.api_key,
                'interval': interval,
                'fmt': 'json'
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if not data:
                logger.warning(f"No intraday data for {symbol}")
                return pd.DataFrame()
            
            df = pd.DataFrame(data)
            
            # Convert timestamp to datetime
            if 'timestamp' in df.columns:
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
                df.set_index('datetime', inplace=True)
            
            # Rename columns to match standard format
            column_mapping = {
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            }
            df.rename(columns=column_mapping, inplace=True)
            
            return df
            
        except Exception as e:
            logger.error(f"Error fetching intraday data for {symbol}: {str(e)}")
            return pd.DataFrame()
    
    def get_historical_data(self, symbol, from_date=None, to_date=None, exchange='US'):
        """
        Get historical end-of-day data
        
        Args:
            symbol: Stock ticker symbol
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            exchange: Exchange code (default: US)
            
        Returns:
            pandas.DataFrame: Historical price data
        """
        try:
            url = f"{self.base_url}/eod/{symbol}.{exchange}"
            
            params = {
                'api_token': self.api_key,
                'fmt': 'json'
            }
            
            if from_date:
                params['from'] = from_date
            if to_date:
                params['to'] = to_date
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if not data:
                logger.warning(f"No historical data for {symbol}")
                return pd.DataFrame()
            
            df = pd.DataFrame(data)
            
            # Convert date to datetime
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
            
            # Rename columns to match standard format
            column_mapping = {
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'adjusted_close': 'Adj Close',
                'volume': 'Volume'
            }
            df.rename(columns=column_mapping, inplace=True)
            
            return df
            
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {str(e)}")
            return pd.DataFrame()
    
    def get_multiple_real_time_prices(self, symbols, exchange='US'):
        """
        Get real-time prices for multiple symbols
        
        Args:
            symbols: List of stock ticker symbols
            exchange: Exchange code (default: US)
            
        Returns:
            dict: Dictionary of symbol -> price data
        """
        results = {}
        
        for symbol in symbols:
            price_data = self.get_real_time_price(symbol, exchange)
            results[symbol] = price_data
        
        return results
    
    def get_quote(self, symbol, exchange='US'):
        """
        Get detailed quote for a symbol
        
        Args:
            symbol: Stock ticker symbol
            exchange: Exchange code (default: US)
            
        Returns:
            dict: Quote data including bid/ask
        """
        try:
            url = f"{self.base_url}/real-time/{symbol}.{exchange}"
            params = {
                'api_token': self.api_key,
                'fmt': 'json',
                's': symbol
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {str(e)}")
            return {'error': str(e)}


def get_real_time_price(symbol, exchange='US'):
    """
    Convenience function to get real-time price
    
    Args:
        symbol: Stock ticker symbol
        exchange: Exchange code (default: US)
        
    Returns:
        float: Current price
    """
    try:
        client = EODHD_API()
        data = client.get_real_time_price(symbol, exchange)
        
        if 'error' in data:
            return None
        
        return data.get('price', 0)
        
    except Exception as e:
        logger.error(f"Error getting real-time price: {str(e)}")
        return None


def get_intraday_data(symbol, interval='1m', exchange='US'):
    """
    Convenience function to get intraday data
    
    Args:
        symbol: Stock ticker symbol
        interval: Time interval (1m, 5m, 1h)
        exchange: Exchange code (default: US)
        
    Returns:
        pandas.DataFrame: Intraday price data
    """
    try:
        client = EODHD_API()
        return client.get_intraday_data(symbol, interval, exchange)
        
    except Exception as e:
        logger.error(f"Error getting intraday data: {str(e)}")
        return pd.DataFrame()


def get_historical_data(symbol, from_date=None, to_date=None, exchange='US'):
    """
    Convenience function to get historical data
    
    Args:
        symbol: Stock ticker symbol
        from_date: Start date (YYYY-MM-DD)
        to_date: End date (YYYY-MM-DD)
        exchange: Exchange code (default: US)
        
    Returns:
        pandas.DataFrame: Historical price data
    """
    try:
        client = EODHD_API()
        return client.get_historical_data(symbol, from_date, to_date, exchange)
        
    except Exception as e:
        logger.error(f"Error getting historical data: {str(e)}")
        return pd.DataFrame()


if __name__ == '__main__':
    # Test the API
    client = EODHD_API()
    
    # Test real-time price
    print("Testing real-time price for AAPL:")
    price_data = client.get_real_time_price('AAPL')
    print(price_data)
    
    # Test intraday data
    print("\nTesting intraday data for AAPL:")
    intraday = client.get_intraday_data('AAPL', interval='1m')
    print(intraday.head() if not intraday.empty else "No data")
    
    # Test historical data
    print("\nTesting historical data for AAPL:")
    historical = client.get_historical_data('AAPL', from_date='2024-01-01')
    print(historical.head() if not historical.empty else "No data")
