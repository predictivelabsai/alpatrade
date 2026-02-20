"""
Report Agent

Read-only agent that queries DB for trading performance metrics.
Supports summary (list of recent runs) and detail (single run) modes.
"""

import sys
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

# Ensure project root is importable
project_root = Path(__file__).parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)


class ReportAgent:
    """Agent that generates trading performance reports from DB data."""

    def summary(self, trade_type: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        List recent runs with key metrics.

        For backtest runs: metrics come from backtest_summaries (is_best=true).
        For paper runs: metrics are aggregated from trades table.

        Args:
            trade_type: Filter by mode ('backtest' or 'paper'). None = all.
            limit: Max rows to return.

        Returns:
            List of dicts with run_id, mode, strategy, status, total_pnl,
            total_return, sharpe_ratio, total_trades, started_at.
        """
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text

        where_clauses = []
        bind: Dict[str, Any] = {"lim": limit}
        if trade_type:
            where_clauses.append("r.mode = :mode")
            bind["mode"] = trade_type

        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        pool = DatabasePool()
        with pool.get_session() as session:
            rows = session.execute(
                text(f"""
                    SELECT
                        r.run_id,
                        r.mode,
                        r.strategy,
                        r.strategy_slug,
                        r.status,
                        r.started_at,
                        r.completed_at,
                        r.config,
                        -- Backtest metrics (best variation)
                        bs.total_pnl          AS bt_pnl,
                        bs.total_return       AS bt_return,
                        bs.sharpe_ratio       AS bt_sharpe,
                        bs.total_trades       AS bt_trades,
                        bs.win_rate           AS bt_win_rate,
                        bs.annualized_return  AS bt_ann_ret,
                        -- Paper trade aggregates
                        pt.paper_pnl,
                        pt.paper_trades,
                        pt.paper_wins,
                        -- Data period (from trades)
                        td.data_start,
                        td.data_end
                    FROM alpatrade.runs r
                    LEFT JOIN alpatrade.backtest_summaries bs
                        ON bs.run_id = r.run_id AND bs.is_best = true
                    LEFT JOIN (
                        SELECT run_id,
                               COALESCE(SUM(pnl), 0)                        AS paper_pnl,
                               COUNT(*)                                       AS paper_trades,
                               COUNT(*) FILTER (WHERE pnl > 0)               AS paper_wins
                        FROM alpatrade.trades
                        WHERE trade_type = 'paper'
                        GROUP BY run_id
                    ) pt ON pt.run_id = r.run_id AND r.mode = 'paper'
                    LEFT JOIN (
                        SELECT run_id,
                               MIN(entry_time) AS data_start,
                               MAX(COALESCE(exit_time, entry_time)) AS data_end
                        FROM alpatrade.trades
                        GROUP BY run_id
                    ) td ON td.run_id = r.run_id
                    {where_sql}
                    ORDER BY r.created_at DESC
                    LIMIT :lim
                """),
                bind,
            ).fetchall()

        results = []
        for row in rows:
            (run_id, mode, strategy, strategy_slug, status, started_at,
             completed_at, config_json, bt_pnl, bt_return, bt_sharpe,
             bt_trades, bt_win_rate, bt_ann_ret,
             paper_pnl, paper_trades, paper_wins,
             data_start, data_end) = row

            initial_capital = self._initial_capital(config_json)

            # Pick metrics based on mode
            if mode == "backtest" and bt_pnl is not None:
                total_pnl = float(bt_pnl)
                total_return = float(bt_return or 0)
                sharpe = float(bt_sharpe or 0)
                trades_count = int(bt_trades or 0)
                ann_ret = float(bt_ann_ret or 0)
            elif mode == "paper" and paper_trades:
                total_pnl = float(paper_pnl or 0)
                total_return = (total_pnl / initial_capital * 100) if initial_capital else 0
                sharpe = 0  # not enough data for paper
                trades_count = int(paper_trades or 0)
                ann_ret = 0
            else:
                total_pnl = 0
                total_return = 0
                sharpe = 0
                trades_count = 0
                ann_ret = 0

            results.append({
                "run_id": run_id,
                "mode": mode,
                "strategy": strategy,
                "strategy_slug": strategy_slug,
                "status": status,
                "initial_capital": initial_capital,
                "total_pnl": total_pnl,
                "total_return": total_return,
                "annualized_return": ann_ret,
                "sharpe_ratio": sharpe,
                "total_trades": trades_count,
                "data_start": data_start,
                "data_end": data_end,
                "run_date": started_at,
            })

        return results

    def detail(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        Full performance report for a single run.

        For backtest: uses pre-computed metrics from backtest_summaries.
        For paper: computes metrics from individual trades.

        Returns:
            Dict with all metrics, or None if run not found.
        """
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text

        pool = DatabasePool()
        with pool.get_session() as session:
            # Support prefix matching (e.g. short IDs like "5acc08ba")
            run_row = session.execute(
                text("""
                    SELECT run_id, mode, strategy, status,
                           config, started_at, completed_at
                    FROM alpatrade.runs
                    WHERE run_id LIKE :prefix
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"prefix": run_id + "%"},
            ).fetchone()

            if not run_row:
                return None

            run_id, mode, strategy, status, config_json, started_at, completed_at = run_row
            initial_capital = self._initial_capital(config_json)

            if mode == "backtest":
                return self._detail_backtest(
                    session, run_id, mode, strategy, status,
                    initial_capital, started_at, completed_at,
                )
            else:
                return self._detail_paper(
                    session, run_id, mode, strategy, status,
                    initial_capital, started_at, completed_at,
                )

    def top_strategies(self, strategy: Optional[str] = None,
                        limit: int = 20) -> List[Dict[str, Any]]:
        """
        Rank strategy slugs by average annualized return across all runs.

        Args:
            strategy: Optional prefix filter (e.g. "btd" to show only buy-the-dip).
            limit: Max rows to return.

        Returns:
            List of dicts with strategy_slug, avg_sharpe, avg_return, avg_win_rate,
            total_runs, total_trades.
        """
        from utils.db.db_pool import DatabasePool
        from sqlalchemy import text

        where_clauses = ["bs.strategy_slug IS NOT NULL"]
        bind: Dict[str, Any] = {"lim": limit}
        if strategy:
            where_clauses.append("bs.strategy_slug LIKE :prefix")
            bind["prefix"] = strategy + "%"

        where_sql = " WHERE " + " AND ".join(where_clauses)

        pool = DatabasePool()
        with pool.get_session() as session:
            rows = session.execute(
                text(f"""
                    SELECT
                        bs.strategy_slug,
                        AVG(bs.sharpe_ratio)      AS avg_sharpe,
                        AVG(bs.total_return)       AS avg_return,
                        AVG(bs.annualized_return)  AS avg_ann_return,
                        AVG(bs.win_rate)           AS avg_win_rate,
                        AVG(bs.max_drawdown)       AS avg_drawdown,
                        SUM(bs.total_trades)       AS total_trades,
                        COUNT(*)                   AS total_runs,
                        AVG(bs.total_pnl)          AS avg_pnl
                    FROM alpatrade.backtest_summaries bs
                    {where_sql}
                    GROUP BY bs.strategy_slug
                    ORDER BY avg_ann_return DESC
                    LIMIT :lim
                """),
                bind,
            ).fetchall()

        results = []
        for row in rows:
            (slug, avg_sharpe, avg_return, avg_ann_return, avg_win_rate,
             avg_drawdown, total_trades, total_runs, avg_pnl) = row
            results.append({
                "strategy_slug": slug,
                "avg_sharpe": float(avg_sharpe or 0),
                "avg_return": float(avg_return or 0),
                "avg_ann_return": float(avg_ann_return or 0),
                "avg_win_rate": float(avg_win_rate or 0),
                "avg_drawdown": float(avg_drawdown or 0),
                "total_trades": int(total_trades or 0),
                "total_runs": int(total_runs or 0),
                "avg_pnl": float(avg_pnl or 0),
            })
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detail_backtest(self, session, run_id, mode, strategy, status,
                         initial_capital, started_at, completed_at):
        from sqlalchemy import text

        bs = session.execute(
            text("""
                SELECT total_return, total_pnl, sharpe_ratio, max_drawdown,
                       annualized_return, win_rate, total_trades, strategy_slug
                FROM alpatrade.backtest_summaries
                WHERE run_id = :run_id AND is_best = true
            """),
            {"run_id": run_id},
        ).fetchone()

        # Data period from trades
        tp = session.execute(
            text("""
                SELECT MIN(entry_time), MAX(COALESCE(exit_time, entry_time))
                FROM alpatrade.trades WHERE run_id = :run_id
            """),
            {"run_id": run_id},
        ).fetchone()
        data_start = tp[0] if tp else None
        data_end = tp[1] if tp else None

        if bs:
            total_return, total_pnl, sharpe, max_dd, ann_ret, win_rate, total_trades, bs_slug = bs
            total_pnl = float(total_pnl or 0)
            total_return = float(total_return or 0)
            final_capital = initial_capital + total_pnl
            winning = int(round(float(win_rate or 0) / 100 * float(total_trades or 0)))
            losing = int(total_trades or 0) - winning
        else:
            total_pnl = total_return = sharpe = max_dd = ann_ret = win_rate = 0
            total_trades = winning = losing = 0
            final_capital = initial_capital
            bs_slug = None

        return {
            "run_id": run_id,
            "mode": mode,
            "strategy": strategy,
            "strategy_slug": bs_slug,
            "status": status,
            "initial_capital": initial_capital,
            "final_capital": final_capital,
            "total_pnl": total_pnl,
            "total_return": float(total_return),
            "annualized_return": float(ann_ret or 0),
            "sharpe_ratio": float(sharpe or 0),
            "max_drawdown": float(max_dd or 0),
            "win_rate": float(win_rate or 0),
            "total_trades": int(total_trades or 0),
            "winning_trades": winning,
            "losing_trades": losing,
            "data_start": data_start,
            "data_end": data_end,
            "run_date": started_at,
        }

    def _detail_paper(self, session, run_id, mode, strategy, status,
                      initial_capital, started_at, completed_at):
        from sqlalchemy import text

        rows = session.execute(
            text("""
                SELECT pnl, pnl_pct, capital_after
                FROM alpatrade.trades
                WHERE run_id = :run_id AND trade_type = 'paper'
                ORDER BY created_at
            """),
            {"run_id": run_id},
        ).fetchall()

        # Data period from trades
        tp = session.execute(
            text("""
                SELECT MIN(entry_time), MAX(COALESCE(exit_time, entry_time))
                FROM alpatrade.trades WHERE run_id = :run_id
            """),
            {"run_id": run_id},
        ).fetchone()
        data_start = tp[0] if tp else None
        data_end = tp[1] if tp else None

        if not rows:
            return {
                "run_id": run_id,
                "mode": mode,
                "strategy": strategy,
                "status": status,
                "initial_capital": initial_capital,
                "final_capital": initial_capital,
                "total_pnl": 0,
                "total_return": 0,
                "annualized_return": 0,
                "sharpe_ratio": 0,
                "max_drawdown": 0,
                "win_rate": 0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "data_start": data_start,
                "data_end": data_end,
                "run_date": started_at,
            }

        import numpy as np

        pnls = [float(r[0] or 0) for r in rows]
        pnl_pcts = [float(r[1] or 0) for r in rows]
        capitals = [float(r[2] or initial_capital) for r in rows]

        total_pnl = sum(pnls)
        total_trades = len(rows)
        winning = sum(1 for p in pnls if p > 0)
        losing = total_trades - winning
        win_rate = (winning / total_trades * 100) if total_trades else 0
        total_return = (total_pnl / initial_capital * 100) if initial_capital else 0
        final_capital = capitals[-1] if capitals else initial_capital

        # Annualized return
        if started_at and completed_at:
            days = (completed_at - started_at).total_seconds() / 86400
        else:
            days = 0
        ann_ret = (total_return * 365.25 / days) if days > 0 else 0

        # Max drawdown from capital curve
        if capitals:
            arr = np.array(capitals)
            running_max = np.maximum.accumulate(arr)
            dd = (arr - running_max) / running_max
            max_dd = abs(dd.min()) * 100
        else:
            max_dd = 0

        # Sharpe ratio
        if pnl_pcts and np.std(pnl_pcts) > 0:
            sharpe = (np.mean(pnl_pcts) / np.std(pnl_pcts)) * np.sqrt(252)
        else:
            sharpe = 0

        return {
            "run_id": run_id,
            "mode": mode,
            "strategy": strategy,
            "status": status,
            "initial_capital": initial_capital,
            "final_capital": final_capital,
            "total_pnl": total_pnl,
            "total_return": total_return,
            "annualized_return": ann_ret,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "total_trades": total_trades,
            "winning_trades": winning,
            "losing_trades": losing,
            "data_start": data_start,
            "data_end": data_end,
            "run_date": started_at,
        }

    @staticmethod
    def _initial_capital(config_json) -> float:
        """Extract initial_capital from the runs.config JSONB column."""
        if not config_json:
            return 10_000.0
        if isinstance(config_json, str):
            import json
            config_json = json.loads(config_json)
        return float(config_json.get("initial_capital", 10_000))
