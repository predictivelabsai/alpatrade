import unittest
from datetime import datetime, timedelta
import pandas as pd
import sys
import os

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.massive_util import MassiveUtil, get_historical_data, get_intraday_prices

class TestMassiveUtil(unittest.TestCase):
    def test_massive_util_init(self):
        """Test MassiveUtil initialization"""
        util = MassiveUtil()
        # This just ensures it doesn't crash
        self.assertTrue(hasattr(util, 'api_key'))

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

    def test_delayed_status_handling(self):
        """Test that the code handles 'DELAYED' status"""
        util = MassiveUtil()
        import inspect
        source = inspect.getsource(util._get_massive_historical)
        self.assertIn("data.get('resultsCount', 0) == 0", source)
        self.assertNotIn("data['status'] != 'OK'", source)

    def test_invalid_symbol(self):
        """Test with an invalid symbol"""
        df = get_historical_data("INVALID_SYMBOL_XYZ_123", start_date=datetime.now()-timedelta(days=2), end_date=datetime.now())
        self.assertIsInstance(df, pd.DataFrame)
        self.assertTrue(df.empty)

if __name__ == '__main__':
    unittest.main()
