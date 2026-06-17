import asyncio
import os
import sys
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
import psycopg2
import psycopg2.extras

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config
from core.database import db_connection

logger = config.get_logger("dau_mcp.timetable_mcp_server")

mcp = FastMCP(
    "timetable_mcp",
    dependencies=["psycopg2-binary"]
)

@mcp.tool()
async def get_faculty_location(faculty_name: str, day: str, time: str) -> str:
    """
    Finds exactly what class/lab a faculty is teaching and in which room at a specific time.
    
    Args:
        faculty_name: Name or initials of the faculty (e.g., 'Ankush', 'PD').
        day: Day of the week (e.g., 'Monday').
        time: Time string (e.g., '10:00:00' or '10:00 AM').
    """
    try:
        with db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = """
                    SELECT session_type, course_code, course_name, location, start_time, end_time, batch_group
                    FROM timetables
                    WHERE faculty_name ILIKE %s
                      AND day_of_week ILIKE %s
                      AND start_time <= %s::TIME
                      AND end_time > %s::TIME
                """
                # Using wildcards for faculty name to match initials or partial names
                cur.execute(query, (f"%{faculty_name}%", f"%{day}%", time, time))
                result = cur.fetchone()
                
                if result:
                    batch_info = f" (Batch: {result['batch_group']})" if result['batch_group'] else ""
                    name_info = f" - {result['course_name']}" if result['course_name'] else ""
                    return (f"{faculty_name} is currently teaching a {result['session_type']} for "
                            f"{result['course_code']}{name_info}{batch_info} "
                            f"in {result['location']} from {result['start_time']} to {result['end_time']}.")
                else:
                    return f"{faculty_name} does not have any scheduled classes at {time} on {day}."
    except Exception as e:
        logger.error(f"Error in get_faculty_location: {e}")
        return f"Error querying faculty location: {str(e)}"

@mcp.tool()
async def get_faculty_schedule(faculty_name: str, day: Optional[str] = None) -> str:
    """
    Retrieves the complete timetable for a specific faculty member.
    
    Args:
        faculty_name: Name or initials of the faculty.
        day: Optional day of the week to filter by.
    """
    try:
        with db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if day:
                    query = """
                        SELECT day_of_week, start_time, end_time, session_type, course_code, location, batch_group
                        FROM timetables
                        WHERE faculty_name ILIKE %s AND day_of_week ILIKE %s
                        ORDER BY start_time
                    """
                    cur.execute(query, (f"%{faculty_name}%", f"%{day}%"))
                else:
                    query = """
                        SELECT day_of_week, start_time, end_time, session_type, course_code, location, batch_group
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
                
                results = cur.fetchall()
                if not results:
                    day_str = f" on {day}" if day else ""
                    return f"No scheduled classes found for {faculty_name}{day_str}."
                
                schedule = [f"Schedule for {faculty_name}:"]
                for row in results:
                    batch_info = f" [Batch: {row['batch_group']}]" if row['batch_group'] else ""
                    schedule.append(f"- {row['day_of_week']} {row['start_time']} to {row['end_time']}: {row['session_type']} ({row['course_code']}) in {row['location']}{batch_info}")
                
                return "\n".join(schedule)
    except Exception as e:
        logger.error(f"Error in get_faculty_schedule: {e}")
        return f"Error querying faculty schedule: {str(e)}"

@mcp.tool()
async def find_faculty_free_time(faculty_name: str, day: str) -> str:
    """
    Calculates the gaps between classes to tell you exactly when a faculty member is free to meet.
    
    Args:
        faculty_name: Name or initials of the faculty.
        day: Day of the week (e.g., 'Monday').
    """
    try:
        with db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                query = """
                    SELECT start_time, end_time
                    FROM timetables
                    WHERE faculty_name ILIKE %s AND day_of_week ILIKE %s
                    ORDER BY start_time
                """
                cur.execute(query, (f"%{faculty_name}%", f"%{day}%"))
                results = cur.fetchall()
                
                if not results:
                    return f"{faculty_name} appears to be completely free on {day}."
                
                free_slots = []
                day_start = "08:00:00"
                day_end = "18:00:00"
                
                current_time = day_start
                for row in results:
                    start_str = row['start_time'].strftime("%H:%M:%S")
                    end_str = row['end_time'].strftime("%H:%M:%S")
                    
                    if current_time < start_str:
                        free_slots.append(f"{current_time} to {start_str}")
                    
                    current_time = max(current_time, end_str)
                
                if current_time < day_end:
                    free_slots.append(f"{current_time} to {day_end}")
                    
                if not free_slots:
                    return f"{faculty_name} has no free time on {day}."
                    
                return f"{faculty_name} is free on {day} during these times:\n" + "\n".join([f"- {slot}" for slot in free_slots])
    except Exception as e:
        logger.error(f"Error in find_faculty_free_time: {e}")
        return f"Error querying faculty free time: {str(e)}"

@mcp.tool()
async def get_course_schedule(course_code: str, day: Optional[str] = None) -> str:
    """
    Finds exactly when and where a particular subject/course is running.
    
    Args:
        course_code: The course code (e.g., 'CS101') or subject name.
        day: Optional day of the week to filter by.
    """
    try:
        with db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if day:
                    query = """
                        SELECT day_of_week, start_time, end_time, session_type, faculty_name, location, batch_group
                        FROM timetables
                        WHERE (course_code ILIKE %s OR course_name ILIKE %s)
                          AND day_of_week ILIKE %s
                        ORDER BY start_time
                    """
                    cur.execute(query, (f"%{course_code}%", f"%{course_code}%", f"%{day}%"))
                else:
                    query = """
                        SELECT day_of_week, start_time, end_time, session_type, faculty_name, location, batch_group
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
                
                results = cur.fetchall()
                if not results:
                    day_str = f" on {day}" if day else ""
                    return f"No scheduled classes found for {course_code}{day_str}."
                
                schedule = [f"Schedule for {course_code}:"]
                for row in results:
                    batch_info = f" [Batch: {row['batch_group']}]" if row['batch_group'] else ""
                    schedule.append(f"- {row['day_of_week']} {row['start_time']} to {row['end_time']}: {row['session_type']} with {row['faculty_name']} in {row['location']}{batch_info}")
                
                return "\n".join(schedule)
    except Exception as e:
        logger.error(f"Error in get_course_schedule: {e}")
        return f"Error querying course schedule: {str(e)}"

