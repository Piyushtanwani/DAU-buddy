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
async def search_library_books(query: str, limit: int = 10, offset: int = 0) -> dict:
    """
    Search the DA-IICT Resource Centre (Koha OPAC) catalog.
    query: title, author, keyword, or ISBN. limit: 1-50 (default 10).

    Returns {total_matches, showing, more_available, results, opac_url_template}.
    If the user asks for more books, call again with offset advanced by limit;
    if more_available is false, tell the user the list is complete.
    Real-time availability: substitute a book's isbn (or title) into opac_url_template.
    """
    logger.info(f"Tool 'search_library_books' invoked — query={query!r}, limit={limit}, offset={offset}")
    try:
        result = await _svc.search_books(query=query, limit=limit, offset=offset)
        result["opac_url_template"] = "https://opac.daiict.ac.in/cgi-bin/koha/opac-search.pl?q={isbn}"
        return result
    except ValueError as exc:
        logger.warning(f"search_library_books validation error: {exc}")
        return {"error": str(exc)}
    except Exception as exc:
        logger.error(f"search_library_books failed: {exc}", exc_info=True)
        return {"error": "Local database search failed."}


@mcp.tool()
async def get_book_details(biblionumber: str) -> dict:
    """
    Full catalog record for one book by biblionumber (from a search result).
    Returns bibliographic metadata plus `opac_availability_link` for real-time
    availability (share that link with the user).
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
