"""
SAQSHY Test Fixtures

Provides comprehensive test fixtures for the SAQSHY anti-spam system:

1. Scenario Fixtures (scenarios.py):
   - Profile fixtures (spammer, trusted user patterns)
   - Behavior fixtures (first message, flood, channel subscriber)
   - Content fixtures (crypto scam, link bomb, clean messages)
   - Network fixtures (spam DB matches, blocklist, whitelist)
   - Combined scenario fixtures for integration testing

2. Telegram Mocks (telegram_mocks.py):
   - Mock Telegram users (regular, spam, premium, bot)
   - Mock Telegram chats (group, supergroup, channel, private)
   - Mock Telegram messages with all required fields
   - Mock Bot with all API methods mocked
   - Mock Updates for webhook testing

3. Database Fixtures (database.py):
   - Test database engine with automatic cleanup
   - Isolated session fixtures with rollback
   - Redis client fixtures
   - Qdrant client fixtures

4. Service Mocks (services.py):
   - LLM Service mocks with controlled verdicts
   - SpamDB Service mocks with configurable matches
   - Cache Service mocks with in-memory storage
   - Embeddings Service mocks
   - Channel Subscription Service mocks

Usage:
    # In conftest.py or test files
    from tests.fixtures import (
        SCENARIO_CRYPTO_SCAM_ATTACK,
        mock_telegram_bot,
        test_db_session,
        mock_llm_service,
    )
"""

# =============================================================================
# Scenario Fixtures (core test data)
# =============================================================================

from tests.fixtures.scenarios import (
    # Profile fixtures
    SPAMMER_NEW_ACCOUNT,
    SPAMMER_CRYPTO_BIO,
    SPAMMER_EMOJI_NAME,
    TRUSTED_VETERAN,
    TRUSTED_REGULAR,
    NEUTRAL_NEW_USER,
    # Behavior fixtures
    BEHAVIOR_FIRST_MESSAGE_FAST,
    BEHAVIOR_FLOOD,
    BEHAVIOR_PREVIOUSLY_BLOCKED,
    BEHAVIOR_CHANNEL_SUBSCRIBER_LONG,
    BEHAVIOR_CHANNEL_SUBSCRIBER_NEW,
    BEHAVIOR_TRUSTED_ENGAGED,
    BEHAVIOR_NEUTRAL,
    # Content fixtures
    CONTENT_CRYPTO_SCAM,
    CONTENT_LINK_BOMB,
    CONTENT_EXCESSIVE_CAPS,
    CONTENT_CLEAN,
    CONTENT_DEALS_PROMO,
    CONTENT_TECH_GITHUB,
    CONTENT_CRYPTO_DISCUSSION,
    CONTENT_LIGHT_PROMO,
    # Network fixtures
    NETWORK_SPAM_HIGH,
    NETWORK_BLOCKLISTED,
    NETWORK_RAID,
    NETWORK_CLEAN,
    NETWORK_WHITELISTED,
    # Scenario fixtures
    SCENARIO_CRYPTO_SCAM_ATTACK,
    SCENARIO_LINK_BOMB_RAID,
    SCENARIO_BLOCKLISTED_USER,
    SCENARIO_TRUSTED_SUBSCRIBER,
    SCENARIO_WHITELISTED_USER,
    SCENARIO_DEALS_AFFILIATE_LINK,
    SCENARIO_TECH_MULTIPLE_LINKS,
    SCENARIO_CRYPTO_WALLET_SHARE,
    SCENARIO_NEW_USER_PROMO,
    # Types
    ScenarioFixture,
    ProfileFixture,
    BehaviorFixture,
    ContentFixture,
    NetworkFixture,
    # Helpers
    create_signals,
    create_message_context,
    get_all_scenarios,
    get_spam_scenarios,
    get_trust_scenarios,
    get_false_positive_scenarios,
    get_gray_zone_scenarios,
)

# =============================================================================
# Telegram Mocks
# =============================================================================

