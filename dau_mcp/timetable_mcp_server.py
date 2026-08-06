import os
import sys
import logging
from datetime import datetime
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config
from api.services import timetable_service
from api.services import calendar_service

logger = config.get_logger("dau_mcp.timetable_mcp_server")

mcp = FastMCP(
    "timetable_mcp",
    dependencies=["psycopg2-binary"]
)

DAY_START = "08:00"
DAY_END = "18:00"


def _now_day_time() -> tuple[str, str]:
    """
    Campus day+time for timetable lookups. Never datetime.now() — see
    config.CAMPUS_TZ — and never the raw weekday either: the academic calendar
    reassigns some dates ("07-08-2026 to be treated as Tuesday"), and on those
    days the campus runs the substituted day's timetable.
    """
    now = config.campus_now()
    day, _ = calendar_service.effective_day(now.date())
    return day, now.strftime("%H:%M:%S")


def _day_note() -> str:
    """' (Friday, treated as Tuesday)' when today is reassigned, else ''."""
    day, substituted_from = calendar_service.effective_day()
    return f" ({substituted_from}, treated as {day})" if substituted_from else ""


def _hhmm(t) -> str:
    """TIME -> 'HH:MM' (drop seconds; slots are minute-grained)."""
    return t.strftime("%H:%M") if hasattr(t, "strftime") else str(t)[:5]


def _fmt_programs(row) -> str:
    progs = row.get("programs")
    return f" [{', '.join(progs)}]" if progs else ""


def _resolution_error(query: str, candidates: list) -> str:
    if not candidates:
        return f"No faculty matching '{query}' in timetable. Check spelling/initials."
    return f"{len(candidates)} faculty match '{query}': {', '.join(candidates)}. Specify one."


def _resolve_single(faculty_name: str) -> tuple[Optional[str], Optional[str]]:
    """Resolve query to exactly one faculty. Returns (name, error_message)."""
    name, matches = timetable_service.resolve_single(faculty_name)
    if name:
        return name, None
    return None, _resolution_error(faculty_name, matches)


# Gap computation is shared with the web-chat wrappers via the service layer.
_free_slots = timetable_service.compute_free_slots


@mcp.tool()
async def get_faculty_location(faculty_name: str, day: Optional[str] = None, time: Optional[str] = None) -> str:
    """
    Which class/room a faculty member is in at a given time.
    Omit day/time to use the current server time.

    Args:
        faculty_name: Name or initials (e.g., 'Ankush', 'PD').
        day: Optional day of week; defaults to today.
        time: Optional 'HH:MM' 24h; defaults to now.
    """
    try:
        now_day, now_time = _now_day_time()
        note = _day_note() if day is None else ""
        day, time = day or now_day, time or now_time
        name, err = _resolve_single(faculty_name)
        if err:
            return err
        result = timetable_service.get_faculty_location(name, day, time)
        if not result:
            return f"{name}: no class at {time} on {day}{note}."
        progs = f" [{', '.join(result['programs'])}]" if result.get("programs") else ""
        name_info = f" - {result['course_name']}" if result.get("course_name") else ""
        return (f"{name}: {result['session_type']} {result['course_code']}{name_info}{progs} "
                f"in {result['room']}, {_hhmm(result['start_time'])}-{_hhmm(result['end_time'])} ({day}{note}).")
    except Exception as e:
        logger.error(f"Error in get_faculty_location: {e}")
        return "Error querying faculty location."


@mcp.tool()
async def get_faculty_schedule(faculty_name: str, day: Optional[str] = None) -> str:
    """
    Full timetable for one faculty member (lectures, labs, tutorials).
    One line per slot; enrolled batches aggregated in brackets.

    Args:
        faculty_name: Name or initials of the faculty.
        day: Optional day of the week to filter by.
    """
    try:
        name, err = _resolve_single(faculty_name)
        if err:
            return err
        results = timetable_service.get_faculty_schedule(name, day)
        if not results:
            return f"No scheduled classes for {name}{f' on {day}' if day else ''}."
        lines = [f"Schedule for {name}:"]
        for r in results:
            lines.append(f"- {r['day_of_week']} {_hhmm(r['start_time'])}-{_hhmm(r['end_time'])}: "
                         f"{r['session_type']} {r['course_code']} in {r['room']}{_fmt_programs(r)}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error in get_faculty_schedule: {e}")
        return "Error querying faculty schedule."


