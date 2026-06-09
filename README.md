# DA-IICT Faculty & Staff AI Buddy

Production-grade conversational search assistant for Dhirubhai Ambani Institute of Information and Communication Technology (DA-IICT).

## Features

- **Conversational RAG Search**: Powered by Google's Gemini 2.5 Flash, enabling natural language queries over live university directories.
- **Real-Time Library OPAC Integration**: Native Gemini tool calling integration with DA-IICT's Koha OPAC to search books, check real-time availability, and fetch catalog details.
- **Robust NLP Fallback**: A local, stateless rule-based engine routing queries instantly when Gemini is offline or on cooldown (now includes Exact Designation Matching).
- **Advanced Full-Text Search**: Uses PostgreSQL's `websearch_to_tsquery` combined with dynamic `OR` logic to understand conversational search intents.
- **Auto-Formatting Profiles**: Clean, readable markdown bullet-point generation for all faculty and staff information.
- **Live Scrapers & Sync**: Built-in chat triggers (e.g., *"sync faculty"*) to dynamically scrape and update the database directly from the DA-IICT website.
- **Separated MCP Servers**: Native Model Context Protocol (MCP) servers for both Faculty and Staff, integrating directly with external agents.


## Project Structure

```
MCP Project/
│
├── core/                       # Shared infrastructure layer
│   ├── config.py               # Environment loading, logging factory, API keys
│   ├── database.py             # Thread-safe PostgreSQL connection pool
│   └── schemas.py              # Shared Pydantic models
│
├── api/                        # FastAPI web layer
│   ├── main.py                 # Application factory (create_app)
│   ├── routes/
│   │   ├── chat.py             # POST /api/chat (SSE streaming enabled)
│   │   ├── health.py           # GET  /api/health
│   │   └── library.py          # GET  /api/v1/library/* (OPAC API wrapper)
│   └── services/
│       ├── gemini.py           # Gemini 2.5 Flash API client + circuit breaker (120s timeout)
│       ├── faculty_service.py  # Faculty DB queries + context caching
│       ├── staff_service.py    # Staff DB queries + context caching
│       ├── library_service.py  # DA-IICT Koha OPAC scraping & HTTP client
│       ├── retrieval.py        # RAG retrieval service using PostgreSQL full-text search
│       ├── context_builder.py  # Transforms DB rows into clean context for Gemini
│       └── fallback.py         # Advanced NLP fallback engine (stateless chat, name extraction, default summaries)
│
├── scrapers/                   # Web scraping layer
│   ├── faculty_scraper.py      # Scrapes all 5 faculty category pages
│   └── staff_scraper.py        # Scrapes the staff directory page
│
├── mcp/                        # Separated MCP server layer
│   ├── faculty_mcp_server.py   # Faculty-only MCP tools (stdio transport)
│   ├── staff_mcp_server.py     # Staff-only MCP tools (stdio transport)
│   └── library_mcp_server.py   # Library OPAC MCP tools (stdio transport)
│
├── frontend/                   # Web UI
│   ├── index.html
│   ├── app.js
│   └── style.css
│
├── scripts/                    # Operational one-shot scripts
│   ├── init_db.sql             # Database schema initialization
│   ├── seed_faculty.py         # Seed faculty data from live website
│   └── seed_staff.py           # Seed staff data from live website
│
├── tests/                      # Test suite
│   ├── test_faculty_service.py
│   ├── test_staff_service.py
│   └── test_library.py
│
├── .env                        # Local credentials (not committed)
├── .env.example                # Template for .env
├── .gitignore
├── Dockerfile
├── Makefile
└── requirements.txt
```

## Quick Start

### 1. Set up environment variables

Copy the example file and add your Gemini API Key and PostgreSQL credentials.
```bash
cp .env.example .env
```

---

### 2. Operating System Specific Setup

#### Option A: Windows (PowerShell)
*Windows does not have `make` installed by default. You will run Python commands directly.*

1. **Install Dependencies:**
   ```powershell
   # It is recommended to run this in a virtual environment, or install globally if you prefer:
   pip install -r requirements.txt
   ```
2. **Seed the Database** (Ensure your Windows PostgreSQL service is running and `daiict_db` is created):
   ```powershell
   python scripts/seed_faculty.py
   python scripts/seed_staff.py
   ```
