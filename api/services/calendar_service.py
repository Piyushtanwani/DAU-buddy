import re
import sys
import os
from datetime import date as _date
from typing import List, Dict, Any, Optional
import psycopg2.extras

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core import config
from core.database import db_connection

logger = config.get_logger("api.services.calendar_service")

# The academic calendar reassigns the weekday of individual dates to make up for
# holidays — e.g. "To be treated as Tuesday" on Friday 07-08-2026. On such a day
# the campus runs another day's timetable, so every schedule lookup that keys off
# the real weekday is wrong. Six such dates exist across the loaded terms.
_DAY_SUBSTITUTION_RE = re.compile(
    r"treated\s+as\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
    re.IGNORECASE,
)


def _parse_day_substitution(event_names: List[str]) -> Optional[str]:
    """First 'treated as <weekday>' found in these event names, capitalised."""
    for name in event_names:
        match = _DAY_SUBSTITUTION_RE.search(name or "")
        if match:
            return match.group(1).capitalize()
    return None


def get_day_substitution(date_str: str) -> Optional[str]:
    """
    The weekday `date_str` (YYYY-MM-DD) is treated as per the academic calendar,
    or None when it runs as its real weekday.
    """
    query = """
        SELECT event_name
        FROM academic_calendar
        WHERE %s >= start_date AND %s <= end_date;
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (date_str, date_str))
                return _parse_day_substitution([r[0] for r in cur.fetchall()])
    except Exception as e:
        # Never let a calendar lookup break a schedule answer: degrade to the
        # real weekday rather than failing the whole query.
        logger.error(f"Day-substitution lookup failed for {date_str}: {e}")
        return None


def effective_day(on_date: Optional[_date] = None) -> tuple[str, Optional[str]]:
    """
    The weekday the campus actually runs on `on_date` (default: today).

    Returns (effective_day, substituted_from). `substituted_from` is None on a
    normal day, and the real weekday when the calendar overrides it — callers
    need it to explain themselves ("Friday, treated as Tuesday").
    """
    on_date = on_date or config.campus_now().date()
    real_day = on_date.strftime("%A")
    substitute = get_day_substitution(on_date.strftime("%Y-%m-%d"))
    if substitute and substitute != real_day:
        return substitute, real_day
    return real_day, None

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

def get_events_by_date(date_str: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Finds academic events or holidays that fall on a specific date (YYYY-MM-DD).
    """
    academic_query = """
        SELECT event_name, start_date, end_date, raw_date_text, semester_type
        FROM academic_calendar
        WHERE %s >= start_date AND %s <= end_date
        ORDER BY start_date ASC;
    """
    
    holiday_query = """
        SELECT holiday_date, holiday_name, day_of_week, raw_date_text
        FROM holiday_calendar
        WHERE holiday_date = %s
        ORDER BY holiday_date ASC;
    """
    
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(academic_query, (date_str, date_str))
            academic_results = cur.fetchall()
            
            cur.execute(holiday_query, (date_str,))
            holiday_results = cur.fetchall()
            
    return {
        "academic_events": academic_results,
        "holidays": holiday_results
    }
