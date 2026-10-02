import re

def normalize_venue_id(room: str) -> str:
    """Normalize venue string to a standard form (e.g. CEP-102, LAB004)."""
    r = re.sub(r"\s+", " ", room.strip())
    # Canonical forms differ by building: CEP/LT are hyphenated (CEP-102, LT-2),
    # LAB is not (LAB004).
    m = re.match(r"^(CEP|LT)\s*-?\s*(\d+[A-Z]?)$", r, re.IGNORECASE)
    if m:
        num = m.group(2).upper()
        # strip leading zeros, e.g. "03" -> "3"
        num_stripped = num.lstrip("0")
        if not num_stripped:
            num_stripped = "0"
        return f"{m.group(1).upper()}-{num_stripped}"
    
    m = re.match(r"^LAB\s*-?\s*(\d+[A-Z]?)$", r, re.IGNORECASE)
    if m:
        num = m.group(1).upper()
        # Note: Do not strip leading zeros for labs since they might use them distinctively (e.g., LAB001)
        return f"LAB{num}"
    return r
