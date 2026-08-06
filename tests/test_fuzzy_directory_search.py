"""
Test Typo-Tolerant Directory Search
===================================
Regression tests for the pg_trgm similarity fallback added to the faculty and
staff directory lookups (issue #42).

Two layers:

* Unit tests mock the database, like the other service tests, and pin the
  control flow: exact first, full-text second, similarity only when both came
  back empty — plus the disclosure wording of a fuzzy result.
* Integration tests run the *real* helper against a live PostgreSQL with
  pg_trgm, over TEMP tables seeded with real directory names, and are skipped
  when no such database is reachable. They are the only place the threshold
  itself can be verified. They never read or write the real faculty/staff
  tables.

Run with:
    python -m pytest tests/ -v
"""
import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from api.services.name_matching import (
    MIN_QUERY_LENGTH,
    TRGM_WORD_SIMILARITY_THRESHOLD,
    _similarity_sql,
    find_similar_names,
    fuzzy_match_notice,
)

# PostgreSQL's own defaults, neither of which resolves the issue's cases:
# similarity_threshold 0.3 admits unrelated names, word_similarity_threshold
# 0.6 rejects "Vijay Vargia" (0.571).
PG_DEFAULT_SIMILARITY_THRESHOLD = 0.3
PG_DEFAULT_WORD_SIMILARITY_THRESHOLD = 0.6


def _tool_fn(tool):
    """FastMCP versions differ on whether @mcp.tool() returns the function or a Tool."""
    return getattr(tool, "fn", tool)


def _mock_db(cursor):
    """Build a db_connection() replacement that yields `cursor`."""
    conn = MagicMock()
    conn.autocommit = False
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn


FACULTY_ROW = (
    "Ankush chander", "ankush_chander@dau.ac.in", "079-68261700", "Faculty Block 1",
    "PhD IIT Bombay", "NLP", "https://www.daiict.ac.in/adjunct-faculty/ankush-chander",
    None, "Adjunct",
)
STAFF_ROW = (
    "Akash Desai", "akash_desai@dau.ac.in", "079-68261701", "Admin Block",
    "MBA", "Placement Officer", None, None,
)


