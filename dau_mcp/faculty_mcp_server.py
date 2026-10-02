"""
Faculty MCP Server
==================
Standalone MCP server exposing DA-IICT faculty tools via stdio transport.

Run with:
    python -m dau_mcp.faculty_mcp_server

Tools exposed:
  - list_faculty
  - search_faculty
  - get_faculty_details
  - search_faculty_by_expertise
  - sync_faculty_data
"""
from mcp.server.fastmcp import FastMCP
from core import config
from core.database import db_connection
from api.services.pagination import envelope
from api.services.name_matching import find_similar_names, fuzzy_match_notice
from scrapers import faculty_scraper
from api.context import user_role_var

# ==============================================================================
# Server Setup
# ==============================================================================
mcp = FastMCP("DA-IICT Faculty Server")
logger = config.get_logger("dau_mcp.faculty_mcp_server")


# ==============================================================================
# Faculty MCP Tools
# ==============================================================================
@mcp.tool()
def list_faculty(limit: int = 50, offset: int = 0) -> dict:
    """
    List DA-IICT faculty members (name | email | type), alphabetical.

    Returns {total_matches, showing, more_available, results}. For more,
    advance offset by limit; if more_available is false, the list is complete.
    """
    logger.info(f"Tool 'list_faculty' invoked (limit={limit}, offset={offset}).")
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT name, email, faculty_type, count(*) OVER () FROM faculty ORDER BY name LIMIT %s OFFSET %s;",
                    (limit, offset),
                )
                rows = cursor.fetchall()
                total = rows[0][3] if rows else 0
                return envelope(
                    [f"{name} | {email or '-'} | {ftype}" for name, email, ftype, _ in rows],
                    total, offset,
                )
    except Exception as e:
        logger.error(f"list_faculty error: {e}")
        return {"error": "Error retrieving faculty directory."}


@mcp.tool()
def search_faculty(query: str) -> str:
    """
    Search for faculty members matching a query string.
    Matches against names, specializations, education, and emails.
    """
    logger.info(f"Tool 'search_faculty' invoked — query: '{query}'")
    if not query.strip():
        return "Please enter a valid search term."
    pattern = f"%{query.strip()}%"
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT name, email, phone, address, education, specialization,
                           profile_url, faculty_type
                    FROM faculty
                    WHERE name ILIKE %s OR specialization ILIKE %s
                       OR education ILIKE %s OR email ILIKE %s
                    ORDER BY name;
                """, (pattern, pattern, pattern, pattern))
                rows = cursor.fetchall()
                if not rows:
                    return f"No faculty matched: '{query}'."
                # Compact one-liners; full profile available via get_faculty_details.
                out = [f"{len(rows)} match(es) for '{query}' (name | type | email | phone | office):"]
                for name, email, phone, addr, edu, spec, url, ftype in rows:
                    office = addr.split(",")[0].strip() if addr else "-"
                    out.append(f"- {name} | {ftype} | {email or '-'} | {phone or '-'} | {office}")
                out.append("Use get_faculty_details for education/specialization/profile.")
                return "\n".join(out)
    except Exception as e:
        logger.error(f"search_faculty error: {e}")
        return f"Error searching faculty: {e}"


@mcp.tool()
def get_faculty_details(name_or_email: str) -> str:
    """
    Retrieve the full detailed profile of a specific faculty member by name or email.
    """
    logger.info(f"Tool 'get_faculty_details' invoked — '{name_or_email}'")
    if not name_or_email.strip():
        return "Please enter a valid faculty name or email."
    pattern = f"%{name_or_email.strip()}%"
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT name, email, phone, address, education, specialization,
                           profile_url, image_url, faculty_type, scraped_at
                    FROM faculty
                    WHERE name ILIKE %s OR email ILIKE %s
                    LIMIT 1;
                """, (pattern, pattern))
                row = cursor.fetchone()

                # Trigram similarity fallback, only after the exact lookup missed.
                fuzzy_notice = ""
                if not row:
                    # The cursor above is still open, so it is reused rather
                    # than checking a second connection out of the pool.
                    for candidate in find_similar_names(
                        "faculty",
                        name_or_email,
                        limit=1,
                        cursor=cursor,
                    ):
                        cursor.execute("""
                            SELECT name, email, phone, address, education, specialization,
                                   profile_url, image_url, faculty_type, scraped_at
                            FROM faculty
                            WHERE name = %s
                            LIMIT 1;
                        """, (candidate,))
                        row = cursor.fetchone()
                        if row:
                            fuzzy_notice = fuzzy_match_notice(name_or_email.strip(), candidate) + "\n"
                            break

                if not row:
                    return f"No faculty member found matching '{name_or_email}'."
                name, email, phone, addr, edu, spec, url, img, ftype, ts = row
                out = [
                    f"### Detailed Profile: {name}",
                    f"- **Faculty Designation:** {ftype} Faculty",
                    f"- **Email Address:** {email or 'N/A'}",
                    f"- **Contact Number:** {phone or 'N/A'}",
                    f"- **Office/Campus Address:** {addr or 'N/A'}",
                    f"- **Education Background:** {edu or 'N/A'}",
                    f"- **Areas of Specialization:** {spec or 'N/A'}",
                ]
                if url: out.append(f"- **Profile URL:** [{url}]({url})")
                if img: out.append(f"- **Profile Image:** [{img}]({img})")
                out.append(f"- **Data Scraped At:** {ts.strftime('%Y-%m-%d %H:%M:%S')}")
                return fuzzy_notice + "\n".join(out)
    except Exception as e:
        logger.error(f"get_faculty_details error: {e}")
        return f"Error retrieving faculty details: {e}"


