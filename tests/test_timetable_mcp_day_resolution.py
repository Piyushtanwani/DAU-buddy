"""
Tests for day resolution in `dau_mcp/timetable_mcp_server.py`.

Two properties that are easy to regress and invisible when they do:

1. Resolving "which day should this query" costs at most one calendar lookup.
   The tools used to reach the calendar three times before touching the
   timetable — once for the day, once to build the substitution note, once more
   for the clock — which is pure latency on every point-in-time answer.
2. A substituted day is reported on the EMPTY path too. "No sessions" on a
   reassigned date is exactly when the caller needs to be told the campus is
   running another day's timetable.
"""
import asyncio

import pytest

from api.services import calendar_service
from dau_mcp import timetable_mcp_server as tt


@pytest.fixture
def calendar_calls(mocker):
    """Count effective_day() calls; pretend the queried date is reassigned."""
    calls = []

    def _counting(on_date=None):
        calls.append(on_date)
        return "Tuesday", "Friday"

    mocker.patch.object(calendar_service, "effective_day", side_effect=_counting)
    return calls


@pytest.fixture
def no_sessions(mocker):
    """Timetable returns nothing, so the tools take their empty-result path."""
    mocker.patch.object(tt.timetable_service, "get_venue_schedule", return_value=[])
    mocker.patch.object(tt.timetable_service, "find_free_venues", return_value=[])
    mocker.patch.object(tt.timetable_service, "list_venues", return_value=["CEP-209"])


class TestCalendarLookupCost:
    def test_defaulting_to_today_resolves_the_day_once(self, calendar_calls, no_sessions):
        asyncio.run(tt.find_free_venues())

        assert len(calendar_calls) == 1

    def test_an_explicit_day_needs_no_calendar_at_all(self, calendar_calls, no_sessions):
        """A bare weekday cannot be calendar-resolved — don't pay for a lookup."""
        asyncio.run(tt.find_free_venues(day="Monday"))

        assert calendar_calls == []

    def test_an_explicit_date_resolves_once(self, calendar_calls, no_sessions):
        asyncio.run(tt.get_venue_schedule("CEP-209", date="2026-08-07"))

        assert len(calendar_calls) == 1


class TestSubstitutionSurvivesTheEmptyPath:
    def test_venue_with_no_sessions_still_reports_the_substitution(
        self, calendar_calls, no_sessions
    ):
        msg = asyncio.run(tt.get_venue_schedule("CEP-209", date="2026-08-07"))

        assert "Tuesday" in msg
        assert "treated as" in msg

    def test_whole_week_lookup_reports_no_day(self, mocker, no_sessions):
        """With no day and no date there is nothing to substitute — stay quiet."""
        mocker.patch.object(calendar_service, "effective_day", return_value=("Friday", None))
        msg = asyncio.run(tt.get_venue_schedule("CEP-209"))

        assert " on " not in msg
        assert "treated as" not in msg
