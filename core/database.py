import atexit
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from typing import Generator

from core import config

logger = config.get_logger("core.database")

# ==============================================================================
# PostgreSQL Threaded Connection Pool
# ==============================================================================
_connection_pool = None

def init_pool():
    global _connection_pool
    if _connection_pool is None:
        try:
            _db_config = config.get_db_config()
            logger.info("Initializing PostgreSQL ThreadedConnectionPool (min=1, max=10)...")
            _connection_pool = ThreadedConnectionPool(1, 10, **_db_config)
            logger.info("PostgreSQL ThreadedConnectionPool initialized successfully.")
        except Exception as e:
            logger.critical(f"Failed to initialize PostgreSQL Connection Pool: {e}")
            raise
    return _connection_pool


@contextmanager
def db_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Context manager that safely leases a connection from the pool and
    returns it automatically after use. Rolls back on error, commits on success.
    """
    pool = init_pool()
    conn = pool.getconn()
    
    # Perform a quick health check to handle connections closed by the server/proxy
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    except psycopg2.OperationalError:
        logger.warning("Pooled connection was dead, leasing a new one.")
        pool.putconn(conn, close=True)
        conn = pool.getconn()
        
    try:
        yield conn
    except Exception as e:
        logger.error(f"DB transaction error — rolling back: {e}")
        if not conn.closed:
            try:
                conn.rollback()
            except Exception as re:
                logger.error(f"Failed to rollback: {re}")
        raise
    else:
        if not conn.closed:
            conn.commit()
    finally:
        if '_connection_pool' in globals() and _connection_pool is not None:
            _connection_pool.putconn(conn, close=bool(conn.closed))


@atexit.register
def _shutdown_pool() -> None:
    """Close all pooled connections cleanly on process exit."""
    logger.info("Shutting down PostgreSQL Connection Pool...")
    if "_connection_pool" in globals() and _connection_pool is not None:
        _connection_pool.closeall()
        logger.info("PostgreSQL Connection Pool shut down cleanly.")
