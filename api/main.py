import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from core import config
from core.database import db_connection
from api.routes import router as api_router
import hashlib
import secrets
from pydantic import BaseModel
from fastapi import HTTPException
from dau_mcp.unified_mcp_server import mcp

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
                    cursor.execute("SELECT status, created_at, last_used, hashed_key, role FROM api_keys WHERE email = %s", (req.email,))
                    row = cursor.fetchone()
                    if row:
                        return {"has_key": True, "status": row[0], "created_at": row[1], "last_used": row[2], "api_key": row[3], "role": row[4]}
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

        # Determine role based on email
        local_part = req.email.split('@')[0]
        assigned_role = 'User'
        
        if local_part.isdigit():
            assigned_role = 'Student'
        else:
            try:
                with db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT 1 FROM faculty WHERE email = %s LIMIT 1", (req.email,))
                        if cursor.fetchone():
                            assigned_role = 'Faculty'
                        else:
                            cursor.execute("SELECT 1 FROM staff WHERE email = %s LIMIT 1", (req.email,))
                            if cursor.fetchone():
                                assigned_role = 'Staff'
            except Exception as e:
                logger.error(f"Error checking directories for role assignment: {e}")

        raw_key = f"dau_sk_{secrets.token_hex(16)}"
        
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO api_keys (email, hashed_key, role, status)
                        VALUES (%s, %s, %s, %s)
                    """, (req.email, raw_key, assigned_role, 'Active'))
            return {"api_key": raw_key}
        except Exception as e:
            logger.error(f"Error generating key: {e}")
            raise HTTPException(status_code=500, detail="Database error")

    @app.post("/api/regenerate-key")
    def regenerate_api_key(req: KeyRequest):
        if not (req.email.endswith("@dau.ac.in") or req.email.endswith("@daiict.ac.in")):
            raise HTTPException(status_code=403, detail="Invalid domain")
            
        raw_key = f"dau_sk_{secrets.token_hex(16)}"
        
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE api_keys 
                        SET hashed_key = %s, status = 'Active', created_at = CURRENT_TIMESTAMP
                        WHERE email = %s
                    """, (raw_key, req.email))
            return {"api_key": raw_key}
        except Exception as e:
            logger.error(f"Error regenerating key: {e}")
            raise HTTPException(status_code=500, detail="Database error")

    # ── API routes (prefixed /api) ────────────────────────────────────────────
    app.include_router(api_router, prefix="/api")

    # ── Mount FastMCP SSE Endpoints ───────────────────────────────────────────
    logger.info("Mounting FastMCP HTTP/SSE endpoints at /mcp")
    mcp.settings.host = "127.0.0.1"
    mcp.settings.port = 8001
    from api.middleware.mcp_auth import MCPAuthMiddleware
    app.mount("/mcp", MCPAuthMiddleware(mcp.sse_app()))

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
