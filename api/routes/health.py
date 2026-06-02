from fastapi import APIRouter, HTTPException
from core import config
from core.database import db_connection

logger = config.get_logger("api.routes.health")
router = APIRouter()


@router.get("/health")
async def health_endpoint():
    """
    Liveness probe — verifies that the database connection pool is responsive.
    Returns 200 OK when healthy, 500 when the database is unreachable.
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1;")
                cursor.fetchone()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Unhealthy: {str(e)}")
