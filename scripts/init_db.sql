-- Initialize schemas for the medical warehouse
-- This runs automatically when the PostgreSQL container starts

-- Raw schema: stores unmodified scraped data
CREATE SCHEMA IF NOT EXISTS raw;

-- Staging schema: cleaned and typed data (managed by dbt)
CREATE SCHEMA IF NOT EXISTS staging;

-- Marts schema: dimensional star schema (managed by dbt)
CREATE SCHEMA IF NOT EXISTS marts;

-- Raw messages table
CREATE TABLE IF NOT EXISTS raw.telegram_messages (
    id              BIGSERIAL PRIMARY KEY,
    message_id      BIGINT NOT NULL,
    channel_name    VARCHAR(255) NOT NULL,
    message_date    TIMESTAMPTZ,
    message_text    TEXT,
    has_media       BOOLEAN DEFAULT FALSE,
    image_path      TEXT,
    views           INTEGER DEFAULT 0,
    forwards        INTEGER DEFAULT 0,
    scraped_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_raw_messages_channel
    ON raw.telegram_messages(channel_name);

CREATE INDEX IF NOT EXISTS idx_raw_messages_date
    ON raw.telegram_messages(message_date);

CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_messages_unique
    ON raw.telegram_messages(message_id, channel_name);
