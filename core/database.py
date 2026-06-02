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
try:
    _db_config = config.get_db_config()
    logger.info("Initializing PostgreSQL ThreadedConnectionPool (min=1, max=10)...")
    _connection_pool = ThreadedConnectionPool(1, 10, **_db_config)
    logger.info("PostgreSQL ThreadedConnectionPool initialized successfully.")
except Exception as e:
    logger.critical(f"Failed to initialize PostgreSQL Connection Pool: {e}")
    raise


@contextmanager
def db_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Context manager that safely leases a connection from the pool and
    returns it automatically after use. Rolls back on error, commits on success.
    """
    conn = _connection_pool.getconn()
    try:
        yield conn
    except Exception as e:
        logger.error(f"DB transaction error — rolling back: {e}")
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        _connection_pool.putconn(conn)


@atexit.register
def _shutdown_pool() -> None:
    """Close all pooled connections cleanly on process exit."""
    logger.info("Shutting down PostgreSQL Connection Pool...")
    if "_connection_pool" in globals():
        _connection_pool.closeall()
        logger.info("PostgreSQL Connection Pool shut down cleanly.")
