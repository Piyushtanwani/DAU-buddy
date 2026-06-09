"""
Integration Tests — Library Service & API
==========================================
Tests the Altcha solver, RSS feed parsing, detail-page HTML scraping, and
the FastAPI endpoints.

Network calls to opac.daiict.ac.in are mocked by default so the suite runs
offline.  Set the environment variable LIBRARY_LIVE_TESTS=1 to enable live
network tests (they are marked with @pytest.mark.skipif by default).

Run:
    python -m pytest tests/test_library.py -v
    python -m pytest tests/test_library.py -v -k live   # live tests only
"""
import asyncio
import base64
import hashlib
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

LIVE = os.getenv("LIBRARY_LIVE_TESTS", "0") == "1"

# Minimal valid RSS feed returned by Koha
_SAMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>DA-IICT OPAC search results</title>
    <item>
      <title>Python Programming for Beginners</title>
      <link>https://opac.daiict.ac.in/cgi-bin/koha/opac-detail.pl?biblionumber=1234</link>
      <description>&lt;p&gt;&lt;span class="label"&gt;Author:&lt;/span&gt; Guido van Rossum&lt;/p&gt;
        &lt;p&gt;&lt;span class="label"&gt;Publisher:&lt;/span&gt; O&#39;Reilly Media&lt;/p&gt;
        &lt;p&gt;&lt;span class="label"&gt;Date:&lt;/span&gt; 2020&lt;/p&gt;
        &lt;p&gt;&lt;span class="label"&gt;ISBN:&lt;/span&gt; 978-0-13-468599-1&lt;/p&gt;
      </description>
      <dc:creator>Guido van Rossum</dc:creator>
      <dc:publisher>O'Reilly Media</dc:publisher>
      <dc:date>2020</dc:date>
      <dc:identifier>978-0-13-468599-1</dc:identifier>
    </item>
    <item>
      <title>Data Structures and Algorithms</title>
      <link>https://opac.daiict.ac.in/cgi-bin/koha/opac-detail.pl?biblionumber=5678</link>
      <description>&lt;p&gt;&lt;span class="label"&gt;Author:&lt;/span&gt; Thomas H. Cormen&lt;/p&gt;</description>
      <dc:creator>Thomas H. Cormen</dc:creator>
    </item>
  </channel>
</rss>
"""

# Minimal HTML returned by Koha's opac-detail.pl
_SAMPLE_DETAIL_HTML = """\
<html>
<head><title>Python Programming</title></head>
<body>
  <h1 class="title" itemprop="name">Python Programming for Beginners</h1>
  <span itemprop="author">Guido van Rossum</span>
  <span itemprop="publisher">O'Reilly Media</span>
  <span itemprop="datePublished">2020</span>
  <span itemprop="isbn">978-0-13-468599-1</span>
  <table id="holdings-table">
    <thead>
      <tr>
        <th>Item type</th>
        <th>Current library</th>
        <th>Call number</th>
        <th>Status</th>
        <th>Barcode</th>
        <th>Date due</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Book</td>
        <td>DA-IICT Library</td>
        <td>005.13/VAN</td>
        <td>Available</td>
        <td>DA001234</td>
        <td></td>
      </tr>
      <tr>
        <td>Book</td>
        <td>DA-IICT Library</td>
        <td>005.13/VAN</td>
        <td>Checked out</td>
        <td>DA001235</td>
        <td>2024-12-31</td>
      </tr>
    </tbody>
  </table>
