"""Lazy database setup: importing the API never requires a live database."""
from functools import lru_cache
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine():
    return create_engine(get_settings().effective_database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def get_db():
    """Yield a session. Apply schema changes explicitly with Alembic before startup."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
