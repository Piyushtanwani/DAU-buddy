import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from core import config
from api.routes import router as api_router

logger = config.get_logger("api.main")


def create_app() -> FastAPI:
    """
    Production FastAPI application factory.
    Registers CORS, all API routes, and mounts the frontend static files.
    """
    logger.info("Starting DA-IICT Faculty & Staff AI Buddy (Production)...")

    app = FastAPI(
        title="DA-IICT Faculty & Staff AI Buddy",
        description=(
            "Production-grade conversational search assistant for "
            "Dhirubhai Ambani University Faculty & Staff."
        ),
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── API routes (prefixed /api) ────────────────────────────────────────────
    app.include_router(api_router, prefix="/api")

    # ── Frontend static files ─────────────────────────────────────────────────
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
