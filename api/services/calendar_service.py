import sys
import os
from typing import List, Dict, Any, Optional
import psycopg2.extras

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.database import db_connection

def get_next_holiday() -> Optional[Dict[str, Any]]:
    """Returns the next upcoming holiday based on the current date."""
    query = """
        SELECT holiday_date, holiday_name, day_of_week, raw_date_text 
        FROM holiday_calendar 
        WHERE holiday_date >= CURRENT_DATE 
        ORDER BY holiday_date ASC 
        LIMIT 1;
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            return cur.fetchone()

def get_upcoming_holidays(limit: int = 5) -> List[Dict[str, Any]]:
    """Returns a list of upcoming holidays."""
    query = """
        SELECT holiday_date, holiday_name, day_of_week, raw_date_text 
        FROM holiday_calendar 
        WHERE holiday_date >= CURRENT_DATE 
        ORDER BY holiday_date ASC 
        LIMIT %s;
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (limit,))
            return cur.fetchall()

def get_all_holidays() -> List[Dict[str, Any]]:
    """Returns a list of all holidays in the database."""
    query = """
        SELECT holiday_date, holiday_name, day_of_week, raw_date_text 
        FROM holiday_calendar 
        ORDER BY holiday_date ASC;
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            return cur.fetchall()

def get_midsem_dates() -> List[Dict[str, Any]]:
    """Returns academic calendar events related to mid-semester exams."""
    query = """
        SELECT event_name, start_date, end_date, raw_date_text, semester_type
        FROM academic_calendar
        WHERE search_vector @@ to_tsquery('english', 'mid:* | mid-sem:* | in-sem:*')
        ORDER BY start_date ASC;
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            res = cur.fetchall()
            # fallback if tsvector fails or syntax differs
            if not res:
                cur.execute("""
                    SELECT event_name, start_date, end_date, raw_date_text, semester_type
                    FROM academic_calendar
                    WHERE event_name ILIKE '%mid%' OR event_name ILIKE '%in-sem%'
                    ORDER BY start_date ASC;
                """)
                res = cur.fetchall()
            return res

def get_endsem_dates() -> List[Dict[str, Any]]:
    """Returns academic calendar events related to end-semester exams."""
    query = """
        SELECT event_name, start_date, end_date, raw_date_text, semester_type
        FROM academic_calendar
        WHERE search_vector @@ to_tsquery('english', 'end:* | end-sem:*')
        ORDER BY start_date ASC;
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            res = cur.fetchall()
            if not res:
                cur.execute("""
                    SELECT event_name, start_date, end_date, raw_date_text, semester_type
                    FROM academic_calendar
                    WHERE event_name ILIKE '%end%' OR event_name ILIKE '%final%'
                    ORDER BY start_date ASC;
                """)
                res = cur.fetchall()
            return res

def get_next_academic_event() -> Optional[Dict[str, Any]]:
    """Returns the next upcoming academic calendar event."""
    query = """
        SELECT event_name, start_date, end_date, raw_date_text, semester_type
        FROM academic_calendar
        WHERE start_date >= CURRENT_DATE OR end_date >= CURRENT_DATE
        ORDER BY start_date ASC
        LIMIT 1;
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            return cur.fetchone()

def search_calendar(query: str, semester: int = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    Full text search across both academic calendar and holidays.
    If semester is provided, odd semesters map to Autumn and even semesters to Winter.
    """
    # format query for tsquery (replace spaces with &)
    parts = [p for p in query.split() if p.strip()]
    if not parts:
        return {"academic_events": [], "holidays": []}
        
    formatted_query = ' & '.join(f"{p}:*" for p in parts)
    
    if semester is not None:
        season = "Autumn" if semester % 2 != 0 else "Winter"
        formatted_query += f" & {season}:*"
        
    academic_query = """
        SELECT event_name, start_date, end_date, raw_date_text, semester_type
        FROM academic_calendar
        WHERE search_vector @@ to_tsquery('english', %s)
        ORDER BY start_date ASC;
    """
    
    holiday_query = """
        SELECT holiday_date, holiday_name, day_of_week, raw_date_text
        FROM holiday_calendar
        WHERE search_vector @@ to_tsquery('english', %s)
        ORDER BY holiday_date ASC;
    """
    
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(academic_query, (formatted_query,))
            academic_results = cur.fetchall()
            
            cur.execute(holiday_query, (formatted_query,))
            holiday_results = cur.fetchall()
            
            return {
                "academic_events": academic_results,
                "holidays": holiday_results
            }
