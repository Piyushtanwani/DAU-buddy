import sys
import os
import csv
import psycopg2
import psycopg2.extras
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config
from core.database import db_connection

logger = config.get_logger("scripts.seed_library")

def main():
    csv_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "library_data.csv")
    if not os.path.exists(csv_file_path):
        logger.error(f"CSV file not found: {csv_file_path}")
        return

    logger.info("Reading CSV data...")
    records = []
    
    # Create table if not exists
    create_table_query = """
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

    ALTER TABLE library_books
        ADD COLUMN IF NOT EXISTS search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(author_editor, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(description, '')), 'C') ||
            setweight(to_tsvector('english', coalesce(isbn, '')), 'D')
        ) STORED;

    CREATE INDEX IF NOT EXISTS idx_library_books_search_vector
        ON library_books USING GIN (search_vector);

    CREATE INDEX IF NOT EXISTS idx_library_books_acc_no
        ON library_books (acc_no);
    """
    
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(create_table_query)
        logger.info("Checked/Created library_books table.")
    except Exception as e:
        logger.error(f"Failed to create table: {e}")
        return

    # Increase field size limit for large descriptions
    try:
        csv.field_size_limit(sys.maxsize)
    except OverflowError:
        csv.field_size_limit(2147483647)

    with open(csv_file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append((
                row.get("Acc_Date"),
                row.get("Acc_No"),
                row.get("Title"),
                row.get("ISBN"),
                row.get("Author_Editor"),
                row.get("Edition_Volume"),
                row.get("Place_Publisher"),
                row.get("Year"),
                row.get("Pages"),
                row.get("Class_No"),
                row.get("description"),
                row.get("poster_url"),
                row.get("book_url")
            ))

    logger.info(f"Loaded {len(records)} records from CSV.")
    
    if not records:
        logger.info("No records to insert.")
        return

    insert_query = """
        INSERT INTO library_books (
            acc_date, acc_no, title, isbn, author_editor, edition_volume, 
            place_publisher, year, pages, class_no, description, poster_url, book_url
        ) VALUES %s
        ON CONFLICT (acc_no) DO UPDATE SET
            title = EXCLUDED.title,
            isbn = EXCLUDED.isbn,
            author_editor = EXCLUDED.author_editor,
            edition_volume = EXCLUDED.edition_volume,
            place_publisher = EXCLUDED.place_publisher,
            year = EXCLUDED.year,
            pages = EXCLUDED.pages,
            class_no = EXCLUDED.class_no,
            description = EXCLUDED.description,
            poster_url = EXCLUDED.poster_url,
            book_url = EXCLUDED.book_url;
    """

    start_time = time.time()
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    insert_query,
                    records,
                    page_size=1000
                )
        logger.info(f"Successfully seeded {len(records)} books in {time.time() - start_time:.2f} seconds.")
    except Exception as e:
        logger.error(f"Failed to seed library data: {e}")

if __name__ == "__main__":
    main()
