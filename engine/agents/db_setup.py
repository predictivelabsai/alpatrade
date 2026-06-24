"""
Database Table Setup for Agent System

Creates the `trades` and `agent_runs` tables if they don't exist.
Uses the existing DatabasePool from utils/db/db_pool.py.
"""

import sys
import logging
from pathlib import Path

# Ensure project root is on the path
project_root = Path(__file__).parent.parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from sqlalchemy import text
from utils.db.db_pool import DatabasePool

logger = logging.getLogger(__name__)

TRADES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64),
    agent VARCHAR(32) NOT NULL DEFAULT 'paper_trader',
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    symbol VARCHAR(16) NOT NULL,
    side VARCHAR(8) NOT NULL,
    qty NUMERIC(12, 4) NOT NULL,
    price NUMERIC(12, 4),
    filled_price NUMERIC(12, 4),
    order_id VARCHAR(64),
    status VARCHAR(32) DEFAULT 'pending',
    pnl NUMERIC(12, 4),
    pnl_pct NUMERIC(8, 4),
    strategy VARCHAR(64),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""

AGENT_RUNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(64) UNIQUE NOT NULL,
    mode VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    config JSONB,
    results JSONB,
    notes TEXT
);
"""


def setup_tables(db_pool: DatabasePool = None):
    """Create agent system tables if they don't exist."""
    pool = db_pool or DatabasePool()
    with pool.get_session() as session:
        session.execute(text(TRADES_TABLE_SQL))
        session.execute(text(AGENT_RUNS_TABLE_SQL))
        logger.info("Agent tables created/verified: trades, agent_runs")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    setup_tables()
    print("Tables created successfully.")
