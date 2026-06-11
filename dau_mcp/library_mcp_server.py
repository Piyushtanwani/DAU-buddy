"""
Library MCP Server
==================
Standalone MCP server exposing DA-IICT library catalog tools via stdio transport.

Run with:
    python -m dau_mcp.library_mcp_server

Tools exposed:
  - search_library_books   — keyword / title / author / ISBN search
  - get_book_details       — full record details

Design note
-----------
Data is fetched from the local PostgreSQL database, seeded from a provided CSV.
The original live Koha OPAC scraping has been replaced for stability. OPAC links are
provided in tool responses for real-time availability checks.
"""
import asyncio
import json

from mcp.server.fastmcp import FastMCP

from core import config
from api.services.library_service import LibraryService

# ==============================================================================
# Server Setup
# ==============================================================================
mcp    = FastMCP("DA-IICT Library Server")
logger = config.get_logger("dau_mcp.library_mcp_server")
_svc   = LibraryService()   # stateless singleton — safe to share


# ==============================================================================
# Library MCP Tools
# ==============================================================================

@mcp.tool()
async def search_library_books(query: str, limit: int = 10) -> list[dict]:
    """
    Search the DA-IICT Resource Centre (Koha OPAC) catalog.

    Returns a list of matching books with title, author, publisher, year,
    ISBN, and a link to the OPAC search. Data is fetched from the local PostgreSQL database.

    IMPORTANT FOR AI: When presenting the search results to the user, you MUST 
    include the OPAC `link` for each book, telling the user they can use it to 
    check real-time availability.

    Parameters
    ----------
    query:
        Free-text search term.  Can be a title, author name, keyword, or ISBN.
    limit:
        Maximum number of results to return (1–50, default 10).

    Returns
    -------
    list[dict]  — each dict has keys:
        title, link, biblionumber, author, publisher, year, isbn
    """
    logger.info(f"Tool 'search_library_books' invoked — query={query!r}, limit={limit}")
    try:
        results = await _svc.search_books(query=query, limit=limit)
        logger.info(f"search_library_books: {len(results)} results")
        return results
    except ValueError as exc:
        logger.warning(f"search_library_books validation error: {exc}")
        return [{"error": str(exc)}]
    except Exception as exc:
        logger.error(f"search_library_books failed: {exc}", exc_info=True)
        return [{"error": f"Local database search failed: {exc}"}]


@mcp.tool()
async def get_book_details(biblionumber: str) -> dict:
    """
    Fetch the full catalog record for a book from the local database.

    Queries the local PostgreSQL database and returns bibliographic metadata.
    Real-time physical holdings are not tracked locally; instead, an OPAC link
    is returned for the user to check availability directly.

    IMPORTANT FOR AI: Always present the `opac_availability_link` prominently 
    to the user in your response, advising them to click it to check real-time 
    copy availability and branch locations!

    Parameters
    ----------
    biblionumber:
        The Koha internal record identifier (integer as a string).
        Obtain this from the `biblionumber` field of a search result.

    Returns
    -------
    dict — with keys:
        biblionumber, title, author, publisher, year, isbn, subjects,
        holdings (list), total_copies (int), available_copies (int)
    """
    logger.info(f"Tool 'get_book_details' invoked — biblionumber={biblionumber!r}")
    try:
        result = await _svc.get_book_details(biblionumber=biblionumber)
        logger.info(
            f"get_book_details: {result.get('total_copies', 0)} copies, "
            f"{result.get('available_copies', 0)} available"
        )
        return result
    except ValueError as exc:
        logger.warning(f"get_book_details validation error: {exc}")
        return {"error": str(exc)}
    except Exception as exc:
        logger.error(f"get_book_details failed: {exc}", exc_info=True)
        return {"error": f"Local database detail lookup failed: {exc}"}


# ==============================================================================
# Entry Point
# ==============================================================================
if __name__ == "__main__":
    logger.info("Starting DA-IICT Library MCP Server (stdio transport)...")
    mcp.run()
