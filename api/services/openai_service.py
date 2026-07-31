import time
import json
import requests
import asyncio
from typing import List, Tuple, Dict, Any

from core import config
from core.schemas import ChatMessage

# Import the existing tool wrappers from gemini.py to avoid code duplication
from api.services.gemini import (
    search_library_books, get_book_details, get_next_holiday, get_upcoming_holidays,
    get_midsem_dates, get_endsem_dates, search_calendar, get_faculty_schedule,
    get_faculty_location, get_faculty_free_time, find_common_free_time, get_course_schedule,
    get_program_timetable, check_room_availability, list_programs,
    search_scholars, get_scholar_details, search_academic_requirements,
    get_creators_info
)

logger = config.get_logger("api.services.openai")

# ==============================================================================
# OpenAI API Availability Circuit Breaker
# ==============================================================================
_openai_healthy: bool = True
_openai_last_check: float = 0.0
_OPENAI_COOLDOWN: float = 60.0

def is_openai_available() -> bool:
    global _openai_healthy, _openai_last_check
    if not _openai_healthy:
        if time.time() - _openai_last_check < _OPENAI_COOLDOWN:
            return False
        _openai_healthy = True
    return True

def record_openai_failure() -> None:
    global _openai_healthy, _openai_last_check
    logger.warning("OpenAI connection failed. Activating 60s bypass cooldown.")
    _openai_healthy = False
    _openai_last_check = time.time()


