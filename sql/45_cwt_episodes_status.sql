-- 45_cwt_episodes_status.sql
-- Bulk pipeline status per Chat With Traders episode (scripts/cwt_pipeline.py).
--   status         transcribed | not_testable | published | skipped | failed | no_transcript
--   status_reason  e.g. "intraday_only: scalping on 1-min bars", "too few trades (3)"
--   category       LLM classification (daily_testable, intraday_only, options, ...)
--   template       breakout | dip | trend_ma | gap | relative_strength | none
--   strategy_key   merged Leaderboard strategy (one per trader + method), seed_key 'cwt-<key>'
-- Idempotent and additive.
ALTER TABLE alpatrade.cwt_episodes ADD COLUMN IF NOT EXISTS status VARCHAR(32);
ALTER TABLE alpatrade.cwt_episodes ADD COLUMN IF NOT EXISTS status_reason TEXT;
ALTER TABLE alpatrade.cwt_episodes ADD COLUMN IF NOT EXISTS category VARCHAR(32);
ALTER TABLE alpatrade.cwt_episodes ADD COLUMN IF NOT EXISTS template VARCHAR(32);
ALTER TABLE alpatrade.cwt_episodes ADD COLUMN IF NOT EXISTS transcript_source VARCHAR(32);
ALTER TABLE alpatrade.cwt_episodes ADD COLUMN IF NOT EXISTS strategy_key VARCHAR(96);
CREATE INDEX IF NOT EXISTS idx_cwt_episodes_status ON alpatrade.cwt_episodes (status);
