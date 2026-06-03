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
2. CRITICAL RULE: If the user just types a name (e.g. "Minal Bhise") or asks a basic query, you MUST ONLY reply using exactly this template:
"[Full Name] works at DA-IICT as [Designation] (holding credentials in [Education]).

Their primary role involves [describe their role briefly based on their designation/specialization].

*(If you need their contact info or full details, just ask for \"details of [First Name]\"!)*"
3. DO NOT list their email, phone, office, or any extra text unless the user explicitly typed the word "details", "contact", or asked for it.
4. For general queries adopt a friendly, conversational approach — name relevant people and briefly explain why they match, then invite a follow-up.
5. When suggesting professors/staff, explain *why* based on specializations, designations, and education.
6. If the user wants to email someone, draft a polished, professional email referencing their actual role.
7. Use clean markdown. Keep initial responses concise and interactive.
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
    Call the OpenRouter API with the provided system instruction and
    full conversation history, utilizing model routing (Gemini + Llama 3 fallback).
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "DA-IICT AI Buddy",
        "Content-Type": "application/json"
    }

    messages = [{"role": "system", "content": system_instruction}]
    
    if history:
        for msg in history:
            if not msg.text or not msg.text.strip():
                continue
            role = "user" if msg.sender == "user" else "assistant"
            messages.append({"role": role, "content": msg.text})

    if len(messages) == 1:
        messages.append({"role": "user", "content": "Hello"})

    payload = {
        "models": ["google/gemini-2.5-flash", "meta-llama/llama-3-8b-instruct"],
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 800,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=(5.0, 120.0))
    response.raise_for_status()
    res_json = response.json()

    choices = res_json.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")

    return "Sorry, I could not parse a valid response from the AI model."