# ==============================================================================
# OpenAI Tool JSON Schemas
# ==============================================================================
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_library_books",
            "description": "Search the DA-IICT Resource Centre catalog. Use this tool when the user asks to find a book.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 3}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_book_details",
            "description": "Fetch the full catalog record and real-time copy availability for a book. Use this tool to check if a book is available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "biblionumber": {"type": "string"}
                },
                "required": ["biblionumber"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_next_holiday",
            "description": "Returns the next upcoming holiday at DA-IICT.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_upcoming_holidays",
            "description": "Returns a list of upcoming DA-IICT holidays.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 5}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_midsem_dates",
            "description": "Returns mid-semester exam dates and related academic events.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_endsem_dates",
            "description": "Returns end-semester exam dates and related academic events.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_calendar",
            "description": "Search the academic calendar and holiday calendar by keyword (e.g., registration, convocation).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_faculty_schedule",
            "description": "Returns the class schedule for a faculty member.",
            "parameters": {
                "type": "object",
                "properties": {
                    "faculty_name": {"type": "string"},
                    "day": {"type": "string"}
                },
                "required": ["faculty_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_faculty_location",
            "description": "Finds what class a faculty is teaching and in which room at a specific day and time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "faculty_name": {"type": "string"},
                    "day": {"type": "string"},
                    "time": {"type": "string"}
                },
                "required": ["faculty_name", "day", "time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_faculty_free_time",
            "description": "Returns pre-computed FREE meeting windows (free_slots) for a faculty on a given day. Use when the user asks when a professor is free. Relay free_slots as-is; do NOT recompute.",
            "parameters": {
                "type": "object",
                "properties": {
                    "faculty_name": {"type": "string"},
                    "day": {"type": "string"}
                },
                "required": ["faculty_name", "day"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_common_free_time",
            "description": "Returns pre-computed common FREE meeting windows when ALL listed faculty can meet on a given day. Use for multi-person meeting scheduling. Relay free_slots as-is.",
            "parameters": {
                "type": "object",
                "properties": {
                    "faculty_names": {"type": "array", "items": {"type": "string"}},
                    "day": {"type": "string"}
                },
                "required": ["faculty_names", "day"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_course_schedule",
            "description": "Returns the schedule for a specific course.",
            "parameters": {
                "type": "object",
                "properties": {
                    "course_code": {"type": "string"},
                    "day": {"type": "string"}
                },
                "required": ["course_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_program_timetable",
            "description": "Returns the full timetable for a program/batch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "program_name": {"type": "string"},
                    "day": {"type": "string"},
                    "semester": {"type": "string"}
                },
                "required": ["program_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_room_availability",
            "description": "Checks if a classroom or lab is available at a given day and time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {"type": "string"},
                    "day": {"type": "string"},
                    "time": {"type": "string"}
                },
                "required": ["room", "day", "time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_programs",
            "description": "Returns a list of all program/batch names available in the timetable database.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_scholars",
            "description": "Search the PhD/doctoral scholars directory by name, supervisor, or topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_scholar_details",
            "description": "Retrieves the full profile of a PhD scholar. Pass the numeric `id` from search_scholars results (preferred) or the scholar's name. Faculty members are NOT scholars — use faculty tools for professors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scholar_id": {"type": "string"}
                },
                "required": ["scholar_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_academic_requirements",
            "description": "Search academic requirement documents for rules, regulations, CPI requirements, graduation criteria, etc. IMPORTANT: Pass 2-4 keywords only, NOT full sentences.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "2-4 keywords (e.g. 'minimum CPI graduation')"},
                    "program": {"type": "string", "description": "Optional program name (e.g. 'MSc IT')"}
                },
                "required": ["query"]
            }
        }
    }
]

TOOL_FUNCTIONS = {
    "search_library_books": search_library_books,
    "get_book_details": get_book_details,
    "get_next_holiday": get_next_holiday,
    "get_upcoming_holidays": get_upcoming_holidays,
    "get_midsem_dates": get_midsem_dates,
    "get_endsem_dates": get_endsem_dates,
    "search_calendar": search_calendar,
    "get_faculty_schedule": get_faculty_schedule,
    "get_faculty_location": get_faculty_location,
    "get_faculty_free_time": get_faculty_free_time,
    "find_common_free_time": find_common_free_time,
    "get_course_schedule": get_course_schedule,
    "get_program_timetable": get_program_timetable,
    "check_room_availability": check_room_availability,
    "list_programs": list_programs,
    "search_scholars": search_scholars,
    "get_scholar_details": get_scholar_details,
    "search_academic_requirements": search_academic_requirements,
}

# ==============================================================================
# OpenAI Chat Execution
# ==============================================================================
def call_openai_api(api_key: str, system_instruction: str, history: List[ChatMessage]) -> Tuple[str, dict]:
    """
    Calls the OpenAI API with function-calling support.
    """
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
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
        "model": "gpt-4o-mini",
        "messages": messages,
        "tools": OPENAI_TOOLS,
        "tool_choice": "auto",
        "temperature": 0.3,
        "max_tokens": 1200
    }

    usage_dict = {"prompt_token_count": 0, "candidates_token_count": 0, "total_token_count": 0}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        
        usage = data.get("usage", {})
        usage_dict["prompt_token_count"] += usage.get("prompt_tokens", 0)
        usage_dict["candidates_token_count"] += usage.get("completion_tokens", 0)
        
        message = data["choices"][0]["message"]

        # Tool calling loop
        while message.get("tool_calls"):
            messages.append(message)
            
            for tool_call in message["tool_calls"]:
                function_name = tool_call["function"]["name"]
                tool_call_id = tool_call["id"]
                try:
                    args = json.loads(tool_call["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                logger.info(f"OpenAI requested tool call: {function_name}({args})")
                
                tool_fn = TOOL_FUNCTIONS.get(function_name)
                if tool_fn:
                    tool_result = tool_fn(**args)
                else:
                    tool_result = {"error": f"Unknown tool: {function_name}"}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": function_name,
                    "content": json.dumps(tool_result, default=str)
                })

            payload["messages"] = messages
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            
            usage = data.get("usage", {})
            usage_dict["prompt_token_count"] += usage.get("prompt_tokens", 0)
            usage_dict["candidates_token_count"] += usage.get("completion_tokens", 0)
            
            message = data["choices"][0]["message"]

        usage_dict["total_token_count"] = usage_dict["prompt_token_count"] + usage_dict["candidates_token_count"]
        out_text = message.get("content") or "I checked the system, but there is no additional information to provide right now."
        return out_text, usage_dict
        
    except requests.exceptions.RequestException as e:
        logger.error(f"OpenAI API Request Error: {e}")
        if response := getattr(e, 'response', None):
            logger.error(f"Response Body: {response.text}")
        raise e
    except Exception as e:
        logger.error(f"OpenAI Integration Error: {e}")
        raise e
