"""
Library API Routes
==================
REST endpoints for querying the DA-IICT Koha OPAC.
All responses are fetched live — no database reads or writes.

Endpoints
---------
GET /api/v1/library/search?q=<str>&limit=<int>
    Search the catalog and return a list of book summaries.

GET /api/v1/library/detail/{biblionumber}
    Fetch full metadata and real-time copy/holdings information for a book.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core import config
from api.services.library_service import LibraryService

logger = config.get_logger("api.routes.library")
router = APIRouter()

# Singleton service — stateless, safe to share across requests
_library_service = LibraryService()


# ==============================================================================
# Response Schemas (Pydantic v2)
# ==============================================================================

class BookSummary(BaseModel):
    """Lightweight catalog record returned by a search."""
    title:        str = Field(default="", description="Book title")
    link:         str = Field(default="", description="Full URL to the OPAC detail page")
    biblionumber: str = Field(default="", description="Koha internal record identifier")
    author:       str = Field(default="", description="Primary author(s)")
    publisher:    str = Field(default="", description="Publisher name")
    year:         str = Field(default="", description="Publication year")
    isbn:         str = Field(default="", description="ISBN-10 or ISBN-13")


class HoldingItem(BaseModel):
    """A single physical copy / holding record for a book."""
    item_type:   str = Field(default="", description="e.g. Book, Reference, …")
    library:     str = Field(default="", description="Current library branch")
    call_number: str = Field(default="", description="Shelf call number")
    status:      str = Field(default="", description="Availability status")
    barcode:     str = Field(default="", description="Item barcode")
    date_due:    str = Field(default="", description="Date due if checked out, else empty")


class BookDetail(BaseModel):
    """Full catalog record with real-time holdings."""
    biblionumber:      str               = Field(description="Koha record ID")
    title:             str               = Field(default="")
    author:            str               = Field(default="")
    publisher:         str               = Field(default="")
    year:              str               = Field(default="")
    isbn:              str               = Field(default="")
    subjects:          list[str]         = Field(default_factory=list)
    holdings:          list[HoldingItem] = Field(default_factory=list)
    total_copies:      int               = Field(default=0)
    available_copies:  int               = Field(default=0)


class SearchResponse(BaseModel):
    query:        str              = Field(description="The original search query")
    total_found:  int              = Field(description="Number of results returned")
    results:      list[BookSummary]


# ==============================================================================
# Endpoints
# ==============================================================================

@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search the DAIICT library catalog",
    description=(
        "Queries the Koha OPAC catalog live via RSS and returns up to `limit` "
        "matching book summaries. No data is stored locally."
    ),
)
async def search_library(
    q: str = Query(..., min_length=2, description="Search term (title, author, keyword, ISBN)"),
    limit: int = Query(default=10, ge=1, le=50, description="Max results to return"),
):
    """Search the DAIICT library OPAC and return a list of matching books."""
    logger.info(f"Library search: q={q!r}, limit={limit}")
    try:
        raw = await _library_service.search_books(query=q, limit=limit)
        books = [BookSummary(**item) for item in raw["results"]]
        return SearchResponse(
            query=q,
            total_found=raw["total_matches"],
            results=books,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error(f"Library search error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"OPAC search failed: {exc}",
        )


@router.get(
    "/detail/{biblionumber}",
    response_model=BookDetail,
    summary="Get full details and holdings for a book",
    description=(
        "Fetches the full OPAC catalog record and real-time copy/availability "
        "information for the given Koha biblionumber. No data is stored locally."
    ),
)
async def get_book_detail(biblionumber: str):
    """Return full metadata and copy availability for a single book."""
    logger.info(f"Library detail: biblionumber={biblionumber!r}")
    try:
        raw = await _library_service.get_book_details(biblionumber=biblionumber)
        # Map raw holding dicts → HoldingItem, stripping the _raw debug key
        holdings = [
            HoldingItem(
                item_type=h.get("item_type", ""),
                library=h.get("library", ""),
                call_number=h.get("call_number", ""),
                status=h.get("status", ""),
                barcode=h.get("barcode", ""),
                date_due=h.get("date_due", ""),
            )
            for h in raw.get("holdings", [])
        ]
        return BookDetail(
            biblionumber=raw["biblionumber"],
            title=raw.get("title", ""),
            author=raw.get("author", ""),
            publisher=raw.get("publisher", ""),
            year=raw.get("year", ""),
            isbn=raw.get("isbn", ""),
            subjects=raw.get("subjects", []),
            holdings=holdings,
            total_copies=raw.get("total_copies", len(holdings)),
            available_copies=raw.get("available_copies", 0),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error(f"Library detail error: {exc}", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"OPAC detail lookup failed: {exc}",
        )
