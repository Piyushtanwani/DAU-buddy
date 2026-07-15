# Contributing to DAU Buddy MCP Server

Thank you for your interest in contributing! This guide covers local setup, coding conventions, and how to submit changes.

## Table of Contents

- [Local Setup](#local-setup)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Submitting Changes](#submitting-changes)
- [Adding a New MCP Tool](#adding-a-new-mcp-tool)

---

## Local Setup

### Prerequisites

- **Python 3.10+** (FastAPI and MCP server runtime)
- **PostgreSQL** (stores faculty, staff, library, timetable, calendar, and scholar data)
- **Node.js / npm** (for `npx mcp-remote` proxy bridge if testing with Claude Desktop)

### 1. Clone the Repository

```bash
git clone https://github.com/gamekeepers/dau-mcp-server.git
cd dau-mcp-server
```

### 2. Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Configuration

```bash
cp .env.example .env
```

Edit `.env` with your PostgreSQL credentials and SMTP settings:

```ini
DB_HOST=localhost
DB_PORT=5432
DB_NAME=daiict_db
DB_USER=postgres
DB_PASSWORD=your_password
```

### 4. Initialize Database

```bash
createdb -U postgres daiict_db
psql -U postgres -d daiict_db -f scripts/init_db.sql
```

### 5. Seed Data

```bash
python scripts/seed_faculty.py
python scripts/seed_staff.py
python scripts/seed_scholars.py
python scripts/seed_library.py
python scripts/seed_timetable.py
python scripts/seed_calendar.py
```

> The library seed takes a few minutes (28,000+ records).

### 6. Run the Server

```bash
# Development mode with hot-reload
make dev

# Production mode
make run
```

The dashboard will be available at `http://127.0.0.1:8000/`.

### 7. Verify Setup

```bash
make test
```

### Docker Alternative

```bash
docker build -t dau-mcp-server .
docker run -p 8080:8080 --env-file .env dau-mcp-server
```

---

## Development Workflow

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the coding standards below.

3. **Run tests**:
   ```bash
   make test
   ```

4. **Commit and push**:
   ```bash
   git add .
   git commit -m "feat: describe your change"
   git push origin feature/your-feature-name
   ```

5. **Open a Pull Request** against `main`.

---

## Coding Standards

### Python

- Follow **PEP 8** for style.
- Use type hints where applicable.
- Add docstrings to all public functions and MCP tools.
- MCP tool docstrings follow this format:

  ```python
  @tool
  def my_tool(param: str) -> dict:
      """
      Short description of what the tool does.

      Args:
          param: Description of the parameter.
      """
  ```

### Naming Conventions

| Component | Convention | Example |
|-----------|-----------|---------|
| MCP tools | `snake_case` with verb prefix | `get_faculty_schedule` |
| Services | `noun_service.py` | `faculty_service.py` |
| Variables/funcs | `snake_case` | `fetch_data()` |
| Classes | `PascalCase` | `DatabasePool` |

### Architecture Layers

- **`api/services/`** — Business logic and database queries. New data access belongs here.
- **`dau_mcp/`** — MCP tool definitions. Tools should delegate to services, not query the database directly.
- **`scrapers/`** — Web scraping logic for external DA-IICT sources.
- **`core/`** — Shared infrastructure (config, DB pool, schemas).
- **`scripts/`** — One-shot operational scripts (DB init, seeding).

---

## Submitting Changes

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

| Type | Description |
|------|-------------|
| `feat` | New feature or tool |
| `fix` | Bug fix |
| `refactor` | Code restructuring without behavior change |
| `docs` | Documentation updates |
| `test` | Adding or modifying tests |
| `chore` | Maintenance, deps, config |

Examples:
```
feat: add scholar search by thesis topic
fix: handle missing timetable data gracefully
refactor: extract DB query logic to timetable_service
docs: update MCP tool descriptions
```

### Pull Requests

- Reference any related issue number.
- Include a summary of changes and the motivation.
- If adding an MCP tool, document it in the PR description with example usage.
- Ensure all tests pass before requesting review.

---

## Adding a New MCP Tool

1. **Add service method** in `api/services/<service>.py` (or create a new service file).
2. **Register the tool** in `dau_mcp/unified_mcp_server.py`:
   ```python
   @mcp.tool()
   def my_new_tool(param: str):
       """Description..."""
       return service.my_method(param)
   ```
3. **Add tests** in `tests/`.
4. **Update this doc** if the tool is user-facing and significant.

---

## Project Structure Reference

```
dau-mcp-server/
├── api/                  # FastAPI app, routes, services
├── core/                 # Config, DB connection, shared schemas
├── dau_mcp/              # MCP server definitions (unified + modular)
├── scrapers/             # Web scrapers for DA-IICT sources
├── scripts/              # DB init SQL and data seeding scripts
├── frontend/             # Web dashboard (HTML, JS)
├── tests/                # pytest test suite
└── docs/                 # Documentation
```

---

## Need Help?

- Check existing tools in `dau_mcp/unified_mcp_server.py` for patterns.
- Look at the tests in `tests/` for usage examples.
- Open an issue if you're unsure about the approach.
