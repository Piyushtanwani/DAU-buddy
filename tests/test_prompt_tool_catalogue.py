"""
The prompt's tool catalogue must not advertise tools the model cannot call.

`tool_bridge.list_tools()` derives the model's function declarations solely from
the unified MCP server's registry, so a tool that is defined but never
`add_tool`'d is unreachable — while the catalogue in SYSTEM_INSTRUCTIONS_TEMPLATE
happily keeps naming it. That is how `check_room_availability` came to be
advertised for months without existing: two surfaces, no test tying them.

Only one direction is asserted. Advertising a tool that does not exist makes the
model attempt an impossible call; a registered tool missing from the catalogue is
merely less discoverable, since its full declaration reaches the model anyway.
"""
import re

import pytest

from api.services import gemini, tool_bridge


def _advertised_tool_names() -> set[str]:
    """Backticked names from the '- **Category**: ...' bullets of the catalogue."""
    tpl = gemini.SYSTEM_INSTRUCTIONS_TEMPLATE
    block = tpl[tpl.index("You answer by calling TOOLS"):tpl.index("**ROUTING")]
    return {
        name
        for line in block.splitlines() if line.startswith("- **")
        for name in re.findall(r"`(\w+)`", line)
    }


def test_the_catalogue_is_actually_being_parsed():
    """Guard against a vacuous pass: a renamed section would match nothing."""
    assert len(_advertised_tool_names()) > 20


def test_every_advertised_tool_is_callable():
    unreachable = _advertised_tool_names() - {t["name"] for t in tool_bridge.list_tools()}

    assert not unreachable, (
        f"Prompt advertises tools the model cannot call: {sorted(unreachable)}. "
        "Register them in dau_mcp/unified_mcp_server.py or drop them from the "
        "catalogue in SYSTEM_INSTRUCTIONS_TEMPLATE."
    )
