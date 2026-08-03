"""
Tests for the lab timetable parser (`scripts/seed_timetable.py`).

Why these exist: the timetable committee ships a reshaped workbook every
semester, and `parse_lab_excel` carries course/faculty values forward across
rows to handle tutorial continuation rows. That carry-forward is correct for
the workbook in front of us, but nothing in the code guarantees it stays
correct for the next one — and a wrong `faculty` lands in the `timetables`
table, which backs `get_faculty_schedule`, `get_faculty_location` and
`find_faculty_free_time`. A wrong instructor there produces a confidently
wrong answer about where a professor is.

These tests feed the parser rows directly, so they need neither a database nor
an .xlsx fixture on disk.
"""
import importlib.util
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_SCRIPT = os.path.join(REPO_ROOT, "scripts", "seed_timetable.py")


def _load_seed_module():
    """`scripts/` is not a package, so load the module by path."""
    spec = importlib.util.spec_from_file_location("seed_timetable", SEED_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed_timetable = _load_seed_module()


# ── Fake workbook plumbing ────────────────────────────────────────────────────
# parse_lab_excel() opens the file itself rather than accepting rows, so the
# openpyxl name in its module globals is swapped for a stub. If that function is
# ever refactored to take rows directly, all of this collapses to a plain call.

class _FakeSheet:
    def __init__(self, rows):
        self._rows = rows

    def iter_rows(self, values_only=True):
        return iter(self._rows)


class _FakeWorkbook:
    sheetnames = ["Sheet1"]

    def __init__(self, rows):
        self._sheet = _FakeSheet(rows)

    def __getitem__(self, _name):
        return self._sheet


class _FakeOpenpyxl:
    def __init__(self, rows):
        self._rows = rows

    def load_workbook(self, *args, **kwargs):
        return _FakeWorkbook(self._rows)


HEADER = ["Time Slot", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", None, None, None]


def row(time_slot, monday=None, room=None, course=None, faculty=None):
    """One sheet row in the column layout parse_lab_excel expects."""
    return [time_slot, monday, None, None, None, None, room, course, faculty]


def parse(monkeypatch, rows, curriculum=None, abbrev_map=None):
    monkeypatch.setattr(seed_timetable, "openpyxl", _FakeOpenpyxl([HEADER] + rows))
    return seed_timetable.parse_lab_excel("fake.xlsx", curriculum or {}, abbrev_map)


# ── Carry-forward: the behaviour the feature exists for ──────────────────────

def test_continuation_row_inherits_course_and_faculty(monkeypatch):
    """A tutorial continuation row leaves course/faculty blank and expects the
    values above it to carry down. Without this the session is dropped."""
    records = parse(monkeypatch, [
        row("B Tech (ICT)"),
        row("09:00-11:00", monday="G1", room="LAB101", course="IC101", faculty="AAA"),
        row("11:00-13:00", monday="Tut. G2", room="LAB102"),
    ])

    assert len(records) == 2
    continuation = records[1]
    assert continuation["course_code"] == "IC101"
    assert continuation["faculty"] == "AAA"
    assert continuation["session_type"] == "Tutorial (Tut. G2)"
    # The room is the continuation row's own, never inherited.
    assert continuation["room"] == "LAB102"


def test_program_header_resets_carry_forward(monkeypatch):
    """Values must not leak across program sections — a blank course under a
    new header means 'no course', not 'the last one from the section above'."""
    records = parse(monkeypatch, [
        row("B Tech (ICT)"),
        row("09:00-11:00", monday="G1", room="LAB101", course="IC101", faculty="AAA"),
        row("B Tech (MnC)"),
        row("11:00-13:00", monday="G2", room="LAB102"),
    ])

    assert len(records) == 1
    assert records[0]["course_code"] == "IC101"


def test_dash_placeholder_does_not_become_a_course(monkeypatch):
    """'-' marks an empty cell, not a course code."""
    records = parse(monkeypatch, [
        row("B Tech (ICT)"),
        row("09:00-11:00", monday="G1", room="LAB101", course="-", faculty="AAA"),
    ])

    assert records == []


# ── The gap this suite was written to pin down ───────────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason="last_course and last_faculty are tracked independently, so a row "
           "introducing a new course with a blank faculty cell inherits the "
           "previous course's instructor. Fix: reset last_faculty when "
           "course_raw != last_course, then drop this marker.",
)
def test_new_course_does_not_inherit_previous_faculty(monkeypatch):
    """A new course with an empty faculty cell must not be attributed to the
    previous course's instructor.

    This does not occur in the current workbook — it depends on the shape of
    the next one, which is exactly why it is worth pinning here rather than
    discovering it through a wrong answer about a professor's whereabouts.
    """
    records = parse(monkeypatch, [
        row("B Tech (ICT)"),
        row("09:00-11:00", monday="G1", room="LAB101", course="IC101", faculty="AAA"),
        row("11:00-13:00", monday="G2", room="LAB102", course="IC202"),  # no faculty
    ])

    assert records[1]["course_code"] == "IC202"
    assert records[1]["faculty"] != "AAA", "IC202 was attributed to IC101's instructor"


# ── Faculty short-name resolution ────────────────────────────────────────────
# The lab workbook names staff by short name ("AC"); the lecture workbook writes
# "Ankush Chander (AC)". Unresolved, every faculty-name query misses that
# person's labs — schedules, locations, and busy/free time alike.

ABBREV = {
    "AC": "Ankush Chander (AC)",
    "AC1": "Arunava Chakravarty (AC1)",
    "NKS": "N K Sharma (NKS)",
}


def test_short_name_resolves_to_lecture_display_form(monkeypatch):
    records = parse(monkeypatch, [
        row("B Tech (ICT)"),
        row("09:00-11:00", monday="G1", room="LAB210", course="DS635", faculty="AC"),
    ], abbrev_map=ABBREV)

    assert records[0]["faculty"] == "Ankush Chander (AC)"


def test_similar_short_names_are_not_confused(monkeypatch):
    """'AC' and 'AC1' are different people. Resolution is exact per token —
    substring matching would cross-attribute their teaching."""
    records = parse(monkeypatch, [
        row("B Tech (ICT)"),
        row("09:00-11:00", monday="G1", room="LAB210", course="DS635", faculty="AC"),
        row("11:00-13:00", monday="G2", room="LAB211", course="IE406", faculty="AC1"),
    ], abbrev_map=ABBREV)

    assert records[0]["faculty"] == "Ankush Chander (AC)"
    assert records[1]["faculty"] == "Arunava Chakravarty (AC1)"


def test_multiple_instructors_each_resolve(monkeypatch):
    records = parse(monkeypatch, [
        row("B Tech (ICT)"),
        row("09:00-11:00", monday="Tut. G1", room="CEP-103", course="IC105", faculty="AC/NKS"),
    ], abbrev_map=ABBREV)

    assert records[0]["faculty"] == "Ankush Chander (AC) / N K Sharma (NKS)"


def test_unknown_short_name_is_left_alone(monkeypatch):
    """'TF/TA' and codes missing from the abbreviations sheet must pass through
    untouched rather than being mangled or dropped."""
    records = parse(monkeypatch, [
        row("B Tech (ICT)"),
        row("09:00-11:00", monday="G1", room="LAB210", course="DS635", faculty="TF/TA"),
        row("11:00-13:00", monday="G2", room="LAB211", course="DS636", faculty="BD"),
    ], abbrev_map=ABBREV)

    assert records[0]["faculty"] == "TF/TA"
    assert records[1]["faculty"] == "BD"


def test_no_abbrev_map_is_a_no_op(monkeypatch):
    """Callers that pass no map (older call sites, tests) keep the raw value."""
    records = parse(monkeypatch, [
        row("B Tech (ICT)"),
        row("09:00-11:00", monday="G1", room="LAB210", course="DS635", faculty="AC"),
    ])

    assert records[0]["faculty"] == "AC"


def test_expand_faculty_codes_is_pure():
    """Unit-level checks of the resolver itself."""
    expand = seed_timetable.expand_faculty_codes
    assert expand("AC", ABBREV) == "Ankush Chander (AC)"
    assert expand("AC / NKS", ABBREV) == "Ankush Chander (AC) / N K Sharma (NKS)"
    assert expand("AC/UNKNOWN", ABBREV) == "Ankush Chander (AC) / UNKNOWN"
    assert expand("UNKNOWN", ABBREV) == "UNKNOWN"
    assert expand("", ABBREV) == ""
    assert expand("AC", {}) == "AC"


# ── Smoke test against the real workbook, when it is present ─────────────────

def test_real_workbook_parses(monkeypatch):
    """Guards against a shipped workbook the parser cannot read at all. Makes
    no assertion about counts — those change legitimately every semester."""
    workbook = os.path.join(seed_timetable.DATA_DIR, "Lab Data.xlsx")
    if not os.path.exists(workbook):
        pytest.skip("data/Lab Data.xlsx not present")

    records = seed_timetable.parse_lab_excel(workbook, seed_timetable.load_curriculum())

    assert records, "parser returned no records for the shipped workbook"
    assert all(r["course_code"] for r in records), "record emitted without a course code"
    assert all(r["day"] and r["start"] and r["end"] for r in records)