3. **Start the Web Server:**
   ```powershell
   # Development (hot-reload)
   python -m uvicorn api.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
   
   # Production
   python -m uvicorn api.main:create_app --factory --host 0.0.0.0 --port 8080
   ```

#### Option B: Linux / Ubuntu (WSL)
*Modern Ubuntu versions enforce strict Python environment rules (`externally-managed-environment`). You must use a Virtual Environment.*

1. **Create and Activate a Virtual Environment:**
   ```bash
   # Install the venv package if you don't have it
   sudo apt update && sudo apt install python3.12-venv
   
   # Create and activate it
   python3 -m venv venv
   source venv/bin/activate
   ```
2. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure Database & Seed Data:**
   *(If your database is running on Windows, you cannot use `localhost` in WSL. It is easiest to install PostgreSQL directly in Ubuntu).*
   ```bash
   # Install PostgreSQL in Ubuntu
   sudo apt install postgresql postgresql-contrib
   sudo service postgresql start
   
   # Log in and configure the user/database to match your .env file
   sudo -u postgres psql
   # Run: ALTER USER postgres PASSWORD 'your_password';
   # Run: CREATE DATABASE daiict_db;
   # Run: \q
   
   # Seed the data using Make
   make seed
   ```
4. **Start the Web Server:**
   ```bash
   make dev
   ```

---

### 3. Access the Chatbot

Open your browser at: `http://127.0.0.1:8000`
---

## MCP Servers

The Faculty, Staff, and Library MCP servers are **fully separated** and independently runnable.

### Library MCP Server

```bash
python -m mcp.library_mcp_server
```

**Tools exposed:**
- `search_library_books(query, limit)` — Keyword / title / author / ISBN search on OPAC
- `get_book_details(biblionumber)` — Full record + real-time copy availability

### Faculty MCP Server

```bash
python -m mcp.faculty_mcp_server
# or: make mcp-faculty
```

**Tools exposed:**
- `list_faculty` — List all faculty members
- `search_faculty(query)` — Search across name, specialization, education, email
- `get_faculty_details(name_or_email)` — Full profile lookup
- `search_faculty_by_expertise(expertise)` — Expertise-specific search
- `sync_faculty_data()` — Live scrape & reload

### Staff MCP Server

```bash
python -m mcp.staff_mcp_server
# or: make mcp-staff
```

**Tools exposed:**
- `list_staff` — List all staff members
- `search_staff(query)` — Search across name, designation, qualification, email
- `get_staff_details(name_or_email)` — Full profile lookup
- `sync_staff_data()` — Live scrape & reload

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/chat` | Main chat endpoint (Gemini RAG + NLP fallback) |
| `GET`  | `/api/health` | Database health probe |
| `GET`  | `/api/v1/library/search` | Search Koha OPAC library catalog |
| `GET`  | `/api/v1/library/detail/{biblionumber}` | Fetch full book details and availability |
| `GET`  | `/docs` | Swagger UI |
| `GET`  | `/redoc` | ReDoc UI |

---

## Running Tests

```bash
make test
# or: python -m pytest tests/ -v
```

---

## Docker

```bash
docker build -t dau-buddy .
docker run -p 8080:8080 --env-file .env dau-buddy
```

---

## Architecture

```
Browser
  │
  ▼
FastAPI (api/main.py)
  ├── /api/chat   →  routes/chat.py
  │                    ├── Sync triggers → scrapers/
  │                    ├── Gemini RAG   → services/gemini.py + retrieval.py + context_builder.py
  │                    │                    └── Library Tools → services/library_service.py
  │                    └── NLP Fallback → services/fallback.py
  ├── /api/health →  routes/health.py → core/database.py
  └── /api/v1/library → routes/library.py → services/library_service.py

MCP Tools (independent processes)
  ├── mcp/faculty_mcp_server.py → core/database.py
  ├── mcp/staff_mcp_server.py   → core/database.py
  └── mcp/library_mcp_server.py → opac.daiict.ac.in (Live Koha API)

Shared Infrastructure (core/)
  ├── config.py   — env, logging, API keys
  ├── database.py — threaded connection pool
  └── schemas.py  — Pydantic models
```
