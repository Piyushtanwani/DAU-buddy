import os
import sys
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config
from api.services import timetable_service
from api.services import calendar_service
from core.utils.program import normalize_program_name, resolve_program

class ProgramQuery(BaseModel):
    program_name: str = Field(description="Program/batch name (e.g., 'B Tech (ICT and CS)')")
    semester: Optional[str] = Field(default=None, description="Optional semester number ('1', '3', '7', etc.)")

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

def _derive_end_time(start_time: str) -> str:
    """Add DEFAULT_VENUE_DURATION_MINUTES to start_time HH:MM."""
    try:
        # handle partial times like '14:00:00' if it's from _campus_time
        time_format = "%H:%M:%S" if start_time.count(":") == 2 else "%H:%M"
        t = datetime.strptime(start_time, time_format)
        t += timedelta(minutes=config.DEFAULT_VENUE_DURATION_MINUTES)
        return t.strftime("%H:%M")
    except ValueError:
        return start_time



def _is_elective_course(course_type: Optional[str]) -> bool:
    return "elective" in (course_type or "").lower()


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
            office = ""
            email_addr = ""
            try:
                db_name = name.split(" (")[0]
                from core.database import db_connection
                with db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT address, email FROM faculty WHERE name ILIKE %s LIMIT 1", (f"{db_name}%",))
                        row = cur.fetchone()
                        if row:
                            if row[0]:
                                office = ", ".join(row[0].split(',')[:2]).strip()
                            if row[1]:
                                email_addr = row[1]
            except Exception:
                pass
            
            base_msg = f"{name}: no class at {time} on {day}{note}."
            if office or email_addr:
                contact_info = []
                if office: contact_info.append(f"Office: {office}")
                if email_addr: contact_info.append(f"Email: {email_addr}")
                base_msg += f" (AI INSTRUCTION: You MUST explicitly include the following contact information in your final answer to the user) Since they have no class right now, they are likely in their office. {', '.join(contact_info)}. You can contact them directly."
            return base_msg
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
        day: Day of the week (e.g., 'Monday', or 'All' for whole week); defaults to today.
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August'): the academic
            calendar reassigns some dates to another weekday, and only `date`
            resolves that.
    """
    try:
        if not date and day and day.lower() == "all":
            results = []
            name = ""
            for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
                data = timetable_service.get_free_time(faculty_name, d)
                if "candidates" in data:
                    return _resolution_error(data["query"], data["candidates"])
                name = data["faculty"]
                if not data["busy_slots"]:
                    results.append(f"{d}: Free all day")
                elif not data["free_slots"]:
                    results.append(f"{d}: No free time")
                else:
                    results.append(f"{d}: " + ", ".join(data["free_slots"]))
            return f"{name} free time for the whole week:\n" + "\n".join(results)

        day, note, err = _resolve_day(day, date, default_to_today=True)
        if err:
            return err
        data = timetable_service.get_free_time(faculty_name, day)
        if "candidates" in data:
            return _resolution_error(data["query"], data["candidates"])
        name = data["faculty"]
        office = ""
        email_addr = ""
        try:
            db_name = name.split(" (")[0]
            from core.database import db_connection
            with db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT address, email FROM faculty WHERE name ILIKE %s LIMIT 1", (f"{db_name}%",))
                    row = cur.fetchone()
                    if row:
                        if row[0]:
                            office = ", ".join(row[0].split(',')[:2]).strip()
                        if row[1]:
                            email_addr = row[1]
        except Exception:
            pass
            
        if not data["busy_slots"]:
            base_msg = f"{name}: no classes on {day}{note} — free all day."
            if office or email_addr:
                contact_info = []
                if office: contact_info.append(f"Office: {office}")
                if email_addr: contact_info.append(f"Email: {email_addr}")
                base_msg += f" (AI INSTRUCTION: You MUST explicitly include the following contact information in your final answer to the user) Since they have no classes, they may be in their office. {', '.join(contact_info)}. You can contact them to schedule a meeting."
            return base_msg
            
        if not data["free_slots"]:
            return f"{name}: no free time on {day}{note}."
        
        base_msg = f"{name} is free on {day}{note} during these times: " + ", ".join(data["free_slots"])
        if office or email_addr:
            contact_info = []
            if office: contact_info.append(f"Office: {office}")
            if email_addr: contact_info.append(f"Email: {email_addr}")
            base_msg += f". (AI INSTRUCTION: You MUST explicitly include the following contact information in your final answer to the user) During their free time, they may be in their office. {', '.join(contact_info)}. You can contact them to schedule a meeting."
        return base_msg
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
        day: Day of the week (e.g., 'Monday', or 'All' for whole week); defaults to today.
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August'): the academic
            calendar reassigns some dates to another weekday, and only `date`
            resolves that.
    """
    try:
        if not date and day and day.lower() == "all":
            results = []
            who = ""
            for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
                data = timetable_service.get_common_free_time(faculty_names, d)
                if "candidates" in data:
                    return _resolution_error(data["query"], data["candidates"])
                who = ", ".join(data["faculty"])
                if not data["free_slots"]:
                    results.append(f"{d}: None")
                else:
                    results.append(f"{d}: " + ", ".join(data["free_slots"]))
            return f"Common free slots for the whole week ({who}):\n" + "\n".join(results)

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
async def find_programs_common_free_time(programs: List[ProgramQuery], day: Optional[str] = None,
                                         date: Optional[str] = None) -> str:
    """
    Find common free slots for multiple programs/batches on a given day.
    (gaps in the union of their class schedules, 08:00-18:00).

    Args:
        programs: A list of objects, each containing 'program_name' (e.g., 'MSc (IT)') and optional 'semester' (e.g., '3').
        day: Day of the week (e.g., 'Monday', or 'All' for whole week); defaults to today.
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date.
    """
    try:
        if not programs:
            return "Please provide at least one valid programme name in the 'programs' list."

        resolved_queries = []
        for p in programs:
            p_name = p.program_name
            if not p_name:
                return "Please provide at least one valid programme name."
                
            matches = resolve_program(p_name)
            if not matches:
                return f"I couldn't find the programme '{p_name}'. Please use the 'list_programs' tool to find the exact name."
            if len(matches) > 1:
                return f"The programme '{p_name}' is ambiguous. It could match: {', '.join(matches)}. Please clarify which one you mean."
                
            resolved_queries.append({
                "program_name": matches[0],
                "semester": p.semester
            })

        if not date and day and day.lower() == "all":
            results = []
            who = ""
            for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
                data = timetable_service.get_programs_common_free_time(resolved_queries, d)
                who = ", ".join(data["programs"])
                if not data["free_slots"]:
                    results.append(f"{d}: None")
                else:
                    results.append(f"{d}: " + ", ".join(data["free_slots"]))
            return f"Common free slots for the whole week ({who}):\n" + "\n".join(results)

        day, note, err = _resolve_day(day, date, default_to_today=True)
        if err:
            return err
            
        data = timetable_service.get_programs_common_free_time(resolved_queries, day)
        who = ", ".join(data["programs"])
        if not data["free_slots"]:
            return f"No common free time on {day}{note} for {who}."
        return f"Common free on {day}{note} ({who}): " + ", ".join(data["free_slots"])
    except Exception as e:
        logger.error(f"Error in find_programs_common_free_time: {e}")
        return "Error querying common free time for programs."



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
    
    IMPORTANT: B.Tech and M.Tech higher semesters (e.g., Sem 7, Sem 8) often consist primarily or entirely of electives. 
    If this tool returns empty for a higher semester, or if the user specifically asks for electives, you MUST also use 
    the `get_electives` tool to provide them with the available elective courses.

    Args:
        program_name: Program/batch name (see list_programs). If the programme name is ambiguous: 1. Call list_programs. 2. Find the exact match. 3. If multiple remain plausible, ask the user. 4. Never silently choose one or guess.
        day: Optional day of the week to filter by; omit for the whole week.
        semester: Optional semester number ('1', '3', ...).
        date: Optional 'YYYY-MM-DD'. PREFER THIS over `day` whenever the user
            means a particular date ('tomorrow', '7 August').
    """
    try:
        day, note, err = _resolve_day(day, date)
        if err:
            return err
            
        matches = resolve_program(program_name)
        if not matches:
            return f"I couldn't find the programme '{program_name}'. Please use the 'list_programs' tool to find the exact name."
        if len(matches) > 1:
            return f"The programme '{program_name}' is ambiguous. It could match: {', '.join(matches)}. Please clarify which one you mean."
        
        resolved_program = matches[0]
        results = timetable_service.get_program_timetable(resolved_program, day, semester)
        sem_str = f" (Sem {semester})" if semester else ""
        
        seen_slots = set()
        
        # Determine if we have actual core courses
        has_core = any(not _is_elective_course(r.get("course_type")) for r in results)
        
        lines = []
        if has_core:
            lines = [f"Core Schedule for {resolved_program}{sem_str}{f' — {day}{note}' if day else ''}:"]
        else:
            lines = [f"No core schedule found for {resolved_program}{sem_str}{f' on {day}' if day else ''}{note}."]
            if semester:
                lines[0] += " However, this semester primarily consists of electives. Here is the schedule of available electives:"
                
        for r in results:
            slot_key = (r['course_code'], r['day_of_week'], _hhmm(r['start_time']), _hhmm(r['end_time']), r['room'], r['session_type'])
            
            # Print core courses here only if there is a core block
            if has_core and not _is_elective_course(r.get("course_type")):
                # We track all printed core slots
                seen_slots.add(slot_key)
                name_info = f" - {r['course_name']}" if r.get("course_name") else ""
                type_info = f" [{r['course_type']}]" if r.get("course_type") else ""
                lines.append(f"- {r['day_of_week']} {_hhmm(r['start_time'])}-{_hhmm(r['end_time'])}: "
                             f"{r['session_type']} {r['course_code']}{type_info}{name_info} "
                             f"with {r['faculty_name']} in {r['room']}")

        if semester:
            electives_sched = timetable_service.get_electives_schedule(resolved_program, semester, day)
            if electives_sched:
                if has_core:
                    lines.append(f"\nAdditionally, here is the schedule for all available electives:")
                
                for r in electives_sched:
                    slot_key = (r['course_code'], r['day_of_week'], _hhmm(r['start_time']), _hhmm(r['end_time']), r['room'], r['session_type'])
                    if slot_key in seen_slots:
                        continue
                    seen_slots.add(slot_key)
                    
                    name_info = f" - {r['course_name']}" if r.get("course_name") else ""
                    type_info = f" [{r['course_type']}]" if r.get("course_type") else ""
                    lines.append(f"- {r['day_of_week']} {_hhmm(r['start_time'])}-{_hhmm(r['end_time'])}: "
                                 f"{r['session_type']} {r['course_code']}{type_info}{name_info} "
                                 f"with {r['faculty_name']} in {r['room']}")

        if len(lines) > 1:
            return "\n".join(lines)
        return lines[0]
    except Exception as e:
        logger.error(f"Error in get_program_timetable: {e}")
        return "Error querying program timetable."


@mcp.tool()
async def get_electives(program_name: Optional[str] = None, semester: Optional[str] = None) -> str:
    """
    Retrieve a list of elective courses, optionally filtered by an exact program name (e.g. 'B Tech (ICT and CS)') and semester.
    Use this when users ask for electives generally or for a specific program.

    Args:
        program_name: Optional exact program name.
        semester: Optional semester number.
    """
    try:
        results = timetable_service.get_electives(program_name, semester)
        if not results:
            sem_str = f" Sem {semester}" if semester else ""
            return f"No electives found{f' for {program_name}{sem_str}' if program_name else ''}."
            
        sem_str = f" Sem {semester}" if semester else ""
        lines = [f"Electives{f' for {program_name}{sem_str}' if program_name else ''}:"]
        for r in results:
            programs_list = r.get('programs', [])
            programs_str = f" [{', '.join(programs_list)}]" if programs_list else ""
            lines.append(f"- {r['course_code']} - {r['course_name']} ({r['course_type']}){programs_str}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error in get_electives: {e}")
        return "Error querying electives."



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
        start_time = time or _campus_time()
        end_time = _derive_end_time(start_time)
        venues = timetable_service.find_free_venues(day, start_time, end_time)
        
        if venue_type:
            vt = venue_type.lower()
            if vt == "room":
                venues = [v for v in venues if "CEP" in v["venue_id"].upper()]
            elif vt == "lab":
                venues = [v for v in venues if "LAB" in v["venue_id"].upper()]
            elif vt == "lt":
                venues = [v for v in venues if "LT" in v["venue_id"].upper()]
                
        if not venues:
            return f"No free venues from {start_time} to {end_time} on {day}{note}."
            
        lines = [f"Free from {start_time} to {end_time} on {day}{note}:"]
        for v in venues:
            vid = v['venue_id']
            cap = v.get('capacity')
            cap_str = f", Capacity: {cap}" if cap and cap > 1 else ""
            lines.append(f"- {vid}{cap_str}")
            
        from core import config
        lines.append("")
        lines.append(f"Note: For CEP rooms contact {config.CEP_BOOKING_POC}. For LABs and LT contact {config.LAB_LT_BOOKING_POC}.")
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
            poc = result.get('booking_poc') or "Not available"
            
            return (f"{venue}{cap_str} (POC: {poc}) is NOT available at {time} {day}{note}: {result['session_type']} "
                    f"{result['course_code']}{name_info}{progs} with {result['faculty_name']}, "
                    f"{_hhmm(result['start_time'])}-{_hhmm(result['end_time'])}.")
                    
        # If None returned from timetable service, it's free. We can fetch standalone metadata:
        from api.services import venue_service
        meta = venue_service.get_venue(venue)
        
        if not meta:
            return f"Venue '{venue}' not found in our records."
            
        cap = meta.get('capacity')
        cap_str = f" [Cap: {cap}]" if cap else ""
        poc = meta.get('booking_poc') or "Not available"
            
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
            poc = v.get('booking_poc') or "Not available"
            lines.append(f"- {vid}: Capacity {cap} (POC: {poc})")
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
        poc = meta.get('booking_poc') or "Not available"
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
        
        effective_start = start_time or _campus_time()
        effective_end = end_time if end_time else _derive_end_time(effective_start)
        
        venues = timetable_service.find_free_venues(day, effective_start, effective_end)
        
        if venue_type:
            vt = venue_type.lower()
            if vt == "room":
                venues = [v for v in venues if "CEP" in v["venue_id"].upper()]
            elif vt == "lab":
                venues = [v for v in venues if "LAB" in v["venue_id"].upper()]
            elif vt == "lt":
                venues = [v for v in venues if "LT" in v["venue_id"].upper()]
                
        if not venues:
            return f"No venues free from {effective_start} to {effective_end} on {day}{note}."
            
        # Filter by capacity
        suitable = [v for v in venues if v.get('capacity') and v['capacity'] >= min_capacity]
        if not suitable:
            return f"No venues free from {effective_start} to {effective_end} on {day}{note} with capacity >= {min_capacity}."
            
        # Sort by capacity ascending (tightest fit first)
        suitable.sort(key=lambda x: x['capacity'])
        
        lines = [f"Available venues (>= {min_capacity} capacity) from {effective_start} to {effective_end} on {day}{note}:"]
        for v in suitable:
            vid = v['venue_id']
            cap = v['capacity']
            poc = v.get('booking_poc') or "Not available"
            lines.append(f"- {vid}: Capacity {cap} (POC: {poc})")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error in find_available_venues: {e}")
        return "Error finding available venues."

if __name__ == "__main__":
    mcp.run()