from tests.fixtures.telegram_mocks import (
    # User fixtures (pytest)
    mock_telegram_user,
    mock_spam_user,
    mock_premium_user,
    mock_bot_user,
    # Chat fixtures (pytest)
    mock_telegram_chat,
    mock_private_chat,
    mock_channel,
    # Message fixtures (pytest)
    mock_telegram_message,
    mock_spam_message,
    mock_link_message,
    mock_reply_message,
    # Bot fixtures (pytest)
    mock_telegram_bot,
    mock_telegram_bot_with_admin,
    # Update fixtures (pytest)
    mock_telegram_update,
    mock_callback_update,
    # Helper functions
    create_mock_user,
    create_mock_chat,
    create_mock_message,
)

# =============================================================================
# Database Fixtures
# =============================================================================

from tests.fixtures.database import (
    # URL helpers
    get_test_database_url,
    get_test_redis_url,
    get_test_qdrant_url,
    # URL fixtures (pytest)
    test_database_url,
    test_redis_url,
    test_qdrant_url,
    # Database fixtures (pytest)
    test_db_engine,
    test_db_session,
    test_db_session_committed,
    test_session_factory,
    # Redis fixtures (pytest)
    test_redis_pool,
    test_redis_client,
    # Qdrant fixtures (pytest)
    test_qdrant_client,
    test_qdrant_collection,
    # Combined fixtures (pytest)
    test_db_with_sample_data,
    # Helper functions
    wait_for_postgres,
    wait_for_redis,
)

# =============================================================================
# Service Mocks
# =============================================================================

from tests.fixtures.services import (
    # LLM types and helpers
    MockLLMResult,
    create_llm_result,
    # LLM fixtures (pytest)
    mock_llm_result_allow,
    mock_llm_result_block,
    mock_llm_result_watch,
    mock_llm_result_error,
    mock_llm_service,
    mock_llm_service_unavailable,
    # SpamDB types
    SpamDBMatch,
    # SpamDB fixtures (pytest)
    mock_spam_db_service,
    mock_spam_db_with_matches,
    # Cache fixtures (pytest)
    mock_cache_service,
    mock_cache_service_with_history,
    # Embeddings fixtures (pytest)
    mock_embeddings_service,
    mock_embeddings_service_realistic,
    # Channel subscription fixtures (pytest)
    mock_channel_subscription_service,
    mock_channel_subscription_service_subscribed,
    # Combined fixtures (pytest)
    mock_all_services,
    # Utilities
    ServicePatcher,
)

# =============================================================================
# Mini App Auth Fixtures
# =============================================================================

from tests.fixtures.miniapp_auth import (
    # Constants
    TEST_BOT_TOKEN,
    # Helper functions
    generate_test_init_data,
    create_mock_webapp_auth,
    create_mock_webapp_request,
    # Fixtures (pytest)
    mock_webapp_user,
    mock_admin_webapp_auth,
    mock_non_admin_webapp_auth,
    valid_init_data,
    expired_init_data,
    # Test client
    MiniAppTestClient,
)

# =============================================================================
# Public API
# =============================================================================