</body>
</html>
"""


def _build_altcha_challenge(salt: str, n: int, max_number: int = 1000) -> dict:
    """Helper: build a synthetic Altcha challenge/response pair."""
    challenge = hashlib.sha256(f"{salt}{n}".encode()).hexdigest()
    return {
        "salt":       salt,
        "challenge":  challenge,
        "maxnumber":  max_number,
        "signature":  "fake_signature_for_tests",
        "algorithm":  "SHA-256",
    }


def _make_mock_response(status: int, json_data=None, text: str = "") -> MagicMock:
    """Build a mock httpx.Response."""
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status
    mock.raise_for_status = MagicMock()   # no-op for 2xx
    mock.json.return_value = json_data or {}
    mock.text = text
    mock.cookies = {}
    return mock


# ---------------------------------------------------------------------------
# Unit Tests — Altcha Solver
# ---------------------------------------------------------------------------

class TestAltchaSolver:
    """Test the proof-of-work SHA-256 solver in isolation."""

    @pytest.mark.asyncio
    async def test_solver_finds_correct_number(self, mocker):
        """
        Solver must return the exact integer n such that
        SHA-256(salt + str(n)) == challenge.
        """
        from api.services.library_service import LibraryService

        SECRET_N = 42
        challenge_payload = _build_altcha_challenge(salt="testsalt_", n=SECRET_N, max_number=1000)

        # Challenge response mock
        challenge_resp = _make_mock_response(200, json_data=challenge_payload)

        # Verify response mock — simulate cookies returned by server
        verify_resp_cookies = {"koha_altcha_verified": "1", "CGISESSID": "abc123"}
        verify_resp = _make_mock_response(200)
        verify_resp.cookies = verify_resp_cookies

        # Build a fake async client that returns our mocks
        mock_client = AsyncMock()
        mock_client.get.return_value  = challenge_resp
        mock_client.post.return_value = verify_resp

        svc = LibraryService()
        cookies = await svc._solve_altcha(mock_client)

        assert cookies.get("koha_altcha_verified") == "1"
        assert cookies.get("CGISESSID") == "abc123"

        # Verify the POST body contained the correctly-encoded solution
        post_call_kwargs = mock_client.post.call_args
        posted_data = post_call_kwargs.kwargs.get("data") or post_call_kwargs.args[1] if len(post_call_kwargs.args) > 1 else {}
        # altcha field should be a base64 JSON string
        if "altcha" in str(posted_data):
            altcha_b64 = posted_data.get("altcha", "")
            solution = json.loads(base64.b64decode(altcha_b64).decode())
            assert solution["number"] == SECRET_N
            assert solution["challenge"] == challenge_payload["challenge"]

    @pytest.mark.asyncio
    async def test_solver_raises_when_no_solution_exists(self, mocker):
        """Solver must raise RuntimeError if maxnumber is exhausted with no match."""
        from api.services.library_service import LibraryService

        # Challenge that is mathematically impossible within maxnumber=5
        bad_challenge = {
            "salt":       "nosolution_",
            "challenge":  "0000000000000000000000000000000000000000000000000000000000000000",
            "maxnumber":  5,
            "signature":  "sig",
            "algorithm":  "SHA-256",
        }
        challenge_resp = _make_mock_response(200, json_data=bad_challenge)
        mock_client = AsyncMock()
        mock_client.get.return_value = challenge_resp

        svc = LibraryService()
        with pytest.raises(RuntimeError, match="no solution found"):
            await svc._solve_altcha(mock_client)


# ---------------------------------------------------------------------------
# Unit Tests — RSS Feed Parsing
# ---------------------------------------------------------------------------

class TestRSSParsing:
    """Test search_books with mocked HTTP responses."""

    @pytest.mark.asyncio
    async def test_search_books_returns_expected_fields(self, mocker):
        """search_books must parse title, author, biblionumber, etc. from RSS."""
        from api.services.library_service import LibraryService

        svc = LibraryService()

        # Mock _solve_altcha to skip PoW
        mocker.patch.object(svc, "_solve_altcha", new=AsyncMock(return_value={}))

        # Mock the HTTP client context manager
        search_resp = _make_mock_response(200, text=_SAMPLE_RSS)
        mock_client  = MagicMock()
        mock_client.get = AsyncMock(return_value=search_resp)
        mock_client.cookies = MagicMock()  # avoid dict.update read-only error
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)

        mocker.patch.object(svc, "_make_client", return_value=mock_client)

        results = await svc.search_books("python", limit=10)

        assert len(results) == 2
        first = results[0]
        assert first["title"] == "Python Programming for Beginners"
        assert first["biblionumber"] == "1234"
        assert first["author"] == "Guido van Rossum"
        assert first["publisher"] == "O'Reilly Media"
        assert first["year"] == "2020"
        assert first["isbn"] == "978-0-13-468599-1"

    @pytest.mark.asyncio
    async def test_search_books_respects_limit(self, mocker):
        """search_books must honour the limit parameter."""
        from api.services.library_service import LibraryService

        svc = LibraryService()
        mocker.patch.object(svc, "_solve_altcha", new=AsyncMock(return_value={}))

        search_resp = _make_mock_response(200, text=_SAMPLE_RSS)
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=search_resp)
        mock_client.cookies = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mocker.patch.object(svc, "_make_client", return_value=mock_client)

        results = await svc.search_books("python", limit=1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_books_empty_query_raises(self):
        """search_books must raise ValueError for empty queries."""
        from api.services.library_service import LibraryService

        svc = LibraryService()
        with pytest.raises(ValueError):
            await svc.search_books("")

    @pytest.mark.asyncio
    async def test_search_books_short_query_raises(self):
        """search_books must raise ValueError for single-character queries."""
        from api.services.library_service import LibraryService

        svc = LibraryService()
        with pytest.raises(ValueError):
            await svc.search_books("a")

    @pytest.mark.asyncio
    async def test_search_books_empty_rss_channel(self, mocker):
        """search_books must return [] when RSS channel has no items."""
        from api.services.library_service import LibraryService

        svc = LibraryService()
        mocker.patch.object(svc, "_solve_altcha", new=AsyncMock(return_value={}))

        empty_rss = '<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
        search_resp = _make_mock_response(200, text=empty_rss)
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=search_resp)
        mock_client.cookies = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mocker.patch.object(svc, "_make_client", return_value=mock_client)

        results = await svc.search_books("nonexistent_book_xyz", limit=10)
        assert results == []


# ---------------------------------------------------------------------------
# Unit Tests — Detail Page HTML Parsing
# ---------------------------------------------------------------------------

class TestDetailParsing:
    """Test get_book_details with mocked HTTP responses."""

    @pytest.mark.asyncio
    async def test_get_book_details_returns_metadata(self, mocker):
        """get_book_details must parse title, author, isbn from the detail page."""
        from api.services.library_service import LibraryService

        svc = LibraryService()
        mocker.patch.object(svc, "_solve_altcha", new=AsyncMock(return_value={}))

        detail_resp = _make_mock_response(200, text=_SAMPLE_DETAIL_HTML)
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=detail_resp)
        mock_client.cookies = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mocker.patch.object(svc, "_make_client", return_value=mock_client)

        result = await svc.get_book_details("1234")

        assert result["biblionumber"] == "1234"
        assert result["title"] == "Python Programming for Beginners"
        assert result["author"] == "Guido van Rossum"
        assert result["isbn"]  == "978-0-13-468599-1"

    @pytest.mark.asyncio
    async def test_get_book_details_parses_holdings(self, mocker):
        """get_book_details must extract holdings rows from the table."""
        from api.services.library_service import LibraryService

        svc = LibraryService()
        mocker.patch.object(svc, "_solve_altcha", new=AsyncMock(return_value={}))

        detail_resp = _make_mock_response(200, text=_SAMPLE_DETAIL_HTML)
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=detail_resp)
        mock_client.cookies = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__  = AsyncMock(return_value=False)
        mocker.patch.object(svc, "_make_client", return_value=mock_client)

        result = await svc.get_book_details("1234")

        assert result["total_copies"] == 2
        assert result["available_copies"] == 1

        holdings = result["holdings"]
        assert len(holdings) == 2

        available = holdings[0]
        assert available["item_type"]   == "Book"
        assert available["library"]     == "DA-IICT Library"
        assert available["call_number"] == "005.13/VAN"
        assert "available" in available["status"].lower()
        assert available["barcode"]     == "DA001234"
        assert available["date_due"]    == ""

        checked_out = holdings[1]
        assert "checked out" in checked_out["status"].lower()
        assert checked_out["date_due"] == "2024-12-31"

    @pytest.mark.asyncio
    async def test_get_book_details_empty_biblionumber_raises(self):
        """get_book_details must raise ValueError for empty biblionumber."""
        from api.services.library_service import LibraryService

        svc = LibraryService()
        with pytest.raises(ValueError):
            await svc.get_book_details("")


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
            new=AsyncMock(return_value=[
                {
                    "title": "Python Programming",
                    "link": "https://opac.daiict.ac.in/cgi-bin/koha/opac-detail.pl?biblionumber=1234",
                    "biblionumber": "1234",
                    "author": "Test Author",
                    "publisher": "Test Pub",
                    "year": "2020",
                    "isbn": "1234567890",
                }
            ]),
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

    def test_detail_endpoint_503_on_opac_error(self, client, mocker):
        """Detail endpoint must return 503 when OPAC raises an exception."""
        mocker.patch(
            "api.routes.library._library_service.get_book_details",
            new=AsyncMock(side_effect=Exception("OPAC unreachable")),
        )
        resp = client.get("/api/v1/library/detail/9999")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Live / Integration Tests (skipped unless LIBRARY_LIVE_TESTS=1)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LIVE, reason="Set LIBRARY_LIVE_TESTS=1 to run live OPAC tests")
class TestLibraryLive:
    """
    End-to-end tests against the real OPAC.
    Run only when explicitly enabled to avoid network dependency in CI.
    """

    @pytest.mark.asyncio
    async def test_altcha_solver_live(self):
        """Solve the real Altcha challenge from opac.daiict.ac.in."""
        from api.services.library_service import LibraryService
        svc = LibraryService()
        async with svc._make_client() as client:
            cookies = await svc._solve_altcha(client)
        assert isinstance(cookies, dict), "Expected a dict of cookies"

    @pytest.mark.asyncio
    async def test_search_books_live(self):
        """Perform a real search against opac.daiict.ac.in."""
        from api.services.library_service import LibraryService
        svc = LibraryService()
        results = await svc.search_books("python", limit=5)
        assert isinstance(results, list)
        if results:
            assert "title" in results[0]
            assert "biblionumber" in results[0]

    @pytest.mark.asyncio
    async def test_get_book_details_live(self):
        """Fetch a real book detail page from opac.daiict.ac.in."""
        from api.services.library_service import LibraryService
        svc = LibraryService()
        # First search to get a real biblionumber
        results = await svc.search_books("data structures", limit=1)
        if not results or not results[0].get("biblionumber"):
            pytest.skip("No results from live search — cannot test detail")
        bib = results[0]["biblionumber"]
        detail = await svc.get_book_details(bib)
        assert detail["biblionumber"] == bib
        assert "holdings" in detail
