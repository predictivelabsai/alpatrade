-- 43_cwt_episodes.sql
-- Chat With Traders podcast catalogue (scripts/cwt_pipeline.py catalogue --db).
-- Idempotent and additive; touches no existing table.
CREATE TABLE IF NOT EXISTS alpatrade.cwt_episodes (
    slug            VARCHAR(160) PRIMARY KEY,
    episode_number  INTEGER,
    title           TEXT NOT NULL DEFAULT '',
    guest           VARCHAR(200) NOT NULL DEFAULT '',
    page_url        TEXT NOT NULL DEFAULT '',
    audio_url       TEXT NOT NULL DEFAULT '',
    youtube_url     TEXT NOT NULL DEFAULT '',
    pub_date        DATE,
    duration_sec    INTEGER,
    categories      TEXT NOT NULL DEFAULT '',
    tags            TEXT NOT NULL DEFAULT '',
    strategy_id     INTEGER,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cwt_episodes_number ON alpatrade.cwt_episodes (episode_number);
