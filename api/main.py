import os
import hashlib
import secrets
import re
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from pydantic import BaseModel
from fastapi import HTTPException

from core import config
from core.database import db_connection
from api.routes import router as api_router


def _classify_role(email: str) -> str:
    """
    Classify a @dau.ac.in / @daiict.ac.in email into a role.

    Rules (applied in order):
      1. Explicit admin list → Admin
      2. Local part is all digits (e.g. 202512063) → Student
      3. Local part starts with a year-prefix digit block followed by letters
         (e.g. 23bce001) → Student
      4. Email found in the faculty table → Faculty
      5. Email found in the staff table  → Staff
      6. Fallback → User
    """
    local = email.split("@")[0].lower()

    # 1. Hardcoded admin accounts
    ADMIN_LOCALS = {"admin", "superadmin", "mcp-admin"}
    if local in ADMIN_LOCALS:
        return "Admin"

    # 2. Pure numeric local part → student enrollment number (e.g. 202512063)
    if re.fullmatch(r"\d+", local):
        return "Student"

    # 3. Year-prefix + letters pattern → student (e.g. 23bce001, 22ict045)
    if re.fullmatch(r"\d{2}[a-z]{2,5}\d{3,4}", local):
        return "Student"

    # 4. Check faculty table for matching email
    try:
        from core.database import db_connection
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM faculty WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                    (email,)
                )
                if cur.fetchone():
                    return "Faculty"

            # 5. Check staff table
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM staff WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                    (email,)
                )
                if cur.fetchone():
                    return "Staff"
    except Exception:
        pass

    # 6. Fallback
    return "User"

logger = config.get_logger("api.main")


