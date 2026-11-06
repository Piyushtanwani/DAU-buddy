"""
Behavioural eval harness for DAU Buddy chat.

Runs the cases in cases.yaml through the real pipeline — the production system
prompt (via build_system_instruction), the real tool bridge, the real model —
and checks which tools were called and what came back.

    python -m evals.run_eval                    # everything
    python -m evals.run_eval --tag day-order    # one area
    python -m evals.run_eval --case free-room-now-uses-campus-time
    python -m evals.run_eval -v                 # print answers and tool calls
    python -m evals.run_eval --provider openai --model Qwen/Qwen3-8B --reps 3 --out runs/x
        # a local OpenAI-compatible model (LLM_BASE_URL), 3 repetitions, one
        # trajectory JSONL per case per repetition plus runs/x/summary.json

Needs GEMINI_API_KEY (read from .env or the environment) and a reachable
database: this exercises the live system, so a failure here means a user would
have seen it. Every model round-trip is a call — a turn that uses one tool
costs two — so the full set is roughly 40 calls.

Kept out of `make test`: pytest stays fast, offline and free, while this layer
is slow, paid and occasionally flaky, and answers "does the assistant behave"
where pytest answers "is the code correct".

Each case ends in one of three states:

    PASS   every assertion held
    FAIL   the assistant misbehaved — a regression candidate
    ERROR  the pipeline could not run (quota, network, database) — says
           nothing about behaviour; fix the environment and re-run

A per-minute rate limit (HTTP 429) is waited out using the delay the API asks
for, and a model overload (HTTP 503) after a fixed backoff, so a free-tier key
completes the run, only slowly. A per-day quota stops
the run, since waiting cannot clear it.
"""
import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import psycopg2
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, database
from core.schemas import ChatMessage
from api.services import gemini, openai_service, tool_bridge
from evals.trajectory import TrajectoryLogger, _make_run_id, validate_tool_arguments, ToolValidationError

CASES_FILE = Path(__file__).parent / "cases.yaml"

PROVIDERS = ("gemini", "openai")

# The canned replies the services return instead of a model answer. They are
# how the runner tells "the loop gave up" and "the model said nothing" apart
# from a real answer (api/services/gemini.py, api/services/openai_service.py).
TURN_LIMIT_PREFIX = "I wasn't able to pull all of that together"
EMPTY_ANSWER = "I checked the system, but there is no additional information to provide right now."

# Attempts per turn when the API reports a transient error. The free tier
# allows 5 requests a minute, and each wait is the API's own retry delay, so
# four covers a multi-call turn landing on a full window.
MAX_TRANSIENT_ATTEMPTS = 4

# Wait after a 503 overload, which carries no retry delay of its own.
OVERLOAD_BACKOFF_S = 30.0

# Causes that mean a tool could not run, as opposed to the model calling it
# badly. tool_bridge.dispatch turns every tool exception into text for the
# model, so the recorder reads the cause before that happens.
ENVIRONMENT_ERRORS = (psycopg2.Error, OSError, TimeoutError)


class PipelineError(Exception):
    """The pipeline could not produce an answer for reasons outside behaviour."""


class DailyQuotaExhausted(PipelineError):
    """A per-day quota was hit; every remaining case would error the same way."""


class _NullTrajectory:
    """Stands in for a TrajectoryLogger when no --out directory was given."""

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


