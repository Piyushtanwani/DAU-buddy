import time
import requests
from typing import List, Optional

from core import config
from core.schemas import ChatMessage

logger = config.get_logger("api.services.gemini")

# ==============================================================================
# Gemini API Availability Circuit Breaker
# ==============================================================================
_gemini_healthy: bool = True
_gemini_last_check: float = 0.0
_GEMINI_COOLDOWN: float = 60.0   # seconds before retrying after a failure


def is_gemini_available() -> bool:
    """
    Returns True if Gemini is currently considered reachable.
    During a cooldown window following a failure, returns False to prevent
    slow API retry loops and route traffic to the fast local NLP engine.
    """
    global _gemini_healthy, _gemini_last_check
    if not _gemini_healthy:
        if time.time() - _gemini_last_check < _GEMINI_COOLDOWN:
            return False
        # Cooldown expired — allow one retry
        _gemini_healthy = True
    return True


def record_gemini_failure() -> None:
    """Mark Gemini as failed and start the cooldown timer."""
    global _gemini_healthy, _gemini_last_check
    logger.warning("Gemini connection failed. Activating 60s bypass cooldown.")
    _gemini_healthy = False
    _gemini_last_check = time.time()


# ==============================================================================
# Gemini RAG System Instructions Template
# ==============================================================================
SYSTEM_INSTRUCTIONS_TEMPLATE = """\
You are the DA-IICT Faculty & Staff AI Buddy, a highly intelligent conversational \
search assistant for Dhirubhai Ambani Institute of Information and Communication Technology (DA-IICT).
You are helping students, researchers, and visitors search, discover, and analyze faculty \
and staff profiles based on official university records.

Below is the complete database of all DA-IICT Faculty members. Use this as your primary \
source of ground-truth information:
=== DA-IICT FACULTY DATABASE ===
{faculty_database}
================================

Below is the complete database of all DA-IICT Staff members. Use this as your primary \
source of ground-truth information:
=== DA-IICT STAFF DATABASE ===
{staff_database}
==============================

Guidelines for Conversation Flow:
1. Ground your answers strictly on the databases provided above.
2. DO NOT dump raw emails, phones, or full education details unless specifically asked.
3. For general queries adopt a friendly, conversational approach — name relevant people \
   and briefly explain why they match, then invite a follow-up.
4. When suggesting professors/staff, explain *why* based on specializations, designations, \
   and education.
5. If the user wants to email someone, draft a polished, professional email referencing \
   their actual role.
6. Use clean markdown. Keep initial responses concise and interactive.
7. Be encouraging, professional, and clear.
"""


# ==============================================================================
# Gemini API Client
# ==============================================================================
def call_gemini_api(
    api_key: str,
    system_instruction: str,
    history: Optional[List[ChatMessage]] = None,
) -> str:
    """
    Call the Gemini 2.5 Flash API with the provided system instruction and
    full conversation history. Enforces strict user→model role alternation
    required by the Gemini API.
    """
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )
    headers = {"Content-Type": "application/json"}

    contents = []
    if history:
        cleaned: list = []
        for msg in history:
            if not msg.text or not msg.text.strip():
                continue
            role = "user" if msg.sender == "user" else "model"
            if cleaned and cleaned[-1]["role"] == role:
                # Merge consecutive same-role messages to avoid Gemini 400 errors
                cleaned[-1]["parts"][0]["text"] += "\n" + msg.text
            else:
                cleaned.append({"role": role, "parts": [{"text": msg.text}]})
        contents = cleaned

    if not contents:
        contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

    payload = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2048,
        },
    }

    response = requests.post(url, headers=headers, json=payload, timeout=(1.5, 2.5))
    response.raise_for_status()
    res_json = response.json()

    candidates = res_json.get("candidates", [])
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        if parts:
            return parts[0].get("text", "")

    return "Sorry, I could not parse a valid response from the AI model."
