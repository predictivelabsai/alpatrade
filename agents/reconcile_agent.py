"""
Reconciliation Agent

Compares DB positions/P&L vs actual Alpaca holdings for a given time window.
Reports discrepancies in positions, trades, and P&L.
"""

import sys
import uuid
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

# Ensure project root is importable
project_root = Path(__file__).parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from utils.alpaca_util import AlpacaAPI

logger = logging.getLogger(__name__)


class ReconciliationResult:
    """Result of a reconciliation run."""

    def __init__(self, status: str, run_id: str,
                 position_mismatches: Optional[List[Dict]] = None,
                 trade_mismatches: Optional[List[Dict]] = None,
                 pnl_comparison: Optional[Dict] = None,
                 missing_trades: Optional[List[Dict]] = None,
                 extra_trades: Optional[List[Dict]] = None):
        self.status = status  # matched, mismatched, error
        self.run_id = run_id
        self.position_mismatches = position_mismatches or []
        self.trade_mismatches = trade_mismatches or []
        self.pnl_comparison = pnl_comparison or {}
        self.missing_trades = missing_trades or []
        self.extra_trades = extra_trades or []

    def to_dict(self) -> Dict:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "position_mismatches": self.position_mismatches,
            "trade_mismatches": self.trade_mismatches,
            "pnl_comparison": self.pnl_comparison,
            "missing_trades": self.missing_trades,
            "extra_trades": self.extra_trades,
            "total_issues": (
                len(self.position_mismatches) +
                len(self.trade_mismatches) +
                len(self.missing_trades) +
                len(self.extra_trades)
            ),
        }


