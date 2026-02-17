"""
Database Connection Pool

SQLAlchemy engine and session management for the trading system.
Reads DATABASE_URL from environment variables.
"""

import os
import logging
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

load_dotenv()
logger = logging.getLogger(__name__)


class DatabasePool:
    """SQLAlchemy connection pool with session context manager."""

    def __init__(self, database_url: str = None):
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError(
                "DATABASE_URL not set. Provide it as argument or set the "
                "DATABASE_URL environment variable."
            )

        self.engine = create_engine(
            self.database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
        self._session_factory = sessionmaker(bind=self.engine)
        logger.info("Database pool initialized")

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
        """Dispose of the engine and all connections."""
        self.engine.dispose()
        logger.info("Database pool disposed")
