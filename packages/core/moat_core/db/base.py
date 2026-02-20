"""
moat_core.db.base
~~~~~~~~~~~~~~~~~
SQLAlchemy async engine, session factory, and declarative base.

Supports both PostgreSQL (asyncpg) and SQLite (aiosqlite) backends
via the DATABASE_URL connection string.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all Moat ORM models."""


def create_engine(url: str, echo: bool = False) -> AsyncEngine:
    """Create an async SQLAlchemy engine from a database URL.

    Args:
        url: Database connection string. Supported formats:
            - ``postgresql+asyncpg://user:pass@host:5432/db``
            - ``sqlite+aiosqlite:///./local.db``
        echo: If True, log all SQL statements (useful for debugging).

    Returns:
        An :class:`~sqlalchemy.ext.asyncio.AsyncEngine` instance.
    """
    kwargs: dict = {"echo": echo}

    # SQLite requires special handling for async access.
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}

    return create_async_engine(url, **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to *engine*.

    Sessions created by this factory do NOT expire on commit, which
    avoids lazy-load issues in async code.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_tables(engine: AsyncEngine) -> None:
    """Create all tables defined on :class:`Base` if they do not exist.

    Safe to call repeatedly - uses ``CREATE TABLE IF NOT EXISTS``.
    In production, prefer Alembic migrations over this function.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
