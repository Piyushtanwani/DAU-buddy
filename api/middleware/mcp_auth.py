import hashlib
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
import logging
logger = logging.getLogger(__name__)
from core.database import db_connection
from api.context import user_role_var

def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

class MCPAuthMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8")

        async def send_error(status_code: int, detail: str, ws_code: int = 1008):
            if scope["type"] == "http":
                response = JSONResponse({"detail": detail}, status_code=status_code)
                await response(scope, receive, send)
            elif scope["type"] == "websocket":
                await send({
                    "type": "websocket.close",
                    "code": ws_code
                })

        if not auth_header.startswith("Bearer "):
            return await send_error(401, "Unauthorized")

        api_key = auth_header.split(" ", 1)[1].strip()
        hashed_k = hash_key(api_key)

        # Determine client name from headers
        client_name = "Unknown"
        x_client_name = headers.get(b"x-client-name")
        if x_client_name:
            client_name = x_client_name.decode("utf-8")
        else:
            user_agent = headers.get(b"user-agent")
            if user_agent:
                client_name = user_agent.decode("utf-8")

        def get_valid_role(h_key: str, client: str):
            # Returns ("ok", role, email), ("invalid", None, None) or
            # ("db_error", None, None). Only the SELECT decides auth.
            try:
                with db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT status, role, email FROM api_keys WHERE hashed_key = %s AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)", (h_key,))
                        row = cursor.fetchone()
            except Exception as e:
                logger.error(f"Auth DB error: {e}")
                return ("db_error", None, None)

            if not row or row[0] != "Active":
                return ("invalid", None, None)

            # Metrics only — a failed last_used update must never fail auth
            # (e.g. Postgres in read-only recovery after a restart).
            try:
                with db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("UPDATE api_keys SET last_used = CURRENT_TIMESTAMP, last_client = %s WHERE hashed_key = %s", (client, h_key))
            except Exception as e:
                logger.warning(f"Failed to update last_used (non-fatal): {e}")

            return ("ok", row[1], row[2])

        outcome, role, email = await run_in_threadpool(get_valid_role, hashed_k, client_name)

        if outcome == "db_error":
            return await send_error(503, "Authentication temporarily unavailable", ws_code=1013)
        if outcome != "ok":
            return await send_error(401, "Invalid, inactive, or expired API key")
        scope["user_role"] = role
        scope["user_email"] = email
        
        # Set ContextVars
        from api.context import user_role_var, user_email_var, client_name_var
        user_role_var.set(role)
        user_email_var.set(email)
        client_name_var.set(client_name)

        if scope["type"] == "http" and scope["path"].startswith("/mcp/messages") and scope["method"] == "POST":
            return await self.app(scope, receive, send)

        return await self.app(scope, receive, send)
