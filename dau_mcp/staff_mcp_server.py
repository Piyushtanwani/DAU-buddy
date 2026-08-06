"""
Staff MCP Server
================
Standalone MCP server exposing DA-IICT staff tools via stdio transport.

Run with:
    python -m dau_mcp.staff_mcp_server

Tools exposed:
  - list_staff
  - search_staff
  - get_staff_details
  - sync_staff_data
"""
from mcp.server.fastmcp import FastMCP
from core import config
from core.database import db_connection
from scrapers import staff_scraper
from api.context import user_role_var
from api.services.pagination import envelope
from api.services.name_matching import find_similar_names, fuzzy_match_notice

# ==============================================================================
# Server Setup
# ==============================================================================
mcp = FastMCP("DA-IICT Staff Server")
logger = config.get_logger("dau_mcp.staff_mcp_server")


# ==============================================================================
# Staff MCP Tools
# ==============================================================================
@mcp.tool()
def list_staff(limit: int = 50, offset: int = 0) -> dict:
    """
    List DA-IICT staff members (name | email | designation), alphabetical.

    Returns {total_matches, showing, more_available, results}. For more,
    advance offset by limit; if more_available is false, the list is complete.
    """
    logger.info(f"Tool 'list_staff' invoked (limit={limit}, offset={offset}).")
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT name, email, designation, count(*) OVER () FROM staff ORDER BY name LIMIT %s OFFSET %s;",
                    (limit, offset),
                )
                rows = cursor.fetchall()
                total = rows[0][3] if rows else 0
                return envelope(
                    [f"{name} | {email or '-'} | {desig or '-'}" for name, email, desig, _ in rows],
                    total, offset,
                )
    except Exception as e:
        logger.error(f"list_staff error: {e}")
        return {"error": "Error retrieving staff directory."}


@mcp.tool()
def search_staff(query: str) -> str:
    """
    Search for staff members matching a query string.
    Matches against names, designations, qualifications, and emails.
    
    IMPORTANT ROUTING RULES FOR AI AGENTS:
    - If the user asks about "WiFi", "Internet", or "Network" problems, search for "IT & SYSTEMS" or "Network".
    - If the user asks about "light", "AC", "fan", "electricity", or "power" problems, search for "Electrician", "Electrical", or "Maintenance".
    """
    logger.info(f"Tool 'search_staff' invoked — query: '{query}'")
    if not query.strip():
        return "Please enter a valid search term."
    pattern = f"%{query.strip()}%"
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT name, email, phone, address, qualification, designation, profile_url
                    FROM staff
                    WHERE name ILIKE %s OR designation ILIKE %s
                       OR qualification ILIKE %s OR email ILIKE %s
                    ORDER BY name;
                """, (pattern, pattern, pattern, pattern))
                rows = cursor.fetchall()
                if not rows:
                    return f"No staff matched: '{query}'."
                out = [f"### Staff Search Results for '{query}'", f"Found {len(rows)} record(s):", ""]
                for i, (name, email, phone, addr, qual, desig, url) in enumerate(rows, 1):
                    out.append(f"#### {i}. {name}")
                    if desig: out.append(f"- **Designation/Role:** {desig}")
                    if email: out.append(f"- **Email:** {email}")
                    if phone: out.append(f"- **Phone:** {phone}")
                    if addr:  out.append(f"- **Office Address:** {addr}")
                    if qual:  out.append(f"- **Qualification:** {qual}")
                    if url:   out.append(f"- **Profile:** [{url}]({url})")
                    out.append("")
                return "\n".join(out)
    except Exception as e:
        logger.error(f"search_staff error: {e}")
        return f"Error searching staff: {e}"


@mcp.tool()
def get_staff_details(name_or_email: str) -> str:
    """
    Retrieve the full detailed profile of a specific staff member by name or email.
    """
    logger.info(f"Tool 'get_staff_details' invoked — '{name_or_email}'")
    if not name_or_email.strip():
        return "Please enter a valid staff name or email."
    pattern = f"%{name_or_email.strip()}%"
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT name, email, phone, address, qualification,
                           designation, profile_url, image_url, scraped_at
                    FROM staff
                    WHERE name ILIKE %s OR email ILIKE %s
                    LIMIT 1;
                """, (pattern, pattern))
                row = cursor.fetchone()

                # Trigram similarity fallback, only after the exact lookup missed.
                fuzzy_notice = ""
                if not row:
                    for candidate in find_similar_names("staff", name_or_email, limit=1):
                        cursor.execute("""
                            SELECT name, email, phone, address, qualification,
                                   designation, profile_url, image_url, scraped_at
                            FROM staff
                            WHERE name = %s
                            LIMIT 1;
                        """, (candidate,))
                        row = cursor.fetchone()
                        if row:
                            fuzzy_notice = fuzzy_match_notice(name_or_email.strip(), candidate) + "\n"
                            break

                if not row:
                    return f"No staff member found matching '{name_or_email}'."
                name, email, phone, addr, qual, desig, url, img, ts = row
                out = [
                    f"### Detailed Staff Profile: {name}",
                    f"- **Role/Designation:** {desig or 'N/A'}",
                    f"- **Email Address:** {email or 'N/A'}",
                    f"- **Contact Number:** {phone or 'N/A'}",
                    f"- **Office Address:** {addr or 'N/A'}",
                    f"- **Qualifications:** {qual or 'N/A'}",
                ]
                if url: out.append(f"- **Profile URL:** [{url}]({url})")
                if img: out.append(f"- **Profile Image:** [{img}]({img})")
                out.append(f"- **Data Scraped At:** {ts.strftime('%Y-%m-%d %H:%M:%S')}")
                return fuzzy_notice + "\n".join(out)
    except Exception as e:
        logger.error(f"get_staff_details error: {e}")
        return f"Error retrieving staff details: {e}"


@mcp.tool()
def sync_staff_data() -> str:
    """
    Trigger a live scrape of the DA-IICT staff website and reload the database.
    """
    logger.info("Tool 'sync_staff_data' invoked.")
    
    role = user_role_var.get()
    if role not in ("Staff", "Faculty", "Admin"):
        return f"Unauthorized: Role '{role}' is not allowed to sync staff data."

    try:
        data = staff_scraper.scrape_staff_data()
        if not data:
            return "Failed to scrape staff directory. Check logs for details."
        staff_scraper.save_to_database(data)
        return f"Successfully synchronized {len(data)} staff profiles from the live DA-IICT website."
    except Exception as e:
        logger.error(f"sync_staff_data error: {e}")
        return f"Error syncing staff data: {e}"


# ==============================================================================
# Entry Point
# ==============================================================================
if __name__ == "__main__":
    logger.info("Starting DA-IICT Staff MCP Server (stdio transport)...")
    mcp.run()
