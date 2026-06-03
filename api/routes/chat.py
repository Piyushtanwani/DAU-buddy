import os
from fastapi import APIRouter, HTTPException
from dotenv import load_dotenv

from core import config
from core.schemas import ChatRequest, ChatResponse
from api.services import (
    fetch_all_faculty_context,
    fetch_all_staff_context,
    call_gemini_api,
    process_fallback_message,
    clear_context_caches,
    is_gemini_available,
    record_gemini_failure,
    SYSTEM_INSTRUCTIONS_TEMPLATE,
)
from scrapers import faculty_scraper, staff_scraper

logger = config.get_logger("api.routes.chat")
router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Main conversational endpoint.
    Routes between sync triggers, Gemini RAG, and the local NLP fallback engine.
    """
    try:
        # Hot-reload .env on every request so Gemini key changes take effect immediately
        _env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            ".env",
        )
        load_dotenv(dotenv_path=_env_path, override=True)

        cleaned = request.message.strip().lower()

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

        # ── 2. LLM RAG Pipeline (OpenRouter) ───────────────────────────────────
        api_key = os.getenv("OPENROUTER_API_KEY")
        if api_key and is_gemini_available():
            logger.info("Processing via LLM RAG pipeline (OpenRouter)...")
            faculty_db = fetch_all_faculty_context()
            staff_db = fetch_all_staff_context()
            system_instruction = SYSTEM_INSTRUCTIONS_TEMPLATE.format(
                faculty_database=faculty_db,
                staff_database=staff_db,
            )
            try:
                response_text = call_gemini_api(api_key, system_instruction, request.history)
                return ChatResponse(response=response_text)
            except Exception:
                logger.exception("Gemini RAG failed — falling back to local NLP engine.")
                record_gemini_failure()
                return ChatResponse(response=process_fallback_message(request.message))

        # ── 3. Local NLP Fallback ──────────────────────────────────────────────
        logger.info("Gemini unavailable or in cooldown — using local NLP engine.")
        return ChatResponse(response=process_fallback_message(request.message))

    except Exception as e:
        logger.error(f"Unhandled error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))