class ToolRecorder:
    """
    Records (name, args) of every tool call, and every tool that failed for an
    environment reason (see ENVIRONMENT_ERRORS). When given a trajectory
    logger it also writes tool_call / tool_validation_error / tool_result
    events, and collects the calls whose arguments failed the tool's schema
    (or that named a tool that is not registered) in `invalid_calls`.

    Two patch points: tool_bridge.dispatch sees what the model asked for, and
    the MCP tool manager's call_tool sees the exception dispatch would
    otherwise turn into text.
    """

    def __init__(self, logger=None):
        self.calls = []
        self.environment_failures = []
        self.invalid_calls = []
        self._logger = logger or _NullTrajectory()
        self._schemas = {t["name"]: t["parameters"] for t in tool_bridge.list_tools()}
        self._real = tool_bridge.dispatch

    def _check_arguments(self, name, arguments):
        if name not in self._schemas:
            return ToolValidationError(
                rule="unknown_tool",
                message=f"tool is not registered: {name}",
            )
        return validate_tool_arguments(self._schemas[name], arguments)

    def __enter__(self):
        def recording_dispatch(name, arguments):
            # Keep the raw value: a non-object (e.g. a JSON list) must reach the
            # validator as a wrong_type error, not be coerced or crash here.
            args = {} if arguments is None else arguments
            self.calls.append((name, args))
            self._logger.tool_call(name, args)

            invalid = self._check_arguments(name, args)
            if invalid:
                self.invalid_calls.append((name, invalid))
                self._logger.tool_validation_error(
                    name, invalid.rule, invalid.message, args,
                    parameter=invalid.parameter,
                    expected_type=invalid.expected_type,
                    actual_type=invalid.actual_type,
                )

            started = time.monotonic()
            try:
                result = self._real(name, arguments)
            except Exception as e:
                self._logger.tool_result(name, None, repr(e), time.monotonic() - started)
                raise
            self._logger.tool_result(name, result, None, time.monotonic() - started)
            return result

        manager = tool_bridge._mcp()._tool_manager
        real_call_tool = manager.call_tool

        async def watching_call_tool(name, arguments, *args, **kwargs):
            try:
                return await real_call_tool(name, arguments, *args, **kwargs)
            except Exception as e:
                cause = e.__cause__ or e
                if isinstance(cause, ENVIRONMENT_ERRORS):
                    self.environment_failures.append(f"{name}: {cause!r}")
                raise

        self._patchers = [
            patch.object(tool_bridge, "dispatch", recording_dispatch),
            patch.object(manager, "call_tool", watching_call_tool),
        ]
        for patcher in self._patchers:
            patcher.start()
        # gemini.py holds its own reference to the module, so patching the
        # attribute is enough — but assert it, or a refactor silently blinds us.
        assert tool_bridge.dispatch is not self._real
        return self

    def __exit__(self, *exc):
        for patcher in reversed(self._patchers):
            patcher.stop()
        return False


def _database_unreachable():
    """None when the database answers SELECT 1, else a description of why not."""
    try:
        with database.db_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        return None
    except Exception as e:
        return repr(e)


def _pin_clock(today: str):
    """Freeze campus_now() so 'tomorrow' means the same thing on every run."""
    if not today:
        return patch.object(config, "campus_now", config.campus_now)
    fmt = "%Y-%m-%d %H:%M" if " " in str(today) else "%Y-%m-%d"
    frozen = datetime.strptime(str(today), fmt).replace(tzinfo=config.CAMPUS_TZ)
    return patch.object(config, "campus_now", lambda: frozen)


def _error_status(error: Exception):
    """HTTP status of an API error: Gemini's `code`, or the status of the
    response a `requests` error carries. None when it has neither."""
    code = getattr(error, "code", None)
    if code is None:
        code = getattr(getattr(error, "response", None), "status_code", None)
    return code


def _retry_delay(error: Exception):
    """
    Seconds to wait before retrying a transient API error, or None when the
    error is not transient. Transient means a per-minute rate limit (429) or
    model overload (503).
    Raises DailyQuotaExhausted for a per-day quota, which waiting cannot clear.
    """
    text = str(error)
    code = _error_status(error)
    if code == 503 or "503 UNAVAILABLE" in text:
        return OVERLOAD_BACKOFF_S
    if code != 429 and "RESOURCE_EXHAUSTED" not in text:
        return None
    if "PerDay" in text:
        raise DailyQuotaExhausted(
            "daily Gemini quota exhausted — re-run after it resets or use a paid key"
        )
    match = re.search(r"retry in ([\d.]+)s", text) or re.search(r"'retryDelay': '(\d+)s'", text)
    return float(match.group(1)) + 1 if match else 30.0


