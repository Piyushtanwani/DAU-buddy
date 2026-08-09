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

def _get_poc(venue_name: str, meta_poc: Optional[str] = None) -> str:
    if meta_poc:
        return meta_poc
    v_upper = venue_name.upper()
    if "CEP" in v_upper:
        return "prabhunath_sharma@dau.ac.in"
    if "LAB" in v_upper or "LT" in v_upper:
        return "laboratory@dau.ac.in"
    return "Not available"


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
async def list_venues() -> str:
    """All venue names present in the timetable database."""
    try:
        venues = timetable_service.list_venues()
        if not venues:
            return "No venues found."
        return "Venues: " + "; ".join(venues)
    except Exception as e:
        logger.error(f"Error in list_venues: {e}")
        return "Error querying venues."


@mcp.tool()
async def get_venue_schedule(venue: str, day: Optional[str] = None,
                             date: Optional[str] = None) -> str:
    """
    Full-day occupancy of a venue: every session (course, faculty, time) plus free gaps.
    Venue matching ignores hyphens/spaces ('CEP209' == 'CEP-209').

    Args:
        venue: Venue name (e.g., 'CEP-209', 'LT-2').
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
        results = timetable_service.get_venue_schedule(venue, day)
        if not results:
            venues = timetable_service.list_venues()
            near = [r for r in venues if venue.replace("-", "").replace(" ", "").lower() in r.replace("-", "").replace(" ", "").lower()]
            hint = f" Close matches: {', '.join(near)}." if near else " See list_venues."
            when = f" on {day}{note}" if day else ""
            return f"No sessions found for venue '{venue}'{when}.{hint}"
        venue_label = venue.upper()
        lines = [f"Venue {venue_label}{f' — {day}{note}' if day else ''}:"]
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
        logger.error(f"Error in get_venue_schedule: {e}")
        return "Error querying venue schedule."


@mcp.tool()
async def find_free_venues(day: Optional[str] = None, time: Optional[str] = None,
                           date: Optional[str] = None, venue_type: Optional[str] = None) -> str:
    """
    Venues with no scheduled session at a given day+time, including capacity and POC info.
    Omit day/time/date to use the current campus time.

    Args:
        day: Optional day of week; defaults to today.
        time: Optional 'HH:MM' 24h; defaults to now.
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August'): the academic
            calendar reassigns some dates to another weekday, and only `date`
            resolves that.
        venue_type: Optional filter: 'room' (for CEP/classroom), 'lab', or 'lt'.
    """
    try:
        day, note, err = _resolve_day(day, date, default_to_today=True)
        if err:
            return err
        time = time or _campus_time()
        venues = timetable_service.find_free_venues(day, time)
        
        if venue_type:
            vt = venue_type.lower()
            if vt == "room":
                venues = [v for v in venues if "CEP" in v["venue_id"].upper()]
            elif vt == "lab":
                venues = [v for v in venues if "LAB" in v["venue_id"].upper()]
            elif vt == "lt":
                venues = [v for v in venues if "LT" in v["venue_id"].upper()]
                
        if not venues:
            return f"No free venues at {time} on {day}{note}."
            
        lines = [f"Free at {time} {day}{note}:"]
        for v in venues:
            vid = v['venue_id']
            cap = v.get('capacity')
            cap_str = f", Capacity: {cap}" if cap else ""
            lines.append(f"- {vid}{cap_str}")
        lines.append("\nBooking Contacts:\n- CEP rooms: prabhunath_sharma@dau.ac.in\n- Labs & LTs: laboratory@dau.ac.in")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error in find_free_venues: {e}")
        return "Error querying free venues."


@mcp.tool()
async def check_venue_availability(venue: str, day: Optional[str] = None, time: Optional[str] = None,
                                   date: Optional[str] = None) -> str:
    """
    Checks if a particular classroom or lab is available at a specific time. Returns metadata (capacity, POC) if free, or the occupying class if busy.

    Args:
        venue: The classroom or lab name (e.g., 'cep-207', 'LT-1').
        day: Day of the week (e.g., 'Monday'); defaults to today.
        time: Time string (e.g., '14:00:00' or '2:00 PM'); defaults to now.
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August').
    """
    try:
        day, note, err = _resolve_day(day, date, default_to_today=True)
        if err:
            return err
        time = time or _campus_time()
        result = timetable_service.get_venue_availability(venue, day, time)
        if result:
            progs = f" [{', '.join(result['programs'])}]" if result.get("programs") else ""
            name_info = f" - {result['course_name']}" if result.get("course_name") else ""
            
            cap = result.get('capacity')
            cap_str = f" [Cap: {cap}]" if cap else ""
            poc = _get_poc(venue, result.get('booking_poc'))
            
            return (f"{venue}{cap_str} (POC: {poc}) is NOT available at {time} {day}{note}: {result['session_type']} "
                    f"{result['course_code']}{name_info}{progs} with {result['faculty_name']}, "
                    f"{_hhmm(result['start_time'])}-{_hhmm(result['end_time'])}.")
                    
        # If None returned from timetable service, it's free. We can fetch standalone metadata:
        from api.services import venue_service
        meta = venue_service.get_venue(venue)
        
        cap_str = ""
        poc = _get_poc(venue, None)
        if meta:
            cap = meta.get('capacity')
            if cap:
                cap_str = f" [Cap: {cap}]"
            poc = _get_poc(venue, meta.get('booking_poc'))
            
        return f"{venue}{cap_str} (POC: {poc}) is free at {time} on {day}{note}."
    except Exception as e:
        logger.error(f"Error in check_venue_availability: {e}")
        return "Error querying venue availability."


@mcp.tool()
async def search_venues(min_capacity: int, venue_type: Optional[str] = None) -> str:
    """
    Search for venues matching a minimum capacity requirement.
    
    Args:
        min_capacity: The minimum capacity required.
        venue_type: Optional filter: 'room' (for CEP/classroom), 'lab', or 'lt'.
    """
    try:
        from api.services import venue_service
        venues = venue_service.search_venues_by_capacity(min_capacity)
        
        if venue_type:
            vt = venue_type.lower()
            if vt == "room":
                venues = [v for v in venues if "CEP" in v["venue_id"].upper()]
            elif vt == "lab":
                venues = [v for v in venues if "LAB" in v["venue_id"].upper()]
            elif vt == "lt":
                venues = [v for v in venues if "LT" in v["venue_id"].upper()]
                
        if not venues:
            return f"No venues found with capacity >= {min_capacity}."
            
        lines = [f"Venues with capacity >= {min_capacity}:"]
        for v in venues:
            vid = v['venue_id']
            cap = v['capacity']
            lines.append(f"- {vid}: Capacity {cap}")
        lines.append("\nBooking Contacts:\n- CEP rooms: prabhunath_sharma@dau.ac.in\n- Labs & LTs: laboratory@dau.ac.in")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error in search_venues: {e}")
        return "Error searching venues."


@mcp.tool()
async def get_venue_info(venue_id: str) -> str:
    """
    Retrieve detailed metadata (capacity, POC) for a single venue.
    """
    try:
        from api.services import venue_service
        meta = venue_service.get_venue(venue_id)
        if not meta:
            return f"No metadata found for venue '{venue_id}'."
            
        cap = meta.get('capacity')
        poc = _get_poc(venue_id, meta.get('booking_poc'))
        return f"Venue: {venue_id}\nCapacity: {cap}\nBooking POC: {poc}"
    except Exception as e:
        logger.error(f"Error in get_venue_info: {e}")
        return "Error retrieving venue info."


@mcp.tool()
async def find_available_venues(min_capacity: int, day: Optional[str] = None, start_time: Optional[str] = None,
                                end_time: Optional[str] = None, date: Optional[str] = None, venue_type: Optional[str] = None) -> str:
    """
    Find venues that are BOTH available in the timetable during the specified window AND meet the minimum capacity requirement.
    Omit day/time to use current campus time.

    Args:
        min_capacity: Minimum capacity required.
        day: Optional day of week; defaults to today.
        start_time: Start time 'HH:MM'; defaults to now.
        end_time: End time 'HH:MM'; defaults to start_time + 1 hour.
        date: Optional 'YYYY-MM-DD'.
        venue_type: Optional filter: 'room' (for CEP/classroom), 'lab', or 'lt'.
    """
    try:
        day, note, err = _resolve_day(day, date, default_to_today=True)
        if err:
            return err
        start_time = start_time or _campus_time()
        
        # We need to find venues free for the whole block. 
        # A simple approach for this POC tool is to just check the start_time using find_free_venues,
        # but technically we should check overlap. The provided find_free_venues takes a point in time.
        # Let's use the point in time (start_time) as requested by the original find_free_rooms logic.
        venues = timetable_service.find_free_venues(day, start_time)
        
        if venue_type:
            vt = venue_type.lower()
            if vt == "room":
                venues = [v for v in venues if "CEP" in v["venue_id"].upper()]
            elif vt == "lab":
                venues = [v for v in venues if "LAB" in v["venue_id"].upper()]
            elif vt == "lt":
                venues = [v for v in venues if "LT" in v["venue_id"].upper()]
                
        if not venues:
            return f"No venues free at {start_time} on {day}{note}."
            
        # Filter by capacity
        suitable = [v for v in venues if v.get('capacity') and v['capacity'] >= min_capacity]
        if not suitable:
            return f"No venues free at {start_time} on {day}{note} with capacity >= {min_capacity}."
            
        # Sort by capacity ascending (tightest fit first)
        suitable.sort(key=lambda x: x['capacity'])
        
        lines = [f"Available venues (>= {min_capacity} capacity) at {start_time} {day}{note}:"]
        for v in suitable:
            vid = v['venue_id']
            cap = v['capacity']
            lines.append(f"- {vid}: Capacity {cap}")
        lines.append("\nBooking Contacts:\n- CEP rooms: prabhunath_sharma@dau.ac.in\n- Labs & LTs: laboratory@dau.ac.in")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error in find_available_venues: {e}")
        return "Error finding available venues."

if __name__ == "__main__":
    mcp.run()
