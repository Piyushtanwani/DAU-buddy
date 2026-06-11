"""
Library Service
===============
A local database client for DA-IICT library data.
"""
import logging
from typing import Any
import psycopg2
from psycopg2.extras import RealDictCursor

from core import config
from core.database import db_connection

logger = config.get_logger("api.services.library_service")

class LibraryService:
    """
    Stateless client querying the local PostgreSQL library_books table.
    """

    def __init__(self) -> None:
        pass

    async def search_books(self, query: str, limit: int = 10) -> list[dict]:
        """
        Search the local library database for books matching *query*.

        Parameters
        ----------
        query:
            The search string.
        limit:
            Maximum number of results to return (default 10).

        Returns
        -------
        A list of book-summary dicts.
        """
        if not query or not query.strip():
            raise ValueError("search query must not be empty")
        if len(query.strip()) < 2:
            raise ValueError("search query must be at least 2 characters")

        books = []
        try:
            with db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Parse the search string to a tsquery
                    words = [w for w in query.strip().split() if w]
                    tsquery = " & ".join([f"{w}:*" for w in words])
                    
                    sql = """
                        SELECT acc_no, title, author_editor, place_publisher, year, isbn, description, poster_url, book_url
                        FROM library_books
                        WHERE search_vector @@ to_tsquery('english', %s)
                        ORDER BY ts_rank(search_vector, to_tsquery('english', %s)) DESC
                        LIMIT %s
                    """
                    cur.execute(sql, (tsquery, tsquery, limit))
                    rows = cur.fetchall()

                    for r in rows:
                        opac_link = f"https://opac.daiict.ac.in/cgi-bin/koha/opac-search.pl?q={r['isbn'] or r['title']}"
                        books.append({
                            "title": r["title"] or "",
                            "link": opac_link,
                            "biblionumber": r["acc_no"] or "",
                            "author": r["author_editor"] or "",
                            "publisher": r["place_publisher"] or "",
                            "year": r["year"] or "",
                            "isbn": r["isbn"] or "",
                        })
        except Exception as e:
            logger.error(f"Failed to search books: {e}")
            raise

        logger.info(f"Local DB search returned {len(books)} results for query={query!r}")
        return books

    async def get_book_details(self, biblionumber: str) -> dict:
        """
        Fetch the full catalog record for a single book by Acc_No.

        Parameters
        ----------
        biblionumber:
            The Acc_No representing the book in the local DB.

        Returns
        -------
        A dict with the book's details. Holdings and availability
        are omitted; an OPAC link is provided instead.
        """
        if not biblionumber or not str(biblionumber).strip():
            raise ValueError("biblionumber must not be empty")

        try:
            with db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    sql = """
                        SELECT * FROM library_books
                        WHERE acc_no = %s
                    """
                    cur.execute(sql, (str(biblionumber).strip(),))
                    row = cur.fetchone()

                    if not row:
                        return {"error": "Book not found."}

                    # Provide an OPAC search link for the user to verify real-time availability
                    opac_link = f"https://opac.daiict.ac.in/cgi-bin/koha/opac-search.pl?q={row['isbn'] or row['title']}"

                    result = {
                        "biblionumber": row["acc_no"] or "",
                        "title": row["title"] or "",
                        "author": row["author_editor"] or "",
                        "publisher": row["place_publisher"] or "",
                        "year": row["year"] or "",
                        "isbn": row["isbn"] or "",
                        "subjects": [],
                        "description": row["description"] or "",
                        "class_no": row["class_no"] or "",
                        "pages": row["pages"] or "",
                        "edition_volume": row["edition_volume"] or "",
                        "poster_url": row["poster_url"] or "",
                        "book_url": row["book_url"] or "",
                        "opac_availability_link": opac_link,
                        "holdings": [],
                        "total_copies": 1,
                        "available_copies": 1,
                    }
                    
                    logger.info(f"Fetched local book detail for {biblionumber}")
                    return result

        except Exception as e:
            logger.error(f"Failed to get book details: {e}")
            raise
