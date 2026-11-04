"""Database package for AI News Aggregator.

Exposes SQLAlchemy models, session management, and CRUD repositories.
"""

from app.database.init_db import create_tables, init_db, seed_initial_data
from app.database.models import Article, Base, Digest, Source, Subscriber, utc_now
from app.database.repository import (
    ArticleRepository,
    DigestRepository,
    NewsRepository,
    SourceRepository,
    SubscriberRepository,
)
from app.database.session import (
    SessionLocal,
    check_connection,
    engine,
    get_database_url,
    get_db_session,
    get_engine,
    get_session_factory,
)

__all__ = [
    # Models
    "Base",
    "Source",
    "Article",
    "Digest",
    "Subscriber",
    "utc_now",
    # Session & Engine
    "engine",
    "SessionLocal",
    "get_engine",
    "get_session_factory",
    "get_db_session",
    "get_database_url",
    "check_connection",
    # Scripts & Initializers
    "create_tables",
    "init_db",
    "seed_initial_data",
    # Repositories
    "NewsRepository",
    "SourceRepository",
    "ArticleRepository",
    "DigestRepository",
    "SubscriberRepository",
]
