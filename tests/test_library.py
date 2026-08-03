"""
Tests — Library Service & API
=============================
`LibraryService` used to scrape the Koha OPAC (Altcha proof-of-work → RSS
search feed → HTML detail page). It is now a thin client over the local
`library_books` table, so these tests mock `db_connection` rather than HTTP.

The suite runs offline against mocks. Set LIBRARY_LIVE_TESTS=1 to additionally
run the smoke tests at the bottom, which need a seeded database.

Run:
    python -m pytest tests/test_library.py -v
    python -m pytest tests/test_library.py -v -k live   # live tests only
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

LIVE = os.getenv("LIBRARY_LIVE_TESTS", "0") == "1"


def _book_row(acc_no="1234", title="Python Programming for Beginners",
              author="Guido van Rossum", publisher="O'Reilly Media",
              year="2020", isbn="978-0-13-468599-1", total=None, **extra):
    """A `library_books` row as RealDictCursor yields it.

    `total` is the `count(*) OVER ()` window column that search_books reads to
    build its pagination envelope — search rows need it, detail rows don't.
    """
    row = {
        "acc_no": acc_no,
        "title": title,
        "author_editor": author,
        "place_publisher": publisher,
        "year": year,
        "isbn": isbn,
    }
    if total is not None:
        row["total"] = total
    row.update(extra)
    return row


def _detail_row(**overrides):
    """A full row for get_book_details, which selects every column."""
    row = _book_row(
        description="An introduction to Python.",
        class_no="005.13/VAN",
        pages="350",
        edition_volume="2nd ed.",
        poster_url="",
        book_url="",
    )
    row.update(overrides)
    return row


def mock_db(mocker, *, fetchall=None, fetchone=None):
    """Point library_service.db_connection at a mock cursor.

    Mirrors the pattern in tests/test_calendar.py.
    """
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    mock_cur.fetchall.return_value = fetchall if fetchall is not None else []
    mock_cur.fetchone.return_value = fetchone

    mocker.patch("api.services.library_service.db_connection", return_value=mock_conn)
    return mock_cur


# ---------------------------------------------------------------------------
# Unit Tests — search_books
# ---------------------------------------------------------------------------

class TestSearchBooks:
    """search_books queries library_books and wraps rows in the shared envelope."""

    @pytest.mark.asyncio
    async def test_returns_expected_fields(self, mocker):
        """DB column names are mapped onto the public result keys."""
        from api.services.library_service import LibraryService

        mock_db(mocker, fetchall=[
            _book_row(total=2),
            _book_row(acc_no="5678", title="Data Structures and Algorithms",
                      author="Thomas H. Cormen", total=2),
        ])

        result = await LibraryService().search_books("python", limit=10)

        books = result["results"]
        assert len(books) == 2
        first = books[0]
        assert first["title"] == "Python Programming for Beginners"
        assert first["biblionumber"] == "1234"          # from acc_no
        assert first["author"] == "Guido van Rossum"    # from author_editor
        assert first["publisher"] == "O'Reilly Media"   # from place_publisher
        assert first["year"] == "2020"
        assert first["isbn"] == "978-0-13-468599-1"

    @pytest.mark.asyncio
    async def test_returns_pagination_envelope(self, mocker):
        """Callers rely on the {total_matches, showing, more_available, results}
        protocol to page through results — see api/services/pagination.py."""
        from api.services.library_service import LibraryService

        mock_db(mocker, fetchall=[_book_row(total=10)])

        result = await LibraryService().search_books("python", limit=1)

        assert result["total_matches"] == 10
        assert result["showing"] == "1-1"
        assert result["more_available"] is True

    @pytest.mark.asyncio
    async def test_limit_and_offset_reach_the_query(self, mocker):
        """Paging is done in SQL, so limit/offset must be passed through."""
        from api.services.library_service import LibraryService

        cur = mock_db(mocker, fetchall=[])
        await LibraryService().search_books("python", limit=5, offset=10)

        _sql, params = cur.execute.call_args.args
        assert params[-2:] == (5, 10)

    @pytest.mark.asyncio
    async def test_multi_word_query_becomes_prefix_tsquery(self, mocker):
        """Words are AND-ed as prefix matches so partial titles still hit."""
        from api.services.library_service import LibraryService

        cur = mock_db(mocker, fetchall=[])
        await LibraryService().search_books("data structures")

        _sql, params = cur.execute.call_args.args
        assert params[0] == "data:* & structures:*"

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty_envelope(self, mocker):
        """A query with no hits is not an error."""
        from api.services.library_service import LibraryService

        mock_db(mocker, fetchall=[])

        result = await LibraryService().search_books("nonexistent_book_xyz", limit=10)

        assert result["results"] == []
        assert result["total_matches"] == 0
        assert result["more_available"] is False

    @pytest.mark.asyncio
    async def test_empty_query_raises(self):
        """search_books must raise ValueError for empty queries."""
        from api.services.library_service import LibraryService

        with pytest.raises(ValueError):
            await LibraryService().search_books("")

    @pytest.mark.asyncio
    async def test_short_query_raises(self):
        """search_books must raise ValueError for single-character queries."""
        from api.services.library_service import LibraryService

        with pytest.raises(ValueError):
            await LibraryService().search_books("a")


# ---------------------------------------------------------------------------
# Unit Tests — get_book_details
# ---------------------------------------------------------------------------

class TestBookDetails:
    """get_book_details reads one row by accession number."""

    @pytest.mark.asyncio
    async def test_returns_metadata(self, mocker):
        from api.services.library_service import LibraryService

        mock_db(mocker, fetchone=_detail_row())

        result = await LibraryService().get_book_details("1234")

        assert result["biblionumber"] == "1234"
        assert result["title"] == "Python Programming for Beginners"
        assert result["author"] == "Guido van Rossum"
        assert result["isbn"] == "978-0-13-468599-1"
        assert result["class_no"] == "005.13/VAN"

    @pytest.mark.asyncio
    async def test_availability_is_not_tracked_locally(self, mocker):
        """The local table holds no per-copy holdings, so the service reports a
        placeholder count and points at the OPAC for real availability.

        This pins a deliberate limitation: if holdings are ever wired up for
        real, this test should fail and be rewritten rather than quietly pass.
        """
        from api.services.library_service import LibraryService

        mock_db(mocker, fetchone=_detail_row())

        result = await LibraryService().get_book_details("1234")

        assert result["holdings"] == []
        assert result["total_copies"] == 1
        assert result["available_copies"] == 1
        assert "opac.daiict.ac.in" in result["opac_availability_link"]

    @pytest.mark.asyncio
    async def test_unknown_biblionumber_returns_error(self, mocker):
        """A missing book is reported in-band, not raised."""
        from api.services.library_service import LibraryService

        mock_db(mocker, fetchone=None)

        result = await LibraryService().get_book_details("does-not-exist")

        assert result == {"error": "Book not found."}

    @pytest.mark.asyncio
    async def test_empty_biblionumber_raises(self):
        """get_book_details must raise ValueError for empty biblionumber."""
        from api.services.library_service import LibraryService

        with pytest.raises(ValueError):
            await LibraryService().get_book_details("")


# ---------------------------------------------------------------------------
# API Endpoint Tests
# ---------------------------------------------------------------------------

class TestLibraryAPIEndpoints:
    """Test the FastAPI library endpoints using TestClient with mocked service."""

    @pytest.fixture
    def client(self):
        """Return a FastAPI test client with DB pool mocked out."""
        # Patch DB init so the app can load without a live Postgres
        with patch("core.database._connection_pool", MagicMock()):
            from api.main import create_app
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as c:
                yield c

    def test_search_endpoint_returns_200(self, client, mocker):
        """GET /api/v1/library/search?q=python must return 200 with result list."""
        mocker.patch(
            "api.routes.library._library_service.search_books",
            new=AsyncMock(return_value={
                "total_matches": 1,
                "showing": "1-1",
                "more_available": False,
                "results": [
                    {
                        "title": "Python Programming",
                        "link": "https://opac.daiict.ac.in/cgi-bin/koha/opac-detail.pl?biblionumber=1234",
                        "biblionumber": "1234",
                        "author": "Test Author",
                        "publisher": "Test Pub",
                        "year": "2020",
                        "isbn": "1234567890",
                    }
                ],
            }),
        )
        resp = client.get("/api/v1/library/search?q=python")
        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "python"
        assert body["total_found"] == 1
        assert body["results"][0]["title"] == "Python Programming"
        assert body["results"][0]["biblionumber"] == "1234"

    def test_search_endpoint_rejects_short_query(self, client):
        """GET /api/v1/library/search?q=a must return 422 (too short)."""
        resp = client.get("/api/v1/library/search?q=a")
        assert resp.status_code == 422

    def test_search_endpoint_missing_query(self, client):
        """GET /api/v1/library/search (no q param) must return 422."""
        resp = client.get("/api/v1/library/search")
        assert resp.status_code == 422

    def test_detail_endpoint_returns_200(self, client, mocker):
        """GET /api/v1/library/detail/1234 must return 200 with book data."""
        mocker.patch(
            "api.routes.library._library_service.get_book_details",
            new=AsyncMock(return_value={
                "biblionumber": "1234",
                "title": "Python Programming",
                "author": "Test Author",
                "publisher": "Test Pub",
                "year": "2020",
                "isbn": "1234567890",
                "subjects": ["Computer Science"],
                "holdings": [
                    {
                        "item_type": "Book",
                        "library": "DA-IICT Library",
                        "call_number": "005.13/T",
                        "status": "Available",
                        "barcode": "DA001",
                        "date_due": "",
                        "_raw": {},
                    }
                ],
                "total_copies": 1,
                "available_copies": 1,
            }),
        )
        resp = client.get("/api/v1/library/detail/1234")
        assert resp.status_code == 200
        body = resp.json()
        assert body["biblionumber"] == "1234"
        assert body["total_copies"] == 1
        assert body["available_copies"] == 1
        assert len(body["holdings"]) == 1
        assert body["holdings"][0]["status"] == "Available"

    def test_detail_endpoint_503_on_lookup_error(self, client, mocker):
        """Detail endpoint must return 503 when the lookup raises."""
        mocker.patch(
            "api.routes.library._library_service.get_book_details",
            new=AsyncMock(side_effect=Exception("database unreachable")),
        )
        resp = client.get("/api/v1/library/detail/9999")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Live / Integration Tests (skipped unless LIBRARY_LIVE_TESTS=1)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LIVE, reason="Set LIBRARY_LIVE_TESTS=1 to run live DB tests")
class TestLibraryLive:
    """
    Smoke tests against a real, seeded `library_books` table.
    Run only when explicitly enabled to avoid a DB dependency in CI.
    """

    @pytest.mark.asyncio
    async def test_search_books_live(self):
        """Search the real catalogue and check the envelope shape."""
        from api.services.library_service import LibraryService

        result = await LibraryService().search_books("python", limit=5)

        assert set(result) >= {"total_matches", "showing", "more_available", "results"}
        for book in result["results"]:
            assert book["title"]
            assert book["biblionumber"]

    @pytest.mark.asyncio
    async def test_get_book_details_live(self):
        """Fetch a real book by an accession number taken from a real search."""
        from api.services.library_service import LibraryService

        svc = LibraryService()
        found = (await svc.search_books("data structures", limit=1))["results"]
        if not found or not found[0].get("biblionumber"):
            pytest.skip("No results from live search — cannot test detail")

        detail = await svc.get_book_details(found[0]["biblionumber"])

        assert detail["biblionumber"] == found[0]["biblionumber"]
        assert "holdings" in detail
