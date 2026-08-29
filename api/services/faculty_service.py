"""
Faculty Service
===============
Handles all faculty-related database queries and in-memory context caching.
"""
from typing import Any, Dict, List, Optional
from core import config
from core.database import db_connection
from api.services.retrieval import PostgresFullTextRetriever
from api.services.name_matching import find_similar_names, fuzzy_match_notice

logger = config.get_logger("api.services.faculty_service")

# ==============================================================================
# In-Memory Context Cache
# ==============================================================================
_cached_faculty_context: Optional[str] = None


def clear_faculty_cache() -> None:
    """Invalidate the faculty context cache (call after a sync operation)."""
    global _cached_faculty_context
    logger.info("Faculty context cache cleared.")
    _cached_faculty_context = None


def fetch_all_faculty_context() -> str:
    """
    Build a formatted text block of all faculty records for use as Gemini RAG context.
    Result is cached in memory after the first call; cleared by clear_faculty_cache().
    """
    global _cached_faculty_context
    if _cached_faculty_context is not None:
        return _cached_faculty_context

    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT name, faculty_type, email, phone, address,
                           education, specialization, profile_url
                    FROM faculty
                    ORDER BY name;
                """)
                rows = cursor.fetchall()
                if not rows:
                    return "No faculty data found in the database. Please synchronize data first."

                parts = []
                for i, row in enumerate(rows, 1):
                    name, ftype, email, phone, addr, edu, spec, url = row
                    parts.append(
                        f"Faculty {i}: {name}\n"
                        f" - Type: {ftype} Faculty\n"
                        f" - Email: {email or 'N/A'}\n"
                        f" - Phone: {phone or 'N/A'}\n"
                        f" - Office: {addr or 'N/A'}\n"
                        f" - Education: {edu or 'N/A'}\n"
                        f" - Specialization: {spec or 'N/A'}\n"
                        f" - Profile: {url or 'N/A'}\n"
                    )
                _cached_faculty_context = "\n".join(parts)
                return _cached_faculty_context
    except Exception as e:
        logger.error(f"Error fetching faculty context: {e}")
        return ""


# ==============================================================================
# Direct Database Query Helpers
# ==============================================================================
def _faculty_records_by_name(names: List[str]) -> List[Dict[str, Any]]:
    """Fetch full faculty rows for exact names, preserving the order given."""
    if not names:
        return []
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT name, faculty_type, email, phone, address,
                       education, specialization, profile_url
                FROM faculty
                WHERE name = ANY(%s);
            """, (list(names),))
            by_name = {row[0]: row for row in cursor.fetchall()}

    records = []
    for name in names:
        row = by_name.get(name)
        if row:
            records.append({
                "name": row[0], "faculty_type": row[1], "email": row[2],
                "phone": row[3], "address": row[4], "education": row[5],
                "specialization": row[6], "profile_url": row[7],
            })
    return records


def search_faculty_db(query: str, error_on_empty: bool = True) -> Optional[str]:
    """Full-text search across faculty name, specialization, education, and email using RAG retriever."""
    try:
        retriever = PostgresFullTextRetriever()
        records = retriever.retrieve_faculty(query, limit=10)

        # Trigram fallback: only once exact/full-text retrieval came back empty.
        fuzzy_notice = ""
        if not records:
            records = _faculty_records_by_name(find_similar_names("faculty", query, limit=1))
            if records:
                fuzzy_notice = fuzzy_match_notice(query.strip(), records[0]["name"]) + "\n"

        if not records:
            if error_on_empty:
                return (
                    f"I couldn't find any faculty or staff members matching "
                    f"**'{query}'** in our records.\n\n"
                    "Please try searching for:\n"
                    "- A specific professor's or staff member's name (e.g., *'Yash Vasavada'*, *'Pinal Patel'*)\n"
                    "- A research field (e.g., *'Machine Learning'*, *'VLSI'*, *'NLP'*)\n"
                    "- A staff department or role (e.g., *'Finance'*, *'Placement'*)\n"
                    "- Or educational background (e.g., *'IIT Bombay'*)"
                )
            return None

        out = [f"### Search Results for '{query}'", f"Found {len(records)} record(s):", ""]
        for i, rec in enumerate(records, 1):
            out.append(f"#### {i}. {rec.get('name')} ({rec.get('faculty_type')} Faculty)")
            if rec.get('email'): out.append(f"- **Email:** {rec.get('email')}")
            if rec.get('phone'): out.append(f"- **Phone:** {rec.get('phone')}")
            if rec.get('address'): out.append(f"- **Office:** {rec.get('address')}")
            if rec.get('education'): out.append(f"- **Education:** {rec.get('education')}")
            if rec.get('specialization'): out.append(f"- **Specialization:** {rec.get('specialization')}")
            if rec.get('profile_url'): out.append(f"- **Profile:** [{rec.get('profile_url')}]({rec.get('profile_url')})")
            out.append("")
        return fuzzy_notice + "\n".join(out)
    except Exception as e:
        logger.error(f"search_faculty_db failed: {e}")
        return f"Database query failed: {e}"


