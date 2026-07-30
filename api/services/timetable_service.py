import sys
import os
from typing import List, Dict, Any, Optional
import psycopg2.extras

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.database import db_connection

def get_faculty_location(faculty_name: str, day: str, time: str) -> Optional[Dict[str, Any]]:
    query = """
        SELECT session_type, course_code, course_name, location, start_time, end_time, program
        FROM timetables
        WHERE faculty_name ILIKE %s
          AND day_of_week ILIKE %s
          AND start_time <= %s::TIME
          AND end_time > %s::TIME
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (f"%{faculty_name}%", f"%{day}%", time, time))
            return cur.fetchone()

def get_faculty_schedule(faculty_name: str, day: Optional[str] = None) -> List[Dict[str, Any]]:
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if day:
                query = """
                    SELECT day_of_week, start_time, end_time, session_type, course_code, room, program, semester, course_type
                    FROM timetables
                    WHERE faculty_name ILIKE %s AND day_of_week ILIKE %s
                    ORDER BY start_time
                """
                cur.execute(query, (f"%{faculty_name}%", f"%{day}%"))
            else:
                query = """
                    SELECT day_of_week, start_time, end_time, session_type, course_code, room, program, semester, course_type
                    FROM timetables
                    WHERE faculty_name ILIKE %s
                    ORDER BY 
                        CASE day_of_week
                            WHEN 'Monday' THEN 1
                            WHEN 'Tuesday' THEN 2
                            WHEN 'Wednesday' THEN 3
                            WHEN 'Thursday' THEN 4
                            WHEN 'Friday' THEN 5
                            ELSE 6
                        END, start_time
                """
                cur.execute(query, (f"%{faculty_name}%",))
            return cur.fetchall()

def find_faculty_free_time(faculty_name: str, day: str) -> List[Dict[str, Any]]:
    query = """
        SELECT start_time, end_time
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
            if day:
                query = """
                    SELECT day_of_week, start_time, end_time, session_type, faculty_name, room, program, semester, course_type, course_code, course_name
                    FROM timetables
                    WHERE (course_code ILIKE %s OR course_name ILIKE %s)
                      AND day_of_week ILIKE %s
                    ORDER BY start_time
                """
                cur.execute(query, (f"%{course_code}%", f"%{course_code}%", f"%{day}%"))
            else:
                query = """
                    SELECT day_of_week, start_time, end_time, session_type, faculty_name, room, program, semester, course_type, course_code, course_name
                    FROM timetables
                    WHERE (course_code ILIKE %s OR course_name ILIKE %s)
                    ORDER BY 
                        CASE day_of_week
                            WHEN 'Monday' THEN 1
                            WHEN 'Tuesday' THEN 2
                            WHEN 'Wednesday' THEN 3
                            WHEN 'Thursday' THEN 4
                            WHEN 'Friday' THEN 5
                            ELSE 6
                        END, start_time
                """
                cur.execute(query, (f"%{course_code}%", f"%{course_code}%"))
            return cur.fetchall()

def list_programs() -> List[str]:
    with db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT program FROM timetables WHERE program IS NOT NULL ORDER BY program;")
            results = cur.fetchall()
            return [r[0] for r in results]

def get_program_timetable(program_name: str, day: Optional[str] = None, semester: Optional[str] = None) -> List[Dict[str, Any]]:
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            query = """
                SELECT day_of_week, start_time, end_time, session_type, course_code, course_name, faculty_name, room, program, semester, course_type
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
                
            query += """
                ORDER BY 
                    CASE day_of_week
                        WHEN 'Monday' THEN 1
                        WHEN 'Tuesday' THEN 2
                        WHEN 'Wednesday' THEN 3
                        WHEN 'Thursday' THEN 4
                        WHEN 'Friday' THEN 5
                        ELSE 6
                    END, start_time
            """
            cur.execute(query, tuple(params))
            return cur.fetchall()

def get_room_availability(room: str, day: str, time: str) -> Optional[Dict[str, Any]]:
    query = """
        SELECT session_type, course_code, course_name, faculty_name, start_time, end_time, program
        FROM timetables
        WHERE room ILIKE %s
          AND day_of_week ILIKE %s
          AND start_time <= %s::TIME
          AND end_time > %s::TIME
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (f"%{room}%", f"%{day}%", time, time))
            return cur.fetchone()

def get_room_schedule_for_day(room: str, day: str) -> List[Dict[str, Any]]:
    query = """
        SELECT session_type, course_code, course_name, faculty_name, start_time, end_time, program
        FROM timetables
        WHERE room ILIKE %s
          AND day_of_week ILIKE %s
        ORDER BY start_time
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (f"%{room}%", f"%{day}%"))
            return cur.fetchall()
