from typing import List, Dict, Optional
from core.database import db_connection

import psycopg2.extras

def get_venue(venue_id: str) -> Optional[Dict]:
    """Retrieve metadata for a single venue."""
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT venue_id, capacity, venue_type, booking_poc
                FROM venues
                WHERE venue_id = %s
            """, (venue_id,))
            row = cur.fetchone()
            if row:
                return dict(row)
    return None

def get_venues_by_ids(venue_ids: List[str]) -> Dict[str, Dict]:
    """Batch fetch metadata for multiple venues to prevent N+1 query issues."""
    if not venue_ids:
        return {}
    
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT venue_id, capacity, venue_type, booking_poc
                FROM venues
                WHERE venue_id = ANY(%s)
            """, (venue_ids,))
            
            result = {}
            for row in cur.fetchall():
                result[row['venue_id']] = dict(row)
            return result

def search_venues_by_capacity(min_capacity: int) -> List[Dict]:
    """Fetch all venues meeting a capacity requirement."""
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT venue_id, capacity, venue_type, booking_poc
                FROM venues
                WHERE capacity >= %s
                ORDER BY capacity ASC
            """, (min_capacity,))
            
            return [dict(row) for row in cur.fetchall()]