# ==============================================================================
# The shared matcher
# ==============================================================================
class TestNameMatchingHelper:

    def test_rejects_tables_outside_the_whitelist(self):
        """Table names are interpolated into SQL, so they must be whitelisted."""
        with patch("api.services.name_matching.db_connection") as mock_db:
            with pytest.raises(ValueError):
                find_similar_names("faculty; DROP TABLE faculty", "Chandar")
        mock_db.assert_not_called()

    def test_short_queries_never_reach_the_database(self):
        """word_similarity scores near-1.0 for 2-3 letter fragments of any name."""
        with patch("api.services.name_matching.db_connection") as mock_db:
            assert find_similar_names("faculty", "an") == []
            assert find_similar_names("staff", "   ") == []
        mock_db.assert_not_called()
        assert MIN_QUERY_LENGTH >= 4

    def test_threshold_is_tuned_not_a_postgres_default(self):
        """0.55 is chosen from measurements; both PG defaults fail the issue's cases."""
        assert TRGM_WORD_SIMILARITY_THRESHOLD == 0.55
        assert TRGM_WORD_SIMILARITY_THRESHOLD != PG_DEFAULT_WORD_SIMILARITY_THRESHOLD
        assert TRGM_WORD_SIMILARITY_THRESHOLD != PG_DEFAULT_SIMILARITY_THRESHOLD
        # "Vijay Vargia" scores 0.571 against "Ankit vijayvargiya": the cut-off
        # must sit below it, and above the 0.500 scored by unrelated names.
        assert 0.500 < TRGM_WORD_SIMILARITY_THRESHOLD < 0.571

    def test_sets_threshold_transaction_locally_on_the_same_cursor(self):
        """The <% operator reads a GUC, so the SET must share the SELECT's transaction."""
        cursor = MagicMock()
        cursor.fetchall.return_value = [("Ankush chander",)]
        with patch("api.services.name_matching.db_connection", return_value=_mock_db(cursor)):
            assert find_similar_names("faculty", "Chandar") == ["Ankush chander"]

        set_call, select_call = cursor.execute.call_args_list
        assert "set_config" in set_call.args[0]
        assert set_call.args[1] == ("0.55", True)     # is_local=True → same transaction
        assert "<%" in select_call.args[0]
        # Both statements ran on one cursor, i.e. one connection and one transaction.
        assert cursor.execute.call_count == 2

    def test_autocommit_connection_gets_its_own_transaction(self):
        """A session-scoped SET would leak 0.55 onto the next user of a pooled
        connection, so an autocommit connection is wrapped and rolled back."""
        cursor = MagicMock()
        cursor.fetchall.return_value = [("Ankush chander",)]
        conn = _mock_db(cursor)
        conn.autocommit = True
        with patch("api.services.name_matching.db_connection", return_value=conn):
            assert find_similar_names("faculty", "Chandar") == ["Ankush chander"]

        statements = [call.args[0] for call in cursor.execute.call_args_list]
        assert statements[0] == "BEGIN;"
        assert statements[-1] == "ROLLBACK;"
        set_call = cursor.execute.call_args_list[1]
        assert "set_config" in set_call.args[0]
        assert set_call.args[1][1] is True          # transaction-local, never session-wide

    def test_threshold_is_never_set_session_wide(self):
        """Whatever the connection mode, is_local must be true."""
        for autocommit in (False, True):
            cursor = MagicMock()
            cursor.fetchall.return_value = []
            conn = _mock_db(cursor)
            conn.autocommit = autocommit
            with patch("api.services.name_matching.db_connection", return_value=conn):
                find_similar_names("faculty", "Chandar")
            for call in cursor.execute.call_args_list:
                if "set_config" in call.args[0]:
                    assert call.args[1][1] is True, f"session-scoped SET with autocommit={autocommit}"

    def test_autocommit_transaction_is_closed_even_when_the_query_fails(self):
        """A failed statement must not leave the pooled connection in an aborted
        transaction holding a modified threshold."""
        cursor = MagicMock()
        cursor.execute.side_effect = [None, None, Exception("boom"), None]
        conn = _mock_db(cursor)
        conn.autocommit = True
        with patch("api.services.name_matching.db_connection", return_value=conn):
            assert find_similar_names("faculty", "Chandar") == []

        assert [call.args[0] for call in cursor.execute.call_args_list][-1] == "ROLLBACK;"

    def test_ranking_is_deterministic(self):
        """Ties are common ("Chandar" ties 3 names at 0.625), so ordering is fully specified."""
        sql = " ".join(_similarity_sql("faculty").split())
        assert "word_similarity(%s, name) DESC, similarity(%s, name) DESC, name ASC" in sql
        assert "LIMIT %s" in sql

    def test_database_failure_is_not_fatal(self):
        with patch("api.services.name_matching.db_connection", side_effect=Exception("boom")):
            assert find_similar_names("faculty", "Chandar") == []

    def test_notice_names_both_the_query_and_the_match(self):
        notice = fuzzy_match_notice("Chandar", "Ankush chander")
        assert "Chandar" in notice
        assert "Ankush chander" in notice
        assert "No exact match" in notice


