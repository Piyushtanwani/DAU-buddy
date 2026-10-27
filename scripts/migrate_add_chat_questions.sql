-- =============================================================================
-- Migration: Add chat_questions table
-- Run on existing databases that were created before this table was added:
--   psql -U postgres -d <db_name> -f scripts/migrate_add_chat_questions.sql
-- =============================================================================

CREATE TABLE IF NOT EXISTS chat_questions (
    id            SERIAL PRIMARY KEY,
    question      TEXT NOT NULL,
    caller_role   VARCHAR(50) NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT date_trunc('day', CURRENT_TIMESTAMP)
);

-- Day only, so rows can't be matched by time to mcp_analytics (which has the email)
ALTER TABLE chat_questions
    ALTER COLUMN created_at SET DEFAULT date_trunc('day', CURRENT_TIMESTAMP);

-- Questions may contain typed personal details: grant SELECT to maintainers only

CREATE INDEX IF NOT EXISTS idx_chat_questions_role
    ON chat_questions (caller_role);

CREATE INDEX IF NOT EXISTS idx_chat_questions_created
    ON chat_questions (created_at);
