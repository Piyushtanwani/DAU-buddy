"""
Tests for faculty name resolution in `api/services/timetable_service.py`.

`resolve_faculty` matches `timetables.faculty_name` by substring, and every
schedule/free-time tool refuses to answer until it narrows to exactly one
candidate. When one stored name is a prefix of another, picking a suggested
candidate has to actually resolve it — otherwise the assistant offers a choice,
the user makes it, and the same question comes back forever.
"""
from unittest.mock import MagicMock

import pytest

from api.services import timetable_service


def mock_db(mocker, rows):
    """Point timetable_service.db_connection at a cursor returning `rows`."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = [(r,) for r in rows]

    mocker.patch("api.services.timetable_service.db_connection", return_value=mock_conn)
    return mock_cur


class TestResolveFaculty:
    def test_single_match_passes_through(self, mocker):
        mock_db(mocker, ["Ankush Chander (AC)"])
        assert timetable_service.resolve_faculty("Ankush") == ["Ankush Chander (AC)"]

    def test_genuinely_ambiguous_query_returns_all_candidates(self, mocker):
        """'Jat' really is ambiguous — the caller should ask."""
        mock_db(mocker, ["H S Jattana (HSJ)", "P M Jat (PMJ)"])

        assert timetable_service.resolve_faculty("Jat") == [
            "H S Jattana (HSJ)", "P M Jat (PMJ)",
        ]

    def test_exact_match_wins_over_longer_substring_match(self, mocker):
        """Picking a candidate we offered must resolve to that candidate.

        Regression: co-taught sessions once stored a joined name, so
        'Ankit Vijayvargiya (AV)' also matched
        'Ankit Vijayvargiya (AV) / Pankaj Kumar (PK)'. The user's answer was
        rejected as ambiguous every time.
        """
        mock_db(mocker, [
            "Ankit Vijayvargiya (AV)",
            "Ankit Vijayvargiya (AV) / Pankaj Kumar (PK)",
        ])

        assert timetable_service.resolve_faculty("Ankit Vijayvargiya (AV)") == [
            "Ankit Vijayvargiya (AV)"
        ]

    def test_exact_match_is_case_and_space_insensitive(self, mocker):
        mock_db(mocker, ["P M Jat (PMJ)", "P M Jat (PMJ) / Someone Else (SE)"])

        assert timetable_service.resolve_faculty("  p m jat (pmj)  ") == [
            "P M Jat (PMJ)"
        ]

    def test_no_match_returns_empty(self, mocker):
        mock_db(mocker, [])
        assert timetable_service.resolve_faculty("Nobody") == []


class TestResolveSingle:
    def test_exact_pick_unblocks_the_caller(self, mocker):
        """resolve_single gates every schedule/free-time tool: no single name,
        no answer. This is the path the disambiguation loop got stuck in."""
        mock_db(mocker, [
            "Ankit Vijayvargiya (AV)",
            "Ankit Vijayvargiya (AV) / Pankaj Kumar (PK)",
        ])

        name, matches = timetable_service.resolve_single("Ankit Vijayvargiya (AV)")

        assert name == "Ankit Vijayvargiya (AV)"
        assert len(matches) == 1

    def test_ambiguous_query_still_blocks(self, mocker):
        mock_db(mocker, ["H S Jattana (HSJ)", "P M Jat (PMJ)"])

        name, matches = timetable_service.resolve_single("Jat")

        assert name is None
        assert len(matches) == 2
