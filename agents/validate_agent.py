"""
Validation Agent

Cross-checks backtest and paper trading results against real market data
from the Massive API. Validates price accuracy, P&L math, market hours,
and strategy logic. Self-corrects up to n=10 iterations before escalating.
"""

import sys
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

import numpy as np
import pytz

# Ensure project root is importable
project_root = Path(__file__).parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from utils.massive_util import MassiveUtil
from utils.agent_storage import fetch_backtest_trades, fetch_paper_trades

logger = logging.getLogger(__name__)

EASTERN = pytz.timezone("US/Eastern")


class ValidationResult:
    """Result of a validation run."""

    def __init__(self, status: str, run_id: str, total_checked: int = 0,
                 anomalies: Optional[List[Dict]] = None,
                 corrections: Optional[List[Dict]] = None,
                 suggestions: Optional[List[str]] = None,
                 iterations_used: int = 0):
        self.status = status  # passed, corrected, failed
        self.run_id = run_id
        self.total_checked = total_checked
        self.anomalies = anomalies or []
        self.corrections = corrections or []
        self.suggestions = suggestions or []
        self.iterations_used = iterations_used

    def to_dict(self) -> Dict:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "total_trades_checked": self.total_checked,
            "anomalies_found": len(self.anomalies),
            "anomalies_corrected": len(self.corrections),
            "iterations_used": self.iterations_used,
            "anomalies": self.anomalies,
            "corrections": self.corrections,
            "suggestions": self.suggestions,
        }


