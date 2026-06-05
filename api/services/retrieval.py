"""
Retrieval Service
=================
Handles retrieval-augmented generation (RAG) queries to fetch the most
relevant records from the database instead of loading the entire context.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any

from core import config
from core.database import db_connection

logger = config.get_logger("api.services.retrieval")

class BaseRetriever(ABC):
    """Abstract interface for retrieving records from the database."""

    @abstractmethod
    def retrieve_faculty(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve the top `limit` relevant faculty records for the given query."""
        pass

    @abstractmethod
    def retrieve_staff(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve the top `limit` relevant staff records for the given query."""
        pass


class PostgresFullTextRetriever(BaseRetriever):
    """Retrieves records using PostgreSQL native full-text search (TSVECTOR)."""

    def retrieve_faculty(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not query.strip():
            return []

        # Convert natural language to tsquery replacing spaces with logical ORs
        # websearch_to_tsquery natively handles ' OR ' syntax.
        import re
        tokens = [t for t in re.split(r'\W+', query) if t]
        if not tokens:
            return []
        or_query = " OR ".join(tokens)

        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT name, faculty_type, email, phone, address, 
                               education, specialization, profile_url,
                               ts_rank(search_vector, websearch_to_tsquery('english', %s)) AS rank
                        FROM faculty
                        WHERE search_vector @@ websearch_to_tsquery('english', %s)
                        ORDER BY rank DESC
                        LIMIT %s;
                    """, (or_query, or_query, limit))
                    
                    rows = cursor.fetchall()
                    logger.info(f"Retrieved {len(rows)} faculty records for query: '{query}'")
                    
                    results = []
                    for row in rows:
                        results.append({
                            "name": row[0],
                            "faculty_type": row[1],
                            "email": row[2],
                            "phone": row[3],
                            "address": row[4],
                            "education": row[5],
                            "specialization": row[6],
                            "profile_url": row[7],
                            "relevance_score": row[8]
                        })
                    return results
        except Exception as e:
            logger.error(f"Error in retrieve_faculty: {e}")
            return []


    def retrieve_staff(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not query.strip():
            return []

        import re
        tokens = [t for t in re.split(r'\W+', query) if t]
        if not tokens:
            return []
        or_query = " OR ".join(tokens)

        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT name, designation, email, phone, address, 
                               qualification, profile_url,
                               ts_rank(search_vector, websearch_to_tsquery('english', %s)) AS rank
                        FROM staff
                        WHERE search_vector @@ websearch_to_tsquery('english', %s)
                        ORDER BY rank DESC
                        LIMIT %s;
                    """, (or_query, or_query, limit))
                    
                    rows = cursor.fetchall()
                    logger.info(f"Retrieved {len(rows)} staff records for query: '{query}'")
                    
                    results = []
                    for row in rows:
                        results.append({
                            "name": row[0],
                            "designation": row[1],
                            "email": row[2],
                            "phone": row[3],
                            "address": row[4],
                            "qualification": row[5],
                            "profile_url": row[6],
                            "relevance_score": row[7]
                        })
                    return results
        except Exception as e:
            logger.error(f"Error in retrieve_staff: {e}")
            return []
