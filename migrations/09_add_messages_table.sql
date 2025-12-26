-- Add messages table to store messages for reaction-based karma changes
CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    user_id INT NOT NULL,
    date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,

    CONSTRAINT messages_chat_fk FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE,
    CONSTRAINT messages_user_fk FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT messages_unique UNIQUE (chat_id, message_id)
);

-- Index for fast lookups by chat_id and message_id
CREATE INDEX idx_messages_chat_message ON messages(chat_id, message_id);

-- Index for cleanup queries (delete old records)
CREATE INDEX idx_messages_date ON messages(date);
