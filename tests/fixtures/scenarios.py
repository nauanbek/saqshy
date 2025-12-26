"""
SAQSHY Test Fixtures - Scenario Data

Provides reusable test fixtures for integration tests covering:
- Spammer profiles (new account, random chars, emoji spam)
- Trusted user profiles (old account, premium, approved messages)
- Spam messages (crypto scam, link bomb, raid content)
- Legitimate messages (deals posts, tech discussions)

These fixtures are designed for deterministic testing of the
cumulative risk scoring system.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

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
# Profile Fixtures
# =============================================================================


@dataclass
class ProfileFixture:
    """Reusable profile configuration."""

    name: str
    description: str
    signals: ProfileSignals


# Spammer profiles
SPAMMER_NEW_ACCOUNT = ProfileFixture(
    name="spammer_new_account",
    description="Brand new account (<24h), no photo, random username",
    signals=ProfileSignals(
        account_age_days=0,
        has_username=True,
        has_profile_photo=False,
        has_bio=False,
        has_first_name=True,
        has_last_name=False,
        is_premium=False,
        is_bot=False,
        username_has_random_chars=True,
        bio_has_links=False,
        bio_has_crypto_terms=False,
        name_has_emoji_spam=False,
    ),
)

SPAMMER_CRYPTO_BIO = ProfileFixture(
    name="spammer_crypto_bio",
    description="New account with crypto terms in bio, suspicious username",
    signals=ProfileSignals(
        account_age_days=3,
        has_username=True,
        has_profile_photo=False,
        has_bio=True,
        has_first_name=True,
        has_last_name=False,
        is_premium=False,
        is_bot=False,
        username_has_random_chars=True,
        bio_has_links=True,
        bio_has_crypto_terms=True,
        name_has_emoji_spam=False,
    ),
)

SPAMMER_EMOJI_NAME = ProfileFixture(
    name="spammer_emoji_name",
    description="Spammer with emoji spam in name (scam cluster)",
    signals=ProfileSignals(
        account_age_days=5,
        has_username=True,
        has_profile_photo=False,
        has_bio=True,
        has_first_name=True,
        has_last_name=True,
        is_premium=False,
        is_bot=False,
        username_has_random_chars=False,
        bio_has_links=False,
        bio_has_crypto_terms=True,
        name_has_emoji_spam=True,  # e.g., name contains "money rocket fire" emoji cluster
    ),
)

# Trusted user profiles
TRUSTED_VETERAN = ProfileFixture(
    name="trusted_veteran",
    description="Account 3+ years old, complete profile, premium",
    signals=ProfileSignals(
        account_age_days=1200,  # ~3.3 years
        has_username=True,
        has_profile_photo=True,
        has_bio=True,
        has_first_name=True,
        has_last_name=True,
        is_premium=True,
        is_bot=False,
        username_has_random_chars=False,
        bio_has_links=False,
        bio_has_crypto_terms=False,
        name_has_emoji_spam=False,
    ),
)

TRUSTED_REGULAR = ProfileFixture(
    name="trusted_regular",
    description="Account 1+ year old, has photo and username",
    signals=ProfileSignals(
        account_age_days=400,
        has_username=True,
        has_profile_photo=True,
        has_bio=False,
        has_first_name=True,
        has_last_name=False,
        is_premium=False,
        is_bot=False,
        username_has_random_chars=False,
        bio_has_links=False,
        bio_has_crypto_terms=False,
        name_has_emoji_spam=False,
    ),
)

NEUTRAL_NEW_USER = ProfileFixture(
    name="neutral_new_user",
    description="New but legitimate-looking account (2 weeks old)",
    signals=ProfileSignals(
        account_age_days=14,
        has_username=True,
        has_profile_photo=True,
        has_bio=True,
        has_first_name=True,
        has_last_name=True,
        is_premium=False,
        is_bot=False,
        username_has_random_chars=False,
        bio_has_links=False,
        bio_has_crypto_terms=False,
        name_has_emoji_spam=False,
    ),
)


# =============================================================================
# Behavior Fixtures
# =============================================================================


@dataclass
class BehaviorFixture:
    """Reusable behavior configuration."""

    name: str
    description: str
    signals: BehaviorSignals


# Spammer behaviors
BEHAVIOR_FIRST_MESSAGE_FAST = BehaviorFixture(
    name="first_message_fast",
    description="First message sent within 10 seconds of join",
    signals=BehaviorSignals(
        time_to_first_message_seconds=8,
        messages_in_last_hour=1,
        messages_in_last_24h=1,
        join_to_message_seconds=8,
        previous_messages_approved=0,
        previous_messages_flagged=0,
        previous_messages_blocked=0,
        is_first_message=True,
        is_channel_subscriber=False,
        channel_subscription_duration_days=0,
        is_reply=False,
        is_reply_to_admin=False,
        mentioned_users_count=0,
    ),
)

BEHAVIOR_FLOOD = BehaviorFixture(
    name="flood",
    description="User flooding with 10+ messages in last hour",
    signals=BehaviorSignals(
        time_to_first_message_seconds=60,
        messages_in_last_hour=12,
        messages_in_last_24h=15,
        join_to_message_seconds=60,
        previous_messages_approved=0,
        previous_messages_flagged=5,
        previous_messages_blocked=0,
        is_first_message=False,
        is_channel_subscriber=False,
        channel_subscription_duration_days=0,
        is_reply=False,
        is_reply_to_admin=False,
        mentioned_users_count=0,
    ),
)

BEHAVIOR_PREVIOUSLY_BLOCKED = BehaviorFixture(
    name="previously_blocked",
    description="User with previously blocked messages",
    signals=BehaviorSignals(
        time_to_first_message_seconds=None,
        messages_in_last_hour=1,
        messages_in_last_24h=3,
        join_to_message_seconds=None,
        previous_messages_approved=0,
        previous_messages_flagged=2,
        previous_messages_blocked=3,
        is_first_message=False,
        is_channel_subscriber=False,
        channel_subscription_duration_days=0,
        is_reply=False,
        is_reply_to_admin=False,
        mentioned_users_count=0,
    ),
)

# Trusted behaviors
BEHAVIOR_CHANNEL_SUBSCRIBER_LONG = BehaviorFixture(
    name="channel_subscriber_long",
    description="Channel subscriber for 30+ days with approved messages",
    signals=BehaviorSignals(
        time_to_first_message_seconds=None,
        messages_in_last_hour=2,
        messages_in_last_24h=5,
        join_to_message_seconds=None,
        previous_messages_approved=15,
        previous_messages_flagged=0,
        previous_messages_blocked=0,
        is_first_message=False,
        is_channel_subscriber=True,
        channel_subscription_duration_days=45,
        is_reply=False,
        is_reply_to_admin=False,
        mentioned_users_count=0,
    ),
)

BEHAVIOR_CHANNEL_SUBSCRIBER_NEW = BehaviorFixture(
    name="channel_subscriber_new",
    description="New channel subscriber (7 days)",
    signals=BehaviorSignals(
        time_to_first_message_seconds=None,
        messages_in_last_hour=1,
        messages_in_last_24h=3,
        join_to_message_seconds=None,
        previous_messages_approved=5,
        previous_messages_flagged=0,
        previous_messages_blocked=0,
        is_first_message=False,
        is_channel_subscriber=True,
        channel_subscription_duration_days=10,
        is_reply=False,
        is_reply_to_admin=False,
        mentioned_users_count=0,
    ),
)

BEHAVIOR_TRUSTED_ENGAGED = BehaviorFixture(
    name="trusted_engaged",
    description="Active trusted member replying to admin",
    signals=BehaviorSignals(
        time_to_first_message_seconds=None,
        messages_in_last_hour=3,
        messages_in_last_24h=8,
        join_to_message_seconds=None,
        previous_messages_approved=25,
        previous_messages_flagged=0,
        previous_messages_blocked=0,
        is_first_message=False,
        is_channel_subscriber=True,
        channel_subscription_duration_days=60,
        is_reply=True,
        is_reply_to_admin=True,
        mentioned_users_count=0,
    ),
)

BEHAVIOR_NEUTRAL = BehaviorFixture(
    name="neutral",
    description="Normal user activity, not subscriber",
    signals=BehaviorSignals(
        time_to_first_message_seconds=300,
        messages_in_last_hour=2,
        messages_in_last_24h=4,
        join_to_message_seconds=3600,
        previous_messages_approved=3,
        previous_messages_flagged=0,
        previous_messages_blocked=0,
        is_first_message=False,
        is_channel_subscriber=False,
        channel_subscription_duration_days=0,
        is_reply=True,
        is_reply_to_admin=False,
        mentioned_users_count=0,
    ),
)


# =============================================================================
# Content Fixtures
# =============================================================================


@dataclass
class ContentFixture:
    """Reusable content configuration."""

    name: str
    description: str
    signals: ContentSignals
    example_text: str


# Spam content
CONTENT_CRYPTO_SCAM = ContentFixture(
    name="crypto_scam",
    description="Crypto scam with wallet address and scam phrases",
    signals=ContentSignals(
        text_length=200,
        word_count=35,
        caps_ratio=0.4,
        emoji_count=5,
        has_cyrillic=False,
        has_latin=True,
        language="en",
        url_count=1,
        has_shortened_urls=False,
        has_whitelisted_urls=False,
        has_suspicious_tld=True,
        unique_domains=1,
        has_crypto_scam_phrases=True,
        has_money_patterns=True,
        has_urgency_patterns=True,
        has_phone_numbers=False,
        has_wallet_addresses=True,
        has_media=False,
        has_forward=False,
        forward_from_channel=False,
    ),
    example_text="GUARANTEED 100x RETURNS! Double your BTC in 24 hours! "
    "Send to bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh "
    "DM me NOW for passive income! Limited spots! Visit crypto-profits.xyz",
)

CONTENT_LINK_BOMB = ContentFixture(
    name="link_bomb",
    description="Message with multiple suspicious URLs",
    signals=ContentSignals(
        text_length=300,
        word_count=40,
        caps_ratio=0.6,
        emoji_count=10,
        has_cyrillic=False,
        has_latin=True,
        language="en",
        url_count=5,
        has_shortened_urls=True,
        has_whitelisted_urls=False,
        has_suspicious_tld=True,
        unique_domains=5,
        has_crypto_scam_phrases=False,
        has_money_patterns=True,
        has_urgency_patterns=True,
        has_phone_numbers=False,
        has_wallet_addresses=False,
        has_media=False,
        has_forward=True,
        forward_from_channel=True,
    ),
    example_text="CHECK OUT THESE DEALS bit.ly/xxx tinyurl.com/yyy "
    "free-money.xyz earn-now.top profits.click LIMITED TIME ONLY!!!",
)

CONTENT_EXCESSIVE_CAPS = ContentFixture(
    name="excessive_caps",
    description="Message with excessive caps and emojis",
    signals=ContentSignals(
        text_length=150,
        word_count=20,
        caps_ratio=0.85,
        emoji_count=25,
        has_cyrillic=False,
        has_latin=True,
        language="en",
        url_count=0,
        has_shortened_urls=False,
        has_whitelisted_urls=False,
        has_suspicious_tld=False,
        unique_domains=0,
        has_crypto_scam_phrases=False,
        has_money_patterns=False,
        has_urgency_patterns=True,
        has_phone_numbers=False,
        has_wallet_addresses=False,
        has_media=False,
        has_forward=False,
        forward_from_channel=False,
    ),
    example_text="HURRY UP!!! THIS IS AMAZING!!! YOU WON'T BELIEVE IT!!!",
)

# Legitimate content
CONTENT_CLEAN = ContentFixture(
    name="clean",
    description="Normal conversational message",
    signals=ContentSignals(
        text_length=80,
        word_count=15,
        caps_ratio=0.05,
        emoji_count=1,
        has_cyrillic=False,
        has_latin=True,
        language="en",
        url_count=0,
        has_shortened_urls=False,
        has_whitelisted_urls=False,
        has_suspicious_tld=False,
        unique_domains=0,
        has_crypto_scam_phrases=False,
        has_money_patterns=False,
        has_urgency_patterns=False,
        has_phone_numbers=False,
        has_wallet_addresses=False,
        has_media=False,
        has_forward=False,
        forward_from_channel=False,
    ),
    example_text="Hey everyone, just wanted to share my thoughts on this topic.",
)

CONTENT_DEALS_PROMO = ContentFixture(
    name="deals_promo",
    description="Legitimate deals post with affiliate links",
    signals=ContentSignals(
        text_length=250,
        word_count=40,
        caps_ratio=0.15,
        emoji_count=5,
        has_cyrillic=False,
        has_latin=True,
        language="en",
        url_count=2,
        has_shortened_urls=True,  # clck.ru or amzn.to
        has_whitelisted_urls=True,  # amazon.com
        has_suspicious_tld=False,
        unique_domains=2,
        has_crypto_scam_phrases=False,
        has_money_patterns=True,  # "$29.99"
        has_urgency_patterns=True,  # "limited time"
        has_phone_numbers=False,
        has_wallet_addresses=False,
        has_media=True,
        has_forward=False,
        forward_from_channel=False,
    ),
    example_text="Apple AirPods Pro 2 - only $199.99 (was $249)! "
    "Limited time deal on Amazon: amzn.to/abc123 "
    "Also check Walmart for $205: walmart.com/airpods",
)

CONTENT_TECH_GITHUB = ContentFixture(
    name="tech_github",
    description="Tech discussion with GitHub/docs links",
    signals=ContentSignals(
        text_length=300,
        word_count=50,
        caps_ratio=0.08,
        emoji_count=0,
        has_cyrillic=False,
        has_latin=True,
        language="en",
        url_count=3,
        has_shortened_urls=False,
        has_whitelisted_urls=True,  # github.com, docs.python.org
        has_suspicious_tld=False,
        unique_domains=3,
        has_crypto_scam_phrases=False,
        has_money_patterns=False,
        has_urgency_patterns=False,
        has_phone_numbers=False,
        has_wallet_addresses=False,
        has_media=False,
        has_forward=False,
        forward_from_channel=False,
    ),
    example_text="Check out this PR I submitted: github.com/project/pr/123 "
    "The implementation follows the pattern from docs.python.org/asyncio "
    "Also see the discussion on stackoverflow.com/questions/abc",
)

CONTENT_CRYPTO_DISCUSSION = ContentFixture(
    name="crypto_discussion",
    description="Legitimate crypto discussion with wallet address (for crypto groups)",
    signals=ContentSignals(
        text_length=200,
        word_count=35,
        caps_ratio=0.05,
        emoji_count=0,
        has_cyrillic=False,
        has_latin=True,
        language="en",
        url_count=0,
        has_shortened_urls=False,
        has_whitelisted_urls=False,
        has_suspicious_tld=False,
        unique_domains=0,
        has_crypto_scam_phrases=False,  # No scam phrases
        has_money_patterns=False,
        has_urgency_patterns=False,
        has_phone_numbers=False,
        has_wallet_addresses=True,  # Sharing wallet for legitimate purpose
        has_media=False,
        has_forward=False,
        forward_from_channel=False,
    ),
    example_text="I moved my ETH to a hardware wallet. Here's my address for "
    "the group tip jar if anyone wants to contribute: 0x1234...",
)


# =============================================================================
# Network Fixtures
# =============================================================================


@dataclass
class NetworkFixture:
    """Reusable network/spam-db configuration."""

    name: str
    description: str
    signals: NetworkSignals


NETWORK_SPAM_HIGH = NetworkFixture(
    name="spam_high",
    description="High spam database match (0.92 similarity)",
    signals=NetworkSignals(
        groups_in_common=0,
        duplicate_messages_in_other_groups=3,
        flagged_in_other_groups=2,
        blocked_in_other_groups=1,
        spam_db_similarity=0.92,
        spam_db_matched_pattern="Known crypto scam pattern",
        is_in_global_blocklist=False,
        is_in_global_whitelist=False,
    ),
)

NETWORK_BLOCKLISTED = NetworkFixture(
    name="blocklisted",
    description="User in global blocklist",
    signals=NetworkSignals(
        groups_in_common=0,
        duplicate_messages_in_other_groups=0,
        flagged_in_other_groups=0,
        blocked_in_other_groups=5,
        spam_db_similarity=0.0,
        spam_db_matched_pattern=None,
        is_in_global_blocklist=True,
        is_in_global_whitelist=False,
    ),
)

NETWORK_RAID = NetworkFixture(
    name="raid",
    description="Duplicate messages in multiple groups (raid behavior)",
    signals=NetworkSignals(
        groups_in_common=0,
        duplicate_messages_in_other_groups=8,
        flagged_in_other_groups=5,
        blocked_in_other_groups=3,
        spam_db_similarity=0.85,
        spam_db_matched_pattern="Raid message pattern",
        is_in_global_blocklist=False,
        is_in_global_whitelist=False,
    ),
)

NETWORK_CLEAN = NetworkFixture(
    name="clean",
    description="No network risk signals",
    signals=NetworkSignals(
        groups_in_common=3,
        duplicate_messages_in_other_groups=0,
        flagged_in_other_groups=0,
        blocked_in_other_groups=0,
        spam_db_similarity=0.0,
        spam_db_matched_pattern=None,
        is_in_global_blocklist=False,
        is_in_global_whitelist=False,
    ),
)

NETWORK_WHITELISTED = NetworkFixture(
    name="whitelisted",
    description="User in global whitelist",
    signals=NetworkSignals(
        groups_in_common=10,
        duplicate_messages_in_other_groups=0,
        flagged_in_other_groups=0,
        blocked_in_other_groups=0,
        spam_db_similarity=0.0,
        spam_db_matched_pattern=None,
        is_in_global_blocklist=False,
        is_in_global_whitelist=True,
    ),
)


# =============================================================================
# Combined Scenario Fixtures
# =============================================================================


@dataclass
class ScenarioFixture:
    """Complete scenario with all signal types."""

    name: str
    description: str
    group_type: GroupType
    signals: Signals
    expected_verdict_range: tuple[int, int]  # (min_score, max_score) range
    is_false_positive: bool  # True if this should NOT be blocked


def create_signals(
    profile: ProfileFixture | None = None,
    content: ContentFixture | None = None,
    behavior: BehaviorFixture | None = None,
    network: NetworkFixture | None = None,
) -> Signals:
    """Create Signals from fixtures."""
    return Signals(
        profile=profile.signals if profile else ProfileSignals(),
        content=content.signals if content else ContentSignals(),
        behavior=behavior.signals if behavior else BehaviorSignals(),
        network=network.signals if network else NetworkSignals(),
    )


# Spam scenarios - SHOULD be blocked or heavily penalized
SCENARIO_CRYPTO_SCAM_ATTACK = ScenarioFixture(
    name="crypto_scam_attack",
    description="New account posting crypto scam with wallet address",
    group_type=GroupType.GENERAL,
    signals=create_signals(
        profile=SPAMMER_CRYPTO_BIO,
        content=CONTENT_CRYPTO_SCAM,
        behavior=BEHAVIOR_FIRST_MESSAGE_FAST,
        network=NETWORK_SPAM_HIGH,
    ),
    expected_verdict_range=(92, 100),
    is_false_positive=False,
)

SCENARIO_LINK_BOMB_RAID = ScenarioFixture(
    name="link_bomb_raid",
    description="Raid attack with link bombing across groups",
    group_type=GroupType.GENERAL,
    signals=create_signals(
        profile=SPAMMER_NEW_ACCOUNT,
        content=CONTENT_LINK_BOMB,
        behavior=BEHAVIOR_FLOOD,
        network=NETWORK_RAID,
    ),
    expected_verdict_range=(92, 100),
    is_false_positive=False,
)

SCENARIO_BLOCKLISTED_USER = ScenarioFixture(
    name="blocklisted_user",
    description="User from global blocklist sending any message",
    group_type=GroupType.GENERAL,
    signals=create_signals(
        profile=NEUTRAL_NEW_USER,
        content=CONTENT_CLEAN,
        behavior=BEHAVIOR_NEUTRAL,
        network=NETWORK_BLOCKLISTED,
    ),
    expected_verdict_range=(50, 100),
    is_false_positive=False,
)

# Trust scenarios - SHOULD be allowed
SCENARIO_TRUSTED_SUBSCRIBER = ScenarioFixture(
    name="trusted_subscriber",
    description="Long-time channel subscriber with clean history",
    group_type=GroupType.GENERAL,
    signals=create_signals(
        profile=TRUSTED_VETERAN,
        content=CONTENT_CLEAN,
        behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_LONG,
        network=NETWORK_CLEAN,
    ),
    expected_verdict_range=(0, 20),
    is_false_positive=False,
)

SCENARIO_WHITELISTED_USER = ScenarioFixture(
    name="whitelisted_user",
    description="Global whitelist user",
    group_type=GroupType.GENERAL,
    signals=create_signals(
        profile=TRUSTED_REGULAR,
        content=CONTENT_CLEAN,
        behavior=BEHAVIOR_NEUTRAL,
        network=NETWORK_WHITELISTED,
    ),
    expected_verdict_range=(0, 20),
    is_false_positive=False,
)

# False positive scenarios - Should NOT be blocked despite some risk signals
SCENARIO_DEALS_AFFILIATE_LINK = ScenarioFixture(
    name="deals_affiliate_link",
    description="Channel subscriber posting Amazon deal with affiliate link in DEALS group",
    group_type=GroupType.DEALS,
    signals=create_signals(
        profile=TRUSTED_REGULAR,
        content=CONTENT_DEALS_PROMO,
        behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_NEW,
        network=NETWORK_CLEAN,
    ),
    expected_verdict_range=(0, 40),  # Should be ALLOW in deals group
    is_false_positive=True,
)

SCENARIO_TECH_MULTIPLE_LINKS = ScenarioFixture(
    name="tech_multiple_links",
    description="Trusted user sharing multiple GitHub/docs links in TECH group",
    group_type=GroupType.TECH,
    signals=create_signals(
        profile=TRUSTED_VETERAN,
        content=CONTENT_TECH_GITHUB,
        behavior=BEHAVIOR_TRUSTED_ENGAGED,
        network=NETWORK_CLEAN,
    ),
    expected_verdict_range=(0, 30),  # Should be ALLOW
    is_false_positive=True,
)

SCENARIO_CRYPTO_WALLET_SHARE = ScenarioFixture(
    name="crypto_wallet_share",
    description="Trusted user sharing wallet address in CRYPTO group (legitimate)",
    group_type=GroupType.CRYPTO,
    signals=create_signals(
        profile=TRUSTED_REGULAR,
        content=CONTENT_CRYPTO_DISCUSSION,
        behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_LONG,
        network=NETWORK_CLEAN,
    ),
    expected_verdict_range=(0, 35),  # Wallet address penalty reduced in crypto group
    is_false_positive=True,
)

# Gray zone content fixture
CONTENT_LIGHT_PROMO = ContentFixture(
    name="light_promo",
    description="Light promotional content",
    signals=ContentSignals(
        text_length=150,
        word_count=25,
        caps_ratio=0.2,
        emoji_count=3,
        url_count=1,
        has_shortened_urls=False,
        has_whitelisted_urls=True,
        has_money_patterns=True,
    ),
    example_text="Check out this YouTube video I found: youtube.com/watch?v=xxx",
)

# Gray zone scenarios - Borderline cases
# Note: This scenario with trust signals ends up in ALLOW range
# The "neutral new user" with promo content is actually quite benign
SCENARIO_NEW_USER_PROMO = ScenarioFixture(
    name="new_user_promo",
    description="New user with some promotional content (with trust signals = ALLOW)",
    group_type=GroupType.GENERAL,
    signals=create_signals(
        profile=NEUTRAL_NEW_USER,
        content=CONTENT_LIGHT_PROMO,
        behavior=BEHAVIOR_NEUTRAL,
        network=NETWORK_CLEAN,
    ),
    expected_verdict_range=(0, 30),  # With trust signals, ends up in ALLOW
    is_false_positive=True,  # Actually a false positive scenario
)


# =============================================================================
# Helper Functions
# =============================================================================


def get_all_scenarios() -> list[ScenarioFixture]:
    """Get all scenario fixtures."""
    return [
        SCENARIO_CRYPTO_SCAM_ATTACK,
        SCENARIO_LINK_BOMB_RAID,
        SCENARIO_BLOCKLISTED_USER,
        SCENARIO_TRUSTED_SUBSCRIBER,
        SCENARIO_WHITELISTED_USER,
        SCENARIO_DEALS_AFFILIATE_LINK,
        SCENARIO_TECH_MULTIPLE_LINKS,
        SCENARIO_CRYPTO_WALLET_SHARE,
        SCENARIO_NEW_USER_PROMO,
    ]


def get_spam_scenarios() -> list[ScenarioFixture]:
    """Get scenarios that should be blocked."""
    return [
        s
        for s in get_all_scenarios()
        if not s.is_false_positive and s.expected_verdict_range[0] >= 75
    ]


def get_trust_scenarios() -> list[ScenarioFixture]:
    """Get scenarios that should be allowed."""
    return [s for s in get_all_scenarios() if s.expected_verdict_range[1] < 30]


def get_false_positive_scenarios() -> list[ScenarioFixture]:
    """Get false positive scenarios (should NOT be blocked despite risk signals)."""
    return [s for s in get_all_scenarios() if s.is_false_positive]


def get_gray_zone_scenarios() -> list[ScenarioFixture]:
    """Get gray zone scenarios (borderline cases)."""
    return [s for s in get_all_scenarios() if 30 <= s.expected_verdict_range[0] <= 70]


# =============================================================================
# Message Context Helpers
# =============================================================================


def create_message_context(
    text: str,
    group_type: GroupType = GroupType.GENERAL,
    user_id: int = 123456789,
    chat_id: int = -1001234567890,
    username: str | None = None,
    first_name: str | None = None,
    is_premium: bool = False,
    is_forward: bool = False,
    has_media: bool = False,
) -> MessageContext:
    """Create a MessageContext for testing."""
    return MessageContext(
        message_id=1,
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        timestamp=datetime.now(UTC),
        username=username,
        first_name=first_name or "TestUser",
        last_name=None,
        is_bot=False,
        is_premium=is_premium,
        chat_type="supergroup",
        chat_title="Test Group",
        group_type=group_type,
        has_media=has_media,
        is_forward=is_forward,
    )


# Export key fixtures for pytest
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
