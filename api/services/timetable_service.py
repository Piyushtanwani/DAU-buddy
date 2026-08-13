import sys
import os
from typing import List, Dict, Any, Optional
import psycopg2.extras

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.database import db_connection
from api.services import venue_service

DAY_ORDER_SQL = """
    CASE day_of_week
        WHEN 'Monday' THEN 1
        WHEN 'Tuesday' THEN 2
        WHEN 'Wednesday' THEN 3
        WHEN 'Thursday' THEN 4
        WHEN 'Friday' THEN 5
        WHEN 'Saturday' THEN 6
        WHEN 'Sunday' THEN 7
        -- Unknown/malformed day values sort first so bad data is visible
        -- rather than silently blending in with the weekend.
        ELSE 0
    END
"""


def resolve_faculty(faculty_name: str) -> List[str]:
    """Return distinct faculty_name values matching the query.

    Used to detect ambiguous matches (e.g. 'Jat' hitting both 'P M Jat' and
    'H S Jattana') before running schedule queries against a blended result.
    """
    query = "SELECT DISTINCT faculty_name FROM timetables WHERE faculty_name ILIKE %s ORDER BY faculty_name"
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (f"%{faculty_name}%",))
            matches = [r[0] for r in cur.fetchall()]

    # An exact (case-insensitive) hit wins even when it is also a substring of
    # longer rows. Without this, picking one of the candidates we just offered
    # narrows nothing and the caller re-asks forever.
    needle = faculty_name.strip().casefold()
    exact = [m for m in matches if m.casefold() == needle]
    return exact or matches


DAY_START = "08:00"
DAY_END = "18:00"


def _hhmm(t) -> str:
    return t.strftime("%H:%M") if hasattr(t, "strftime") else str(t)[:5]


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def compute_free_slots(busy_rows: List[Dict[str, Any]], min_minutes: int = 0) -> List[str]:
    """Merge busy intervals, return free 'HH:MM-HH:MM' gaps within the campus day.

    min_minutes drops gaps too short to be useful (e.g. 10-min class changeovers).
    Shared by the MCP tools and the web-chat (Gemini/OpenAI) tool wrappers so
    free/busy inversion never has to happen inside a model.
    """
    slots = []
    current = DAY_START
    for row in sorted(busy_rows, key=lambda r: _hhmm(r["start_time"])):
        start, end = _hhmm(row["start_time"]), _hhmm(row["end_time"])
        if current < start and _minutes(start) - _minutes(current) >= min_minutes:
            slots.append(f"{current}-{start}")
        current = max(current, end)
    if current < DAY_END and _minutes(DAY_END) - _minutes(current) >= min_minutes:
        slots.append(f"{current}-{DAY_END}")
    return slots


def resolve_single(faculty_name: str) -> tuple[Optional[str], List[str]]:
    """Resolve a query to exactly one faculty.

    Returns (name, matches): name is set only on an unambiguous match;
    matches is the full candidate list (empty = no match at all).
    """
    matches = resolve_faculty(faculty_name)
    return (matches[0] if len(matches) == 1 else None), matches


def get_free_time(faculty_name: str, day: str, min_minutes: int = 20) -> Dict[str, Any]:
    """Free meeting windows for one faculty on a day.

    Returns {faculty, day, free_slots, busy_slots} on success, or
    {query, candidates} when the name is missing/ambiguous. Callers format;
    all free/busy semantics live here so no model ever has to invert them.
    """
    name, matches = resolve_single(faculty_name)
    if not name:
        return {"query": faculty_name, "candidates": matches}
    busy = get_busy_slots(name, day)
    return {
        "faculty": name,
        "day": day,
        "free_slots": compute_free_slots(busy, min_minutes),
        "busy_slots": [f"{_hhmm(b['start_time'])}-{_hhmm(b['end_time'])}" for b in busy],
    }


def get_common_free_time(faculty_names: List[str], day: str, min_minutes: int = 20) -> Dict[str, Any]:
    """Common free windows when ALL listed faculty can meet on a day.

    Same contract as get_free_time; resolution failure of any name returns
    {query, candidates} for that name.
    """
    resolved, all_busy = [], []
    for fname in faculty_names:
        name, matches = resolve_single(fname)
        if not name:
            return {"query": fname, "candidates": matches}
        resolved.append(name)
        all_busy.extend(get_busy_slots(name, day))
    return {
        "faculty": resolved,
        "day": day,
        "free_slots": compute_free_slots(all_busy, min_minutes),
    }