class ReconcileAgent:
    """Agent that reconciles DB state against Alpaca actual holdings."""

    def __init__(self, message_bus=None, state=None):
        self.message_bus = message_bus
        self.state = state
        self.client: Optional[AlpacaAPI] = None

    def run(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run reconciliation for a given time window.

        Args:
            request: Dict with keys:
                - window_days: int (default 7)
                - run_id: str (optional)

        Returns:
            ReconciliationResult as dict
        """
        run_id = request.get("run_id", str(uuid.uuid4()))
        window_days = request.get("window_days", 7)

        logger.info(f"Reconciliation agent starting for run {run_id} (window={window_days}d)")

        # Initialize Alpaca client
        try:
            self.client = AlpacaAPI(paper=True)
            account = self.client.get_account()
            if "error" in account:
                raise RuntimeError(f"Alpaca API error: {account['error']}")
        except Exception as e:
            logger.error(f"Failed to initialize Alpaca client: {e}")
            return ReconciliationResult(
                status="error", run_id=run_id,
            ).to_dict()

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=window_days)

        # Run all checks
        position_mismatches = self._check_positions(run_id)
        trade_mismatches, missing, extra = self._check_trades(window_start, now)
        pnl_comparison = self._check_pnl(account)

        total_issues = (
            len(position_mismatches) + len(trade_mismatches) +
            len(missing) + len(extra)
        )
        status = "matched" if total_issues == 0 else "mismatched"

        result = ReconciliationResult(
            status=status,
            run_id=run_id,
            position_mismatches=position_mismatches,
            trade_mismatches=trade_mismatches,
            pnl_comparison=pnl_comparison,
            missing_trades=missing,
            extra_trades=extra,
        )

        self._publish_result(result)

        logger.info(
            f"Reconciliation {status}: {total_issues} issues found "
            f"({len(position_mismatches)} position, {len(trade_mismatches)} trade, "
            f"{len(missing)} missing, {len(extra)} extra)"
        )

        return result.to_dict()

    def _check_positions(self, run_id: str) -> List[Dict]:
        """Compare DB open paper trades vs Alpaca get_positions()."""
        mismatches = []

        # Get Alpaca positions
        alpaca_positions = self.client.get_positions()
        if isinstance(alpaca_positions, dict) and "error" in alpaca_positions:
            mismatches.append({
                "type": "api_error",
                "message": f"Failed to get Alpaca positions: {alpaca_positions['error']}",
            })
            return mismatches

        alpaca_by_symbol = {
            p["symbol"]: p for p in alpaca_positions
        }

        # Get DB positions
        db_positions = self._get_db_positions()
        db_by_symbol = {p["symbol"]: p for p in db_positions}

        # Check each Alpaca position against DB
        for symbol, alpaca_pos in alpaca_by_symbol.items():
            db_pos = db_by_symbol.get(symbol)
            if not db_pos:
                mismatches.append({
                    "type": "position_in_alpaca_not_db",
                    "symbol": symbol,
                    "alpaca_qty": float(alpaca_pos.get("qty", 0)),
                    "message": f"{symbol}: position in Alpaca but not in DB",
                })
            else:
                alpaca_qty = float(alpaca_pos.get("qty", 0))
                db_qty = float(db_pos.get("qty", 0))
                if abs(alpaca_qty - db_qty) > 0.01:
                    mismatches.append({
                        "type": "position_qty_mismatch",
                        "symbol": symbol,
                        "alpaca_qty": alpaca_qty,
                        "db_qty": db_qty,
                        "message": f"{symbol}: Alpaca qty={alpaca_qty}, DB qty={db_qty}",
                    })

        # Check DB positions not in Alpaca
        for symbol, db_pos in db_by_symbol.items():
            if symbol not in alpaca_by_symbol:
                mismatches.append({
                    "type": "position_in_db_not_alpaca",
                    "symbol": symbol,
                    "db_qty": float(db_pos.get("qty", 0)),
                    "message": f"{symbol}: position in DB but not in Alpaca",
                })

        return mismatches

    def _check_trades(self, window_start: datetime,
                      window_end: datetime) -> tuple:
        """Compare DB paper trades in window vs Alpaca orders in window."""
        trade_mismatches = []
        missing_trades = []
        extra_trades = []

        # Get Alpaca filled orders in window
        alpaca_orders = self.client.get_orders(
            status="closed",
            after=window_start.isoformat(),
            until=window_end.isoformat(),
            limit=500,
        )
        if isinstance(alpaca_orders, dict) and "error" in alpaca_orders:
            trade_mismatches.append({
                "type": "api_error",
                "message": f"Failed to get Alpaca orders: {alpaca_orders['error']}",
            })
            return trade_mismatches, missing_trades, extra_trades

        # Filter to filled orders only
        alpaca_filled = [
            o for o in alpaca_orders
            if o.get("status") == "filled"
        ]

        alpaca_by_id = {str(o.get("id", "")): o for o in alpaca_filled}

        # Get DB trades in window
        db_trades = self._get_db_trades(window_start, window_end)
        db_order_ids = {t.get("order_id") for t in db_trades if t.get("order_id")}

        # Orders in Alpaca but not in DB
        for order_id, order in alpaca_by_id.items():
            if order_id not in db_order_ids:
                missing_trades.append({
                    "order_id": order_id,
                    "symbol": order.get("symbol"),
                    "side": order.get("side"),
                    "qty": order.get("qty"),
                    "filled_at": order.get("filled_at"),
                    "message": f"Order {order_id[:8]}... ({order.get('symbol')} {order.get('side')}) in Alpaca but not DB",
                })

        # Trades in DB with order_ids not in Alpaca
        for trade in db_trades:
            order_id = trade.get("order_id")
            if order_id and order_id not in alpaca_by_id:
                extra_trades.append({
                    "order_id": order_id,
                    "symbol": trade.get("symbol"),
                    "side": trade.get("side"),
                    "message": f"Order {order_id[:8]}... ({trade.get('symbol')}) in DB but not Alpaca",
                })

        return trade_mismatches, missing_trades, extra_trades

    def _check_pnl(self, account: Dict) -> Dict:
        """Compare DB calculated P&L vs Alpaca portfolio equity."""
        alpaca_equity = float(account.get("equity", 0))
        alpaca_cash = float(account.get("cash", 0))
        alpaca_pv = float(account.get("portfolio_value", 0))

        db_pnl = self._get_db_total_pnl()

        return {
            "alpaca_equity": alpaca_equity,
            "alpaca_cash": alpaca_cash,
            "alpaca_portfolio_value": alpaca_pv,
            "db_total_pnl": db_pnl,
        }

    def _get_db_positions(self) -> List[Dict]:
        """Fetch open paper trade positions from DB."""
        try:
            from utils.db.db_pool import DatabasePool
            from sqlalchemy import text

            pool = DatabasePool()
            with pool.get_session() as session:
                result = session.execute(text("""
                    SELECT symbol, SUM(shares) as qty
                    FROM alpatrade.trades
                    WHERE trade_type = 'paper'
                      AND direction = 'long'
                      AND exit_price IS NULL
                    GROUP BY symbol
                    HAVING SUM(shares) > 0
                """))
                return [{"symbol": r[0], "qty": float(r[1])} for r in result.fetchall()]
        except Exception as e:
            logger.warning(f"Could not fetch DB positions: {e}")
            return []

    def _get_db_trades(self, window_start: datetime,
                       window_end: datetime) -> List[Dict]:
        """Fetch paper trades from DB in the given window."""
        try:
            from utils.db.db_pool import DatabasePool
            from sqlalchemy import text

            pool = DatabasePool()
            with pool.get_session() as session:
                result = session.execute(
                    text("""
                        SELECT symbol, direction, shares, entry_price, exit_price,
                               pnl, trade_type, created_at, order_id
                        FROM alpatrade.trades
                        WHERE trade_type = 'paper'
                          AND created_at >= :start
                          AND created_at <= :end
                        ORDER BY created_at
                    """),
                    {"start": window_start, "end": window_end},
                )
                rows = result.fetchall()
                return [
                    {
                        "symbol": r[0],
                        "side": "buy" if r[1] == "long" else "sell",
                        "shares": float(r[2]) if r[2] else 0,
                        "entry_price": float(r[3]) if r[3] else 0,
                        "exit_price": float(r[4]) if r[4] else None,
                        "pnl": float(r[5]) if r[5] else 0,
                        "trade_type": r[6],
                        "created_at": r[7],
                        "order_id": r[8],
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning(f"Could not fetch DB trades: {e}")
            return []

    def _get_db_total_pnl(self) -> float:
        """Get total P&L from DB paper trades."""
        try:
            from utils.db.db_pool import DatabasePool
            from sqlalchemy import text

            pool = DatabasePool()
            with pool.get_session() as session:
                result = session.execute(text("""
                    SELECT COALESCE(SUM(pnl), 0)
                    FROM alpatrade.trades
                    WHERE trade_type = 'paper'
                      AND pnl IS NOT NULL
                """))
                row = result.fetchone()
                return float(row[0]) if row else 0.0
        except Exception as e:
            logger.warning(f"Could not fetch DB total P&L: {e}")
            return 0.0

    def _publish_result(self, result: ReconciliationResult):
        """Send reconciliation result to message bus."""
        if self.message_bus:
            self.message_bus.publish(
                from_agent="reconciler",
                to_agent="portfolio_manager",
                msg_type="reconciliation_result",
                payload=result.to_dict(),
            )