@mcp.tool()
async def list_programs() -> str:
    """
    Returns a list of all available programs and batch names in the timetable database.
    Use this tool if you need to know the exact name of a program (e.g., 'MSc Sem-II (IT)') to pass to get_program_timetable.
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT batch_group FROM timetables WHERE batch_group IS NOT NULL ORDER BY batch_group;")
                results = cur.fetchall()
                if not results:
                    return "No programs found in the timetable database."
                
                programs = [r[0] for r in results]
                return "Available Programs/Batches:\n" + "\n".join([f"- {p}" for p in programs])
    except Exception as e:
        logger.error(f"Error in list_programs: {e}")
        return f"Error querying programs: {str(e)}"

@mcp.tool()
async def get_program_timetable(program_name: str, day: Optional[str] = None) -> str:
    """
    Retrieves the timetable for an entire program/batch.
    
    Args:
        program_name: The name of the program or batch (e.g., 'Msc-it Semester 2', 'BTech Sem-II').
        day: Optional day of the week to filter by.
    """
    try:
        with db_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if day:
                    query = """
                        SELECT day_of_week, start_time, end_time, session_type, course_code, course_name, faculty_name, location, batch_group
                        FROM timetables
                        WHERE batch_group ILIKE %s AND day_of_week ILIKE %s
                        ORDER BY start_time
                    """
                    cur.execute(query, (f"%{program_name}%", f"%{day}%"))
                else:
                    query = """
                        SELECT day_of_week, start_time, end_time, session_type, course_code, course_name, faculty_name, location, batch_group
                        FROM timetables
                        WHERE batch_group ILIKE %s
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
                    cur.execute(query, (f"%{program_name}%",))
                
                results = cur.fetchall()
                if not results:
                    day_str = f" on {day}" if day else ""
                    return f"No scheduled classes found for program {program_name}{day_str}."
                
                schedule = [f"Schedule for {program_name}:"]
                for row in results:
                    name_info = f" - {row['course_name']}" if row['course_name'] else ""
                    schedule.append(f"- {row['day_of_week']} {row['start_time']} to {row['end_time']}: {row['session_type']} for {row['course_code']}{name_info} with {row['faculty_name']} in {row['location']}")
                
                return "\n".join(schedule)
    except Exception as e:
        logger.error(f"Error in get_program_timetable: {e}")
        return f"Error querying program timetable: {str(e)}"

if __name__ == "__main__":
    mcp.run()
