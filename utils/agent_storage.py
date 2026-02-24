"""
Agent Storage Utility

Provides configurable storage backends (file or DB) for agent results.
Controlled by `general.storage_backend` in config/parameters.yaml.

DB backend writes to the `alpatrade` schema (runs, backtest_summaries,
trades, validations).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
CONFIG_PATH = PROJECT_ROOT / "config" / "parameters.yaml"
DATA_DIR = PROJECT_ROOT / "data"
BACKTEST_DIR = DATA_DIR / "backtest_results"
PAPER_TRADE_DIR = DATA_DIR / "paper_trades"


def get_storage_backend() -> str:
    """Read storage_backend from config. Defaults to 'file'."""
    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
        return cfg.get("general", {}).get("storage_backend", "file")
    except Exception:
        return "file"


def _get_pool():
    """Lazily import and return a DatabasePool instance."""
    from utils.db.db_pool import DatabasePool
    return DatabasePool()


def _py(val):
    """Convert numpy scalars to native Python types for SQL parameters."""
    if val is None:
        return None
    try:
        return val.item()
    except (AttributeError, ValueError):
        return val


# ---------------------------------------------------------------------------
# Runs (DB only)
# ---------------------------------------------------------------------------

def store_run(run_id: str, mode: str, strategy: str = None,
              config: Dict = None, strategy_slug: str = None,
              user_id: Optional[str] = None):
    """Insert a new row into alpatrade.runs."""
    backend = get_storage_backend()
    if backend != "db":
        return
    from sqlalchemy import text
    pool = _get_pool()
    with pool.get_session() as session:
        session.execute(
            text("""
                INSERT INTO alpatrade.runs
                    (run_id, mode, strategy, status, config, started_at, strategy_slug, user_id)
                VALUES
                    (:run_id, :mode, :strategy, 'running', :config, :started_at, :strategy_slug, :user_id)
                ON CONFLICT (run_id) DO NOTHING
            """),
            {
                "run_id": run_id,
                "mode": mode,
                "strategy": strategy,
                "config": json.dumps(config or {}, default=str),
                "started_at": datetime.now(timezone.utc),
                "strategy_slug": strategy_slug,
                "user_id": user_id,
            },
        )
    logger.info(f"Run {run_id} stored (mode={mode})")


def update_run(run_id: str, status: str, results: Dict = None):
    """Update an existing run with final status and results."""
    backend = get_storage_backend()
    if backend != "db":
        return
    from sqlalchemy import text
    pool = _get_pool()
    with pool.get_session() as session:
        session.execute(
            text("""
                UPDATE alpatrade.runs
                SET status = :status,
                    results = :results,
                    completed_at = :completed_at
                WHERE run_id = :run_id
            """),
            {
                "run_id": run_id,
                "status": status,
                "results": json.dumps(results or {}, default=str),
                "completed_at": datetime.now(timezone.utc),
            },
        )
    logger.info(f"Run {run_id} updated -> {status}")


# ---------------------------------------------------------------------------
# Backtest results
# ---------------------------------------------------------------------------

def store_backtest_results(run_id: str, best: Dict, all_results: List[Dict],
                           trades: Optional[List[Dict]] = None,
                           strategy: str = None, lookback: str = None,
                           user_id: Optional[str] = None):
    """Store backtest results using the configured backend."""
    backend = get_storage_backend()
    if backend == "db":
        _store_backtest_db(run_id, best, all_results, trades,
                           strategy=strategy, lookback=lookback,
                           user_id=user_id)
    else:
        _store_backtest_file(run_id, best, all_results, trades)


def _store_backtest_file(run_id: str, best: Dict, all_results: List[Dict],
                         trades: Optional[List[Dict]] = None):
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKTEST_DIR / f"{run_id}.json"
    payload = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "best_config": best,
        "all_results": all_results,
        "trades": trades or [],
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    logger.info(f"Backtest results written to {path}")


def _store_backtest_db(run_id: str, best: Dict, all_results: List[Dict],
                       trades: Optional[List[Dict]] = None,
                       strategy: str = None, lookback: str = None,
                       user_id: Optional[str] = None):
    """Write backtest summaries + trades into the alpatrade schema."""
    from sqlalchemy import text
    pool = _get_pool()

    # Build slugs for each variation and identify the best slug
    best_slug = None
    if strategy:
        from utils.strategy_slug import build_slug

    with pool.get_session() as session:
        # --- backtest_summaries ---
        for idx, variation in enumerate(all_results):
            is_best = (variation == best)
            params = variation.get("params", {})

            # Build per-variation slug
            slug = None
            if strategy:
                slug = build_slug(strategy, params, lookback or "")
            if is_best:
                best_slug = slug

            session.execute(
                text("""
                    INSERT INTO alpatrade.backtest_summaries
                        (run_id, variation_index, params, total_return, total_pnl,
                         win_rate, total_trades, sharpe_ratio, max_drawdown,
                         annualized_return, is_best, strategy_slug, user_id)
                    VALUES
                        (:run_id, :idx, :params, :total_return, :total_pnl,
                         :win_rate, :total_trades, :sharpe_ratio, :max_drawdown,
                         :annualized_return, :is_best, :strategy_slug, :user_id)
                """),
                {
                    "run_id": run_id,
                    "idx": idx,
                    "params": json.dumps(params, default=str),
                    "total_return": _py(variation.get("total_return")),
                    "total_pnl": _py(variation.get("total_pnl")),
                    "win_rate": _py(variation.get("win_rate")),
                    "total_trades": _py(variation.get("total_trades")),
                    "sharpe_ratio": _py(variation.get("sharpe_ratio")),
                    "max_drawdown": _py(variation.get("max_drawdown")),
                    "annualized_return": _py(variation.get("annualized_return")),
                    "is_best": is_best,
                    "strategy_slug": slug,
                    "user_id": user_id,
                },
            )

        # Update runs.strategy_slug with the best variation's slug
        if best_slug:
            session.execute(
                text("""
                    UPDATE alpatrade.runs
                    SET strategy_slug = :slug
                    WHERE run_id = :run_id
                """),
                {"run_id": run_id, "slug": best_slug},
            )

        # --- trades (trade_type='backtest') ---
        for t in (trades or []):
            session.execute(
                text("""
                    INSERT INTO alpatrade.trades
                        (run_id, trade_type, symbol, direction, shares,
                         entry_time, exit_time, entry_price, exit_price,
                         target_price, stop_price, hit_target, hit_stop,
                         pnl, pnl_pct, capital_after, total_fees, dip_pct,
                         reason, user_id)
                    VALUES
                        (:run_id, 'backtest', :symbol, :direction, :shares,
                         :entry_time, :exit_time, :entry_price, :exit_price,
                         :target_price, :stop_price, :hit_target, :hit_stop,
                         :pnl, :pnl_pct, :capital_after, :total_fees, :dip_pct,
                         :reason, :user_id)
                """),
                {
                    "run_id": run_id,
                    "symbol": t.get("ticker") or t.get("symbol"),
                    "direction": t.get("direction", "long"),
                    "shares": _py(t.get("shares") or t.get("qty")),
                    "entry_time": t.get("entry_time") or t.get("entry_date"),
                    "exit_time": t.get("exit_time") or t.get("exit_date"),
                    "entry_price": _py(t.get("entry_price")),
                    "exit_price": _py(t.get("exit_price")),
                    "target_price": _py(t.get("target_price")),
                    "stop_price": _py(t.get("stop_price")),
                    "hit_target": t.get("hit_target"),
                    "hit_stop": t.get("hit_stop"),
                    "pnl": _py(t.get("pnl")),
                    "pnl_pct": _py(t.get("pnl_pct")),
                    "capital_after": _py(t.get("capital_after")),
                    "total_fees": _py(t.get("total_fees", 0)),
                    "dip_pct": _py(t.get("dip_pct")),
                    "reason": t.get("reason"),
                    "user_id": user_id,
                },
            )

    logger.info(
        f"Backtest DB: {len(all_results)} summaries, "
        f"{len(trades or [])} trades for run {run_id}"
    )


def fetch_backtest_trades(run_id: str, user_id: Optional[str] = None) -> List[Dict]:
    """Fetch backtest trades using the configured backend."""
    backend = get_storage_backend()
    if backend == "db":
        return _fetch_backtest_trades_db(run_id, user_id=user_id)
    return _fetch_backtest_trades_file(run_id)


def _fetch_backtest_trades_file(run_id: str) -> List[Dict]:
    path = BACKTEST_DIR / f"{run_id}.json"
    if not path.exists():
        logger.warning(f"Backtest file not found: {path}")
        return []
    data = json.loads(path.read_text())
    return data.get("trades", [])


def _fetch_backtest_trades_db(run_id: str, user_id: Optional[str] = None) -> List[Dict]:
    from sqlalchemy import text
    pool = _get_pool()
    with pool.get_session() as session:
        sql = """
            SELECT * FROM alpatrade.trades
            WHERE trade_type = 'backtest' AND run_id = :run_id
        """
        bind = {"run_id": run_id}
        if user_id:
            sql += " AND user_id = :user_id"
            bind["user_id"] = user_id
        sql += " ORDER BY entry_time"
        result = session.execute(text(sql), bind)
        columns = result.keys()
        return [dict(zip(columns, row)) for row in result.fetchall()]


# ---------------------------------------------------------------------------
# Paper trades
# ---------------------------------------------------------------------------

def store_paper_trade(session_id: str, trade: Dict,
                      user_id: Optional[str] = None):
    """Store a single paper trade using the configured backend."""
    backend = get_storage_backend()
    if backend == "db":
        _store_paper_trade_db(session_id, trade, user_id=user_id)
    else:
        _store_paper_trade_file(session_id, trade)


def _store_paper_trade_file(session_id: str, trade: Dict):
    PAPER_TRADE_DIR.mkdir(parents=True, exist_ok=True)
    path = PAPER_TRADE_DIR / f"{session_id}.jsonl"
    with open(path, "a") as f:
        f.write(json.dumps(trade, default=str) + "\n")
    logger.debug(f"Paper trade appended to {path}")


def _store_paper_trade_db(session_id: str, trade: Dict,
                          user_id: Optional[str] = None):
    from sqlalchemy import text
    pool = _get_pool()
    with pool.get_session() as session:
        session.execute(
            text("""
                INSERT INTO alpatrade.trades
                    (run_id, trade_type, symbol, direction, shares,
                     entry_time, exit_time, entry_price, exit_price,
                     target_price, stop_price, hit_target, hit_stop,
                     pnl, pnl_pct, capital_after, total_fees, dip_pct,
                     order_id, reason, user_id)
                VALUES
                    (:run_id, 'paper', :symbol, :direction, :shares,
                     :entry_time, :exit_time, :entry_price, :exit_price,
                     :target_price, :stop_price, :hit_target, :hit_stop,
                     :pnl, :pnl_pct, :capital_after, :total_fees, :dip_pct,
                     :order_id, :reason, :user_id)
            """),
            {
                "run_id": session_id,
                "symbol": trade.get("symbol"),
                "direction": trade.get("side") or trade.get("direction"),
                "shares": _py(trade.get("qty") or trade.get("shares")),
                "entry_time": trade.get("entry_time"),
                "exit_time": trade.get("exit_time"),
                "entry_price": _py(trade.get("entry_price") or trade.get("price")),
                "exit_price": _py(trade.get("exit_price") or trade.get("filled_price")),
                "target_price": _py(trade.get("target_price")),
                "stop_price": _py(trade.get("stop_price")),
                "hit_target": trade.get("hit_target"),
                "hit_stop": trade.get("hit_stop"),
                "pnl": _py(trade.get("pnl")),
                "pnl_pct": _py(trade.get("pnl_pct")),
                "capital_after": _py(trade.get("capital_after")),
                "total_fees": _py(trade.get("total_fees", 0)),
                "dip_pct": _py(trade.get("dip_pct")),
                "order_id": trade.get("order_id"),
                "reason": trade.get("reason") or trade.get("notes"),
                "user_id": user_id,
            },
        )
    logger.debug(f"Paper trade stored to DB for session {session_id}")


def fetch_paper_trades(run_id: str, user_id: Optional[str] = None) -> List[Dict]:
    """Fetch paper trades using the configured backend."""
    backend = get_storage_backend()
    if backend == "db":
        return _fetch_paper_trades_db(run_id, user_id=user_id)
    return _fetch_paper_trades_file(run_id)


def _fetch_paper_trades_file(run_id: str) -> List[Dict]:
    path = PAPER_TRADE_DIR / f"{run_id}.jsonl"
    if not path.exists():
        logger.warning(f"Paper trades file not found: {path}")
        return []
    trades = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            trades.append(json.loads(line))
    return trades


def _fetch_paper_trades_db(run_id: str, user_id: Optional[str] = None) -> List[Dict]:
    from sqlalchemy import text
    pool = _get_pool()
    with pool.get_session() as session:
        sql = """
            SELECT * FROM alpatrade.trades
            WHERE trade_type = 'paper' AND run_id = :run_id
        """
        bind = {"run_id": run_id}
        if user_id:
            sql += " AND user_id = :user_id"
            bind["user_id"] = user_id
        sql += " ORDER BY entry_time"
        result = session.execute(text(sql), bind)
        columns = result.keys()
        return [dict(zip(columns, row)) for row in result.fetchall()]


# ---------------------------------------------------------------------------
# PDT bootstrap (DB only)
# ---------------------------------------------------------------------------

def fetch_recent_day_trades(window_days: int = 7,
                            user_id: Optional[str] = None) -> List[Dict]:
    """Fetch recent same-day round-trips from alpatrade.trades for PDT bootstrap.

    Returns list of {"date": date, "symbol": str} for trades where entry
    and exit occurred on the same calendar day within the last N days.
    """
    backend = get_storage_backend()
    if backend != "db":
        return []
    from sqlalchemy import text
    pool = _get_pool()
    with pool.get_session() as session:
        sql = """
            SELECT symbol, DATE(exit_time) as trade_date
            FROM alpatrade.trades
            WHERE trade_type = 'paper'
              AND exit_time IS NOT NULL
              AND DATE(entry_time) = DATE(exit_time)
              AND exit_time >= NOW() - INTERVAL :days
        """
        bind: Dict[str, Any] = {"days": f"{window_days} days"}
        if user_id:
            sql += " AND user_id = :user_id"
            bind["user_id"] = user_id
        result = session.execute(text(sql), bind)
        return [{"date": row[1], "symbol": row[0]} for row in result.fetchall()]


# ---------------------------------------------------------------------------
# Validations (DB only)
# ---------------------------------------------------------------------------

def store_validation(run_id: str, result: Dict,
                     user_id: Optional[str] = None):
    """Store a validation result into alpatrade.validations."""
    backend = get_storage_backend()
    if backend != "db":
        return
    from sqlalchemy import text
    pool = _get_pool()
    with pool.get_session() as session:
        session.execute(
            text("""
                INSERT INTO alpatrade.validations
                    (run_id, source, status, total_checked, anomalies_found,
                     anomalies_corrected, iterations_used, corrections, suggestions,
                     user_id)
                VALUES
                    (:run_id, :source, :status, :total_checked, :anomalies_found,
                     :anomalies_corrected, :iterations_used, :corrections, :suggestions,
                     :user_id)
            """),
            {
                "run_id": run_id,
                "source": result.get("source"),
                "status": result.get("status"),
                "total_checked": result.get("total_checked", 0),
                "anomalies_found": result.get("anomalies_found", 0),
                "anomalies_corrected": result.get("anomalies_corrected", 0),
                "iterations_used": result.get("iterations_used", 0),
                "corrections": json.dumps(
                    result.get("corrections", []), default=str
                ),
                "suggestions": json.dumps(
                    result.get("suggestions", []), default=str
                ),
                "user_id": user_id,
            },
        )
    logger.info(f"Validation stored for run {run_id}: {result.get('status')}")