@dataclass
class CaseTrace:
    """What one case leaves behind besides its verdict: the trajectory logger
    plus the numbers the summary and run_end event need."""

    logger: object = field(default_factory=_NullTrajectory)
    provider: str = "gemini"
    invalid_calls: list = field(default_factory=list)   # (tool, ToolValidationError)
    usages: list = field(default_factory=list)          # one usage dict per model turn
    turn_latency_s: list = field(default_factory=list)  # diagnosis only, not the SLA latency


def _call_model(provider: str, api_key, system_instruction: str, history: list):
    if provider == "openai":
        return openai_service.call_openai_api(api_key, system_instruction, history)
    return gemini.call_gemini_api(api_key, system_instruction, history)


def _answer_turn(api_key: str, history: list, trace: CaseTrace | None = None) -> tuple[str, list]:
    """
    One user turn through the real pipeline, retrying transient API errors.
    Returns (answer, tool calls); a retried attempt's tool calls are discarded
    so assertions only see the attempt that produced the answer. `trace`, when
    given, collects the answering attempt's usage, latency and invalid calls.
    """
    trace = trace or CaseTrace()
    system_instruction = gemini.build_system_instruction()
    for attempt in range(1, MAX_TRANSIENT_ATTEMPTS + 1):
        started = time.monotonic()
        with ToolRecorder(trace.logger) as recorder:
            try:
                answer, usage = _call_model(trace.provider, api_key, system_instruction, history)
            except Exception as e:
                delay = _retry_delay(e)
                if delay is None:
                    raise PipelineError(f"pipeline raised {e!r}") from e
                failure = e
                attempt_duration = time.monotonic() - started
            else:
                if recorder.environment_failures:
                    raise PipelineError(
                        "tool failed in the environment: "
                        + "; ".join(recorder.environment_failures)
                    )
                trace.usages.append(usage or {})
                trace.turn_latency_s.append(time.monotonic() - started)
                trace.invalid_calls += recorder.invalid_calls
                return answer, recorder.calls
        if attempt < MAX_TRANSIENT_ATTEMPTS:
            trace.logger.retry(
                str(failure)[:300],
                status=_error_status(failure) or type(failure).__name__,
                attempt=attempt,
                max_attempts=MAX_TRANSIENT_ATTEMPTS,
                delay_s=delay,
                attempt_duration_s=attempt_duration,
            )
            print(f"          transient API error; waiting {delay:.0f}s", flush=True)
            time.sleep(delay)
    raise PipelineError(f"API still unavailable after {MAX_TRANSIENT_ATTEMPTS} attempts")


def _args_match(actual: dict, expected: dict) -> bool:
    """Expected args are a subset check, compared case-insensitively as text."""
    if not isinstance(actual, dict):
        return False
    for key, want in expected.items():
        if key not in actual:
            return False
        if str(actual[key]).strip().lower() != str(want).strip().lower():
            return False
    return True


def _tool_was_called(calls, spec) -> bool:
    name = spec["name"] if isinstance(spec, dict) else spec
    want_args = spec.get("args_include", {}) if isinstance(spec, dict) else {}
    return any(
        called_name == name and _args_match(called_args, want_args)
        for called_name, called_args in calls
    )


def _describe(spec) -> str:
    if not isinstance(spec, dict):
        return str(spec)
    args = spec.get("args_include")
    return f"{spec['name']}({args})" if args else spec["name"]


def check_turn(turn: dict, answer: str, calls: list) -> list:
    """Returns a list of failure strings; empty means the turn passed."""
    failures = []
    low = answer.lower()

    for spec in turn.get("expect_tools", []):
        if not _tool_was_called(calls, spec):
            failures.append(f"expected tool call {_describe(spec)}")
    for spec in turn.get("forbid_tools", []):
        if _tool_was_called(calls, spec):
            failures.append(f"forbidden tool call happened: {_describe(spec)}")
    for needle in turn.get("answer_contains", []):
        if needle.lower() not in low:
            failures.append(f"answer missing {needle!r}")
    failures += _exclude_violations(turn, answer)
    for pattern in turn.get("answer_matches", []):
        if not re.search(pattern, answer, re.IGNORECASE):
            failures.append(f"answer does not match /{pattern}/")
    failures += _not_match_violations(turn, answer)
    return failures


