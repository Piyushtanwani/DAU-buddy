import os
import sys
from typing import Dict, Any, List, Optional
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp.server.fastmcp import FastMCP
from core import config
from api.services import calendar_service

logger = config.get_logger("dau_mcp.calendar_mcp_server")

mcp = FastMCP("calendar_mcp")

def format_date(date_obj) -> str:
    if date_obj is None:
        return ""
    if hasattr(date_obj, "strftime"):
        return date_obj.strftime("%Y-%m-%d")
    return str(date_obj)

def serialize_records(records: List[Dict[str, Any]]) -> str:
    formatted_records = []
    for r in records:
        r_copy = dict(r)
        if 'start_date' in r_copy:
            r_copy['start_date'] = format_date(r_copy['start_date'])
        if 'end_date' in r_copy:
            r_copy['end_date'] = format_date(r_copy['end_date'])
        if 'holiday_date' in r_copy:
            r_copy['holiday_date'] = format_date(r_copy['holiday_date'])
        formatted_records.append(r_copy)
    return json.dumps(formatted_records, indent=2)

@mcp.tool()
async def get_next_holiday() -> str:
    """
    Returns the next upcoming holiday for DA-IICT.
    """
    logger.info("Executing get_next_holiday tool")
    try:
        holiday = calendar_service.get_next_holiday()
        if not holiday:
            return "No upcoming holidays found."
        return serialize_records([holiday])
    except Exception as e:
        logger.error(f"Error in get_next_holiday: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
async def get_upcoming_holidays(limit: int = 5) -> str:
    """
    Returns a list of upcoming DA-IICT holidays.
    
    Args:
        limit: Number of holidays to return (default: 5).
    """
    logger.info(f"Executing get_upcoming_holidays tool with limit={limit}")
    try:
        holidays = calendar_service.get_upcoming_holidays(limit)
        if not holidays:
            return "No upcoming holidays found."
        return serialize_records(holidays)
    except Exception as e:
        logger.error(f"Error in get_upcoming_holidays: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
async def get_all_holidays() -> str:
    """
    Returns a list of all holidays for the entire year, regardless of the current date.
    """
    try:
        results = calendar_service.get_all_holidays()
        if not results:
            return "No holidays found in the system."
        
        return serialize_records(results)
    except Exception as e:
        logger.error(f"Error getting all holidays: {e}")
        return f"Error retrieving holidays: {str(e)}"

@mcp.tool()
async def get_midsem_dates() -> str:
    """
    Returns the dates for DA-IICT mid-semester (in-sem) exams.
    """
    logger.info("Executing get_midsem_dates tool")
    try:
        events = calendar_service.get_midsem_dates()
        if not events:
            return "No mid-semester dates found in the calendar."
        return serialize_records(events)
    except Exception as e:
        logger.error(f"Error in get_midsem_dates: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
async def get_endsem_dates() -> str:
    """
    Returns the dates for DA-IICT end-semester exams.
    """
    logger.info("Executing get_endsem_dates tool")
    try:
        events = calendar_service.get_endsem_dates()
        if not events:
            return "No end-semester dates found in the calendar."
        return serialize_records(events)
    except Exception as e:
        logger.error(f"Error in get_endsem_dates: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
async def get_next_academic_event() -> str:
    """
    Returns the very next upcoming academic calendar event for DA-IICT.
    """
    logger.info("Executing get_next_academic_event tool")
    try:
        event = calendar_service.get_next_academic_event()
        if not event:
            return "No upcoming academic events found."
        return serialize_records([event])
    except Exception as e:
        logger.error(f"Error in get_next_academic_event: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
async def search_calendar(query: str, semester: Optional[int] = None) -> str:
    """
    Searches the calendar for specific events or holidays using a text query.
    Optionally provide semester (e.g., 1, 2, 3) to automatically filter by Autumn (odd semesters) or Winter (even semesters).
    """
    logger.info(f"Executing search_calendar tool with query: {query}, semester: {semester}")
    try:
        results = calendar_service.search_calendar(query, semester=semester)
        if not results['academic_events'] and not results['holidays']:
            return f"No events found for query: '{query}'"
        
        output = []
        if results['academic_events']:
            output.append("=== Academic Events ===")
            output.append(serialize_records(results['academic_events']))
        if results['holidays']:
            output.append("=== Holidays ===")
            output.append(serialize_records(results['holidays']))
            
        return "\n".join(output)
    except Exception as e:
        logger.error(f"Error in search_calendar: {e}")
        return f"Error: {str(e)}"

@mcp.tool()
async def get_events_by_date(date_str: str) -> str:
    """
    Finds academic events or holidays that fall on a specific date.
    Args:
        date_str: The date to check, in YYYY-MM-DD format (e.g. '2024-07-20').
    """
    logger.info(f"Executing get_events_by_date tool for date: {date_str}")
    try:
        results = calendar_service.get_events_by_date(date_str)
        if not results['academic_events'] and not results['holidays']:
            return f"No events found for date: {date_str}"
        
        output = []
        if results['academic_events']:
            output.append("=== Academic Events ===")
            output.append(serialize_records(results['academic_events']))
        if results['holidays']:
            output.append("=== Holidays ===")
            output.append(serialize_records(results['holidays']))
            
        return "\n".join(output)
    except ValueError:
        return "Error: Invalid date format. Please use YYYY-MM-DD format."
    except Exception as e:
        logger.error(f"Error in get_events_by_date: {e}")
        return f"Error: {str(e)}"
