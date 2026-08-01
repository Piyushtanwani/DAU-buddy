import time
import json
import requests
import asyncio
from typing import List, Optional, Tuple, Dict, Any

from core import config
from core.schemas import ChatMessage
from api.services.library_service import LibraryService
from api.services import calendar_service, timetable_service
from api.services.scholar_service import search_scholars as _search_scholars_db, get_scholar_by_id
from api.services.document_service import DocumentService
from api.services import tool_bridge

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
You are DAU Buddy, the official AI assistant for Dhirubhai Ambani Institute of \
Information and Communication Technology (DA-IICT). You help students, faculty, \
researchers, and visitors with everything about the university — people, schedules, \
holidays, library books, academic rules, PhD scholars, and more.

**CURRENT CONTEXT**
Today's Day of the Week: {current_day}

You answer by calling TOOLS — you have no built-in directory. Available tools:
- **Directory**: `search_faculty`, `get_faculty_details`, `search_faculty_by_expertise`, `list_faculty`, `search_staff`, `get_staff_details`, `list_staff` — ALWAYS use these for any question about a person; never answer people questions from memory.
- **Library**: `search_library_books`, `get_book_details` — search the OPAC catalog
- **Calendar**: `get_next_holiday`, `get_upcoming_holidays`, `get_midsem_dates`, `get_endsem_dates`, `search_calendar` — holidays and academic events
- **Timetable**: `get_faculty_schedule`, `get_faculty_location`, `find_faculty_free_time`, `find_common_free_time`, `get_course_schedule`, `get_program_timetable`, `get_room_schedule`, `check_room_availability`, `find_free_rooms`, `list_programs`, `list_rooms` — class schedules, free-slot lookup, room checks. For "when is professor X free" or meeting scheduling, ALWAYS use `find_faculty_free_time` / `find_common_free_time` and relay their free windows verbatim — never derive free time from a schedule yourself.
- **Scholars**: `search_scholars`, `get_scholar_details` — PhD/doctoral scholar lookup (professors are faculty, NOT scholars)
- **Academic Docs**: `search_academic_requirements` — rules, regulations, CPI requirements, graduation criteria
- **About**: `get_creators_info` — creators, developers, and team info

Guidelines:
1. Ground your answers on tool results. NEVER fabricate names, dates, or details.
2. For faculty/staff name lookups, give a brief intro first. Only show email/phone/office if the user asks for "details" or "contact".
3. For casual greetings or chit-chat, respond naturally and warmly.
4. When suggesting people, explain *why* they match based on their specialization/designation.
5. Use clean markdown with bullet points for structured data.
6. For library queries, ALWAYS use `search_library_books` then `get_book_details` to check availability.
7. For holiday/exam date questions, use the calendar tools.
8. For timetable/schedule questions (who is teaching where/when), use the timetable tools.
9. For academic rules, curriculum, or list of courses for a semester/program (e.g. 'all courses for sem 2 in mscit'), use `search_academic_requirements` with 2-4 keywords.
10. For PhD scholar queries, use `search_scholars`.
11. WiFi/Internet/Network issues → suggest IT & Systems staff. Light/AC/Fan issues → suggest Electrical staff.
12. If the user asks who made/created DAU Buddy or about Piyush, Afif, or Ankush, you MUST use `get_creators_info` and output its EXACT response without summarizing.
13. Keep responses concise and invite follow-up questions.
14. Timetable Rule: The database uses strict names like "MSc (IT)", "B Tech (CS)". If a user asks for a program schedule (e.g. "msc it"), you MUST call `list_programs` first to find the exact matching name, then pass that exact name to `get_program_timetable`. Also, use the `current_day` provided above when the user asks for "today's" schedule. You MUST ALWAYS include the exact start and end times for each class/session in your final response.
"""




# ==============================================================================
# Gemini Tools
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

def _serialize_dates(obj):
    """Convert date/time objects to strings for JSON serialization."""
    if obj is None:
        return obj
    if isinstance(obj, dict):
        return {k: _serialize_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_dates(item) for item in obj]
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    if hasattr(obj, 'strftime'):
        return str(obj)
    return obj

# ── Library Tools ─────────────────────────────────────────────────────────────
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
        return {
            "title": details.get("title"),
            "author": details.get("author"),
            "total_copies": details.get("total_copies"),
            "available_copies": details.get("available_copies"),
        }
    except Exception as e:
        return {"error": str(e)}

# ── Calendar Tools ────────────────────────────────────────────────────────────
def get_next_holiday() -> dict:
    """Returns the next upcoming holiday at DA-IICT. Use when the user asks about the next holiday or day off."""
    try:
        result = calendar_service.get_next_holiday()
        return _serialize_dates(result) if result else {"message": "No upcoming holidays found."}
    except Exception as e:
        return {"error": str(e)}

def get_upcoming_holidays(limit: int = 5) -> list[dict]:
    """Returns a list of upcoming DA-IICT holidays. Use when the user asks about upcoming holidays or the holiday list."""
    try:
        results = calendar_service.get_upcoming_holidays(limit)
        return _serialize_dates(results)
    except Exception as e:
        return [{"error": str(e)}]

def get_midsem_dates() -> list[dict]:
    """Returns mid-semester exam dates and related academic events. Use when the user asks about midsem exams."""
    try:
        results = calendar_service.get_midsem_dates()
        return _serialize_dates(results)
    except Exception as e:
        return [{"error": str(e)}]

def get_endsem_dates() -> list[dict]:
    """Returns end-semester exam dates and related academic events. Use when the user asks about endsem or final exams."""
    try:
        results = calendar_service.get_endsem_dates()
        return _serialize_dates(results)
    except Exception as e:
        return [{"error": str(e)}]

def search_calendar(query: str) -> dict:
    """Search the academic calendar and holiday calendar by keyword. Use when the user asks about specific events, registration, convocation, etc."""
    try:
        results = calendar_service.search_calendar(query)
        return _serialize_dates(results)
    except Exception as e:
        return {"error": str(e)}

# ── Timetable Tools ───────────────────────────────────────────────────────────
def get_faculty_schedule(faculty_name: str, day: str = None) -> list[dict]:
    """Returns the class schedule for a faculty member. Optionally filter by day of week. Use when the user asks about a professor's timetable or classes."""
    try:
        results = timetable_service.get_faculty_schedule(faculty_name, day)
        return _serialize_dates(results)
    except Exception as e:
        return [{"error": str(e)}]

