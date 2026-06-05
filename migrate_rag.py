import os
import sys
from psycopg2 import sql
import logging

# Ensure we can import from core
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core import config
from core.database import db_connection

logger = config.get_logger("migrate_rag")

def migrate_database():
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                logger.info("Starting PostgreSQL RAG Database Migration...")

                # 1. Add generated TSVECTOR column to faculty table
                logger.info("Adding search_vector to faculty table...")
                cursor.execute("""
                    ALTER TABLE faculty
                    ADD COLUMN IF NOT EXISTS search_vector tsvector
                    GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
                        setweight(to_tsvector('english', coalesce(specialization, '')), 'B') ||
                        setweight(to_tsvector('english', coalesce(education, '')), 'C') ||
                        setweight(to_tsvector('english', coalesce(email, '')), 'D')
                    ) STORED;
                """)

                # 2. Add GIN index to faculty table
                logger.info("Creating GIN index for faculty search_vector...")
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_faculty_search_vector 
                    ON faculty USING GIN (search_vector);
                """)

                # 3. Add generated TSVECTOR column to staff table
                logger.info("Adding search_vector to staff table...")
                cursor.execute("""
                    ALTER TABLE staff
                    ADD COLUMN IF NOT EXISTS search_vector tsvector
                    GENERATED ALWAYS AS (
                        setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
                        setweight(to_tsvector('english', coalesce(designation, '')), 'B') ||
                        setweight(to_tsvector('english', coalesce(qualification, '')), 'C') ||
                        setweight(to_tsvector('english', coalesce(email, '')), 'D')
                    ) STORED;
                """)

                # 4. Add GIN index to staff table
                logger.info("Creating GIN index for staff search_vector...")
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_staff_search_vector 
                    ON staff USING GIN (search_vector);
                """)

                logger.info("Migration completed successfully!")
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise

if __name__ == "__main__":
    migrate_database()
