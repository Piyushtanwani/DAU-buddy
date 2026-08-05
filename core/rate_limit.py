"""
Shared SlowAPI limiter.

Lives in `core` so that both `api.main` (which registers it on the app) and the
route modules (which decorate endpoints with it) can import it without a
circular import — `api.main` imports the routers, so the routers cannot import
back from `api.main`.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request

def auth_or_ip(request: Request) -> str:
    """Use the verified email if authentication succeeded, fallback to IP."""
    if hasattr(request.state, "email") and request.state.email:
        return request.state.email
    return get_remote_address(request)

limiter = Limiter(key_func=auth_or_ip)
