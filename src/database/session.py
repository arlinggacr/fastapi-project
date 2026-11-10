"""Database session and engine.

Importing :mod:`src.database.models` at the bottom registers every entity, so
relationships resolve regardless of which module is imported first.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_settings
from src.database.base import Base

settings = get_settings()

engine = create_async_engine(
    settings.sqlalchemy_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    async with SessionLocal() as session:
        yield session


__all__ = ["Base", "SessionLocal", "engine", "get_session"]

# Registers all entities (side effect only) - keep this import last.
import src.database.models  # noqa: E402, F401
