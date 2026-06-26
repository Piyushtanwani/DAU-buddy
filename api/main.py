import os
import hashlib
import secrets
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core import config
from core.database import db_connection
from api.routes import router as api_router
from dau_mcp.unified_mcp_server import mcp

# Google Auth
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import requests

global_session = requests.Session()
cached_google_request = google_requests.Request(session=global_session)

# SlowAPI Rate Limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from starlette.middleware.base import BaseHTTPMiddleware

class PayloadLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and int(cl) > 100 * 1024:
            return JSONResponse(status_code=413, content={"detail": "Payload too large"})
        return await call_next(request)

logger = config.get_logger("api.main")
CLIENT_ID = "590260573365-9151v4jkovetn7rhml7vhtfs5c0or2em.apps.googleusercontent.com"

limiter = Limiter(key_func=get_remote_address)

def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

def verify_google_token(credential: str) -> str:
    try:
        idinfo = id_token.verify_oauth2_token(credential, cached_google_request, CLIENT_ID)
        email = idinfo['email']
        # Domain check bypassed for testing
        # if not (email.endswith("@dau.ac.in") or email.endswith("@daiict.ac.in")):
        #     raise HTTPException(status_code=403, detail="Invalid domain")
        return email
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

def create_app() -> FastAPI:
    logger.info("Starting DA-IICT Faculty & Staff AI Buddy (Production)...")

    app = FastAPI(
        title="DA-IICT Faculty & Staff AI Buddy",
        description="Production-grade conversational search assistant for DAU Faculty & Staff.",
        version="2.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None
    )
    
    @app.on_event("startup")
    def startup_event():
        from core.database import init_pool
        init_pool()

    @app.on_event("shutdown")
    def shutdown_event():
        from core.database import _shutdown_pool
        _shutdown_pool()

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled Exception: {exc}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "An internal error occurred. Please try again."})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://mcp.dau.ac.in", "http://localhost:8001", "http://127.0.0.1:8001"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    
    app.add_middleware(PayloadLimitMiddleware)

    class KeyRequest(BaseModel):
        credential: str

    @app.post("/api/me")
    @limiter.limit("5/minute")
    def get_me(request: Request, req: KeyRequest):
        email = verify_google_token(req.credential)
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT status, created_at, last_used, role FROM api_keys WHERE email = %s AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)", (email,))
                    row = cursor.fetchone()
                    if row:
                        return {"has_key": True, "status": row[0], "created_at": row[1], "last_used": row[2], "role": row[3]}
                    return {"has_key": False}
        except Exception as e:
            logger.error(f"DB Error: {e}")
            raise HTTPException(status_code=500, detail="Database error")

    @app.post("/api/generate-key")
    @limiter.limit("5/minute")
    def generate_api_key(request: Request, req: KeyRequest):
        email = verify_google_token(req.credential)
        
        local_part = email.split('@')[0]
        assigned_role = 'User'
        
        if local_part.isdigit():
            assigned_role = 'Student'
        else:
            try:
                with db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT 1 FROM faculty WHERE email = %s LIMIT 1", (email,))
                        if cursor.fetchone():
                            assigned_role = 'Faculty'
                        else:
                            cursor.execute("SELECT 1 FROM staff WHERE email = %s LIMIT 1", (email,))
                            if cursor.fetchone():
                                assigned_role = 'Staff'
            except Exception as e:
                logger.error(f"Error checking directories for role assignment: {e}")

        raw_key = f"dau_sk_{secrets.token_hex(16)}"
        hashed_k = hash_key(raw_key)
        
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO api_keys (email, hashed_key, role, status, expires_at)
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP + INTERVAL '90 days')
                        ON CONFLICT (email) DO UPDATE 
                        SET hashed_key = EXCLUDED.hashed_key,
                            status = 'Active',
                            created_at = CURRENT_TIMESTAMP,
                            expires_at = CURRENT_TIMESTAMP + INTERVAL '90 days'
                    """, (email, hashed_k, assigned_role, 'Active'))
            return {"api_key": raw_key, "role": assigned_role}
        except Exception as e:
            logger.error(f"Error generating key: {e}")
            raise HTTPException(status_code=500, detail="Database error")

    @app.post("/api/regenerate-key")
    @limiter.limit("5/minute")
    def regenerate_api_key(request: Request, req: KeyRequest):
        email = verify_google_token(req.credential)
            
        raw_key = f"dau_sk_{secrets.token_hex(16)}"
        hashed_k = hash_key(raw_key)
        
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE api_keys 
                        SET hashed_key = %s, status = 'Active', created_at = CURRENT_TIMESTAMP, expires_at = CURRENT_TIMESTAMP + INTERVAL '90 days'
                        WHERE email = %s
                        RETURNING role
                    """, (hashed_k, email))
                    row = cursor.fetchone()
                    role = row[0] if row else 'User'
            return {"api_key": raw_key, "role": role}
        except Exception as e:
            logger.error(f"Error regenerating key: {e}")
            raise HTTPException(status_code=500, detail="Database error")

    app.include_router(api_router, prefix="/api")

    logger.info("Mounting FastMCP HTTP/SSE endpoints at /mcp")
    mcp.settings.host = "127.0.0.1"
    mcp.settings.port = 8001
    
    from api.middleware.mcp_auth import MCPAuthMiddleware
    app.mount("/mcp", MCPAuthMiddleware(mcp.sse_app()))

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