# ==============================================================================
# Faculty service control flow
# ==============================================================================
class TestFacultyDetailsFallback:

    def test_exact_hit_never_runs_similarity(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = FACULTY_ROW
        with patch("api.services.faculty_service.db_connection", return_value=_mock_db(cursor)), \
             patch("api.services.faculty_service.find_similar_names") as mock_fuzzy:
            from api.services.faculty_service import get_faculty_details_db
            result = get_faculty_details_db("Ankush chander")

        mock_fuzzy.assert_not_called()
        assert result.startswith("### Detailed Profile: Ankush chander")
        assert "No exact match" not in result

    def test_misspelling_falls_back_and_discloses_the_match(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, FACULTY_ROW]   # exact miss, then fuzzy hit
        cursor.fetchall.return_value = []                   # token fallback finds nothing
        with patch("api.services.faculty_service.db_connection", return_value=_mock_db(cursor)), \
             patch("api.services.faculty_service.find_similar_names",
                   return_value=["Ankush chander"]) as mock_fuzzy:
            from api.services.faculty_service import get_faculty_details_db
            result = get_faculty_details_db("Chandar")

        mock_fuzzy.assert_called_once_with("faculty", "Chandar", limit=1)
        assert "No exact match for **'Chandar'**" in result
        assert "**Ankush chander**" in result
        # The detailed-profile contract is preserved, only prefixed.
        assert "### Detailed Profile: Ankush chander" in result
        assert "- **Email Address:** ankush_chander@dau.ac.in" in result

    def test_unrelated_name_still_returns_not_found(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None]
        cursor.fetchall.return_value = []
        with patch("api.services.faculty_service.db_connection", return_value=_mock_db(cursor)), \
             patch("api.services.faculty_service.find_similar_names", return_value=[]):
            from api.services.faculty_service import get_faculty_details_db
            result = get_faculty_details_db("Elon Musk")

        assert result == "Could not find any faculty member matching 'Elon Musk'."


class TestFacultySearchFallback:

    def test_full_text_hit_never_runs_similarity(self):
        records = [{"name": "Aditya tatu", "faculty_type": "Regular",
                    "email": "aditya_tatu@dau.ac.in", "specialization": "Image Processing"}]
        with patch("api.services.faculty_service.PostgresFullTextRetriever") as mock_retriever, \
             patch("api.services.faculty_service.find_similar_names") as mock_fuzzy:
            mock_retriever.return_value.retrieve_faculty.return_value = records
            from api.services.faculty_service import search_faculty_db
            result = search_faculty_db("image processing")

        mock_fuzzy.assert_not_called()
        assert result.startswith("### Search Results for 'image processing'")
        assert "No exact match" not in result

    def test_empty_full_text_falls_back_and_discloses_the_match(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            ("Ankush chander", "Adjunct", "ankush_chander@dau.ac.in", "079-68261700",
             "Faculty Block 1", "PhD IIT Bombay", "NLP", None),
        ]
        with patch("api.services.faculty_service.PostgresFullTextRetriever") as mock_retriever, \
             patch("api.services.faculty_service.db_connection", return_value=_mock_db(cursor)), \
             patch("api.services.faculty_service.find_similar_names",
                   return_value=["Ankush chander"]) as mock_fuzzy:
            mock_retriever.return_value.retrieve_faculty.return_value = []
            from api.services.faculty_service import search_faculty_db
            result = search_faculty_db("Chandar")

        # Only the single best candidate is resolved, as the notice claims.
        mock_fuzzy.assert_called_once_with("faculty", "Chandar", limit=1)
        assert "No exact match for **'Chandar'**" in result
        assert "**Ankush chander**" in result
        # The search-results contract is preserved, only prefixed.
        assert "### Search Results for 'Chandar'" in result
        assert "#### 1. Ankush chander (Adjunct Faculty)" in result

    def test_unrelated_query_keeps_the_existing_guidance_message(self):
        with patch("api.services.faculty_service.PostgresFullTextRetriever") as mock_retriever, \
             patch("api.services.faculty_service.find_similar_names", return_value=[]):
            mock_retriever.return_value.retrieve_faculty.return_value = []
            from api.services.faculty_service import search_faculty_db
            result = search_faculty_db("Elon Musk")
            assert "I couldn't find any faculty or staff members matching" in result
            assert search_faculty_db("Elon Musk", error_on_empty=False) is None


# ==============================================================================
# Staff service control flow
# ==============================================================================
class TestStaffFallback:

    def test_exact_hit_never_runs_similarity(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = STAFF_ROW
        with patch("api.services.staff_service.db_connection", return_value=_mock_db(cursor)), \
             patch("api.services.staff_service.find_similar_names") as mock_fuzzy:
            from api.services.staff_service import get_staff_details_db
            result = get_staff_details_db("Akash Desai")

        mock_fuzzy.assert_not_called()
        assert result.startswith("### Detailed Staff Profile: Akash Desai")
        assert "No exact match" not in result

    def test_misspelling_falls_back_and_discloses_the_match(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, STAFF_ROW]
        cursor.fetchall.return_value = []
        with patch("api.services.staff_service.db_connection", return_value=_mock_db(cursor)), \
             patch("api.services.staff_service.find_similar_names",
                   return_value=["Akash Desai"]) as mock_fuzzy:
            from api.services.staff_service import get_staff_details_db
            result = get_staff_details_db("Akaash Desa")

        mock_fuzzy.assert_called_once_with("staff", "Akaash Desa", limit=1)
        assert "No exact match for **'Akaash Desa'**" in result
        assert "**Akash Desai**" in result
        assert "### Detailed Staff Profile: Akash Desai" in result

    def test_unrelated_name_still_returns_not_found(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None]
        cursor.fetchall.return_value = []
        with patch("api.services.staff_service.db_connection", return_value=_mock_db(cursor)), \
             patch("api.services.staff_service.find_similar_names", return_value=[]):
            from api.services.staff_service import get_staff_details_db
            assert get_staff_details_db("Elon Musk") == \
                "Could not find any staff member matching 'Elon Musk'."

    def test_empty_full_text_falls_back_and_discloses_the_match(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            ("Akash Desai", "Placement Officer", "akash_desai@dau.ac.in",
             "079-68261701", "Admin Block", "MBA", None),
        ]
        with patch("api.services.staff_service.PostgresFullTextRetriever") as mock_retriever, \
             patch("api.services.staff_service.db_connection", return_value=_mock_db(cursor)), \
             patch("api.services.staff_service.find_similar_names",
                   return_value=["Akash Desai"]) as mock_fuzzy:
            mock_retriever.return_value.retrieve_staff.return_value = []
            from api.services.staff_service import search_staff_db
            result = search_staff_db("Akaash Desa")

        # Only the single best candidate is resolved, as the notice claims.
        mock_fuzzy.assert_called_once_with("staff", "Akaash Desa", limit=1)
        assert "No exact match for **'Akaash Desa'**" in result
        assert "### Staff Search Results for 'Akaash Desa'" in result
        assert "#### 1. Akash Desai" in result


# ==============================================================================
# MCP tool surfaces (the path web chat actually calls)
# ==============================================================================
class TestMcpDetailTools:

    def test_faculty_tool_discloses_a_fuzzy_match(self):
        import datetime
        from dau_mcp.faculty_mcp_server import get_faculty_details
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, FACULTY_ROW + (datetime.datetime(2026, 1, 1),)]
        with patch("dau_mcp.faculty_mcp_server.db_connection", return_value=_mock_db(cursor)), \
             patch("dau_mcp.faculty_mcp_server.find_similar_names",
                   return_value=["Ankush chander"]):
            result = _tool_fn(get_faculty_details)("Chandar")

        assert "No exact match for **'Chandar'**" in result
        assert "### Detailed Profile: Ankush chander" in result
        assert "Data Scraped At" in result

    def test_faculty_tool_exact_hit_never_runs_similarity(self):
        import datetime
        from dau_mcp.faculty_mcp_server import get_faculty_details
        cursor = MagicMock()
        cursor.fetchone.return_value = FACULTY_ROW + (datetime.datetime(2026, 1, 1),)
        with patch("dau_mcp.faculty_mcp_server.db_connection", return_value=_mock_db(cursor)), \
             patch("dau_mcp.faculty_mcp_server.find_similar_names") as mock_fuzzy:
            result = _tool_fn(get_faculty_details)("Ankush chander")

        mock_fuzzy.assert_not_called()
        assert "No exact match" not in result

    def test_staff_tool_discloses_a_fuzzy_match(self):
        import datetime
        from dau_mcp.staff_mcp_server import get_staff_details
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, STAFF_ROW + (datetime.datetime(2026, 1, 1),)]
        with patch("dau_mcp.staff_mcp_server.db_connection", return_value=_mock_db(cursor)), \
             patch("dau_mcp.staff_mcp_server.find_similar_names", return_value=["Akash Desai"]):
            result = _tool_fn(get_staff_details)("Akaash Desa")

        assert "No exact match for **'Akaash Desa'**" in result
        assert "### Detailed Staff Profile: Akash Desai" in result

    def test_staff_tool_unrelated_name_returns_not_found(self):
        from dau_mcp.staff_mcp_server import get_staff_details
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None]
        with patch("dau_mcp.staff_mcp_server.db_connection", return_value=_mock_db(cursor)), \
             patch("dau_mcp.staff_mcp_server.find_similar_names", return_value=[]):
            assert _tool_fn(get_staff_details)("Elon Musk") == \
                "No staff member found matching 'Elon Musk'."


