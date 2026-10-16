-- RBAC (admin / member / user), teams, login tracking and referrals. Additive + idempotent.
CREATE TABLE IF NOT EXISTS alpatrade.teams (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(120) UNIQUE NOT NULL,
    created_by UUID REFERENCES alpatrade.users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE alpatrade.users ADD COLUMN IF NOT EXISTS role VARCHAR(16) NOT NULL DEFAULT 'user';
ALTER TABLE alpatrade.users ADD COLUMN IF NOT EXISTS team_id INTEGER REFERENCES alpatrade.teams(id) ON DELETE SET NULL;
ALTER TABLE alpatrade.users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
ALTER TABLE alpatrade.users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(16);
ALTER TABLE alpatrade.users ADD COLUMN IF NOT EXISTS referred_by UUID REFERENCES alpatrade.users(user_id) ON DELETE SET NULL;
CREATE UNIQUE INDEX IF NOT EXISTS users_referral_code_uq ON alpatrade.users(referral_code) WHERE referral_code IS NOT NULL;
DO $$ BEGIN
    ALTER TABLE alpatrade.users ADD CONSTRAINT users_role_check CHECK (role IN ('admin', 'member', 'user'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- Existing admins keep admin; Julian is seeded as admin.
UPDATE alpatrade.users SET role = 'admin' WHERE is_admin AND role <> 'admin';
UPDATE alpatrade.users SET role = 'admin', is_admin = TRUE WHERE lower(email) = 'kaljuvee@gmail.com';

CREATE TABLE IF NOT EXISTS alpatrade.user_logins (
    id         BIGSERIAL PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    method     VARCHAR(16) NOT NULL DEFAULT 'password',
    ip         VARCHAR(64),
    user_agent VARCHAR(300),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS user_logins_created ON alpatrade.user_logins(created_at DESC);
CREATE INDEX IF NOT EXISTS user_logins_user ON alpatrade.user_logins(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS alpatrade.referral_invites (
    id               SERIAL PRIMARY KEY,
    referrer_id      UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    email            VARCHAR(255) NOT NULL,
    status           VARCHAR(16) NOT NULL DEFAULT 'sent' CHECK (status IN ('sent', 'failed', 'accepted')),
    message_id       VARCHAR(80),
    sent_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_at      TIMESTAMPTZ,
    accepted_user_id UUID REFERENCES alpatrade.users(user_id) ON DELETE SET NULL,
    UNIQUE (referrer_id, email)
);
CREATE INDEX IF NOT EXISTS referral_invites_email ON alpatrade.referral_invites(email);
