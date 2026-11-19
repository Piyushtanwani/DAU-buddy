"""
Coverage of the eval suite: case counts per tool family x kind.

    python -m evals.coverage        # prints the markdown table for evals/README.md

Every case in cases.yaml carries `family` (the tool family the question is
about) and `kind` (what the question demands). tests/test_eval_suite.py checks
that the table in the README is the one this prints, so the two cannot drift.
"""
import sys
from collections import Counter
from pathlib import Path

import yaml

CASES_FILE = Path(__file__).parent / "cases.yaml"

FAMILIES = ["faculty", "staff", "scholars", "library", "timetable", "calendar",
            "documents", "venues", "general"]
KINDS = ["single", "multi-step", "no-tool", "out-of-scope", "ambiguous"]

# Which family each chat tool belongs to. `general` holds what no tool family
# owns: greetings, injection, out-of-scope requests, and the assistant itself.
TOOL_FAMILY = {
    **dict.fromkeys(["list_faculty", "search_faculty", "get_faculty_details",
                     "search_faculty_by_expertise"], "faculty"),
    **dict.fromkeys(["list_staff", "search_staff", "get_staff_details"], "staff"),
    **dict.fromkeys(["list_scholars", "search_scholars", "get_scholar_details"], "scholars"),
    **dict.fromkeys(["search_library_books", "get_book_details"], "library"),
    **dict.fromkeys(["get_faculty_location", "get_faculty_schedule", "find_faculty_free_time",
                     "find_common_free_time", "find_programs_common_free_time",
                     "get_course_schedule", "list_programs", "get_program_timetable",
                     "get_electives"], "timetable"),
    **dict.fromkeys(["list_venues", "get_venue_schedule", "find_free_venues",
                     "check_venue_availability", "search_venues", "get_venue_info",
                     "find_available_venues"], "venues"),
    **dict.fromkeys(["get_next_holiday", "get_upcoming_holidays", "get_all_holidays",
                     "get_midsem_dates", "get_endsem_dates", "get_next_academic_event",
                     "search_calendar", "get_events_by_date"], "calendar"),
    **dict.fromkeys(["search_academic_requirements", "list_academic_documents",
                     "get_academic_document_pages"], "documents"),
    "get_creators_info": "general",
}


def load_cases(path: Path = CASES_FILE) -> list:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def coverage_table(cases: list) -> str:
    counts = Counter((c["family"], c["kind"]) for c in cases)
    header = "| Family | " + " | ".join(KINDS) + " | Total |"
    rule = "|---|" + "---:|" * (len(KINDS) + 1)
    rows = [header, rule]
    for family in FAMILIES:
        cells = [counts[(family, kind)] for kind in KINDS]
        rows.append(f"| {family} | " + " | ".join(str(n) for n in cells) + f" | {sum(cells)} |")
    totals = [sum(counts[(f, k)] for f in FAMILIES) for k in KINDS]
    rows.append("| **Total** | " + " | ".join(str(n) for n in totals) + f" | {sum(totals)} |")
    return "\n".join(rows)


if __name__ == "__main__":
    sys.stdout.write(coverage_table(load_cases()) + "\n")
