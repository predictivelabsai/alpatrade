"""
PDT (Pattern Day Trader) Rule Tracker

Enforces FINRA Pattern Day Trading rule: accounts under $25k are limited
to 3 day trades in a rolling 5-business-day window. This tracker is
conservative — it blocks at 3 to avoid triggering the 4th.
"""

from datetime import date, timedelta
from typing import Dict, List, Optional


class PDTTracker:
    """Track day trades in a rolling 5-business-day window."""

    def __init__(self):
        # List of (date, symbol) for each day trade
        self._day_trades: List[Dict] = []

    def _business_days_back(self, from_date: date, n: int) -> date:
        """Get the date n business days before from_date."""
        current = from_date
        days_counted = 0
        while days_counted < n:
            current -= timedelta(days=1)
            if current.weekday() < 5:  # Mon-Fri
                days_counted += 1
        return current

    def _count_in_window(self, check_date: date) -> int:
        """Count day trades in the 5-business-day window ending on check_date."""
        window_start = self._business_days_back(check_date, 5)
        return sum(
            1 for dt in self._day_trades
            if window_start < dt["date"] <= check_date
        )

    def can_day_trade(self, check_date) -> bool:
        """Return True if a day trade is allowed (count < 3 in window)."""
        if hasattr(check_date, 'date'):
            check_date = check_date.date()
        return self._count_in_window(check_date) < 3

    def get_day_trade_count(self, check_date) -> int:
        """Get the number of day trades in the current 5-business-day window."""
        if hasattr(check_date, 'date'):
            check_date = check_date.date()
        return self._count_in_window(check_date)

    def record_day_trade(self, trade_date, symbol: str):
        """Record a day trade."""
        if hasattr(trade_date, 'date'):
            trade_date = trade_date.date()
        self._day_trades.append({"date": trade_date, "symbol": symbol})

    def bootstrap(self, day_trades: List[Dict]):
        """Load historical day trades from DB/Alpaca on startup.

        Args:
            day_trades: List of {"date": date, "symbol": str} dicts
        """
        self._day_trades = []
        for dt in day_trades:
            d = dt["date"]
            if hasattr(d, 'date'):
                d = d.date()
            elif isinstance(d, str):
                d = date.fromisoformat(d)
            self._day_trades.append({"date": d, "symbol": dt["symbol"]})

    @staticmethod
    def check_account_pdt_status(account: Dict) -> Dict:
        """Check Alpaca account for PDT flags.

        Returns dict with:
            - blocked: bool (True = cannot trade at all)
            - reason: str (human-readable explanation)
            - equity: float
            - daytrade_count: int
            - pattern_day_trader: bool
        """
        blocked = False
        reason = ""
        equity = float(account.get("equity", 0))
        pdt_flagged = account.get("pattern_day_trader", False)
        trading_blocked = account.get("trading_blocked", False)
        daytrade_count = int(account.get("daytrade_count", 0))

        if trading_blocked:
            blocked = True
            reason = "Account trading is blocked by Alpaca"
        elif pdt_flagged and equity < 25000:
            blocked = True
            reason = f"PDT-flagged account with equity ${equity:,.2f} < $25k"
        elif daytrade_count >= 3 and equity < 25000:
            blocked = True
            reason = f"At {daytrade_count} day trades with equity ${equity:,.2f} < $25k — next day trade would trigger PDT flag"

        return {
            "blocked": blocked,
            "reason": reason,
            "equity": equity,
            "daytrade_count": daytrade_count,
            "pattern_day_trader": pdt_flagged,
        }

    def reset(self):
        """Clear all tracked day trades."""
        self._day_trades.clear()
