import os
import asyncio
from fastapi import APIRouter, HTTPException, Request
from core import config
import hashlib
from core.database import db_connection
from core.schemas import ChatRequest, ChatResponse
from api.services import (
    call_gemini_api,
    process_fallback_message,
    clear_context_caches,
    is_gemini_available,
    record_gemini_failure,
    SYSTEM_INSTRUCTIONS_TEMPLATE,
)
from api.services.retrieval import PostgresFullTextRetriever
from api.services.context_builder import build_faculty_context, build_staff_context
from api.services.faculty_service import list_all_faculty_db
from api.services.staff_service import list_all_staff_db
from api.services.library_service import LibraryService

from scrapers import faculty_scraper, staff_scraper

logger = config.get_logger("api.routes.chat")
router = APIRouter()

# Shared library service instance (stateless, thread-safe)
_library_svc = LibraryService()

# ── Library intent keyword sets ───────────────────────────────────────────────
_LIBRARY_KEYWORDS = {
    "book", "books", "library", "resource centre", "resource center",
    "opac", "catalog", "catalogue", "borrow", "isbn", "publication",
    "textbook", "text book", "novel", "author", "publisher",
    "find a book", "search book", "check availability", "available book",
    "is it available", "copies available", "reserve book",
}


def _is_library_query(text: str) -> bool:
    """Return True if the message is asking about library/book resources."""
    t = text.lower()
    return any(kw in t for kw in _LIBRARY_KEYWORDS)


