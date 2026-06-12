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

# ==============================================================================
# Server Setup
# ==============================================================================
mcp = FastMCP("DA-IICT Staff Server")
logger = config.get_logger("dau_mcp.staff_mcp_server")


# ==============================================================================
# Staff MCP Tools
# ==============================================================================
@mcp.tool()
def list_staff() -> str:
    """
    List all DA-IICT staff members with their names, emails, and designations.
    Use this to get a general directory of all staff.
    """
    logger.info("Tool 'list_staff' invoked.")
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT name, email, designation FROM staff ORDER BY name;")
                rows = cursor.fetchall()
                if not rows:
                    return "No staff members found. Please run sync_staff_data first."
                out = ["### DA-IICT Staff Directory", f"Total Staff Members: {len(rows)}", ""]
                for i, (name, email, desig) in enumerate(rows, 1):
                    desig_str = f" - *{desig}*" if desig else ""
                    out.append(f"{i}. **{name}** ({email or 'N/A'}){desig_str}")
                return "\n".join(out)
    except Exception as e:
        logger.error(f"list_staff error: {e}")
        return f"Error retrieving staff directory: {e}"


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
                return "\n".join(out)
    except Exception as e:
        logger.error(f"get_staff_details error: {e}")
        return f"Error retrieving staff details: {e}"


@mcp.tool()
def sync_staff_data() -> str:
    """
    Trigger a live scrape of the DA-IICT staff website and reload the database.
    """
    logger.info("Tool 'sync_staff_data' invoked.")
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
