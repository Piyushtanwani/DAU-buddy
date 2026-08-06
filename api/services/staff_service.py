"""
Staff Service
=============
Handles all staff-related database queries and in-memory context caching.
"""
from typing import Any, Dict, List, Optional
from core import config
from core.database import db_connection
from api.services.retrieval import PostgresFullTextRetriever
from api.services.name_matching import find_similar_names, fuzzy_match_notice

logger = config.get_logger("api.services.staff_service")

# ==============================================================================
# In-Memory Context Cache
# ==============================================================================
_cached_staff_context: Optional[str] = None


def clear_staff_cache() -> None:
    """Invalidate the staff context cache (call after a sync operation)."""
    global _cached_staff_context
    logger.info("Staff context cache cleared.")
    _cached_staff_context = None


def fetch_all_staff_context() -> str:
    """
    Build a formatted text block of all staff records for use as Gemini RAG context.
    Result is cached in memory after the first call; cleared by clear_staff_cache().
    """
    global _cached_staff_context
    if _cached_staff_context is not None:
        return _cached_staff_context

    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT name, designation, email, phone, address,
                           qualification, profile_url
                    FROM staff
                    ORDER BY name;
                """)
                rows = cursor.fetchall()
                if not rows:
                    return "No staff data found in the database. Please synchronize data first."

                parts = []
                for i, row in enumerate(rows, 1):
                    name, desig, email, phone, addr, qual, url = row
                    parts.append(
                        f"Staff {i}: {name}\n"
                        f" - Designation: {desig or 'N/A'}\n"
                        f" - Email: {email or 'N/A'}\n"
                        f" - Phone: {phone or 'N/A'}\n"
                        f" - Office: {addr or 'N/A'}\n"
                        f" - Qualification: {qual or 'N/A'}\n"
                        f" - Profile: {url or 'N/A'}\n"
                    )
                _cached_staff_context = "\n".join(parts)
                return _cached_staff_context
    except Exception as e:
        logger.error(f"Error fetching staff context: {e}")
        return ""


# ==============================================================================
# Direct Database Query Helpers
# ==============================================================================
def _staff_records_by_name(names: List[str]) -> List[Dict[str, Any]]:
    """Fetch full staff rows for exact names, preserving the order given."""
    if not names:
        return []
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT name, designation, email, phone, address,
                       qualification, profile_url
                FROM staff
                WHERE name = ANY(%s);
            """, (list(names),))
            by_name = {row[0]: row for row in cursor.fetchall()}

    records = []
    for name in names:
        row = by_name.get(name)
        if row:
            records.append({
                "name": row[0], "designation": row[1], "email": row[2],
                "phone": row[3], "address": row[4], "qualification": row[5],
                "profile_url": row[6],
            })
    return records


def search_staff_db(query: str, error_on_empty: bool = True) -> Optional[str]:
    """Full-text search across staff name, designation, qualification, and email using RAG retriever."""
    try:
        retriever = PostgresFullTextRetriever()
        records = retriever.retrieve_staff(query, limit=10)

        # Trigram fallback: only once exact/full-text retrieval came back empty.
        fuzzy_notice = ""
        if not records:
            records = _staff_records_by_name(find_similar_names("staff", query, limit=1))
            if records:
                fuzzy_notice = fuzzy_match_notice(query.strip(), records[0]["name"]) + "\n"

        if not records:
            if error_on_empty:
                return (
                    f"I couldn't find any staff members matching **'{query}'** in our records.\n\n"
                    "Please try:\n"
                    "- A specific name (e.g., *'Akash Desai'*)\n"
                    "- A designation (e.g., *'Finance'*, *'Library'*, *'Registrar'*)\n"
                    "- Or a qualification (e.g., *'MBA'*)"
                )
            return None

        out = [f"### Staff Search Results for '{query}'", f"Found {len(records)} record(s):", ""]
        for i, rec in enumerate(records, 1):
            out.append(f"#### {i}. {rec.get('name')}")
            if rec.get('designation'): out.append(f"- **Designation/Role:** {rec.get('designation')}")
            if rec.get('email'): out.append(f"- **Email:** {rec.get('email')}")
            if rec.get('phone'): out.append(f"- **Phone:** {rec.get('phone')}")
            if rec.get('address'): out.append(f"- **Office Address:** {rec.get('address')}")
            if rec.get('qualification'): out.append(f"- **Qualification:** {rec.get('qualification')}")
            if rec.get('profile_url'): out.append(f"- **Profile:** [{rec.get('profile_url')}]({rec.get('profile_url')})")
            out.append("")
        return fuzzy_notice + "\n".join(out)
    except Exception as e:
        logger.error(f"search_staff_db failed: {e}")
        return f"Database query failed: {e}"


