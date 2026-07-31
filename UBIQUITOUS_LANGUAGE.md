# Ubiquitous Language

Domain vocabulary for the DAU Buddy MCP Server — an MCP platform giving AI assistants structured access to DAU (Dhirubhai Ambani University) institutional data.

## People

| Term        | Definition                                                                              | Aliases to avoid                     |
| ----------- | --------------------------------------------------------------------------------------- | ------------------------------------ |
| **Faculty** | An academic teaching/research member of DAU with a specialization and profile           | Professor, teacher, instructor       |
| **Staff**   | A non-teaching DAU employee with an administrative designation (e.g. electrician, coordinator) | Employee, admin, personnel     |
| **Scholar** | A Ph.D. student enrolled at DAU with a research area                                    | Doctoral scholar, Ph.D. student, researcher |
| **User**    | An authenticated person holding an API Key, identified by their DAU email               | Client, account                      |
| **Role**    | The access level assigned to a User at sign-in (Student, Faculty, Staff, or Admin)      | Permission, user type                |
| **Privileged Role** | A Role (Faculty, Staff, Admin) that sees unredacted contact details             | Elevated user, admin role            |

## Access & security

| Term           | Definition                                                                        | Aliases to avoid          |
| -------------- | --------------------------------------------------------------------------------- | ------------------------- |
| **API Key**    | A per-User bearer secret (`dau_sk_...`) stored hashed, with status and expiry     | Token, secret, credential |
| **Redaction**  | Stripping phone numbers and office addresses from directory results for non-privileged Roles | Filtering, masking, sanitization |
| **Rate Limit** | The per-key request ceiling enforced by the auth middleware                        | Throttle, quota           |

## Scheduling

| Term             | Definition                                                                        | Aliases to avoid            |
| ---------------- | --------------------------------------------------------------------------------- | --------------------------- |
| **Timetable**    | The weekly grid of teaching Slots for a Program and Semester                      | Schedule, routine           |
| **Slot**         | One timetabled interval on a day: a Course, Faculty, room, and start/end time     | Session, period, class hour |
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

- A **User** has exactly one **API Key** and exactly one **Role**.
- A **Program** has one **Timetable** per **Semester**; a **Timetable** is made of **Slots**.
- A **Slot** links one **Course**, one **Faculty**, and one room at one time; a **Free Slot** is derived, never stored.
- A **Document** belongs to one **Collection** and is split into many **Chunks**; search returns **Chunks**, citations point at their **Document** page.
- The **Curriculum** places each **Course** in a **Program** and **Semester**.
- **Sync** Tools and **Seeding** scripts both write datasets; only **Sync** is reachable through MCP, and neither is exposed to **Web Chat**.
- The **Tool Bridge** re-exposes every non-excluded MCP **Tool** to **Web Chat**, applying **Redaction** based on the caller's **Role**.

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
> **Domain expert:** "Their **Role** is Student, which isn't a **Privileged Role**, so **Redaction** strips phone and office from the directory result before it reaches the model."
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
- **"User" Role default** — `api_keys.role` defaults to `'User'`, but the documented Roles are Student, Faculty, Staff, and Admin. `'User'` as a role value is a fifth, undocumented state; the default should probably be `'Student'` or the docs should acknowledge it.
- **"Session"** — `session_type` in the timetable means Lecture/Lab/Tutorial (a property of a **Slot**), not an auth session or academic session (year). Prefer **Session Type** in full, never bare "session".
