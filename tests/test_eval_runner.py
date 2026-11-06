"""
Offline checks for the SLA-scoring parts of the eval runner: argument
validation, outcome labels, summary arithmetic and trajectory files.
"""
import json

import pytest

from api.services import tool_bridge
from evals import run_eval
from evals.trajectory import RUN_OUTCOMES, validate_tool_arguments

SCHEMAS = {t["name"]: t["parameters"] for t in tool_bridge.list_tools()}
PROGRAMS = SCHEMAS["find_programs_common_free_time"]
FACULTY = SCHEMAS["find_common_free_time"]


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

def test_valid_calls_pass():
    assert validate_tool_arguments(FACULTY, {"faculty_names": ["A", "B"], "day": "Monday"}) is None
    assert validate_tool_arguments(PROGRAMS, {"programs": [{"program_name": "B Tech", "semester": "3"}]}) is None


@pytest.mark.parametrize("arguments, rule, parameter", [
    ({}, "missing_required_param", "faculty_names"),
    ({"faculty_names": ["A"], "bogus": 1}, "unknown_param", "bogus"),
    ({"faculty_names": "A"}, "wrong_type", "faculty_names"),
    ({"faculty_names": ["A", 7]}, "wrong_type", "faculty_names[1]"),
    ({"faculty_names": ["A"], "day": 5}, "wrong_type", "day"),
])
def test_array_of_strings_is_checked_item_by_item(arguments, rule, parameter):
    error = validate_tool_arguments(FACULTY, arguments)
    assert (error.rule, error.parameter) == (rule, parameter)


@pytest.mark.parametrize("arguments, rule, parameter", [
    ({"programs": ["B Tech"]}, "wrong_type", "programs[0]"),
    ({"programs": [{"semester": "3"}]}, "missing_required_param", "programs[0].program_name"),
    ({"programs": [{"program_name": 3}]}, "wrong_type", "programs[0].program_name"),
])
def test_ref_items_are_resolved_from_defs(arguments, rule, parameter):
    error = validate_tool_arguments(PROGRAMS, arguments)
    assert (error.rule, error.parameter) == (rule, parameter)


def test_arguments_must_be_an_object():
    assert validate_tool_arguments(FACULTY, ["A"]).rule == "wrong_type"


def test_bool_is_not_an_integer_and_null_is_fine_for_optional_params():
    schema = {"type": "object", "properties": {"n": {"type": "integer"}, "s": {"type": "string"}},
              "required": ["n"]}
    assert validate_tool_arguments(schema, {"n": True}).rule == "wrong_type"
    assert validate_tool_arguments(schema, {"n": 1, "s": None}) is None
    assert validate_tool_arguments(schema, {"n": None}).rule == "wrong_type"


# ---------------------------------------------------------------------------
# Outcome labels
# ---------------------------------------------------------------------------

EXPECTING = {"id": "c", "turns": [{"user": "q", "expect_tools": ["search_staff"]}]}
PLAIN = {"id": "c", "turns": [{"user": "q"}]}


@pytest.mark.parametrize("case, status, answers, tool_called, expected", [
    (EXPECTING, "PASS", ["Here you go"], True, "completed"),
    (EXPECTING, "FAIL", ["Here you go"], False, "non_attempt"),
    (PLAIN, "PASS", ["Hello"], False, "completed"),
    (EXPECTING, "FAIL", [run_eval.TURN_LIMIT_PREFIX + ". Could you ask..."], True, "turn_limit"),
    (EXPECTING, "FAIL", [run_eval.EMPTY_ANSWER], True, "empty_answer"),
    (EXPECTING, "ERROR", [], False, "harness_error"),
])
def test_outcome_labels(case, status, answers, tool_called, expected):
    outcome = run_eval.classify_outcome(case, status, answers, tool_called)
    assert outcome == expected
    assert outcome in RUN_OUTCOMES


def test_truncated_flag_is_labelled_when_a_service_reports_it():
    assert run_eval.classify_outcome(PLAIN, "FAIL", ["cut off"], False, truncated=True) == "truncated"


# ---------------------------------------------------------------------------
# Summary arithmetic
# ---------------------------------------------------------------------------

def _r(rep, status, fabricated=False, outcome="completed"):
    return run_eval.CaseResult("c", rep, status, [], outcome, fabricated, 0, [])


def test_summary_scores_pass_fail_and_never_scores_errors():
    results = [
        _r(1, "PASS"), _r(1, "PASS", fabricated=True), _r(1, "FAIL"), _r(1, "ERROR", outcome="harness_error"),
        _r(2, "PASS"), _r(2, "PASS"), _r(2, "PASS"), _r(2, "FAIL"),
    ]
    summary = run_eval.summarize(results, provider="openai", model="m", reps=2)

    first, second = summary["runs"]
    assert (first["pass"], first["fail"], first["error"]) == (2, 1, 1)
    assert first["pass_rate"] == pytest.approx(2 / 3)
    assert first["fabrication_rate"] == pytest.approx(1 / 3)
    assert second["pass_rate"] == pytest.approx(3 / 4)
    assert summary["pass_rate"] == pytest.approx((2 / 3 + 3 / 4) / 2)
    assert summary["fabrication_rate"] == pytest.approx((1 / 3 + 0) / 2)
    assert summary["error_count"] == 1
    assert first["outcomes"] == {"completed": 3, "harness_error": 1}


