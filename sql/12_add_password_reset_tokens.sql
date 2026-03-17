-- Password reset tokens table
-- Stores time-limited tokens for forgot-password flow

CREATE TABLE IF NOT EXISTS alpatrade.password_reset_tokens (
    id          SERIAL PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    token       VARCHAR(128) UNIQUE NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,           -- NULL until token is consumed
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_password_reset_token ON alpatrade.password_reset_tokens(token);
CREATE INDEX IF NOT EXISTS idx_password_reset_user ON alpatrade.password_reset_tokens(user_id);
