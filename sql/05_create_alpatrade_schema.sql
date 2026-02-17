-- AlpaTrade unified schema
-- Consolidates agent data into a single schema with a unified trades table.

CREATE SCHEMA IF NOT EXISTS alpatrade;

-- Table 1: runs
-- Tracks each orchestrator run.
CREATE TABLE IF NOT EXISTS alpatrade.runs (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(64) UNIQUE NOT NULL,
    mode VARCHAR(32) NOT NULL,
    strategy VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    config JSONB,
    results JSONB,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_runs_run_id ON alpatrade.runs(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON alpatrade.runs(status);

-- Table 2: backtest_summaries
-- One row per parameter variation tested in a backtest run.
CREATE TABLE IF NOT EXISTS alpatrade.backtest_summaries (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL REFERENCES alpatrade.runs(run_id),
    variation_index INTEGER NOT NULL DEFAULT 0,
    params JSONB,
    total_return NUMERIC(12,4),
    total_pnl NUMERIC(12,4),
    win_rate NUMERIC(8,4),
    total_trades INTEGER,
    sharpe_ratio NUMERIC(10,4),
    max_drawdown NUMERIC(10,4),
    annualized_return NUMERIC(10,4),
    is_best BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_summaries_run_id ON alpatrade.backtest_summaries(run_id);

-- Table 3: trades (unified)
-- Single table for backtest, paper, and live trades.
CREATE TABLE IF NOT EXISTS alpatrade.trades (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL REFERENCES alpatrade.runs(run_id),
    trade_type VARCHAR(16) NOT NULL,
    symbol VARCHAR(16),
    direction VARCHAR(8),
    shares NUMERIC(12,4),
    entry_time TIMESTAMPTZ,
    exit_time TIMESTAMPTZ,
    entry_price NUMERIC(12,4),
    exit_price NUMERIC(12,4),
    target_price NUMERIC(12,4),
    stop_price NUMERIC(12,4),
    hit_target BOOLEAN,
    hit_stop BOOLEAN,
    pnl NUMERIC(12,4),
    pnl_pct NUMERIC(10,4),
    capital_after NUMERIC(12,4),
    total_fees NUMERIC(10,4) DEFAULT 0,
    dip_pct NUMERIC(10,4),
    order_id VARCHAR(64),
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_run_id ON alpatrade.trades(run_id);
CREATE INDEX IF NOT EXISTS idx_trades_trade_type ON alpatrade.trades(trade_type);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON alpatrade.trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_run_type ON alpatrade.trades(run_id, trade_type);

-- Table 4: validations
-- Stores validation run results.
CREATE TABLE IF NOT EXISTS alpatrade.validations (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL REFERENCES alpatrade.runs(run_id),
    source VARCHAR(16),
    status VARCHAR(16),
    total_checked INTEGER,
    anomalies_found INTEGER,
    anomalies_corrected INTEGER,
    iterations_used INTEGER,
    corrections JSONB,
    suggestions JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_validations_run_id ON alpatrade.validations(run_id);
