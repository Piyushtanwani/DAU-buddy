"""
Offline checks for the behavioural eval harness (evals/run_eval.py).

The harness itself needs a live model; these cover the parts that decide what
a run reports, so a quota error can never be counted as a behaviour failure.
"""
import pytest
import yaml

from api.services import tool_bridge
from evals import run_eval


class _ApiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


PER_MINUTE_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota. Please retry in 19.3s.', 'details': [{'quotaId': "
    "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}, {'retryDelay': '19s'}]}}"
)
PER_DAY_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'quotaId': "
    "'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}}"
)


def test_per_minute_rate_limit_waits_the_requested_delay():
    assert run_eval._retry_delay(_ApiError(429, PER_MINUTE_429)) == pytest.approx(20.3)


def test_per_day_quota_stops_the_run():
    with pytest.raises(run_eval.DailyQuotaExhausted):
        run_eval._retry_delay(_ApiError(429, PER_DAY_429))


def test_model_overload_is_retried_after_a_backoff():
    overloaded = _ApiError(503, "503 UNAVAILABLE. {'error': {'code': 503, 'status': 'UNAVAILABLE'}}")
    assert run_eval._retry_delay(overloaded) == run_eval.OVERLOAD_BACKOFF_S


def test_other_errors_are_not_retried():
    assert run_eval._retry_delay(_ApiError(500, "internal error")) is None
    assert run_eval._retry_delay(ValueError("bad json")) is None


def test_rate_limited_turn_is_retried_and_keeps_only_the_answering_attempt(monkeypatch):
    attempts = []

    def fake_call(api_key, system_instruction, history):
        attempts.append(1)
        run_eval.tool_bridge.dispatch("probe_tool", {"attempt": len(attempts)})
        if len(attempts) == 1:
            raise _ApiError(429, PER_MINUTE_429)
        return "answer", {}

    monkeypatch.setattr(run_eval.gemini, "build_system_instruction", lambda: "")
    monkeypatch.setattr(run_eval.gemini, "call_gemini_api", fake_call)
    monkeypatch.setattr(run_eval.tool_bridge, "dispatch", lambda name, args: "{}")
    monkeypatch.setattr(run_eval.time, "sleep", lambda seconds: None)

    answer, calls = run_eval._answer_turn("key", [])

    assert answer == "answer"
    assert calls == [("probe_tool", {"attempt": 2})]


def test_pipeline_error_makes_the_case_error_not_fail(monkeypatch):
    def broken_call(api_key, system_instruction, history):
        raise ConnectionError("database unreachable")

    monkeypatch.setattr(run_eval.gemini, "build_system_instruction", lambda: "")
    monkeypatch.setattr(run_eval.gemini, "call_gemini_api", broken_call)

    case = {"id": "probe", "turns": [{"user": "hi", "answer_contains": ["x"]}]}
    status, messages = run_eval.run_case(case, "key", verbose=False)

    assert status == "ERROR"
    assert "database unreachable" in messages[0]


def test_check_turn_reports_each_assertion_kind():
    turn = {
        "expect_tools": [{"name": "get_events_by_date", "args_include": {"date_str": "2026-08-07"}}],
        "forbid_tools": [{"name": "get_faculty_schedule", "args_include": {"day": "Friday"}}],
        "answer_contains": ["Tuesday"],
        "answer_excludes": ["12:00"],
        "answer_matches": [r"\b14:00\b"],
    }
    calls = [("get_faculty_schedule", {"day": "friday", "faculty_name": "V Sunitha"})]

    failures = run_eval.check_turn(turn, "Friday at 12:00", calls)

    assert len(failures) == 5


def _tool_names_in_cases() -> set[str]:
    names = set()
    for case in yaml.safe_load(run_eval.CASES_FILE.read_text()):
        for turn in case["turns"]:
            for spec in turn.get("expect_tools", []) + turn.get("forbid_tools", []):
                names.add(spec["name"] if isinstance(spec, dict) else spec)
    return names


def test_cases_name_only_tools_the_model_can_call():
    """
    A case expecting a tool that is not registered can never pass, and a
    forbidden one that is not registered can never fire. Either way the case
    stops testing anything the moment a tool is renamed.
    """
    names = _tool_names_in_cases()
    assert len(names) > 5, "cases.yaml parsed to almost no tool names"

    unknown = names - {t["name"] for t in tool_bridge.list_tools()}
    assert not unknown, f"cases.yaml names tools the model cannot call: {sorted(unknown)}"
