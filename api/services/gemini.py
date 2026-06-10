import time
import requests
import asyncio
from typing import List, Optional, Tuple, Dict, Any

from core import config
from core.schemas import ChatMessage
from api.services.library_service import LibraryService

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
10. Library Rule: If the user asks about books, use the library search tools. When you receive the book results, you MUST use the `get_book_details` tool to check their availability. Then, present the results using exactly this format for each book:
- **[Book Title]**
  - Author: [Author]
  - Availability: [Available Copies / Total Copies]
  - Link: [OPAC Link]
"""




# ==============================================================================
# Gemini Tools (Library)
# ==============================================================================
_library_svc = LibraryService()

def _run_async_in_thread(coro):
    import threading
    result = None
    exception = None
    def worker():
        nonlocal result, exception
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(coro)
            loop.close()
        except Exception as e:
            exception = e
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    if exception:
        raise exception
    return result

def search_library_books(query: str, limit: int = 3) -> list[dict]:
    """Search the DA-IICT Resource Centre (Koha OPAC) catalog. Use this tool when the user asks to find a book."""
    try:
        return _run_async_in_thread(_library_svc.search_books(query=query, limit=limit))
    except Exception as e:
        return [{"error": str(e)}]

def get_book_details(biblionumber: str) -> dict:
    """Fetch the full catalog record and real-time copy availability for a book. Use this tool to check if a book is available, using the biblionumber from the search results."""
    try:
        details = _run_async_in_thread(_library_svc.get_book_details(biblionumber=biblionumber))
        # Return only essential info to save tokens
        return {
            "title": details.get("title"),
            "author": details.get("author"),
            "total_copies": details.get("total_copies"),
            "available_copies": details.get("available_copies"),
        }
    except Exception as e:
        return {"error": str(e)}


# ==============================================================================
# Gemini API Client
# ==============================================================================
def call_gemini_api(
    api_key: str,
    system_instruction: str,
    history: Optional[List[ChatMessage]] = None,
) -> Tuple[str, Dict[str, int]]:
    """
    Call the native Google Gemini API using google-generativeai, with tool support.
    Returns a tuple of (response_text, usage_metadata_dict).
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
        tools=[search_library_books, get_book_details],
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
        
        # Tool calling loop
        while True:
            fc = None
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    # In google-generativeai, the function_call field on a Part is populated if it's a tool call
                    if type(part).to_dict(part).get("function_call") or getattr(part, "function_call", None):
                        fc = getattr(part, "function_call", None)
                        if fc and not getattr(fc, "name", None): # Sometimes it's empty
                            fc = None
                        if fc:
                            break
                            
            if not fc and getattr(response, "function_call", None):
                fc = response.function_call
                
            if not fc:
                break
                
            function_name = fc.name
            # convert protobuf map to dict safely
            args = {}
            if hasattr(fc, "args"):
                for k, v in fc.args.items():
                    args[k] = v
            
            logger.info(f"Gemini requested tool call: {function_name}({args})")
            
            tool_result = None
            if function_name == "search_library_books":
                tool_result = search_library_books(**args)
            elif function_name == "get_book_details":
                tool_result = get_book_details(**args)
            else:
                tool_result = {"error": f"Unknown tool: {function_name}"}
                
            logger.info(f"Returning tool result to Gemini...")
            response = chat.send_message(
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=function_name,
                        response={"result": tool_result}
                    )
                )
            )

        usage = response.usage_metadata
        usage_dict = {
            "prompt_token_count": usage.prompt_token_count,
            "candidates_token_count": usage.candidates_token_count,
            "total_token_count": usage.total_token_count
        } if usage else {}

        try:
            out_text = response.text
        except ValueError:
            out_text = "I checked the system, but there is no additional information to provide right now."
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                try:
                    out_text = response.candidates[0].content.parts[0].text
                except Exception:
                    pass

        return out_text, usage_dict
    except Exception as e:
        logger.error(f"Native Gemini API Error: {e}")
        raise e
