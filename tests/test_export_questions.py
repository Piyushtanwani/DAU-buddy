"""Tests for scripts/export_questions.py (spreadsheet-safe CSV cells)."""

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "export_questions.py"
_spec = importlib.util.spec_from_file_location("export_questions", _PATH)
export_questions = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export_questions)


@pytest.mark.parametrize("value, expected", [
    ("=HYPERLINK(\"http://x\")", "'=HYPERLINK(\"http://x\")"),
    ("+1+1", "'+1+1"),
    ("-2+3", "'-2+3"),
    ("@SUM(A1)", "'@SUM(A1)"),
    ("\tcmd", "'\tcmd"),
    ("Where is the library?", "Where is the library?"),
    ("student", "student"),
    (12, 12),
    (None, None),
    ("", ""),
])
def test_safe_cell(value, expected):
    assert export_questions.safe_cell(value) == expected
