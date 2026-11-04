"""Database Session & Engine Management for AI News Aggregator.

Provides SQLAlchemy 2.0 engine configuration, thread-safe session factories,
and context-managed sessions with automatic commit/rollback.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

logger = logging.getLogger("ai_news.database")

# Load .env from project root if present
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)

DEFAULT_DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_news_db"


def get_database_url() -> str:
    """Retrieve normalized database URL from environment or fallback default."""
    url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL).strip()
    # Normalize legacy postgres:// and postgresql:// to explicit driver postgresql+psycopg2://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def get_engine(database_url: Optional[str] = None, echo: bool = False) -> Engine:
    """Create and configure a SQLAlchemy Engine.

    Supports PostgreSQL (psycopg2) and SQLite (for tests/fallback).
    """
    url = database_url or get_database_url()

    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        if ":memory:" in url:
            return create_engine(
                url,
                connect_args=connect_args,
                poolclass=StaticPool,
                echo=echo,
            )
        return create_engine(url, connect_args=connect_args, echo=echo)

    # PostgreSQL configuration with connection pooling
    return create_engine(
        url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=echo,
    )


# Global default engine and sessionmaker
engine: Engine = get_engine()
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_session_factory(custom_engine: Optional[Engine] = None) -> sessionmaker[Session]:
    """Get a sessionmaker bound to the given or default engine."""
    eng = custom_engine or engine
    return sessionmaker(
        bind=eng,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


@contextmanager
def get_db_session(
    factory: Optional[sessionmaker[Session]] = None,
) -> Generator[Session, None, None]:
    """Context manager for safe database transactions.

    Yields a Session, automatically commits on successful exit,
    and rolls back if any exception occurs.
    """
    maker = factory or SessionLocal
    session: Session = maker()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("Database session rollback due to exception: %s", e)
        raise
    finally:
        session.close()


def check_connection(target_engine: Optional[Engine] = None) -> bool:
    """Verify whether the database is reachable and accepting queries."""
    eng = target_engine or engine
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.debug("Database connection check failed: %s", e)
        return False


def dispose_engine(target_engine: Optional[Engine] = None) -> None:
    """Safely close and dispose all connection pool resources."""
    eng = target_engine or engine
    eng.dispose()

