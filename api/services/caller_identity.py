import re
import sys
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Tuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.database import db_connection
from core import config

logger = config.get_logger("api.services.caller_identity")

# Digits 5-6 of a roll number → candidate programme names. More than one
# candidate means ambiguous: resolve by asking, not by parsing. Code 01 is
# documented as "if it is 014 then ICT-CS else ICT", which reads a digit of the
# serial as part of the programme code — so it stays ambiguous here.
PROGRAM_CODES: dict[str, Tuple[str, ...]] = {
    "01": ("B Tech (ICT)", "B Tech (ICT-CS)"),
    "02": ("BE",),
    "03": ("B Tech (MnC)",),
    "04": ("B Tech (EVD)",),
    "11": ("M Tech (ICT)",),
    "12": ("MSc (IT)",),
    "13": ("MSc (ICT-ARD)",),
    "14": ("M Des (CD)", "M Des (IUXD)"),
    "15": ("M Tech (EC)", "M Tech (CS&ML)"),
    "16": ("M Tech (CS - Data Science)",),
    "17": ("M Tech (CS - Information Security)",),
    "18": ("MSc (DS)",),
    "19": ("MSc (AA)",),
    "21": ("Ph D",),
}

# Nominal length, used only to tell a current student from a graduate.
PROGRAM_DURATION_SEMESTERS: dict[str, int] = {
    "01": 8, "02": 8, "03": 8, "04": 8,
    "11": 4, "12": 4, "13": 4, "14": 4, "15": 4, "16": 4, "17": 4,
    "18": 4, "19": 4,
}

# 4-digit admission year + 2-digit programme code + 3-digit serial.
ROLL_NUMBER_RE = re.compile(r"^(\d{4})(\d{2})(\d{3})$")

EARLIEST_ADMISSION_YEAR = 2001


@dataclass(frozen=True)
class CallerIdentity:
    email: str
    role: str
    display_name: Optional[str] = None
    # The caller's name as the *timetable* spells it, when it could be
    # confirmed. Separate from display_name because the directory and the
    # timetable are different name spaces (see _resolve_timetable_name).
    timetable_name: Optional[str] = None

    roll_number: Optional[str] = None
    admission_year: Optional[int] = None
    program_code: Optional[str] = None
    program_candidates: Tuple[str, ...] = field(default_factory=tuple)
    semester_estimate: Optional[int] = None
    is_probably_alumnus: bool = False

    @property
    def is_student(self) -> bool:
        return self.role.startswith("Student")

    @property
    def program(self) -> Optional[str]:
        """The programme, only when unambiguous."""
        return self.program_candidates[0] if len(self.program_candidates) == 1 else None

    @property
    def program_is_ambiguous(self) -> bool:
        return len(self.program_candidates) > 1

    @property
    def program_is_unmapped(self) -> bool:
        return self.program_code is not None and not self.program_candidates


def parse_roll_number(local_part: str) -> Optional[Tuple[int, str, str]]:
    m = ROLL_NUMBER_RE.match(local_part.strip())
    if not m:
        return None

    year_s, code, serial = m.groups()
    year = int(year_s)
    if not (EARLIEST_ADMISSION_YEAR <= year <= date.today().year + 1):
        return None

    return year, code, serial


def current_academic_term(today: Optional[date] = None) -> Tuple[int, int]:
    today = today or date.today()
    if today.month >= 7:
        return today.year, 0
    return today.year - 1, 1


def estimate_semester(admission_year: int, today: Optional[date] = None) -> int:
    """
    Semesters elapsed since admission, floored at 1.

    The floor is not cosmetic: between January and June of their own admission
    year a fresher's roll number scores 0, and a roll number issued one year
    ahead (which parse_roll_number deliberately accepts) scores -1. Those went
    into the prompt verbatim as "Likely semester: 0".
    """
    academic_year_start, term_index = current_academic_term(today)
    return max(1, (academic_year_start - admission_year) * 2 + 1 + term_index)


