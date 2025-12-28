"""
SAQSHY Test Fixtures - Database

Provides async database fixtures for integration testing:
- Test database engine with proper cleanup
- Isolated session fixtures with automatic rollback
- Session factory for repository testing
- Redis test client fixture

These fixtures require the test containers from docker-compose.test.yml
to be running. Use pytest markers to skip if containers are unavailable.

Environment Variables:
    TEST_DATABASE_URL: PostgreSQL connection URL (default: localhost:5434)
    TEST_REDIS_URL: Redis connection URL (default: localhost:6380)
    TEST_QDRANT_URL: Qdrant connection URL (default: localhost:6335)
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


# =============================================================================
# Environment Configuration
# =============================================================================


def get_test_database_url() -> str:
    """
    Get test database URL from environment or default.

    Default connects to the test PostgreSQL container on port 5434.
    """
    return os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://saqshy_test:test_password@localhost:5434/saqshy_test",
    )


def get_test_redis_url() -> str:
    """
    Get test Redis URL from environment or default.

    Default connects to the test Redis container on port 6380.
    """
    return os.getenv("TEST_REDIS_URL", "redis://localhost:6380/0")


def get_test_qdrant_url() -> str:
    """
    Get test Qdrant URL from environment or default.

    Default connects to the test Qdrant container on port 6335.
    """
    return os.getenv("TEST_QDRANT_URL", "http://localhost:6335")


# =============================================================================
# Database URL Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """
    Get test database URL for the session.

    This is a session-scoped fixture to ensure consistent URL across tests.
    """
    return get_test_database_url()


@pytest.fixture(scope="session")
def test_redis_url() -> str:
    """Get test Redis URL for the session."""
    return get_test_redis_url()


@pytest.fixture(scope="session")
def test_qdrant_url() -> str:
    """Get test Qdrant URL for the session."""
    return get_test_qdrant_url()


# =============================================================================
# Database Engine Fixtures
# =============================================================================


@pytest.fixture(scope="session")
async def test_db_engine(test_database_url: str) -> AsyncGenerator[AsyncEngine, None]:
    """
    Create test database engine (session-scoped).

    The engine is shared across all tests in the session for efficiency.
    Tables are created once at session start and dropped at session end.

    This fixture requires the test PostgreSQL container to be running:
        docker compose -f docker/docker-compose.test.yml up postgres-test

    Yields:
        AsyncEngine: Configured async engine for test database
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from saqshy.db import Base

    engine = create_async_engine(
        test_database_url,
        echo=False,  # Set to True for SQL debugging
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )

    # Create PostgreSQL extensions and enum types before creating tables
    # SQLAlchemy's create_all doesn't handle these properly for fresh DBs
    async with engine.begin() as conn:
        # Create required extensions
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pg_trgm"'))

        # Create enum types if they don't exist
        await conn.execute(text("""
            DO $$ BEGIN
                CREATE TYPE group_type_enum AS ENUM ('general', 'tech', 'deals', 'crypto');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        await conn.execute(text("""
            DO $$ BEGIN
                CREATE TYPE trust_level_enum AS ENUM ('new', 'sandbox', 'limited', 'trusted', 'admin');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        await conn.execute(text("""
            DO $$ BEGIN
                CREATE TYPE verdict_enum AS ENUM ('allow', 'watch', 'limit', 'review', 'block');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))

    # Create all tables at session start
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables at session end
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    # Drop enum types as well
    async with engine.begin() as conn:
        await conn.execute(text("DROP TYPE IF EXISTS group_type_enum CASCADE"))
        await conn.execute(text("DROP TYPE IF EXISTS trust_level_enum CASCADE"))
        await conn.execute(text("DROP TYPE IF EXISTS verdict_enum CASCADE"))

    await engine.dispose()


@pytest.fixture
async def test_db_session(
    test_db_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Create isolated test database session with automatic rollback.

    Each test gets a fresh session that is rolled back after the test,
    ensuring complete isolation between tests without the overhead
    of recreating tables.

    Usage:
        async def test_something(test_db_session):
            repo = GroupRepository(test_db_session)
            group = await repo.create(chat_id=-1001234567890, title="Test")
            # Changes are automatically rolled back after test

    Yields:
        AsyncSession: Isolated session for the test
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session_factory = async_sessionmaker(
        test_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with session_factory() as session:
        # Start a savepoint for this test
        async with session.begin():
            yield session
            # Rollback to savepoint after test (implicit on exit)


@pytest.fixture
async def test_db_session_committed(
    test_db_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Create database session that commits changes.

    Unlike test_db_session, this fixture allows commits which is useful
    for tests that need to verify data persistence across operations.

    WARNING: This fixture clears ALL tables after each test to maintain
    isolation. Use test_db_session when rollback is sufficient.

    Usage:
        async def test_persistence(test_db_session_committed):
            repo = GroupRepository(test_db_session_committed)
            group = await repo.create(chat_id=-1001234567890, title="Test")
            await test_db_session_committed.commit()
            # Data is committed and visible in other sessions

    Yields:
        AsyncSession: Session that allows commits
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from saqshy.db import Base

    session_factory = async_sessionmaker(
        test_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with session_factory() as session:
        yield session

    # Clean up: truncate all tables after test
    async with test_db_engine.begin() as conn:
        # Get all table names and truncate them
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"TRUNCATE TABLE {table.name} CASCADE"))


@pytest.fixture
def test_session_factory(
    test_db_engine: AsyncEngine,
) -> async_sessionmaker:
    """
    Get session factory for repository testing.

    Useful when you need to create multiple sessions or test
    repository initialization patterns.

    Usage:
        async def test_repo(test_session_factory):
            async with test_session_factory() as session:
                repo = GroupRepository(session)
                ...

    Returns:
        async_sessionmaker: Factory that creates AsyncSession instances
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    return async_sessionmaker(
        test_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


# =============================================================================
# Redis Fixtures
# =============================================================================


@pytest.fixture(scope="session")
async def test_redis_pool(test_redis_url: str) -> AsyncGenerator[Redis, None]:
    """
    Create test Redis connection pool (session-scoped).

    The pool is shared across tests for efficiency. Each test should
    use test_redis_client for an isolated client.

    Requires the test Redis container:
        docker compose -f docker/docker-compose.test.yml up redis-test

    Yields:
        Redis: Async Redis client with connection pool
    """
    import redis.asyncio as redis

    pool = redis.ConnectionPool.from_url(
        test_redis_url,
        max_connections=10,
        decode_responses=True,
    )
    client = redis.Redis(connection_pool=pool)

    # Verify connection
    try:
        await client.ping()
    except redis.ConnectionError as e:
        pytest.skip(f"Redis not available: {e}")

    yield client

    await client.aclose()


@pytest.fixture
async def test_redis_client(
    test_redis_pool: Redis,
) -> AsyncGenerator[Redis, None]:
    """
    Create isolated Redis client for each test.

    The test database (0) is flushed after each test to ensure isolation.

    Usage:
        async def test_cache(test_redis_client):
            await test_redis_client.set("key", "value")
            result = await test_redis_client.get("key")
            # Database is flushed after test

    Yields:
        Redis: Isolated Redis client for the test
    """
    yield test_redis_pool

    # Flush test database after each test
    await test_redis_pool.flushdb()


# =============================================================================
# Qdrant Fixtures
# =============================================================================


@pytest.fixture(scope="session")
async def test_qdrant_client(test_qdrant_url: str):
    """
    Create test Qdrant client (session-scoped).

    The client is shared across tests. Collections should be created
    and cleaned up in individual tests.

    Requires the test Qdrant container:
        docker compose -f docker/docker-compose.test.yml up qdrant-test

    Yields:
        AsyncQdrantClient: Configured Qdrant client
    """
    from qdrant_client import AsyncQdrantClient

    # Extract host and port from URL
    url = test_qdrant_url.replace("http://", "")
    host, port = url.split(":")

    client = AsyncQdrantClient(host=host, port=int(port))

    # Verify connection
    try:
        await client.get_collections()
    except Exception as e:
        pytest.skip(f"Qdrant not available: {e}")

    yield client

    await client.close()


@pytest.fixture
async def test_qdrant_collection(test_qdrant_client, request):
    """
    Create a unique test collection in Qdrant.

    The collection is automatically deleted after the test.
    Collection name includes the test name for debugging.

    Usage:
        async def test_embeddings(test_qdrant_collection):
            collection_name = test_qdrant_collection
            # Collection is created and cleaned up automatically

    Yields:
        str: Name of the test collection
    """
    from qdrant_client.http import models as qdrant_models

    # Create unique collection name based on test
    test_name = request.node.name.replace("[", "_").replace("]", "_")
    collection_name = f"test_{test_name}"

    # Create collection with standard embedding dimensions
    await test_qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=qdrant_models.VectorParams(
            size=1024,  # Cohere embed-multilingual-v3.0 dimension
            distance=qdrant_models.Distance.COSINE,
        ),
    )

    yield collection_name

    # Cleanup: delete collection after test
    await test_qdrant_client.delete_collection(collection_name)


# =============================================================================
# Combined Database Fixtures
# =============================================================================


@pytest.fixture
async def test_db_with_sample_data(
    test_db_session: AsyncSession,
) -> AsyncGenerator[dict, None]:
    """
    Create database session with pre-populated sample data.

    Useful for tests that need existing records to work with.
    Data is rolled back after the test.

    Returns a dict with created objects:
        - group: Sample Group record
        - user: Sample User record
        - member: Sample GroupMember record

    Usage:
        async def test_with_data(test_db_with_sample_data):
            data = test_db_with_sample_data
            group = data["group"]
            user = data["user"]
            ...
    """
    from saqshy.db import (
        DecisionRepository,
        Group,
        GroupMember,
        GroupMemberRepository,
        GroupRepository,
        GroupType,
        TrustLevel,
        User,
        UserRepository,
    )

    # Create repositories
    group_repo = GroupRepository(test_db_session)
    user_repo = UserRepository(test_db_session)
    member_repo = GroupMemberRepository(test_db_session)

    # Create sample group
    group, _ = await group_repo.create_or_update(
        chat_id=-1001234567890,
        title="Test Group",
        group_type=GroupType.GENERAL,
        is_active=True,
    )

    # Create sample user
    user, _ = await user_repo.create_or_update(
        user_id=123456789,
        username="testuser",
        first_name="Test",
        last_name="User",
    )

    # Create group membership
    member = await member_repo.add_member(
        group_id=group.id,
        user_id=user.id,
        trust_level=TrustLevel.TRUSTED,
    )

    await test_db_session.flush()

    yield {
        "group": group,
        "user": user,
        "member": member,
        "session": test_db_session,
    }


# =============================================================================
# Helper Functions
# =============================================================================


async def wait_for_postgres(url: str, timeout: float = 30.0) -> bool:
    """
    Wait for PostgreSQL to become available.

    Useful for CI environments where containers may take time to start.

    Args:
        url: PostgreSQL connection URL
        timeout: Maximum seconds to wait

    Returns:
        True if connection succeeded, False if timeout
    """
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    start = asyncio.get_event_loop().time()

    while (asyncio.get_event_loop().time() - start) < timeout:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                await engine.dispose()
                return True
        except Exception:
            await asyncio.sleep(0.5)

    await engine.dispose()
    return False


async def wait_for_redis(url: str, timeout: float = 30.0) -> bool:
    """
    Wait for Redis to become available.

    Args:
        url: Redis connection URL
        timeout: Maximum seconds to wait

    Returns:
        True if connection succeeded, False if timeout
    """
    import asyncio

    import redis.asyncio as redis

    start = asyncio.get_event_loop().time()

    while (asyncio.get_event_loop().time() - start) < timeout:
        try:
            client = redis.from_url(url)
            await client.ping()
            await client.aclose()
            return True
        except Exception:
            await asyncio.sleep(0.5)

    return False


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # URL helpers
    "get_test_database_url",
    "get_test_redis_url",
    "get_test_qdrant_url",
    # URL fixtures
    "test_database_url",
    "test_redis_url",
    "test_qdrant_url",
    # Database fixtures
    "test_db_engine",
    "test_db_session",
    "test_db_session_committed",
    "test_session_factory",
    # Redis fixtures
    "test_redis_pool",
    "test_redis_client",
    # Qdrant fixtures
    "test_qdrant_client",
    "test_qdrant_collection",
    # Combined fixtures
    "test_db_with_sample_data",
    # Helper functions
    "wait_for_postgres",
    "wait_for_redis",
]
