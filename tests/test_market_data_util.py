import unittest
from datetime import datetime, timedelta
import pandas as pd
import sys
import os
from unittest.mock import patch

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.feeds.market_data import MarketDataUtil, get_historical_data, get_intraday_prices

class TestMarketDataUtil(unittest.TestCase):
    def test_yfinance_is_default(self):
        util = MarketDataUtil()
        self.assertEqual(util.provider, "yfinance")

    def test_get_historical_data_daily(self):
        """Test getting daily data for AAPL"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=10)
        
        df = get_historical_data("AAPL", start_date=start_date, end_date=end_date)
        
        self.assertIsInstance(df, pd.DataFrame)
        if not df.empty:
            self.assertIn('Open', df.columns)
            self.assertIn('Close', df.columns)
            self.assertIn('High', df.columns)
            self.assertIn('Low', df.columns)
            self.assertIn('Volume', df.columns)

    def test_get_intraday_prices(self):
        """Test getting intraday data (1-min bars)"""
        date = datetime.now()
        while date.weekday() >= 5:
            date -= timedelta(days=1)
        
        if date.hour < 10:
            date -= timedelta(days=1)
            while date.weekday() >= 5:
                date -= timedelta(days=1)

        df = get_intraday_prices("AAPL", date=date, interval='1')
        
        self.assertIsInstance(df, pd.DataFrame)
        if not df.empty:
            self.assertIn('Close', df.columns)

    def test_unknown_provider_falls_back_to_yfinance(self):
        self.assertEqual(MarketDataUtil(provider="retired").provider, "yfinance")

    def test_alpaca_provider_without_credentials_falls_back(self):
        with patch.dict(os.environ, {
            "ALPACA_PAPER_API_KEY": "", "ALPACA_PAPER_SECRET_KEY": "",
        }):
            util = MarketDataUtil(provider="alpaca")
        self.assertEqual(util.provider, "yfinance")

    def test_invalid_symbol(self):
        """Test with an invalid symbol"""
        df = get_historical_data("INVALID_SYMBOL_XYZ_123", start_date=datetime.now()-timedelta(days=2), end_date=datetime.now())
        self.assertIsInstance(df, pd.DataFrame)
        self.assertTrue(df.empty)

if __name__ == '__main__':
    unittest.main()
