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
| `truncated` | the service reported hitting its output-token limit; neither service reports this, so no case gets the label |
| `harness_error` | the case ended `ERROR` |

Every tool call's arguments are checked against the tool's schema (array items
and `$ref` included). A call to an unregistered tool, or with arguments that
fail the schema, counts toward the fabrication rate, as does an
`answer_excludes` / `answer_not_matches` violation. Arguments that are not
valid JSON are logged as `malformed_json` and count too. A scalar the tool
coerces to the declared type (`"5"` or `5.0` for an integer) is logged as
`coercible_type` and counted per case as `coercible_calls`, not as a
fabrication.

`run_end` token totals cover each user turn as the service reports it: OpenAI
sums the whole tool loop, Gemini reports the final response only. Totals are
not comparable across providers, and `peak_input_tokens` / `completions` are
`null`.

`summary.json` holds, per repetition and as the mean over repetitions,
`pass_rate` (`PASS / (PASS + FAIL)`), `fabrication_rate` (share of scored cases
that fabricated) and the `ERROR` count. `ERROR` cases are never scored; re-run
them. Per-turn latency is recorded for diagnosis only — the SLA latency comes
from the 4-chat load test.

For diagnosis it also holds `tier_pass_rate` (where on the ladder a model
breaks), `mean_tool_calls` and `mean_total_tokens` per scored case (what a model
costs to run; Gemini reports tokens for the final response only, so its token
count is a floor).

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
  source: original               # or synthetic
  family: timetable              # tool family, for the coverage table
  kind: single                   # single | multi-step | no-tool | out-of-scope | ambiguous
  tags: [tier-1, day-order, timetable]
  today: 2026-08-06 10:00        # required: pins the clock, so "tomorrow" is fixed
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
| `answer_contains_any` | list of lists; each inner list needs at least one of its substrings |
| `answer_contains_any` | list of lists; each inner list needs at least one of its substrings |
| `answer_contains_any` | list of lists; each inner list needs at least one of its substrings |
| `answer_contains_any` | list of lists; each inner list needs at least one of its substrings |
| `answer_matches` | regex, case-insensitive |
| `answer_not_matches` | regex that must not match, case-insensitive; `\b` word boundaries catch a word at the start of the answer or next to punctuation |

Trajectory assertions for multi-call behaviour:

| Key | Checks |
|---|---|
| `expect_no_tools` | no tool was called this turn |
| `min_tool_calls` / `max_tool_calls` | how many calls the turn made |
| `tool_order` | these tools were called in this order; other calls may sit between them |
| `args_from_results` | `[{tool, arg}]`: that argument's value appears in an earlier tool result, so the model read the id instead of inventing it |

## Tiers

Every case is tagged `tier-N`, the number of tool calls its hardest turn needs:
`tier-0` no tool, `tier-1` one lookup, `tier-2` two calls, `tier-3` three,
`tier-4` four. Tags `chain` (a later call needs an earlier result) and
`parallel` (independent calls in one message) separate the two ways a model can
need several calls. Run one tier with `--tag tier-3`; a model that passes tier-1
and fails tier-3 is the "needs fine-tuning" signal.

`source: original` cases were written against shipped bugs. `source: synthetic`
cases were written from the tool schemas and the system prompt and have not been
run against the database yet: run them with Gemini first and read every failure
before trusting the expectation. Every case, whatever its source, must be
excluded from the fine-tuning corpus, or a fine-tuned model is scored on
questions it trained on.

## Coverage

Case counts per tool family × kind, generated by `python -m evals.coverage`.
`make test` fails when this table is stale or a row is empty. `general` holds
what no tool family owns: greetings, injection, out-of-scope requests and the
assistant itself. Venue-booking questions are `venues`; schedules, free time,
courses and programs are `timetable`.

<!-- coverage:start -->
| Family | single | multi-step | no-tool | out-of-scope | ambiguous | Total |
|---|---:|---:|---:|---:|---:|---:|
| faculty | 13 | 6 | 0 | 1 | 0 | 20 |
| staff | 4 | 3 | 0 | 1 | 0 | 8 |
| scholars | 1 | 2 | 0 | 0 | 0 | 3 |
| library | 3 | 5 | 0 | 0 | 1 | 9 |
| timetable | 20 | 8 | 0 | 0 | 3 | 31 |
| calendar | 9 | 3 | 0 | 0 | 0 | 12 |
| documents | 3 | 1 | 0 | 0 | 0 | 4 |
| venues | 6 | 4 | 0 | 1 | 0 | 11 |
| general | 1 | 0 | 1 | 10 | 0 | 12 |
| **Total** | 60 | 32 | 1 | 13 | 4 | 110 |
<!-- coverage:end -->

**Contact details must come from a tool.** In every case the runner checks that each
email, phone number (8+ digits) and room code (`CEP-nnn`, `LT-n`, `LABnnn`) in the
answer appears in the user's messages or in a tool result so far. A value that does
not is counted as a fabrication, whether or not the case forbids it. Dates, times and
counts are not checked this way.

