import os
import time
import json
import requests
import asyncio
from typing import List, Tuple, Dict, Any, Optional

from core import config
from core.schemas import ChatMessage

# Tool surface is derived from the unified MCP server via the bridge —
# declarations and dispatch are never hand-maintained here.
from api.services import tool_bridge

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
# Provider configuration (env-driven so a local vLLM server can be used)
# ==============================================================================
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_PROVIDER_ORDER = ("gemini", "openai")

_KNOWN_PROVIDERS = {"gemini", "openai"}

def get_llm_base_url() -> str:
    # `or` (not a getenv default) so a blank `LLM_BASE_URL=` also falls back.
    return (os.getenv("LLM_BASE_URL") or DEFAULT_LLM_BASE_URL).rstrip("/")

def get_llm_model() -> str:
    return os.getenv("LLM_MODEL") or DEFAULT_LLM_MODEL

def openai_configured() -> bool:
    """
    The OpenAI-compatible path is usable if there is an API key (real OpenAI)
    or a custom base URL (a local server needs no key).
    """
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("LLM_BASE_URL"))

def get_provider_order() -> List[str]:
    """
    Parse LLM_PROVIDER_ORDER, e.g. "openai,gemini" puts the OpenAI-compatible
    (local) model first. Unknown names are ignored; empty/invalid -> default.
    """
    raw = os.getenv("LLM_PROVIDER_ORDER") or ""
    order = []
    for name in raw.split(","):
        name = name.strip().lower()
        if name in _KNOWN_PROVIDERS and name not in order:
            order.append(name)
        elif name and name not in _KNOWN_PROVIDERS:
            logger.warning(f"Ignoring unknown provider '{name}' in LLM_PROVIDER_ORDER.")
    return order + [name for name in DEFAULT_PROVIDER_ORDER if name not in order]


# ==============================================================================
# OpenAI Tool JSON Schemas
# ==============================================================================
OPENAI_TOOLS = tool_bridge.openai_declarations()

# Hard ceiling on tool round-trips for a single user message.
MAX_TOOL_TURNS = 8

# ==============================================================================
# OpenAI Chat Execution
# ==============================================================================
def call_openai_api(api_key: Optional[str], system_instruction: str, history: List[ChatMessage]) -> Tuple[str, dict]:
    """
    Calls the OpenAI-compatible chat API (OpenAI itself or a local server such as vLLM) with function-calling support.
    """
    url = f"{get_llm_base_url()}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key: # a local server needs no key
        headers["Authorization"] = f"Bearer {api_key}"

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
        "model": get_llm_model(),
        "messages": messages,
        "tools": OPENAI_TOOLS,
        "tool_choice": "auto",
        "temperature": 0.3,
        "max_tokens": 4000
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

        # Tool calling loop — bounded, so a model that keeps re-requesting tools
        # cannot hold the request open indefinitely.
        turns = 0
        while message.get("tool_calls"):
            turns += 1
            if turns > MAX_TOOL_TURNS:
                logger.warning(f"OpenAI still requesting tools after {MAX_TOOL_TURNS} turns — stopping.")
                return (
                    "I wasn't able to pull all of that together. Could you ask about "
                    "one thing at a time — a specific person, course, or book?"
                ), usage_dict
            messages.append(message)
            
            for tool_call in message["tool_calls"]:
                function_name = tool_call["function"]["name"]
                tool_call_id = tool_call["id"]
                try:
                    args = json.loads(tool_call["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                logger.info(f"OpenAI requested tool call: {function_name}({args})")
                
                tool_result = tool_bridge.dispatch(function_name, args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": function_name,
                    "content": tool_result
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
