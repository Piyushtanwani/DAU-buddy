# Ubiquitous Language

Domain vocabulary for the DAU Buddy MCP Server — an MCP platform giving AI assistants structured access to DAU (Dhirubhai Ambani University) institutional data.

## People

| Term        | Definition                                                                              | Aliases to avoid                     |
| ----------- | --------------------------------------------------------------------------------------- | ------------------------------------ |
| **Faculty** | An academic teaching/research member of DAU with a specialization and profile           | Professor, teacher, instructor       |
| **Staff**   | A non-teaching DAU employee with an administrative designation (e.g. electrician, coordinator) | Employee, admin, personnel     |
| **Scholar** | A Ph.D. student enrolled at DAU with a research area                                    | Doctoral scholar, Ph.D. student, researcher |
| **User**    | An authenticated person, identified by their verified DAU email — via a Google credential (Web Chat) or an API Key (MCP clients) | Client, account, key holder |
| **Role**    | The access level derived from a User's email: Student, Faculty, Staff, Maintainer, or Student / Maintainer | Permission, user type |

## Access & security

| Term           | Definition                                                                        | Aliases to avoid          |
| -------------- | --------------------------------------------------------------------------------- | ------------------------- |
| **API Key**    | A bearer secret (`dau_sk_...`) stored hashed, with status and expiry. Optional: a User only needs one to reach the MCP surface | Token, secret, credential |
| **Credential** | The Google-issued ID token a Web Chat User signs in with; verified per request and restricted to `@dau.ac.in` / `@daiict.ac.in` | Token, login, session |
| **Rate Limit** | The per-User request ceiling, keyed on the verified email and falling back to client IP when a request is unauthenticated | Throttle, quota |

## Scheduling

| Term             | Definition                                                                        | Aliases to avoid            |
| ---------------- | --------------------------------------------------------------------------------- | --------------------------- |
| **Timetable**    | The weekly grid of teaching Slots for a Program and Semester                      | Schedule, routine           |
| **Slot**         | One timetabled interval on a day: a Course, **one** Faculty, room, and start/end time. A co-taught session is several Slots, one per instructor, so each name stays searchable | Session, period, class hour |
| **Short Name**   | A Faculty's initials as the timetable workbooks write them (`AC`); resolved at seeding time to the display form `Ankush Chander (AC)` so lecture and lab rows match one lookup | Abbreviation, code, initials |
| **Section Header** | A row in the lab workbook naming the program and semester the rows beneath it belong to (`BTech (ICT and CS) Core: SEMESTER III (2025 Batch)`); parsed to attribute Slots to one Program | Group header, title row |
| **Session Type** | The kind of Slot: Lecture, Lab, or Tutorial                                       | Class type, mode            |
| **Free Slot**    | A gap in a Faculty's day (08:00–18:00) computed by inverting their busy Slots     | Free time, availability     |
| **Program**      | A degree offering (e.g. BTech ICT) whose batches share a Timetable                | Course (never), degree, branch |
| **Course**       | A single taught subject with a course code, name, and Course Type                 | Subject, class, paper       |
| **Semester**     | One academic term; also the axis that positions Courses within a Program         | Term                        |

## Academic calendar

| Term               | Definition                                                                | Aliases to avoid          |
| ------------------ | ------------------------------------------------------------------------- | ------------------------- |
| **Academic Event** | A dated institutional activity in the academic calendar (exams, registration, convocation) | Calendar entry, activity |
| **Holiday**        | A dated non-working day, kept separately from Academic Events             | Off day, vacation         |
| **Midsem / Endsem**| The mid-semester and end-semester examination windows, found by searching Academic Events | Internals, finals |

## Documents & retrieval

