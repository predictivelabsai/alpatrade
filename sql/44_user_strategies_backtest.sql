-- 44_user_strategies_backtest.sql
-- Backtest-only Leaderboard strategies (e.g. Chat With Traders pipeline).
--   kind              'live' (default; figures from the owner's live run) or 'backtest'
--   source/source_url where the strategy came from (e.g. chatwithtraders.com + episode link)
--   backtest_metrics  JSON: annualised_pct, total_return_pct, spy_return_pct, alpha_pct,
--                     sharpe, max_drawdown_pct, win_rate_pct, trades, period_start/end, ...
-- Idempotent and additive; existing rows default to kind='live'.
ALTER TABLE alpatrade.user_strategies ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'live';
ALTER TABLE alpatrade.user_strategies ADD COLUMN IF NOT EXISTS source VARCHAR(120);
ALTER TABLE alpatrade.user_strategies ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE alpatrade.user_strategies ADD COLUMN IF NOT EXISTS backtest_metrics JSONB;
