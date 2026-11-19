"""
Offline checks for the eval suite itself (evals/cases.yaml) and for the
trajectory assertions the suite relies on: expect_no_tools, min/max_tool_calls,
tool_order and args_from_results.
"""
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

from api.services import tool_bridge
from evals import coverage, run_eval

CASES = yaml.safe_load(run_eval.CASES_FILE.read_text(encoding="utf-8"))
TOOLS = {t["name"]: t["parameters"] for t in tool_bridge.list_tools()}
README = Path(run_eval.CASES_FILE).parent / "README.md"

KNOWN_CASE_KEYS = {"id", "source", "family", "kind", "tags", "today", "why", "turns"}
KNOWN_TURN_KEYS = {
    "user", "expect_tools", "forbid_tools", "expect_no_tools", "min_tool_calls",
    "max_tool_calls", "tool_order", "args_from_results", "answer_contains",
    "answer_contains_any", "answer_excludes", "answer_matches", "answer_not_matches",
}
TIER_RE = re.compile(r"^tier-(\d)$")


def _tier(case) -> int:
    tiers = [int(m.group(1)) for t in case["tags"] if (m := TIER_RE.match(t))]
    assert len(tiers) == 1, f"{case['id']} needs exactly one tier-N tag"
    return tiers[0]


def _spec_name(spec) -> str:
    return spec["name"] if isinstance(spec, dict) else spec


# ---------------------------------------------------------------------------
# The suite's shape
# ---------------------------------------------------------------------------

def test_suite_size_and_unique_ids():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), f"duplicate ids: {[i for i, n in Counter(ids).items() if n > 1]}"
    assert 55 <= len(CASES) <= 130


def test_every_case_has_a_why_a_source_and_exactly_one_tier():
    for case in CASES:
        assert set(case) <= KNOWN_CASE_KEYS, f"{case['id']}: {set(case) - KNOWN_CASE_KEYS}"
        assert case.get("why", "").strip(), f"{case['id']} has no why"
        assert case.get("source") in {"original", "synthetic"}, f"{case['id']} has no source"
        _tier(case)


def test_every_case_pins_today():
    """An unpinned case answers "tomorrow" differently on every run day."""
    for case in CASES:
        today = str(case.get("today", ""))
        assert today, f"{case['id']} has no today"
        datetime.strptime(today, "%Y-%m-%d %H:%M" if " " in today else "%Y-%m-%d")


def test_family_and_kind_are_valid_and_agree_with_the_case():
    for case in CASES:
        family, kind = case.get("family"), case.get("kind")
        assert family in coverage.FAMILIES, f"{case['id']}: family {family!r}"
        assert kind in coverage.KINDS, f"{case['id']}: kind {kind!r}"

        expected = set()
        for turn in case["turns"]:
            expected |= {_spec_name(s) for s in turn.get("expect_tools", [])} | set(turn.get("tool_order", []))
        if expected:
            families = {coverage.TOOL_FAMILY[name] for name in expected}
            assert family in families, f"{case['id']} is {family} but its tools are {sorted(families)}"

        tier = _tier(case)
        if tier >= 2 or "multi-turn" in case["tags"]:
            assert kind == "multi-step", f"{case['id']} needs several calls but is {kind}"
        if kind == "multi-step":
            assert tier >= 2 or "multi-turn" in case["tags"], case["id"]
        if kind in ("no-tool", "out-of-scope"):
            assert tier == 0, f"{case['id']} is {kind} but tier-{tier}"


def test_every_chat_tool_has_a_family():
    assert set(TOOLS) <= set(coverage.TOOL_FAMILY), sorted(set(TOOLS) - set(coverage.TOOL_FAMILY))


def test_coverage_table_has_no_empty_row_and_matches_the_readme():
    table = coverage.coverage_table(CASES)
    for line in table.splitlines()[2:-1]:
        family, *cells = [c.strip() for c in line.strip("|").split("|")]
        assert int(cells[-1]) > 0, f"coverage row {family} is empty"
    readme = README.read_text(encoding="utf-8")
    section = re.search(r"<!-- coverage:start -->\n(.*?)\n<!-- coverage:end -->", readme, re.S)
    assert section, "evals/README.md has no coverage section"
    assert section.group(1).strip() == table, "coverage table is stale: run `python -m evals.coverage`"