| Term               | Definition                                                                     | Aliases to avoid              |
| ------------------ | ------------------------------------------------------------------------------ | ----------------------------- |
| **Document**       | An official DAU PDF (e.g. Academic Requirements) with a title, Program, effective year, and status | File, PDF, upload |
| **Chunk**          | A page-anchored slice of a Document, indexed for full-text search and cited by page number | Passage, segment, fragment |
| **Collection**     | A named grouping of Documents queried together (e.g. academic requirements)    | Category, folder              |
| **Curriculum**     | The structured mapping of Courses to Program and Semester, parsed from official sources | Syllabus, course list  |
| **Retrieval**      | Fetching the top-ranked relevant records via PostgreSQL full-text search instead of loading everything | Search (when ranked), RAG lookup |

## Library

| Term                 | Definition                                                          | Aliases to avoid       |
| -------------------- | -------------------------------------------------------------------- | ---------------------- |
| **Catalog**          | The searchable set of ~28,000 library book records mirrored from the DAU OPAC | Inventory, collection (reserved for Documents) |
| **OPAC**             | The live DAU Online Public Access Catalog, linked to as a fallback when local search misses | Library website |
| **Accession Number** | The library's unique identifier for a physical book copy             | Acc no, book ID        |

## Platform

| Term                    | Definition                                                                            | Aliases to avoid            |
| ----------------------- | -------------------------------------------------------------------------------------- | --------------------------- |
| **Tool**                | A callable capability exposed by the MCP server (e.g. `search_faculty`)                | Function, endpoint, API     |
| **Unified MCP Server**  | The single server exposing every domain's Tools; the recommended integration point     | Main server, combined server |
| **Tool Bridge**         | The layer that derives Web Chat (Gemini/OpenAI) tool declarations from the MCP registry so the two surfaces never drift | Adapter, wrapper |
| **Web Chat**            | The browser-based chat surface that reaches the same Tools through the Tool Bridge     | Chatbot, chat API           |
| **Fallback Engine**     | The rule-based intent router that answers directory queries when the LLM is unavailable | Offline mode, NLP engine   |
| **Sync**                | An on-demand re-scrape of the live DAU website that refreshes a dataset; exposed as MCP-only Tools | Refresh, update, seed (never) |
| **Seeding**             | One-shot operator scripts that populate the database from source files or scrapes      | Sync (never), import, load  |
| **Feedback**            | A user-submitted bug report, feature request, or suggestion, emailed to administrators | Report, ticket              |
| **User Dashboard**      | The sign-in portal where a User gets their Role and API Key                            | Portal, frontend            |
| **Maintainer Dashboard**| The analytics view of API usage, rate limits, and Tool popularity                      | Admin panel, analytics page |

## Relationships

- A **User** has exactly one **Role**, and *at most* one **API Key** — Web Chat Users authenticate with a **Credential** and may never hold a key.
- A **Program** has one **Timetable** per **Semester**; a **Timetable** is made of **Slots**.
- A **Slot** links one **Course**, one **Faculty**, and one room at one time; a **Free Slot** is derived, never stored.
- A **Short Name** identifies a **Faculty** inside the timetable workbooks only; it is resolved to the full display name before it reaches the database.
- A **Document** belongs to one **Collection** and is split into many **Chunks**; search returns **Chunks**, citations point at their **Document** page.
- The **Curriculum** places each **Course** in a **Program** and **Semester**.
- **Sync** Tools and **Seeding** scripts both write datasets; only **Sync** is reachable through MCP, and neither is exposed to **Web Chat**.
- The **Tool Bridge** re-exposes every non-excluded MCP **Tool** to **Web Chat** verbatim; it does not filter results by **Role**.

## Example dialogue

