# api/services/ — Business logic layer split by domain
# Re-export key symbols for convenient imports
from api.services.gemini import (
    call_gemini_api,
    is_gemini_available,
    record_gemini_failure,
    SYSTEM_INSTRUCTIONS_TEMPLATE,
    build_system_instruction,
)
from api.services.faculty_service import (
    fetch_all_faculty_context,
    clear_faculty_cache,
)
from api.services.staff_service import (
    fetch_all_staff_context,
    clear_staff_cache,
)
from api.services.fallback import process_fallback_message


def clear_context_caches() -> None:
    """Clear both faculty and staff in-memory context caches."""
    clear_faculty_cache()
    clear_staff_cache()
