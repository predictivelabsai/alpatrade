-- 11_add_user_accounts.sql
-- Adds support for multiple Alpaca accounts per user.

-- 1. Create the user_accounts table
CREATE TABLE IF NOT EXISTS alpatrade.user_accounts (
    id SERIAL PRIMARY KEY,
    account_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    account_name VARCHAR(255) NOT NULL DEFAULT 'Default Account',
    alpaca_api_key_enc BYTEA,
    alpaca_secret_key_enc BYTEA,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_accounts_user_id ON alpatrade.user_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_user_accounts_account_id ON alpatrade.user_accounts(account_id);

-- 2. Migrate existing keys from users table to user_accounts
INSERT INTO alpatrade.user_accounts (user_id, account_name, alpaca_api_key_enc, alpaca_secret_key_enc)
SELECT 
    user_id, 
    'Default Account', 
    alpaca_api_key_enc, 
    alpaca_secret_key_enc
FROM alpatrade.users
WHERE alpaca_api_key_enc IS NOT NULL AND alpaca_secret_key_enc IS NOT NULL
ON CONFLICT DO NOTHING;

-- 3. Add account_id to runs, trades, positions, pnl_summary, etc.
ALTER TABLE alpatrade.runs ADD COLUMN IF NOT EXISTS account_id UUID REFERENCES alpatrade.user_accounts(account_id) ON DELETE SET NULL;
ALTER TABLE alpatrade.trades ADD COLUMN IF NOT EXISTS account_id UUID REFERENCES alpatrade.user_accounts(account_id) ON DELETE SET NULL;
ALTER TABLE alpatrade.positions ADD COLUMN IF NOT EXISTS account_id UUID REFERENCES alpatrade.user_accounts(account_id) ON DELETE SET NULL;
ALTER TABLE alpatrade.pnl_summary ADD COLUMN IF NOT EXISTS account_id UUID REFERENCES alpatrade.user_accounts(account_id) ON DELETE SET NULL;

-- 4. Update existing records to link to the migrated default account for each user
UPDATE alpatrade.runs r
SET account_id = (SELECT account_id FROM alpatrade.user_accounts ua WHERE ua.user_id = r.user_id LIMIT 1)
WHERE account_id IS NULL AND user_id IS NOT NULL;

UPDATE alpatrade.trades t
SET account_id = (SELECT account_id FROM alpatrade.user_accounts ua WHERE ua.user_id = t.user_id LIMIT 1)
WHERE account_id IS NULL AND user_id IS NOT NULL;

UPDATE alpatrade.positions p
SET account_id = (SELECT account_id FROM alpatrade.user_accounts ua WHERE ua.user_id = p.user_id LIMIT 1)
WHERE account_id IS NULL AND user_id IS NOT NULL;

UPDATE alpatrade.pnl_summary ps
SET account_id = (SELECT account_id FROM alpatrade.user_accounts ua WHERE ua.user_id = ps.user_id LIMIT 1)
WHERE account_id IS NULL AND user_id IS NOT NULL;

-- 5. Drop the old columns from users (OPTIONAL, but recommended once verified)
-- ALTER TABLE alpatrade.users DROP COLUMN alpaca_api_key_enc;
-- ALTER TABLE alpatrade.users DROP COLUMN alpaca_secret_key_enc;