**Contact details must come from a tool.** In every case the runner checks that each
email, phone number (8+ digits) and room code (`CEP-nnn`, `LT-n`, `LABnnn`) in the
answer appears in the user's messages or in a tool result so far. A value that does
not is counted as a fabrication, whether or not the case forbids it. Dates, times and
counts are not checked this way.

**Contact details must come from a tool.** In every case the runner checks that each
email, phone number (8+ digits) and room code (`CEP-nnn`, `LT-n`, `LABnnn`) in the
answer appears in the user's messages or in a tool result so far. A value that does
not is counted as a fabrication, whether or not the case forbids it. Dates, times and
counts are not checked this way.

**Contact details must come from a tool.** In every case the runner checks that each
email, phone number (8+ digits) and room code (`CEP-nnn`, `LT-n`, `LABnnn`) in the
answer appears in the user's messages or in a tool result so far. A value that does
not is counted as a fabrication, whether or not the case forbids it. Dates, times and
counts are not checked this way.

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
- Latency: per-turn timings are recorded for diagnosis only. The SLA latency
  comes from the 4-chat load test.
- Cost: token totals are partial for Gemini (final response only).
- The provider fallback order: `--provider` drives one service directly.
- The model is nondeterministic. A single failure is a signal to look, not proof
  of a regression — re-run the case before you go hunting.

## Suite v1.1 (tester review)

v1 had three gaps: answers were rarely checked against the data, fabrication was only
caught by patterns written per case, and every question read like a developer wrote
it. v1.1 adds 41 cases (tag `added-v1.1`) and changes four things:

- Facts from the eval database are asserted in answers (emails, phone numbers,
  capacities, holiday and exam dates, instructors, rooms), so a wrong or invented
  value fails the case.
- The grounded-contact-details check above runs in every case.
- Phrasing varies: typos, Romanised Hindi, shorthand, all caps, long polite messages,
  corrections and follow-ups.
- Honesty traps for information the data does not hold (salary, home address, unknown
  room or book, student records), plus more safety and out-of-scope cases.

One v1 case named a professor who is not in the database; it now uses one who is.
Expected facts were checked against `daiict_db-2026-10-27.dump`; if the eval
database changes, re-check them.

## Suite v1.1 (tester review)

v1 had three gaps: answers were rarely checked against the data, fabrication was only
caught by patterns written per case, and every question read like a developer wrote
it. v1.1 adds 41 cases (tag `added-v1.1`) and changes four things:

- Facts from the eval database are asserted in answers (emails, phone numbers,
  capacities, holiday and exam dates, instructors, rooms), so a wrong or invented
  value fails the case.
- The grounded-contact-details check above runs in every case.
- Phrasing varies: typos, Romanised Hindi, shorthand, all caps, long polite messages,
  corrections and follow-ups.
- Honesty traps for information the data does not hold (salary, home address, unknown
  room or book, student records), plus more safety and out-of-scope cases.

One v1 case named a professor who is not in the database; it now uses one who is.
Expected facts were checked against `daiict_db-2026-10-27.dump`; if the eval
database changes, re-check them.

## Suite v1.1 (tester review)

v1 had three gaps: answers were rarely checked against the data, fabrication was only
caught by patterns written per case, and every question read like a developer wrote
it. v1.1 adds 41 cases (tag `added-v1.1`) and changes four things:

- Facts from the eval database are asserted in answers (emails, phone numbers,
  capacities, holiday and exam dates, instructors, rooms), so a wrong or invented
  value fails the case.
- The grounded-contact-details check above runs in every case.
- Phrasing varies: typos, Romanised Hindi, shorthand, all caps, long polite messages,
  corrections and follow-ups.
- Honesty traps for information the data does not hold (salary, home address, unknown
  room or book, student records), plus more safety and out-of-scope cases.

One v1 case named a professor who is not in the database; it now uses one who is.
Expected facts were checked against `daiict_db-2026-10-27.dump`; if the eval
database changes, re-check them.

## Suite v1.1 (tester review)

v1 had three gaps: answers were rarely checked against the data, fabrication was only
caught by patterns written per case, and every question read like a developer wrote
it. v1.1 adds 40 cases (tag `added-v1.1`) and changes four things:

- Facts from the eval database are asserted in answers (emails, phone numbers,
  capacities, holiday and exam dates, instructors, rooms), so a wrong or invented
  value fails the case.
- The grounded-contact-details check above runs in every case.
- Phrasing varies: typos, Romanised Hindi, shorthand, all caps, long polite messages,
  corrections and follow-ups.
- Honesty traps for information the data does not hold (salary, home address, unknown
  room or book, student records), plus more safety and out-of-scope cases.

One v1 case named a professor who is not in the database; it now uses one who is.
Expected facts were checked against `daiict_db-2026-10-27.dump`; if the eval
database changes, re-check them.
