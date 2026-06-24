-- Run this in your Neon SQL editor at console.neon.tech
-- Creates the api_keys table for the DAU Buddy portal

CREATE TABLE IF NOT EXISTS api_keys (
    email       VARCHAR(255) PRIMARY KEY,
    hashed_key  VARCHAR(255) NOT NULL,
    role        VARCHAR(50)  DEFAULT 'User',
    created_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    last_used   TIMESTAMP,
    status      VARCHAR(20)  DEFAULT 'Active'
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hashed ON api_keys (hashed_key);

-- Verify
SELECT 'api_keys table created successfully' AS result;
