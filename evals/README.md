# Behavioural evals

`pytest` answers "is the code correct". This answers a different question: **does
the assistant behave** — does it call the right tool, with the right arguments,
and say something true.

Those failures do not show up in unit tests. Every bug in `cases.yaml` marked
*"Shipped bug"* was live, passed the whole suite, and was found only because
somebody happened to ask the right follow-up question in chat.

## Running

```bash
make eval                            # all cases
python -m evals.run_eval --tag day-order
python -m evals.run_eval --case dated-schedule-uses-effective-day
python -m evals.run_eval -v          # print every answer and tool call
```

Needs `GEMINI_API_KEY` (read from `.env`, like the server) and a reachable
database — this drives the real pipeline, so a failure here is a failure a user
would have seen.

Every model round-trip is one call, so a turn that uses one tool costs two. The
full set is roughly 40 calls. A free-tier key allows 5 a minute; the runner
waits out each rate limit with the delay the API asks for, and each model
overload (503) with a 30-second backoff. A per-day quota stops the run, since
waiting cannot clear it — and the free tier's daily quota runs out partway
through the set, so a complete run needs a paid key.

`make test` checks that every tool named in `cases.yaml` is registered, so a
tool rename breaks the unit suite, not a paid eval run.

Run it before merging anything that touches the system prompt, the tool
signatures, or the calendar/timetable services. It stays out of `make test`:
the unit suite is fast, free and offline, and this layer is slow, paid, and can
wobble on phrasing.

## Scoring a run against the SLA

```bash
python -m evals.run_eval --provider openai --model Qwen/Qwen3-8B --reps 3 --out runs/x
```

| Flag | Meaning |
|---|---|
| `--provider gemini\|openai` | `openai` uses `LLM_BASE_URL` / `LLM_MODEL` (and `OPENAI_API_KEY` if set); default `gemini` |
| `--model` | model name; overrides `GEMINI_MODEL` / `LLM_MODEL` for this run |
| `--reps N` | full passes over the selected cases (default 1) |
| `--out DIR` | write trajectories and `summary.json` there |

Without `--out` nothing is written, and plain `make eval` behaves as before.

With `--out`, each case in each repetition gets
`<case>.rep<N>.<run id>.jsonl`, one JSON line per event: `run_start`,
`tool_call`, `tool_validation_error`, `tool_result` (with latency), `retry`,
`run_end`. The format is copied from Agent Anatomy (`evals/trajectory.py`).
`run_end.outcome` is one of:

| Outcome | Signal |
|---|---|
| `completed` | a final answer that is neither canned reply below |
| `non_attempt` | the case has `expect_tools` and no tool was called |
| `turn_limit` | the reply starts "I wasn't able to pull all of that together" |
| `empty_answer` | the reply is "I checked the system, but there is no additional information…" |
| `truncated` | reserved: neither service reports hitting its output-token limit yet |
| `harness_error` | the case ended `ERROR` |

Every tool call's arguments are checked against the tool's schema (array items
and `$ref` included). A call to an unregistered tool, or with arguments that
fail the schema, counts toward the fabrication rate, as does an
`answer_excludes` / `answer_not_matches` violation.

`summary.json` holds, per repetition and as the mean over repetitions,
`pass_rate` (`PASS / (PASS + FAIL)`), `fabrication_rate` (share of scored cases
that fabricated) and the `ERROR` count. `ERROR` cases are never scored; re-run
them. Per-turn latency is recorded for diagnosis only — the SLA latency comes
from the 4-chat load test.

## Reading a run

| Status | Meaning | Exit code |
|---|---|---|
| `PASS` | every assertion held | 0 when all pass |
| `FAIL` | the assistant misbehaved — a regression candidate | 1 if any case fails |
| `ERROR` | the pipeline could not run (quota, network, database); says nothing about behaviour | 2 if cases errored and none failed |

A case is `ERROR` when the model API fails, when a tool raises a database,
network or timeout error, or when the database does not answer `SELECT 1`
before or after the case. A tool that rejects the model's arguments is
behaviour, and the case's assertions decide it.

An answer of *"I checked the system, but there is no additional information to
provide right now."* is the pipeline's reply when the model returns neither
text nor a tool call. It counts as `FAIL`: the user saw it.

## Writing a case

```yaml
- id: dated-schedule-uses-effective-day
  tags: [day-order, timetable]
  today: 2026-08-06 10:00        # pins the clock, so "tomorrow" is fixed
  why: >
    Shipped bug. "Schedule tomorrow" returned Friday's classes even though the
    calendar reassigns 2026-08-07 to Tuesday.
  turns:
    - user: What is Prof V Sunitha's schedule tomorrow?
      expect_tools:
        - name: get_faculty_schedule
          args_include: {date: "2026-08-07"}
      forbid_tools:
        - name: get_faculty_schedule
          args_include: {day: "Friday"}
      answer_contains: ["Tuesday"]
      answer_excludes: ["12:00"]
```

Assertions, in the order you should reach for them:

| Key | Checks |
|---|---|
| `expect_tools` | a tool was called, optionally with `args_include` (subset match) |
| `forbid_tools` | a tool was **not** called with those arguments |
| `answer_contains` / `answer_excludes` | case-insensitive substrings |
| `answer_matches` | regex, case-insensitive |
| `answer_not_matches` | regex that must not match, case-insensitive; `\b` word boundaries catch a word at the start of the answer or next to punctuation |

**Prefer trajectory assertions to text assertions.** `get_faculty_schedule` being
called with `date=2026-08-07` is a fact; whether the reply says "Tuesday" or
"treated as Tuesday" is phrasing, and phrasing changes for innocent reasons. Use
text assertions for facts that must appear (an extension number, a room code)
and for things that must never appear (a leaked prompt section, a gendered
pronoun) — not for tone or structure.

Two more rules that keep this set worth running:

1. **Every case needs a `why`.** If you cannot name the bug it catches, you are
   testing that the model still phrases things the way it did last Tuesday.
2. **Add the case when you fix the bug**, in the same branch. A regression suite
   assembled later only contains the bugs somebody still remembered.

## Multi-turn cases

`turns` is a list, and each turn gets its own assertions. The model's real reply
is fed back as history, so a follow-up sees what actually happened, not a
scripted version of it. Useful for the conversations where the first answer looks
fine and only the follow-up reveals the bug — which is how the day-order bug
surfaced in the first place.

## What is not covered

- Every case runs against the live database, so a case can fail because the data
  changed rather than because the assistant regressed. Names and numbers in
  assertions are the fragile part; `68261641` is stable, a timetable slot in week
  three of term may not be.
- A database that drops and recovers inside one case can go unnoticed: many
  services turn a query error into answer text, and the check before and after
  the case both see a working database.
- Nothing here checks latency, cost, or the OpenAI fallback path.
- The model is nondeterministic. A single failure is a signal to look, not proof
  of a regression — re-run the case before you go hunting.
