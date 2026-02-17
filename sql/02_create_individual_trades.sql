-- Individual Trades Table
-- Stores detailed information for each trade executed during backtests

CREATE TABLE IF NOT EXISTS individual_trades (
    id SERIAL PRIMARY KEY,
    published_date TIMESTAMPTZ NOT NULL,
    market VARCHAR(50) DEFAULT 'US',
    entry_time TIMESTAMPTZ NOT NULL,
    exit_time TIMESTAMPTZ NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('long', 'short')),
    shares INTEGER NOT NULL DEFAULT 1,
    entry_price NUMERIC(15, 4) NOT NULL,
    exit_price NUMERIC(15, 4) NOT NULL,
    target_price NUMERIC(15, 4) DEFAULT 0,
    stop_price NUMERIC(15, 4) DEFAULT 0,
    hit_target BOOLEAN DEFAULT FALSE,
    hit_stop BOOLEAN DEFAULT FALSE,
    pnl NUMERIC(15, 2) NOT NULL DEFAULT 0,
    pnl_pct NUMERIC(10, 4) NOT NULL DEFAULT 0,
    capital_after NUMERIC(15, 2) NOT NULL DEFAULT 0,
    news_event VARCHAR(255),
    link TEXT,
    runid VARCHAR(255) NOT NULL,
    rundate TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    news_id INTEGER,
    agent VARCHAR(100) DEFAULT 'manus'
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_individual_trades_runid ON individual_trades(runid);
CREATE INDEX IF NOT EXISTS idx_individual_trades_ticker ON individual_trades(ticker);
CREATE INDEX IF NOT EXISTS idx_individual_trades_entry_time ON individual_trades(entry_time DESC);
CREATE INDEX IF NOT EXISTS idx_individual_trades_rundate ON individual_trades(rundate DESC);
CREATE INDEX IF NOT EXISTS idx_individual_trades_news_event ON individual_trades(news_event);
