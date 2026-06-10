# ==============================================================================
# DA-IICT Faculty & Staff AI Buddy — Makefile
# ==============================================================================
# Usage:  make <target>

.PHONY: run dev seed-faculty seed-staff seed test help

# ── Application ────────────────────────────────────────────────────────────────
run:
	python -m uvicorn api.main:create_app --factory --host 0.0.0.0 --port 8080

dev:
	python -m uvicorn api.main:create_app --factory --host 127.0.0.1 --port 8000 --reload

# ── MCP Servers ────────────────────────────────────────────────────────────────
mcp-faculty:
	python -m dau_mcp.faculty_mcp_server

mcp-staff:
	python -m dau_mcp.staff_mcp_server

# ── Data Seeding ───────────────────────────────────────────────────────────────
seed-faculty:
	python scripts/seed_faculty.py

seed-staff:
	python scripts/seed_staff.py

seed: seed-faculty seed-staff

# ── Testing ────────────────────────────────────────────────────────────────────
test:
	python -m pytest tests/ -v

# ── Help ───────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  make dev            Start dev server (localhost:8000, hot-reload)"
	@echo "  make run            Start production server (0.0.0.0:8080)"
	@echo "  make mcp-faculty    Start Faculty MCP Server (stdio)"
	@echo "  make mcp-staff      Start Staff MCP Server (stdio)"
	@echo "  make seed-faculty   Scrape & seed faculty data"
	@echo "  make seed-staff     Scrape & seed staff data"
	@echo "  make seed           Seed both faculty and staff"
	@echo "  make test           Run the test suite"
	@echo ""
