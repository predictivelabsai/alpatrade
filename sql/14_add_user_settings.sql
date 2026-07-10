-- 14_add_user_settings.sql
-- Per-user preferences for the model / data / search / agent providers.
-- These live in the DB (not just .env) because the web app and the REST API run
-- in separate processes and must resolve the same effective settings per user.
-- Alpaca BYOK keys already live in alpatrade.user_accounts (Fernet-encrypted).

CREATE TABLE IF NOT EXISTS alpatrade.user_settings (
    user_id UUID PRIMARY KEY REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    model_provider       VARCHAR(64),   -- xai | openai | anthropic
    model_name           VARCHAR(128),  -- e.g. grok-4.3
    market_data_provider VARCHAR(64),   -- massive | eodhd
    search_provider      VARCHAR(64),   -- tavily | exa
    agent_framework      VARCHAR(64),   -- langgraph | hermes | deepagents
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