__all__ = [
    # =========================================================================
    # Scenario Fixtures
    # =========================================================================
    # Profile fixtures
    "SPAMMER_NEW_ACCOUNT",
    "SPAMMER_CRYPTO_BIO",
    "SPAMMER_EMOJI_NAME",
    "TRUSTED_VETERAN",
    "TRUSTED_REGULAR",
    "NEUTRAL_NEW_USER",
    # Behavior fixtures
    "BEHAVIOR_FIRST_MESSAGE_FAST",
    "BEHAVIOR_FLOOD",
    "BEHAVIOR_PREVIOUSLY_BLOCKED",
    "BEHAVIOR_CHANNEL_SUBSCRIBER_LONG",
    "BEHAVIOR_CHANNEL_SUBSCRIBER_NEW",
    "BEHAVIOR_TRUSTED_ENGAGED",
    "BEHAVIOR_NEUTRAL",
    # Content fixtures
    "CONTENT_CRYPTO_SCAM",
    "CONTENT_LINK_BOMB",
    "CONTENT_EXCESSIVE_CAPS",
    "CONTENT_CLEAN",
    "CONTENT_DEALS_PROMO",
    "CONTENT_TECH_GITHUB",
    "CONTENT_CRYPTO_DISCUSSION",
    "CONTENT_LIGHT_PROMO",
    # Network fixtures
    "NETWORK_SPAM_HIGH",
    "NETWORK_BLOCKLISTED",
    "NETWORK_RAID",
    "NETWORK_CLEAN",
    "NETWORK_WHITELISTED",
    # Scenario fixtures
    "SCENARIO_CRYPTO_SCAM_ATTACK",
    "SCENARIO_LINK_BOMB_RAID",
    "SCENARIO_BLOCKLISTED_USER",
    "SCENARIO_TRUSTED_SUBSCRIBER",
    "SCENARIO_WHITELISTED_USER",
    "SCENARIO_DEALS_AFFILIATE_LINK",
    "SCENARIO_TECH_MULTIPLE_LINKS",
    "SCENARIO_CRYPTO_WALLET_SHARE",
    "SCENARIO_NEW_USER_PROMO",
    # Types
    "ScenarioFixture",
    "ProfileFixture",
    "BehaviorFixture",
    "ContentFixture",
    "NetworkFixture",
    # Scenario helpers
    "create_signals",
    "create_message_context",
    "get_all_scenarios",
    "get_spam_scenarios",
    "get_trust_scenarios",
    "get_false_positive_scenarios",
    "get_gray_zone_scenarios",
    # =========================================================================
    # Telegram Mocks
    # =========================================================================
    # User fixtures
    "mock_telegram_user",
    "mock_spam_user",
    "mock_premium_user",
    "mock_bot_user",
    # Chat fixtures
    "mock_telegram_chat",
    "mock_private_chat",
    "mock_channel",
    # Message fixtures
    "mock_telegram_message",
    "mock_spam_message",
    "mock_link_message",
    "mock_reply_message",
    # Bot fixtures
    "mock_telegram_bot",
    "mock_telegram_bot_with_admin",
    # Update fixtures
    "mock_telegram_update",
    "mock_callback_update",
    # Telegram helpers
    "create_mock_user",
    "create_mock_chat",
    "create_mock_message",
    # =========================================================================
    # Database Fixtures
    # =========================================================================
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
    # Database helpers
    "wait_for_postgres",
    "wait_for_redis",
    # =========================================================================
    # Service Mocks
    # =========================================================================
    # LLM types
    "MockLLMResult",
    "create_llm_result",
    # LLM fixtures
    "mock_llm_result_allow",
    "mock_llm_result_block",
    "mock_llm_result_watch",
    "mock_llm_result_error",
    "mock_llm_service",
    "mock_llm_service_unavailable",
    # SpamDB types
    "SpamDBMatch",
    # SpamDB fixtures
    "mock_spam_db_service",
    "mock_spam_db_with_matches",
    # Cache fixtures
    "mock_cache_service",
    "mock_cache_service_with_history",
    # Embeddings fixtures
    "mock_embeddings_service",
    "mock_embeddings_service_realistic",
    # Channel subscription fixtures
    "mock_channel_subscription_service",
    "mock_channel_subscription_service_subscribed",
    # Combined service fixtures
    "mock_all_services",
    # Service utilities
    "ServicePatcher",
    # =========================================================================
    # Mini App Auth Fixtures
    # =========================================================================
    # Constants
    "TEST_BOT_TOKEN",
    # Helper functions
    "generate_test_init_data",
    "create_mock_webapp_auth",
    "create_mock_webapp_request",
    # Fixtures
    "mock_webapp_user",
    "mock_admin_webapp_auth",
    "mock_non_admin_webapp_auth",
    "valid_init_data",
    "expired_init_data",
    # Test client
    "MiniAppTestClient",
]
