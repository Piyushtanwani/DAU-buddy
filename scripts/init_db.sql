-- =============================================================================
-- DA-IICT Faculty & Staff AI Buddy — PostgreSQL Initialisation Script
-- =============================================================================
-- Run as the postgres superuser:
--   psql -U postgres -f scripts/init_db.sql
-- =============================================================================

-- 1. Create the database (idempotent via DO block)
SELECT 'CREATE DATABASE daiict_db'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'daiict_db'
)\gexec

-- 2. Connect to the new database
\connect daiict_db

-- =============================================================================
-- Faculty Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS faculty (
    id             SERIAL PRIMARY KEY,
    name           VARCHAR(255) NOT NULL,
    profile_url    TEXT,
    image_url      TEXT,
    education      TEXT,
    phone          VARCHAR(100),
    address        TEXT,
    email          VARCHAR(255),
    specialization TEXT,
    faculty_type   VARCHAR(50)  NOT NULL DEFAULT 'Regular',
    scraped_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Add faculty_type column if the table already existed without it
ALTER TABLE faculty
    ADD COLUMN IF NOT EXISTS faculty_type VARCHAR(50) NOT NULL DEFAULT 'Regular';

-- Generated tsvector column for full-text search (PostgreSQL 12+)
ALTER TABLE faculty
    ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(name,           '')), 'A') ||
        setweight(to_tsvector('english', coalesce(specialization, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(education,      '')), 'C') ||
        setweight(to_tsvector('english', coalesce(email,          '')), 'D')
    ) STORED;

-- GIN index for fast full-text searches
CREATE INDEX IF NOT EXISTS idx_faculty_search_vector
    ON faculty USING GIN (search_vector);

-- Optional: index on email for direct lookups
CREATE INDEX IF NOT EXISTS idx_faculty_email
    ON faculty (email);

-- =============================================================================
-- Staff Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS staff (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(255) NOT NULL,
    profile_url   TEXT,
    image_url     TEXT,
    designation   VARCHAR(255),
    qualification TEXT,
    phone         VARCHAR(100),
    address       TEXT,
    email         VARCHAR(255),
    scraped_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Generated tsvector column for full-text search (PostgreSQL 12+)
ALTER TABLE staff
    ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(name,          '')), 'A') ||
        setweight(to_tsvector('english', coalesce(designation,   '')), 'B') ||
        setweight(to_tsvector('english', coalesce(qualification, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(email,         '')), 'D')
    ) STORED;

-- GIN index for fast full-text searches
CREATE INDEX IF NOT EXISTS idx_staff_search_vector
    ON staff USING GIN (search_vector);

-- Optional: index on email for direct lookups
CREATE INDEX IF NOT EXISTS idx_staff_email
    ON staff (email);

-- =============================================================================
-- Library Books Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS library_books (
    id              SERIAL PRIMARY KEY,
    acc_date        VARCHAR(50),
    acc_no          VARCHAR(50) UNIQUE,
    title           TEXT,
    isbn            VARCHAR(255),
    author_editor   TEXT,
    edition_volume  VARCHAR(255),
    place_publisher TEXT,
    year            VARCHAR(50),
    pages           VARCHAR(100),
    class_no        VARCHAR(100),
    description     TEXT,
    poster_url      TEXT,
    book_url        TEXT,
    scraped_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Generated tsvector column for full-text search (PostgreSQL 12+)
ALTER TABLE library_books
    ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(author_editor, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(description, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(isbn, '')), 'D')
    ) STORED;

-- GIN index for fast full-text searches
CREATE INDEX IF NOT EXISTS idx_library_books_search_vector
    ON library_books USING GIN (search_vector);

-- Optional: index on acc_no for direct lookups
CREATE INDEX IF NOT EXISTS idx_library_books_acc_no
    ON library_books (acc_no);

-- =============================================================================
-- Done
-- =============================================================================
\echo '✅  daiict_db initialised successfully (faculty + staff + library tables ready).'