@mcp.tool()
async def find_faculty_free_time(faculty_name: str, day: str) -> str:
    """
    Free (meeting-available) windows for a faculty member on a given day,
    computed as gaps between classes within the 08:00-18:00 campus day.

    Args:
        faculty_name: Name or initials of the faculty.
        day: Day of the week (e.g., 'Monday').
    """
    try:
        data = timetable_service.get_free_time(faculty_name, day)
        if "candidates" in data:
            return _resolution_error(data["query"], data["candidates"])
        name = data["faculty"]
        if not data["busy_slots"]:
            return f"{name}: no classes on {day} — free all day (timetable only; other commitments not tracked)."
        if not data["free_slots"]:
            return f"{name}: no free time on {day}."
        return f"{name} free on {day}: " + ", ".join(data["free_slots"])
    except Exception as e:
        logger.error(f"Error in find_faculty_free_time: {e}")
        return "Error querying faculty free time."


@mcp.tool()
async def find_common_free_time(faculty_names: List[str], day: str) -> str:
    """
    Meeting slots when ALL listed faculty are free on a given day
    (gaps in the union of their class schedules, 08:00-18:00).

    Args:
        faculty_names: List of names/initials (e.g., ['Sourish', 'Kalyan', 'AC']).
        day: Day of the week.
    """
    try:
        data = timetable_service.get_common_free_time(faculty_names, day)
        if "candidates" in data:
            return _resolution_error(data["query"], data["candidates"])
        who = ", ".join(data["faculty"])
        if not data["free_slots"]:
            return f"No common free time on {day} for {who}."
        return f"Common free on {day} ({who}): " + ", ".join(data["free_slots"])
    except Exception as e:
        logger.error(f"Error in find_common_free_time: {e}")
        return "Error querying common free time."


@mcp.tool()
async def get_course_schedule(course_code: str, day: Optional[str] = None) -> str:
    """
    When and where a course runs (lectures and labs/tutorials).

    Args:
        course_code: Course code (e.g., 'CS101') or subject name.
        day: Optional day of the week to filter by.
    """
    try:
        results = timetable_service.get_course_schedule(course_code, day)
        if not results:
            return f"No scheduled classes for {course_code}{f' on {day}' if day else ''}."
        lines = [f"Schedule for {course_code}:"]
        for r in results:
            name_info = f" - {r['course_name']}" if r.get("course_name") else ""
            lines.append(f"- {r['day_of_week']} {_hhmm(r['start_time'])}-{_hhmm(r['end_time'])}: "
                         f"{r['session_type']} {r['course_code']}{name_info} with {r['faculty_name']} "
                         f"in {r['room']}{_fmt_programs(r)}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error in get_course_schedule: {e}")
        return "Error querying course schedule."


@mcp.tool()
async def list_programs() -> str:
    """
    All program/batch names in the timetable database.
    Use to get exact names for get_program_timetable.
    """
    try:
        programs = timetable_service.list_programs()
        if not programs:
            return "No programs found."
        return "Programs: " + "; ".join(programs)
    except Exception as e:
        logger.error(f"Error in list_programs: {e}")
        return "Error querying programs."


