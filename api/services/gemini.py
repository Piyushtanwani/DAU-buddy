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
search assistant for Dhirubhai Ambani Institute of Information and Communication Technology (DA-IICT).\
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
1. Ground your answers strictly on the databases provided above. If you cannot find a relevant person or the answer in the databases, you MUST clearly state that you cannot find the information. DO NOT make up, guess, or hallucinate names, roles, or contact details under any circumstances.
2. CRITICAL RULE: If the user just types a name (e.g. "Minal Bhise") or asks a basic query, you MUST ONLY reply using exactly this template:
"[Full Name] works at DA-IICT as [Designation] (holding credentials in [Education]).

Their primary role involves [describe their role briefly based on their designation/specialization].

*(If you need their contact info or full details, just ask for \"details of [First Name]\"!)*"
3. DO NOT list their email, phone, office, or any extra text unless the user explicitly typed the word "details", "contact", or asked for it.
4. For general queries adopt a friendly, conversational approach — name relevant people and briefly explain why they match, then invite a follow-up.
5. When suggesting professors/staff, explain *why* based on specializations, designations, and education.
6. If the user wants to email someone, draft a polished, professional email referencing their actual role.
7. Use clean markdown. Keep initial responses concise and interactive.
8. Whenever you are asked to provide details or list out information about a faculty or staff member (like their email, phone, office, specialization, etc.), you MUST format the response using clear, markdown bullet points. Do not present details in a dense paragraph.
9. Domain Mapping Rule: If a user asks about "WiFi", "Internet", or "Network" problems, you must look for and suggest staff members whose designation involves "IT & SYSTEMS".
10. Library Rule: If the user asks about books, the library, or the Resource Centre, let them know that the system has a live library search. You do NOT have book data in your context — the library search is handled separately by querying the Koha OPAC in real time. Simply say: "I can search the DA-IICT Resource Centre for you — please ask me something like *'find a book on machine learning'* and I'll look it up live."
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
    Call the native Google Gemini API using google-generativeai.
    """
    import os
    import google.generativeai as genai

    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        raise ValueError("GEMINI_API_KEY is missing. Cannot use native Gemini API.")
    
    genai.configure(api_key=gemini_key)
    
    # Using 2.5 flash
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=system_instruction,
        generation_config={"temperature": 0.3, "max_output_tokens": 800}
    )
    
    # Format history
    formatted_history = []
    latest_msg = "Hello"
    
    if history:
        for i, msg in enumerate(history):
            if not msg.text or not msg.text.strip():
                continue
            
            # The last message from user must be sent via send_message
            if i == len(history) - 1 and msg.sender == "user":
                latest_msg = msg.text
                break
                
            role = "user" if msg.sender == "user" else "model"
            formatted_history.append({"role": role, "parts": [msg.text]})
    
    try:
        chat = model.start_chat(history=formatted_history)
        response = chat.send_message(latest_msg)
        return response.text
    except Exception as e:
        logger.error(f"Native Gemini API Error: {e}")
        raise e
