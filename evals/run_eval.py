"""
Behavioural eval harness for DAU Buddy chat.

Runs the cases in cases.yaml through the real pipeline — the production system
prompt (via build_system_instruction), the real tool bridge, the real model —
and checks which tools were called and what came back.

    python -m evals.run_eval                    # everything
    python -m evals.run_eval --tag day-order    # one area
    python -m evals.run_eval --case free-room-now-uses-campus-time
    python -m evals.run_eval -v                 # print answers and tool calls

Needs GEMINI_API_KEY and a reachable database: this exercises the live system,
so a failure here means a user would have seen it. Costs one model call per
turn — the full set is ~20 calls.

Deliberately NOT part of `make test`. pytest must stay fast, offline and free;
this is the slow, paid, occasionally flaky layer that answers a different
question — not "is the code correct" but "does the assistant behave".
"""
import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config
from core.schemas import ChatMessage
from api.services import gemini, tool_bridge

CASES_FILE = Path(__file__).parent / "cases.yaml"


class ToolRecorder:
    """Wraps tool_bridge.dispatch to record (name, args) of every tool call."""

    def __init__(self):
        self.calls = []
        self._real = tool_bridge.dispatch

    def __enter__(self):
        def recording_dispatch(name, arguments):
            self.calls.append((name, dict(arguments or {})))
            return self._real(name, arguments)

        self._patcher = patch.object(tool_bridge, "dispatch", recording_dispatch)
        self._patcher.start()
        # gemini.py holds its own reference to the module, so patching the
        # attribute is enough — but assert it, or a refactor silently blinds us.
        assert tool_bridge.dispatch is not self._real
        return self

    def __exit__(self, *exc):
        self._patcher.stop()
        return False


def _pin_clock(today: str):
    """Freeze campus_now() so 'tomorrow' means the same thing on every run."""
    if not today:
        return patch.object(config, "campus_now", config.campus_now)
    fmt = "%Y-%m-%d %H:%M" if " " in str(today) else "%Y-%m-%d"
    frozen = datetime.strptime(str(today), fmt).replace(tzinfo=config.CAMPUS_TZ)
    return patch.object(config, "campus_now", lambda: frozen)


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
    return failures


def run_case(case: dict, api_key: str, verbose: bool) -> tuple[bool, list]:
    history: list[ChatMessage] = []
    all_failures = []

    with _pin_clock(case.get("today")):
        for index, turn in enumerate(case["turns"], start=1):
            history.append(ChatMessage(sender="user", text=turn["user"]))
            with ToolRecorder() as recorder:
                system_instruction = gemini.build_system_instruction()
                try:
                    answer, _usage = gemini.call_gemini_api(
                        api_key, system_instruction, history
                    )
                except Exception as e:
                    all_failures.append(f"turn {index}: pipeline raised {e!r}")
                    break
            history.append(ChatMessage(sender="ai", text=answer))

            if verbose:
                print(f"\n    > {turn['user']}")
                print(f"    tools: {[c[0] for c in recorder.calls] or 'none'}")
                for name, args in recorder.calls:
                    print(f"      {name}({args})")
                print(f"    < {answer.strip()[:600]}")

            all_failures += [
                f"turn {index}: {f}" for f in check_turn(turn, answer, recorder.calls)
            ]

    return not all_failures, all_failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
    failed = []
    for case in cases:
        ok, failures = run_case(case, api_key, args.verbose)
        print(f"  {'PASS' if ok else 'FAIL'}  {case['id']}")
        for failure in failures:
            print(f"          {failure}")
        if not ok:
            failed.append(case["id"])

    print(f"\n{len(cases) - len(failed)}/{len(cases)} passed")
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
