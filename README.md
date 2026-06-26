# DAU Buddy MCP Server

A unified MCP platform providing AI assistants with structured access to DA-IICT faculty, staff, library, timetable, academic calendar, and scholars data through PostgreSQL-backed retrieval services.

## Features

- **Faculty Tools**: List faculty, search by name or expertise, view full profiles, and trigger live website syncing.
- **Staff Tools**: List staff, search by name or designation, view full profiles, and trigger live website syncing.
- **Scholars Tools**: List Ph.D. scholars, search by name or research area, view detailed profiles, and synchronize directly from the DA-IICT directory.
- **Library OPAC Tools**: Instantly search the DA-IICT library catalog (over 28,000 records) and retrieve detailed book metadata using PostgreSQL full-text search. Includes fallback links to the live OPAC.
- **Timetable Tools**: Query faculty schedules, course timings, free time slots, and full program batch timetables.
- **Calendar Tools**: Query academic calendar events, examination schedules, semester activities, and holidays synchronized from official DA-IICT sources.
- **Retrieval-Augmented Search**: Uses PostgreSQL Full-Text Search (TSVECTOR + GIN indexes) to efficiently retrieve relevant records before serving results.
- **Secure Authentication**: All endpoints are secured by an ASGI authentication middleware that verifies API keys stored in the database.
- **Role-Based Access**: Automatically assigns roles (Student, Faculty, Staff) based on your DA-IICT email upon Google Sign-In.

## Architecture

```text
Claude / Cursor
        │
        ▼
   Auth Middleware (Bearer Token)
        │
        ▼
   FastMCP SSE Application
        │
 ┌──────┼──────────┬──────────┬──────────┬─────────┐
 │      │          │          │          │         │
Faculty Staff   Library   Timetable  Calendar   Scholar
Service Service Service   Service    Service    Service
 │      │          │          │          │         │
 └──────────── PostgreSQL (Local) ─────────────────┘
```

## Tech Stack
- **Language**: Python 3.10+
- **Database**: PostgreSQL (Local)
- **Framework**: FastAPI, `mcp` (Model Context Protocol), `FastMCP`
- **Data Processing**: `pandas`, `BeautifulSoup4`, `pdfplumber`
- **Search**: PostgreSQL `tsvector` and GIN Indexes
- **Integration**: SSE (Server-Sent Events) over HTTP with dynamic Stdio bridging via `mcp-remote`.

## Project Structure

```text
MCP Project/
│
├── core/                       # Shared infrastructure layer
│   ├── config.py               # Environment loading, logging factory
│   ├── database.py             # Thread-safe PostgreSQL connection pool
│   └── schemas.py              # Shared Pydantic models
│
├── data/                       # Seed data files
│
├── api/                        # HTTP Server & Dashboard
│   ├── main.py                 # FastAPI and FastMCP entry point
│   ├── middleware/             # ASGI Middlewares
│   │   └── mcp_auth.py         # Bearer token validation for MCP
│   └── services/               # Database Business Logic layer
│       ├── faculty_service.py
│       ├── staff_service.py
│       ├── scholar_service.py
│       ├── library_service.py
│       ├── timetable_service.py
│       └── calendar_service.py
│
├── frontend/                   # Web Dashboard UI
│   ├── index.html
│   └── app.js                  # Login and key management logic
│
├── scrapers/                   # Web scraping layer
│   ├── faculty_scraper.py
│   └── staff_scraper.py
│
├── dau_mcp/                    # Model Context Protocol Servers
│   ├── unified_mcp_server.py   # Exposes ALL tools over FastMCP (Recommended)
│   ├── faculty_mcp_server.py
│   ├── staff_mcp_server.py
│   ├── library_mcp_server.py
│   ├── timetable_mcp_server.py
│   ├── calendar_mcp_server.py
│   └── scholar_mcp_server.py
│
├── scripts/                    # Operational one-shot scripts
│   ├── init_db.sql             # Database schema initialization
│   ├── seed_faculty.py
│   ├── seed_staff.py
│   ├── seed_library.py
│   ├── seed_timetable.py
│   └── seed_calendar.py
│
├── tests/                      # Unit and integration tests
│
├── .env.example                # Template for .env
├── requirements.txt
├── Makefile                    # Make commands
├── Dockerfile                  # Docker containerization
└── migrate_rag.py              # RAG migration script
```

## Setup & Installation

### Prerequisites
Before you begin, ensure you have the following installed on your machine:
- **Python 3.10+** (For running the FastAPI and MCP server)
- **PostgreSQL** (For storing all retrieval data and user API keys)
- **Node.js / npm** (Required for the `npx mcp-remote` proxy bridge for Claude)

