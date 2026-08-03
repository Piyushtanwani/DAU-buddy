"""
Shared SlowAPI limiter.

Lives in `core` so that both `api.main` (which registers it on the app) and the
route modules (which decorate endpoints with it) can import it without a
circular import — `api.main` imports the routers, so the routers cannot import
back from `api.main`.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
