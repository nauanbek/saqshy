"""
SAQSHY Test Fixtures

Provides reusable fixtures for testing the SAQSHY anti-spam system.
"""

from tests.fixtures.scenarios import (
    BEHAVIOR_CHANNEL_SUBSCRIBER_LONG,
    BEHAVIOR_CHANNEL_SUBSCRIBER_NEW,
    # Behavior fixtures
    BEHAVIOR_FIRST_MESSAGE_FAST,
    BEHAVIOR_FLOOD,
    BEHAVIOR_NEUTRAL,
    BEHAVIOR_PREVIOUSLY_BLOCKED,
    BEHAVIOR_TRUSTED_ENGAGED,
    CONTENT_CLEAN,
    CONTENT_CRYPTO_DISCUSSION,
    # Content fixtures
    CONTENT_CRYPTO_SCAM,
    CONTENT_DEALS_PROMO,
    CONTENT_EXCESSIVE_CAPS,
    CONTENT_LINK_BOMB,
    CONTENT_TECH_GITHUB,
    NETWORK_BLOCKLISTED,
    NETWORK_CLEAN,
    NETWORK_RAID,
    # Network fixtures
    NETWORK_SPAM_HIGH,
    NETWORK_WHITELISTED,
    NEUTRAL_NEW_USER,
    SCENARIO_BLOCKLISTED_USER,
    # Scenario fixtures
    SCENARIO_CRYPTO_SCAM_ATTACK,
    SCENARIO_CRYPTO_WALLET_SHARE,
    SCENARIO_DEALS_AFFILIATE_LINK,
    SCENARIO_LINK_BOMB_RAID,
    SCENARIO_NEW_USER_PROMO,
    SCENARIO_TECH_MULTIPLE_LINKS,
    SCENARIO_TRUSTED_SUBSCRIBER,
    SCENARIO_WHITELISTED_USER,
    SPAMMER_CRYPTO_BIO,
    SPAMMER_EMOJI_NAME,
    # Profile fixtures
    SPAMMER_NEW_ACCOUNT,
    TRUSTED_REGULAR,
    TRUSTED_VETERAN,
    BehaviorFixture,
    ContentFixture,
    NetworkFixture,
    ProfileFixture,
    # Types
    ScenarioFixture,
    create_message_context,
    # Helpers
    create_signals,
    get_all_scenarios,
    get_false_positive_scenarios,
    get_gray_zone_scenarios,
    get_spam_scenarios,
    get_trust_scenarios,
)

__all__ = [
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
    # Helpers
    "create_signals",
    "create_message_context",
    "get_all_scenarios",
    "get_spam_scenarios",
    "get_trust_scenarios",
    "get_false_positive_scenarios",
    "get_gray_zone_scenarios",
    # Types
    "ScenarioFixture",
    "ProfileFixture",
    "BehaviorFixture",
    "ContentFixture",
    "NetworkFixture",
]
