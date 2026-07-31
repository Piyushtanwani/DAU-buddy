from typing import List, Dict, Any
from core.database import db_connection

from api.services.pagination import envelope as _envelope


def get_all_scholars(limit: int = 20, offset: int = 0, status: str = "all") -> Dict[str, Any]:
    status_clause = {
        "current": "WHERE COALESCE(year_of_graduation, '') = ''",
        "graduated": "WHERE COALESCE(year_of_graduation, '') <> ''",
    }.get(status, "")
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT id, name, advisor, thesis_topic, year_of_joining, year_of_graduation,
                       CASE WHEN COALESCE(year_of_graduation, '') = ''
                            THEN 'current' ELSE 'graduated' END AS status,
                       count(*) OVER () AS total
                FROM doctoral_scholars
                {status_clause}
                ORDER BY (COALESCE(year_of_graduation, '') = '') DESC, name ASC
                LIMIT %s OFFSET %s
            """, (limit, offset))
            rows = cur.fetchall()
            total = rows[0][7] if rows else 0
            return _envelope([
                {
                    "id": r[0],
                    "name": r[1],
                    "advisor": r[2],
                    "thesis_topic": r[3],
                    "year_of_joining": r[4],
                    "year_of_graduation": r[5] or None,
                    "status": r[6],
                }
                for r in rows
            ], total, offset)

def search_scholars(query: str, limit: int = 10, status: str = "all", offset: int = 0) -> Dict[str, Any]:
    """Topic/name search over doctoral scholars.

    Current scholars mostly have no thesis_topic/areas_of_research on record yet,
    so a plain full-text search only ever finds alumni. To keep current students
    findable by topic, a scholar also matches when their advisor's faculty
    specialization matches the query (flagged as match_via='advisor').

    status: 'current' | 'graduated' | 'all' (default). Results are always
    current-first and carry an explicit status field.
    """
    clean_query = query.strip()
    if not clean_query:
        return _envelope([], 0, 0)

    status_clause = {
        "current": "AND COALESCE(s.year_of_graduation, '') = ''",
        "graduated": "AND COALESCE(s.year_of_graduation, '') <> ''",
    }.get(status, "")

    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT s.id, s.name, s.advisor, s.thesis_topic, s.year_of_joining,
                       s.year_of_graduation,
                       CASE WHEN COALESCE(s.year_of_graduation, '') = ''
                            THEN 'current' ELSE 'graduated' END AS status,
                       s.search_vector @@ websearch_to_tsquery('english', %s) AS direct_match,
                       count(*) OVER () AS total
                FROM doctoral_scholars s
                WHERE (
                    s.search_vector @@ websearch_to_tsquery('english', %s)
                    OR EXISTS (
                        SELECT 1 FROM faculty f
                        WHERE f.specialization ILIKE %s
                          AND s.advisor ILIKE '%%' || f.name || '%%'
                    )
                ) {status_clause}
                ORDER BY (COALESCE(s.year_of_graduation, '') = '') DESC,
                         direct_match DESC,
                         ts_rank(s.search_vector, websearch_to_tsquery('english', %s)) DESC
                LIMIT %s OFFSET %s
            """, (clean_query, clean_query, f"%{clean_query}%", clean_query, limit, offset))
            rows = cur.fetchall()
            total = rows[0][8] if rows else 0
            return _envelope([
                {
                    "id": r[0],
                    "name": r[1],
                    "advisor": r[2],
                    "thesis_topic": r[3],
                    "year_of_joining": r[4],
                    "year_of_graduation": r[5] or None,
                    "status": r[6],
                    "match_via": "direct" if r[7] else "advisor_specialization",
                }
                for r in rows
            ], total, offset)

def get_scholar_by_id(scholar_id) -> Dict[str, Any]:
    """Fetch one scholar by numeric id, or by name when callers (LLM tool calls)
    pass a name instead of an id — never feed a non-integer into the id column."""
    ident = str(scholar_id).strip()
    if ident.isdigit():
        where, param = "id = %s", int(ident)
    else:
        where, param = "name ILIKE %s", f"%{ident}%"
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT id, name, image_url, year_of_joining, year_of_graduation,
                       advisor, thesis_topic, areas_of_research, publications,
                       awards, post_phd_employment, personal_webpage, scraped_at
                FROM doctoral_scholars
                WHERE {where}
                ORDER BY id
                LIMIT 1
            """, (param,))
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