def normalize_person_name(name: str) -> str:
    """
    Casefold a person's name to the form used to compare across name spaces:
    the trailing "(MVJ)" initials the timetable carries are dropped and every
    run of punctuation or space becomes a single space. "Manjunath v. joshi"
    and "Manjunath V Joshi (MVJ)" both reduce to "manjunath v joshi".

    The SQL in _resolve_timetable_name applies the same two substitutions, so
    the two sides must be changed together.
    """
    without_initials = re.sub(r"\(.*?\)", " ", name or "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_initials.lower()).split())


# Same normalisation as normalize_person_name, evaluated in the database so the
# comparison can run over timetables.faculty_name directly.
_TIMETABLE_NAME_SQL = r"""
    SELECT DISTINCT faculty_name
    FROM timetables
    WHERE faculty_name IS NOT NULL
      AND btrim(regexp_replace(
              regexp_replace(lower(faculty_name), '\(.*?\)', ' ', 'g'),
              '[^a-z0-9]+', ' ', 'g')) = %s
"""


def _resolve_timetable_name(cur, display_name: str) -> Optional[str]:
    """
    The caller's name as timetables.faculty_name spells it, or None.

    Deliberately exact-after-normalisation, and deliberately not fuzzy. The
    directory and the timetable are populated from different sources, and 29 of
    121 faculty who teach are spelled differently in the two. Every cheap way of
    bridging that gap was measured against the live data and each one hands a
    signed-in caller a *colleague's* identity as verified context:

      - unique surname match:  6 of the 20 it fires on are the wrong person
        ("Anupam rana" -> "Arpit Rana", "Dhaval joshi" -> "Manjunath V Joshi").
      - pg_trgm word_similarity at the tuned 0.55 threshold: 3 of 19 wrong, and
        it ranks "Abhishek Tripathy" (0.667) above the correct "Abhishek
        Kantilal Tilva" (0.652) for directory name "Abhishek tilva".

    So a name that does not match exactly yields None and the caller context
    simply omits the line. That is safe here because the system prompt already
    tells the model these are two name spaces and to fall back to
    search_faculty/search_staff (rules A3 and A4). Closing the gap properly
    needs a real alias table, not a third fuzzy matcher.
    """
    normalized = normalize_person_name(display_name)
    if not normalized:
        return None
    cur.execute(_TIMETABLE_NAME_SQL, (normalized,))
    rows = cur.fetchall()
    # More than one distinct spelling normalising to the same name is a genuine
    # ambiguity in the timetable; omit rather than pick.
    return rows[0][0] if len(rows) == 1 else None


def _lookup_directory_identity(email: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve (directory name, timetable name) for a non-student caller.

    Both come out of one connection: this runs on every chat turn for faculty
    and staff, and the directory lookup already had to open one.
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                name = None
                for table in ("faculty", "staff"):
                    cur.execute(
                        f"SELECT name FROM {table} WHERE email = %s LIMIT 1", (email,)
                    )
                    row = cur.fetchone()
                    if row:
                        name = row[0]
                        break

                if not name:
                    return None, None

                return name, _resolve_timetable_name(cur, name)
    except Exception as e:
        logger.error(f"Directory name lookup failed for {email}: {e}")

    return None, None


def resolve_caller(email: str, role: str, today: Optional[date] = None) -> CallerIdentity:
    local_part = email.split("@")[0]

    if not role.startswith("Student"):
        display_name, timetable_name = _lookup_directory_identity(email)
        return CallerIdentity(
            email=email,
            role=role,
            display_name=display_name,
            timetable_name=timetable_name,
        )

    parsed = parse_roll_number(local_part)
    if not parsed:
        return CallerIdentity(email=email, role=role)

    admission_year, code, _serial = parsed
    candidates = PROGRAM_CODES.get(code, ())
    # parse_roll_number accepts next year's intake, who have not started yet:
    # there is no semester to estimate for them, and stating one would be a
    # claim about a student who does not exist.
    started = admission_year <= (today or date.today()).year
    semester = estimate_semester(admission_year, today) if started else None
    duration = PROGRAM_DURATION_SEMESTERS.get(code)

    return CallerIdentity(
        email=email,
        role=role,
        roll_number=local_part,
        admission_year=admission_year,
        program_code=code,
        program_candidates=candidates,
        semester_estimate=semester,
        is_probably_alumnus=(
            duration is not None and semester is not None and semester > duration
        ),
    )
