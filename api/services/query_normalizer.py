"""
Shared normalization for academic document queries.

Single source of truth for program name canonicalization and semester number
expansion, called by both the MCP tool layer and the Gemini chat wrapper.
"""
import re
from typing import Optional, Tuple

ROMAN_MAP: dict[int, str] = {
    1: "I", 2: "II", 3: "III", 4: "IV",
    5: "V", 6: "VI", 7: "VII", 8: "VIII",
}

SEMESTER_RE: re.Pattern[str] = re.compile(
    r'(?i)\b(?:'
     r'(?:sem\s*(?:ester\s*)?)\s*([\d]+)'
   r'|([\d]+)(?:st|nd|rd|th)\s+(?:sem(?:ester)?)'
   r'|(?:sem(?:ester)?)\s*(-?(?:[ivxlcdm]+|[I-VIII]+))'
   r')\b',
)


# --------------------------------------------------------------------------- #

def _match_semester_number(token: str) -> int:
    """Parse digit or Roman-numeral string to an integer 1-8."""
    clean = token.lstrip("-")
    if clean.isdigit():
        n = int(clean)
        if 1 <= n <= 8:
            return n
    for arabic, roman in ROMAN_MAP.items():
        if token.upper() == roman:
            return arabic
    return -1


def normalize_semester_tokens(query: str) -> str:
    """Replace any semester token with an exhaustive pg_fts OR-expression
    while preserving surrounding text.

    ``sem 2 core courses``  ->  ``(Semester-II OR ...) core courses``
    """
    def _replacer(m: re.Match[str]) -> str:
        raw = m.group(1) or m.group(2) or m.group(3)
        n = _match_semester_number(raw or "")
        if n == -1:
            return m.group(0)
        roman = ROMAN_MAP[n]
        return (f'(Semester-{roman} OR "Semester {roman}" '
                f'OR Semester-{n} OR "Semester {n}")')

    return SEMESTER_RE.sub(_replacer, query)


# --------------------------------------------------------------------------- #
#  Program name detection
# --------------------------------------------------------------------------- #

def detect_program(query: str, program: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """Detect canonical program from the combined text of ``query`` + ``program``.

    Returns ``(cleaned_query, canonical_program)`` where *cleaned\_query* has
    had the detected program tokens stripped to avoid duplication in ft-search.

    Matching order (most-specific first): sub-specializations are checked
    before their parent umbrella e.g. "BTech MnC" before "BTech ICT".
    """
    combined = query.lower().strip()
    if program:
        combined += " " + program.lower()

    canon: Optional[str] = None

    # --- MSc variants ---------------------------------------------------
    for abbrevs, name in (
        ({"mscit", "msc it", "msc(it)", "msc (it)"},   "MSc IT"),
        ({"mscds", "msc ds", "msc(ds)", "msc (ds)"},   "MSc DS"),
        ({"mscaa", "msc aa", "msc(aa)", "msc (aa)"},   "MSc AA"),
    ):
        if any(a in combined for a in abbrevs):
            canon = name
            break

    # --- MTech variants -------------------------------------------------
    if not canon and re.search(r'\bmtech\b', combined):
        if re.search(r'\b(?:cs|ml)\b', combined):
            canon = "MTech CS ML"
        elif re.search(r'\bec\b', combined):
            canon = "MTech EC"
        else:
            canon = "MTech ICT"

    # --- BTech variants -------------------------------------------------
    if not canon and re.search(r'\b(?:btech|b\s*tech)\b', combined):
        if re.search(r'\bmnc\b', combined):
            canon = "BTech MnC"
        elif re.search(r'\bcs\b', combined):
            canon = "BTech ICT CS"
        elif re.search(r'\bevd\b', combined):
            canon = "BTech EVD"
        else:
            canon = "BTech ICT"

    # --- MDes variants --------------------------------------------------
    if not canon and "mdes" in combined:
        if re.search(r'\bcd\b', combined):
            canon = "MDes CD"
        else:
            canon = "MDes IUxD"

    cleaned = _strip_program_tokens(query, canon) if canon else query
    return cleaned, canon


def _strip_program_tokens(query: str, hint: Optional[str]) -> str:
    """Remove program-name tokens already detected from the query text."""
    if not hint:
        return query
    pattern = (
        r'(?:msc|btech|b\.?tech|mtech|m\.?des)\s*'
        r'(?:(?:ict|it|ds|aa|mnc|cs\s*ml|ec|evd|cd|iuxd))?'
        r'|(?:mscit|mscds|mscaa\b)'
    )
    cleaned = re.sub(pattern, '', query, flags=re.IGNORECASE).strip()
    return cleaned


def strip_parens(name: Optional[str]) -> Optional[str]:
    """Remove parentheses from program names before DB lookup."""
    if not name:
        return None
    return name.replace('(', '').replace(')', '')