def _exclude_violations(turn: dict, answer: str) -> list:
    low = answer.lower()
    return [f"answer contains {needle!r}" for needle in turn.get("answer_excludes", [])
            if needle.lower() in low]


def _not_match_violations(turn: dict, answer: str) -> list:
    violations = []
    for pattern in turn.get("answer_not_matches", []):
        found = re.search(pattern, answer, re.IGNORECASE)
        if found:
            violations.append(f"answer matches /{pattern}/ at {found.group(0)!r}")
    return violations


def answer_is_fabricated(turn: dict, answer: str) -> bool:
    """An answer_excludes or answer_not_matches violation: the answer said
    something the case says it must never say."""
    return bool(_exclude_violations(turn, answer) or _not_match_violations(turn, answer))


def classify_outcome(case: dict, status: str, answers: list, any_tool_called: bool,
                     truncated: bool = False) -> str:
    """
    The trajectory outcome label for one case (see trajectory.RUN_OUTCOMES).

    Precedence: harness_error, turn_limit, empty_answer, truncated,
    non_attempt, completed. `truncated` is whatever the service reports about
    hitting its output-token limit; neither service reports it today.
    """
    if status == "ERROR":
        return "harness_error"
    if any(a.startswith(TURN_LIMIT_PREFIX) for a in answers):
        return "turn_limit"
    if any(a.strip() == EMPTY_ANSWER for a in answers):
        return "empty_answer"
    if truncated:
        return "truncated"
    expects_tools = any(turn.get("expect_tools") for turn in case["turns"])
    if expects_tools and not any_tool_called:
        return "non_attempt"
    return "completed"


@dataclass
class CaseResult:
    case_id: str
    rep: int
    status: str                 # PASS, FAIL or ERROR
    messages: list
    outcome: str
    fabricated: bool
    invalid_calls: int
    turn_latency_s: list
    trajectory: str | None = None


def summarize(results: list, *, provider: str, model: str, reps: int) -> dict:
    """
    summary.json contents, computed as the capability-floor README defines
    them. Per repetition: pass rate is PASS / (PASS + FAIL); fabrication rate
    is the share of scored (PASS or FAIL) cases that fabricated; ERROR cases
    are counted but never scored. The headline numbers are the mean over
    repetitions, skipping a repetition that scored no case.
    """
    runs = []
    for rep in sorted({r.rep for r in results}):
        rows = [r for r in results if r.rep == rep]
        scored = [r for r in rows if r.status in ("PASS", "FAIL")]
        passed = sum(r.status == "PASS" for r in scored)
        outcomes: dict = {}
        for r in rows:
            outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
        runs.append({
            "rep": rep,
            "pass": passed,
            "fail": len(scored) - passed,
            "error": len(rows) - len(scored),
            "pass_rate": passed / len(scored) if scored else None,
            "fabrication_rate": sum(r.fabricated for r in scored) / len(scored) if scored else None,
            "outcomes": outcomes,
            "cases": [
                {
                    "id": r.case_id, "status": r.status, "outcome": r.outcome,
                    "fabricated": r.fabricated, "invalid_calls": r.invalid_calls,
                    "turn_latency_s": [round(s, 3) for s in r.turn_latency_s],
                    "trajectory": r.trajectory,
                }
                for r in rows
            ],
        })

    def mean(key):
        values = [run[key] for run in runs if run[key] is not None]
        return sum(values) / len(values) if values else None

    return {
        "provider": provider,
        "model": model,
        "reps": reps,
        "pass_rate": mean("pass_rate"),
        "fabrication_rate": mean("fabrication_rate"),
        "error_count": sum(run["error"] for run in runs),
        "runs": runs,
    }


