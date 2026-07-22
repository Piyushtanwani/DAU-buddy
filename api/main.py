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

class PayloadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
            
        headers = dict(scope.get("headers", []))
        cl = headers.get(b"content-length")
        
        if cl and int(cl) > 100 * 1024:
            response = JSONResponse(status_code=413, content={"detail": "Payload too large"})
            return await response(scope, receive, send)
            
        await self.app(scope, receive, send)

logger = config.get_logger("api.main")
CLIENT_ID = "590260573365-9151v4jkovetn7rhml7vhtfs5c0or2em.apps.googleusercontent.com"

limiter = Limiter(key_func=get_remote_address)

def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

def split_key(raw_key: str) -> tuple[str, str]:
    prefix = raw_key[:14]
    return prefix, hash_key(raw_key)

def verify_google_token(credential: str) -> str:
    try:
        idinfo = id_token.verify_oauth2_token(credential, cached_google_request, CLIENT_ID, clock_skew_in_seconds=300)
        email = idinfo['email']
        # Domain check bypassed for testing
        # if not (email.endswith("@dau.ac.in") or email.endswith("@daiict.ac.in")):
        #     raise HTTPException(status_code=403, detail="Invalid domain")
        return email
    except ValueError as e:
        logger.error(f"Google Token Verification Error (ValueError): {e}")
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

    class TestConnectionRequest(BaseModel):
        credential: str
        app: str

    @app.get("/api/config-info")
    def get_config_info():
        import sys
        import os
        return {
            "python_path": sys.executable,
            "project_path": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        }

    @app.post("/api/me")
    @limiter.limit("60/minute")
    def get_me(request: Request, req: KeyRequest):
        email = verify_google_token(req.credential)
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT status, created_at, last_used, role, key_prefix FROM api_keys WHERE email = %s AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)", (email,))
                    row = cursor.fetchone()
                    if row:
                        role = row[3]
                        if email in config.get_feedback_recipient_emails():
                            local_part = email.split('@')[0]
                            role = 'Student / Maintainer' if local_part.isdigit() else 'Maintainer'
                        return {"has_key": True, "status": row[0], "created_at": row[1], "last_used": row[2], "role": role, "key_prefix": row[4]}
                    
                    assigned_role = 'User'
                    if email in config.get_feedback_recipient_emails():
                        local_part = email.split('@')[0]
                        assigned_role = 'Student / Maintainer' if local_part.isdigit() else 'Maintainer'
                    else:
                        local_part = email.split('@')[0]
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
        
        assigned_role = 'User'
        if email in config.get_feedback_recipient_emails():
            local_part = email.split('@')[0]
            assigned_role = 'Student / Maintainer' if local_part.isdigit() else 'Maintainer'
        else:
            local_part = email.split('@')[0]
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
        key_prefix, hashed_k = split_key(raw_key)
        
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO api_keys (email, key_prefix, hashed_key, role, status, expires_at)
                        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP + INTERVAL '90 days')
                        ON CONFLICT (email) DO UPDATE 
                        SET key_prefix = EXCLUDED.key_prefix,
                            hashed_key = EXCLUDED.hashed_key,
                            status = 'Active',
                            created_at = CURRENT_TIMESTAMP,
                            expires_at = CURRENT_TIMESTAMP + INTERVAL '90 days'
                    """, (email, key_prefix, hashed_k, assigned_role, 'Active'))
            return {"api_key": raw_key, "role": assigned_role}
        except Exception as e:
            logger.error(f"Error generating key: {e}")
            raise HTTPException(status_code=500, detail=f"Database error: {e}")

    @app.post("/api/regenerate-key")
    @limiter.limit("5/minute")
    def regenerate_api_key(request: Request, req: KeyRequest):
        email = verify_google_token(req.credential)
            
        raw_key = f"dau_sk_{secrets.token_hex(16)}"
        key_prefix, hashed_k = split_key(raw_key)
        
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE api_keys 
                        SET key_prefix = %s, hashed_key = %s, status = 'Active', created_at = CURRENT_TIMESTAMP, expires_at = CURRENT_TIMESTAMP + INTERVAL '90 days'
                        WHERE email = %s
                        RETURNING role
                    """, (key_prefix, hashed_k, email))
                    row = cursor.fetchone()
                    role = row[0] if row else 'User'
                    if email in config.get_feedback_recipient_emails():
                        local_part = email.split('@')[0]
                        role = 'Student / Maintainer' if local_part.isdigit() else 'Maintainer'
            return {"api_key": raw_key, "role": role}
        except Exception as e:
            logger.error(f"Error regenerating key: {e}")
            raise HTTPException(status_code=500, detail="Database error")

    security = HTTPBearer()

    def get_current_user_from_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
        api_key = credentials.credentials
        key_prefix = api_key[:14]
        hashed_k = hash_key(api_key)
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT status, role, email, hashed_key FROM api_keys "
                        "WHERE (key_prefix = %s OR (key_prefix IS NULL AND hashed_key = %s)) "
                        "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)", 
                        (key_prefix, hashed_k)
                    )
                    row = cursor.fetchone()
                    if row and row[0] == "Active" and secrets.compare_digest(row[3], hashed_k):
                        cursor.execute("UPDATE api_keys SET last_used = CURRENT_TIMESTAMP WHERE hashed_key = %s", (hashed_k,))
                        email = row[2]
                        role = row[1]
                        if email in config.get_feedback_recipient_emails():
                            local_part = email.split('@')[0]
                            role = 'Student / Maintainer' if local_part.isdigit() else 'Maintainer'
                        return {"role": role, "email": email}
        except Exception as e:
            logger.error(f"Auth Error: {e}")
        
        raise HTTPException(status_code=401, detail="Invalid, inactive, or expired API key")

    class FeedbackRequest(BaseModel):
        category: str = Field(..., max_length=100)
        subject: str = Field(..., max_length=200)
        description: str = Field(..., max_length=2000)
        priority: str = Field(default="Medium", max_length=20)
        credential: str

    @app.post("/api/feedback")
    @limiter.limit("5/minute")
    def submit_feedback(request: Request, req: FeedbackRequest, background_tasks: BackgroundTasks):
        email = verify_google_token(req.credential)
        from core.email_service import send_feedback_email_async
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    # Get user role from api_keys or assign default
                    cursor.execute("SELECT role FROM api_keys WHERE email = %s", (email,))
                    row = cursor.fetchone()
                    role = row[0] if row else 'User'

                    cursor.execute("""
                        INSERT INTO feedback (user_email, role, category, subject, description, priority, status)
                        VALUES (%s, %s, %s, %s, %s, %s, 'Open')
                        RETURNING id
                    """, (email, role, req.category, req.subject, req.description, req.priority))
                    feedback_id = cursor.fetchone()[0]
            
            # Send Email Asynchronously
            background_tasks.add_task(
                send_feedback_email_async,
                feedback_id=feedback_id,
                user_email=email,
                role=role,
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

    class OpenFolderRequest(BaseModel):
        app: str

    @app.post("/api/open-config-folder")
    def open_config_folder(req: OpenFolderRequest):
        import platform, subprocess
        path = ""
        is_file = False
        system = platform.system().lower()
        if req.app == "claude":
            is_file = True
            if system == "windows":
                path = os.path.expandvars(r"%APPDATA%\Claude\claude_desktop_config.json")
            elif system == "darwin":
                path = os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
            elif system == "linux":
                path = os.path.expanduser("~/.config/Claude/claude_desktop_config.json")
        elif req.app == "cursor":
            is_file = True
            if system == "windows":
                path = os.path.expanduser(r"~\.cursor\mcp.json")
            elif system == "darwin":
                path = os.path.expanduser("~/.cursor/mcp.json")
            elif system == "linux":
                path = os.path.expanduser("~/.cursor/mcp.json")
        elif req.app == "opencode":
            is_file = True
            if system == "windows":
                path = os.path.expanduser(r"~\.config\opencode\opencode.json")
            elif system == "darwin":
                path = os.path.expanduser("~/Library/Application Support/OpenCode/opencode.json")
            elif system == "linux":
                path = os.path.expanduser("~/.config/opencode/opencode.json")
        elif req.app == "codex":
            is_file = True
            path = os.path.expanduser("~/.codex/config.toml")
        # Other apps might have other paths, but for now we'll support the common ones
        
        if path:
            folder = os.path.dirname(path) if is_file else path
            os.makedirs(folder, exist_ok=True)
            
            if is_file and not os.path.exists(path):
                try:
                    with open(path, 'w') as f:
                        if req.app in ["claude", "opencode", "cursor"]:
                            f.write("{\n  \"mcpServers\": {\n    \n  }\n}")
                        else:
                            f.write("")
                except Exception as e:
                    logger.error(f"Failed to create config file: {e}")

            try:
                if system == "windows":
                    os.startfile(path)
                elif system == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
                return {"status": "success"}
            except Exception as e:
                logger.error(f"Failed to open path: {e}")
                return JSONResponse(status_code=500, content={"error": str(e)})
        else:
            return JSONResponse(status_code=400, content={"error": "Unsupported app or OS for direct folder opening"})

    @app.post("/api/test-connection")
    def test_connection(req: TestConnectionRequest):
        email = verify_google_token(req.credential)
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    # Check if the active key was used in the last 2 minutes (120 seconds)
                    cursor.execute("""
                        SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - last_used)), last_client
                        FROM api_keys 
                        WHERE email = %s AND status = 'Active' 
                        ORDER BY created_at DESC LIMIT 1
                    """, (email,))
                    row = cursor.fetchone()
                    
                    if row and row[0] is not None:
                        delta_seconds = float(row[0])
                        last_client = row[1] or ""
                        
                        if delta_seconds < 120:
                            # Verify that the connecting client matches the app we are testing
                            if req.app.lower() in last_client.lower():
                                return {"status": "success", "message": "Connection verified"}
                            else:
                                return JSONResponse(status_code=400, content={"error": f"Connection detected from {last_client}, not {req.app}"})
                            
            return JSONResponse(status_code=400, content={"error": "No recent connection detected"})
        except Exception as e:
            logger.error(f"Test connection error: {e}")
            return JSONResponse(status_code=500, content={"error": "Database error"})
    @app.post("/api/maintainer/dashboard")
    def maintainer_dashboard(request: Request, req: KeyRequest):
        email = verify_google_token(req.credential)
        if email not in config.get_feedback_recipient_emails():
            raise HTTPException(status_code=403, detail="Maintainer access required")
        
        try:
            with db_connection() as conn:
                with conn.cursor() as cursor:
                    # User Growth
                    cursor.execute("SELECT COUNT(*) FROM api_keys")
                    total_users = cursor.fetchone()[0]
                    cursor.execute("SELECT COUNT(*) FROM api_keys WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'")
                    new_users = cursor.fetchone()[0]
                    
                    # Platform Usage
                    cursor.execute("SELECT COUNT(*) FROM mcp_analytics")
                    total_queries = cursor.fetchone()[0]
                    cursor.execute("SELECT COUNT(DISTINCT user_email) FROM mcp_analytics")
                    active_users = cursor.fetchone()[0]
                    
                    # Signups Over Time (Last 30 Days)
                    cursor.execute("""
                        SELECT DATE(created_at), COUNT(*) 
                        FROM api_keys 
                        WHERE created_at >= CURRENT_DATE - INTERVAL '30 days' 
                        GROUP BY DATE(created_at) 
                        ORDER BY DATE(created_at) ASC
                    """)
                    signups_over_time = [{"date": str(r[0]), "count": r[1]} for r in cursor.fetchall()]
                    
                    # Queries Per User
                    cursor.execute("""
                        SELECT user_email, COUNT(*) as c 
                        FROM mcp_analytics 
                        GROUP BY user_email 
                        ORDER BY c DESC
                    """)
                    queries_per_user = [{"email": r[0], "count": r[1]} for r in cursor.fetchall()]
                    
                    # Tool Analytics
                    cursor.execute("SELECT tool_name, COUNT(*) as c FROM mcp_analytics GROUP BY tool_name ORDER BY c DESC")
                    tools_data = [{"tool_name": r[0], "count": r[1]} for r in cursor.fetchall()]
                    
                    # Client Analytics
                    cursor.execute("SELECT client_name, COUNT(*) as c FROM mcp_analytics GROUP BY client_name ORDER BY c DESC")
                    clients_data = [{"client_name": r[0], "count": r[1]} for r in cursor.fetchall()]
                    
                    # Role Analytics
                    cursor.execute("SELECT role, COUNT(*) as c FROM api_keys GROUP BY role ORDER BY c DESC")
                    roles_data = [{"role": r[0], "count": r[1]} for r in cursor.fetchall()]
                    
                    return {
                        "users": {"total": total_users, "new_last_7_days": new_users},
                        "platform": {"total_queries": total_queries, "active_users": active_users},
                        "tools": tools_data,
                        "clients": clients_data,
                        "roles": roles_data,
                        "signups_over_time": signups_over_time,
                        "queries_per_user": queries_per_user
                    }
        except Exception as e:
            logger.error(f"Dashboard Error: {e}")
            raise HTTPException(status_code=500, detail="Database error")

    app.include_router(api_router, prefix="/api")

    logger.info("Mounting FastMCP HTTP/SSE endpoints at /mcp")
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = 8001
    mcp.settings.transport_security = None
    
    from api.middleware.mcp_auth import MCPAuthMiddleware
    app.mount("/mcp", MCPAuthMiddleware(mcp.sse_app()))

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    frontend_dir = os.path.join(root_dir, "frontend")

    from fastapi.responses import FileResponse
    
    if os.path.exists(frontend_dir):
        logger.info(f"Mounting frontend from: {frontend_dir}")
        app.mount("/css", StaticFiles(directory=os.path.join(frontend_dir, "css")), name="css")
        app.mount("/js", StaticFiles(directory=os.path.join(frontend_dir, "js")), name="js")
        
        @app.get("/")
        def serve_index():
            return FileResponse(os.path.join(frontend_dir, "html", "index.html"))
            
        @app.get("/api-keys")
        def serve_api_keys():
            return FileResponse(os.path.join(frontend_dir, "html", "api-key.html"))
            
        @app.get("/docs")
        def serve_docs():
            return FileResponse(os.path.join(frontend_dir, "html", "docs.html"))
            
        @app.get("/maintainer")
        def serve_maintainer():
            return FileResponse(os.path.join(frontend_dir, "html", "maintainer.html"))
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
