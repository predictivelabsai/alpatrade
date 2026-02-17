"""
Paper Trading Agent

Executes real paper trades via the Alpaca paper trading API.
Runs continuously for a configurable duration, applying validated
strategy parameters. Logs trades to the DB.
"""

import sys
import uuid
import time
import logging
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

# Ensure project root is importable
project_root = Path(__file__).parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from utils.alpaca_util import AlpacaAPI
from utils.massive_util import get_historical_data, get_intraday_prices, is_market_open
from utils.agent_storage import store_paper_trade
from utils.pdt_tracker import PDTTracker

logger = logging.getLogger(__name__)


class PaperTradeAgent:
    """Agent that runs continuous paper trading via Alpaca paper API."""

    def __init__(self, message_bus=None, state=None):
        self.message_bus = message_bus
        self.state = state
        self.client: Optional[AlpacaAPI] = None
        self.session_id = str(uuid.uuid4())
        self.trades: List[Dict[str, Any]] = []
        self.daily_pnl: List[Dict[str, Any]] = []
        self._tracked_positions: Dict[str, Dict] = {}
        self.pdt_tracker = PDTTracker()

    def run(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run paper trading session.

        Args:
            request: Dict with keys:
                - strategy: str (default "buy_the_dip")
                - symbols: list of str
                - params: dict with strategy parameters
                - duration_seconds: int (default 604800 = 1 week)
                - poll_interval_seconds: int (default 300 = 5 min)

        Returns:
            Dict with session summary
        """
        strategy = request.get("strategy", "buy_the_dip")
        symbols = request.get("symbols", ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"])
        params = request.get("params", {})
        duration = request.get("duration_seconds", 604800)
        poll_interval = request.get("poll_interval_seconds", 300)
        extended_hours = request.get("extended_hours", False)
        email_notifications = request.get("email_notifications", True)

        # PDT protection: default True, disable with pdt:false for accounts >$25k
        pdt_protection = request.get("pdt_protection")
        if pdt_protection is False:
            self.pdt_tracker = None
        else:
            self.pdt_tracker = PDTTracker()

        # Strategy parameters with defaults
        dip_threshold = params.get("dip_threshold", 5.0)
        take_profit = params.get("take_profit_threshold", 1.0)
        stop_loss = params.get("stop_loss_threshold", 0.5)
        hold_days = params.get("hold_days", 2)
        capital_per_trade = params.get("capital_per_trade", 1000.0)

        logger.info(f"Paper trade agent starting session {self.session_id}")
        logger.info(f"Strategy: {strategy}, Symbols: {symbols}")
        logger.info(f"Duration: {duration}s, Poll interval: {poll_interval}s")
        logger.info(f"Params: dip={dip_threshold}%, tp={take_profit}%, sl={stop_loss}%, hold={hold_days}d")

        # Initialize Alpaca client
        try:
            self.client = AlpacaAPI(paper=True)
            account = self.client.get_account()
            if "error" in account:
                raise RuntimeError(f"Alpaca API error: {account['error']}")
            logger.info(f"Connected to Alpaca paper. Portfolio value: ${float(account.get('portfolio_value', 0)):,.2f}")
        except Exception as e:
            logger.error(f"Failed to initialize Alpaca client: {e}")
            return {"error": str(e), "session_id": self.session_id}

        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(seconds=duration)
        last_daily_report = start_time.date()

        logger.info(f"Trading until {end_time.isoformat()}")

        try:
            while datetime.now(timezone.utc) < end_time:
                now = datetime.now(timezone.utc)

                # Check if market is open
                if not is_market_open(now, extended_hours=extended_hours):
                    logger.debug("Market closed, sleeping...")
                    time.sleep(min(poll_interval, 60))
                    continue

                # Execute one trading cycle
                try:
                    self._execute_cycle(
                        symbols=symbols,
                        dip_threshold=dip_threshold,
                        take_profit=take_profit,
                        stop_loss=stop_loss,
                        hold_days=hold_days,
                        capital_per_trade=capital_per_trade,
                    )
                except Exception as e:
                    logger.error(f"Trading cycle error: {e}")
                    if self.message_bus:
                        self.message_bus.publish(
                            from_agent="paper_trader",
                            to_agent="portfolio_manager",
                            msg_type="error",
                            payload={"error": str(e), "session_id": self.session_id},
                        )

                # Daily P&L report + email
                today = datetime.now(timezone.utc).date()
                if today > last_daily_report:
                    self._record_daily_pnl()
                    if email_notifications:
                        self._send_daily_email(last_daily_report.isoformat())
                    last_daily_report = today

                time.sleep(poll_interval)

        except KeyboardInterrupt:
            logger.info("Paper trading interrupted by user")

        # Final summary
        return self._generate_summary(start_time)

    def _execute_cycle(self, symbols, dip_threshold, take_profit, stop_loss,
                       hold_days, capital_per_trade):
        """Execute one buy-the-dip trading cycle: check exits then entries."""
        # 1. Process exits
        self._process_exits(take_profit, stop_loss, hold_days)

        # 2. Process entries
        self._process_entries(symbols, dip_threshold, capital_per_trade)

    def _process_exits(self, take_profit, stop_loss, hold_days):
        """Check existing positions for exit signals."""
        try:
            positions = self.client.get_positions()
            if isinstance(positions, dict) and "error" in positions:
                logger.error(f"Error getting positions: {positions['error']}")
                return

            for pos in positions:
                symbol = pos.get("symbol")
                qty = float(pos.get("qty", 0))
                entry_price = float(pos.get("avg_entry_price", 0))
                current_price = float(pos.get("current_price", 0))

                if entry_price <= 0:
                    continue

                unrealized_pct = ((current_price - entry_price) / entry_price) * 100

                # Check hold period from tracked positions
                tracked = self._tracked_positions.get(symbol, {})
                entry_time_str = tracked.get("entry_time")
                if entry_time_str:
                    entry_dt = datetime.fromisoformat(entry_time_str)
                    days_held = (datetime.now(timezone.utc) - entry_dt).days
                else:
                    days_held = 99

                # PDT protection using tracker
                if self.pdt_tracker and entry_time_str:
                    entry_dt = datetime.fromisoformat(entry_time_str)
                    if entry_dt.date() == datetime.now(timezone.utc).date():
                        if not self.pdt_tracker.can_day_trade(datetime.now(timezone.utc)):
                            logger.debug(f"PDT protection: cannot sell {symbol} same day (3 day trades in 5-day window)")
                            continue

                exit_reason = None
                if unrealized_pct >= take_profit:
                    exit_reason = f"TAKE_PROFIT ({unrealized_pct:.2f}%)"
                elif unrealized_pct <= -stop_loss:
                    exit_reason = f"STOP_LOSS ({unrealized_pct:.2f}%)"
                elif days_held >= hold_days:
                    exit_reason = f"HOLD_EXPIRED ({days_held}d)"

                if exit_reason:
                    logger.info(f"EXIT {symbol}: {exit_reason}")
                    result = self.client.close_position(symbol)
                    if "error" not in result:
                        pnl = (current_price - entry_price) * qty
                        trade = {
                            "symbol": symbol,
                            "side": "sell",
                            "qty": qty,
                            "entry_price": entry_price,
                            "exit_price": current_price,
                            "pnl": pnl,
                            "pnl_pct": unrealized_pct,
                            "reason": exit_reason,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        self.trades.append(trade)
                        self._tracked_positions.pop(symbol, None)
                        self._store_trade(trade)
                        self._publish_trade_update(trade)

                        # Record day trade in PDT tracker if same-day exit
                        if self.pdt_tracker and entry_time_str:
                            entry_dt = datetime.fromisoformat(entry_time_str)
                            if entry_dt.date() == datetime.now(timezone.utc).date():
                                self.pdt_tracker.record_day_trade(datetime.now(timezone.utc), symbol)
                    else:
                        logger.error(f"Failed to exit {symbol}: {result['error']}")

        except Exception as e:
            logger.error(f"Exit processing error: {e}")

    def _process_entries(self, symbols, dip_threshold, capital_per_trade):
        """Check for dip entry signals."""
        try:
            # Get existing positions to skip
            positions = self.client.get_positions()
            existing = set()
            if isinstance(positions, list):
                existing = {p.get("symbol") for p in positions}

            account = self.client.get_account()
            if "error" in account:
                return
            buying_power = float(account.get("buying_power", 0))
            max_position = buying_power * 0.05

            for symbol in symbols:
                if symbol in existing:
                    continue

                try:
                    # Get recent price data
                    end_date = datetime.now()
                    start_date = end_date - timedelta(days=40)
                    hist = get_historical_data(symbol, start_date=start_date, end_date=end_date)

                    if hist.empty:
                        continue

                    # Calculate dip from 20-period high
                    high_series = hist["High"].tail(20)
                    max_val = high_series.max()
                    recent_high = float(max_val.iloc[0]) if hasattr(max_val, "iloc") else float(max_val)

                    # Get current price from intraday if possible
                    current_price = None
                    today_data = get_intraday_prices(symbol, date=end_date, interval="1")
                    if not today_data.empty:
                        val = today_data["Close"].iloc[-1]
                        current_price = float(val.item()) if hasattr(val, "item") else float(val)

                    if current_price is None:
                        val = hist["Close"].iloc[-1]
                        current_price = float(val.iloc[0]) if hasattr(val, "iloc") else float(val)

                    dip_pct = ((recent_high - current_price) / recent_high) * 100

                    if dip_pct < dip_threshold:
                        continue

                    # Calculate position size
                    position_value = min(capital_per_trade, max_position)
                    if position_value > buying_power:
                        continue

                    qty = int(position_value / current_price)
                    if qty == 0:
                        continue

                    # Check for existing position one more time
                    pos_check = self.client.get_position(symbol)
                    if pos_check and isinstance(pos_check, dict) and "error" not in pos_check:
                        continue

                    # Place order
                    result = self.client.create_order(
                        symbol=symbol, qty=qty, side="buy",
                        type="market", time_in_force="day",
                    )

                    if "error" not in result:
                        logger.info(f"BUY {qty} {symbol} @ ~${current_price:.2f} (dip: {dip_pct:.1f}%)")
                        entry_time = datetime.now(timezone.utc).isoformat()
                        self._tracked_positions[symbol] = {
                            "entry_time": entry_time,
                            "entry_price": current_price,
                            "qty": qty,
                        }
                        trade = {
                            "symbol": symbol,
                            "side": "buy",
                            "qty": qty,
                            "price": current_price,
                            "dip_pct": dip_pct,
                            "order_id": str(result.get("id", "")),
                            "timestamp": entry_time,
                        }
                        self.trades.append(trade)
                        self._store_trade(trade)
                        self._publish_trade_update(trade)
                        buying_power -= position_value
                        max_position = buying_power * 0.05
                    else:
                        logger.error(f"Order failed for {symbol}: {result['error']}")

                    # Rate limit
                    time.sleep(0.5)

                except Exception as e:
                    logger.error(f"Entry processing error for {symbol}: {e}")

        except Exception as e:
            logger.error(f"Entry cycle error: {e}")

    def _store_trade(self, trade: Dict):
        """Store trade using the configured backend (file or DB)."""
        try:
            store_paper_trade(self.session_id, trade)
        except Exception as e:
            logger.warning(f"Could not store trade: {e}")

    def _publish_trade_update(self, trade: Dict):
        """Send trade update to message bus."""
        if self.message_bus:
            self.message_bus.publish(
                from_agent="paper_trader",
                to_agent="portfolio_manager",
                msg_type="trade_update",
                payload={**trade, "session_id": self.session_id},
            )

    def _record_daily_pnl(self):
        """Record daily P&L snapshot."""
        try:
            account = self.client.get_account()
            if "error" not in account:
                self.daily_pnl.append({
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "portfolio_value": float(account.get("portfolio_value", 0)),
                    "cash": float(account.get("cash", 0)),
                    "equity": float(account.get("equity", 0)),
                })
        except Exception as e:
            logger.warning(f"Could not record daily P&L: {e}")

    def _send_daily_email(self, date: str):
        """Send daily P&L email report via Postmark."""
        try:
            from utils.email_util import send_daily_pnl_report

            # Gather positions
            positions = []
            try:
                pos_list = self.client.get_positions()
                if isinstance(pos_list, list):
                    positions = pos_list
            except Exception:
                pass

            # Calculate daily P&L from today's sell trades
            sell_trades = [t for t in self.trades if t.get("side") == "sell"]
            today_trades = [t for t in self.trades
                           if t.get("timestamp", "").startswith(date)]
            daily_pnl = sum(t.get("pnl", 0) for t in sell_trades
                           if t.get("timestamp", "").startswith(date))
            cumulative_pnl = sum(t.get("pnl", 0) for t in sell_trades)
            win_count = sum(1 for t in sell_trades if (t.get("pnl") or 0) > 0)
            win_rate = (win_count / len(sell_trades) * 100) if sell_trades else 0.0

            send_daily_pnl_report(
                date=date,
                pnl=daily_pnl,
                positions=positions,
                trades=today_trades,
                cumulative_pnl=cumulative_pnl,
                win_rate=win_rate,
            )
        except Exception as e:
            logger.warning(f"Could not send daily email: {e}")

    def _generate_summary(self, start_time: datetime) -> Dict[str, Any]:
        """Generate session summary."""
        duration = datetime.now(timezone.utc) - start_time
        sell_trades = [t for t in self.trades if t.get("side") == "sell"]
        winning = [t for t in sell_trades if (t.get("pnl") or 0) > 0]
        losing = [t for t in sell_trades if (t.get("pnl") or 0) < 0]
        total_pnl = sum(t.get("pnl", 0) for t in sell_trades)

        # Get final positions
        final_positions = []
        try:
            positions = self.client.get_positions()
            if isinstance(positions, list):
                final_positions = positions
        except Exception:
            pass

        summary = {
            "session_id": self.session_id,
            "duration_seconds": int(duration.total_seconds()),
            "total_trades": len(self.trades),
            "sell_trades": len(sell_trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "total_pnl": total_pnl,
            "daily_pnl": self.daily_pnl,
            "final_positions": final_positions,
        }

        # Publish result
        if self.message_bus:
            self.message_bus.publish(
                from_agent="paper_trader",
                to_agent="portfolio_manager",
                msg_type="paper_trade_result",
                payload=summary,
            )

        logger.info(
            f"Paper trading session {self.session_id} complete: "
            f"{len(self.trades)} trades, P&L: ${total_pnl:.2f}"
        )
        return summary
