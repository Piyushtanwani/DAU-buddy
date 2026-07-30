import asyncio
import os
import sys
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config
from api.services import timetable_service

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
        result = timetable_service.get_faculty_location(faculty_name, day, time)
        if result:
            batch_info = f" (Batch: {result['program']})" if result['program'] else ""
            name_info = f" - {result['course_name']}" if result['course_name'] else ""
            return (f"{faculty_name} is currently teaching a {result['session_type']} for "
                    f"{result['course_code']}{name_info}{batch_info} "
                    f"in {result['room']} from {result['start_time']} to {result['end_time']}.")
        else:
            return f"{faculty_name} does not have any scheduled classes at {time} on {day}."
    except Exception as e:
        logger.error(f"Error in get_faculty_room: {e}")
        return f"Error querying faculty room: {str(e)}"

@mcp.tool()
async def get_faculty_schedule(faculty_name: str, day: Optional[str] = None) -> str:
    """
    Retrieves the complete timetable for a specific faculty member, including lectures, labs, and tutorials.
    
    Args:
        faculty_name: Name or initials of the faculty.
        day: Optional day of the week to filter by.
    """
    try:
        results = timetable_service.get_faculty_schedule(faculty_name, day)
        if not results:
            day_str = f" on {day}" if day else ""
            return f"No scheduled classes found for {faculty_name}{day_str}."
        
        schedule = [f"Schedule for {faculty_name}:"]
        for row in results:
            batch_info = f" [Batch: {row['program']}]" if row['program'] else ""
            schedule.append(f"- {row['day_of_week']} {row['start_time']} to {row['end_time']}: {row['session_type']} ({row['course_code']}) in {row['room']}{batch_info}")
        
        return "\n".join(schedule)
    except Exception as e:
        logger.error(f"Error in get_faculty_schedule: {e}")
        return f"Error querying faculty schedule: {str(e)}"

@mcp.tool()
async def find_faculty_free_time(faculty_name: str, day: str) -> str:
    """
    Calculates the gaps between classes (lectures, labs, tutorials) to tell you exactly when a faculty member is free to meet.
    
    Args:
        faculty_name: Name or initials of the faculty.
        day: Day of the week (e.g., 'Monday').
    """
    try:
        results = timetable_service.find_faculty_free_time(faculty_name, day)
        
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
    Finds exactly when and where a particular subject/course is running (includes both lectures and labs/tutorials).
    
    Args:
        course_code: The course code (e.g., 'CS101') or subject name.
        day: Optional day of the week to filter by.
    """
    try:
        results = timetable_service.get_course_schedule(course_code, day)
        if not results:
            day_str = f" on {day}" if day else ""
            return f"No scheduled classes found for {course_code}{day_str}."
        
        schedule = [f"Schedule for {course_code}:"]
        for row in results:
            batch_info = f" [Batch: {row['program']} Sem {row['semester']}]" if row['program'] else ""
            type_info = f" [{row['course_type']}]" if row.get('course_type') else ""
            name_info = f" - {row['course_name']}" if row.get('course_name') else ""
            schedule.append(f"- {row['day_of_week']} {row['start_time']} to {row['end_time']}: {row['session_type']} for {row.get('course_code', course_code)}{type_info}{name_info} with {row['faculty_name']} in {row['room']}{batch_info}")
        
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
        programs = timetable_service.list_programs()
        if not programs:
            return "No programs found in the timetable database."
        
        return "Available Programs/Batches:\n" + "\n".join([f"- {p}" for p in programs])
    except Exception as e:
        logger.error(f"Error in list_programs: {e}")
        return f"Error querying programs: {str(e)}"

@mcp.tool()
async def get_program_timetable(program_name: str, day: Optional[str] = None, semester: Optional[str] = None) -> str:
    """
    Retrieves the timetable for an entire program/batch, including both lectures and lab sessions.
    
    Args:
        program_name: The name of the program or batch (e.g., 'Msc-it Semester 2', 'BTech Sem-II').
        day: Optional day of the week to filter by.
        semester: Optional semester number (e.g., '1', '2', '3') to filter the timetable by.
    """
    try:
        results = timetable_service.get_program_timetable(program_name, day, semester)
        if not results:
            day_str = f" on {day}" if day else ""
            sem_str = f" for Semester {semester}" if semester else ""
            return f"No scheduled classes found for program {program_name}{sem_str}{day_str}."
        
        sem_str = f" (Semester {semester})" if semester else ""
        schedule = [f"Schedule for {program_name}{sem_str}:"]
        for row in results:
            name_info = f" - {row['course_name']}" if row['course_name'] else ""
            type_info = f" [{row['course_type']}]" if row.get('course_type') else ""
            schedule.append(f"- {row['day_of_week']} {row['start_time']} to {row['end_time']}: {row['session_type']} for {row['course_code']}{type_info}{name_info} with {row['faculty_name']} in {row['room']}")
        
        return "\n".join(schedule)
    except Exception as e:
        logger.error(f"Error in get_program_timetable: {e}")
        return f"Error querying program timetable: {str(e)}"

@mcp.tool()
async def check_room_availability(room: str, day: str, time: str) -> str:
    """
    Checks if a particular classroom or lab is available at a specific time, and if not, returns what class is currently happening there.
    
    Args:
        room: The classroom or lab name (e.g., 'cep-207', 'LT-1').
        day: Day of the week (e.g., 'Monday').
        time: Time string (e.g., '14:00:00' or '2:00 PM').
    """
    try:
        result = timetable_service.get_room_availability(room, day, time)
        
        daily_schedule = timetable_service.get_room_schedule_for_day(room, day)
        schedule_info = "\n\nFull Schedule for the Day:\n"
        if not daily_schedule:
            schedule_info += "No classes scheduled for today.\n"
        else:
            for c in daily_schedule:
                b_info = f" (Batch: {c['program']})" if c['program'] else ""
                n_info = f" - {c['course_name']}" if c['course_name'] else ""
                schedule_info += f"- {c['start_time']} to {c['end_time']}: {c['session_type']} ({c['course_code']}{n_info}){b_info} with {c['faculty_name']}\n"

        if result:
            batch_info = f" (Batch: {result['program']})" if result['program'] else ""
            name_info = f" - {result['course_name']}" if result['course_name'] else ""
            base_msg = (f"{room} is NOT available at {time} on {day}. "
                    f"It is currently booked for a {result['session_type']} ({result['course_code']}{name_info}){batch_info} "
                    f"with {result['faculty_name']} from {result['start_time']} to {result['end_time']}.")
        else:
            base_msg = f"Yes, {room} is available at {time} on {day}. There are no scheduled classes at this exact time."
            
        return base_msg + schedule_info
    except Exception as e:
        logger.error(f"Error in check_room_availability: {e}")
        return f"Error querying room availability: {str(e)}"

if __name__ == "__main__":
    mcp.run()
