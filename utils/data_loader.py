"""
Shared data loading functions for strategy modules.

Provides yfinance-based data fetching for intraday and historical data.
"""
import logging
from datetime import datetime
from typing import Dict, List

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def get_intraday_data(ticker: str, interval: str = '1d', period: str = '30d') -> pd.DataFrame:
    """
    Fetch intraday or daily data from yfinance.

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
            logger.warning(f"No data returned for {ticker} with interval {interval}")
            return pd.DataFrame()

        # Ensure timezone-aware datetime index
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        else:
            df.index = df.index.tz_convert('UTC')

        return df
    except Exception as e:
        logger.error(f"Error fetching data for {ticker}: {e}")
        return pd.DataFrame()


def get_historical_data(symbols: List[str], start_date: datetime,
                        end_date: datetime) -> Dict[str, pd.DataFrame]:
    """Fetch historical price data for multiple symbols."""
    data = {}
    for symbol in symbols:
        try:
            df = yf.download(symbol, start=start_date, end=end_date, progress=False)
            if not df.empty:
                data[symbol] = df
        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")
    return data