@mcp.tool()
def search_faculty_by_expertise(expertise: str) -> str:
    """
    Search for faculty members by specific area(s) of expertise / specialization.
    Supports comma, 'and', or 'or' separated terms.
    """
    logger.info(f"Tool 'search_faculty_by_expertise' invoked — '{expertise}'")
    if not expertise.strip():
        return "Please enter a valid area of expertise."
    import re
    terms = [
        t.strip().replace("meachine", "machine")
        for t in re.split(r",|\s+and\s+|\s+or\s+", expertise, flags=re.IGNORECASE)
        if t.strip()
    ]
    if not terms:
        return f"No valid search terms extracted from: '{expertise}'."
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                clauses = " OR ".join(["specialization ILIKE %s"] * len(terms))
                params = tuple(f"%{t}%" for t in terms)
                cursor.execute(
                    f"SELECT name, email, phone, address, education, specialization, "
                    f"profile_url, faculty_type FROM faculty WHERE {clauses} ORDER BY name;",
                    params,
                )
                rows = cursor.fetchall()
                if not rows:
                    return f"No faculty found specialized in '{expertise}'."
                header = " & ".join(f"'{t}'" for t in terms)
                out = [f"{len(rows)} faculty in {header} (name | type | email | specialization):"]
                for name, email, phone, addr, edu, spec, url, ftype in rows:
                    out.append(f"- {name} | {ftype} | {email or '-'} | {spec or '-'}")
                return "\n".join(out)
    except Exception as e:
        logger.error(f"search_faculty_by_expertise error: {e}")
        return f"Error searching by expertise: {e}"


@mcp.tool()
def sync_faculty_data() -> str:
    """
    Trigger a live scrape of the DA-IICT faculty website and reload the database.
    """
    logger.info("Tool 'sync_faculty_data' invoked.")
    
    role = user_role_var.get()
    if role not in ("Staff", "Faculty", "Admin"):
        return f"Unauthorized: Role '{role}' is not allowed to sync faculty data."

    try:
        data = faculty_scraper.scrape_faculty_data()
        if not data:
            return "Failed to scrape faculty directory. Check logs for details."
        faculty_scraper.save_to_database(data)
        return f"Successfully synchronized {len(data)} faculty profiles from the live DA-IICT website."
    except Exception as e:
        logger.error(f"sync_faculty_data error: {e}")
        return f"Error syncing faculty data: {e}"


# ==============================================================================
# Entry Point
# ==============================================================================
if __name__ == "__main__":
    logger.info("Starting DA-IICT Faculty MCP Server (stdio transport)...")
    mcp.run()