### 1. Configure Environment

First, create your environment variable file by copying the template:
```bash
cp .env.example .env
```

Open `.env` and fill in your PostgreSQL connection details. Make sure they match your local PostgreSQL credentials:
```ini
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=daiict_db
DB_USER=postgres
DB_PASSWORD=your-postgresql-password
```

### 2. Install Python Dependencies

It is highly recommended to use a virtual environment (`venv`) to avoid conflicting with your system Python packages.

**For Windows (PowerShell):**
```powershell
python -m venv win_venv
.\win_venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**For Mac/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Initialize & Seed Database

1. **Create the Database:**
   Open your local `psql` command line or a GUI like pgAdmin, and execute:
   ```sql
   CREATE DATABASE daiict_db;
   ```

2. **Run Initialization Scripts:**
   This sets up the required PostgreSQL schema (tables for faculty, staff, library, calendar, and api_keys):
   ```bash
   psql -U postgres -d daiict_db -f scripts/init_db.sql
   ```

3. **Seed the Data:**
   Run the individual Python scripts provided in the `scripts/` folder to populate your database with real data:
   ```bash
   python scripts/seed_faculty.py
   python scripts/seed_staff.py
   python scripts/seed_library.py
   python scripts/seed_timetable.py
   python scripts/seed_calendar.py
   ```
   *(Wait for each script to finish before starting the next one. The library seeding might take a moment since there are 28,000+ books).*

## Starting the Server & Dashboard

The MCP server runs over secure HTTP/SSE via FastAPI. Start the backend server to host the portal and authenticate MCP connections:

```bash
python -m uvicorn api.main:create_app --factory --host 127.0.0.1 --port 8001
```

Once running:
1. Open **[http://127.0.0.1:8001/](http://127.0.0.1:8001/)** in your browser.
2. Sign in with your DA-IICT Google account.
3. Your secure API key will automatically be generated and saved.

---

## Editor Configurations

Copy the configurations directly from your web dashboard to ensure your API keys are correctly injected.

### 1. Claude Desktop (Stdio Proxy)

Claude Desktop requires a local `stdio` executable. By utilizing `npx mcp-remote`, we can securely bridge the local HTTP SSE server directly into Claude's memory without exposing local paths.

Add this to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "daiict": {
      "command": "cmd",
      "args": [
        "/c",
        "npx",
        "-y",
        "mcp-remote",
        "http://127.0.0.1:8001/mcp/sse",
        "--allow-http",
        "--transport",
        "sse-only",
        "--header",
        "Authorization:${AUTH_HEADER}"
      ],
      "env": {
        "AUTH_HEADER": "Bearer dau_sk_YOUR_API_KEY_HERE"
      }
    }
  }
}
```

### 2. Cursor / Windsurf (Native HTTP/SSE)

Cursor and Windsurf support direct SSE network connections. You only need to supply the connection URL, the explicit type flag, and your API key header:

```json
{
  "mcpServers": {
    "daiict": {
      "type": "sse",
      "url": "http://127.0.0.1:8001/mcp/sse",
      "headers": {
        "Authorization": "Bearer dau_sk_YOUR_API_KEY_HERE"
      }
    }
  }
}
```

---

## Available Tools & Example Queries

**Faculty:**
- `list_faculty()`, `search_faculty(query)`, `get_faculty_details(name_or_email)`, `search_faculty_by_expertise(expertise)`, `sync_faculty_data()`
*Example*: "Who is the faculty expert in Machine Learning?"

**Staff:**
- `list_staff()`, `search_staff(query)`, `get_staff_details(name_or_email)`, `sync_staff_data()`
*Example*: "Who is the placement coordinator?"

**Scholars:**
- `list_scholars()`, `search_scholars(query)`, `get_scholar_details(name_or_email)`, `sync_scholar_data()`
*Example*: "Show me the research areas of Ph.D. scholars."

**Library:**
- `search_library_books(query, limit)`, `get_book_details(biblionumber)`
*Example*: "Find books on Artificial Intelligence."

**Timetables:**
- `get_faculty_location(faculty_name, day, time)`, `get_faculty_schedule(faculty_name, day)`, `find_faculty_free_time(faculty_name, day)`, `get_course_schedule(course_code, day)`, `list_programs()`, `get_program_timetable(program_name, day)`
*Example*: "When is Prof. Manish Khare free on Tuesday?"

**Calendar:**
- `get_next_holiday()`, `get_upcoming_holidays()`, `get_all_holidays()`, `get_midsem_dates()`, `get_endsem_dates()`, `get_next_academic_event()`, `search_calendar(query, semester)`
*Example*: "When are the mid-semester exams?"
