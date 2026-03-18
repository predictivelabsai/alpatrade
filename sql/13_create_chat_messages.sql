-- Chat persistence: conversations and messages
-- Stores AG-UI chat threads for reload/resume across sessions.

CREATE TABLE IF NOT EXISTS alpatrade.chat_conversations (
    thread_id   UUID PRIMARY KEY,
    user_id     UUID REFERENCES alpatrade.users(user_id) ON DELETE CASCADE,
    title       VARCHAR(200) DEFAULT 'New chat',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_conv_user
    ON alpatrade.chat_conversations(user_id);

CREATE TABLE IF NOT EXISTS alpatrade.chat_messages (
    id          BIGSERIAL PRIMARY KEY,
    thread_id   UUID NOT NULL REFERENCES alpatrade.chat_conversations(thread_id) ON DELETE CASCADE,
    message_id  UUID NOT NULL,
    role        VARCHAR(20) NOT NULL,   -- 'user' or 'assistant'
    content     TEXT NOT NULL DEFAULT '',
    metadata    JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_msg_thread
    ON alpatrade.chat_messages(thread_id, created_at);