> **Dev:** "When a student asks 'when is Prof. Khare free?', do we ask the model to work out the gaps?"
>
> **Domain expert:** "No — **Free Slots** are computed server-side by inverting the busy **Slots** in the **Timetable**. The model only formats the result; free/busy inversion never happens inside a model."
>
> **Dev:** "And that same Tool works from **Web Chat**?"
>
> **Domain expert:** "Yes, through the **Tool Bridge** — it mirrors the **Unified MCP Server**'s registry, minus the **Sync** Tools, which are MCP-only because they mutate data."
>
> **Dev:** "If the student asks for the professor's phone number?"
>
> **Domain expert:** "They get it. The directory's numbers are institute switchboard extensions and the addresses are campus office rooms — the same data daiict.ac.in publishes. **Role** gates *mutating* Tools, not contact details."
>
> **Dev:** "One more — is a Ph.D. student a **Scholar** or a **User**?"
>
> **Domain expert:** "Both, but in different contexts. **Scholar** is a directory record we serve data *about*; **User** is whoever holds the **API Key** making the request. The same person could be each, but the concepts never mix."

## Flagged ambiguities

- **"Course" vs "Program"** — "course" is sometimes used colloquially for a degree ("the BTech course"). In this domain a **Course** is always a single subject (`course_code`); a degree is always a **Program**. Never use "course" for a Program.
- **"Collection"** — used both for a **Document** grouping (`documents.collection`) and colloquially for the library's books. Reserve **Collection** for Documents; the library's set of books is the **Catalog**.
- **"Sync" vs "Seeding"** — both populate the database, but **Sync** is a runtime, tool-triggered re-scrape while **Seeding** is an operator-run setup script. The distinction matters for security (Sync tools are excluded from Web Chat) — never use one word for the other.
- **"Dashboard"** — used for two different surfaces. Say **User Dashboard** (sign-in, key management) or **Maintainer Dashboard** (analytics); plain "dashboard" is ambiguous.
- **"Scholar"** — the database table is `doctoral_scholars` but tools and docs say "scholar". A **Scholar** always means a Ph.D. scholar; it never means a student or academic generally.
- **`biblionumber` vs Accession Number** — the `get_book_details(biblionumber)` tool parameter uses OPAC (Koha) terminology while the local table keys books by `acc_no` (**Accession Number**). Decide which identifier the tool actually accepts and name the parameter accordingly; today the mismatch invites wrong lookups.
- **`'Admin'` is a Role nothing assigns** — `faculty_mcp_server.py` and `staff_mcp_server.py` gate the Sync Tools on `("Staff", "Faculty", "Admin")`, but `resolve_role` only ever returns Student, Faculty, Staff, Maintainer, or Student / Maintainer. `'Admin'` is dead in the gate, and Maintainers are *not* in it — so a Maintainer cannot trigger a Sync. Settle the vocabulary in one place.
- **"Program" is not only programs** — `timetables.program` currently holds 21 distinct values including course categories (`General Elective (Technical)`, `Specialization Core`), raw **Section Headers** (`BTech Core: SEMESTER I (2026 Batch)`), four spellings of the same BTech branch, and 121 rows of `Unknown Program`. `list_programs` returns them verbatim, so the model is offered section headers as if a student could enrol in one. Tracked in issue #48; until it is settled, "Program" means different things in the glossary and in the column.
- **Faculty name: Short Name vs display name** — the lecture workbook writes `Ankush Chander (AC)` while the lab workbook writes `AC`. Storing both forms in `faculty_name` made every faculty lookup miss that person's labs, and joining co-instructors into one cell then made their own name ambiguous against the compound value. One Slot, one instructor, one display form — never a **Short Name** and never a joined string.
- **"Session"** — `session_type` in the timetable means Lecture/Lab/Tutorial (a property of a **Slot**), not an auth session or academic session (year). Prefer **Session Type** in full, never bare "session".

## Retired terms

Kept so that older code comments, commits and PRs remain readable.

- **Redaction** / **Privileged Role** — until 2026-08-03, directory Tool results had phone numbers and office addresses stripped for non-privileged Roles. Removed: the numbers are institute switchboard extensions (`079-6826xxxx`) and the addresses are campus office rooms, both already public at daiict.ac.in, so there was nothing to withhold. Role still gates **Sync** Tools. If either term reappears in a diff, it is probably a bad merge — `tests/test_chat_guardrails.py` asserts the machinery stays gone.
