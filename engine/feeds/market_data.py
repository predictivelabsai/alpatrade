"""Market-data feed backed by Yahoo Finance or Alpaca."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pandas as pd
import pytz
import yfinance as yf

logger = logging.getLogger(__name__)


def _provider(value: str | None = None) -> str:
    selected = (value or os.getenv("MARKET_DATA_PROVIDER") or "yfinance").strip().lower()
    return "alpaca" if selected == "alpaca" else "yfinance"


class MarketDataUtil:
    """OHLCV adapter with Yahoo Finance default and optional Alpaca data."""

    def __init__(self, provider: str | None = None, api_key: str | None = None,
                 secret_key: str | None = None):
        self.provider = _provider(provider)
        self.api_key = api_key or os.getenv("ALPACA_PAPER_API_KEY")
        self.secret_key = secret_key or os.getenv("ALPACA_PAPER_SECRET_KEY")
        if self.provider == "alpaca" and not (self.api_key and self.secret_key):
            logger.warning("Alpaca market data selected without credentials; using yfinance")
            self.provider = "yfinance"

    def _alpaca_client(self):
        from alpaca.data.historical import StockHistoricalDataClient
        return StockHistoricalDataClient(self.api_key, self.secret_key)

    @staticmethod
    def _normalise(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if frame is None or frame.empty:
            return pd.DataFrame()
        frame = frame.copy()
        if isinstance(frame.index, pd.MultiIndex):
            try:
                frame = frame.xs(symbol, level=0)
            except (KeyError, ValueError):
                frame = frame.droplevel(0)
        # yfinance 1.5+ returns MultiIndex columns even for a single symbol,
        # e.g. [('Close', 'AAPL'), ('High', 'AAPL'), ...]. Flatten to plain
        # field names so `df['Close']` yields a Series, not a DataFrame.
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.droplevel(1)
        frame.rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        }, inplace=True)
        return frame

    def get_intraday_prices(self, symbol: str, date: datetime,
                            interval: str = "5") -> pd.DataFrame:
        if self.provider == "alpaca":
            return self._alpaca_bars(
                symbol, date, date + timedelta(days=1), "minute", int(interval))
        start = date.strftime("%Y-%m-%d")
        end = (date + timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            return self._normalise(yf.download(
                symbol, start=start, end=end, interval=f"{interval}m",
                progress=False, auto_adjust=False), symbol)
        except Exception as exc:  # noqa: BLE001
            logger.error("Yahoo Finance intraday request failed for %s: %s", symbol, exc)
            return pd.DataFrame()

    def get_historical_data(self, symbol: str, start_date: datetime,
                            end_date: datetime, timeframe: str = "day",
                            interval: int = 1) -> pd.DataFrame:
        if self.provider == "alpaca":
            return self._alpaca_bars(
                symbol, start_date, end_date, timeframe, interval)
        yf_interval = {
            "minute": f"{interval}m", "hour": f"{interval}h",
            "day": f"{interval}d", "week": f"{interval}wk",
            "month": f"{interval}mo",
        }.get(timeframe, "1d")
        try:
            return self._normalise(yf.download(
                symbol, start=start_date, end=end_date, interval=yf_interval,
                progress=False, auto_adjust=False), symbol)
        except Exception as exc:  # noqa: BLE001
            logger.error("Yahoo Finance historical request failed for %s: %s", symbol, exc)
            return pd.DataFrame()

    def _alpaca_bars(self, symbol: str, start: datetime, end: datetime,
                     timeframe: str, interval: int) -> pd.DataFrame:
        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
            units = {
                "minute": TimeFrameUnit.Minute, "hour": TimeFrameUnit.Hour,
                "day": TimeFrameUnit.Day, "week": TimeFrameUnit.Week,
                "month": TimeFrameUnit.Month,
            }
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame(interval, units.get(timeframe, TimeFrameUnit.Day)),
                start=start,
                end=end,
            )
            return self._normalise(self._alpaca_client().get_stock_bars(request).df, symbol)
        except Exception as exc:  # noqa: BLE001
            logger.error("Alpaca market-data request failed for %s: %s", symbol, exc)
            return pd.DataFrame()

    def get_ticker_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        try:
            info = yf.Ticker(symbol).info
            return info or None
        except Exception as exc:  # noqa: BLE001
            logger.error("Yahoo Finance ticker request failed for %s: %s", symbol, exc)
            return None

    def is_market_open(self, date: datetime,
                       extended_hours: bool = False) -> bool:
        eastern = pytz.timezone("US/Eastern")
        local = date.astimezone(eastern) if date.tzinfo else eastern.localize(date)
        if local.weekday() >= 5:
            return False
        open_hour, close_hour = ((4, 20) if extended_hours else (9.5, 16))
        current = local.hour + local.minute / 60
        return open_hour <= current < close_hour


market_data_util = MarketDataUtil()


def get_intraday_prices(symbol: str, date: datetime, interval: str = "5") -> pd.DataFrame:
    return market_data_util.get_intraday_prices(symbol, date, interval)


def get_ticker_info(symbol: str) -> Optional[Dict[str, Any]]:
    return market_data_util.get_ticker_info(symbol)


def is_market_open(date: datetime, extended_hours: bool = False) -> bool:
    return market_data_util.is_market_open(date, extended_hours)


def get_historical_data(symbol: str, start_date: datetime, end_date: datetime,
                        timeframe: str = "day", interval: int = 1) -> pd.DataFrame:
    return market_data_util.get_historical_data(
        symbol, start_date, end_date, timeframe, interval)