def test_turns_use_only_known_assertion_keys():
    for case in CASES:
        for turn in case["turns"]:
            assert set(turn) <= KNOWN_TURN_KEYS, f"{case['id']}: {set(turn) - KNOWN_TURN_KEYS}"


def test_every_tool_the_suite_names_is_registered_and_its_args_exist():
    for case in CASES:
        for turn in case["turns"]:
            specs = turn.get("expect_tools", []) + turn.get("forbid_tools", [])
            names = [_spec_name(s) for s in specs] + turn.get("tool_order", [])
            names += [s["tool"] for s in turn.get("args_from_results", [])]
            for name in names:
                assert name in TOOLS, f"{case['id']}: unknown tool {name}"
            for spec in specs:
                if isinstance(spec, dict):
                    for arg in spec.get("args_include", {}):
                        assert arg in TOOLS[spec["name"]]["properties"], f"{case['id']}: {spec['name']} has no {arg}"
            for spec in turn.get("args_from_results", []):
                assert spec["arg"] in TOOLS[spec["tool"]]["properties"], f"{case['id']}: {spec}"


def test_tier_tag_matches_what_the_case_demands():
    """tier-N means some turn needs N calls; tier-0 means no turn needs any."""
    for case in CASES:
        tier = _tier(case)
        needed = max(
            max(turn.get("min_tool_calls", 0), len({_spec_name(s) for s in turn.get("expect_tools", [])}))
            for turn in case["turns"]
        )
        if tier >= 2:
            assert needed >= tier, f"{case['id']} is tier-{tier} but demands only {needed} calls"
        if tier == 0:
            assert needed == 0, f"{case['id']} is tier-0 but demands tools"


def test_the_ladder_has_depth():
    tiers = Counter(_tier(c) for c in CASES)
    assert tiers[0] >= 6 and tiers[1] >= 15
    assert tiers[2] >= 8 and tiers[3] >= 4 and tiers[4] >= 3


def test_chain_cases_check_order_or_grounding():
    for case in CASES:
        if "chain" in case["tags"] and _tier(case) >= 2:
            turns = case["turns"]
            assert any(t.get("tool_order") or t.get("args_from_results") or t.get("min_tool_calls")
                       or len(t.get("expect_tools", [])) >= 2 for t in turns), case["id"]


def test_regexes_in_the_suite_compile():
    for case in CASES:
        for turn in case["turns"]:
            for pattern in turn.get("answer_matches", []) + turn.get("answer_not_matches", []):
                re.compile(pattern)


def test_the_suite_exercises_most_of_the_tool_surface():
    used = set()
    for case in CASES:
        for turn in case["turns"]:
            used |= {_spec_name(s) for s in turn.get("expect_tools", [])} | set(turn.get("tool_order", []))
    assert len(used) >= 30, f"only {len(used)} of {len(TOOLS)} tools are exercised: missing {sorted(set(TOOLS) - used)}"


# ---------------------------------------------------------------------------
# The assertions themselves
# ---------------------------------------------------------------------------

def test_expect_no_tools():
    assert not run_eval.check_turn({"expect_no_tools": True}, "hello", [])
    assert run_eval.check_turn({"expect_no_tools": True}, "hello", [("list_faculty", {})])


def test_min_and_max_tool_calls():
    calls = [("a", {}), ("b", {})]
    assert not run_eval.check_turn({"min_tool_calls": 2, "max_tool_calls": 2}, "x", calls)
    assert run_eval.check_turn({"min_tool_calls": 3}, "x", calls)
    assert run_eval.check_turn({"max_tool_calls": 1}, "x", calls)


def test_tool_order_is_a_subsequence_not_an_exact_match():
    calls = [("list_programs", {}), ("get_creators_info", {}), ("get_program_timetable", {})]
    assert not run_eval.check_turn({"tool_order": ["list_programs", "get_program_timetable"]}, "x", calls)
    assert run_eval.check_turn({"tool_order": ["get_program_timetable", "list_programs"]}, "x", calls)
    assert run_eval.check_turn({"tool_order": ["list_programs", "search_staff"]}, "x", calls)


