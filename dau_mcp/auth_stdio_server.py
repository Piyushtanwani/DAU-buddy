"""
Authenticated Stdio MCP Server
==============================
A stdio wrapper around the unified MCP server that validates a DAU API key
read from the DAU_API_KEY environment variable before allowing any tools to run.

Claude Desktop config usage:
  {
    "mcpServers": {
      "daiict": {
        "command": "C:\\\\path\\\\to\\\\venv\\\\Scripts\\\\python.exe",
        "args": ["-m", "dau_mcp.auth_stdio_server"],
        "env": {
          "PYTHONPATH": "C:\\\\path\\\\to\\\\mcp-server",
          "DAU_API_KEY": "dau_sk_your_key_here"
        }
      }
    }
  }
"""
import sys
import os
import hashlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _validate_key(raw_key: str) -> tuple[bool, str]:
    """
    Validate the API key against the database.
    Returns (is_valid, email_or_error_msg).
    """
    if not raw_key or not raw_key.startswith("dau_sk_"):
        return False, "Key must start with dau_sk_"

    hashed = hashlib.sha256(raw_key.encode()).hexdigest()

    try:
        from core.database import db_connection
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT email, status FROM api_keys WHERE hashed_key = %s",
                    (hashed,)
                )
                row = cur.fetchone()

        if not row:
            return False, "Invalid API key — not found."

        email, status = row
        if status != "Active":
            return False, f"API key for {email} is {status}."

        # Stamp last_used
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE api_keys SET last_used = CURRENT_TIMESTAMP WHERE hashed_key = %s",
                    (hashed,)
                )

        return True, email

    except Exception as e:
        return False, f"Database error during auth: {e}"


def main():
    raw_key = os.getenv("DAU_API_KEY", "").strip()

    if not raw_key:
        print(
            "[DAU MCP] ERROR: DAU_API_KEY environment variable is not set.\n"
            "Add it to your claude_desktop_config.json env block.",
            file=sys.stderr
        )
        sys.exit(1)

    valid, result = _validate_key(raw_key)

    if not valid:
        print(f"[DAU MCP] ACCESS DENIED: {result}", file=sys.stderr)
        sys.exit(1)

    print(f"[DAU MCP] Authenticated as {result} — starting unified server.", file=sys.stderr)

    # ── All tools validated — run the unified stdio server ────────────────────
    from mcp.server.fastmcp import FastMCP

    from dau_mcp.faculty_mcp_server import (
        list_faculty, search_faculty, get_faculty_details,
        search_faculty_by_expertise, sync_faculty_data,
    )
    from dau_mcp.staff_mcp_server import (
        list_staff, search_staff, get_staff_details, sync_staff_data,
    )
    from dau_mcp.library_mcp_server import search_library_books, get_book_details
    from dau_mcp.timetable_mcp_server import (
        get_faculty_location, get_faculty_schedule, find_faculty_free_time,
        get_course_schedule, list_programs, get_program_timetable,
    )
    from dau_mcp.calendar_mcp_server import (
        get_next_holiday, get_upcoming_holidays, get_all_holidays,
        get_midsem_dates, get_endsem_dates, get_next_academic_event, search_calendar,
    )

    mcp = FastMCP("DA-IICT Unified Server")

    for tool in [
        list_faculty, search_faculty, get_faculty_details, search_faculty_by_expertise, sync_faculty_data,
        list_staff, search_staff, get_staff_details, sync_staff_data,
        search_library_books, get_book_details,
        get_faculty_location, get_faculty_schedule, find_faculty_free_time,
        get_course_schedule, list_programs, get_program_timetable,
        get_next_holiday, get_upcoming_holidays, get_all_holidays,
        get_midsem_dates, get_endsem_dates, get_next_academic_event, search_calendar,
    ]:
        mcp.add_tool(tool)

    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
