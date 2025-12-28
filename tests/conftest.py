"""
SAQSHY Test Configuration

Pytest fixtures and configuration for all tests.

This module provides:
1. Core fixtures (MessageContext, Signals) defined locally
2. Telegram mocks imported from fixtures/telegram_mocks.py
3. Database fixtures imported from fixtures/database.py
4. Service mocks imported from fixtures/services.py
5. Scenario fixtures imported from fixtures/scenarios.py

Usage in tests:
    def test_something(mock_telegram_bot, test_db_session, mock_llm_service):
        # All fixtures are available via pytest discovery
        ...
"""

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from saqshy.core.types import (
    BehaviorSignals,
    ContentSignals,
    GroupType,
    MessageContext,
    NetworkSignals,
    ProfileSignals,
    Signals,
)

# =============================================================================
# Import fixtures from fixture modules
# =============================================================================

# Telegram mocks (pytest fixtures are auto-discovered when imported)
from tests.fixtures.telegram_mocks import (  # noqa: F401
    create_mock_chat,
    create_mock_message,
    create_mock_user,
    mock_bot_user,
    mock_callback_update,
    mock_channel,
    mock_link_message,
    mock_premium_user,
    mock_private_chat,
    mock_reply_message,
    mock_spam_message,
    mock_spam_user,
    mock_telegram_bot,
    mock_telegram_bot_with_admin,
    mock_telegram_chat,
    mock_telegram_message,
    mock_telegram_update,
    mock_telegram_user,
)

# Database fixtures
from tests.fixtures.database import (  # noqa: F401
    get_test_database_url,
    get_test_qdrant_url,
    get_test_redis_url,
    test_database_url,
    test_db_engine,
    test_db_session,
    test_db_session_committed,
    test_db_with_sample_data,
    test_qdrant_client,
    test_qdrant_collection,
    test_qdrant_url,
    test_redis_client,
    test_redis_pool,
    test_redis_url,
    test_session_factory,
    wait_for_postgres,
    wait_for_redis,
)

# Service mocks
from tests.fixtures.services import (  # noqa: F401
    MockLLMResult,
    ServicePatcher,
    SpamDBMatch,
    create_llm_result,
    mock_all_services,
    mock_channel_subscription_service,
    mock_channel_subscription_service_subscribed,
    mock_embeddings_service_realistic,
    mock_llm_result_allow,
    mock_llm_result_block,
    mock_llm_result_error,
    mock_llm_result_watch,
    mock_llm_service_unavailable,
    mock_spam_db_with_matches,
)

# Mini App auth mocks
from tests.fixtures.miniapp_auth import (  # noqa: F401
    TEST_BOT_TOKEN,
    MiniAppTestClient,
    create_mock_webapp_auth,
    create_mock_webapp_request,
    expired_init_data,
    generate_test_init_data,
    mock_admin_webapp_auth,
    mock_non_admin_webapp_auth,
    mock_webapp_user,
    valid_init_data,
)

# Note: Some fixtures defined below have the same names as imported ones.
# The local definitions take precedence for backward compatibility.
# New tests should prefer the more comprehensive fixtures from the modules.

# =============================================================================
# Message Context Fixtures
# =============================================================================


@pytest.fixture
def sample_message_context() -> MessageContext:
    """Create a sample MessageContext for testing."""
    return MessageContext(
        message_id=12345,
        chat_id=-1001234567890,
        user_id=987654321,
        text="Hello, this is a test message!",
        timestamp=datetime.now(UTC),
        username="testuser",
        first_name="Test",
        last_name="User",
        is_bot=False,
        is_premium=False,
        chat_type="supergroup",
        chat_title="Test Group",
        group_type=GroupType.GENERAL,
        has_media=False,
        is_forward=False,
    )


