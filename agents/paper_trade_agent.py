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
from engine.feeds.market_data import get_historical_data, get_intraday_prices, is_market_open
from utils.agent_storage import (
    store_paper_trade, fetch_paper_trades, fetch_recent_day_trades, heartbeat_run,
)
from utils.config import load_parameters
from utils.pdt_tracker import PDTTracker
from utils.paper_strategies import PARAM_SCHEMA, canonical_strategy, resolve_paper_params
from utils.paper_signals import (
    box_wedge_entry_signal,
    box_wedge_stop_target,
    fetch_vix_close,
    momentum_entry_signal,
    vix_entry_signal,
)
from utils.box_wedge import calculate_position_size
from utils.data_loader import get_intraday_data
import pytz

logger = logging.getLogger(__name__)

_ET = pytz.timezone("America/New_York")


class PaperTradeAgent:
    """Agent that runs continuous paper trading via Alpaca paper API."""

    def __init__(self, message_bus=None, state=None, user_id=None,
                 alpaca_api_key=None, alpaca_secret_key=None,
                 account_id=None, account_name=None):
        self.message_bus = message_bus
        self.state = state
        self.user_id = user_id
        self._alpaca_api_key = alpaca_api_key
        self._alpaca_secret_key = alpaca_secret_key
        self.account_id = account_id
        self.account_name = account_name or ""
        self.client: Optional[AlpacaAPI] = None
        self.session_id = str(uuid.uuid4())
        self.trades: List[Dict[str, Any]] = []
        self.daily_pnl: List[Dict[str, Any]] = []
        self._tracked_positions: Dict[str, Dict] = {}
        self.pdt_tracker = PDTTracker()
        # Per-strategy session state (vix / box_wedge cycles)
        self._entered_today: Dict[str, str] = {}   # symbol -> UTC date of entry
        self._vix_entry_day: Optional[str] = None  # one VIX entry pass per ET day
        self._last_vix_warn: float = 0.0           # rate-limits VIX fetch warnings

    def run(self, request: Dict[str, Any], stop_event=None, run_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Run paper trading session.

        Args:
            request: Dict with keys:
                - strategy: str (default "buy_the_dip")
                - symbols: list of str
                - params: dict with strategy parameters
                - duration_seconds: int (default 604800 = 1 week)
                - poll_interval_seconds: int (default 300 = 5 min)
            stop_event: optional threading.Event checked each loop iteration
            run_id: optional orchestrator run_id (must exist in alpatrade.runs)

        Returns:
            Dict with session summary
        """
        # Use orchestrator's run_id if provided so trades FK to the runs table
        if run_id:
            self.session_id = run_id
        # Load defaults from parameters.yaml
        yaml_params = load_parameters()
        yaml_general = yaml_params.get("general", {})

        strategy = canonical_strategy(request.get("strategy") or "buy_the_dip")
        if strategy not in PARAM_SCHEMA:
            logger.error(f"Unknown paper strategy {strategy!r} — refusing to trade")
            return {"error": f"Unknown strategy: {strategy}", "session_id": self.session_id}
        yaml_cfg = yaml_params.get(strategy, {})
        yaml_symbols = [s.strip() for s in yaml_cfg.get("symbols", "").split(",") if s.strip()]

        symbols = request.get("symbols", yaml_symbols or ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA"])
        params = request.get("params", {})
        duration = request.get("duration_seconds", 604800)
        poll_interval = request.get("poll_interval_seconds", yaml_general.get("polling_interval", 300))
        extended_hours = request.get("extended_hours", True)
        email_notifications = request.get("email_notifications", True)
        report_email = request.get("report_email", "")
        report_hour_utc = int(request.get("report_hour_utc", 21))
        report_format = str(request.get("report_format", "default"))
        advice_enabled = bool(request.get("advice_enabled", False))
        advice_interval = max(60, int(request.get("advice_interval_seconds", 900)))

        # PDT protection: default True, disable with pdt:false for accounts >$25k
        pdt_protection = request.get("pdt_protection")
        if pdt_protection is False:
            self.pdt_tracker = None
        else:
            self.pdt_tracker = PDTTracker()

        # Strategy parameters — percent units (5.0 = 5%). The orchestrator
        # already translated any stored DB ratios to percents, and
        # parameters.yaml is percent-unit too, so resolution here must NOT
        # re-translate (a 0.5% stop_loss would otherwise become 50%).
        # Precedence: explicit params > yaml section > schema defaults.
        resolved = resolve_paper_params(strategy, params, yaml_params, translate=False)
        position_size = resolved.get("position_size")

        logger.info(f"Paper trade agent starting session {self.session_id}")
        logger.info(f"Strategy: {strategy}, Symbols: {symbols}")
        logger.info(f"Duration: {duration}s, Poll interval: {poll_interval}s")
        logger.info(f"Resolved params: {resolved}")

        # Initialize Alpaca client (use injected per-user keys or fall back to env)
        try:
            self.client = AlpacaAPI(
                paper=True,
                api_key=self._alpaca_api_key,
                secret_key=self._alpaca_secret_key,
            )
            account = self.client.get_account()
            if "error" in account:
                raise RuntimeError(f"Alpaca API error: {account['error']}")
            if position_size is not None:
                fraction = float(position_size)
                if not 0 < fraction <= 0.25:
                    raise ValueError("position_size must be greater than 0 and no more than 0.25")
                equity = float(account.get("equity") or account.get("portfolio_value") or 0)
                # Feed the equity-based budget back into the resolved params so
                # the per-strategy cycles size off the same value.
                resolved["capital_per_trade"] = equity * fraction
            logger.info(f"Connected to Alpaca paper. Portfolio value: ${float(account.get('portfolio_value', 0)):,.2f}")
        except Exception as e:
            logger.error(f"Failed to initialize Alpaca client: {e}")
            return {"error": str(e), "session_id": self.session_id}

        # --- PDT bootstrap ---
        if self.pdt_tracker:
            # 1. Check account-level PDT status (hard blocks only)
            pdt_status = PDTTracker.check_account_pdt_status(account)
            if pdt_status["blocked"]:
                logger.error(f"PDT BLOCKED: {pdt_status['reason']}")
                return {"error": f"PDT blocked: {pdt_status['reason']}",
                        "session_id": self.session_id}

            # 2. Bootstrap from DB (recent same-day round-trips)
            db_day_trades = fetch_recent_day_trades(
                window_days=7,
                user_id=self.user_id,
                account_id=self.account_id,
            )
            if db_day_trades:
                self.pdt_tracker.bootstrap(db_day_trades)
                logger.info(f"PDT tracker bootstrapped with {len(db_day_trades)} DB day trades")

            # 3. Cross-check with Alpaca's count — use the higher of the two
            alpaca_count = pdt_status["daytrade_count"]
            tracker_count = self.pdt_tracker.get_day_trade_count(datetime.now(timezone.utc))
            if alpaca_count > tracker_count:
                # Alpaca knows about day trades our DB missed — sync up
                for _ in range(alpaca_count - tracker_count):
                    self.pdt_tracker.record_day_trade(datetime.now(timezone.utc), "_synced")
                logger.info(f"PDT tracker synced: added {alpaca_count - tracker_count} missing day trades from Alpaca")
                tracker_count = alpaca_count

            if tracker_count >= 3:
                logger.warning(f"PDT: at {tracker_count}/3 day trades — new entries and same-day exits blocked, but multi-day exits still allowed")
            else:
                logger.info(f"PDT status: {tracker_count}/3 day trades in window, "
                            f"Alpaca daytrade_count={alpaca_count}")

        # --- Sync open orders and positions from Alpaca ---
        self._sync_orders_and_positions()

        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(seconds=duration)
        last_daily_report = None
        last_advice_at = 0.0
        cycle_count = 0

        logger.info(f"Trading until {end_time.isoformat()}")
        heartbeat_run(self.session_id)

        try:
            while datetime.now(timezone.utc) < end_time:
                heartbeat_run(self.session_id)
                if stop_event and hasattr(stop_event, "wait_if_paused"):
                    if not stop_event.wait_if_paused():
                        logger.info("Paper trading stopped while paused")
                        break
                # Check for external stop request
                if stop_event and stop_event.is_set():
                    logger.info("Paper trading stopped via stop event")
                    break

                # Stamp liveness so the stale-run sweep never mistakes an active
                # (possibly long-running) session for an interrupted orphan.
                heartbeat_run(self.session_id)

                now = datetime.now(timezone.utc)
                live_advice = {}
                if stop_event and hasattr(stop_event, "advice_settings"):
                    live_advice = stop_event.advice_settings()
                    advice_enabled = bool(live_advice.get("enabled", advice_enabled))
                    advice_interval = int(
                        live_advice.get("interval_seconds", advice_interval)
                    )

                # Send at most one owned report per UTC trading date after the
                # configured post-close hour, even while the market is closed.
                if now.hour >= report_hour_utc and last_daily_report != now.date():
                    if stop_event and hasattr(stop_event, "report_target"):
                        email_notifications, report_email = stop_event.report_target()
                    if email_notifications:
                        self._record_daily_pnl()
                        daily_advice = (stop_event.recent_advice() if stop_event and
                                        hasattr(stop_event, "recent_advice") else [])
                        self._send_daily_email(
                            now.date().isoformat(), report_email, advice=daily_advice,
                            report_context=live_advice, report_format=report_format,
                        )
                    last_daily_report = now.date()

                # Check if market is open
                if not is_market_open(now, extended_hours=extended_hours):
                    logger.debug("Market closed, sleeping...")
                    if self._interruptible_wait(min(poll_interval, 60), stop_event):
                        break
                    continue

                # Periodic PDT re-check (every ~10 cycles)
                cycle_count += 1
                if self.pdt_tracker and cycle_count % 10 == 0:
                    try:
                        acct = self.client.get_account()
                        if "error" not in acct:
                            status = PDTTracker.check_account_pdt_status(acct)
                            if status["blocked"]:
                                logger.error(f"PDT BLOCKED mid-session: {status['reason']}")
                                break
                    except Exception:
                        pass

                # Execute one trading cycle
                try:
                    trades_before_cycle = len(self.trades)
                    self._run_strategy_cycle(
                        strategy=strategy,
                        symbols=symbols,
                        params=resolved,
                    )
                    if advice_enabled and stop_event and hasattr(stop_event, "publish_advice"):
                        trade_advice = self._trade_advice(
                            self.trades[trades_before_cycle:], params
                        )
                        if trade_advice:
                            stop_event.publish_advice(trade_advice)
                    if (advice_enabled and stop_event and
                            hasattr(stop_event, "publish_advice") and
                            time.monotonic() - last_advice_at >= advice_interval):
                        stop_event.publish_advice(
                            self._build_hermes_advice(symbols, params)
                        )
                        if hasattr(stop_event, "evaluate_drift_guard"):
                            stop_event.evaluate_drift_guard()
                        last_advice_at = time.monotonic()
                except Exception as e:
                    logger.error(f"Trading cycle error: {e}")
                    if self.message_bus:
                        self.message_bus.publish(
                            from_agent="paper_trader",
                            to_agent="portfolio_manager",
                            msg_type="error",
                            payload={"error": str(e), "session_id": self.session_id},
                        )

                if self._interruptible_wait(poll_interval, stop_event):
                    break

        except KeyboardInterrupt:
            logger.info("Paper trading interrupted by user")

        # Final summary
        return self._generate_summary(start_time)

    @staticmethod
    def _interruptible_wait(seconds: float, stop_event=None) -> bool:
        """Sleep responsively so durable pause/stop requests take effect quickly."""
        deadline = time.monotonic() + max(0, seconds)
        while time.monotonic() < deadline:
            if stop_event and hasattr(stop_event, "wait_if_paused"):
                if not stop_event.wait_if_paused():
                    return True
            if stop_event and stop_event.is_set():
                return True
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        return False

    def _execute_cycle(self, symbols, dip_threshold, take_profit, stop_loss,
                       hold_days, capital_per_trade, min_hold_days=0):
        """Execute one buy-the-dip trading cycle: check exits then entries."""
        # 1. Process exits
        self._process_exits(take_profit, stop_loss, hold_days, min_hold_days)

        # 2. Process entries
        self._process_entries(symbols, dip_threshold, capital_per_trade)

    def _run_strategy_cycle(self, strategy: str, symbols, params: Dict):
        """Dispatch one trading cycle for the session's strategy.

        buy_the_dip keeps its original code path untouched; the other
        strategies route through their dedicated cycles below.
        """
        if strategy == "buy_the_dip":
            self._execute_cycle(
                symbols=symbols,
                dip_threshold=params.get("dip_threshold", 5.0),
                take_profit=params.get("take_profit_threshold", 1.0),
                stop_loss=params.get("stop_loss_threshold", 0.5),
                hold_days=params.get("hold_days", 2),
                min_hold_days=params.get("min_hold_days", 0),
                capital_per_trade=params.get("capital_per_trade", 1000.0),
            )
        elif strategy == "momentum":
            self._momentum_cycle(symbols, params)
        elif strategy == "vix":
            self._vix_cycle(symbols, params)
        elif strategy == "box_wedge":
            self._box_wedge_cycle(symbols, params)
        else:
            logger.error(f"Unknown paper strategy {strategy!r} — no cycle executed")

    # ------------------------------------------------------------------
    # Momentum strategy cycle
    # ------------------------------------------------------------------

    def _momentum_cycle(self, symbols, params: Dict):
        """One momentum cycle: generic TP/SL/hold exits + momentum entries."""
        self._process_exits(
            params.get("take_profit_threshold", 10.0),
            params.get("stop_loss_threshold", 5.0),
            params.get("hold_days", 5),
        )
        self._process_momentum_entries(
            symbols,
            lookback_period=int(params.get("lookback_period") or 20),
            momentum_threshold=float(params.get("momentum_threshold") or 5.0),
            capital_per_trade=float(params.get("capital_per_trade") or 1000.0),
        )

    def _process_momentum_entries(self, symbols, lookback_period, momentum_threshold,
                                  capital_per_trade):
        """Check for momentum entry signals (same shell as dip entries)."""
        if self.pdt_tracker and not self.pdt_tracker.can_day_trade(datetime.now(timezone.utc)):
            logger.info("PDT: at day-trade limit, skipping new entries (could not exit same-day)")
            return

        try:
            positions = self.client.get_positions()
            existing = set()
            if isinstance(positions, list):
                existing = {p.get("symbol") for p in positions}

            # Also skip symbols with pending buy orders
            try:
                open_orders = self.client.get_orders(status='open')
                if isinstance(open_orders, list):
                    for o in open_orders:
                        if str(o.get("side", "")).lower() == "buy":
                            existing.add(o.get("symbol"))
            except Exception:
                pass

            account = self.client.get_account()
            if "error" in account:
                return
            buying_power = float(account.get("buying_power", 0))
            max_position = buying_power * 0.05

            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_period * 3 + 40)
            for symbol in symbols:
                if symbol in existing:
                    continue
                if self._entered_today.get(symbol) == end_date.date().isoformat():
                    continue  # already entered (and maybe stopped out) today

                try:
                    hist = get_historical_data(symbol, start_date=start_date, end_date=end_date)
                    if hist is None or hist.empty:
                        continue

                    signal, momentum_pct, reason = momentum_entry_signal(
                        hist, lookback_period, momentum_threshold
                    )
                    if not signal:
                        continue

                    # Get current price from intraday if possible
                    current_price = None
                    today_data = get_intraday_prices(symbol, date=end_date, interval="1")
                    if not today_data.empty:
                        val = today_data["Close"].iloc[-1]
                        current_price = float(val.item()) if hasattr(val, "item") else float(val)
                    if current_price is None:
                        val = hist["Close"].iloc[-1]
                        current_price = float(val.iloc[0]) if hasattr(val, "iloc") else float(val)

                    position_value = min(capital_per_trade, max_position)
                    if position_value > buying_power:
                        continue

                    qty = int(position_value / current_price)
                    if qty == 0:
                        continue

                    pos_check = self.client.get_position(symbol)
                    if pos_check and isinstance(pos_check, dict) and "error" not in pos_check:
                        continue

                    result = self.client.create_order(
                        symbol=symbol, qty=qty, side="buy",
                        type="market", time_in_force="day",
                    )

                    if "error" not in result:
                        logger.info(f"BUY {qty} {symbol} @ ~${current_price:.2f} (momentum: {reason})")
                        entry_time = datetime.now(timezone.utc).isoformat()
                        self._tracked_positions[symbol] = {
                            "entry_time": entry_time,
                            "entry_price": current_price,
                            "qty": qty,
                        }
                        self._entered_today[symbol] = entry_time[:10]
                        trade = {
                            "symbol": symbol,
                            "side": "buy",
                            "qty": qty,
                            "price": current_price,
                            "entry_time": entry_time,
                            "momentum_pct": round(momentum_pct, 2) if momentum_pct is not None else None,
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
                    logger.error(f"Momentum entry error for {symbol}: {e}")

        except Exception as e:
            logger.error(f"Momentum entry cycle error: {e}")

    # ------------------------------------------------------------------
    # VIX fear-index strategy cycle
    # ------------------------------------------------------------------

    def _vix_cycle(self, symbols, params: Dict):
        """One VIX-fear cycle: time-based exits + once-a-day threshold entries.

        VIX positions are time-driven, never TP/SL — they are deliberately
        kept out of the generic _process_exits machinery.
        """
        self._process_vix_exits(hold_overnight=bool(params.get("hold_overnight", True)))
        self._process_vix_entries(
            symbols,
            vix_threshold=float(params.get("vix_threshold") or 20.0),
            capital_per_trade=float(params.get("capital_per_trade") or 1000.0),
            position_size=params.get("position_size"),
        )

    def _process_vix_exits(self, hold_overnight: bool = True):
        """Time-based VIX exits: next session after entry, or same-day near the close."""
        try:
            positions = self.client.get_positions()
            if isinstance(positions, dict) and "error" in positions:
                logger.error(f"Error getting positions: {positions['error']}")
                return

            now_utc = datetime.now(timezone.utc)
            et_now = now_utc.astimezone(_ET)
            for pos in positions:
                symbol = pos.get("symbol")
                qty = float(pos.get("qty", 0))
                qty_available = float(pos.get("qty_available", qty))
                entry_price = float(pos.get("avg_entry_price", 0))
                current_price = float(pos.get("current_price", 0))
                if abs(qty_available) <= 0 or entry_price <= 0:
                    continue

                tracked = self._tracked_positions.get(symbol, {})
                entry_time_str = tracked.get("entry_time")
                known_entry = False
                is_same_day = False
                if entry_time_str:
                    try:
                        entry_date = datetime.fromisoformat(entry_time_str).date()
                        known_entry = True
                        is_same_day = entry_date == now_utc.date()
                    except ValueError:
                        pass

                exit_reason = None
                if not hold_overnight:
                    # Same-day mode: flatten near the close.
                    if et_now.hour > 15 or (et_now.hour == 15 and et_now.minute >= 45):
                        exit_reason = f"EOD_FLAT (hold_overnight=false, {et_now:%H:%M} ET)"
                elif known_entry and not is_same_day:
                    # Overnight mode: held through a session boundary → sell now.
                    # An unknown entry date is treated conservatively as same-day.
                    exit_reason = "OVERNIGHT_HOLD (next-session exit)"

                if not exit_reason:
                    continue

                if self.pdt_tracker and is_same_day:
                    if not self.pdt_tracker.can_day_trade(now_utc):
                        logger.debug(f"PDT protection: cannot sell {symbol} same day")
                        continue
                    if self._is_pdt_blocked():
                        logger.warning(f"PDT blocked: cannot exit {symbol} (same-day)")
                        continue

                logger.info(f"EXIT {symbol}: {exit_reason}")
                close_qty = (int(abs(qty_available))
                             if abs(qty_available) < abs(qty) else None)
                result = self.client.close_position(symbol, qty=close_qty)
                if "error" not in result:
                    pnl = (current_price - entry_price) * qty_available
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    trade = {
                        "symbol": symbol,
                        "side": "sell",
                        "qty": abs(qty_available),
                        "entry_price": entry_price,
                        "exit_price": current_price,
                        "entry_time": entry_time_str,
                        "exit_time": now_utc.isoformat(),
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "reason": exit_reason,
                        "timestamp": now_utc.isoformat(),
                    }
                    self.trades.append(trade)
                    self._tracked_positions.pop(symbol, None)
                    self._store_trade(trade)
                    self._publish_trade_update(trade)

                    if self.pdt_tracker and is_same_day:
                        self.pdt_tracker.record_day_trade(now_utc, symbol)
                else:
                    logger.error(f"Failed to exit {symbol}: {result['error']}")

        except Exception as e:
            logger.error(f"VIX exit processing error: {e}")

    def _process_vix_entries(self, symbols, vix_threshold, capital_per_trade,
                             position_size=None):
        """VIX fear entries, evaluated once per ET day on the first poll after 09:35."""
        now_utc = datetime.now(timezone.utc)
        et_now = now_utc.astimezone(_ET)
        if et_now.hour < 9 or (et_now.hour == 9 and et_now.minute < 35):
            return
        today = et_now.date().isoformat()
        if self._vix_entry_day == today:
            return

        try:
            vix_close, reason = fetch_vix_close()
            if vix_close is None:
                # Rate-limited warning: a dead feed must not spam the logs all day.
                if time.monotonic() - self._last_vix_warn >= 3600:
                    self._last_vix_warn = time.monotonic()
                    logger.warning(f"VIX fetch failed ({reason}) — skipping VIX entries this poll")
                return

            signal, sig_reason = vix_entry_signal(vix_close, vix_threshold)
            if not signal:
                logger.info(f"VIX entry check: {sig_reason}")
                self._vix_entry_day = today
                return

            # One entry evaluation per ET day, regardless of what gets bought
            self._vix_entry_day = today

            if self.pdt_tracker and not self.pdt_tracker.can_day_trade(now_utc):
                logger.info("PDT: at day-trade limit, skipping VIX entries")
                return

            positions = self.client.get_positions()
            existing = set()
            if isinstance(positions, list):
                existing = {p.get("symbol") for p in positions}

            account = self.client.get_account()
            if "error" in account:
                return
            buying_power = float(account.get("buying_power", 0))
            max_position = buying_power * 0.05
            equity = float(account.get("equity") or account.get("portfolio_value") or 0)

            # Sizing mirrors the backtest: a fraction of equity when
            # position_size is set, else capital_per_trade.
            if position_size:
                position_value = equity * float(position_size)
            else:
                position_value = capital_per_trade
            position_value = min(position_value, max_position)

            for symbol in symbols:
                if symbol in existing:
                    continue
                if self._entered_today.get(symbol) == now_utc.date().isoformat():
                    continue  # already entered (and maybe stopped out) today
                try:
                    current_price = None
                    today_data = get_intraday_prices(symbol, date=datetime.now(), interval="1")
                    if not today_data.empty:
                        val = today_data["Close"].iloc[-1]
                        current_price = float(val.item()) if hasattr(val, "item") else float(val)
                    if current_price is None:
                        continue

                    if position_value > buying_power:
                        continue
                    qty = int(position_value / current_price)
                    if qty == 0:
                        continue

                    pos_check = self.client.get_position(symbol)
                    if pos_check and isinstance(pos_check, dict) and "error" not in pos_check:
                        continue

                    result = self.client.create_order(
                        symbol=symbol, qty=qty, side="buy",
                        type="market", time_in_force="day",
                    )
                    if "error" not in result:
                        logger.info(f"BUY {qty} {symbol} @ ~${current_price:.2f} ({sig_reason})")
                        entry_time = now_utc.isoformat()
                        self._tracked_positions[symbol] = {
                            "entry_time": entry_time,
                            "entry_price": current_price,
                            "qty": qty,
                        }
                        self._entered_today[symbol] = now_utc.date().isoformat()
                        trade = {
                            "symbol": symbol,
                            "side": "buy",
                            "qty": qty,
                            "price": current_price,
                            "entry_time": entry_time,
                            "vix_level": vix_close,
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
                    time.sleep(0.5)
                except Exception as e:
                    logger.error(f"VIX entry error for {symbol}: {e}")

        except Exception as e:
            logger.error(f"VIX entry cycle error: {e}")

    # ------------------------------------------------------------------
    # Box & wedge strategy cycle
    # ------------------------------------------------------------------

    def _box_wedge_cycle(self, symbols, params: Dict):
        """One box & wedge cycle: R-multiple scale-outs + wedge-breakout entries.

        Exits are per-position (stop at wedge low, 50% off at 1.5R → stop to
        breakeven, 25% at 3R, runner) and never routed through the generic
        TP/SL machinery.
        """
        self._process_box_wedge_exits()
        self._process_box_wedge_entries(
            symbols,
            risk_pct=float(params.get("risk_per_trade_pct") or 1.0) / 100.0,
            contraction_threshold=float(params.get("contraction_threshold") or 0.7),
            box_lookback=int(params.get("box_lookback") or 100),
            wedge_lookback=int(params.get("wedge_lookback") or 20),
            max_capital_per_trade=float(params.get("capital_per_trade") or 1000.0),
        )

    def _process_box_wedge_exits(self):
        """Scale-out exits for box & wedge positions.

        Geometry (stop at wedge low, 1.5R/3R targets) lives in
        _tracked_positions; positions without it (synced at startup or after a
        restart) fall back to the live wedge low. The runner leg holds until
        its stop is hit. Regular-hours exits only — the 5m frame behind the
        stops is a regular-session feed.
        """
        try:
            positions = self.client.get_positions()
            if isinstance(positions, dict) and "error" in positions:
                logger.error(f"Error getting positions: {positions['error']}")
                return

            now_utc = datetime.now(timezone.utc)
            et_now = now_utc.astimezone(_ET)
            if et_now.hour < 9 or et_now.hour >= 16:
                return

            for pos in positions:
                symbol = pos.get("symbol")
                qty = float(pos.get("qty", 0))
                qty_available = float(pos.get("qty_available", qty))
                entry_price = float(pos.get("avg_entry_price", 0))
                if qty_available <= 0 or entry_price <= 0:
                    continue

                tracked = self._tracked_positions.get(symbol, {})
                entry_time_str = tracked.get("entry_time")
                is_same_day = False
                if entry_time_str:
                    try:
                        is_same_day = (
                            datetime.fromisoformat(entry_time_str).date() == now_utc.date()
                        )
                    except ValueError:
                        pass

                # Live bar range for stop/target checks (one session of 5m bars)
                try:
                    intraday = get_intraday_data(symbol, interval="5m", period="5d")
                except Exception:
                    intraday = None
                if intraday is None or getattr(intraday, "empty", True):
                    continue
                recent = intraday.tail(78)
                bar_high = float(recent["High"].max())
                bar_low = float(recent["Low"].min())

                stop_price = tracked.get("stop_price")
                target_1_5r = tracked.get("target_1_5r")
                target_3r = tracked.get("target_3r")
                if stop_price is None:
                    # Rebuild geometry from the live wedge low.
                    _, _, levels = box_wedge_entry_signal(intraday)
                    stop_price = levels.get("wedge_low")
                    if not stop_price or stop_price <= 0:
                        continue  # no reliable geometry — never manage blind
                    target_1_5r, target_3r = box_wedge_stop_target(entry_price, stop_price)
                    tracked.update({
                        "stop_price": stop_price,
                        "target_1_5r": target_1_5r,
                        "target_3r": target_3r,
                        "scaled_1_5r": False,
                        "scaled_3r": False,
                    })
                    self._tracked_positions[symbol] = tracked

                r_value = entry_price - stop_price
                if r_value <= 0:
                    continue

                exit_reason = None
                close_qty = None  # None = full remaining position
                if bar_low <= stop_price:
                    exit_reason = f"STOP_LOSS (wedge low ${stop_price:.2f})"
                elif not tracked.get("scaled_1_5r") and target_1_5r and bar_high >= target_1_5r:
                    exit_reason = f"SCALE_OUT_1.5R (${target_1_5r:.2f})"
                    close_qty = max(1, int(float(tracked.get("qty", qty_available)) * 0.50))
                elif not tracked.get("scaled_3r") and target_3r and bar_high >= target_3r:
                    exit_reason = f"SCALE_OUT_3R (${target_3r:.2f})"
                    close_qty = max(1, int(float(tracked.get("qty", qty_available)) * 0.25))

                if not exit_reason:
                    # Stop ratchets to breakeven once the 1.5R scale-out fired.
                    if tracked.get("scaled_1_5r") and stop_price < entry_price:
                        tracked["stop_price"] = entry_price
                        logger.info(
                            f"Box-wedge stop for {symbol} moved to breakeven (${entry_price:.2f})"
                        )
                    continue

                if close_qty is not None:
                    close_qty = min(close_qty, int(abs(qty_available)))
                else:
                    close_qty = (int(abs(qty_available))
                                 if abs(qty_available) < abs(qty) else None)

                if self.pdt_tracker and is_same_day:
                    if not self.pdt_tracker.can_day_trade(now_utc):
                        logger.debug(f"PDT protection: cannot sell {symbol} same day")
                        continue
                    if self._is_pdt_blocked():
                        logger.warning(f"PDT blocked: cannot exit {symbol} (same-day)")
                        continue

                logger.info(f"EXIT {symbol}: {exit_reason}")
                result = self.client.close_position(symbol, qty=close_qty)
                if "error" not in result:
                    current_price = float(pos.get("current_price", entry_price))
                    shares_closed = close_qty if close_qty is not None else abs(qty_available)
                    pnl = (current_price - entry_price) * shares_closed
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    trade = {
                        "symbol": symbol,
                        "side": "sell",
                        "qty": shares_closed,
                        "entry_price": entry_price,
                        "exit_price": current_price,
                        "entry_time": entry_time_str,
                        "exit_time": now_utc.isoformat(),
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "reason": exit_reason,
                        "timestamp": now_utc.isoformat(),
                    }
                    self.trades.append(trade)
                    self._store_trade(trade)
                    self._publish_trade_update(trade)

                    partial = close_qty is not None and close_qty < int(abs(qty_available))
                    if partial:
                        if exit_reason.startswith("SCALE_OUT_1.5R"):
                            tracked["scaled_1_5r"] = True
                            tracked["stop_price"] = max(stop_price, entry_price)
                        elif exit_reason.startswith("SCALE_OUT_3R"):
                            tracked["scaled_3r"] = True
                        tracked["qty"] = max(1, float(tracked.get("qty", qty)) - (close_qty or 0))
                    else:
                        self._tracked_positions.pop(symbol, None)

                    if self.pdt_tracker and is_same_day:
                        self.pdt_tracker.record_day_trade(now_utc, symbol)
                else:
                    logger.error(f"Failed to exit {symbol}: {result['error']}")

        except Exception as e:
            logger.error(f"Box-wedge exit processing error: {e}")

    def _process_box_wedge_entries(self, symbols, risk_pct, contraction_threshold,
                                   box_lookback, wedge_lookback, max_capital_per_trade):
        """Wedge-breakout entries — regular hours only, risk-based sizing."""
        now_utc = datetime.now(timezone.utc)
        et_now = now_utc.astimezone(_ET)
        if et_now.hour < 9 or et_now.hour >= 16:
            return
        if self.pdt_tracker and not self.pdt_tracker.can_day_trade(now_utc):
            logger.info("PDT: at day-trade limit, skipping box-wedge entries")
            return

        try:
            positions = self.client.get_positions()
            existing = set()
            if isinstance(positions, list):
                existing = {p.get("symbol") for p in positions}

            try:
                open_orders = self.client.get_orders(status='open')
                if isinstance(open_orders, list):
                    for o in open_orders:
                        if str(o.get("side", "")).lower() == "buy":
                            existing.add(o.get("symbol"))
            except Exception:
                pass

            account = self.client.get_account()
            if "error" in account:
                return
            buying_power = float(account.get("buying_power", 0))
            max_position = buying_power * 0.05
            equity = float(account.get("equity") or account.get("portfolio_value") or 0)

            for symbol in symbols:
                if symbol in existing:
                    continue
                if self._entered_today.get(symbol) == now_utc.date().isoformat():
                    continue  # already entered (and maybe stopped out) today
                try:
                    intraday = get_intraday_data(symbol, interval="5m", period="30d")
                    if intraday is None or getattr(intraday, "empty", True):
                        logger.debug(f"Box-wedge: no intraday data for {symbol} — skipping")
                        continue

                    signal, reason, levels = box_wedge_entry_signal(
                        intraday,
                        box_lookback=box_lookback,
                        wedge_lookback=wedge_lookback,
                        contraction_threshold=contraction_threshold,
                    )
                    if not signal:
                        continue

                    # Entry price: latest 5m close
                    val = intraday["Close"].iloc[-1]
                    current_price = float(val.iloc[0]) if hasattr(val, "iloc") else float(val)

                    stop_price = levels.get("wedge_low", 0.0)
                    if current_price <= 0 or stop_price <= 0 or stop_price >= current_price:
                        continue

                    shares = calculate_position_size(
                        equity, risk_pct, current_price, stop_price
                    )
                    # Cap risk-sized shares by the per-trade capital budget
                    max_shares = int(max(min(max_capital_per_trade, max_position),
                                         0) / current_price)
                    qty = min(shares, max_shares)
                    if qty <= 0:
                        continue

                    pos_check = self.client.get_position(symbol)
                    if pos_check and isinstance(pos_check, dict) and "error" not in pos_check:
                        continue

                    result = self.client.create_order(
                        symbol=symbol, qty=qty, side="buy",
                        type="market", time_in_force="day",
                    )
                    if "error" not in result:
                        target_1_5r, target_3r = box_wedge_stop_target(
                            current_price, stop_price
                        )
                        logger.info(f"BUY {qty} {symbol} @ ~${current_price:.2f} "
                                    f"(box-wedge: {reason}, stop ${stop_price:.2f})")
                        entry_time = now_utc.isoformat()
                        self._tracked_positions[symbol] = {
                            "entry_time": entry_time,
                            "entry_price": current_price,
                            "qty": qty,
                            "stop_price": stop_price,
                            "target_1_5r": target_1_5r,
                            "target_3r": target_3r,
                            "scaled_1_5r": False,
                            "scaled_3r": False,
                        }
                        self._entered_today[symbol] = entry_time[:10]
                        trade = {
                            "symbol": symbol,
                            "side": "buy",
                            "qty": qty,
                            "price": current_price,
                            "entry_time": entry_time,
                            "stop_price": stop_price,
                            "target_1_5r": target_1_5r,
                            "target_3r": target_3r,
                            "order_id": str(result.get("id", "")),
                            "timestamp": entry_time,
                        }
                        self.trades.append(trade)
                        self._store_trade(trade)
                        self._publish_trade_update(trade)
                        buying_power -= qty * current_price
                        max_position = buying_power * 0.05
                    else:
                        logger.error(f"Order failed for {symbol}: {result['error']}")
                    time.sleep(0.5)
                except Exception as e:
                    logger.error(f"Box-wedge entry error for {symbol}: {e}")

        except Exception as e:
            logger.error(f"Box-wedge entry cycle error: {e}")

    def _build_hermes_advice(self, symbols: List[str], params: Dict) -> List[Dict]:
        """Build paper-only observations; delivery and ownership stay in Hermes control."""
        from engine.agents.hermes_advice import position_advice
        try:
            positions = self.client.get_positions()
            if not isinstance(positions, list):
                positions = []
        except Exception as exc:
            logger.warning("Could not gather positions for Hermes advice: %s", exc)
            positions = []
        return position_advice(positions, symbols, params)

    @staticmethod
    def _trade_advice(trades: List[Dict], params: Optional[Dict] = None) -> List[Dict]:
        """Describe strategy-confirmed paper entries/exits without creating orders."""
        items = []
        params = params or {}
        for trade in trades:
            symbol = str(trade.get("symbol") or "").upper()
            side = str(trade.get("side") or "").lower()
            is_entry = side == "buy" and "exit_price" not in trade
            action = "ENTRY_EXECUTED" if is_entry else "EXIT_EXECUTED"
            reason = (f"Approved dip signal confirmed at {float(trade.get('dip_pct', 0)):.2f}%."
                      if is_entry else str(trade.get("reason") or "Approved exit rule triggered."))
            items.append({
                "symbol": symbol,
                "advice_type": "entry" if is_entry else "exit",
                "action": action, "severity": "action",
                "summary": f"{symbol}: {action}", "rationale": reason,
                "snapshot": {
                    **trade,
                    "dip_threshold_pct": params.get("dip_threshold"),
                    "take_profit_pct": params.get("take_profit_threshold"),
                    "stop_loss_pct": params.get("stop_loss_threshold"),
                },
            })
        return items

    def _is_pdt_blocked(self) -> bool:
        """Check if account is PDT-blocked right now."""
        if not self.pdt_tracker:
            return False
        try:
            account = self.client.get_account()
            if "error" in account:
                logger.warning("Cannot check PDT status — Alpaca error, blocking trade")
                return True
            status = PDTTracker.check_account_pdt_status(account)
            if status["blocked"]:
                logger.warning(f"PDT blocked: {status['reason']}")
                return True
        except Exception as e:
            logger.warning(f"PDT check failed: {e}, blocking trade as precaution")
            return True
        return False

    def _sync_orders_and_positions(self):
        """Sync open orders and positions from Alpaca on startup.

        Cancels stale open orders and reconciles in-memory tracked positions
        with actual Alpaca positions so exits use correct qty_available.
        """
        # 1. Cancel all open orders to clear held_for_orders locks
        try:
            open_orders = self.client.get_orders(status='open')
            if isinstance(open_orders, list) and open_orders:
                logger.info(f"Found {len(open_orders)} open orders on startup — cancelling stale orders")
                for order in open_orders:
                    oid = order.get("id") or str(order.get("id", ""))
                    symbol = order.get("symbol", "?")
                    side = order.get("side", "?")
                    logger.info(f"Cancelling stale {side} order for {symbol} (order {str(oid)[:8]})")
                    self.client.cancel_order(str(oid))
                logger.info("All stale open orders cancelled")
            else:
                logger.info("No open orders found on startup")
        except Exception as e:
            logger.warning(f"Could not sync open orders: {e}")

        # 2. Reconcile positions — populate _tracked_positions from Alpaca
        try:
            positions = self.client.get_positions()
            if isinstance(positions, list) and positions:
                # Query recent filled buy orders to determine actual entry dates
                entry_times = self._lookup_entry_times(
                    [p.get("symbol") for p in positions if p.get("symbol")]
                )

                for pos in positions:
                    symbol = pos.get("symbol")
                    if symbol and symbol not in self._tracked_positions:
                        entry_time = entry_times.get(symbol)
                        if entry_time:
                            try:
                                self._entered_today[symbol] = (
                                    datetime.fromisoformat(entry_time).date().isoformat()
                                )
                            except ValueError:
                                pass
                        self._tracked_positions[symbol] = {
                            "entry_time": entry_time,
                            "entry_price": float(pos.get("avg_entry_price", 0)),
                            "qty": float(pos.get("qty", 0)),
                        }
                        et_label = entry_time[:19] if entry_time else "unknown"
                        logger.info(
                            f"Synced existing position: {symbol} "
                            f"qty={pos.get('qty')} @ ${float(pos.get('avg_entry_price', 0)):.2f} "
                            f"(entered: {et_label})"
                        )
                logger.info(f"Position sync complete: {len(self._tracked_positions)} positions tracked")
        except Exception as e:
            logger.warning(f"Could not sync positions: {e}")

    def _lookup_entry_times(self, symbols: List[str]) -> Dict[str, str]:
        """Query Alpaca filled buy orders to find actual entry times for positions.

        Returns dict of symbol -> ISO datetime string for the most recent
        filled buy order per symbol.
        """
        entry_times: Dict[str, str] = {}
        try:
            # Query filled orders from last 90 days (covers most positions)
            after = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
            orders = self.client.get_orders(status='closed', after=after, limit=500)
            if not isinstance(orders, list):
                return entry_times

            # Find most recent filled buy order per symbol
            for order in orders:
                sym = order.get("symbol")
                if sym not in symbols:
                    continue
                if str(order.get("side", "")).lower() != "buy":
                    continue
                if str(order.get("status", "")).lower() != "filled":
                    continue
                filled_at = order.get("filled_at")
                if filled_at and sym not in entry_times:
                    # Orders are returned newest-first, so first match is most recent
                    if hasattr(filled_at, 'isoformat'):
                        entry_times[sym] = filled_at.isoformat()
                    else:
                        entry_times[sym] = str(filled_at)

        except Exception as e:
            logger.warning(f"Could not look up entry times from Alpaca orders: {e}")

        # Fallback: check DB trades for any missing symbols
        missing = [s for s in symbols if s not in entry_times]
        if missing:
            try:
                from utils.db.db_pool import DatabasePool
                from sqlalchemy import text
                pool = DatabasePool()
                placeholders = ", ".join(f":s{i}" for i in range(len(missing)))
                bind = {f"s{i}": s for i, s in enumerate(missing)}
                with pool.get_session() as session:
                    rows = session.execute(
                        text(f"""
                            SELECT DISTINCT ON (symbol) symbol, created_at
                            FROM alpatrade.trades
                            WHERE symbol IN ({placeholders})
                              AND direction = 'buy' AND trade_type = 'paper'
                            ORDER BY symbol, created_at DESC
                        """),
                        bind,
                    ).fetchall()
                    for row in rows:
                        sym, created = row
                        if sym not in entry_times and created:
                            entry_times[sym] = created.isoformat() if hasattr(created, 'isoformat') else str(created)
            except Exception as e:
                logger.debug(f"DB fallback for entry times failed: {e}")

        return entry_times

    def _process_exits(self, take_profit, stop_loss, hold_days, min_hold_days=0):
        """Check existing positions for exit signals."""
        try:
            positions = self.client.get_positions()
            if isinstance(positions, dict) and "error" in positions:
                logger.error(f"Error getting positions: {positions['error']}")
                return

            # Get open sell orders to skip symbols with pending exits
            pending_sell_symbols = set()
            try:
                open_orders = self.client.get_orders(status='open')
                if isinstance(open_orders, list):
                    for o in open_orders:
                        if str(o.get("side", "")).lower() == "sell":
                            pending_sell_symbols.add(o.get("symbol"))
            except Exception:
                pass

            for pos in positions:
                symbol = pos.get("symbol")
                qty = float(pos.get("qty", 0))
                qty_available = float(pos.get("qty_available", qty))
                entry_price = float(pos.get("avg_entry_price", 0))
                current_price = float(pos.get("current_price", 0))

                if entry_price <= 0:
                    continue

                # Skip if there's already a pending sell order for this symbol
                if symbol in pending_sell_symbols:
                    logger.debug(f"Skipping {symbol}: pending sell order exists")
                    continue

                # Skip if no shares available to trade. Use magnitude: a short position
                # reports a negative qty_available, and comparing it against 0 silently
                # skipped every short, so shorts were never considered for exit at all.
                if abs(qty_available) <= 0:
                    logger.debug(f"Skipping {symbol}: no qty available (held for orders)")
                    continue

                # Prefer the broker's own P&L percentage: it is signed correctly for both
                # directions. Deriving it from prices alone inverts the sign on a short,
                # which reported a winning short as a loser and would stop it out at the
                # moment it was most profitable.
                plpc = pos.get("unrealized_plpc")
                if plpc not in (None, ""):
                    unrealized_pct = float(plpc) * 100
                else:
                    unrealized_pct = ((current_price - entry_price) / entry_price) * 100
                    if qty < 0:
                        unrealized_pct = -unrealized_pct

                # Check hold period from tracked positions
                tracked = self._tracked_positions.get(symbol, {})
                entry_time_str = tracked.get("entry_time")
                if entry_time_str:
                    entry_dt = datetime.fromisoformat(entry_time_str)
                    days_held = (datetime.now(timezone.utc) - entry_dt).days
                else:
                    days_held = 99

                # PDT protection — determine if selling would be a day trade
                is_same_day = False
                if entry_time_str:
                    entry_dt = datetime.fromisoformat(entry_time_str)
                    is_same_day = entry_dt.date() == datetime.now(timezone.utc).date()

                if self.pdt_tracker and is_same_day:
                    if not self.pdt_tracker.can_day_trade(datetime.now(timezone.utc)):
                        logger.debug(f"PDT protection: cannot sell {symbol} same day (3 day trades in 5-day window)")
                        continue

                exit_reason = None
                # Minimum hold (PDT-safe swing): no TP/SL exit until min_hold_days elapsed.
                if days_held >= min_hold_days:
                    if unrealized_pct >= take_profit:
                        exit_reason = f"TAKE_PROFIT ({unrealized_pct:.2f}%)"
                    elif unrealized_pct <= -stop_loss:
                        exit_reason = f"STOP_LOSS ({unrealized_pct:.2f}%)"
                # Time-based exit is opt-in: hold_days of 0/None means hold until the
                # position resolves on take-profit or stop-loss, with no expiry.
                if exit_reason is None and hold_days and days_held >= hold_days:
                    exit_reason = f"HOLD_EXPIRED ({days_held}d)"

                if exit_reason:
                    # Account-level PDT check — only relevant for same-day exits
                    if is_same_day and self._is_pdt_blocked():
                        logger.warning(f"PDT blocked: cannot exit {symbol} (same-day, would be day trade)")
                        continue

                    logger.info(f"EXIT {symbol}: {exit_reason}")
                    # Close only available qty to avoid held_for_orders errors. Compare
                    # magnitudes so a partially-held short isn't mistaken for a full one,
                    # and always pass a positive quantity to the broker.
                    close_qty = (int(abs(qty_available))
                                 if abs(qty_available) < abs(qty) else None)
                    result = self.client.close_position(symbol, qty=close_qty)
                    if "error" not in result:
                        # qty_available is negative for a short, which correctly flips the
                        # sign: a short closed below entry is a gain.
                        pnl = (current_price - entry_price) * qty_available
                        trade = {
                            "symbol": symbol,
                            # Closing a short is a buy, not a sell.
                            "side": "buy" if qty < 0 else "sell",
                            "qty": abs(qty_available),
                            "entry_price": entry_price,
                            "exit_price": current_price,
                            "entry_time": entry_time_str,
                            "exit_time": datetime.now(timezone.utc).isoformat(),
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
        # PDT guard: skip new entries if we can't exit same-day
        if self.pdt_tracker and not self.pdt_tracker.can_day_trade(datetime.now(timezone.utc)):
            logger.info("PDT: at day-trade limit, skipping new entries (could not exit same-day)")
            return

        try:
            # Get existing positions and pending buy orders to skip
            positions = self.client.get_positions()
            existing = set()
            if isinstance(positions, list):
                existing = {p.get("symbol") for p in positions}

            # Also skip symbols with pending buy orders
            try:
                open_orders = self.client.get_orders(status='open')
                if isinstance(open_orders, list):
                    for o in open_orders:
                        if str(o.get("side", "")).lower() == "buy":
                            existing.add(o.get("symbol"))
            except Exception:
                pass

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
                            "entry_time": entry_time,
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
            store_paper_trade(self.session_id, trade, user_id=self.user_id,
                              account_id=self.account_id)
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

    def _send_daily_email(self, date: str, to_email: str = "",
                          advice: Optional[List[Dict]] = None,
                          report_context: Optional[Dict] = None,
                          report_format: str = "default"):
        """Leave daily summaries to the single account-owned report scheduler.

        Historically each paper worker could send a separate daily message,
        producing duplicate and inconsistent emails. The consolidated scheduler
        now owns daily reporting for Hermes, DeepAgents, LangGraph, and legacy
        runs. Hermes entry/exit advice remains an independent opt-in channel.
        """
        logger.info(
            "Worker daily summary suppressed for %s (%s); account digest owns delivery",
            date, report_format,
        )

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