def test_a_run_with_nothing_scored_has_no_rate():
    summary = run_eval.summarize([_r(1, "ERROR", outcome="harness_error")], provider="gemini", model="m", reps=1)
    assert summary["pass_rate"] is None and summary["fabrication_rate"] is None
    assert summary["error_count"] == 1


# ---------------------------------------------------------------------------
# Trajectory files
# ---------------------------------------------------------------------------

def _events(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def _patch_pipeline(monkeypatch, model):
    monkeypatch.setattr(run_eval.gemini, "build_system_instruction", lambda: "")
    monkeypatch.setattr(run_eval.openai_service, "call_openai_api", model)
    monkeypatch.setattr(run_eval, "_database_unreachable", lambda: None)
    monkeypatch.setattr(run_eval.tool_bridge, "dispatch", lambda name, args: "ok")
    monkeypatch.setattr(run_eval.time, "sleep", lambda seconds: None)


def test_case_writes_a_trajectory_and_counts_bad_arguments_as_fabrication(monkeypatch, tmp_path):
    def model(api_key, system_instruction, history):
        run_eval.tool_bridge.dispatch("search_staff", {"query": 123})   # wrong type
        run_eval.tool_bridge.dispatch("made_up_tool", {})              # not registered
        return "answer", {"prompt_token_count": 100, "candidates_token_count": 20}

    _patch_pipeline(monkeypatch, model)
    case = {"id": "probe", "turns": [{"user": "hi", "expect_tools": ["search_staff"]}]}

    result = run_eval.execute_case(case, None, False, provider="openai", model="Qwen/Qwen3-8B",
                                   rep=2, out_dir=tmp_path)

    assert (result.status, result.outcome, result.fabricated, result.invalid_calls) == ("PASS", "completed", True, 2)
    events = _events(result.trajectory)
    assert [e["type"] for e in events] == [
        "run_start", "tool_call", "tool_validation_error", "tool_result",
        "tool_call", "tool_validation_error", "tool_result", "run_end",
    ]
    start, end = events[0], events[-1]
    assert (start["task_id"], start["backend"], start["model"], start["config"]) == (
        "probe", "openai", "Qwen/Qwen3-8B", {"rep": 2})
    assert end["outcome"] == "completed" and end["success"] is True
    assert (end["input_tokens"], end["output_tokens"], end["total_tokens"]) == (100, 20, 120)
    assert [e["rule"] for e in events if e["type"] == "tool_validation_error"] == ["wrong_type", "unknown_tool"]


def test_answer_violating_answer_excludes_is_a_fabrication(monkeypatch, tmp_path):
    _patch_pipeline(monkeypatch, lambda *a: ("It is 12:00", {}))
    case = {"id": "probe", "turns": [{"user": "hi", "answer_excludes": ["12:00"]}]}

    result = run_eval.execute_case(case, None, False, provider="openai", out_dir=tmp_path)

    assert (result.status, result.fabricated) == ("FAIL", True)


def test_rate_limit_writes_a_retry_event_and_error_case_ends_harness_error(monkeypatch, tmp_path):
    class RateLimited(Exception):
        code = 429

    attempts = []

    def model(*args):
        attempts.append(1)
        raise RateLimited("429 Too Many Requests")

    _patch_pipeline(monkeypatch, model)
    case = {"id": "probe", "turns": [{"user": "hi"}]}

    result = run_eval.execute_case(case, None, False, provider="openai", out_dir=tmp_path)

    assert (result.status, result.outcome, result.fabricated) == ("ERROR", "harness_error", False)
    events = _events(result.trajectory)
    retries = [e for e in events if e["type"] == "retry"]
    assert len(retries) == run_eval.MAX_TRANSIENT_ATTEMPTS - 1
    assert retries[0]["status"] == 429 and retries[0]["attempt"] == 1
    assert events[-1]["type"] == "run_end" and events[-1]["graded_ok"] is False


def test_no_out_dir_writes_nothing_and_run_case_keeps_its_shape(monkeypatch):
    _patch_pipeline(monkeypatch, lambda *a: ("fine", {}))
    monkeypatch.setattr(run_eval.gemini, "call_gemini_api", lambda *a: ("fine", {}))

    assert run_eval.run_case({"id": "probe", "turns": [{"user": "hi"}]}, "key", False) == ("PASS", [])

def test_non_object_arguments_are_a_validation_error_not_a_harness_error(monkeypatch, tmp_path):
    def model(api_key, system_instruction, history):
        run_eval.tool_bridge.dispatch("search_staff", ["not", "an", "object"])
        return "answer", {}

    _patch_pipeline(monkeypatch, model)
    case = {"id": "probe", "turns": [{"user": "hi"}]}

    result = run_eval.execute_case(case, None, False, provider="openai", out_dir=tmp_path)

    assert (result.status, result.fabricated) == ("PASS", True)
    rules = [e["rule"] for e in _events(result.trajectory) if e["type"] == "tool_validation_error"]
    assert rules == ["wrong_type"]