def get_faculty_location(faculty_name: str, day: str, time: str) -> dict:
    """Finds what class a faculty is teaching and in which room at a specific day and time. Use when the user asks 'where is professor X right now'."""
    try:
        result = timetable_service.get_faculty_location(faculty_name, day, time)
        return _serialize_dates(result) if result else {"message": f"{faculty_name} has no class at {time} on {day}."}
    except Exception as e:
        return {"error": str(e)}

def _free_time_result(data: dict, note: str) -> dict:
    """Convert a service free-time dict into a chat-tool result."""
    if "candidates" in data:
        cands = data["candidates"]
        if not cands:
            return {"error": f"No faculty matching '{data['query']}' in timetable."}
        return {"error": f"Ambiguous name '{data['query']}'. Matches: {', '.join(cands)}. Ask the user to specify."}
    data["note"] = note
    return data

def get_faculty_free_time(faculty_name: str, day: str) -> dict:
    """Returns the pre-computed FREE meeting windows for a faculty on a given day. Use when the user asks when a professor is free or wants to schedule a meeting. Relay free_slots as-is; do NOT recompute from busy_slots."""
    try:
        return _free_time_result(
            timetable_service.get_free_time(faculty_name, day),
            "free_slots = when the faculty CAN meet (timetable only; other commitments not tracked).",
        )
    except Exception as e:
        return {"error": str(e)}

def find_common_free_time(faculty_names: list[str], day: str) -> dict:
    """Returns the pre-computed common FREE meeting windows when ALL listed faculty can meet on a given day. Use for multi-person meeting scheduling. Relay free_slots as-is."""
    try:
        return _free_time_result(
            timetable_service.get_common_free_time(faculty_names, day),
            "free_slots = when ALL listed faculty can meet (timetable only).",
        )
    except Exception as e:
        return {"error": str(e)}

def get_course_schedule(course_code: str, day: str = None) -> list[dict]:
    """Returns the schedule for a specific course (by code or name). Use when the user asks about a course timetable."""
    try:
        results = timetable_service.get_course_schedule(course_code, day)
        return _serialize_dates(results)
    except Exception as e:
        return [{"error": str(e)}]

def get_program_timetable(program_name: str, day: str = None, semester: str = None) -> list[dict]:
    """Returns the daily class schedule with timings for a program/batch (e.g. 'BTech', 'MSc IT'). Use when the user asks about daily timetables. DO NOT use this tool when the user asks for the curriculum or a list of all courses in a semester (use search_academic_requirements instead)."""
    try:
        results = timetable_service.get_program_timetable(program_name, day, semester)
        return _serialize_dates(results)
    except Exception as e:
        return [{"error": str(e)}]

def check_room_availability(room: str, day: str, time: str) -> dict:
    """Checks if a classroom or lab is available at a given day and time. Use when the user asks if a room is free."""
    try:
        result = timetable_service.get_room_availability(room, day, time)
        if result:
            return _serialize_dates({"available": False, **result})
        return {"available": True, "message": f"{room} is available at {time} on {day}."}
    except Exception as e:
        return {"error": str(e)}

def list_programs() -> list[str]:
    """Returns a list of all program/batch names available in the timetable database. Use this to discover valid program names before calling get_program_timetable."""
    try:
        return timetable_service.list_programs()
    except Exception as e:
        return [f"Error: {str(e)}"]

