-- Admin user approval (v0.56.0). Idempotent and lock-light, safe to replay at runtime
-- (engine.approval.ensure_schema runs this file on first use).
--
-- * alpatrade.users.approval_status: pending | approved | rejected.
--   The column is added with a constant DEFAULT 'approved' (metadata-only on PG 11+, no table
--   rewrite), so every EXISTING user reads 'approved' and their live/paper activations are
--   untouched. The default then switches to 'pending', so every NEW sign-up (email, Google,
--   API) starts pending until an admin approves it at /admin/running#approvals.
-- * One-off data step (only in the same transaction that adds the column, never on replay):
--   'Rupam Investment' (shastryinvest@gmail.com) goes back to 'pending' (unknown, bot-like).
-- * alpatrade.app_settings: small key/value store; 'signup_approvers' is the list of emails
--   notified on each sign-up (and allowed to review). Env SIGNUP_APPROVER_EMAILS overrides it.
--
-- Every DDL on alpatrade.users sits inside an existence check, so a replay takes no lock on
-- the table the live runners read. lock_timeout makes the one real ALTER give up rather than
-- queue behind a long transaction (and block readers behind it).
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS alpatrade.app_settings (
    key        VARCHAR(64) PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by UUID
);
INSERT INTO alpatrade.app_settings (key, value)
VALUES ('signup_approvers', '["kaljuvee@gmail.com", "joosep.laats@gmail.com"]'::jsonb)
ON CONFLICT (key) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'alpatrade' AND table_name = 'users'
                     AND column_name = 'approval_status') THEN
        ALTER TABLE alpatrade.users
            ADD COLUMN approval_status     VARCHAR(16) NOT NULL DEFAULT 'approved',
            ADD COLUMN approval_decided_at TIMESTAMPTZ,
            ADD COLUMN approval_decided_by UUID,
            ADD COLUMN signup_method       VARCHAR(16),
            ADD COLUMN signup_ip           VARCHAR(64),
            ADD COLUMN signup_user_agent   VARCHAR(300),
            ADD CONSTRAINT users_approval_status_check
                CHECK (approval_status IN ('pending', 'approved', 'rejected'));
        ALTER TABLE alpatrade.users ALTER COLUMN approval_status SET DEFAULT 'pending';
        UPDATE alpatrade.users SET approval_status = 'pending'
        WHERE lower(email) = 'shastryinvest@gmail.com';
    END IF;
END $$;
