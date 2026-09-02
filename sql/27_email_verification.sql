-- Email verification
-- email_verified_at on users (NULL = not yet verified; existing users are
-- backfilled as verified so the deploy does not lock out the beta base) plus a
-- time-limited token table mirroring sql/12_add_password_reset_tokens.sql.

ALTER TABLE alpatrade.users
    ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;

UPDATE alpatrade.users
SET email_verified_at = COALESCE(email_verified_at, created_at)
WHERE email_verified_at IS NULL;

CREATE TABLE IF NOT EXISTS alpatrade.email_verification_tokens (
    id          SERIAL PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    token       VARCHAR(128) UNIQUE NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,           -- NULL until token is consumed
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_verification_token
    ON alpatrade.email_verification_tokens(token);
CREATE INDEX IF NOT EXISTS idx_email_verification_user
    ON alpatrade.email_verification_tokens(user_id);