# ── Scholar Tools ─────────────────────────────────────────────────────────────
def get_creators_info() -> dict:
    """Returns information about the creators and developers of the DAU Buddy platform. Use this tool whenever someone asks who made DAU Buddy or asks about Piyush, Afif, or Ankush in the context of creating this project."""
    return {
        "text": (
            "DAU Buddy was created by a dedicated team:\n\n"
            "1. Piyush Tanwani (AI/ML Engineer)\n"
            "   - Role: Project Lead, AI/ML Infrastructure, MCP Server Logic\n"
            "   - Education: M.Sc. IT Student, DAU (Dhirubhai Ambani University)\n"
            "   - LinkedIn: https://www.linkedin.com/in/piyushtanwani/\n"
            "   - GitHub: https://github.com/Piyushtanwani/\n\n"
            "2. Afif Momin (Cybersecurity Analyst)\n"
            "   - Role: Security Analysis, Infrastructure Hardening\n"
            "   - Education: M.Sc. IT Student, DAU (Dhirubhai Ambani University)\n"
            "   - LinkedIn: https://www.linkedin.com/in/afif-momin/\n"
            "   - GitHub: https://github.com/Afif-Momin\n\n"
            "3. Prof. Ankush Chander (Faculty Mentor & Project Guide)\n"
            "   - Designation: Adjunct Faculty, DA-IICT\n"
            "   - Specialization: Natural Language Processing, Information Retrieval, Operating Systems\n"
            "   - Profile: https://www.daiict.ac.in/adjunct-faculty/ankush-chander\n"
            "   - Email: ankush_chander@dau.ac.in\n"
            "   - LinkedIn: https://www.linkedin.com/in/ankush-chander/\n"
            "   - GitHub: https://github.com/Ankush-Chander\n\n"
            "Mission: We built DAU Buddy as passionate DAU (Dhirubhai Ambani University) students to make accessing university data and resources seamless for everyone through AI!"
        )
    }

def search_scholars(query: str, limit: int = 5) -> list[dict]:
    """Search DA-IICT PhD/doctoral scholars by name, research topic, or advisor. Use when the user asks about PhD students or researchers."""
    try:
        return _search_scholars_db(query, limit)
    except Exception as e:
        return [{"error": str(e)}]

def get_scholar_details(scholar_id: str) -> dict:
    """Get full profile of a PhD scholar. Pass the numeric `id` from search_scholars results (preferred) or the scholar's name. Includes thesis topic, publications, awards, and employment. Note: faculty members are NOT scholars — use faculty tools for professors."""
    try:
        result = get_scholar_by_id(scholar_id)
        return result if result else {"message": f"No PhD scholar found for '{scholar_id}'. Use search_scholars first, or faculty tools if this is a professor."}
    except Exception as e:
        return {"error": str(e)}

# ── Academic Document Tools ───────────────────────────────────────────────────
def search_academic_requirements(query: str, program: str = None) -> str:
    """Search academic requirement documents for rules, regulations, CPI requirements, graduation criteria, etc. IMPORTANT: Pass 2-4 keywords only. If searching for a semester curriculum, use roman numerals for the semester (e.g., 'Semester-II' instead of 'Semester 2'). DO NOT include the program name inside the `query` string (put it ONLY in the `program` argument). If passing a program name, you MUST use official spacing (e.g. 'MSc IT' instead of 'mscit')."""
    try:
        query_lower = query.lower()
        
        # Auto-extract program if AI fails to separate it
        if not program:
            if "msc it" in query_lower or "mscit" in query_lower:
                program = "MSc IT"
            elif "btech" in query_lower:
                if "mnc" in query_lower: program = "BTech MnC"
                elif "cs" in query_lower: program = "BTech ICT CS"
                else: program = "BTech ICT"
                
        # Auto-correct semester numbers to roman numerals
        if "sem 2" in query_lower or "semester 2" in query_lower or "2nd sem" in query_lower:
            query = "Semester-II curriculum"
        elif "sem 1" in query_lower or "semester 1" in query_lower or "1st sem" in query_lower:
            query = "Semester-I curriculum"
        elif "sem 3" in query_lower or "semester 3" in query_lower or "3rd sem" in query_lower:
            query = "Semester-III curriculum"
        elif "sem 4" in query_lower or "semester 4" in query_lower or "4th sem" in query_lower:
            query = "Semester-IV curriculum"
            
        with open('debug_log.txt', 'a') as f:
            f.write(f"DEBUG TOOL CALL: search_academic_requirements(query='{query}', program='{program}')\n")
        if program:
            program = program.replace('(', '').replace(')', '')
        results = DocumentService.search_documents("academic_requirements", query, program, limit=5)
        if not results:
            return "No documents found matching the query."
        
        formatted = []
        for r in results:
            formatted.append(f"Title: {r.get('document_title')} (Program: {r.get('program')}, Year: {r.get('effective_year')})\nContent:\n{r.get('content')}\n---")
        
        return "\n".join(formatted)
    except Exception as e:
        return f"Error: {str(e)}"


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
    
    # Tool surface derived from the unified MCP server (single source of truth).
    all_tools = tool_bridge.gemini_tool_config()
    
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=system_instruction,
        tools=all_tools,
        generation_config={"temperature": 0.3, "max_output_tokens": 1200}
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
            
            tool_result = tool_bridge.dispatch(function_name, args)
                
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
