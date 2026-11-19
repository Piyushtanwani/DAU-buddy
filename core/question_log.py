"""Anonymous logging of chat questions for the eval suite. Never stores identity."""

import re

from core import config
from core.database import db_connection

logger = config.get_logger("core.question_log")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# A date is matched first and kept, so the number pattern never sees it:
# YYYY-MM-DD and DD-MM-YYYY with -, / or . and real day/month ranges.
_DATE = (
    r"(?<![\w.-])(?:"
    r"(?:19|20)\d{2}[./-](?:0?[1-9]|1[0-2])[./-](?:0?[1-9]|[12]\d|3[01])"
    r"|(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-](?:19|20)\d{2}"
    r")(?![.-]?\d)"
)
# A phone / enrollment number: optional +country code and (area code), then
# groups of 2+ digits joined by a space, dot or hyphen — "987-654-3210",
# "987.654.3210", "(079) 6826 1641", "98 76 54 32 10". An unbroken run is
# redacted from 7 digits (enrollment numbers); a grouped one from 10, the length
# of a mobile or an area code plus landline. Below 10, grouped digits are room
# lists, slots and times ("rooms 101 102 103", "10.30 11.30"), which the eval
# suite needs intact. Single digits ("sem 3 4 5") and "10:00" never match.
_NUMBER = (
    r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,5}\)[\s.-]?)?"
    r"\d{2,}(?:[\s.-]\d{2,})*(?!\w)"
)
_DATE_OR_NUMBER_RE = re.compile(f"(?P<date>{_DATE})|(?P<number>{_NUMBER})")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
# Clock times and ranges of them, "10.30-12.30 14.00-15.00": kept at any length.
_TIME = r"(?:[01]?\d|2[0-3])[.:][0-5]\d"
_TIMES_RE = re.compile(rf"{_TIME}(?:[\s-]+{_TIME})*")

_ROLE_BUCKETS = {"faculty": "faculty", "staff": "staff"}


def caller_role_bucket(role: str | None) -> str:
    """Map a resolved role to student | faculty | staff."""
    first = (role or "").lower().split("/")[0].strip()
    return _ROLE_BUCKETS.get(first, "student")


def _redact_number(match: re.Match) -> str:
    if match.group("date"):
        return match.group("date")
    text = match.group("number")
    groups = re.findall(r"\d+", text)
    if sum(len(g) for g in groups) < (7 if len(groups) == 1 else 10):
        return text
    if _TIMES_RE.fullmatch(text):
        return text
    if all(_YEAR_RE.fullmatch(g) for g in groups):   # "the 2022 2023 batch"
        return text
    return "[number]"


def redact_personal_details(text: str) -> str:
    return _DATE_OR_NUMBER_RE.sub(_redact_number, _EMAIL_RE.sub("[email]", text))


def log_chat_question(question: str, role: str | None) -> bool:
    """Store one anonymous row. Returns False on skip or failure; never raises."""
    try:
        cleaned = redact_personal_details(question).strip()
        if not cleaned:
            return False
        with db_connection() as conn:
            with conn.cursor() as cursor:
                # day only, so the row can't be matched by time to the analytics row
                cursor.execute(
                    "INSERT INTO chat_questions (question, caller_role, created_at) "
                    "VALUES (%s, %s, date_trunc('day', CURRENT_TIMESTAMP))",
                    (cleaned, caller_role_bucket(role)),
                )
        return True
    except Exception as e:
        logger.error(f"Failed to log chat question: {e}")
        return False
