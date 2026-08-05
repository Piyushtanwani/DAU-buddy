# DAU Buddy MCP Server

A unified MCP platform providing AI assistants with structured access to DAU faculty, staff, library, timetable, academic calendar, and scholars data through PostgreSQL-backed retrieval services.

## Features

- **Faculty Tools**: List faculty, search by name or expertise, view full profiles, and trigger live website syncing.
- **Staff Tools**: List staff, search by name or designation, view full profiles, and trigger live website syncing.
- **Scholars Tools**: List Ph.D. scholars, search by name or research area, view detailed profiles, and synchronize directly with the official DAU directory.
- **Document Retrieval**: Full-text search across official DAU documents (like Academic Requirements). Automatically chunks PDFs and returns exact page citations.
- **Library OPAC Tools**: Instantly search the DAU library catalog (over 28,000 records) and retrieve detailed book metadata using PostgreSQL full-text search. Includes fallback links to the live OPAC.
- **Timetable Tools**: Query faculty schedules, course timings, free time slots, and full program batch timetables.
- **Calendar Tools**: Query academic calendar events, examination schedules, semester activities, and holidays synchronized from official DAU sources.
- **User Feedback System**: Built-in feedback form allowing users to submit bug reports, feature requests, and suggestions. Automatically sends beautifully formatted HTML emails to administrators asynchronously.
- **Maintainer Dashboard**: Dedicated analytics portal for monitoring API usage, rate limit metrics, and endpoint popularity via interactive charts.
- **Full-Text Search**: Powered by PostgreSQL tsvector, `websearch_to_tsquery`, and GIN indexes for fast, relevance-ranked retrieval across institutional datasets.
- **Web Chat Interface**: Built-in chat dashboard enabling users to query DAU Buddy directly from the browser using a RAG pipeline backed by Google Gemini or OpenAI.
- **Secure Authentication**: All endpoints (including the Feedback API and Chat API) are secured by an ASGI authentication middleware that verifies API keys and Google Credentials.
- **Role-Based Access**: Automatically assigns roles (Student, Faculty, Staff) based on your DAU email upon Google Sign-In.

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
  ┌──────┼──────────┬──────────┬──────────┬─────────┬─────────┐
  │      │          │          │          │         │         │         │
Faculty Staff   Library   Timetable  Calendar  Scholar   Feedback  Document
Service Service Service   Service    Service   Service   Service   Service
  │      │          │          │          │         │         │         │
  └──────────── PostgreSQL (Local) ───────────────────────────┘
```

## Tech Stack
- **Backend**: Python 3.10+, FastAPI, `mcp` (Model Context Protocol), `FastMCP`
- **AI Integrations**: Google Gemini (`google-generativeai`), OpenAI RAG pipeline
- **Database**: PostgreSQL (Local)
- **Frontend**: HTML5, Vanilla CSS3, JavaScript, Google Identity Services (OAuth 2.0)
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
│   ├── schemas.py              # Shared Pydantic models
│   └── email_service.py        # Asynchronous HTML email dispatch
│
├── data/                       # Seed data files
│
├── api/                        # HTTP Server & Dashboard
│   ├── main.py                 # FastAPI and FastMCP entry point
│   ├── routes/                 # FastAPI routers
│   │   └── chat.py             # Chat endpoint handling RAG strategy routing
│   ├── middleware/             # ASGI Middlewares
│   │   └── mcp_auth.py         # Bearer token validation for MCP
│   ├── auth.py                 # Core authentication and role resolution
│   ├── context.py              # Context variables for tracking user state
│   └── services/               # Database Business Logic layer
│       ├── gemini.py           # Gemini Tool calling and AI Integration
│       ├── openai_service.py   # OpenAI Fallback Integration
│       ├── tool_bridge.py      # Translates MCP tools for AI APIs
│       ├── faculty_service.py
│       ├── staff_service.py
│       ├── scholar_service.py
│       ├── library_service.py
│       ├── timetable_service.py
│       ├── calendar_service.py
│       └── document_service.py
│
├── frontend/                   # Web Dashboard UI
│   ├── index.html
│   └── app.js                  # Login and key management logic
│
├── scrapers/                   # Web scraping layer
│   ├── faculty_scraper.py
│   ├── staff_scraper.py
│   └── scholars_scraper.py
│
├── dau_mcp/                    # Model Context Protocol Servers
│   ├── unified_mcp_server.py   # Exposes ALL tools over FastMCP (Recommended)
│   ├── faculty_mcp_server.py
│   ├── staff_mcp_server.py
│   ├── library_mcp_server.py
│   ├── timetable_mcp_server.py
│   ├── calendar_mcp_server.py
│   ├── scholar_mcp_server.py
│   └── documents_mcp_server.py
│
├── scripts/                    # Operational one-shot scripts
│   ├── init_db.sql             # Database schema initialization
│   ├── setup_db.py             # Master database setup & seeder script
│   ├── seed_faculty.py
│   ├── seed_staff.py
│   ├── seed_library.py
│   ├── seed_timetable.py
│   ├── seed_calendar.py
│   ├── seed_scholars.py
│   └── seed_documents.py
│
├── tests/                      # Unit and integration tests
│
├── .env.example                # Template for .env
├── requirements.txt
├── Makefile                    # Make commands
└── Dockerfile                  # Docker containerization
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

Open `.env` and fill in your PostgreSQL connection details and SMTP configurations for the Feedback system:
```ini
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=daiict_db
DB_USER=postgres
DB_PASSWORD=your-postgresql-password

