"""
Tool bridge: single source of truth for chat-backend tool surfaces.

Derives OpenAI function declarations, Gemini tool declarations, and a dispatch
entrypoint directly from the unified FastMCP server's tool registry. Web chat
(Gemini/OpenAI) therefore always exposes exactly what the MCP server exposes —
no hand-maintained declaration lists, no drift between the two surfaces.

Role awareness: directory tools return full contact info; for non-privileged
roles (students) the dispatch result is redacted (phone numbers and office
addresses stripped), matching the old prompt-injection behaviour.
"""
import re
import copy
import asyncio
import threading
from typing import Any, Dict, List

from core import config
from api.context import user_role_var

logger = config.get_logger("api.services.tool_bridge")

# Mutating/administrative tools stay MCP-only; web chat must not expose them.
EXCLUDED_TOOLS = {
    "sync_faculty_data",
    "sync_staff_data",
    "sync_scholar_data",
    "sync_academic_documents",
}

# Tools whose output contains personal contact details subject to role redaction.
DIRECTORY_TOOLS = {
    "list_faculty", "search_faculty", "get_faculty_details", "search_faculty_by_expertise",
    "list_staff", "search_staff", "get_staff_details",
}

PRIVILEGED_ROLES = ("Faculty", "Staff", "Admin")

_PHONE_RE = re.compile(r"(\+?\d[\d\s-]{7,}\d)")
_OFFICE_RE = re.compile(r"#\s?\d{3,4}(?:,\s?FB-\d[^,|\n]*)?")

# The placeholder the model sees in place of a redacted value. It is
# self-explaining on purpose: a bare "[restricted]" left the model guessing why
# the field was missing, so it invented privacy rationales and could be argued
# out of them. The system prompt keys off this exact wording.
REDACTED = "[withheld: visible to faculty and staff only]"


def _mcp():
    # Imported lazily so importing the bridge never boots the MCP server at module load.
    from dau_mcp.unified_mcp_server import mcp
    return mcp


def _sanitize_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Strip pydantic artifacts (title/$schema) and flatten Optional anyOf so the
    schema is accepted by both OpenAI and Gemini."""
    def clean(node):
        if isinstance(node, dict):
            node = {k: clean(v) for k, v in node.items()
                    if k not in ("title", "$schema", "default", "additionalProperties")}
            if "anyOf" in node:
                non_null = [s for s in node["anyOf"] if s.get("type") != "null"]
                if non_null:
                    merged = non_null[0]
                    node = {**{k: v for k, v in node.items() if k != "anyOf"}, **merged}
            return node
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node

    return clean(copy.deepcopy(schema))


def list_tools() -> List[Dict[str, Any]]:
    """[{name, description, parameters}] for every chat-exposed tool."""
    out = []
    for t in _mcp()._tool_manager.list_tools():
        if t.name in EXCLUDED_TOOLS:
            continue
        out.append({
            "name": t.name,
            "description": " ".join((t.description or t.name).split()),
            "parameters": _sanitize_schema(t.parameters),
        })
    return out


def openai_declarations() -> List[Dict[str, Any]]:
    return [{"type": "function", "function": t} for t in list_tools()]


def gemini_tool_config() -> List[Dict[str, Any]]:
    """google-generativeai accepts dict-form tools: [{function_declarations: [...]}]."""
    return [{"function_declarations": list_tools()}]


def _redact(text: str) -> str:
    text = _PHONE_RE.sub(REDACTED, text)
    return _OFFICE_RE.sub(REDACTED, text)


def _run_async(coro):
    """Run a coroutine to completion from sync code, safe inside a running loop."""
    result, exc = [None], [None]

    def worker():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result[0] = loop.run_until_complete(coro)
            loop.close()
        except Exception as e:
            exc[0] = e

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    if exc[0]:
        raise exc[0]
    return result[0]


def dispatch(name: str, arguments: Dict[str, Any]) -> str:
    """Execute a tool by name and return its text result (sync).

    All chat backends funnel through here, so redaction and logging are
    applied uniformly.
    """
    if name in EXCLUDED_TOOLS:
        return f"Tool '{name}' is not available in chat."
    
    logger.info(f"Bridge dispatch: {name}({arguments})")
    try:
        result = _run_async(_mcp()._tool_manager.call_tool(name, arguments or {}))
    except Exception as e:
        logger.error(f"Bridge dispatch failed for {name}: {e}")
        return f"Tool '{name}' failed: check the arguments and try again."
    text = result if isinstance(result, str) else str(result)
    if name in DIRECTORY_TOOLS and user_role_var.get() not in PRIVILEGED_ROLES:
        text = _redact(text)
    return text