@pytest.fixture
def spam_message_context() -> MessageContext:
    """Create a spam-like MessageContext for testing."""
    return MessageContext(
        message_id=12346,
        chat_id=-1001234567890,
        user_id=123456789,
        text="URGENT! Double your Bitcoin NOW! DM me for guaranteed profits! 💰🚀",
        timestamp=datetime.now(UTC),
        username="user12345678",
        first_name="💰 Crypto 🚀",
        last_name="Profits 💵",
        is_bot=False,
        is_premium=False,
        chat_type="supergroup",
        chat_title="Test Group",
        group_type=GroupType.GENERAL,
        has_media=False,
        is_forward=True,
    )


@pytest.fixture
def trusted_user_context() -> MessageContext:
    """Create a trusted user MessageContext for testing."""
    return MessageContext(
        message_id=12347,
        chat_id=-1001234567890,
        user_id=111222333,
        text="Just sharing some thoughts on the topic.",
        timestamp=datetime.now(UTC),
        username="trustedmember",
        first_name="Trusted",
        last_name="Member",
        is_bot=False,
        is_premium=True,
        chat_type="supergroup",
        chat_title="Test Group",
        group_type=GroupType.GENERAL,
        has_media=False,
        is_forward=False,
    )


# =============================================================================
# Signal Fixtures
# =============================================================================


@pytest.fixture
def clean_signals() -> Signals:
    """Create clean (low risk) signals."""
    return Signals(
        profile=ProfileSignals(
            account_age_days=730,
            has_username=True,
            has_profile_photo=True,
            has_bio=True,
            has_first_name=True,
            has_last_name=True,
            is_premium=False,
            is_bot=False,
        ),
        content=ContentSignals(
            text_length=50,
            word_count=10,
            caps_ratio=0.1,
            emoji_count=1,
            url_count=0,
        ),
        behavior=BehaviorSignals(
            previous_messages_approved=15,
            is_channel_subscriber=True,
            channel_subscription_duration_days=30,
            is_first_message=False,
        ),
        network=NetworkSignals(
            spam_db_similarity=0.0,
        ),
    )


@pytest.fixture
def spam_signals() -> Signals:
    """Create spam-like (high risk) signals."""
    return Signals(
        profile=ProfileSignals(
            account_age_days=3,
            has_username=True,
            has_profile_photo=False,
            has_bio=True,
            has_first_name=True,
            has_last_name=False,
            is_premium=False,
            is_bot=False,
            username_has_random_chars=True,
            bio_has_crypto_terms=True,
            name_has_emoji_spam=True,
        ),
        content=ContentSignals(
            text_length=200,
            word_count=30,
            caps_ratio=0.6,
            emoji_count=8,
            url_count=3,
            has_shortened_urls=True,
            has_crypto_scam_phrases=True,
            has_urgency_patterns=True,
            has_wallet_addresses=True,
        ),
        behavior=BehaviorSignals(
            is_first_message=True,
            time_to_first_message_seconds=15,
            previous_messages_approved=0,
            is_channel_subscriber=False,
        ),
        network=NetworkSignals(
            spam_db_similarity=0.92,
            duplicate_messages_in_other_groups=3,
        ),
    )


# =============================================================================
# Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_cache_service() -> AsyncMock:
    """Create mock cache service."""
    cache = AsyncMock()
    cache.get.return_value = None
    cache.set.return_value = True
    cache.get_admin_status.return_value = None
    cache.get_channel_subscription.return_value = None
    return cache


@pytest.fixture
def mock_embeddings_service() -> AsyncMock:
    """Create mock embeddings service."""
    service = AsyncMock()
    service.embed_text.return_value = [0.0] * 1024
    service.embed_texts.return_value = [[0.0] * 1024]
    return service


@pytest.fixture
def mock_spam_db_service() -> AsyncMock:
    """Create mock spam database service."""
    service = AsyncMock()
    service.search.return_value = []
    service.get_max_similarity.return_value = (0.0, None)
    return service


@pytest.fixture
def mock_llm_service() -> AsyncMock:
    """Create mock LLM service."""
    service = AsyncMock()
    service.analyze_gray_zone.return_value = {
        "verdict": "allow",
        "confidence": 0.8,
        "reasoning": "Test reasoning",
    }
    return service


# =============================================================================
# Database Fixtures (for integration tests)
# =============================================================================