def list_all_faculty_db() -> str:
    """Return a compact directory of all faculty members."""
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT name, email, faculty_type FROM faculty ORDER BY name;")
                rows = cursor.fetchall()
                if not rows:
                    return "No faculty members found in the database. Please sync first."
                out = ["### DA-IICT Faculty Directory", f"Total Members: {len(rows)}", ""]
                for i, (name, email, ftype) in enumerate(rows, 1):
                    out.append(f"{i}. **{name}** ({email or 'N/A'}) - *{ftype} Faculty*")
                return "\n".join(out)
    except Exception as e:
        logger.error(f"list_all_faculty_db failed: {e}")
        return f"Database query failed: {e}"


def get_faculty_details_db(name_or_email: str, error_on_empty: bool = True) -> Optional[str]:
    """
    Retrieve full profile of a faculty member by name or email.
    Includes token-based typo-tolerant fallback matching.
    """
    pattern = f"%{name_or_email.strip()}%"
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT name, email, phone, address, education, specialization,
                           profile_url, image_url, faculty_type
                    FROM faculty
                    WHERE name ILIKE %s OR email ILIKE %s
                    LIMIT 1;
                """, (pattern, pattern))
                row = cursor.fetchone()

                # Token-based typo fallback. Like the trigram path below, this
                # can select a different person than was typed, so the reply
                # discloses whichever name it settled on.
                fuzzy_notice = ""
                if not row:
                    tokens = [t for t in name_or_email.split() if len(t) >= 3]
                    if tokens:
                        clauses = " OR ".join(["name ILIKE %s"] * len(tokens))
                        params = tuple(f"%{t}%" for t in tokens)
                        cursor.execute(
                            f"SELECT name, email, phone, address, education, specialization, "
                            f"profile_url, image_url, faculty_type FROM faculty WHERE {clauses} ORDER BY name;",
                            params,
                        )
                        candidates = cursor.fetchall()
                        if candidates:
                            row = max(
                                candidates,
                                key=lambda r: sum(1 for t in tokens if t in r[0].lower()),
                            )
                            if row[0].strip().lower() != name_or_email.strip().lower():
                                fuzzy_notice = fuzzy_match_notice(
                                    name_or_email.strip(), row[0]
                                ) + "\n"

                # Trigram similarity fallback — last resort, and the only other
                # path here whose answer may be a different name than was asked
                # for, so the reply discloses the substitution.
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
                                   profile_url, image_url, faculty_type
                            FROM faculty
                            WHERE name = %s
                            LIMIT 1;
                        """, (candidate,))
                        row = cursor.fetchone()
                        if row:
                            fuzzy_notice = fuzzy_match_notice(name_or_email.strip(), candidate) + "\n"
                            break

                if not row:
                    if error_on_empty:
                        return f"Could not find any faculty member matching '{name_or_email}'."
                    return None

                name, email, phone, addr, edu, spec, url, img, ftype = row
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
                return fuzzy_notice + "\n".join(out)
    except Exception as e:
        logger.error(f"get_faculty_details_db failed: {e}")
        return f"Database query failed: {e}"


def search_faculty_by_expertise_db(expertise: str, error_on_empty: bool = True) -> Optional[str]:
    """Search faculty by their specialization field(s). Supports comma/and/or delimited terms."""
    import re
    raw = re.split(r",|\s+and\s+|\s+or\s+", expertise, flags=re.IGNORECASE)
    terms = [t.strip().replace("meachine", "machine") for t in raw if t.strip()]

    if not terms:
        return f"No valid search terms extracted from: '{expertise}'." if error_on_empty else None

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
                    if error_on_empty:
                        formatted = " or ".join(f"**'{t}'**" for t in terms)
                        return (
                            f"I couldn't find any faculty specialized in {formatted}.\n\n"
                            "Try related areas like *'Machine Learning'*, *'Data Science'*, "
                            "*'Signal Processing'*, or *'VLSI'*."
                        )
                    return None

                header = " and ".join(f"**'{t}'**" for t in terms)
                out = [f"### Faculty specialized in {header}", f"Found {len(rows)} member(s):", ""]
                for i, (name, email, phone, addr, edu, spec, url, ftype) in enumerate(rows, 1):
                    out.append(f"#### {i}. {name} ({ftype} Faculty)")
                    if email: out.append(f"- **Email:** {email}")
                    if edu:   out.append(f"- **Education:** {edu}")
                    if spec:  out.append(f"- **Specialization:** {spec}")
                    out.append("")
                return "\n".join(out)
    except Exception as e:
        logger.error(f"search_faculty_by_expertise_db failed: {e}")
        return f"Database query failed: {e}"
