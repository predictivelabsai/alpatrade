-- Backtest Summary Table
-- Stores high-level metrics for each backtest run

CREATE TABLE IF NOT EXISTS backtest_summary (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(255) UNIQUE NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    model_name VARCHAR(255) DEFAULT 'prediction_llm',
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_capital NUMERIC(15, 2) NOT NULL,
    final_capital NUMERIC(15, 2) NOT NULL,
    total_pnl NUMERIC(15, 2) NOT NULL,
    return_percent NUMERIC(10, 4) NOT NULL,
    total_trades INTEGER NOT NULL DEFAULT 0,
    winning_trades INTEGER NOT NULL DEFAULT 0,
    losing_trades INTEGER NOT NULL DEFAULT 0,
    win_rate_percent NUMERIC(10, 4) NOT NULL DEFAULT 0,
    max_drawdown NUMERIC(10, 4) NOT NULL DEFAULT 0,
    sharpe_ratio NUMERIC(10, 4) NOT NULL DEFAULT 0,
    news_articles_used INTEGER NOT NULL DEFAULT 0,
    price_moves_used INTEGER NOT NULL DEFAULT 0,
    database_version VARCHAR(50) DEFAULT 'v1.0',
    agent VARCHAR(100) DEFAULT 'manus',
    annualized_return NUMERIC(10, 4) NOT NULL DEFAULT 0,
    rundate DATE NOT NULL,
    notes TEXT,
    strategy_id VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_backtest_summary_run_id ON backtest_summary(run_id);
CREATE INDEX IF NOT EXISTS idx_backtest_summary_timestamp ON backtest_summary(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_summary_strategy_id ON backtest_summary(strategy_id);
CREATE INDEX IF NOT EXISTS idx_backtest_summary_rundate ON backtest_summary(rundate DESC);
