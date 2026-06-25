from typing import List, Dict, Any
from core.database import db_connection

def get_all_scholars(limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, advisor, thesis_topic, year_of_joining FROM doctoral_scholars ORDER BY name ASC LIMIT %s OFFSET %s",
                (limit, offset)
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "advisor": r[2],
                    "thesis_topic": r[3],
                    "year_of_joining": r[4]
                }
                for r in rows
            ]

def search_scholars(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    clean_query = query.strip()
    if not clean_query:
        return []
        
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, advisor, thesis_topic, year_of_joining
                FROM doctoral_scholars
                WHERE search_vector @@ websearch_to_tsquery('english', %s)
                ORDER BY ts_rank(search_vector, websearch_to_tsquery('english', %s)) DESC
                LIMIT %s
            """, (clean_query, clean_query, limit))
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "advisor": r[2],
                    "thesis_topic": r[3],
                    "year_of_joining": r[4]
                }
                for r in rows
            ]

def get_scholar_by_id(scholar_id: int) -> Dict[str, Any]:
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, image_url, year_of_joining, year_of_graduation, 
                       advisor, thesis_topic, areas_of_research, publications, 
                       awards, post_phd_employment, personal_webpage, scraped_at
                FROM doctoral_scholars 
                WHERE id = %s
            """, (scholar_id,))
            row = cur.fetchone()
            if not row:
                return {}
                
            return {
                "id": row[0],
                "name": row[1],
                "image_url": row[2],
                "year_of_joining": row[3],
                "year_of_graduation": row[4],
                "advisor": row[5],
                "thesis_topic": row[6],
                "areas_of_research": row[7],
                "publications": row[8],
                "awards": row[9],
                "post_phd_employment": row[10],
                "personal_webpage": row[11],
                "scraped_at": str(row[12])
            }
