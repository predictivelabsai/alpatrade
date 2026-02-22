-- AlpaTrade user management
-- Stores user accounts with encrypted Alpaca credentials.

CREATE TABLE IF NOT EXISTS alpatrade.users (
    id SERIAL PRIMARY KEY,
    user_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),          -- nullable for Google-only users
    google_id VARCHAR(255) UNIQUE,       -- nullable for email-only users
    alpaca_api_key_enc BYTEA,            -- Fernet-encrypted
    alpaca_secret_key_enc BYTEA,         -- Fernet-encrypted
    display_name VARCHAR(255),
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_user_id ON alpatrade.users(user_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON alpatrade.users(email);
CREATE INDEX IF NOT EXISTS idx_users_google_id ON alpatrade.users(google_id);
