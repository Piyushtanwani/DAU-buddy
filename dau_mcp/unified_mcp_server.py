"""
Unified MCP Server
==================
Standalone MCP server exposing DA-IICT faculty, staff, and library tools via stdio transport.

Run with:
    python -m dau_mcp.unified_mcp_server
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import *
from mcp.server.fastmcp import FastMCP
from core import config

from dau_mcp.faculty_mcp_server import (
    list_faculty, search_faculty, get_faculty_details,
    search_faculty_by_expertise, sync_faculty_data
)
from dau_mcp.staff_mcp_server import (
    list_staff, search_staff, get_staff_details, sync_staff_data
)
from dau_mcp.library_mcp_server import (
    search_library_books, get_book_details
)
from dau_mcp.timetable_mcp_server import (
    get_faculty_location, get_faculty_schedule, find_faculty_free_time, get_course_schedule, get_program_timetable, list_programs
)
from dau_mcp.calendar_mcp_server import (
    get_next_holiday, get_upcoming_holidays, get_all_holidays, get_midsem_dates, get_endsem_dates, get_next_academic_event, search_calendar, get_events_by_date
)
from dau_mcp.scholar_mcp_server import (
    list_scholars, search_scholars, get_scholar_details, sync_scholar_data
)
from dau_mcp.documents_mcp_server import (
    search_academic_requirements, list_academic_documents,
    get_academic_document_pages, sync_academic_documents
)

# ==============================================================================
# Usage Tracking
# ==============================================================================
import functools
import inspect
from core.database import db_connection
from api.context import user_email_var, client_name_var

# ==============================================================================
# Server Setup
# ==============================================================================
mcp = FastMCP("DA-IICT Unified Server")
logger = config.get_logger("dau_mcp.unified_mcp_server")

# Register Faculty Tools
mcp.add_tool(list_faculty)
mcp.add_tool(search_faculty)
mcp.add_tool(get_faculty_details)
mcp.add_tool(search_faculty_by_expertise)
mcp.add_tool(sync_faculty_data)

# Register Staff Tools
mcp.add_tool(list_staff)
mcp.add_tool(search_staff)
mcp.add_tool(get_staff_details)
mcp.add_tool(sync_staff_data)

# Register Library Tools
mcp.add_tool(search_library_books)
mcp.add_tool(get_book_details)

# Register Timetable Tools
mcp.add_tool(get_faculty_location)
mcp.add_tool(get_faculty_schedule)
mcp.add_tool(find_faculty_free_time)
mcp.add_tool(get_course_schedule)
mcp.add_tool(list_programs)
mcp.add_tool(get_program_timetable)

# Register Calendar Tools
mcp.add_tool(get_next_holiday)
mcp.add_tool(get_upcoming_holidays)
mcp.add_tool(get_all_holidays)
mcp.add_tool(get_midsem_dates)
mcp.add_tool(get_endsem_dates)
mcp.add_tool(get_next_academic_event)
mcp.add_tool(search_calendar)
mcp.add_tool(get_events_by_date)

# Register Scholar Tools
mcp.add_tool(list_scholars)
mcp.add_tool(search_scholars)
mcp.add_tool(get_scholar_details)
mcp.add_tool(sync_scholar_data)

# Register Academic Document Tools
mcp.add_tool(search_academic_requirements)
mcp.add_tool(list_academic_documents)
mcp.add_tool(get_academic_document_pages)
mcp.add_tool(sync_academic_documents)

# ==============================================================================
# Usage Tracking (wrapping ToolManager.call_tool)
# ==============================================================================
_original_call_tool = mcp._tool_manager.call_tool

async def _tracking_call_tool(name, arguments, context=None, convert_result=False):
    """Wrapper that only logs to mcp_analytics on successful tool execution."""
    result = await _original_call_tool(name, arguments, context=context, convert_result=convert_result)
    
    # If we reach here, the tool executed successfully
    try:
        email = user_email_var.get()
        client_name = client_name_var.get()
        if email:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO mcp_analytics (user_email, tool_name, client_name) VALUES (%s, %s, %s)",
                        (email, name, client_name)
                    )
    except Exception as e:
        logger.error(f"Error tracking successful usage for {name}: {e}")
        
    return result

mcp._tool_manager.call_tool = _tracking_call_tool

# ==============================================================================
# Entry Point
# ==============================================================================
if __name__ == "__main__":
    logger.info("Starting DA-IICT Unified MCP Server (stdio transport)...")
    mcp.run()