def _usage_totals(usages: list) -> dict:
    prompt = [u.get("prompt_token_count", 0) or 0 for u in usages]
    output = sum(u.get("candidates_token_count", 0) or 0 for u in usages)
    return {
        "input_tokens": sum(prompt),
        "output_tokens": output,
        "peak_input_tokens": max(prompt, default=0),
        "total_tokens": sum(prompt) + output,
        "completions": len(usages),
    }


def execute_case(case: dict, api_key, verbose: bool, *, provider: str = "gemini",
                 model: str = "", rep: int = 1, out_dir: Path | None = None) -> CaseResult:
    """
    Runs one case and returns its CaseResult; status is PASS, FAIL or ERROR.

    The database is checked before and after the case: services turn many
    database errors into answer text, so an outage during the case can surface
    only as a wrong answer, and a verdict reached with the database down says
    nothing about behaviour.

    With out_dir, writes one trajectory file: run_start before the first turn,
    run_end after the last (also when the case ends ERROR or the run stops).
    """
    logger = (
        TrajectoryLogger(out_dir, run_id=f"{case['id']}.rep{rep}.{_make_run_id()}")
        if out_dir else _NullTrajectory()
    )
    trace = CaseTrace(logger=logger, provider=provider)
    logger.run_start(case["id"], provider, model, {"rep": rep})
    started = time.monotonic()

    history: list[ChatMessage] = []
    answers: list[str] = []
    any_tool_called = False
    failures: list[str] = []
    fabricated = False
    status = "ERROR"
    messages: list[str] = []
    turns_run = 0

    try:
        down = _database_unreachable()
        if down:
            messages = [f"database unreachable before the case: {down}"]
        else:
            with _pin_clock(case.get("today")):
                for index, turn in enumerate(case["turns"], start=1):
                    history.append(ChatMessage(sender="user", text=turn["user"]))
                    try:
                        answer, calls = _answer_turn(api_key, history, trace)
                    except DailyQuotaExhausted:
                        raise
                    except PipelineError as e:
                        messages = [f"turn {index}: {e}"]
                        break
                    turns_run += 1
                    logger.next_turn()
                    history.append(ChatMessage(sender="ai", text=answer))
                    answers.append(answer)
                    any_tool_called = any_tool_called or bool(calls)
                    fabricated = fabricated or answer_is_fabricated(turn, answer)

                    if verbose:
                        print(f"\n    > {turn['user']}")
                        print(f"    tools: {[c[0] for c in calls] or 'none'}")
                        for name, args in calls:
                            print(f"      {name}({args})")
                        print(f"    < {answer.strip()[:600]}")

                    failures += [f"turn {index}: {f}" for f in check_turn(turn, answer, calls)]
                else:
                    down = _database_unreachable()
                    if down:
                        messages = [f"database unreachable after the case: {down}"]
                    else:
                        status = "FAIL" if failures else "PASS"
                        messages = failures
    except BaseException as e:
        # DailyQuotaExhausted, KeyboardInterrupt, a bug: still close the file.
        logger.run_end(False, f"run stopped: {e!r}", turns_run, time.monotonic() - started,
                       "harness_error", **_usage_totals(trace.usages), graded_ok=False)
        raise

    fabricated = fabricated or bool(trace.invalid_calls)
    outcome = classify_outcome(case, status, answers, any_tool_called)
    logger.run_end(
        status == "PASS",
        "; ".join(messages) or "all assertions held",
        turns_run,
        time.monotonic() - started,
        outcome,
        **_usage_totals(trace.usages),
        graded_ok=status != "ERROR",
    )
    return CaseResult(
        case_id=case["id"], rep=rep, status=status, messages=messages, outcome=outcome,
        fabricated=fabricated and status != "ERROR", invalid_calls=len(trace.invalid_calls),
        turn_latency_s=trace.turn_latency_s,
        trajectory=str(logger.path) if out_dir else None,
    )


