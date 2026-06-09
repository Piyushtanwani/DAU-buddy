from fastapi import APIRouter
from api.routes import chat, health, library

router = APIRouter()
router.include_router(chat.router, tags=["Chat"])
router.include_router(health.router, tags=["Health"])
router.include_router(library.router, prefix="/v1/library", tags=["Library"])

