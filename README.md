# DA-IICT Unified MCP Server

A unified MCP platform providing AI assistants with structured access to DA-IICT faculty, staff, library, timetable, and academic calendar data through PostgreSQL-backed retrieval services.

## Features

- **Faculty Tools**: List faculty, search by name or expertise, view full profiles, and trigger live website syncing.
- **Staff Tools**: List staff, search by name or designation, view full profiles, and trigger live website syncing.
- **Library OPAC Tools**: Instantly search the DA-IICT library catalog (over 28,000 records) and retrieve detailed book metadata using PostgreSQL full-text search. Includes fallback links to the live OPAC for physical availability checking.
- **Timetable Tools**: Query faculty schedules, course timings, free time slots, and full program batch timetables.
- **Calendar Tools**: Query academic calendar events, examination schedules, semester activities, and holidays synchronized from official DA-IICT sources.
- **Retrieval-Augmented Search**: Uses PostgreSQL Full-Text Search (TSVECTOR + GIN indexes) to efficiently retrieve relevant faculty, staff, library, and calendar records before serving results.

## Architecture

```text
Claude Desktop
        │
        ▼
DA-IICT Unified MCP Server
        │
 ┌──────┼──────────┬──────────┬──────────┐
 │      │          │          │          │
Faculty Staff   Library   Timetable  Calendar
Service Service Service   Service    Service
 │      │          │          │          │
 └──────────── PostgreSQL (Local) ───────────┘
```

## Tech Stack
- **Language**: Python 3.10+
- **Database**: PostgreSQL (Local)
- **Framework**: `mcp` (Model Context Protocol), `FastMCP`
- **Data Processing**: `pandas`, `BeautifulSoup4`, `pdfplumber`
- **Search**: PostgreSQL `tsvector` and GIN Indexes for Full-Text Search
- **Unified Server**: Exposes all tools over standard `stdio` transport for seamless integration with Claude Desktop.

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
│   ├── library_data.csv        # Extracted catalog for the library
│   ├── Lecture Data.xlsx       # Faculty lecture schedules
│   └── Lab Data.xlsx           # Faculty lab/tutorial schedules
│
├── api/services/               # Business Logic layer
│   ├── faculty_service.py      # Faculty DB queries
│   ├── staff_service.py        # Staff DB queries
│   ├── library_service.py      # Local Library DB queries
│   ├── timetable_service.py    # Timetable DB queries
│   └── calendar_service.py     # Calendar DB queries
│
├── scrapers/                   # Web scraping layer
│   ├── faculty_scraper.py      # Scrapes all 5 faculty category pages
│   └── staff_scraper.py        # Scrapes the staff directory page
│
├── dau_mcp/                    # Model Context Protocol Servers
│   ├── unified_mcp_server.py   # Exposes ALL tools (Recommended)
│   ├── faculty_mcp_server.py   # Faculty-only MCP tools
│   ├── staff_mcp_server.py     # Staff-only MCP tools
│   ├── library_mcp_server.py   # Library MCP tools
│   ├── timetable_mcp_server.py # Timetable MCP tools
│   └── calendar_mcp_server.py  # Calendar MCP tools
│
├── scripts/                    # Operational one-shot scripts
│   ├── init_db.sql             # Database schema initialization
│   ├── seed_faculty.py         # Seed faculty data from live website
│   ├── seed_staff.py           # Seed staff data from live website
│   ├── seed_library.py         # Seed library catalog from CSV
│   ├── seed_timetable.py       # Seed lecture and lab schedules from Excel
│   └── seed_calendar.py        # Seed academic calendar and holidays
│
├── .env.example                # Template for .env
├── .gitignore
└── requirements.txt
```

## Setup & Installation

### 1. Configure Environment

Copy the example file to set up your environment variables:
```bash
cp .env.example .env
```

Ensure your `.env` contains the required database connection variables for your local PostgreSQL database:
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=daiict_db
DB_USER=postgres
DB_PASSWORD=your-password
```

### 2. Install Dependencies

You must install dependencies in your Python environment. For Windows, using a virtual environment (`venv`) is highly recommended.

```powershell
# Create and activate a virtual environment
python -m venv win_venv
.\win_venv\Scripts\Activate.ps1

# Install requirements
pip install -r requirements.txt
```

### 3. Initialize Database

Since we use a local PostgreSQL database, you will need to initialize the schema and populate the data locally.

1. **Create the Database:**
   Log into your local `psql` or pgAdmin and run:
   ```sql
   CREATE DATABASE daiict_db;
   ```

