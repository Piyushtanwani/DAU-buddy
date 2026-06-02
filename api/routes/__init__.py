from fastapi import APIRouter
from api.routes import chat, health

router = APIRouter()
router.include_router(chat.router, tags=["Chat"])
router.include_router(health.router, tags=["Health"])
