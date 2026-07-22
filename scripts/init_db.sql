-- =============================================================================
-- DA-IICT Faculty & Staff AI Buddy — PostgreSQL Initialisation Script
-- =============================================================================
-- Run as the postgres superuser:
--   psql -U postgres -f scripts/init_db.sql
-- =============================================================================



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
-- Academic Calendar Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS academic_calendar (
    id              SERIAL PRIMARY KEY,
    event_name      TEXT NOT NULL,
    start_date      DATE,
    end_date        DATE,
    raw_date_text   TEXT,
    semester_type   VARCHAR(100),
    description     TEXT,
    source_url      TEXT,
    scraped_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Generated tsvector column for full-text search (PostgreSQL 12+)
ALTER TABLE academic_calendar
    ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(event_name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(description, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(semester_type, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(raw_date_text, '')), 'D')
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_academic_calendar_search_vector
    ON academic_calendar USING GIN (search_vector);


-- =============================================================================
-- Holiday Calendar Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS holiday_calendar (
    id              SERIAL PRIMARY KEY,
    holiday_date    DATE,
    holiday_name    VARCHAR(255) NOT NULL,
    day_of_week     VARCHAR(50),
    raw_date_text   TEXT,
    scraped_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE holiday_calendar
    ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(holiday_name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(day_of_week, '')), 'B')
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_holiday_calendar_search_vector
    ON holiday_calendar USING GIN (search_vector);

-- =============================================================================
-- API Keys Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS api_keys (
    email VARCHAR(255) PRIMARY KEY,
    key_prefix VARCHAR(14),
    hashed_key VARCHAR(255) NOT NULL,
    role VARCHAR(50) DEFAULT 'User',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP,
    last_client VARCHAR(255),
    status VARCHAR(20) DEFAULT 'Active',
    expires_at TIMESTAMP
);

-- Add expires_at column if the table already existed without it
ALTER TABLE api_keys
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;

ALTER TABLE api_keys 
    ADD COLUMN IF NOT EXISTS key_prefix VARCHAR(14);

ALTER TABLE api_keys 
    ADD COLUMN IF NOT EXISTS last_client VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(key_prefix);
CREATE INDEX IF NOT EXISTS idx_api_keys_hashed ON api_keys (hashed_key);

-- =============================================================================
-- Doctoral Scholars Table
-- =============================================================================

CREATE TABLE IF NOT EXISTS doctoral_scholars (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    image_url       TEXT,
    year_of_joining VARCHAR(100),
    year_of_graduation VARCHAR(100),
    advisor         VARCHAR(255),
    thesis_topic    TEXT,
    areas_of_research TEXT,
    publications    TEXT,
    awards          TEXT,
    post_phd_employment TEXT,
    personal_webpage TEXT,
    scraped_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE doctoral_scholars
    ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(advisor, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(thesis_topic, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(areas_of_research, '')), 'D')
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_doctoral_scholars_search_vector
    ON doctoral_scholars USING GIN (search_vector);

-- =============================================================================
-- Feedback Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    category VARCHAR(100) NOT NULL,
    priority VARCHAR(20) DEFAULT 'Medium',
    subject TEXT NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(30) DEFAULT 'Open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- =============================================================================
-- MCP Analytics Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS mcp_analytics (
    id SERIAL PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    client_name VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_analytics_email ON mcp_analytics(user_email);
CREATE INDEX IF NOT EXISTS idx_analytics_tool ON mcp_analytics(tool_name);

-- =============================================================================
-- Generic Document Retrieval Framework Tables
-- =============================================================================

CREATE TABLE IF NOT EXISTS documents (
    id              SERIAL PRIMARY KEY,
    collection      VARCHAR(100) NOT NULL,
    filename        TEXT NOT NULL,
    title           TEXT,
    url             TEXT NOT NULL,
    degree          VARCHAR(100),
    program         VARCHAR(255),
    effective_year  VARCHAR(50),
    version         VARCHAR(50),
    is_latest       BOOLEAN DEFAULT false,
    last_modified   TIMESTAMP,
    synced_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    page_count      INT,
    checksum        VARCHAR(64),
    status          VARCHAR(50) DEFAULT 'active',
    UNIQUE (collection, filename)
);

CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents(collection);
CREATE INDEX IF NOT EXISTS idx_documents_program ON documents(program);

CREATE TABLE IF NOT EXISTS document_chunks (
    id              SERIAL PRIMARY KEY,
    document_id     INT REFERENCES documents(id) ON DELETE CASCADE,
    page            INT,
    section_heading TEXT,
    chunk_index     INT NOT NULL,
    content         TEXT NOT NULL,
    search_vector   tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_search_vector
    ON document_chunks USING GIN (search_vector);

-- =============================================================================
-- Timetables Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS timetables (
    id             SERIAL PRIMARY KEY,
    
    -- Program Information
    program        VARCHAR(100),
    semester       VARCHAR(20),
    
    -- Session Information
    session_type   VARCHAR(50),
    -- Course Information
    course_code    VARCHAR(100),
    course_name    VARCHAR(255),
    course_type    VARCHAR(100),

    -- Faculty Information
    faculty_name   VARCHAR(255),

    -- Schedule Information
    day_of_week    VARCHAR(20),
    start_time     TIME,
    end_time       TIME,

    -- Venue Information
    room           VARCHAR(255),

    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE timetables
    ADD COLUMN IF NOT EXISTS course_type VARCHAR(100);

ALTER TABLE timetables
    ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(course_code, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(course_name, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(faculty_name, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(room, '')), 'D')
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_timetables_search_vector ON timetables USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_timetables_faculty ON timetables (faculty_name, day_of_week);
CREATE INDEX IF NOT EXISTS idx_timetables_course ON timetables (course_code, day_of_week);