SEARCH_RESULT = '{"results": [{"biblionumber": "4711", "title": "Algorithms"}]}'
GROUNDED = {"args_from_results": [{"tool": "get_book_details", "arg": "biblionumber"}]}


def test_a_biblionumber_read_from_the_search_result_is_grounded():
    calls = [("search_library_books", {"query": "x"}), ("get_book_details", {"biblionumber": "4711"})]
    assert not run_eval.check_turn(GROUNDED, "x", calls, [SEARCH_RESULT, "{}"])


def test_an_invented_biblionumber_fails_the_case():
    calls = [("search_library_books", {"query": "x"}), ("get_book_details", {"biblionumber": "99999"})]
    failures = run_eval.check_turn(GROUNDED, "x", calls, [SEARCH_RESULT, "{}"])
    assert failures and "99999" in failures[0]


def test_grounding_ignores_hyphens_and_spaces_the_tools_also_ignore():
    spec = {"args_from_results": [{"tool": "get_venue_schedule", "arg": "venue"}]}
    calls = [("search_venues", {"min_capacity": 120}), ("get_venue_schedule", {"venue": "CEP209"})]
    assert not run_eval.check_turn(spec, "x", calls, ["- CEP-209: Capacity 150", "{}"])


def test_summary_reports_pass_rate_per_tier_and_resource_use():
    def row(tier, status, calls):
        return run_eval.CaseResult("c", 1, status, [], "completed", False, 0, [],
                                   tool_calls=calls, total_tokens=100 * calls, tier=tier)

    summary = run_eval.summarize(
        [row(1, "PASS", 1), row(1, "PASS", 1), row(3, "FAIL", 1), row(3, "PASS", 3)],
        provider="openai", model="m", reps=1,
    )
    assert summary["tier_pass_rate"] == {"1": 1.0, "3": 0.5}
    assert summary["mean_tool_calls"] == 1.5
    assert summary["mean_total_tokens"] == 150


def test_an_id_that_only_appears_in_a_later_result_is_not_grounded():
    calls = [("get_book_details", {"biblionumber": "4711"}), ("search_library_books", {"query": "x"})]
    assert run_eval.check_turn(GROUNDED, "x", calls, ["{}", SEARCH_RESULT])


def test_a_missing_or_non_object_argument_is_reported_not_raised():
    assert run_eval.check_turn(GROUNDED, "x", [("get_book_details", {})], ["{}"])
    assert run_eval.check_turn(GROUNDED, "x", [("get_book_details", ["4711"])], ["{}"])


def test_grounding_is_skipped_without_results():
    calls = [("get_book_details", {"biblionumber": "99999"})]
    assert not run_eval.check_turn(GROUNDED, "x", calls)


def test_a_chain_case_end_to_end_with_a_fake_model(monkeypatch, tmp_path):
    """The real case from cases.yaml, driven by a model that does the right thing."""
    case = next(c for c in CASES if c["id"] == "syn-chain-book-availability")

    def model(api_key, system_instruction, history):
        run_eval.tool_bridge.dispatch("search_library_books", {"query": "Introduction to Algorithms"})
        run_eval.tool_bridge.dispatch("get_book_details", {"biblionumber": "4711"})
        return "One copy is available.", {}

    results = {"search_library_books": SEARCH_RESULT, "get_book_details": "{}"}
    monkeypatch.setattr(run_eval.gemini, "build_system_instruction", lambda: "")
    monkeypatch.setattr(run_eval.openai_service, "call_openai_api", model)
    monkeypatch.setattr(run_eval, "_database_unreachable", lambda: None)
    monkeypatch.setattr(run_eval.tool_bridge, "dispatch", lambda name, args: results[name])

    assert run_eval.execute_case(case, None, False, provider="openai").status == "PASS"

    def lazy_model(api_key, system_instruction, history):
        run_eval.tool_bridge.dispatch("search_library_books", {"query": "x"})
        return "Probably available.", {}

    monkeypatch.setattr(run_eval.openai_service, "call_openai_api", lazy_model)
    result = run_eval.execute_case(case, None, False, provider="openai")
    assert result.status == "FAIL"
    assert any("expected tool order" in m for m in result.messages)