def get_faculty_location(faculty_name: str, day: str, time: str) -> Optional[Dict[str, Any]]:
    query = """
        SELECT session_type, course_code, course_name, room, start_time, end_time,
               array_agg(DISTINCT program) AS programs
        FROM timetables
        WHERE faculty_name ILIKE %s
          AND day_of_week ILIKE %s
          AND start_time <= %s::TIME
          AND end_time > %s::TIME
        GROUP BY session_type, course_code, course_name, room, start_time, end_time
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (f"%{faculty_name}%", f"%{day}%", time, time))
            return cur.fetchone()


def get_faculty_schedule(faculty_name: str, day: Optional[str] = None) -> List[Dict[str, Any]]:
    """One row per teaching slot; enrolled programs aggregated into `programs`."""
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            base = f"""
                SELECT day_of_week, start_time, end_time, session_type, course_code, room,
                       array_agg(DISTINCT program) AS programs
                FROM timetables
                WHERE faculty_name ILIKE %s {{day_clause}}
                GROUP BY day_of_week, start_time, end_time, session_type, course_code, room
                ORDER BY {DAY_ORDER_SQL}, start_time
            """
            if day:
                cur.execute(base.format(day_clause="AND day_of_week ILIKE %s"),
                            (f"%{faculty_name}%", f"%{day}%"))
            else:
                cur.execute(base.format(day_clause=""), (f"%{faculty_name}%",))
            return cur.fetchall()


def get_busy_slots(faculty_name: str, day: str) -> List[Dict[str, Any]]:
    query = """
        SELECT DISTINCT start_time, end_time
        FROM timetables
        WHERE faculty_name ILIKE %s AND day_of_week ILIKE %s
        ORDER BY start_time
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (f"%{faculty_name}%", f"%{day}%"))
            return cur.fetchall()

def get_course_schedule(course_code: str, day: Optional[str] = None) -> List[Dict[str, Any]]:
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            base = f"""
                SELECT day_of_week, start_time, end_time, session_type, room,
                       course_type, course_code, course_name,
                       -- Co-taught sessions are stored one row per instructor,
                       -- so each name stays independently searchable; rejoin
                       -- them here so the slot is listed once.
                       string_agg(DISTINCT faculty_name, ' / ') AS faculty_name,
                       array_agg(DISTINCT program) AS programs
                FROM timetables
                WHERE (course_code ILIKE %s OR course_name ILIKE %s) {{day_clause}}
                GROUP BY day_of_week, start_time, end_time, session_type, room,
                         course_type, course_code, course_name
                ORDER BY {DAY_ORDER_SQL}, start_time
            """
            if day:
                cur.execute(base.format(day_clause="AND day_of_week ILIKE %s"),
                            (f"%{course_code}%", f"%{course_code}%", f"%{day}%"))
            else:
                cur.execute(base.format(day_clause=""),
                            (f"%{course_code}%", f"%{course_code}%"))
            return cur.fetchall()

def list_programs() -> List[str]:
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT program FROM timetables WHERE program IS NOT NULL ORDER BY program;")
            return [r[0] for r in cur.fetchall()]


from core.utils.program import SQL_NORMALIZE_EXPR, normalize_program_name

def get_program_timetable(program_name: str, day: Optional[str] = None, semester: Optional[str] = None) -> List[Dict[str, Any]]:
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            query = f"""
                SELECT day_of_week, start_time, end_time, session_type, course_code,
                       course_name, faculty_name, room, semester, course_type
                FROM timetables
                WHERE {SQL_NORMALIZE_EXPR} = %s
            """
            params = [normalize_program_name(program_name)]
            if day:
                query += " AND day_of_week ILIKE %s"
                params.append(f"%{day}%")
            if semester:
                query += " AND semester = %s"
                params.append(str(semester))
            query += f"""
                GROUP BY day_of_week, start_time, end_time, session_type, course_code,
                         course_name, faculty_name, room, semester, course_type
                ORDER BY {DAY_ORDER_SQL}, start_time
            """
            cur.execute(query, tuple(params))
            return cur.fetchall()


def get_electives(program_name: Optional[str] = None, semester: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get all electives, optionally filtered by an exact program name and semester."""
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            query = f"""
                SELECT course_code, course_name, string_agg(DISTINCT course_type, ', ') AS course_type, array_agg(DISTINCT program) AS programs 
                FROM timetables 
                WHERE course_type ILIKE '%%elective%%'
            """
            params = []
            if program_name:
                query += f" AND {SQL_NORMALIZE_EXPR} = %s "
                params.append(normalize_program_name(program_name))
            if semester:
                query += " AND semester = %s "
                params.append(str(semester))
            
            query += """
                GROUP BY course_code, course_name
                ORDER BY course_code;
            """
            
            cur.execute(query, tuple(params))
            return cur.fetchall()


def get_electives_schedule(program_name: str, semester: str, day: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get the schedule (timetable slots) for all electives for a given exact program."""
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            query = f"""
                SELECT day_of_week, start_time, end_time, session_type, course_code,
                       course_name, faculty_name, room, semester, string_agg(DISTINCT course_type, ', ') AS course_type, array_agg(DISTINCT program) AS programs
                FROM timetables
                WHERE course_type ILIKE '%%elective%%' AND {SQL_NORMALIZE_EXPR} = %s AND semester = %s
            """
            params = [normalize_program_name(program_name), str(semester)]
            if day:
                query += " AND day_of_week ILIKE %s"
                params.append(f"%{day}%")
                
            query += f"""
                GROUP BY day_of_week, start_time, end_time, session_type, course_code,
                         course_name, faculty_name, room, semester
                ORDER BY {DAY_ORDER_SQL}, start_time, course_code
            """
            cur.execute(query, tuple(params))
            return cur.fetchall()


def get_program_busy_slots(program_name: str, day: str, semester: Optional[str] = None) -> List[Dict[str, Any]]:
    query = f"""
        SELECT DISTINCT start_time, end_time
        FROM timetables
        WHERE {SQL_NORMALIZE_EXPR} = %s AND day_of_week ILIKE %s
    """
    params = [normalize_program_name(program_name), f"%{day}%"]
    if semester:
        query += " AND semester = %s"
        params.append(str(semester))
    query += " ORDER BY start_time"
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, tuple(params))
            return cur.fetchall()


def get_programs_common_free_time(programs: List[Dict[str, Any]], day: str, min_minutes: int = 20) -> Dict[str, Any]:
    """Common free windows when ALL listed programs/batches are free on a day.
    `programs` is a list of dicts with 'program_name' and optional 'semester'.
    """
    all_busy = []
    resolved = []
    for p in programs:
        p_name = p.get('program_name')
        if not p_name:
            continue
        p_sem = p.get('semester')
        all_busy.extend(get_program_busy_slots(p_name, day, p_sem))
        resolved.append(f"{p_name}{f' (Sem {p_sem})' if p_sem else ''}")
        
    return {
        "programs": resolved,
        "day": day,
        "free_slots": compute_free_slots(all_busy, min_minutes),
    }


def list_venues() -> List[str]:
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT room FROM timetables WHERE room IS NOT NULL AND room <> '' ORDER BY room;")
            return [r[0] for r in cur.fetchall()]


def get_venue_schedule(venue: str, day: Optional[str] = None) -> List[Dict[str, Any]]:
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            base = f"""
                SELECT day_of_week, start_time, end_time, session_type, course_code,
                       -- One stored row per instructor; rejoin for display.
                       string_agg(DISTINCT faculty_name, ' / ') AS faculty_name
                FROM timetables
                WHERE REPLACE(REPLACE(room, '-', ''), ' ', '') ILIKE REPLACE(REPLACE(%s, '-', ''), ' ', '') {{day_clause}}
                GROUP BY day_of_week, start_time, end_time, session_type, course_code
                ORDER BY {DAY_ORDER_SQL}, start_time
            """
            if day:
                cur.execute(base.format(day_clause="AND day_of_week ILIKE %s"),
                            (f"%{venue}%", f"%{day}%"))
            else:
                cur.execute(base.format(day_clause=""), (f"%{venue}%",))
            return cur.fetchall()


def get_venue_availability(venue: str, day: str, time: str) -> Optional[Dict[str, Any]]:
    """Point-in-time venue check: the session occupying `venue` at `time`, or None if free. Enriched with metadata."""
    query = """
        SELECT session_type, course_code, course_name, faculty_name, start_time, end_time,
               array_agg(DISTINCT program) AS programs, room as venue_id
        FROM timetables
        WHERE REPLACE(REPLACE(room, '-', ''), ' ', '') ILIKE REPLACE(REPLACE(%s, '-', ''), ' ', '')
          AND day_of_week ILIKE %s
          AND start_time <= %s::TIME
          AND end_time > %s::TIME
        GROUP BY session_type, course_code, course_name, faculty_name, start_time, end_time, room
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (f"%{venue}%", f"%{day}%", time, time))
            result = cur.fetchone()
            if result:
                metadata = venue_service.get_venue(result['venue_id']) or {}
                result['capacity'] = metadata.get('capacity')
                result['booking_poc'] = metadata.get('booking_poc')
                result['venue_type'] = metadata.get('venue_type')
                return dict(result)
            return None


def find_free_venues(day: str, start_time: str, end_time: str) -> List[Dict[str, Any]]:
    """Venues with no session overlapping [start_time, end_time) on `day` (among venues seen in the timetable). Enriched with metadata."""
    query = """
        SELECT DISTINCT room FROM timetables
        WHERE room IS NOT NULL AND room <> ''
          AND room NOT IN (
            SELECT room FROM timetables
            WHERE day_of_week ILIKE %s
              AND start_time < %s::TIME AND end_time > %s::TIME
              AND room IS NOT NULL AND room <> ''
          )
        ORDER BY room
    """
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (f"%{day}%", end_time, start_time))
            venue_ids = [r[0] for r in cur.fetchall()]
            
            # Batch fetch metadata
            metadata_map = venue_service.get_venues_by_ids(venue_ids)
            
            results = []
            for vid in venue_ids:
                meta = metadata_map.get(vid, {})
                results.append({
                    "venue_id": vid,
                    "capacity": meta.get("capacity"),
                    "venue_type": meta.get("venue_type"),
                    "booking_poc": meta.get("booking_poc")
                })
            return results