def run_case(case: dict, api_key: str, verbose: bool) -> tuple[str, list]:
    """Returns (status, messages) where status is PASS, FAIL or ERROR."""
    result = execute_case(case, api_key, verbose)
    return result.status, result.messages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", help="only cases carrying this tag")
    parser.add_argument("--case", help="only this case id")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print every answer and tool call")
    parser.add_argument("--provider", choices=PROVIDERS, default="gemini",
                        help="gemini (default) or openai: the OpenAI-compatible endpoint "
                             "from LLM_BASE_URL / LLM_MODEL")
    parser.add_argument("--model", help="model name; overrides GEMINI_MODEL or LLM_MODEL")
    parser.add_argument("--reps", type=int, default=1, help="full passes over the selected cases")
    parser.add_argument("--out", type=Path,
                        help="directory for per-case trajectory JSONL files and summary.json")
    args = parser.parse_args()

    if args.reps < 1:
        print("--reps must be at least 1.")
        return 2

    if args.provider == "openai":
        if not openai_service.openai_configured():
            print("Set LLM_BASE_URL (or OPENAI_API_KEY) — --provider openai needs an endpoint.")
            return 2
        api_key = os.getenv("OPENAI_API_KEY") or None  # a local server needs no key
        if args.model:
            os.environ["LLM_MODEL"] = args.model
        model = openai_service.get_llm_model()
    else:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("GEMINI_API_KEY is not set — this harness needs the live model.")
            return 2
        if args.model:
            os.environ["GEMINI_MODEL"] = args.model
        model = config.get_gemini_model()

    cases = yaml.safe_load(CASES_FILE.read_text())
    if args.tag:
        cases = [c for c in cases if args.tag in c.get("tags", [])]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    if not cases:
        print("No cases matched.")
        return 2

    print(f"Running {len(cases)} case(s)\n" if args.reps == 1
          else f"Running {len(cases)} case(s) x {args.reps} repetitions\n")
    all_results: list[CaseResult] = []
    stopped = False
    for rep in range(1, args.reps + 1):
        if args.reps > 1:
            print(f"-- repetition {rep}/{args.reps}")
        for position, case in enumerate(cases):
            try:
                result = execute_case(case, api_key, args.verbose, provider=args.provider,
                                      model=model, rep=rep, out_dir=args.out)
            except DailyQuotaExhausted as e:
                # Cases that never ran are ERRORs, so error_count stays honest.
                pending = [(r, c) for r in range(rep, args.reps + 1)
                           for c in (cases[position:] if r == rep else cases)]
                for r, c in pending:
                    all_results.append(CaseResult(c["id"], r, "ERROR", [str(e)], "harness_error",
                                                  False, 0, []))
                print(f"  STOP  {e}; {len(pending)} case(s) not run")
                stopped = True
                break
            all_results.append(result)
            print(f"  {result.status:<5} {case['id']}", flush=True)
            for message in result.messages:
                print(f"          {message}")
        if stopped:
            break

    summary = summarize(all_results, provider=args.provider, model=model, reps=args.reps)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    for run in summary["runs"]:
        prefix = f"[rep {run['rep']}] " if args.reps > 1 else ""
        print(
            f"\n{prefix}{run['pass']} passed, {run['fail']} failed, "
            f"{run['error']} errored — {len(cases)} case(s)"
        )
        failed = [c["id"] for c in run["cases"] if c["status"] == "FAIL"]
        errored = [c["id"] for c in run["cases"] if c["status"] == "ERROR"]
        if failed:
            print("failed: " + ", ".join(failed))
        if errored:
            print("errored (environment, not behaviour): " + ", ".join(errored))
    if args.reps > 1 or args.out:
        def pct(x):
            return "n/a" if x is None else f"{x:.1%}"
        print(f"\nmean over {len(summary['runs'])} run(s): pass rate {pct(summary['pass_rate'])}, "
              f"fabrication rate {pct(summary['fabrication_rate'])}, "
              f"{summary['error_count']} ERROR")
    if args.out:
        print(f"summary: {args.out / 'summary.json'}")

    if any(r.status == "FAIL" for r in all_results):
        return 1
    return 2 if any(r.status == "ERROR" for r in all_results) else 0


if __name__ == "__main__":
    sys.exit(main())
