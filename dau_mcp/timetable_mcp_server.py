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


def _campus_time() -> str:
    """
    Current campus clock time. Never datetime.now() — see config.CAMPUS_TZ, the
    deployed image runs UTC. Deliberately does no calendar lookup: the day a
    lookup should query comes from _resolve_day, which resolves it once.
    """
    return config.campus_now().strftime("%H:%M:%S")


def _resolve_day(
    day: Optional[str] = None,
    date: Optional[str] = None,
    default_to_today: bool = False,
) -> tuple[Optional[str], str, Optional[str]]:
    """
    Decide which weekday a lookup should query.

    Precedence: an explicit `date` wins, then an explicit `day`, then today (only
    where a tool defaults to today; elsewhere None means the whole week).

    A date is resolved through the academic calendar, so 2026-08-07 queries
    TUESDAY — the calendar reassigns that Friday. A bare `day` cannot be
    resolved: by then the date is gone, and "Friday" is taken at face value.

    Returns (day_to_query, note, error). `note` explains a substitution in the
    tool's own output; `error` is a message to return verbatim to the caller.
    Costs at most one calendar lookup, and none when `day` is explicit.
    """
    if date:
        try:
            parsed = datetime.strptime(date.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None, "", f"Invalid date '{date}'. Use YYYY-MM-DD."
        effective, substituted_from = calendar_service.effective_day(parsed)
        note = (
            f" ({date} is a {substituted_from}, treated as {effective})"
            if substituted_from else ""
        )
        return effective, note, None
    if day:
        return day, "", None
    if default_to_today:
        effective, substituted_from = calendar_service.effective_day(
            config.campus_now().date()
        )
        note = (
            f" ({substituted_from}, treated as {effective})"
            if substituted_from else ""
        )
        return effective, note, None
    return None, "", None


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
async def get_faculty_location(faculty_name: str, day: Optional[str] = None, time: Optional[str] = None,
                               date: Optional[str] = None) -> str:
    """
    Which class/room a faculty member is in at a given time.
    Omit day/time/date to use the current campus time.

    Args:
        faculty_name: Name or initials (e.g., 'Ankush', 'PD').
        day: Optional day of week; defaults to today.
        time: Optional 'HH:MM' 24h; defaults to now.
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August'): the academic
            calendar reassigns some dates to another weekday, and only `date`
            resolves that.
    """
    try:
        day, note, err = _resolve_day(day, date, default_to_today=True)
        if err:
            return err
        time = time or _campus_time()
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
async def get_faculty_schedule(faculty_name: str, day: Optional[str] = None,
                               date: Optional[str] = None) -> str:
    """
    Full timetable for one faculty member (lectures, labs, tutorials).
    One line per slot; enrolled batches aggregated in brackets.

    Args:
        faculty_name: Name or initials of the faculty.
        day: Optional day of the week to filter by; omit for the whole week.
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August'): the academic
            calendar reassigns some dates to another weekday, and only `date`
            resolves that.
    """
    try:
        day, note, err = _resolve_day(day, date)
        if err:
            return err
        name, err = _resolve_single(faculty_name)
        if err:
            return err
        results = timetable_service.get_faculty_schedule(name, day)
        if not results:
            return f"No scheduled classes for {name}{f' on {day}' if day else ''}{note}."
        lines = [f"Schedule for {name}{f' — {day}{note}' if day else ''}:"]
        for r in results:
            lines.append(f"- {r['day_of_week']} {_hhmm(r['start_time'])}-{_hhmm(r['end_time'])}: "
                         f"{r['session_type']} {r['course_code']} in {r['room']}{_fmt_programs(r)}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error in get_faculty_schedule: {e}")
        return "Error querying faculty schedule."


@mcp.tool()
async def find_faculty_free_time(faculty_name: str, day: Optional[str] = None,
                                 date: Optional[str] = None) -> str:
    """
    Free (meeting-available) windows for a faculty member on a given day,
    computed as gaps between classes within the 08:00-18:00 campus day.

    Args:
        faculty_name: Name or initials of the faculty.
        day: Day of the week (e.g., 'Monday'); defaults to today.
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August'): the academic
            calendar reassigns some dates to another weekday, and only `date`
            resolves that.
    """
    try:
        day, note, err = _resolve_day(day, date, default_to_today=True)
        if err:
            return err
        data = timetable_service.get_free_time(faculty_name, day)
        if "candidates" in data:
            return _resolution_error(data["query"], data["candidates"])
        name = data["faculty"]
        if not data["busy_slots"]:
            return f"{name}: no classes on {day}{note} — free all day (timetable only; other commitments not tracked)."
        if not data["free_slots"]:
            return f"{name}: no free time on {day}{note}."
        return f"{name} free on {day}{note}: " + ", ".join(data["free_slots"])
    except Exception as e:
        logger.error(f"Error in find_faculty_free_time: {e}")
        return "Error querying faculty free time."


@mcp.tool()
async def find_common_free_time(faculty_names: List[str], day: Optional[str] = None,
                                date: Optional[str] = None) -> str:
    """
    Meeting slots when ALL listed faculty are free on a given day
    (gaps in the union of their class schedules, 08:00-18:00).

    Args:
        faculty_names: List of names/initials (e.g., ['Sourish', 'Kalyan', 'AC']).
        day: Day of the week; defaults to today.
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August'): the academic
            calendar reassigns some dates to another weekday, and only `date`
            resolves that.
    """
    try:
        day, note, err = _resolve_day(day, date, default_to_today=True)
        if err:
            return err
        data = timetable_service.get_common_free_time(faculty_names, day)
        if "candidates" in data:
            return _resolution_error(data["query"], data["candidates"])
        who = ", ".join(data["faculty"])
        if not data["free_slots"]:
            return f"No common free time on {day}{note} for {who}."
        return f"Common free on {day}{note} ({who}): " + ", ".join(data["free_slots"])
    except Exception as e:
        logger.error(f"Error in find_common_free_time: {e}")
        return "Error querying common free time."


@mcp.tool()
async def get_course_schedule(course_code: str, day: Optional[str] = None,
                              date: Optional[str] = None) -> str:
    """
    When and where a course runs (lectures and labs/tutorials).

    Args:
        course_code: Course code (e.g., 'CS101') or subject name.
        day: Optional day of the week to filter by; omit for the whole week.
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August'): the academic
            calendar reassigns some dates to another weekday, and only `date`
            resolves that.
    """
    try:
        day, note, err = _resolve_day(day, date)
        if err:
            return err
        results = timetable_service.get_course_schedule(course_code, day)
        if not results:
            return f"No scheduled classes for {course_code}{f' on {day}' if day else ''}{note}."
        lines = [f"Schedule for {course_code}{f' — {day}{note}' if day else ''}:"]
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
async def get_program_timetable(program_name: str, day: Optional[str] = None, semester: Optional[str] = None,
                                date: Optional[str] = None) -> str:
    """
    Timetable for a whole program/batch (lectures and labs).

    Args:
        program_name: Program/batch name (see list_programs).
        day: Optional day of the week to filter by; omit for the whole week.
        semester: Optional semester number ('1', '3', ...).
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August'): the academic
            calendar reassigns some dates to another weekday, and only `date`
            resolves that.
    """
    try:
        day, note, err = _resolve_day(day, date)
        if err:
            return err
        results = timetable_service.get_program_timetable(program_name, day, semester)
        if not results:
            return f"No classes for {program_name}{f' sem {semester}' if semester else ''}{f' on {day}' if day else ''}{note}."
        sem_str = f" (Sem {semester})" if semester else ""
        lines = [f"Schedule for {program_name}{sem_str}{f' — {day}{note}' if day else ''}:"]
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
async def get_room_schedule(room: str, day: Optional[str] = None,
                            date: Optional[str] = None) -> str:
    """
    Full-day occupancy of a room: every session (course, faculty, time) plus free gaps.
    Room matching ignores hyphens/spaces ('CEP209' == 'CEP-209').

    Args:
        room: Room name (e.g., 'CEP-209', 'LT-2').
        day: Optional day of week; omit for the whole week.
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August'): the academic
            calendar reassigns some dates to another weekday, and only `date`
            resolves that.
    """
    try:
        day, note, err = _resolve_day(day, date)
        if err:
            return err
        results = timetable_service.get_room_schedule(room, day)
        if not results:
            rooms = timetable_service.list_rooms()
            near = [r for r in rooms if room.replace("-", "").replace(" ", "").lower() in r.replace("-", "").replace(" ", "").lower()]
            hint = f" Close matches: {', '.join(near)}." if near else " See list_rooms."
            # Carry the resolved day and substitution note here too: "no sessions"
            # on a reassigned date is exactly when the caller needs to be told the
            # campus is running another day's timetable.
            when = f" on {day}{note}" if day else ""
            return f"No sessions found for room '{room}'{when}.{hint}"
        room_label = room.upper()
        lines = [f"Room {room_label}{f' — {day}{note}' if day else ''}:"]
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
async def find_free_rooms(day: Optional[str] = None, time: Optional[str] = None,
                          date: Optional[str] = None) -> str:
    """
    Rooms with no scheduled session at a given day+time.
    Omit day/time/date to use the current campus time.

    Args:
        day: Optional day of week; defaults to today.
        time: Optional 'HH:MM' 24h; defaults to now.
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August'): the academic
            calendar reassigns some dates to another weekday, and only `date`
            resolves that.
    """
    try:
        day, note, err = _resolve_day(day, date, default_to_today=True)
        if err:
            return err
        time = time or _campus_time()
        rooms = timetable_service.find_free_rooms(day, time)
        if not rooms:
            return f"No free rooms at {time} on {day}{note}."
        return f"Free at {time} {day}{note}: " + "; ".join(rooms)
    except Exception as e:
        logger.error(f"Error in find_free_rooms: {e}")
        return "Error querying free rooms."


@mcp.tool()
async def check_room_availability(room: str, day: Optional[str] = None, time: Optional[str] = None,
                                  date: Optional[str] = None) -> str:
    """
    Checks if a particular classroom or lab is available at a specific time, and if not, returns what class is currently happening there.

    Args:
        room: The classroom or lab name (e.g., 'cep-207', 'LT-1').
        day: Day of the week (e.g., 'Monday'); defaults to today.
        time: Time string (e.g., '14:00:00' or '2:00 PM'); defaults to now.
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August'): the academic
            calendar reassigns some dates to another weekday, and only `date`
            resolves that.
    """
    try:
        day, note, err = _resolve_day(day, date, default_to_today=True)
        if err:
            return err
        time = time or _campus_time()
        result = timetable_service.get_room_availability(room, day, time)
        if result:
            progs = f" [{', '.join(result['programs'])}]" if result.get("programs") else ""
            name_info = f" - {result['course_name']}" if result.get("course_name") else ""
            return (f"{room} NOT available at {time} {day}{note}: {result['session_type']} "
                    f"{result['course_code']}{name_info}{progs} with {result['faculty_name']}, "
                    f"{_hhmm(result['start_time'])}-{_hhmm(result['end_time'])}.")
        return f"{room} is free at {time} on {day}{note} (no scheduled class; caveat: unknown room names also report free — see list_rooms)."
    except Exception as e:
        logger.error(f"Error in check_room_availability: {e}")
        return "Error querying room availability."

if __name__ == "__main__":
    mcp.run()