def list_all_staff_db() -> str:
    """Return a compact directory of all staff members."""
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT name, email, designation FROM staff ORDER BY name;")
                rows = cursor.fetchall()
                if not rows:
                    return "No staff members found in the database. Please sync first."
                out = ["### DA-IICT Staff Directory", f"Total Members: {len(rows)}", ""]
                for i, (name, email, desig) in enumerate(rows, 1):
                    desig_str = f" - *{desig}*" if desig else ""
                    out.append(f"{i}. **{name}** ({email or 'N/A'}){desig_str}")
                return "\n".join(out)
    except Exception as e:
        logger.error(f"list_all_staff_db failed: {e}")
        return f"Database query failed: {e}"


def get_staff_details_db(name_or_email: str, error_on_empty: bool = True) -> Optional[str]:
    """
    Retrieve full profile of a staff member by name or email.
    Includes token-based typo-tolerant fallback matching.
    """
    pattern = f"%{name_or_email.strip()}%"
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT name, email, phone, address, qualification,
                           designation, profile_url, image_url
                    FROM staff
                    WHERE name ILIKE %s OR email ILIKE %s
                    LIMIT 1;
                """, (pattern, pattern))
                row = cursor.fetchone()

                # Token-based typo fallback
                if not row:
                    tokens = [t for t in name_or_email.split() if len(t) >= 3]
                    if tokens:
                        clauses = " OR ".join(["name ILIKE %s"] * len(tokens))
                        params = tuple(f"%{t}%" for t in tokens)
                        cursor.execute(
                            f"SELECT name, email, phone, address, qualification, "
                            f"designation, profile_url, image_url FROM staff WHERE {clauses} ORDER BY name;",
                            params,
                        )
                        candidates = cursor.fetchall()
                        if candidates:
                            row = max(
                                candidates,
                                key=lambda r: sum(1 for t in tokens if t in r[0].lower()),
                            )

                # Trigram similarity fallback — last resort, and the only path
                # here whose answer may be a different name than was asked for,
                # so the reply discloses the substitution.
                fuzzy_notice = ""
                if not row:
                    for candidate in find_similar_names("staff", name_or_email, limit=1):
                        cursor.execute("""
                            SELECT name, email, phone, address, qualification,
                                   designation, profile_url, image_url
                            FROM staff
                            WHERE name = %s
                            LIMIT 1;
                        """, (candidate,))
                        row = cursor.fetchone()
                        if row:
                            fuzzy_notice = fuzzy_match_notice(name_or_email.strip(), candidate) + "\n"
                            break

                if not row:
                    if error_on_empty:
                        return f"Could not find any staff member matching '{name_or_email}'."
                    return None

                name, email, phone, addr, qual, desig, url, img = row
                out = [
                    f"### Detailed Staff Profile: {name}",
                    f"- **Role/Designation:** {desig or 'N/A'}",
                    f"- **Email Address:** {email or 'N/A'}",
                    f"- **Contact Number:** {phone or 'N/A'}",
                    f"- **Office Address:** {addr or 'N/A'}",
                    f"- **Qualifications:** {qual or 'N/A'}",
                ]
                if url: out.append(f"- **Profile URL:** [{url}]({url})")
                if img: out.append(f"- **Profile Image:** [{img}]({img})")
                return fuzzy_notice + "\n".join(out)
    except Exception as e:
        logger.error(f"get_staff_details_db failed: {e}")
        return f"Database query failed: {e}"