# ==============================================================================
# Integration: the real query, against a real pg_trgm
# ==============================================================================
# Real directory names (scraped subset), chosen to include every required match
# *and* the near misses that constrain the threshold from below and above.
FACULTY_FIXTURE = [
    "Ankit vijayvargiya", "Ankush chander", "Sunitha v", "Prince vijay",
    "K narayana chandran", "Subhas chandra nandy", "Arunava chakravarty",
    "Aditya tatu", "Anish mathuria", "Rahul muthu", "Mukesh tiwari",
    "Madhumita mazumdar", "Jayanth varma", "Swati priya", "Arpita mal",
    "Bhaskar chaudhury", "Vinay palaparthy", "Sudip bera",
]
STAFF_FIXTURE = [
    "Rajesh Patel", "Savita Joshi", "Anand Chavan", "Priyank Santola",
    "Priya Kumari", "Akash Desai", "Abhilash Kumar Bhaskaran",
    "Mukesh Shrimali", "Rajendra Shah", "Keshurbhai M Zala",
]

# Issue #42's required resolutions.
REQUIRED_MATCHES = [
    ("Sunita", "Sunitha v"),
    ("Vijay Vargia", "Ankit vijayvargiya"),
    ("Vijayvargia", "Ankit vijayvargiya"),
    ("Chandar", "Ankush chander"),
]

