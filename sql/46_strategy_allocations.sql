-- 46_strategy_allocations.sql
-- Several live strategies per Alpaca account, each with its own cash allocation (sleeve)
-- and its own client_order_id prefix (utils/strategy_allocation.py).
--
--   account_number  Alpaca account the sleeve trades in
--   strategy_name   alpatrade.strategy_configs.name (params stay in that versioned table)
--   cid_prefix      tag on every order: entries <p>-SYM-YYYYMMDD, exits <p>tp-/<p>sl-/<p>x-
--                   'btd' is reserved for the primary (Mag-7) strategy.
--   allocation_usd  dollars of equity the sleeve may use; NULL = rest of the account
--                   (equity minus every other active allocation).
--
-- Backward compatible: the primary strategy needs NO row. With no rows the runner behaves
-- exactly as before (Mag-7 sleeve = whole account, pos_frac 1/7 of equity, btd- ids).
-- Rows are written by the web app (/live/allocations), validated against account equity.
--
-- Also seeds the Semi 7 BTD config INACTIVE (is_active = FALSE): nothing trades it until an
-- operator activates the config AND an allocation row exists for the account.
-- Idempotent and additive:  python run_migration.py sql/46_strategy_allocations.sql

CREATE TABLE IF NOT EXISTS alpatrade.strategy_allocations (
    id              SERIAL PRIMARY KEY,
    account_number  VARCHAR(64)  NOT NULL,
    strategy_name   VARCHAR(96)  NOT NULL,
    cid_prefix      VARCHAR(12)  NOT NULL,
    allocation_usd  NUMERIC(14,2) CHECK (allocation_usd IS NULL OR allocation_usd >= 0),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by      VARCHAR(128),
    UNIQUE (account_number, strategy_name),
    UNIQUE (account_number, cid_prefix)
);

-- Semi 7 = the 7 largest US-listed semiconductor stocks by market cap excluding the Mag-7
-- (NVDA excluded). yfinance market caps 2026-10-09: TSM 2346B, AVGO 1726B, MU 1159B,
-- AMD 992B, ASML 684B, INTC 552B, AMAT 402B (next: LRCX 399B, ARM 285B, TXN 259B).
-- Same params as the live Mag-7 BTD (dip 3% vs 20d high, TP 8, SL 1.5, min/max hold 3d).
INSERT INTO alpatrade.strategy_configs (name, display_name, description, params, execution, is_active, updated_by)
VALUES (
    'buy_the_dip_semi7_minhold_live',
    'Semi-7 BTD min-hold 3d',
    'Semi 7 buy-the-dip (largest non-Mag-7 semis), true calendar min-hold; sleeve of the live account',
    '{"symbols": ["TSM", "AVGO", "MU", "AMD", "ASML", "INTC", "AMAT"],
      "dip": 3.0, "tp": 8.0, "sl": 1.5, "min_hold": 3, "max_hold": 3,
      "pos_frac": 0.142857, "max_exposure": 0.0, "ref": "high20", "feed": "iex",
      "entry_window": "15-5", "close_window": "15-2"}'::jsonb,
    '{"regular_hours_exit": {"order_type": "market", "time_in_force": "day"},
      "extended_hours_exit": {"enabled": false, "order_type": "limit", "limit_ref": "bid",
                              "discount_bps": 15, "reprice_after_min": 5, "max_reprices": 2,
                              "fallback": "market_day_at_regular_open"}}'::jsonb,
    FALSE,
    'sql/46_strategy_allocations.sql'
)
ON CONFLICT (name) DO NOTHING;
