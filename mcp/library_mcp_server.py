"""
Library MCP Server
==================
Standalone MCP server exposing DA-IICT library catalog tools via stdio transport.

Run with:
    python -m mcp.library_mcp_server

Tools exposed:
  - search_library_books   — keyword / title / author / ISBN search
  - get_book_details       — full record + real-time copy availability

Design note
-----------
All data is fetched **live** from the Koha OPAC at https://opac.daiict.ac.in.
Nothing is stored in the local PostgreSQL database — the library catalog is far
too large to cache, and real-time availability information would be stale
within minutes of being written.
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
logger = config.get_logger("mcp.library_mcp_server")
_svc   = LibraryService()   # stateless singleton — safe to share


# ==============================================================================
# Library MCP Tools
# ==============================================================================

@mcp.tool()
def search_library_books(query: str, limit: int = 10) -> list[dict]:
    """
    Search the DA-IICT Resource Centre (Koha OPAC) catalog.

    Returns a list of matching books with title, author, publisher, year,
    ISBN, and a link to the full OPAC record.  Data is fetched live — no
    local database is involved.

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
        results = asyncio.run(_svc.search_books(query=query, limit=limit))
        logger.info(f"search_library_books: {len(results)} results")
        return results
    except ValueError as exc:
        logger.warning(f"search_library_books validation error: {exc}")
        return [{"error": str(exc)}]
    except Exception as exc:
        logger.error(f"search_library_books failed: {exc}", exc_info=True)
        return [{"error": f"OPAC search failed: {exc}"}]


@mcp.tool()
def get_book_details(biblionumber: str) -> dict:
    """
    Fetch the full catalog record and real-time copy availability for a book.

    Queries the Koha OPAC detail page live and returns bibliographic metadata
    plus a list of physical holdings (item type, library branch, call number,
    availability status, barcode, and due date if checked out).

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
        result = asyncio.run(_svc.get_book_details(biblionumber=biblionumber))
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
        return {"error": f"OPAC detail lookup failed: {exc}"}


# ==============================================================================
# Entry Point
# ==============================================================================
if __name__ == "__main__":
    logger.info("Starting DA-IICT Library MCP Server (stdio transport)...")
    mcp.run()
