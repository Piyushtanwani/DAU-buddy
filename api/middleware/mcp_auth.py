import hashlib
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.concurrency import run_in_threadpool
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

        async def send_unauthorized(detail: str):
            if scope["type"] == "http":
                response = JSONResponse({"detail": detail}, status_code=401)
                await response(scope, receive, send)
            elif scope["type"] == "websocket":
                await send({
                    "type": "websocket.close",
                    "code": 1008
                })

        if not auth_header.startswith("Bearer "):
            return await send_unauthorized("Unauthorized")

        api_key = auth_header.split(" ", 1)[1].strip()
        hashed_k = hash_key(api_key)

        def get_valid_role(h_key: str):
            try:
                with db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT status, role FROM api_keys WHERE hashed_key = %s AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)", (h_key,))
                        row = cursor.fetchone()
                        if row and row[0] == "Active":
                            cursor.execute("UPDATE api_keys SET last_used = CURRENT_TIMESTAMP WHERE hashed_key = %s", (h_key,))
                            return row[1]
            except Exception:
                pass
            return None

        role = await run_in_threadpool(get_valid_role, hashed_k)

        if not role:
            return await send_unauthorized("Invalid, inactive, or expired API key")

        scope["user_role"] = role
        user_role_var.set(role)

        return await self.app(scope, receive, send)