@pytest.fixture(scope="session")
def db_url() -> str:
    """
    Get database URL for integration tests.

    Uses TEST_DATABASE_URL environment variable if set,
    otherwise defaults to localhost:5433 (test postgres).
    """
    return os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://saqshy:password@localhost:5433/saqshy_test",
    )


@pytest.fixture
async def db_engine(db_url: str) -> AsyncGenerator[AsyncEngine, None]:
    """
    Create async database engine for integration tests.

    Creates a fresh engine per test function for proper async loop handling.
    The engine is disposed after the test completes.
    """
    from saqshy.db import get_engine

    engine = get_engine(db_url, echo=False, pool_size=5, max_overflow=10)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """
    Create database session for integration tests.

    This fixture:
    1. Creates all tables before each test
    2. Yields a fresh session for the test to use
    3. Rolls back any changes after the test
    4. Drops all tables to ensure test isolation

    Note: This requires a test database to be available.
    Set TEST_DATABASE_URL or ensure postgres is running on localhost:5433.
    """
    from sqlalchemy import text

    from saqshy.db import Base

    # Create PostgreSQL extensions and enum types before creating tables
    async with db_engine.begin() as conn:
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

    # Create all tables before test
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session factory and session for this test
    session_factory = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with session_factory() as session:
        try:
            yield session
        finally:
            # Always rollback to discard any uncommitted changes
            await session.rollback()

    # Drop all tables after test for isolation
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    # Drop enum types as well
    async with db_engine.begin() as conn:
        await conn.execute(text("DROP TYPE IF EXISTS group_type_enum CASCADE"))
        await conn.execute(text("DROP TYPE IF EXISTS trust_level_enum CASCADE"))
        await conn.execute(text("DROP TYPE IF EXISTS verdict_enum CASCADE"))


@pytest.fixture
async def db_session_committed(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """
    Create database session that commits changes.

    Unlike db_session, this fixture commits changes which is useful for
    tests that need to verify data persistence across operations.

    Use this when you need to:
    - Test repository commit behavior
    - Verify data is actually persisted
    - Test concurrent access patterns
    """
    from sqlalchemy import text

    from saqshy.db import Base

    # Create PostgreSQL extensions and enum types before creating tables
    async with db_engine.begin() as conn:
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

    # Create all tables before test
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with session_factory() as session:
        yield session
        # Commit is the test's responsibility
        # We just close the session here

    # Drop all tables after test for isolation
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    # Drop enum types as well
    async with db_engine.begin() as conn:
        await conn.execute(text("DROP TYPE IF EXISTS group_type_enum CASCADE"))
        await conn.execute(text("DROP TYPE IF EXISTS trust_level_enum CASCADE"))
        await conn.execute(text("DROP TYPE IF EXISTS verdict_enum CASCADE"))


# =============================================================================
# Helper Functions
# =============================================================================


def create_message_context(**kwargs: Any) -> MessageContext:
    """
    Create MessageContext with custom values.

    Provides sensible defaults that can be overridden.
    """
    defaults: dict[str, Any] = {
        "message_id": 1,
        "chat_id": -1001234567890,
        "user_id": 123456789,
        "text": "Test message",
        "timestamp": datetime.now(UTC),
        "chat_type": "supergroup",
        "group_type": GroupType.GENERAL,
    }
    defaults.update(kwargs)
    return MessageContext(**defaults)


def create_signals(**kwargs: Any) -> Signals:
    """
    Create Signals with custom values.

    Accepts nested dicts for profile, content, behavior, network.
    """
    profile_kwargs = kwargs.pop("profile", {})
    content_kwargs = kwargs.pop("content", {})
    behavior_kwargs = kwargs.pop("behavior", {})
    network_kwargs = kwargs.pop("network", {})

    return Signals(
        profile=ProfileSignals(**profile_kwargs),
        content=ContentSignals(**content_kwargs),
        behavior=BehaviorSignals(**behavior_kwargs),
        network=NetworkSignals(**network_kwargs),
    )
