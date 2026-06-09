"""
Library Service
===============
A stateless, live-proxy client for the DA-IICT Koha OPAC at
https://opac.daiict.ac.in

**No data is stored in the database.**
Results are fetched on-demand, parsed, and returned directly to the caller.
The library catalog is far too large to cache wholesale — searches are cheap
HTTP calls to the OPAC's RSS endpoint.

Koha OPAC is protected by an Altcha proof-of-work captcha.  The service
solves this challenge programmatically before every search or detail request.
"""
import asyncio
import base64
import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from core import config

logger = config.get_logger("api.services.library_service")


# ---------------------------------------------------------------------------
# RSS namespace used by Koha
# ---------------------------------------------------------------------------
_RSS_NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


class LibraryService:
    """
    Stateless client for the DA-IICT Koha OPAC.

    Every public method is async and creates a fresh httpx session — no
    connection state is kept between calls, so the class is thread-safe and
    safe to use as a module-level singleton.
    """

    def __init__(self) -> None:
        self._base_url: str = config.get_library_opac_base_url()

    # ======================================================================
    # Internal helpers
    # ======================================================================

    def _make_client(self) -> httpx.AsyncClient:
        """
        Return a new async HTTP client.
        SSL verification is disabled because the OPAC's certificate chain
        is often self-signed / untrusted in production environments.
        """
        return httpx.AsyncClient(
            verify=False,
            timeout=30.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # Altcha solver
    # ------------------------------------------------------------------

    async def _solve_altcha(self, client: httpx.AsyncClient) -> dict[str, str]:
        """
        Solve the Altcha proof-of-work challenge and return the verified
        session cookies that must accompany subsequent OPAC requests.

        Algorithm
        ---------
        1. Fetch challenge JSON from ``/altcha-challenge``.
        2. Brute-force SHA-256( salt + str(n) ) until it equals `challenge`.
        3. Base64-encode the solution JSON.
        4. POST the solution to ``/altcha-verify``.
        5. Return the resulting session cookies.
        """
        challenge_url = f"{self._base_url}/altcha-challenge"
        logger.info(f"Fetching Altcha challenge from {challenge_url}")

        resp = await client.get(challenge_url)
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()

        salt: str       = payload["salt"]
        challenge: str  = payload["challenge"]
        max_number: int = int(payload.get("maxnumber", 1_000_000))
        signature: str  = payload["signature"]
        algorithm: str  = payload.get("algorithm", "SHA-256")

        logger.info(f"Altcha: salt={salt!r}, maxnumber={max_number}, algo={algorithm}")

        # --- brute-force loop (runs in a thread to avoid blocking event loop)
        def _find_n() -> int:
            for n in range(max_number + 1):
                digest = hashlib.sha256(f"{salt}{n}".encode()).hexdigest()
                if digest == challenge:
                    return n
            raise RuntimeError(
                f"Altcha: no solution found in [0, {max_number}] — "
                "challenge may have changed or maxnumber is too small."
            )

        loop = asyncio.get_event_loop()
        n = await loop.run_in_executor(None, _find_n)
        logger.info(f"Altcha: solved n={n}")

        solution = {
            "algorithm": algorithm,
            "challenge": challenge,
            "number": n,
            "salt": salt,
            "signature": signature,
        }
        altcha_b64 = base64.b64encode(json.dumps(solution).encode()).decode()

        verify_url = f"{self._base_url}/altcha-verify"
        verify_resp = await client.post(
            verify_url,
            data={"original_url": "/", "altcha": altcha_b64},
        )
        verify_resp.raise_for_status()

        cookies: dict[str, str] = {}
        for cookie_name in ("koha_altcha_verified", "CGISESSID"):
            val = verify_resp.cookies.get(cookie_name)
            if val:
                cookies[cookie_name] = val

        logger.info(f"Altcha: verified, cookies obtained: {list(cookies.keys())}")
        return cookies

    # ------------------------------------------------------------------
    # RSS / description field parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _text_between(text: str, start_marker: str, end_marker: str) -> str:
        """Extract the first occurrence of text between two markers."""
        try:
            start = text.index(start_marker) + len(start_marker)
            end   = text.index(end_marker, start)
            return text[start:end].strip()
        except ValueError:
            return ""

    @staticmethod
    def _parse_description_html(description_html: str) -> dict[str, str]:
        """
        Extract structured fields from the raw HTML snippet inside a Koha
        RSS ``<description>`` element.

        Koha renders each field as a ``<p>`` containing a ``<span class="label">``
        followed by the value.  We fall back to regex for robustness.
        """
        soup = BeautifulSoup(description_html, "html.parser")
        result: dict[str, str] = {}

        for p in soup.find_all("p"):
            label_tag = p.find("span", class_="label")
            if not label_tag:
                continue
            label = label_tag.get_text(strip=True).rstrip(":").strip().lower()
            # Remove the label span to get the remaining value text
            label_tag.decompose()
            value = p.get_text(separator=" ", strip=True)
            if value:
                result[label] = value

        # Fallback pass for plain-text descriptions without span labels
        if not result:
            lines = [re.sub(r"<[^>]+>", "", line).strip() for line in re.split(r"<br\s*/?>|\n", description_html)]
            lines = [L for L in lines if L]
            
            for line in lines:
                if line.startswith("By "):
                    result["author"] = line[3:].strip(" .")
                elif ":" in line and "," in line and "cm" not in line and "pages" not in line:
                    # Attempt to parse "City : Publisher, Year ."
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        pub_year = parts[1].rsplit(",", 1)
                        if len(pub_year) == 2:
                            result["publisher"] = pub_year[0].strip(" .")
                            year_match = re.search(r"(\d{4})", pub_year[1])
                            if year_match:
                                result["date"] = year_match.group(1)
                
                # If there's a strict colon line, keep the old fallback just in case
                if ":" in line and not line.startswith("By "):
                    k, _, v = line.partition(":")
                    k, v = k.strip().lower(), v.strip()
                    if k and v and k not in result:
                        result[k] = v

        return result

    @staticmethod
    def _extract_biblionumber(url: str) -> str:
        """Parse the ``biblionumber`` query parameter from a Koha detail URL."""
        try:
            qs = parse_qs(urlparse(url).query)
            return qs.get("biblionumber", [""])[0]
        except Exception:
            return ""

    # ======================================================================
    # Public API — NO DATABASE WRITES
    # ======================================================================

    async def search_books(self, query: str, limit: int = 10) -> list[dict]:
        """
        Search the OPAC catalog for books matching *query*.

        Results are fetched live from the Koha RSS endpoint and returned
        directly — nothing is persisted.

        Parameters
        ----------
        query:
            The search string (title, author, keyword, ISBN, …).
        limit:
            Maximum number of results to return (default 10).

        Returns
        -------
        A list of book-summary dicts with keys:
          title, link, biblionumber, author, publisher, year, isbn
        """
        if not query or not query.strip():
            raise ValueError("search query must not be empty")
        if len(query.strip()) < 2:
            raise ValueError("search query must be at least 2 characters")

        async with self._make_client() as client:
            # Solve captcha and grab session cookies
            try:
                cookies = await self._solve_altcha(client)
                client.cookies.update(cookies)
            except Exception as e:
                logger.warning(f"Altcha solve failed ({e}); retrying without cookies")

            search_url = (
                f"{self._base_url}/cgi-bin/koha/opac-search.pl"
                f"?q={query.strip()}&format=rss"
            )
            logger.info(f"Searching OPAC: {search_url}")
            resp = await client.get(search_url)
            resp.raise_for_status()

        # --- XML RSS parsing (no lxml dependency needed)
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as exc:
            logger.error(f"RSS XML parse error: {exc}")
            return []

        channel = root.find("channel")
        if channel is None:
            return []

        books: list[dict] = []
        for item in channel.findall("item")[:limit]:
            title_el = item.find("title")
            link_el  = item.find("link")
            desc_el  = item.find("description")

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            link  = link_el.text.strip()  if link_el  is not None and link_el.text  else ""
            biblionumber = self._extract_biblionumber(link)

            # Parse structured metadata from the HTML description blob
            parsed = self._parse_description_html(desc_el.text or "") if desc_el is not None else {}

            # Pull DC metadata elements (Koha usually includes these)
            author    = item.find("dc:creator", _RSS_NS)
            if author is None:
                author = item.find("author")
            publisher = item.find("dc:publisher",  _RSS_NS)
            year_el   = item.find("dc:date",       _RSS_NS)
            isbn_el   = item.find("dc:identifier", _RSS_NS)

            books.append({
                "title":       title,
                "link":        link,
                "biblionumber": biblionumber,
                "author":      (author.text.strip()    if author    is not None and author.text    else parsed.get("author", "")),
                "publisher":   (publisher.text.strip() if publisher is not None and publisher.text else parsed.get("publisher", "")),
                "year":        (year_el.text.strip()   if year_el   is not None and year_el.text   else parsed.get("date", "")),
                "isbn":        (isbn_el.text.strip()   if isbn_el   is not None and isbn_el.text   else parsed.get("isbn", "")),
            })

        logger.info(f"OPAC search returned {len(books)} results for query={query!r}")
        return books

    async def get_book_details(self, biblionumber: str) -> dict:
        """
        Fetch the full catalog record and real-time holdings for a single book.

        Queries the Koha OPAC detail page live — no DB read or write.

        Parameters
        ----------
        biblionumber:
            The Koha biblionumber (integer as a string).

        Returns
        -------
        A dict with keys:
          biblionumber, title, author, publisher, year, isbn, subjects,
          holdings (list of item dicts)
        """
        if not biblionumber or not str(biblionumber).strip():
            raise ValueError("biblionumber must not be empty")

        async with self._make_client() as client:
            try:
                cookies = await self._solve_altcha(client)
                client.cookies.update(cookies)
            except Exception as e:
                logger.warning(f"Altcha solve failed ({e}); retrying without cookies")

            detail_url = (
                f"{self._base_url}/cgi-bin/koha/opac-detail.pl"
                f"?biblionumber={biblionumber}"
            )
            logger.info(f"Fetching book detail: {detail_url}")
            resp = await client.get(detail_url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # ------------------------------------------------------------------
        # Extract bibliographic metadata from the page header area
        # ------------------------------------------------------------------
        def _meta(itemprop: str) -> str:
            tag = soup.find(attrs={"itemprop": itemprop})
            return tag.get_text(strip=True) if tag else ""

        def _meta_content(name: str) -> str:
            tag = soup.find("meta", attrs={"name": name})
            return (tag.get("content") or "").strip() if tag else ""

        title     = _meta("name")     or soup.find("h1", class_=re.compile(r"title", re.I)) and soup.find("h1").get_text(strip=True) or ""
        author    = _meta("author")   or ""
        publisher = _meta("publisher") or ""
        year      = _meta("datePublished") or ""
        isbn      = _meta("isbn")     or ""

        # subjects
        subjects = [
            a.get_text(strip=True)
            for a in soup.select("span[class*='subject'] a, a[href*='subject=']")
        ]

        # ------------------------------------------------------------------
        # Parse the holdings / items table
        # ------------------------------------------------------------------
        holdings: list[dict] = []

        # Koha wraps the holdings table in #holdings-table or id="holdings"
        holdings_table = (
            soup.find("table", id=re.compile(r"holdings", re.I))
            or soup.find("table", id="holdingst")
            or soup.find("table", class_=re.compile(r"holdings", re.I))
        )

        # Fallback: pick the first sizable table on the page
        if holdings_table is None:
            all_tables = soup.find_all("table")
            for t in all_tables:
                if t.find("th"):
                    holdings_table = t
                    break

        if holdings_table:
            # Build column index from header row — find first <tr> that has <th> tags
            headers: list[str] = []

            for tr in holdings_table.find_all("tr"):
                ths = tr.find_all("th")
                if ths:
                    headers = [th.get_text(strip=True).lower().replace(" ", "_") for th in ths]
                    break

            # Parse data rows
            for tr in holdings_table.find_all("tr"):
                tds = tr.find_all("td")
                if not tds or len(tds) < 2:
                    continue

                row_data: dict[str, str] = {}
                for idx, td in enumerate(tds):
                    col_name = headers[idx] if idx < len(headers) else f"col_{idx}"
                    row_data[col_name] = td.get_text(separator=" ", strip=True)

                # Normalise to a consistent shape regardless of column order
                holding = {
                    "item_type":      row_data.get("item_type",      row_data.get("type",    "")),
                    "library":        row_data.get("current_library", row_data.get("library", row_data.get("home_library", ""))),
                    "call_number":    row_data.get("call_number",    row_data.get("call_no",  "")),
                    "status":         row_data.get("status",         row_data.get("loan_status", row_data.get("availability", ""))),
                    "barcode":        row_data.get("barcode",        ""),
                    "date_due":       row_data.get("date_due",       row_data.get("due_date", "")),
                    "_raw":           row_data,   # preserve full row for debugging
                }
                # Skip ghost rows (all empty values)
                if any(v for k, v in holding.items() if k != "_raw"):
                    holdings.append(holding)

        result = {
            "biblionumber": str(biblionumber),
            "title":        title,
            "author":       author,
            "publisher":    publisher,
            "year":         year,
            "isbn":         isbn,
            "subjects":     subjects,
            "holdings":     holdings,
            "total_copies": len(holdings),
            "available_copies": sum(
                1 for h in holdings
                if "available" in h.get("status", "").lower()
                or "on shelf"  in h.get("status", "").lower()
            ),
        }

        logger.info(
            f"Book {biblionumber}: {len(holdings)} holding(s), "
            f"{result['available_copies']} available"
        )
        return result