class ValidateAgent:
    """Agent that validates trades against market data with self-correction."""

    def __init__(self, message_bus=None, state=None, max_iterations: int = 10,
                 price_tolerance: float = 0.01):
        self.message_bus = message_bus
        self.state = state
        self.max_iterations = max_iterations
        self.price_tolerance = price_tolerance
        self.massive = MassiveUtil()
        self.extended_hours = False

    def run(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate trades for a given run.

        Args:
            request: Dict with keys:
                - run_id: str
                - source: "backtest" or "paper_trade"
                - trades: list of trade dicts (optional, will fetch from DB if missing)
                - max_iterations: int (override default)
                - price_tolerance: float (override default)

        Returns:
            ValidationResult as dict
        """
        run_id = request.get("run_id", str(uuid.uuid4()))
        source = request.get("source", "backtest")
        max_iter = request.get("max_iterations", self.max_iterations)
        tolerance = request.get("price_tolerance", self.price_tolerance)
        trades = request.get("trades")
        self.extended_hours = request.get("extended_hours", False)

        logger.info(f"Validation agent starting for run {run_id} (source={source})")

        # Fetch trades from DB if not provided
        if not trades:
            trades = self._fetch_trades(run_id, source)

        if not trades:
            logger.warning(f"No trades found for run {run_id}")
            return ValidationResult(
                status="passed", run_id=run_id, total_checked=0,
            ).to_dict()

        logger.info(f"Validating {len(trades)} trades (max {max_iter} iterations)")

        all_corrections = []

        for iteration in range(max_iter):
            logger.info(f"  Iteration {iteration + 1}/{max_iter}")

            # Run all validation checks
            anomalies = self._run_checks(trades, tolerance)

            if not anomalies:
                logger.info(f"  All checks passed on iteration {iteration + 1}")
                result = ValidationResult(
                    status="corrected" if all_corrections else "passed",
                    run_id=run_id,
                    total_checked=len(trades),
                    corrections=all_corrections,
                    iterations_used=iteration + 1,
                )
                self._publish_result(result)
                return result.to_dict()

            logger.info(f"  Found {len(anomalies)} anomalies, attempting corrections")

            # Attempt corrections
            corrections = self._attempt_corrections(trades, anomalies)
            all_corrections.extend(corrections)

            # Apply corrections to trades
            trades = self._apply_corrections(trades, corrections)

        # Failed after max iterations
        remaining = self._run_checks(trades, tolerance)
        suggestions = self._generate_suggestions(remaining)

        result = ValidationResult(
            status="failed",
            run_id=run_id,
            total_checked=len(trades),
            anomalies=remaining,
            corrections=all_corrections,
            suggestions=suggestions,
            iterations_used=max_iter,
        )

        logger.warning(
            f"Validation FAILED for run {run_id} after {max_iter} iterations. "
            f"{len(remaining)} unresolved anomalies."
        )

        self._publish_result(result)
        return result.to_dict()

    def _fetch_trades(self, run_id: str, source: str) -> List[Dict]:
        """Fetch trades using the configured backend (file or DB)."""
        try:
            if source == "backtest":
                return fetch_backtest_trades(run_id)
            else:
                return fetch_paper_trades(run_id)
        except Exception as e:
            logger.error(f"Failed to fetch trades: {e}")
            return []

    def _run_checks(self, trades: List[Dict], tolerance: float) -> List[Dict]:
        """Run all validation checks on trades."""
        anomalies = []

        for idx, trade in enumerate(trades):
            trade_anomalies = []

            # 1. Price tolerance check against market data
            price_issues = self._check_price_tolerance(trade, tolerance)
            trade_anomalies.extend(price_issues)

            # 2. P&L math validation
            pnl_issues = self._check_pnl_math(trade)
            trade_anomalies.extend(pnl_issues)

            # 3. Market hours check
            hours_issues = self._check_market_hours(trade)
            trade_anomalies.extend(hours_issues)

            # 4. Weekend check
            weekend_issues = self._check_weekends(trade)
            trade_anomalies.extend(weekend_issues)

            # 5. TP/SL logic check
            tpsl_issues = self._check_tp_sl_logic(trade)
            trade_anomalies.extend(tpsl_issues)

            for issue in trade_anomalies:
                issue["trade_index"] = idx
                issue["symbol"] = trade.get("ticker") or trade.get("symbol", "")
                anomalies.append(issue)

        return anomalies

    def check_summary_metrics(self, metrics: Dict, trades: List[Dict],
                              initial_capital: float, start_date, end_date) -> List[Dict]:
        """
        Validate summary-level metrics for consistency.

        Checks:
        - annualized_return == total_return * (365.25 / days)
        - win_rate == winning_trades / total_trades * 100
        - total_return == total_pnl / initial_capital * 100
        - Sharpe ratio is not NaN/Inf
        """
        anomalies = []

        total_return = metrics.get("total_return", 0)
        total_pnl = metrics.get("total_pnl", 0)
        annualized_return = metrics.get("annualized_return", 0)
        win_rate = metrics.get("win_rate", 0)
        total_trades = metrics.get("total_trades", 0)
        winning_trades = metrics.get("winning_trades", 0)
        sharpe = metrics.get("sharpe_ratio", 0)

        # Parse dates
        sd = self._parse_datetime(start_date) if not isinstance(start_date, datetime) else start_date
        ed = self._parse_datetime(end_date) if not isinstance(end_date, datetime) else end_date
        days = (ed - sd).days

        # 1. Check total_return vs total_pnl / initial_capital
        if initial_capital > 0:
            expected_return = (total_pnl / initial_capital) * 100
            if not np.isclose(total_return, expected_return, atol=0.1):
                anomalies.append({
                    "type": "summary_total_return",
                    "expected": expected_return,
                    "actual": total_return,
                    "message": f"total_return {total_return:.2f}% != total_pnl/capital ({expected_return:.2f}%)",
                })

        # 2. Check annualized_return consistency
        if days > 0:
            expected_annual = total_return * 365.25 / days
            if abs(annualized_return) > 0.01 or abs(expected_annual) > 0.01:
                if not np.isclose(annualized_return, expected_annual, rtol=0.05):
                    anomalies.append({
                        "type": "summary_annualized_return",
                        "expected": expected_annual,
                        "actual": annualized_return,
                        "message": (
                            f"annualized_return {annualized_return:.2f}% != "
                            f"total_return*365.25/{days} ({expected_annual:.2f}%)"
                        ),
                    })

        # 3. Check win_rate
        if total_trades > 0:
            expected_wr = (winning_trades / total_trades) * 100
            if not np.isclose(win_rate, expected_wr, atol=0.1):
                anomalies.append({
                    "type": "summary_win_rate",
                    "expected": expected_wr,
                    "actual": win_rate,
                    "message": f"win_rate {win_rate:.1f}% != {winning_trades}/{total_trades} ({expected_wr:.1f}%)",
                })

        # 4. Sharpe sanity check
        if np.isnan(sharpe) or np.isinf(sharpe):
            anomalies.append({
                "type": "summary_sharpe_invalid",
                "actual": sharpe,
                "message": f"Sharpe ratio is {sharpe} (NaN/Inf)",
            })

        return anomalies

    def _check_price_tolerance(self, trade: Dict, tolerance: float) -> List[Dict]:
        """Check recorded prices against actual market data."""
        issues = []
        symbol = trade.get("ticker") or trade.get("symbol")
        if not symbol:
            return issues

        # Check entry price
        entry_time = trade.get("entry_time")
        entry_price = trade.get("entry_price")
        if entry_time and entry_price:
            actual = self._get_market_price(symbol, entry_time)
            if actual is not None:
                diff = abs(float(entry_price) - actual) / actual
                if diff > tolerance:
                    issues.append({
                        "type": "price_tolerance",
                        "field": "entry_price",
                        "recorded": float(entry_price),
                        "actual": actual,
                        "diff_pct": diff * 100,
                        "message": f"Entry price ${entry_price} differs from market ${actual:.2f} by {diff*100:.1f}%",
                    })

        # Check exit price
        exit_time = trade.get("exit_time")
        exit_price = trade.get("exit_price")
        if exit_time and exit_price:
            actual = self._get_market_price(symbol, exit_time)
            if actual is not None:
                diff = abs(float(exit_price) - actual) / actual
                if diff > tolerance:
                    issues.append({
                        "type": "price_tolerance",
                        "field": "exit_price",
                        "recorded": float(exit_price),
                        "actual": actual,
                        "diff_pct": diff * 100,
                        "message": f"Exit price ${exit_price} differs from market ${actual:.2f} by {diff*100:.1f}%",
                    })

        return issues

    def _check_pnl_math(self, trade: Dict) -> List[Dict]:
        """Verify P&L calculations."""
        issues = []
        entry = trade.get("entry_price")
        exit_p = trade.get("exit_price")
        shares = trade.get("shares", trade.get("qty"))
        recorded_pnl = trade.get("pnl")
        total_fees = trade.get("total_fees", 0)

        if all(v is not None for v in [entry, exit_p, shares, recorded_pnl]):
            expected = (float(exit_p) - float(entry)) * float(shares) - float(total_fees)
            if not np.isclose(float(recorded_pnl), expected, atol=0.01):
                issues.append({
                    "type": "pnl_math",
                    "expected_pnl": expected,
                    "recorded_pnl": float(recorded_pnl),
                    "message": f"P&L mismatch: expected ${expected:.2f}, recorded ${float(recorded_pnl):.2f}",
                })

        return issues

    def _check_market_hours(self, trade: Dict) -> List[Dict]:
        """Check that trades occurred during market hours."""
        issues = []

        for field in ["entry_time", "exit_time"]:
            time_val = trade.get(field)
            if not time_val:
                continue

            try:
                dt = self._parse_datetime(time_val)
                et = dt.astimezone(EASTERN)
                hour_float = et.hour + et.minute / 60.0

                if self.extended_hours:
                    # Extended: 4:00 AM - 8:00 PM ET
                    in_window = 4.0 <= hour_float < 20.0
                    window_label = "4AM-8PM"
                else:
                    # Regular: 9:30 AM - 4:00 PM ET
                    in_window = 9.5 <= hour_float < 16.0
                    window_label = "9:30AM-4PM"

                if not in_window:
                    issues.append({
                        "type": "market_hours",
                        "field": field,
                        "hour_et": et.hour,
                        "message": f"{field} at {et.strftime('%H:%M')} ET is outside {window_label} window",
                    })
            except Exception:
                pass

        return issues

    def _check_weekends(self, trade: Dict) -> List[Dict]:
        """Check for weekend trades."""
        issues = []

        for field in ["entry_time", "exit_time"]:
            time_val = trade.get(field)
            if not time_val:
                continue

            try:
                dt = self._parse_datetime(time_val)
                et = dt.astimezone(EASTERN)
                if et.weekday() >= 5:
                    day_name = et.strftime("%A")
                    issues.append({
                        "type": "weekend_trade",
                        "field": field,
                        "day": day_name,
                        "message": f"{field} on {day_name} (weekend)",
                    })
            except Exception:
                pass

        return issues

    def _check_tp_sl_logic(self, trade: Dict) -> List[Dict]:
        """Check take profit / stop loss logic consistency."""
        issues = []
        hit_tp = trade.get("hit_target", False)
        hit_sl = trade.get("hit_stop", False)

        if hit_tp and hit_sl:
            issues.append({
                "type": "tp_sl_conflict",
                "message": "Both take profit and stop loss marked as hit",
            })

        return issues

    def _get_market_price(self, symbol: str, timestamp) -> Optional[float]:
        """Fetch actual market price at a given timestamp."""
        try:
            dt = self._parse_datetime(timestamp)
            data = self.massive.get_intraday_prices(symbol, dt, interval="1")
            if data.empty:
                return None

            # Find closest bar to the timestamp
            if hasattr(data.index, "tz_localize"):
                try:
                    data.index = data.index.tz_localize("UTC")
                except TypeError:
                    pass

            # Get the close price of the nearest bar
            closest_idx = data.index.get_indexer([dt], method="nearest")[0]
            if 0 <= closest_idx < len(data):
                val = data["Close"].iloc[closest_idx]
                return float(val.iloc[0]) if hasattr(val, "iloc") else float(val)
            return None
        except Exception as e:
            logger.debug(f"Could not fetch market price for {symbol} at {timestamp}: {e}")
            return None

    def _attempt_corrections(self, trades: List[Dict],
                             anomalies: List[Dict]) -> List[Dict]:
        """Attempt to correct identified anomalies."""
        corrections = []

        for anomaly in anomalies:
            atype = anomaly.get("type")

            if atype == "pnl_math":
                # Recalculate P&L
                corrections.append({
                    "type": "pnl_recalculation",
                    "trade_index": anomaly["trade_index"],
                    "old_pnl": anomaly["recorded_pnl"],
                    "new_pnl": anomaly["expected_pnl"],
                })

            elif atype == "price_tolerance":
                # Use actual market price
                corrections.append({
                    "type": "price_correction",
                    "trade_index": anomaly["trade_index"],
                    "field": anomaly["field"],
                    "old_price": anomaly["recorded"],
                    "new_price": anomaly["actual"],
                })

            # Weekend and market hours issues cannot be auto-corrected
            elif atype in ("weekend_trade", "market_hours", "tp_sl_conflict"):
                corrections.append({
                    "type": "flagged",
                    "trade_index": anomaly["trade_index"],
                    "issue": atype,
                    "message": anomaly["message"],
                })

        return corrections

    def _apply_corrections(self, trades: List[Dict],
                           corrections: List[Dict]) -> List[Dict]:
        """Apply corrections to trade data."""
        trades = [dict(t) for t in trades]  # Copy

        for corr in corrections:
            idx = corr.get("trade_index")
            if idx is None or idx >= len(trades):
                continue

            if corr["type"] == "pnl_recalculation":
                trades[idx]["pnl"] = corr["new_pnl"]

            elif corr["type"] == "price_correction":
                field = corr["field"]
                trades[idx][field] = corr["new_price"]
                # Recalculate P&L if both prices are available
                entry = trades[idx].get("entry_price")
                exit_p = trades[idx].get("exit_price")
                shares = trades[idx].get("shares", trades[idx].get("qty"))
                fees = trades[idx].get("total_fees", 0)
                if all(v is not None for v in [entry, exit_p, shares]):
                    trades[idx]["pnl"] = (float(exit_p) - float(entry)) * float(shares) - float(fees)

        return trades

    def _generate_suggestions(self, anomalies: List[Dict]) -> List[str]:
        """Generate human-readable suggestions for unresolvable anomalies."""
        suggestions = []
        types = {a["type"] for a in anomalies}

        if "weekend_trade" in types:
            suggestions.append(
                "Weekend trades detected. Check the data source for incorrect timestamps "
                "or ensure the backtester skips weekends."
            )
        if "market_hours" in types:
            suggestions.append(
                "Trades outside market hours detected. Verify the data source provides "
                "correct timestamps and that the strategy respects trading hours."
            )
        if "price_tolerance" in types:
            suggestions.append(
                "Significant price deviations from market data. This may indicate "
                "stale price data or data feed issues. Consider re-running with a "
                "different data source."
            )
        if "tp_sl_conflict" in types:
            suggestions.append(
                "Take profit and stop loss both triggered on the same trade. "
                "Review the strategy exit logic for race conditions."
            )
        if "pnl_math" in types:
            suggestions.append(
                "P&L calculation mismatches remain after correction. Manually "
                "verify the fee calculations and entry/exit prices."
            )

        return suggestions

    def _publish_result(self, result: ValidationResult):
        """Send validation result to message bus."""
        if self.message_bus:
            self.message_bus.publish(
                from_agent="validator",
                to_agent="portfolio_manager",
                msg_type="validation_result",
                payload=result.to_dict(),
            )

    @staticmethod
    def _parse_datetime(value) -> datetime:
        """Parse a datetime from various formats."""
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return pytz.utc.localize(value)
            return value

        s = str(value)
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            from dateutil.parser import parse
            dt = parse(s)

        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt
