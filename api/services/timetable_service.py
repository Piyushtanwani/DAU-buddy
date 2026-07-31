import sys
import os
from typing import List, Dict, Any, Optional
import psycopg2.extras

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.database import db_connection

DAY_ORDER_SQL = """
    CASE day_of_week
        WHEN 'Monday' THEN 1
        WHEN 'Tuesday' THEN 2
        WHEN 'Wednesday' THEN 3
        WHEN 'Thursday' THEN 4
        WHEN 'Friday' THEN 5
        ELSE 6
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
            return [r[0] for r in cur.fetchall()]


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
                SELECT day_of_week, start_time, end_time, session_type, faculty_name, room,
                       course_type, course_code, course_name,
                       array_agg(DISTINCT program) AS programs
                FROM timetables
                WHERE (course_code ILIKE %s OR course_name ILIKE %s) {{day_clause}}
                GROUP BY day_of_week, start_time, end_time, session_type, faculty_name, room,
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


def get_program_timetable(program_name: str, day: Optional[str] = None, semester: Optional[str] = None) -> List[Dict[str, Any]]:
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            query = """
                SELECT day_of_week, start_time, end_time, session_type, course_code,
                       course_name, faculty_name, room, semester, course_type
                FROM timetables
                WHERE program ILIKE %s
            """
            params = [f"%{program_name}%"]
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


def list_rooms() -> List[str]:
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT room FROM timetables WHERE room IS NOT NULL AND room <> '' ORDER BY room;")
            return [r[0] for r in cur.fetchall()]


def get_room_schedule(room: str, day: Optional[str] = None) -> List[Dict[str, Any]]:
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            base = f"""
                SELECT day_of_week, start_time, end_time, session_type, course_code, faculty_name
                FROM timetables
                WHERE REPLACE(REPLACE(room, '-', ''), ' ', '') ILIKE REPLACE(REPLACE(%s, '-', ''), ' ', '') {{day_clause}}
                GROUP BY day_of_week, start_time, end_time, session_type, course_code, faculty_name
                ORDER BY {DAY_ORDER_SQL}, start_time
            """
            if day:
                cur.execute(base.format(day_clause="AND day_of_week ILIKE %s"),
                            (f"%{room}%", f"%{day}%"))
            else:
                cur.execute(base.format(day_clause=""), (f"%{room}%",))
            return cur.fetchall()


def get_room_availability(room: str, day: str, time: str) -> Optional[Dict[str, Any]]:
    """Point-in-time room check: the session occupying `room` at `time`, or None if free."""
    query = """
        SELECT session_type, course_code, course_name, faculty_name, start_time, end_time,
               array_agg(DISTINCT program) AS programs
        FROM timetables
        WHERE REPLACE(REPLACE(room, '-', ''), ' ', '') ILIKE REPLACE(REPLACE(%s, '-', ''), ' ', '')
          AND day_of_week ILIKE %s
          AND start_time <= %s::TIME
          AND end_time > %s::TIME
        GROUP BY session_type, course_code, course_name, faculty_name, start_time, end_time
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (f"%{room}%", f"%{day}%", time, time))
            return cur.fetchone()


def find_free_rooms(day: str, time: str) -> List[str]:
    """Rooms with no session covering `time` on `day` (among rooms seen in the timetable)."""
    query = """
        SELECT DISTINCT room FROM timetables
        WHERE room IS NOT NULL AND room <> ''
          AND room NOT IN (
            SELECT room FROM timetables
            WHERE day_of_week ILIKE %s
              AND start_time <= %s::TIME AND end_time > %s::TIME
              AND room IS NOT NULL AND room <> ''
          )
        ORDER BY room
    """
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (f"%{day}%", time, time))
            return [r[0] for r in cur.fetchall()]
