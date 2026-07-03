import os
import hashlib
import secrets
from fastapi import FastAPI, HTTPException, Request, Depends, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
import base64
import urllib.parse
from pydantic import BaseModel, Field

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

oauth_codes = {}

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
                    
                    # Calculate role if no key exists
                    local_part = email.split('@')[0]
                    assigned_role = 'User'
                    if local_part.isdigit():
                        assigned_role = 'Student'
                    else:
                        cursor.execute("SELECT 1 FROM faculty WHERE email = %s LIMIT 1", (email,))
                        if cursor.fetchone():
                            assigned_role = 'Faculty'
                        else:
                            cursor.execute("SELECT 1 FROM staff WHERE email = %s LIMIT 1", (email,))
                            if cursor.fetchone():
                                assigned_role = 'Staff'
                                
                    return {"has_key": False, "role": assigned_role}
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
            raise HTTPException(status_code=500, detail=f"Database error: {e}")

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

    security = HTTPBearer()

    def get_current_user_from_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
        api_key = credentials.credentials
        hashed_k = hash_key(api_key)
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT status, role, email FROM api_keys WHERE hashed_key = %s AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)", (hashed_k,))
                    row = cursor.fetchone()
                    if row and row[0] == "Active":
                        cursor.execute("UPDATE api_keys SET last_used = CURRENT_TIMESTAMP WHERE hashed_key = %s", (hashed_k,))
                        return {"role": row[1], "email": row[2]}
        except Exception as e:
            logger.error(f"Auth Error: {e}")
        
        raise HTTPException(status_code=401, detail="Invalid, inactive, or expired API key")

    class FeedbackRequest(BaseModel):
        category: str = Field(..., max_length=100)
        subject: str = Field(..., max_length=200)
        description: str = Field(..., max_length=2000)
        priority: str = Field(default="Medium", max_length=20)

    @app.post("/api/feedback")
    @limiter.limit("5/minute")
    def submit_feedback(request: Request, req: FeedbackRequest, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user_from_api_key)):
        from core.email_service import send_feedback_email_async
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO feedback (user_email, role, category, subject, description, priority, status)
                        VALUES (%s, %s, %s, %s, %s, %s, 'Open')
                    """, (user["email"], user["role"], req.category, req.subject, req.description, req.priority))
            
            # Send Email Asynchronously
            background_tasks.add_task(
                send_feedback_email_async,
                user_email=user["email"],
                role=user["role"],
                category=req.category,
                subject=req.subject,
                description=req.description
            )
            return {"status": "success", "message": "Feedback submitted successfully."}
        except Exception as e:
            logger.error(f"Feedback Error: {e}")
            raise HTTPException(status_code=500, detail="Database error")

    @app.get("/authorize")
    def authorize(
        response_type: str,
        client_id: str,
        redirect_uri: str,
        state: str,
        code_challenge: str = None,
        code_challenge_method: str = None
    ):
        if response_type != "code":
            raise HTTPException(status_code=400, detail="Unsupported response_type")
            
        code = secrets.token_urlsafe(32)
        oauth_codes[code] = {
            "client_id": client_id,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "redirect_uri": redirect_uri
        }
        
        params = {"code": code, "state": state}
        url = f"{redirect_uri}?{urllib.parse.urlencode(params)}"
        return RedirectResponse(url=url)

    @app.post("/token")
    async def token(request: Request):
        body = await request.body()
        form = dict(urllib.parse.parse_qsl(body.decode("utf-8")))
        
        grant_type = form.get("grant_type")
        code = form.get("code")
        client_id = form.get("client_id")
        code_verifier = form.get("code_verifier")
        redirect_uri = form.get("redirect_uri")
        
        if grant_type != "authorization_code":
            raise HTTPException(status_code=400, detail="Unsupported grant_type")
            
        if code not in oauth_codes:
            raise HTTPException(status_code=400, detail="Invalid code")
            
        session = oauth_codes.pop(code)
        
        if session["client_id"] != client_id:
            raise HTTPException(status_code=400, detail="Client ID mismatch")
            
        if session["redirect_uri"] != redirect_uri:
            raise HTTPException(status_code=400, detail="Redirect URI mismatch")
            
        if session["code_challenge"] and code_verifier:
            if session["code_challenge_method"] == "S256":
                digest = hashlib.sha256(code_verifier.encode()).digest()
                b64_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
                if b64_challenge != session["code_challenge"]:
                    raise HTTPException(status_code=400, detail="Code challenge failed")
                    
        return {
            "access_token": client_id,
            "token_type": "bearer",
            "expires_in": 31536000,
            "refresh_token": client_id
        }

    app.include_router(api_router, prefix="/api")

    logger.info("Mounting FastMCP HTTP/SSE endpoints at /mcp")
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = 8001
    mcp.settings.transport_security = None
    
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
