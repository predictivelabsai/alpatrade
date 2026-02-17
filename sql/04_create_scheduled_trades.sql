-- Scheduled Trades Table
-- Stores scheduled trading jobs and their execution status

CREATE TABLE IF NOT EXISTS scheduled_trades (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(255) UNIQUE NOT NULL,
    strategy_id VARCHAR(255) NOT NULL,
    schedule_type VARCHAR(50) NOT NULL CHECK (schedule_type IN ('once', 'daily', 'weekly', 'cron')),
    schedule_expression VARCHAR(255),
    start_time TIME,
    end_time TIME,
    is_paper BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT TRUE,
    last_run TIMESTAMPTZ,
    next_run TIMESTAMPTZ,
    run_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100) DEFAULT 'user'
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_scheduled_trades_job_id ON scheduled_trades(job_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_trades_strategy_id ON scheduled_trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_trades_is_active ON scheduled_trades(is_active);
CREATE INDEX IF NOT EXISTS idx_scheduled_trades_next_run ON scheduled_trades(next_run);