# AI Integrations (Web Chat)
GEMINI_API_KEY=your_gemini_api_key
OPENAI_API_KEY=your_openai_api_key

# Email Configuration (Feedback System)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_sender_email@gmail.com
SMTP_PASSWORD=your_app_password
FEEDBACK_RECIPIENT_EMAILS=admin1@domain.com,admin2@domain.com
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

2. **Master Automated Setup (Recommended):**
   Run `scripts/setup_db.py` to execute schema initialization (`init_db.sql`) and all seeder scripts in their required dependency order:
   ```bash
   python scripts/setup_db.py
   ```

   **Production / Live Server Deployment (e.g. `mcp.dau.ac.in`):**
   - Skip long-running operations (like re-indexing 28,000+ library catalog books or PDF scraping):
     ```bash
     python scripts/setup_db.py --skip-library --skip-documents
     ```
   - Update **only** timetable entries (e.g. after uploading a new timetable Excel):
     ```bash
     python scripts/setup_db.py --only timetable
     ```
   - Target a specific dataset seeder:
     ```bash
     python scripts/setup_db.py --only faculty
     python scripts/setup_db.py --only staff
     python scripts/setup_db.py --only calendar
     ```

3. **Manual / Individual Seeding (Optional):**
   ```bash
   psql -U postgres -d daiict_db -f scripts/init_db.sql
   python scripts/seed_faculty.py
   python scripts/seed_staff.py
   python scripts/seed_scholars.py
   python scripts/seed_library.py
   python scripts/seed_calendar.py
   python scripts/seed_timetable.py          
   python scripts/seed_documents.py
   ```

## Starting the Server & Dashboard

The MCP server runs over secure HTTP/SSE via FastAPI and includes a responsive web portal for managing your access. Start the backend server:

```bash
python -m uvicorn api.main:create_app --factory --host 127.0.0.1 --port 8001
```

Once running:
1. Open **[http://127.0.0.1:8001/](http://127.0.0.1:8001/)** in your browser.
2. Sign in securely using your DAU Google account.
3. The dashboard will automatically assign your role (Student, Faculty, or Staff) and generate your personal API key.
4. Use the 1-click copy feature to grab your ready-to-use configuration snippet.

---

## Editor Configurations

Copy the configurations directly from your web dashboard to ensure your API keys are correctly injected.

### 1. Claude Desktop (Stdio Proxy)

Claude Desktop requires a local `stdio` executable. By utilizing `npx mcp-remote`, we can securely bridge the local HTTP SSE server directly into Claude's memory without exposing local paths.

Add this to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "DAU Buddy": {
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

### 2. Cursor / Windsurf / OpenCode (Native HTTP/SSE)

Cursor, Windsurf, and OpenCode support direct SSE network connections. You only need to supply the connection URL, the explicit type flag, and your API key header:

```json
{
  "mcpServers": {
    "DAU Buddy": {
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

**Documents:**
- `search_academic_requirements(query)`, `list_academic_documents()`, `get_academic_document_pages(filename)`, `sync_academic_documents()`
*Example*: "What is the minimum CPI to graduate with a BTech in ICT?"

**Library:**
- `search_library_books(query, limit)`, `get_book_details(biblionumber)`
*Example*: "Find books on Artificial Intelligence."

**Timetables:**
- `get_faculty_location(faculty_name, day, time)`, `get_faculty_schedule(faculty_name, day)`, `find_faculty_free_time(faculty_name, day)`, `get_course_schedule(course_code, day)`, `list_programs()`, `get_program_timetable(program_name, day)`
*Example*: "When is Prof. Manish Khare free on Tuesday?"

**Calendar:**
- `get_next_holiday()`, `get_upcoming_holidays()`, `get_all_holidays()`, `get_midsem_dates()`, `get_endsem_dates()`, `get_next_academic_event()`, `search_calendar(query, semester)`
*Example*: "When are the mid-semester exams?"

---

## Database Statistics

The local PostgreSQL database is actively seeded with:

| Dataset | Record Count | Details |
|---------|--------------|---------|
| **Faculty Records** | ~116 | Includes expertise & contact information |
| **Staff Records** | ~92 | Includes administrative designations |
| **Scholars Records**| ~60 | Ph.D. scholars and research areas |
| **Academic Documents** | ~15 | Multi-page PDFs (chunked & indexed) |
| **Library Catalog** | 28,000+ | Books searchable via OPAC |
| **Timetable Slots** | 1,200+ | Daily Lectures, Labs, and Tutorials |
| **Academic Calendar**| 120+ | Semester events and public holidays |
| **API Keys** | N/A | Securely managed via `init_db.sql` |

## Prerequisites
- Python 3.10+
- PostgreSQL
- Node.js (required for Claude Desktop configuration via npx)
