"""
Behavioural eval harness for DAU Buddy chat.

Runs the cases in cases.yaml through the real pipeline — the production system
prompt (via build_system_instruction), the real tool bridge, the real model —
and checks which tools were called and what came back.

    python -m evals.run_eval                    # everything
    python -m evals.run_eval --tag day-order    # one area
    python -m evals.run_eval --case free-room-now-uses-campus-time
    python -m evals.run_eval -v                 # print answers and tool calls

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
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import psycopg2
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, database
from core.schemas import ChatMessage
from api.services import gemini, tool_bridge

CASES_FILE = Path(__file__).parent / "cases.yaml"

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


class ToolRecorder:
    """
    Records (name, args) of every tool call, and every tool that failed for an
    environment reason (see ENVIRONMENT_ERRORS).

    Two patch points: tool_bridge.dispatch sees what the model asked for, and
    the MCP tool manager's call_tool sees the exception dispatch would
    otherwise turn into text.
    """

    def __init__(self):
        self.calls = []
        self.environment_failures = []
        self._real = tool_bridge.dispatch

    def __enter__(self):
        def recording_dispatch(name, arguments):
            self.calls.append((name, dict(arguments or {})))
            return self._real(name, arguments)

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


def _retry_delay(error: Exception):
    """
    Seconds to wait before retrying a transient API error, or None when the
    error is not transient. Transient means a per-minute rate limit (429) or
    model overload (503).
    Raises DailyQuotaExhausted for a per-day quota, which waiting cannot clear.
    """
    text = str(error)
    code = getattr(error, "code", None)
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


def _answer_turn(api_key: str, history: list) -> tuple[str, list]:
    """
    One user turn through the real pipeline, retrying transient API errors.
    Returns (answer, tool calls); a retried attempt's tool calls are discarded
    so assertions only see the attempt that produced the answer.
    """
    system_instruction = gemini.build_system_instruction()
    for attempt in range(1, MAX_TRANSIENT_ATTEMPTS + 1):
        with ToolRecorder() as recorder:
            try:
                answer, _usage = gemini.call_gemini_api(api_key, system_instruction, history)
            except Exception as e:
                delay = _retry_delay(e)
                if delay is None:
                    raise PipelineError(f"pipeline raised {e!r}") from e
            else:
                if recorder.environment_failures:
                    raise PipelineError(
                        "tool failed in the environment: "
                        + "; ".join(recorder.environment_failures)
                    )
                return answer, recorder.calls
        if attempt < MAX_TRANSIENT_ATTEMPTS:
            print(f"          transient API error; waiting {delay:.0f}s", flush=True)
            time.sleep(delay)
    raise PipelineError(f"API still unavailable after {MAX_TRANSIENT_ATTEMPTS} attempts")


def _args_match(actual: dict, expected: dict) -> bool:
    """Expected args are a subset check, compared case-insensitively as text."""
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
    for needle in turn.get("answer_excludes", []):
        if needle.lower() in low:
            failures.append(f"answer contains {needle!r}")
    for pattern in turn.get("answer_matches", []):
        if not re.search(pattern, answer, re.IGNORECASE):
            failures.append(f"answer does not match /{pattern}/")
    for pattern in turn.get("answer_not_matches", []):
        found = re.search(pattern, answer, re.IGNORECASE)
        if found:
            failures.append(f"answer matches /{pattern}/ at {found.group(0)!r}")
    return failures


def run_case(case: dict, api_key: str, verbose: bool) -> tuple[str, list]:
    """
    Returns (status, messages) where status is PASS, FAIL or ERROR.

    The database is checked before and after the case: services turn many
    database errors into answer text, so an outage during the case can surface
    only as a wrong answer, and a verdict reached with the database down says
    nothing about behaviour.
    """
    history: list[ChatMessage] = []
    failures = []

    down = _database_unreachable()
    if down:
        return "ERROR", [f"database unreachable before the case: {down}"]

    with _pin_clock(case.get("today")):
        for index, turn in enumerate(case["turns"], start=1):
            history.append(ChatMessage(sender="user", text=turn["user"]))
            try:
                answer, calls = _answer_turn(api_key, history)
            except DailyQuotaExhausted:
                raise
            except PipelineError as e:
                return "ERROR", [f"turn {index}: {e}"]
            history.append(ChatMessage(sender="ai", text=answer))

            if verbose:
                print(f"\n    > {turn['user']}")
                print(f"    tools: {[c[0] for c in calls] or 'none'}")
                for name, args in calls:
                    print(f"      {name}({args})")
                print(f"    < {answer.strip()[:600]}")

            failures += [f"turn {index}: {f}" for f in check_turn(turn, answer, calls)]

    down = _database_unreachable()
    if down:
        return "ERROR", [f"database unreachable after the case: {down}"]
    return ("FAIL" if failures else "PASS"), failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", help="only cases carrying this tag")
    parser.add_argument("--case", help="only this case id")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print every answer and tool call")
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set — this harness needs the live model.")
        return 2

    cases = yaml.safe_load(CASES_FILE.read_text())
    if args.tag:
        cases = [c for c in cases if args.tag in c.get("tags", [])]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    if not cases:
        print("No cases matched.")
        return 2

    print(f"Running {len(cases)} case(s)\n")
    results = {"PASS": [], "FAIL": [], "ERROR": []}
    for position, case in enumerate(cases):
        try:
            status, messages = run_case(case, api_key, args.verbose)
        except DailyQuotaExhausted as e:
            skipped = [c["id"] for c in cases[position:]]
            results["ERROR"] += skipped
            print(f"  STOP  {e}; {len(skipped)} case(s) not run")
            break
        results[status].append(case["id"])
        print(f"  {status:<5} {case['id']}", flush=True)
        for message in messages:
            print(f"          {message}")

    print(
        f"\n{len(results['PASS'])} passed, {len(results['FAIL'])} failed, "
        f"{len(results['ERROR'])} errored — {len(cases)} case(s)"
    )
    if results["FAIL"]:
        print("failed: " + ", ".join(results["FAIL"]))
    if results["ERROR"]:
        print("errored (environment, not behaviour): " + ", ".join(results["ERROR"]))
    if results["FAIL"]:
        return 1
    return 2 if results["ERROR"] else 0


if __name__ == "__main__":
    sys.exit(main())