def _extract_book_query(text: str) -> str:
    """
    Strip conversational framing and return the core search keyword(s).

    Strategy
    --------
    Pass 1 — Preposition anchor:
        Look for phrases like "related to X", "about X", "on X", "called X".
        These reliably mark where the real search topic begins.

    Pass 2 — Preamble strip:
        Remove leading conversational filler layer by layer:
        "can u suggest me a book to read" → ""
        Then strip trailing noise like "from the resource centre".

    Examples
    --------
    "can u suggest me a book to read related to computer networks" → "computer networks"
    "is there any book related to fiction"                         → "fiction"
    "find me a book on machine learning"                           → "machine learning"
    "search for textbooks about databases"                         → "databases"
    "do you have anything on algorithms"                           → "algorithms"
    """
    import re

    _TRAILING_NOISE = re.compile(
        r"\s*(from\s+(the\s+)?resource\s+cent(re|er)"
        r"|from\s+(the\s+)?library"
        r"|in\s+(the\s+)?library"
        r"|from\s+opac"
        r"|from\s+catalog(ue)?"
        r"|please|thanks|thank\s+you)\s*",
        re.IGNORECASE,
    )

    def _clean_tail(s: str) -> str:
        return _TRAILING_NOISE.sub(" ", s).strip()

    # ── Pass 1: extract after a preposition anchor ─────────────────────────
    for pattern in [
        r"related\s+to\s+(.+)",
        r"(?<!\w)about\s+(.+)",
        r"(?:^|\s)on\s+(.+)",          # require space before 'on' to avoid 'novels'
        r"(?:^|\s)for\s+(.+)",         # same for 'for'
        r"(?<!\w)regarding\s+(.+)",
        r"(?<!\w)called\s+(.+)",
        r"(?<!\w)titled\s+(.+)",
        r"(?<!\w)named\s+(.+)",
        r"(?:^|\s)by\s+(.+)",          # "novels by Chetan Bhagat" → "Chetan Bhagat"
        r"(?:^|\s)of\s+(.+)",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            candidate = _clean_tail(m.group(1))
            # Must be a real topic, not another stop phrase
            if len(candidate) >= 2 and not re.fullmatch(
                r"(a\s+)?book(s)?|textbook(s)?|novel(s)?|any|one|it|them",
                candidate, re.IGNORECASE
            ):
                return candidate

    # ── Pass 2: preamble strip (layer by layer) ────────────────────────────
    cleaned = text.strip()

    # Remove leading conversational openers
    cleaned = re.sub(
        r"^(can\s+u|can\s+you|could\s+you|would\s+you|do\s+you|is\s+there|"
        r"are\s+there|do\s+we\s+have|suggest|recommend|help\s+me(\s+find)?)\s+",
        "", cleaned, flags=re.IGNORECASE,
    ).strip()

    # Remove "me a book / any book / some books / a textbook" with optional verb
    cleaned = re.sub(
        r"^(me\s+)?(find\s+|get\s+|show\s+)?"
        r"(a\s+|any\s+|some\s+|the\s+)?"
        r"(book|books|textbook|textbooks|novel|novels|copy|copies)\s*"
        r"(to\s+read\s+|to\s+borrow\s+|i\s+can\s+read\s+)?",
        "", cleaned, flags=re.IGNORECASE,
    ).strip()

    # Strip any remaining leading prepositions left over
    cleaned = re.sub(
        r"^(on|about|related\s+to|for|regarding|covering|dealing\s+with)\s+",
        "", cleaned, flags=re.IGNORECASE,
    ).strip()

    # Strip trailing noise
    cleaned = _clean_tail(cleaned)

    # If we didn't manage to strip anything meaningful, fall back to full text
    return cleaned if len(cleaned) >= 2 else text.strip()


async def handle_library_fallback(book_query: str) -> str:
    """Helper to process library fallback logic and return the formatted markdown string."""
    try:
        results = await _library_svc.search_books(query=book_query, limit=5)
        if not results:
            return (
                f"📚 I searched the DA-IICT Resource Centre for **\"{book_query}\"** "
                f"but found no matching books.\n\n"
                "You can also search directly at: "
                "[opac.daiict.ac.in](https://opac.daiict.ac.in)"
            )

        lines = [
            f"📚 **Library Search Results for \"{ book_query }\"**",
            f"Found **{len(results)}** book(s) in the DA-IICT Resource Centre:",
            "",
        ]
        
        # Fetch availability in parallel
        async def fetch_avail(bib):
            if not bib: return None
            try:
                return await _library_svc.get_book_details(bib)
            except Exception:
                return None
                
        import asyncio
        details_list = await asyncio.gather(*(fetch_avail(b.get("biblionumber")) for b in results))

        for book, details in zip(results, details_list):
            title     = book.get("title", "Unknown Title")
            author    = book.get("author", "")
            link      = book.get("link", "")
            
            avail_str = "Unknown"
            if details:
                avail_str = f"{details.get('available_copies', 0)} / {details.get('total_copies', 0)}"

            lines.append(f"- **{title}**")
            if author:
                lines.append(f"  - Author: {author}")
            lines.append(f"  - Availability: {avail_str}")
            if link:
                lines.append(f"  - Link: {link}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Library search error in chat: {e}")
        return (
            f"⚠️ I tried to search the library catalog for **\"{book_query}\"** "
            f"but encountered an error: `{e}`\n\n"
            "Please try searching directly at: "
            "[opac.daiict.ac.in](https://opac.daiict.ac.in)"
        )


def get_role_from_request(request: Request) -> str:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return "Student"
    
    raw_key = auth.split(" ", 1)[1].strip()
    hashed_k = hashlib.sha256(raw_key.encode()).hexdigest()
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT role FROM api_keys WHERE hashed_key = %s AND status = 'Active'", (hashed_k,))
                row = cursor.fetchone()
                if row:
                    return row[0]
    except Exception:
        pass
    return "Student"

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: Request, body: ChatRequest):
    """
    Main conversational endpoint.
    Routes between sync triggers, library search, Gemini RAG, and the local NLP fallback engine.
    """
    try:
        cleaned = body.message.strip().lower()

        # ── 0. Library Search Trigger (Fallback) ──────────────────────────────
        api_key = os.getenv("GEMINI_API_KEY")
        if _is_library_query(body.message) and not (api_key and is_gemini_available()):
            logger.info("Chat trigger: library search detected (Gemini unavailable).")
            book_query = _extract_book_query(body.message)
            return ChatResponse(response=await handle_library_fallback(book_query))

        # ── 1. Sync Triggers ──────────────────────────────────────────────────
        if any(k in cleaned for k in ["sync staff", "scrape staff", "reload staff", "update staff database"]):
            logger.info("Chat trigger: manual staff synchronization initiated.")
            try:
                staff_data = staff_scraper.scrape_staff_data()
                if not staff_data:
                    return ChatResponse(response="[FAILED]: Could not scrape the live staff directory. Please check the logs.")
                staff_scraper.save_to_database(staff_data)
                clear_context_caches()
                return ChatResponse(response=(
                    f"**Staff Database synchronized successfully!**\n\n"
                    f"Reloaded **{len(staff_data)}** staff profiles from the live DA-IICT portal.\n"
                    "All query tools are now operating on the latest staff data!"
                ))
            except Exception as e:
                logger.error(f"Error during staff sync: {e}")
                return ChatResponse(response=f"[Error during staff synchronization]: {e}")

        elif any(k in cleaned for k in ["sync faculty", "sync faculties", "scrape faculty", "scrape faculties", "reload faculty", "reload faculties", "update faculty database"]):
            logger.info("Chat trigger: manual faculty synchronization initiated.")
            try:
                faculty_data = faculty_scraper.scrape_faculty_data()
                if not faculty_data:
                    return ChatResponse(response="[FAILED]: Could not scrape the live faculty directory. Please check the logs.")
                faculty_scraper.save_to_database(faculty_data)
                clear_context_caches()
                return ChatResponse(response=(
                    f"**Faculty Database synchronized successfully!**\n\n"
                    f"Reloaded **{len(faculty_data)}** faculty profiles from the live DA-IICT portal.\n"
                    "All query tools are now operating on the latest faculty data!"
                ))
            except Exception as e:
                logger.error(f"Error during faculty sync: {e}")
                return ChatResponse(response=f"[Error during faculty synchronization]: {e}")

        elif any(k in cleaned for k in ["sync", "scrape", "reload", "update database", "sync latest"]):
            logger.info("Chat trigger: full synchronization initiated.")
            try:
                faculty_data = faculty_scraper.scrape_faculty_data()
                if faculty_data:
                    faculty_scraper.save_to_database(faculty_data)
                staff_data = staff_scraper.scrape_staff_data()
                if staff_data:
                    staff_scraper.save_to_database(staff_data)
                clear_context_caches()
                return ChatResponse(response=(
                    f"**Full Database synchronized successfully!**\n\n"
                    f"- **{len(faculty_data) if faculty_data else 0}** faculty profiles\n"
                    f"- **{len(staff_data) if staff_data else 0}** staff profiles\n\n"
                    "All query tools are now operating on the latest university directory!"
                ))
            except Exception as e:
                logger.error(f"Error during full sync: {e}")
                return ChatResponse(response=f"[Error during synchronization]: {e}")

        # ── 2. Retrieval Strategy Selection ──────────────────────────────────────
        api_key = os.getenv("GEMINI_API_KEY")

        # Strategy B: List/Intent Queries (Bypass RAG)
        if any(k in cleaned for k in ["list all staff", "show all staff", "staff directory", "all staff"]):
            return ChatResponse(response=list_all_staff_db())
        if any(k in cleaned for k in ["list all", "show all", "directory", "all faculty", "all faculties"]) and \
           not any(k in cleaned for k in ["specializ", "expert", "teach", "research", "subject"]):
            return ChatResponse(response=list_all_faculty_db())

        # Strategy A: Informational Queries (RAG)
        if api_key and is_gemini_available():
            logger.info("Processing via RAG pipeline (Strategy A)...")
            retriever = PostgresFullTextRetriever()
            limit = config.get_retrieval_limit()
            
            # Query Expansion to ensure retriever fetches correct staff
            search_query = body.message
            if any(k in cleaned for k in ["wifi", "internet", "network", "router"]):
                search_query += " IT SYSTEMS"
                
            if any(k in cleaned for k in ["light", "fan", "ac"]) and any(w in cleaned for w in ["not work", "stop", "broken", "problem", "problems", "issue", "issues", "fix"]):
                search_query += " electrician electrical maintenance"
            
            faculty_records = retriever.retrieve_faculty(search_query, limit=limit)
            staff_records = retriever.retrieve_staff(search_query, limit=limit)
            
            user_role = get_role_from_request(request)
            if user_role in ("Faculty", "Staff", "Admin"):
                faculty_db = build_faculty_context(faculty_records)
                staff_db = build_staff_context(staff_records)
            else:
                faculty_db = "Limited Directory Data (Students):\n"
                staff_db = "Limited Directory Data (Students):\n"
                for r in faculty_records:
                    faculty_db += f"- {r.get('name', '')} (Specialization: {r.get('specialization', '')})\n"
                for r in staff_records:
                    staff_db += f"- {r.get('name', '')} (Designation: {r.get('designation', '')})\n"
            
            logger.info(f"Context Size - Faculty chars: {len(faculty_db)}, Staff chars: {len(staff_db)}")

            system_instruction = SYSTEM_INSTRUCTIONS_TEMPLATE.format(
                faculty_database=faculty_db,
                staff_database=staff_db,
            )
            try:
                response_text, token_usage = call_gemini_api(api_key, system_instruction, body.history)
                return ChatResponse(response=response_text)
            except Exception:
                logger.exception("Gemini RAG failed — falling back to local NLP engine/library.")
                record_gemini_failure()
                if _is_library_query(body.message):
                    return ChatResponse(response=await handle_library_fallback(_extract_book_query(body.message)))
                return ChatResponse(response=process_fallback_message(body.message))

        # ── 3. Local NLP Fallback ──────────────────────────────────────────────
        logger.info("Gemini unavailable or in cooldown — using local NLP engine.")
        if _is_library_query(body.message):
            return ChatResponse(response=await handle_library_fallback(_extract_book_query(body.message)))
        return ChatResponse(response=process_fallback_message(body.message))

    except Exception as e:
        logger.error(f"Unhandled error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))