# Genuinely different people; must stay unresolved even though the corpus
# contains a "Rajesh", a "Priyank" and several "Mukesh"es.
REQUIRED_NON_MATCHES = [
    "Rajesh Khanna", "Elon Musk", "Priyanka Deshmukh", "Christopher Nolan",
    "Fatima Sheikh", "Zzyzx Qwerty",
]


def _probe_database():
    """Return (connect_kwargs, None) if a pg_trgm-enabled database is reachable."""
    try:
        import psycopg2
    except ImportError:
        return None, "psycopg2 not installed"

    kwargs = dict(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "daiict_db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        connect_timeout=3,
    )
    try:
        conn = psycopg2.connect(**kwargs)
    except Exception as e:
        return None, f"no database reachable ({type(e).__name__})"
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm';")
            if not cur.fetchone():
                return None, "pg_trgm not installed — run scripts/init_db.sql"
    finally:
        conn.close()
    return kwargs, None


_DB_KWARGS, _SKIP_REASON = _probe_database()


@pytest.mark.skipif(_DB_KWARGS is None, reason=str(_SKIP_REASON))
class TestSimilarityAgainstLivePostgres:
    """Exercises the production helper itself; only the connection is redirected."""

    @pytest.fixture
    def patched_db(self):
        import psycopg2
        conn = psycopg2.connect(**_DB_KWARGS)          # autocommit off, as the pool hands out
        with conn.cursor() as cur:
            # TEMP tables shadow the real ones for this session only: the real
            # faculty/staff data is never read or written by these tests.
            cur.execute("""
                CREATE TEMP TABLE faculty (
                    name VARCHAR(255), email VARCHAR(255), phone VARCHAR(100),
                    address TEXT, education TEXT, specialization TEXT,
                    profile_url TEXT, image_url TEXT,
                    faculty_type VARCHAR(50) DEFAULT 'Regular'
                ) ON COMMIT PRESERVE ROWS;
                CREATE TEMP TABLE staff (
                    name VARCHAR(255), email VARCHAR(255), phone VARCHAR(100),
                    address TEXT, qualification TEXT, designation VARCHAR(255),
                    profile_url TEXT, image_url TEXT
                ) ON COMMIT PRESERVE ROWS;
            """)
            cur.executemany("INSERT INTO faculty(name) VALUES (%s);",
                            [(n,) for n in FACULTY_FIXTURE])
            cur.executemany("INSERT INTO staff(name) VALUES (%s);",
                            [(n,) for n in STAFF_FIXTURE])
        conn.commit()

        @contextmanager
        def fake_db_connection():
            yield conn
            conn.commit()

        with patch("api.services.name_matching.db_connection", fake_db_connection), \
             patch("api.services.faculty_service.db_connection", fake_db_connection):
            yield conn
        conn.close()

    @pytest.mark.parametrize("query,expected", REQUIRED_MATCHES)
    def test_required_misspellings_resolve(self, patched_db, query, expected):
        """Issue #42's cases. 'Vijay Vargia' scores 0.571, so this also fails if
        the query ever runs at PostgreSQL's default 0.6 word_similarity cut-off."""
        assert find_similar_names("faculty", query)[:1] == [expected]

    @pytest.mark.parametrize("query", REQUIRED_NON_MATCHES)
    def test_unrelated_names_resolve_to_nothing(self, patched_db, query):
        assert find_similar_names("faculty", query) == []
        assert find_similar_names("staff", query) == []

    def test_staff_misspelling_resolves(self, patched_db):
        assert find_similar_names("staff", "Akaash Desa")[:1] == ["Akash Desai"]

    def test_ranking_breaks_ties_by_full_string_similarity(self, patched_db):
        """'Chandar' ties three names at word_similarity 0.625."""
        assert find_similar_names("faculty", "Chandar")[0] == "Ankush chander"

    def test_default_word_similarity_threshold_would_lose_a_required_match(self, patched_db):
        """Documents *why* the threshold is overridden rather than left alone."""
        with patch("api.services.name_matching.TRGM_WORD_SIMILARITY_THRESHOLD",
                   PG_DEFAULT_WORD_SIMILARITY_THRESHOLD):
            assert find_similar_names("faculty", "Vijay Vargia") == []

    def test_default_similarity_threshold_would_admit_an_unrelated_name(self, patched_db):
        """The other PG default, 0.3, is too loose for these short names."""
        with patch("api.services.name_matching.TRGM_WORD_SIMILARITY_THRESHOLD",
                   PG_DEFAULT_SIMILARITY_THRESHOLD):
            assert "Rajesh Patel" in find_similar_names("staff", "Rajesh Khanna")

    def test_end_to_end_details_lookup_discloses_the_matched_name(self, patched_db):
        """Full chain: exact ILIKE misses, similarity resolves, reply names both."""
        from api.services.faculty_service import get_faculty_details_db
        result = get_faculty_details_db("Chandar")
        assert "No exact match for **'Chandar'**" in result
        assert "### Detailed Profile: Ankush chander" in result

    def test_end_to_end_search_returns_only_the_selected_best_match(self, patched_db):
        """The notice promises one closest name, so a tie must not leak the
        runners-up into the results list. 'Chandar' ties three fixture names at
        word_similarity 0.625; only the ranked winner may appear."""
        from api.services.faculty_service import search_faculty_db
        with patch("api.services.faculty_service.PostgresFullTextRetriever") as mock_retriever:
            mock_retriever.return_value.retrieve_faculty.return_value = []
            result = search_faculty_db("Chandar")

        assert "No exact match for **'Chandar'**" in result
        assert "Found 1 record(s):" in result
        assert "#### 1. Ankush chander" in result
        # The other two tied candidates cleared the threshold but lost the ranking.
        assert "Subhas chandra nandy" not in result
        assert "K narayana chandran" not in result

    def test_end_to_end_exact_lookup_is_unchanged(self, patched_db):
        from api.services.faculty_service import get_faculty_details_db
        result = get_faculty_details_db("Ankush chander")
        assert result.startswith("### Detailed Profile: Ankush chander")
        assert "No exact match" not in result

    def test_threshold_does_not_survive_the_call(self, patched_db):
        """The pooled connection must go back with pg_trgm's default in place."""
        assert find_similar_names("faculty", "Chandar")[0] == "Ankush chander"

        with patched_db.cursor() as cur:
            # The GUC only exists once pg_trgm has been used in the session,
            # so it is read after the call, not before.
            cur.execute("SHOW pg_trgm.word_similarity_threshold;")
            assert float(cur.fetchone()[0]) == PG_DEFAULT_WORD_SIMILARITY_THRESHOLD

    def test_threshold_does_not_leak_from_an_autocommit_connection(self):
        """Same guarantee when the connection has no surrounding transaction."""
        import psycopg2
        conn = psycopg2.connect(**_DB_KWARGS)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute("CREATE TEMP TABLE faculty (name VARCHAR(255));")
                cur.executemany("INSERT INTO faculty(name) VALUES (%s);",
                                [(n,) for n in FACULTY_FIXTURE])

            @contextmanager
            def fake_db_connection():
                yield conn

            with patch("api.services.name_matching.db_connection", fake_db_connection):
                assert find_similar_names("faculty", "Chandar")[0] == "Ankush chander"

            with conn.cursor() as cur:
                cur.execute("SHOW pg_trgm.word_similarity_threshold;")
                assert float(cur.fetchone()[0]) == PG_DEFAULT_WORD_SIMILARITY_THRESHOLD
                cur.execute("SELECT 1;")                # connection still usable
                assert cur.fetchone()[0] == 1
        finally:
            conn.close()