2. **Run Initialization Scripts:**
   Run the schema setup script (this will create tables for faculty, staff, library, calendar, and api_keys) and then seed the tables with live DA-IICT data:
   ```powershell
   # Create tables
   psql -U postgres -d daiict_db -f scripts/init_db.sql

   # Seed Data
   python scripts/seed_faculty.py
   python scripts/seed_staff.py
   python scripts/seed_library.py
   python scripts/seed_timetable.py
   python scripts/seed_calendar.py
   ```

## Starting the Portal & Hosting HTTP/SSE

The MCP server runs over secure HTTP/SSE. Start the FastAPI backend server to host the portal and authenticate MCP connections:

```bash
python -m uvicorn api.main:create_app --factory --host 0.0.0.0 --port 8001
```

Once running:
1. Open **[http://localhost:8001/](http://localhost:8001/)** in your browser.
2. Sign in with your DA-IICT Google account.
3. The portal will verify your domain, show your user category (Student, Faculty, or Staff), and automatically generate your secure API key (`dau_sk_...`).

---

## Editor Configurations

Choose the appropriate integration tab on the portal dashboard to copy your configuration:

### 1. Claude Desktop (Pathless In-Memory HTTP/SSE Bridge)

Claude Desktop only supports local `stdio` processes. To connect it securely without exposing your local workspace folder, Python path, or environment variables, you can configure it to fetch and execute a tiny proxy bridge script in memory.

On Windows, edit `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "daiict": {
      "command": "python",
      "args": [
        "-c",
        "import urllib.request; exec(urllib.request.urlopen('http://localhost:8001/mcp_proxy.py').read().decode())",
        "http://localhost:8001/mcp/sse",
        "YOUR_DAU_API_KEY_HERE"
      ]
    }
  }
}
```

### 2. Cursor / Windsurf (Native HTTP/SSE)

Cursor and Windsurf support direct network connections. You only need to supply the connection URL and header (no local pathways or commands needed):

```json
{
  "mcpServers": {
    "daiict": {
      "url": "http://localhost:8001/mcp/sse",
      "headers": {
        "Authorization": "Bearer YOUR_DAU_API_KEY_HERE"
      }
    }
  }
}
```

---

## Available Tools & Example Queries

Once configured, Claude can natively call the following tools. Try asking Claude these example questions to see it in action!

**Faculty:**
- `list_faculty()`
- `search_faculty(query)`
- `get_faculty_details(name_or_email)`
- `search_faculty_by_expertise(expertise)`
- `sync_faculty_data()`
*Example Query*: "Who is the faculty expert in Machine Learning?" or "Get the profile for Prof. Suman Mitra."

**Staff:**
- `list_staff()`
- `search_staff(query)`
- `get_staff_details(name_or_email)`
- `sync_staff_data()`
*Example Query*: "Who is the placement coordinator?"

**Library:**
- `search_library_books(query, limit)`
- `get_book_details(biblionumber)`
*Example Query*: "Find books on Artificial Intelligence in the library."

**Timetables:**
- `get_faculty_location(faculty_name, day, time)`
- `get_faculty_schedule(faculty_name, day)`
- `find_faculty_free_time(faculty_name, day)`
- `get_course_schedule(course_code, day)`
- `list_programs()`
- `get_program_timetable(program_name, day)`
*Example Query*: "When is Prof. Manish Khare free on Tuesday?" or "Where is the lecture for CS301 on Monday at 10 AM?"

**Calendar:**
- `get_next_holiday()`
- `get_upcoming_holidays()`
- `get_all_holidays()`
- `get_midsem_dates()`
- `get_endsem_dates()`
- `get_next_academic_event()`
- `search_calendar(query, semester=None)`
*Example Query*: "When are the mid-semester exams for semester 3?" or "List all the DA-IICT holidays for the year."

## Database Statistics

The local PostgreSQL database is actively seeded with:
- **Faculty Records**: ~116
- **Staff Records**: ~92
- **Library Catalog**: 28,000+ Books
- **Timetable Slots**: 1,200+ (Lectures, Labs, Tutorials)
- **Academic Calendar**: 120+ Events & Holidays
- **API Keys**: Managed via init_db.sql

## Sample Conversations

- Who teaches Machine Learning at DA-IICT?
- Show details of Prof. Aditya Tatu.
- Find books on Artificial Intelligence.
- Where is Prof. Abhishek Gupta currently teaching?
- Show MSc IT timetable for Monday.
- When are the Mid-Semester examinations?
- When is the next public holiday?
- List all Winter semester academic events.
