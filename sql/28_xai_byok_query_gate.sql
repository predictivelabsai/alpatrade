-- Per-user xAI credentials and the platform-funded query allowance.
-- Secrets are Fernet-encrypted by the application before they reach PostgreSQL.

CREATE TABLE IF NOT EXISTS alpatrade.user_provider_credentials (
    user_id UUID NOT NULL REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    provider VARCHAR(32) NOT NULL,
    api_key_enc BYTEA NOT NULL,
    api_key_hint VARCHAR(32) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, provider)
);

CREATE TABLE IF NOT EXISTS alpatrade.user_ai_query_allowances (
    user_id UUID PRIMARY KEY REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    platform_queries_used INTEGER NOT NULL DEFAULT 0
        CHECK (platform_queries_used >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

