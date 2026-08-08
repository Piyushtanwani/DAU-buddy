"""
Name Matching Service
=====================
Trigram-based (``pg_trgm``) name resolution shared by the faculty and staff
directory lookups.

This is the **last** step of the directory search chain, never the first one:

    1. exact      — ``name ILIKE '%query%'`` (unchanged, fastest)
    2. full-text  — ``websearch_to_tsquery`` via PostgresFullTextRetriever
    3. similarity — this module, only when 1 and 2 returned nothing

It resolves a *misspelled query to a real directory name*; the caller then
renders that name through its own existing exact-lookup formatting, so no
response format is duplicated here. Because the answer may be wrong, callers
must prefix ``fuzzy_match_notice()`` so the reply names both what the user
typed and who was actually matched.

Threshold evidence
------------------
Measured with PostgreSQL 16 / pg_trgm 1.6 over the live DA-IICT directory
(122 faculty + 91 staff names), ordered by word_similarity:

    query               top match              word_sim  similarity
    Vijayvargia         Ankit vijayvargiya      0.833     0.476     (want)
    Sunita              Sunitha v               0.714     0.417     (want)
    Chandar             Ankush chander          0.625     0.278     (want)
    Vijay Vargia        Ankit vijayvargiya      0.571     0.348     (want)
    -------------------------------------------------------- 0.55 cut
    Rajesh Khanna       Rajesh Patel            0.500     0.350     (reject)
    Vijay Vargia        Prince vijay            0.500     0.316     (reject)
    Priyanka Deshmukh   Priyank Santola         0.389     0.259     (reject)
    Elon Musk           Rahul muthu             0.200     0.100     (reject)

Neither PostgreSQL default works here: ``similarity_threshold`` (0.3) admits
"Priyank Santola" for "Priyanka Deshmukh", and ``word_similarity_threshold``
(0.6) rejects "Vijay Vargia" at 0.571. Plain ``similarity()`` cannot separate
the two groups at any threshold — "Chandar" scores 0.278 against its correct
match while unrelated "Rajesh Khanna" scores 0.350. Hence word_similarity at
0.55: above every unrelated score observed, at or below every required match.
"""
from typing import List

from core import config
from core.database import db_connection

logger = config.get_logger("api.services.name_matching")

# Minimum word_similarity for a candidate to be considered the same person.
# Deliberately tuned — see the module docstring for the measurements.
TRGM_WORD_SIMILARITY_THRESHOLD = 0.55

# word_similarity() measures how much of the query is contained in the name, so
# very short queries match almost everything ("an" scores 1.0 against "Anand").
# Anything this short is already handled by the exact ILIKE substring path.
MIN_QUERY_LENGTH = 4

# A misspelling should resolve to one person; a handful of alternatives is a
# safety net for the caller, not a search result page.
DEFAULT_CANDIDATE_LIMIT = 3

# Table names are interpolated into SQL, so they are whitelisted, never trusted.
_ALLOWED_TABLES = ("faculty", "staff")

# is_local is passed as a parameter and is always true: the threshold must never
# survive this call on a connection that goes back into the pool.
_THRESHOLD_SQL = "SELECT set_config('pg_trgm.word_similarity_threshold', %s, %s);"


def _similarity_sql(table: str) -> str:
    """Build the ranked similarity query for `table` (whitelisted)."""
    if table not in _ALLOWED_TABLES:
        raise ValueError(
            f"Unsupported table for similarity search: {table!r}. "
            f"Expected one of {_ALLOWED_TABLES}."
        )
    # `%s <%% name` (the word_similarity operator) rather than a bare function
    # call in WHERE, so the GIN trigram index on name is usable. Ties are
    # common on a single shared token ("Chandar" ties three names at 0.625),
    # so ordering falls through to full-string similarity and then name for a
    # deterministic winner.
    return f"""
        SELECT name
        FROM {table}
        WHERE %s <%% name
        ORDER BY word_similarity(%s, name) DESC,
                 similarity(%s, name) DESC,
                 name ASC
        LIMIT %s;
    """


def find_similar_names(
    table: str,
    query: str,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> List[str]:
    """
    Return directory names similar to `query`, best match first.

    Args:
        table: 'faculty' or 'staff'.
        query: The (possibly misspelled) name the user typed.
        limit: Maximum candidates to return.

    Returns an empty list when nothing clears the similarity threshold, when
    the query is too short to match safely, or when the lookup fails.
    """
    sql = _similarity_sql(table)  # validate the table before touching the DB
    cleaned = (query or "").strip()
    if len(cleaned) < MIN_QUERY_LENGTH:
        return []

    def _run(cur) -> List[str]:
        # The `<%` operator reads its cut-off from a GUC, so the setting must
        # still be in effect when the SELECT runs — but it must not outlive this
        # call, because pooled connections are handed to other callers
        # afterwards. The setting is therefore always transaction-local: the
        # pool's connections have autocommit off, so both statements share the
        # transaction the pool commits on exit. An autocommit connection has no
        # such transaction, so one is opened here and rolled back below; this
        # function only reads.
        started_transaction = False
        if getattr(cur.connection, "autocommit", False):
            cur.execute("BEGIN;")
            started_transaction = True
        try:
            cur.execute(_THRESHOLD_SQL, (str(TRGM_WORD_SIMILARITY_THRESHOLD), True))
            cur.execute(sql, (cleaned, cleaned, cleaned, limit))
            return [row[0] for row in cur.fetchall()]
        finally:
            if started_transaction:
                # Discards the local threshold and clears the aborted state a
                # failed statement would otherwise leave behind.
                try:
                    cur.execute("ROLLBACK;")
                except Exception as rollback_error:
                    logger.error(
                        f"Failed to roll back similarity transaction: {rollback_error}"
                    )

    try:
        if cursor is not None:
            # Reuse the caller's cursor: avoids a second pool checkout while the
            # caller still holds one, and keeps the threshold local to the
            # caller's transaction.
            names = _run(cursor)
        else:
            with db_connection() as conn:
                with conn.cursor() as own_cursor:
                    names = _run(own_cursor)

        if names:
            logger.info(
                f"Similarity fallback matched {table} name(s) {names} for query '{cleaned}'."
            )
        return names
    except Exception as e:
        logger.error(f"find_similar_names failed for {table} query '{cleaned}': {e}")
        return []


def fuzzy_match_notice(query: str, matched_name: str) -> str:
    """
    Disclosure banner for a result produced by similarity matching.

    The match may be wrong, so the reply must never read as if the user's
    spelling was found: it states what was typed and who was actually matched.
    """
    return (
        f"> No exact match for **'{query}'** in the directory. "
        f"Showing the closest name found: **{matched_name}**.\n"
        f"> If that is not who you meant, please check the spelling.\n"
    )
