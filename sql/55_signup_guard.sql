-- Anti-bot signup guard (v0.46.0): per-IP signup log + daily admin alert marker.
CREATE TABLE IF NOT EXISTS alpatrade.signup_attempts (
    id          BIGSERIAL PRIMARY KEY,
    ip          VARCHAR(64),
    email       VARCHAR(255),
    user_agent  VARCHAR(300),
    outcome     VARCHAR(32) NOT NULL,      -- created | rate_limited | captcha | honeypot | too_fast | invalid
    user_id     UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_signup_attempts_ip_time ON alpatrade.signup_attempts (ip, created_at);
CREATE INDEX IF NOT EXISTS ix_signup_attempts_time ON alpatrade.signup_attempts (created_at);
CREATE TABLE IF NOT EXISTS alpatrade.signup_alerts (
    alert_day   DATE PRIMARY KEY,
    signups     INTEGER NOT NULL,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
