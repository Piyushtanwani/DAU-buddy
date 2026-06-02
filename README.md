# DA-IICT Faculty & Staff AI Buddy

Production-grade conversational search assistant for Dhirubhai Ambani Institute of Information and Communication Technology (DA-IICT).

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
│   │   ├── chat.py             # POST /api/chat
│   │   └── health.py           # GET  /api/health
│   └── services/
│       ├── gemini.py           # Gemini API client + circuit breaker
│       ├── faculty_service.py  # Faculty DB queries + context caching
│       ├── staff_service.py    # Staff DB queries + context caching
│       └── fallback.py         # 8-pass rule-based NLP fallback engine
│
├── scrapers/                   # Web scraping layer
│   ├── faculty_scraper.py      # Scrapes all 5 faculty category pages
│   └── staff_scraper.py        # Scrapes the staff directory page
│
├── mcp/                        # Separated MCP server layer
│   ├── faculty_mcp_server.py   # Faculty-only MCP tools (stdio transport)
│   └── staff_mcp_server.py     # Staff-only MCP tools (stdio transport)
│
├── frontend/                   # Web UI
│   ├── index.html
│   ├── app.js
│   └── style.css
│
├── scripts/                    # Operational one-shot scripts
│   ├── seed_faculty.py         # Seed faculty data from live website
│   └── seed_staff.py           # Seed staff data from live website
│
├── tests/                      # Test suite
│   ├── test_faculty_service.py
│   └── test_staff_service.py
│
├── .env                        # Local credentials (not committed)
├── .env.example                # Template for .env
├── .gitignore
├── Dockerfile
├── Makefile
└── requirements.txt
```

## Quick Start

### 1. Set up environment

```bash
cp .env.example .env
# Edit .env with your PostgreSQL credentials and Gemini API key
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Seed the database

```bash
# Seed faculty data
python scripts/seed_faculty.py

# Seed staff data  
python scripts/seed_staff.py

# Or use Makefile
make seed
```

### 4. Start the web server

```bash
# Development (hot-reload, localhost:8000)
make dev
# or: python -m uvicorn api.main:create_app --factory --host 127.0.0.1 --port 8000 --reload

# Production (0.0.0.0:8080)
make run
```

Open your browser at: `http://127.0.0.1:8000`

---

## MCP Servers

The Faculty and Staff MCP servers are **fully separated** and independently runnable.

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
  │                    ├── Gemini RAG   → services/gemini.py + faculty/staff_service.py
  │                    └── NLP Fallback → services/fallback.py
  └── /api/health →  routes/health.py → core/database.py

MCP Tools (independent processes)
  ├── mcp/faculty_mcp_server.py → core/database.py
  └── mcp/staff_mcp_server.py   → core/database.py

Shared Infrastructure (core/)
  ├── config.py   — env, logging, API keys
  ├── database.py — threaded connection pool
  └── schemas.py  — Pydantic models
```
