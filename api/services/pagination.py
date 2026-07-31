"""
Shared pagination envelope for list/search tool results.

Every paginated tool returns the same shape —
    {total_matches, showing, more_available, results}
— so LLM callers learn one protocol: advance `offset` for more; when
`more_available` is false the list is complete (never re-present a page as new).
"""
from typing import Any, Dict, List


def envelope(rows: List[Any], total: int, offset: int) -> Dict[str, Any]:
    shown_to = offset + len(rows)
    return {
        "total_matches": total,
        "showing": f"{offset + 1}-{shown_to}" if rows else "none",
        "more_available": shown_to < total,
        "results": rows,
    }