def create_app() -> FastAPI:
    """
    Production FastAPI application factory.
    Registers CORS, all API routes, and mounts the frontend static files.
    """
    logger.info("Starting DA-IICT Faculty & Staff AI Buddy (Production)...")

    app = FastAPI(
        title="DA-IICT Faculty & Staff AI Buddy",
        description=(
            "Production-grade conversational search assistant for "
            "Dhirubhai Ambani University Faculty & Staff."
        ),
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class KeyRequest(BaseModel):
        email: str

    @app.post("/api/me")
    def get_me(req: KeyRequest):
        if not (req.email.endswith("@dau.ac.in") or req.email.endswith("@daiict.ac.in")):
            raise HTTPException(status_code=403, detail="Invalid domain")
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT status, created_at, last_used, role FROM api_keys WHERE email = %s", (req.email,))
                    row = cursor.fetchone()
                    if row:
                        return {"has_key": True, "status": row[0], "created_at": row[1], "last_used": row[2], "role": row[3]}
                    return {"has_key": False}
        except Exception as e:
            raise HTTPException(status_code=500, detail="Database error")

    @app.post("/api/generate-key")
    def generate_api_key(req: KeyRequest):
        if not (req.email.endswith("@dau.ac.in") or req.email.endswith("@daiict.ac.in")):
            raise HTTPException(status_code=403, detail="Invalid domain")
            
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT email FROM api_keys WHERE email = %s", (req.email,))
                    if cursor.fetchone():
                        raise HTTPException(status_code=400, detail="Key already exists. Please regenerate if lost.")
        except HTTPException:
            raise
        except Exception as e:
            pass

        raw_key = f"dau_sk_{secrets.token_hex(16)}"
        hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()
        
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    role = _classify_role(req.email)
                    cursor.execute("""
                        INSERT INTO api_keys (email, hashed_key, role, status)
                        VALUES (%s, %s, %s, %s)
                    """, (req.email, hashed_key, role, 'Active'))
            return {"api_key": raw_key, "role": role}
        except Exception as e:
            logger.error(f"Error generating key: {e}")
            raise HTTPException(status_code=500, detail="Database error")

    @app.post("/api/regenerate-key")
    def regenerate_api_key(req: KeyRequest):
        if not (req.email.endswith("@dau.ac.in") or req.email.endswith("@daiict.ac.in")):
            raise HTTPException(status_code=403, detail="Invalid domain")
            
        raw_key = f"dau_sk_{secrets.token_hex(16)}"
        hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()
        
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    role = _classify_role(req.email)
                    cursor.execute("""
                        UPDATE api_keys 
                        SET hashed_key = %s, status = 'Active', created_at = CURRENT_TIMESTAMP, role = %s
                        WHERE email = %s
                    """, (hashed_key, role, req.email))
            return {"api_key": raw_key, "role": role}
        except Exception as e:
            logger.error(f"Error regenerating key: {e}")
            raise HTTPException(status_code=500, detail="Database error")

    @app.get("/api/config-info")
    def get_config_info():
        import sys
        return {
            "python_path": sys.executable,
            "project_path": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        }

    @app.get("/mcp_proxy.py")
    def get_mcp_proxy():
        from fastapi.responses import PlainTextResponse
        proxy_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "mcp_sse_proxy.py")
        if os.path.exists(proxy_path):
            with open(proxy_path, "r", encoding="utf-8") as f:
                return PlainTextResponse(f.read())
        raise HTTPException(status_code=404, detail="Proxy script not found")

    # ── API routes (prefixed /api) ────────────────────────────────────────────
    app.include_router(api_router, prefix="/api")

    # ── MCP Auth Middleware ───────────────────────────────────────────────────
    class MCPAuthMiddleware(BaseHTTPMiddleware):
        """
        Intercepts all requests to /mcp/* and validates the
        'Authorization: Bearer dau_sk_...' header against the api_keys table.
        Passes everything else through untouched.
        """
        async def dispatch(self, request: Request, call_next):
            if not request.url.path.startswith("/mcp"):
                return await call_next(request)

            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    status_code=401,
                    content={"error": "Missing Authorization header. Include: Authorization: Bearer dau_sk_..."}
                )

            raw_key = auth_header.removeprefix("Bearer ").strip()
            hashed = hashlib.sha256(raw_key.encode()).hexdigest()

            try:
                with db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT email, role, status FROM api_keys WHERE hashed_key = %s",
                            (hashed,)
                        )
                        row = cur.fetchone()

                if not row:
                    return JSONResponse(status_code=401, content={"error": "Invalid API key."})

                email, role, status = row
                if status != "Active":
                    return JSONResponse(status_code=403, content={"error": "API key is revoked or inactive."})

                # Stamp last_used
                with db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE api_keys SET last_used = CURRENT_TIMESTAMP WHERE hashed_key = %s",
                            (hashed,)
                        )

                logger.info(f"MCP access granted: {email} ({role})")
                return await call_next(request)

            except Exception as e:
                logger.error(f"MCP auth DB error: {e}")
                return JSONResponse(status_code=500, content={"error": "Auth service error."})

    app.add_middleware(MCPAuthMiddleware)

    # ── MCP over SSE (authenticated) ──────────────────────────────────────────
    # Build and mount the unified MCP server as an SSE ASGI app at /mcp
    try:
        from mcp.server.fastmcp import FastMCP as _FastMCP
        from dau_mcp.faculty_mcp_server import (
            list_faculty, search_faculty, get_faculty_details,
            search_faculty_by_expertise, sync_faculty_data
        )
        from dau_mcp.staff_mcp_server import (
            list_staff, search_staff, get_staff_details, sync_staff_data
        )
        from dau_mcp.library_mcp_server import search_library_books, get_book_details
        from dau_mcp.timetable_mcp_server import (
            get_faculty_location, get_faculty_schedule, find_faculty_free_time,
            get_course_schedule, list_programs, get_program_timetable
        )
        from dau_mcp.calendar_mcp_server import (
            get_next_holiday, get_upcoming_holidays, get_all_holidays,
            get_midsem_dates, get_endsem_dates, get_next_academic_event, search_calendar
        )

        _mcp = _FastMCP("DA-IICT Unified Server (HTTP)")
        for _tool in [
            list_faculty, search_faculty, get_faculty_details, search_faculty_by_expertise, sync_faculty_data,
            list_staff, search_staff, get_staff_details, sync_staff_data,
            search_library_books, get_book_details,
            get_faculty_location, get_faculty_schedule, find_faculty_free_time,
            get_course_schedule, list_programs, get_program_timetable,
            get_next_holiday, get_upcoming_holidays, get_all_holidays,
            get_midsem_dates, get_endsem_dates, get_next_academic_event, search_calendar,
        ]:
            _mcp.add_tool(_tool)

        app.mount("/mcp", _mcp.sse_app())
        logger.info("MCP SSE server mounted at /mcp/sse — auth required.")
    except Exception as e:
        logger.error(f"Failed to mount MCP SSE server: {e}")

    # ── Frontend static files ─────────────────────────────────────────────────
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    frontend_dir = os.path.join(root_dir, "frontend")

    if os.path.exists(frontend_dir):
        logger.info(f"Mounting frontend from: {frontend_dir}")
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    else:
        logger.error(f"Frontend directory not found at: {frontend_dir}")

    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:create_app",
        host="0.0.0.0",
        port=8080,
        factory=True,
        reload=True,
    )
