"""Database connection and session management.

This module provides async SQLAlchemy engine and session factory setup
for PostgreSQL with asyncpg driver.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models.

    All models should inherit from this class to be properly
    registered with Alembic migrations.
    """

    pass


# Type alias for session factory
AsyncSessionFactory = async_sessionmaker[AsyncSession]


def get_engine(
    database_url: str,
    echo: bool = False,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_pre_ping: bool = True,
) -> AsyncEngine:
    """Create an async SQLAlchemy engine.

    Args:
        database_url: PostgreSQL connection URL. Can be either:
            - postgresql://user:pass@host:port/db
            - postgresql+asyncpg://user:pass@host:port/db
        echo: If True, log all SQL statements (useful for debugging)
        pool_size: Number of connections to keep in the pool
        max_overflow: Max additional connections beyond pool_size
        pool_pre_ping: If True, test connections before using them

    Returns:
        AsyncEngine instance configured for asyncpg

    Example:
        >>> engine = get_engine("postgresql://user:pass@localhost/saqshy")
        >>> async with engine.begin() as conn:
        ...     await conn.execute(text("SELECT 1"))
    """
    # Ensure we're using asyncpg driver
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    return create_async_engine(
        database_url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=pool_pre_ping,
        # Recommended settings for production
        pool_recycle=3600,  # Recycle connections after 1 hour
        pool_timeout=30,  # Wait up to 30s for a connection
    )


def get_session_factory(engine: AsyncEngine) -> AsyncSessionFactory:
    """Create an async session factory.

    Args:
        engine: AsyncEngine instance from get_engine()

    Returns:
        Session factory that creates AsyncSession instances

    Example:
        >>> engine = get_engine(database_url)
        >>> session_factory = get_session_factory(engine)
        >>> async with session_factory() as session:
        ...     result = await session.execute(select(User))
    """
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session(
    session_factory: AsyncSessionFactory,
) -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI/aiohttp to get a database session.

    This is a generator that yields a session and ensures it's
    closed after use, even if an exception occurs.

    Args:
        session_factory: Session factory from get_session_factory()

    Yields:
        AsyncSession instance

    Example (FastAPI):
        >>> @app.get("/users")
        >>> async def get_users(
        ...     session: AsyncSession = Depends(get_session)
        ... ):
        ...     return await session.execute(select(User))
    """
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
