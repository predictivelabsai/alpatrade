-- 38_hedge_fund_13f.sql
-- 13F-HR holdings for a curated set of funds (ingested straight from SEC EDGAR by
-- scripts/hedge_fund_13f.py), a CUSIP -> ticker cache (OpenFIGI), and the cached
-- "13F-implied" performance estimates shown on /hedge-funds.
-- The wide, all-filer 13F dataset stays in the shared hedgefolio schema (read-only
-- for this app); these tables live in the alpatrade schema.
-- Apply with: python run_migration.py sql/38_hedge_fund_13f.sql

CREATE SCHEMA IF NOT EXISTS alpatrade;

CREATE TABLE IF NOT EXISTS alpatrade.hf13f_funds (
    cik VARCHAR(10) PRIMARY KEY,               -- zero-padded SEC CIK
    name TEXT NOT NULL,                        -- EDGAR conformed filer name
    display_name TEXT NOT NULL,
    is_starter BOOLEAN NOT NULL DEFAULT TRUE,
    last_ingested_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alpatrade.hf13f_filings (
    accession_number VARCHAR(25) PRIMARY KEY,
    cik VARCHAR(10) NOT NULL REFERENCES alpatrade.hf13f_funds(cik) ON DELETE CASCADE,
    form_type VARCHAR(16) NOT NULL,            -- 13F-HR | 13F-HR/A
    amendment_type VARCHAR(32),                -- RESTATEMENT | NEW HOLDINGS | NULL
    period_of_report DATE NOT NULL,
    filing_date DATE NOT NULL,
    value_multiplier INTEGER NOT NULL DEFAULT 1, -- 1000 when the filer reported $ thousands
    value_total_usd NUMERIC(20, 2),
    n_positions INTEGER,
    info_table_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hf13f_filings_cik_period
    ON alpatrade.hf13f_filings(cik, period_of_report);

CREATE TABLE IF NOT EXISTS alpatrade.hf13f_holdings (
    accession_number VARCHAR(25) NOT NULL
        REFERENCES alpatrade.hf13f_filings(accession_number) ON DELETE CASCADE,
    row_no INTEGER NOT NULL,
    cusip VARCHAR(9) NOT NULL,
    issuer TEXT,
    title_of_class TEXT,
    value_usd NUMERIC(20, 2) NOT NULL,         -- already multiplied by value_multiplier
    shares NUMERIC(20, 2),
    sh_prn_type VARCHAR(8),                    -- SH | PRN
    put_call VARCHAR(8),                       -- PUT | CALL | NULL
    PRIMARY KEY (accession_number, row_no)
);
CREATE INDEX IF NOT EXISTS idx_hf13f_holdings_cusip ON alpatrade.hf13f_holdings(cusip);

CREATE TABLE IF NOT EXISTS alpatrade.hf13f_cusip_map (
    cusip VARCHAR(9) PRIMARY KEY,
    ticker VARCHAR(24),                        -- Yahoo-style (BRK-B); NULL when unmapped
    name TEXT,
    security_type TEXT,
    status VARCHAR(16) NOT NULL,               -- mapped | unmapped | error
    source VARCHAR(16) NOT NULL DEFAULT 'openfigi',
    resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hf13f_cusip_map_ticker ON alpatrade.hf13f_cusip_map(ticker);

-- One row per fund x method x period label ('2024', 'YTD 2026', 'TTM').
CREATE TABLE IF NOT EXISTS alpatrade.hf13f_performance (
    cik VARCHAR(10) NOT NULL REFERENCES alpatrade.hf13f_funds(cik) ON DELETE CASCADE,
    method VARCHAR(16) NOT NULL,               -- quarter_end | follow_filing
    period_label VARCHAR(16) NOT NULL,
    period_kind VARCHAR(8) NOT NULL,           -- year | ytd | ttm
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    fund_return DOUBLE PRECISION,              -- NULL = not enough 13F data (n/a)
    spy_return DOUBLE PRECISION,
    coverage DOUBLE PRECISION,                 -- avg share of 13F long-equity value priced
    quarters_used INTEGER,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (cik, method, period_label)
);

-- Per holding-period detail (what the annual numbers are chained from).
CREATE TABLE IF NOT EXISTS alpatrade.hf13f_period_returns (
    cik VARCHAR(10) NOT NULL REFERENCES alpatrade.hf13f_funds(cik) ON DELETE CASCADE,
    method VARCHAR(16) NOT NULL,
    period_of_report DATE NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    fund_return DOUBLE PRECISION,
    spy_return DOUBLE PRECISION,
    coverage DOUBLE PRECISION,
    n_priced INTEGER,
    n_positions INTEGER,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (cik, method, period_of_report)
);
