"""Tests for chat question logging (#70)."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import question_log
from core.question_log import caller_role_bucket, log_chat_question, redact_personal_details

ANSWER = "Test fallback answer"


class _FakeDb:
    """Fake db_connection() that records execute() calls."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.executed: list[tuple[str, tuple]] = []

    def __call__(self):
        db = self

        class _Conn:
            def __enter__(self_inner):
                if db.fail:
                    raise RuntimeError("simulated database failure")
                conn = MagicMock()
                cursor = MagicMock()
                cursor.execute.side_effect = lambda sql, params=None: db.executed.append((sql, params))
                conn.cursor.return_value.__enter__.return_value = cursor
                conn.cursor.return_value.__exit__.return_value = False
                return conn

            def __exit__(self_inner, *exc):
                return False

        return _Conn()


@pytest.mark.parametrize("role_in, role_out", [
    ("Student", "student"),
    ("student", "student"),
    ("Student / Maintainer", "student"),
    ("Faculty", "faculty"),
    ("Staff", "staff"),
    ("Maintainer", "student"),
    ("Unknown", "student"),
    ("", "student"),
    (None, "student"),
])
def test_caller_role_bucket(role_in, role_out):
    assert caller_role_bucket(role_in) == role_out


class TestRowContents:
    def test_writes_exactly_one_row_without_identity(self):
        db = _FakeDb()
        with patch.object(question_log, "db_connection", db):
            assert log_chat_question("Where is Prof Sunitha's office?", "Faculty") is True

        assert len(db.executed) == 1
        sql, params = db.executed[0]
        assert "INSERT INTO chat_questions" in sql
        assert params == ("Where is Prof Sunitha's office?", "faculty")
        column_list = sql.split("VALUES")[0].lower()
        for forbidden in ("email", "ip", "history", "user"):
            assert forbidden not in column_list.replace("caller_role", "")

    def test_time_is_cut_to_the_day(self):
        db = _FakeDb()
        with patch.object(question_log, "db_connection", db):
            log_chat_question("hello", "Student")
        assert "date_trunc('day'" in db.executed[0][0]

    def test_blank_question_is_not_stored(self):
        db = _FakeDb()
        with patch.object(question_log, "db_connection", db):
            assert log_chat_question("   ", "Student") is False
        assert db.executed == []


@pytest.mark.parametrize("text, expected", [
    ("mail me at 202001001@daiict.ac.in", "mail me at [email]"),
    ("my id is 202001001", "my id is [number]"),
    ("call +919876543210 now", "call [number] now"),
    ("call 98765 43210 now", "call [number] now"),
    # kept as is
    ("classes on 2026-08-07 at 10:00", "classes on 2026-08-07 at 10:00"),
    ("room 1203 and CS 101", "room 1203 and CS 101"),
])
def test_redaction(text, expected):
    assert redact_personal_details(text) == expected


def test_redacted_text_is_what_gets_stored():
    db = _FakeDb()
    with patch.object(question_log, "db_connection", db):
        log_chat_question("my id is 202001001, mail a@b.com", "Student")
    assert db.executed[0][1][0] == "my id is [number], mail [email]"


def test_insert_failure_is_logged_and_does_not_raise(caplog):
    with patch.object(question_log, "db_connection", _FakeDb(fail=True)):
        with caplog.at_level(logging.ERROR):
            result = log_chat_question("anything", "Student")
    assert result is False
    assert any("Failed to log chat question" in r.getMessage() for r in caplog.records)


class TestChatEndpoint:

    @pytest.fixture()
    def client(self):
        from api.routes import chat as chat_module

        patches = [
            patch.object(chat_module, "is_gemini_available", return_value=False),
            patch.object(chat_module, "openai_configured", return_value=False),
            patch.object(chat_module, "is_openai_available", return_value=False),
            patch.object(chat_module, "process_fallback_message", new=MagicMock(return_value=ANSWER)),
            patch.object(chat_module, "db_connection", _FakeDb()),
        ]
        for p in patches:
            p.start()

        app = FastAPI()
        app.include_router(chat_module.router)
        app.dependency_overrides[chat_module.authenticate_request] = (
            lambda: ("202001001@daiict.ac.in", "Student")
        )
        yield TestClient(app, raise_server_exceptions=False)
        for p in patches:
            p.stop()

    def test_one_question_logs_one_row_with_no_email(self, client):
        db = _FakeDb()
        with patch.object(question_log, "db_connection", db):
            resp = client.post("/chat", json={"message": "When is the next holiday?", "history": []})

        assert resp.status_code == 200
        assert resp.json()["response"] == ANSWER
        assert len(db.executed) == 1
        sql, params = db.executed[0]
        assert "chat_questions" in sql
        assert params == ("When is the next holiday?", "student")
        assert "202001001" not in repr(db.executed)     

    def test_chat_still_answers_when_the_insert_raises(self, client, caplog):
        with patch.object(question_log, "db_connection", _FakeDb(fail=True)):
            with caplog.at_level(logging.ERROR):
                resp = client.post("/chat", json={"message": "When is the next holiday?", "history": []})

        assert resp.status_code == 200
        assert resp.json()["response"] == ANSWER
        assert any("Failed to log chat question" in r.getMessage() for r in caplog.records)

@pytest.mark.parametrize("text, expected", [
    ("call 987-654-3210", "call [number]"),
    ("+91 98765 43210", "[number]"),
    ("id 202001001", "id [number]"),
    ("schedule on 2026-08-07 10:00", "schedule on 2026-08-07 10:00"),
    ("due 07-08-2026", "due 07-08-2026"),
    ("room 101 and 102", "room 101 and 102"),
    # brackets, dots and 2-digit groups are redacted too
    ("call (079) 6826 1641", "call [number]"),
    ("call 987.654.3210", "call [number]"),
    ("call 98 76 54 32 10", "call [number]"),
    # ...while dates in the same shapes, digit lists and year ranges are kept
    ("due 07.08.2026", "due 07.08.2026"),
    ("between 2026-08-07 2026-08-08", "between 2026-08-07 2026-08-08"),
    ("sem 3 4 5 6 7 8 9", "sem 3 4 5 6 7 8 9"),
    ("the 2022 2023 batch", "the 2022 2023 batch"),
    ("10:00-11:00 in IC101", "10:00-11:00 in IC101"),
    # room lists and slots (grouped, under 10 digits) and clock times (any length)
    ("lab 10.30-12.30 then 14.00-15.00", "lab 10.30-12.30 then 14.00-15.00"),
    ("free 10.30-12.30 14.00-15.00", "free 10.30-12.30 14.00-15.00"),
    ("class 10.30 11.30", "class 10.30 11.30"),
    ("rooms 101 102 103", "rooms 101 102 103"),
    ("slots 10 11 12 13", "slots 10 11 12 13"),
    ("IT 227 643 635", "IT 227 643 635"),
    # a landline with its area code, and a 10-digit number in dotted pairs
    ("call 079-68261563", "call [number]"),
    ("call 98.76.54.32.10", "call [number]"),
])
def test_number_redaction_keeps_dates_and_short_numbers(text, expected):
    assert redact_personal_details(text) == expected
