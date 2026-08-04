"""
Database Connection Pool

SQLAlchemy engine and session management for the trading system.
Reads DATABASE_URL from environment variables.

`DatabasePool` is a **per-URL singleton**: the ~50 call sites that do a bare
`DatabasePool()` all share one engine, so the process holds one connection pool
instead of one per call site. Abandoned engines used to keep up to `pool_size`
connections open forever, which exhausted the shared Postgres server
("remaining connection slots are reserved for roles with the SUPERUSER
attribute"). Prefer `get_pool()` in new code.
"""

import os
import logging
import threading
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

load_dotenv()
logger = logging.getLogger(__name__)

# Sized for a shared Postgres (max_connections=100) hosting several apps.
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "5"))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))  # drop conns older than 30m
POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "10"))    # fail fast instead of hanging
APPLICATION_NAME = os.getenv("DB_APPLICATION_NAME", "alpatrade")


class DatabasePool:
    """SQLAlchemy connection pool with session context manager.

    Instances are cached per database URL, so repeated `DatabasePool()` calls
    return the same object and share a single engine.
    """

    _instances: dict[str, "DatabasePool"] = {}
    _lock = threading.Lock()

    def __new__(cls, database_url: str = None):
        url = database_url or os.getenv("DATABASE_URL")
        if not url:
            raise ValueError(
                "DATABASE_URL not set. Provide it as argument or set the "
                "DATABASE_URL environment variable."
            )
        instance = cls._instances.get(url)
        if instance is not None:
            return instance
        with cls._lock:
            # Re-check under the lock: another thread may have won the race.
            instance = cls._instances.get(url)
            if instance is None:
                instance = super().__new__(cls)
                instance._setup(url)
                cls._instances[url] = instance
        return instance

    def __init__(self, database_url: str = None):
        # Real initialization happens once, in _setup() via __new__.
        pass

    def _setup(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = create_engine(
            database_url,
            pool_size=POOL_SIZE,
            max_overflow=MAX_OVERFLOW,
            pool_recycle=POOL_RECYCLE,
            pool_timeout=POOL_TIMEOUT,
            pool_pre_ping=True,
            connect_args={"application_name": APPLICATION_NAME},
        )
        self._session_factory = sessionmaker(bind=self.engine)
        logger.info(
            "Database pool initialized (size=%s overflow=%s recycle=%ss)",
            POOL_SIZE, MAX_OVERFLOW, POOL_RECYCLE,
        )

    @contextmanager
    def get_session(self) -> Session:
        """Yield a session that auto-commits on success, rolls back on error."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self):
        """Close all pooled connections. The engine stays usable (SQLAlchemy
        lazily builds a fresh pool on the next checkout)."""
        self.engine.dispose()
        logger.info("Database pool disposed")


def get_pool(database_url: str = None) -> DatabasePool:
    """Return the shared pool for `database_url` (defaults to DATABASE_URL)."""
    return DatabasePool(database_url)


def reset_pools() -> None:
    """Dispose and forget every cached pool. For tests and shutdown hooks."""
    with DatabasePool._lock:
        instances = list(DatabasePool._instances.values())
        DatabasePool._instances.clear()
    for pool in instances:
        try:
            pool.engine.dispose()
        except Exception:  # noqa: BLE001 - best effort during teardown
            logger.warning("Failed disposing pool", exc_info=True)