@mcp.tool()
async def get_program_timetable(program_name: str, day: Optional[str] = None, semester: Optional[str] = None) -> str:
    """
    Timetable for a whole program/batch (lectures and labs).

    Args:
        program_name: Program/batch name (see list_programs).
        day: Optional day of the week to filter by.
        semester: Optional semester number ('1', '3', ...).
    """
    try:
        results = timetable_service.get_program_timetable(program_name, day, semester)
        if not results:
            return f"No classes for {program_name}{f' sem {semester}' if semester else ''}{f' on {day}' if day else ''}."
        sem_str = f" (Sem {semester})" if semester else ""
        lines = [f"Schedule for {program_name}{sem_str}:"]
        for r in results:
            name_info = f" - {r['course_name']}" if r.get("course_name") else ""
            type_info = f" [{r['course_type']}]" if r.get("course_type") else ""
            lines.append(f"- {r['day_of_week']} {_hhmm(r['start_time'])}-{_hhmm(r['end_time'])}: "
                         f"{r['session_type']} {r['course_code']}{type_info}{name_info} "
                         f"with {r['faculty_name']} in {r['room']}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error in get_program_timetable: {e}")
        return "Error querying program timetable."


@mcp.tool()
async def list_rooms() -> str:
    """All room names present in the timetable database."""
    try:
        rooms = timetable_service.list_rooms()
        if not rooms:
            return "No rooms found."
        return "Rooms: " + "; ".join(rooms)
    except Exception as e:
        logger.error(f"Error in list_rooms: {e}")
        return "Error querying rooms."


@mcp.tool()
async def get_room_schedule(room: str, day: Optional[str] = None) -> str:
    """
    Full-day occupancy of a room: every session (course, faculty, time) plus free gaps.
    Room matching ignores hyphens/spaces ('CEP209' == 'CEP-209').

    Args:
        room: Room name (e.g., 'CEP-209', 'LT-2').
        day: Optional day of week; omit for the whole week.
    """
    try:
        results = timetable_service.get_room_schedule(room, day)
        if not results:
            rooms = timetable_service.list_rooms()
            near = [r for r in rooms if room.replace("-", "").replace(" ", "").lower() in r.replace("-", "").replace(" ", "").lower()]
            hint = f" Close matches: {', '.join(near)}." if near else " See list_rooms."
            return f"No sessions found for room '{room}'.{hint}"
        room_label = room.upper()
        lines = [f"Room {room_label}{f' — {day}' if day else ''}:"]
        by_day: dict[str, list] = {}
        for r in results:
            by_day.setdefault(r["day_of_week"], []).append(r)
        for d, rows in by_day.items():
            if not day:
                lines.append(f"{d}:")
            for r in rows:
                lines.append(f"- {_hhmm(r['start_time'])}-{_hhmm(r['end_time'])}: "
                             f"{r['session_type']} {r['course_code']} ({r['faculty_name']})")
            lines.append(f"  Free: {', '.join(_free_slots(rows)) or 'none'}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error in get_room_schedule: {e}")
        return "Error querying room schedule."


@mcp.tool()
async def find_free_rooms(day: Optional[str] = None, time: Optional[str] = None) -> str:
    """
    Rooms with no scheduled session at a given day+time.
    Omit day/time to use the current server time.

    Args:
        day: Optional day of week; defaults to today.
        time: Optional 'HH:MM' 24h; defaults to now.
    """
    try:
        now_day, now_time = _now_day_time()
        note = _day_note() if day is None else ""
        day, time = day or now_day, time or now_time
        rooms = timetable_service.find_free_rooms(day, time)
        if not rooms:
            return f"No free rooms at {time} on {day}{note}."
        return f"Free at {time} {day}{note}: " + "; ".join(rooms)
    except Exception as e:
        logger.error(f"Error in find_free_rooms: {e}")
        return "Error querying free rooms."


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
        if result:
            progs = f" [{', '.join(result['programs'])}]" if result.get("programs") else ""
            name_info = f" - {result['course_name']}" if result.get("course_name") else ""
            return (f"{room} NOT available at {time} {day}: {result['session_type']} "
                    f"{result['course_code']}{name_info}{progs} with {result['faculty_name']}, "
                    f"{_hhmm(result['start_time'])}-{_hhmm(result['end_time'])}.")
        return f"{room} is free at {time} on {day} (no scheduled class; caveat: unknown room names also report free — see list_rooms)."
    except Exception as e:
        logger.error(f"Error in check_room_availability: {e}")
        return "Error querying room availability."

if __name__ == "__main__":
    mcp.run()
