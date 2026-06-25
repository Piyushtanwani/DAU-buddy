from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from core.database import db_connection

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

        def is_key_valid(key: str) -> bool:
            try:
                with db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT status FROM api_keys WHERE hashed_key = %s", (key,))
                        row = cursor.fetchone()
                        if row and row[0] == "Active":
                            cursor.execute("UPDATE api_keys SET last_used = CURRENT_TIMESTAMP WHERE hashed_key = %s", (key,))
                            return True
            except Exception:
                pass
            return False

        valid = await run_in_threadpool(is_key_valid, api_key)

        if not valid:
            return await send_unauthorized("Invalid or inactive API key")

        return await self.app(scope, receive, send)
