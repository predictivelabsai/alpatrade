-- Migration 10: Add positions table, pnl_summary table
--
-- positions: tracks open/closed positions per user/run
-- pnl_summary: aggregated P&L breakdown per run+symbol, derived from trades
--
-- trade_type values: 'backtest', 'paper', 'live' (VARCHAR(16), no enum constraint)

-- Table: positions
-- Tracks position state for paper trading and live trading.
CREATE TABLE IF NOT EXISTS alpatrade.positions (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL REFERENCES alpatrade.runs(run_id),
    symbol VARCHAR(16) NOT NULL,
    side VARCHAR(8) NOT NULL,              -- 'long' or 'short'
    shares NUMERIC(12,4) NOT NULL DEFAULT 0,
    avg_entry_price NUMERIC(12,4),
    current_price NUMERIC(12,4),
    market_value NUMERIC(14,4),
    unrealized_pnl NUMERIC(12,4),
    unrealized_pnl_pct NUMERIC(10,4),
    cost_basis NUMERIC(14,4),
    status VARCHAR(16) NOT NULL DEFAULT 'open',   -- 'open' or 'closed'
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    user_id UUID REFERENCES alpatrade.users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_positions_run_id ON alpatrade.positions(run_id);
CREATE INDEX IF NOT EXISTS idx_positions_user_id ON alpatrade.positions(user_id);
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON alpatrade.positions(symbol);
CREATE INDEX IF NOT EXISTS idx_positions_status ON alpatrade.positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_run_symbol ON alpatrade.positions(run_id, symbol);

-- Table: pnl_summary
-- Pre-aggregated P&L breakdown per run + symbol, derived from trades table.
-- Populated/refreshed by application code after trades complete.
CREATE TABLE IF NOT EXISTS alpatrade.pnl_summary (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL REFERENCES alpatrade.runs(run_id),
    symbol VARCHAR(16),                     -- NULL row = run-level totals
    trade_count INTEGER NOT NULL DEFAULT 0,
    win_count INTEGER NOT NULL DEFAULT 0,
    loss_count INTEGER NOT NULL DEFAULT 0,
    total_pnl NUMERIC(14,4) NOT NULL DEFAULT 0,
    total_fees NUMERIC(10,4) NOT NULL DEFAULT 0,
    avg_pnl NUMERIC(12,4),
    avg_pnl_pct NUMERIC(10,4),
    best_trade_pnl NUMERIC(12,4),
    worst_trade_pnl NUMERIC(12,4),
    total_return_pct NUMERIC(10,4),
    win_rate NUMERIC(8,4),
    user_id UUID REFERENCES alpatrade.users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pnl_summary_run_id ON alpatrade.pnl_summary(run_id);
CREATE INDEX IF NOT EXISTS idx_pnl_summary_user_id ON alpatrade.pnl_summary(user_id);
CREATE INDEX IF NOT EXISTS idx_pnl_summary_run_symbol ON alpatrade.pnl_summary(run_id, symbol);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pnl_summary_unique ON alpatrade.pnl_summary(run_id, COALESCE(symbol, '__TOTAL__'));
