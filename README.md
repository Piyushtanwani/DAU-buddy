# DA-IICT Unified MCP Server

A Model Context Protocol (MCP) server providing Claude (and other LLMs) with direct access to Dhirubhai Ambani Institute of Information and Communication Technology (DA-IICT) databases.

This server enables AI models to natively search the faculty directory, staff directory, and the library OPAC catalog through a local high-performance PostgreSQL database.

## Features

- **Faculty Tools**: List faculty, search by name or expertise, view full profiles, and trigger live website syncing.
- **Staff Tools**: List staff, search by name or designation, view full profiles, and trigger live website syncing.
- **Library OPAC Tools**: Instantly search the DA-IICT library catalog (over 28,000 records) and retrieve detailed book metadata using PostgreSQL full-text search. Includes fallback links to the live OPAC for physical availability checking.
- **Timetable Tools**: Query faculty schedules, course timings, free time slots, and full program batch timetables.
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
│   └── library_service.py      # Local Library DB queries
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
│   └── timetable_mcp_server.py # Timetable MCP tools
│
├── scripts/                    # Operational one-shot scripts
│   ├── init_db.sql             # Database schema initialization
│   ├── seed_faculty.py         # Seed faculty data from live website
│   ├── seed_staff.py           # Seed staff data from live website
│   ├── seed_library.py         # Seed library catalog from CSV
│   └── seed_timetable.py       # Seed lecture and lab schedules from Excel
│
├── .env.example                # Template for .env
├── .gitignore
└── requirements.txt
```

## Setup & Installation

### 1. Configure Environment

Copy the example file and add your database password (ask the project owner if you don't have it) and Gemini API Key:
```bash
cp .env.example .env
```

Ensure your `.env` contains the required database connection variables for the online Neon DB:
```
DB_HOST=ep-curly-cloud-atr9widv.c-9.us-east-1.aws.neon.tech
DB_PORT=5432
DB_NAME=neondb
DB_USER=neondb_owner
DB_PASSWORD=your_password_here
DB_SSLMODE=require
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

🎉 **Zero Local Setup Required!** 🎉

The database is hosted online securely via Neon DB and is already fully seeded with Faculty, Staff, Timetable, and Library data. 

Once your `.env` file is set, you can jump straight into adding it to Claude Desktop.

## Adding to Claude Desktop

To allow Claude to use these tools, add the Unified Server to your Claude Desktop configuration file.

On Windows, edit `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "daiict-unified": {
      "command": "C:\\path\\to\\MCP Project\\venv\\Scripts\\python.exe",
      "args": [
        "-m",
        "dau_mcp.unified_mcp_server"
      ],
      "env": {
        "PYTHONPATH": "C:\\path\\to\\MCP Project"
      }
    }
  }
}
```
*(Make sure to replace `C:\\path\\to\\MCP Project` with the actual absolute path to your project folder).*

After saving the configuration, **fully restart Claude Desktop** to initialize the server.

## Available Tools

Once configured, Claude can natively call the following tools:

**Faculty:**
- `list_faculty()`
- `search_faculty(query)`
- `get_faculty_details(name_or_email)`
- `search_faculty_by_expertise(expertise)`
- `sync_faculty_data()`

**Staff:**
- `list_staff()`
- `search_staff(query)`
- `get_staff_details(name_or_email)`
- `sync_staff_data()`

**Library:**
- `search_library_books(query, limit)`
- `get_book_details(biblionumber)`

**Timetables:**
- `get_faculty_location(faculty_name, day, time)`
- `get_faculty_schedule(faculty_name, day)`
- `find_faculty_free_time(faculty_name, day)`
- `get_course_schedule(course_code, day)`
- `list_programs()`
- `get_program_timetable(program_name, day)`
