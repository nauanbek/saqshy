"""
SAQSHY Core Constants

All weights, thresholds, and configuration values for the risk calculation system.
This module has ZERO external dependencies beyond the standard library.

Signal weights are calibrated based on:
- Positive values = risk signals (increase score)
- Negative values = trust signals (decrease score)
- Magnitude indicates signal strength
"""

from saqshy.core.types import GroupType

# =============================================================================
# Risk Score Thresholds by Group Type
# =============================================================================
# Format: (WATCH, LIMIT, REVIEW, BLOCK)
# Scores below WATCH = ALLOW

THRESHOLDS: dict[GroupType, tuple[int, int, int, int]] = {
    GroupType.GENERAL: (30, 50, 75, 92),
    GroupType.TECH: (30, 50, 75, 92),
    GroupType.DEALS: (40, 60, 80, 95),  # Higher tolerance for promo content
    GroupType.CRYPTO: (25, 45, 70, 90),  # Lower thresholds, scam-prone
}


# =============================================================================
# Profile Weights
# =============================================================================
# Analyze user profile for trust/risk signals

PROFILE_WEIGHTS: dict[str, int] = {
    # Trust signals (negative = reduce risk)
    "account_age_3_years": -15,
    "account_age_1_year": -10,
    "account_age_6_months": -5,
    "account_age_1_month": -2,
    "has_username": -3,
    "has_profile_photo": -5,
    "has_bio": -3,
    "has_first_name": -2,
    "has_last_name": -2,
    "is_premium": -10,
    # Risk signals (positive = increase risk)
    "account_age_under_7_days": 15,
    "account_age_under_24_hours": 25,
    "no_profile_photo": 8,
    "no_username": 5,
    "username_random_chars": 12,
    "bio_has_links": 8,
    "bio_has_crypto_terms": 10,
    "name_has_emoji_spam": 15,
    "is_bot": 5,  # Bots aren't necessarily bad, just flagged
}


# =============================================================================
# Content Weights
# =============================================================================
# Analyze message content for spam signals

CONTENT_WEIGHTS: dict[str, int] = {
    # Text patterns
    "excessive_caps_50_percent": 8,
    "excessive_caps_80_percent": 15,
    "excessive_emoji_10_plus": 10,
    "excessive_emoji_20_plus": 18,
    "very_short_message": 3,  # Under 10 chars
    "very_long_message": 5,  # Over 1000 chars (unusual for chat)
    # URL signals
    "has_urls": 5,
    "multiple_urls_3_plus": 12,
    "has_shortened_urls": 15,
    "has_suspicious_tld": 18,
    "has_whitelisted_domains": -8,  # Trust signal
    # Pattern matching (high risk)
    "crypto_scam_phrase": 35,
    "money_pattern": 12,  # "$1000", "earn money"
    "urgency_pattern": 10,  # "limited time", "act now"
    "phone_number": 8,
    "wallet_address": 20,
    # Media signals
    "is_forward_from_channel": 12,
    "is_forward": 5,
}


# =============================================================================
# Behavior Weights
# =============================================================================
# Analyze user behavior patterns

BEHAVIOR_WEIGHTS: dict[str, int] = {
    # Trust signals (VERY important)
    "is_channel_subscriber": -25,  # Strongest trust signal (conditional in calculator)
    "channel_sub_30_days": -10,
    "channel_sub_7_days": -5,
    "previous_messages_approved_10_plus": -15,
    "previous_messages_approved_5_plus": -10,
    "previous_messages_approved_1_plus": -5,
    "is_reply": -3,
    "is_reply_to_admin": -5,
    # Group membership trust signals
    "group_member_7_days": -5,
    "group_member_30_days": -10,
    "group_member_90_days": -15,
    # Risk signals
    "is_first_message": 8,
    "ttfm_under_30_seconds": 15,  # Time to first message
    "ttfm_under_5_minutes": 8,
    "messages_in_hour_5_plus": 12,  # Flood detection
    "messages_in_hour_10_plus": 20,
    "join_to_message_under_10_seconds": 18,  # Bot-like behavior
    "previous_messages_flagged": 15,
    "previous_messages_blocked": 25,
}


# =============================================================================
# Network Weights
# =============================================================================
# Cross-group and spam database signals

NETWORK_WEIGHTS: dict[str, int] = {
    # Trust signals
    "is_in_global_whitelist": -30,
    "groups_in_common_5_plus": -5,
    # Risk signals (VERY high impact)
    "spam_db_similarity_0.95_plus": 50,  # Near-exact match
    "spam_db_similarity_0.88_plus": 45,
    "spam_db_similarity_0.80_plus": 35,
    "spam_db_similarity_0.70_plus": 25,
    # Tiered duplicate detection - more groups = higher risk
    "duplicate_in_2_groups": 20,  # Message in 2 other groups
    "duplicate_in_3_groups": 35,  # Message in 3 other groups
    "duplicate_in_5_plus_groups": 50,  # Message in 5+ other groups (coordinated attack)
    "flagged_in_other_groups": 25,
    "blocked_in_other_groups": 40,
    "is_in_global_blocklist": 50,
}


# =============================================================================
# Deals Group Weight Overrides
# =============================================================================
# For deals/shopping groups, promotional content is NORMAL

DEALS_WEIGHT_OVERRIDES: dict[str, int] = {
    # Reduce penalty for promotional content
    "has_urls": 2,  # Reduced from 5
    "multiple_urls_3_plus": 5,  # Reduced from 12
    "has_shortened_urls": 5,  # Reduced from 15 (common in deals)
    "money_pattern": 3,  # Reduced from 12 (prices are normal)
    "urgency_pattern": 3,  # Reduced from 10 (sales are time-limited)
    "is_forward_from_channel": 5,  # Reduced from 12
    # Keep crypto scam penalties high
    "crypto_scam_phrase": 35,
    "wallet_address": 20,
}


# =============================================================================
# Crypto Group Adjustments
# =============================================================================
# For crypto groups, crypto terms are NORMAL but scams are punished harder

CRYPTO_WEIGHT_OVERRIDES: dict[str, int] = {
    # Reduce penalty for normal crypto discussion
    "bio_has_crypto_terms": 3,  # Reduced from 10
    "wallet_address": 5,  # Reduced from 20 (wallets are normal in crypto)
    # Increase penalty for scam patterns
    "crypto_scam_phrase": 45,  # Increased from 35
    "money_pattern": 18,  # Increased from 12 (more suspicious in crypto)
}


# =============================================================================
# Tech Group Adjustments
# =============================================================================
# For tech groups, GitHub/docs links are NORMAL

TECH_WEIGHT_OVERRIDES: dict[str, int] = {
    "has_urls": 2,  # Reduced - docs/github links are normal
    "multiple_urls_3_plus": 5,  # Reduced
}


# =============================================================================
# Whitelisted Domains
# =============================================================================

WHITELIST_DOMAINS_GENERAL: set[str] = {
    # Major platforms
    "youtube.com",
    "youtu.be",
    "twitter.com",
    "x.com",
    "instagram.com",
    "facebook.com",
    "linkedin.com",
    "reddit.com",
    "telegram.org",
    "t.me",
    # News
    "bbc.com",
    "cnn.com",
    "reuters.com",
    # Tech
    "github.com",
    "gitlab.com",
    "stackoverflow.com",
    "medium.com",
    "dev.to",
}

WHITELIST_DOMAINS_TECH: set[str] = WHITELIST_DOMAINS_GENERAL | {
    # Documentation
    "docs.python.org",
    "developer.mozilla.org",
    "kubernetes.io",
    "docker.com",
    # Package registries
    "pypi.org",
    "npmjs.com",
    "crates.io",
    # Cloud providers
    "aws.amazon.com",
    "cloud.google.com",
    "azure.microsoft.com",
}

WHITELIST_DOMAINS_DEALS: set[str] = WHITELIST_DOMAINS_GENERAL | {
    # Major retailers (example subset)
    "amazon.com",
    "amazon.co.uk",
    "ebay.com",
    "walmart.com",
    "target.com",
    "bestbuy.com",
    "newegg.com",
    "aliexpress.com",
    "ozon.ru",
    "wildberries.ru",
}

# Allowed URL shorteners for deals groups
ALLOWED_SHORTENERS: set[str] = {
    "clck.ru",
    "fas.st",
    "bit.ly",
    "t.co",
    "amzn.to",
}


# =============================================================================
# Suspicious TLDs
# =============================================================================

SUSPICIOUS_TLDS: set[str] = {
    ".xyz",
    ".top",
    ".work",
    ".click",
    ".link",
    ".tk",
    ".ml",
    ".ga",
    ".cf",
    ".gq",
    ".pw",
    ".cc",
    ".ws",
}


# =============================================================================
# Crypto Scam Phrases
# =============================================================================
# These phrases strongly indicate scam activity

CRYPTO_SCAM_PHRASES: list[str] = [
    # Investment scams
    "guaranteed profit",
    "100% profit",
    "double your",
    "triple your",
    "10x return",
    "100x return",
    "instant profit",
    "passive income crypto",
    # Mining scams
    "free mining",
    "cloud mining invest",
    "mining pool invest",
    # DM scams
    "dm me for",
    "message me for",
    "contact admin",
    "write to manager",
    # Recovery scams
    "recover lost crypto",
    "recover stolen",
    "crypto recovery",
    # Giveaway/Airdrop scams
    "airdrop",  # Standalone airdrop is almost always scam
    "free airdrop",
    "airdrop claim",
    "claim airdrop",
    "get airdrop",
    "free tokens",
    "free tokens claim",
    "claim your reward",
    "claim reward",
    "free crypto",
    "free nft",
    # Channel promotion (spam)
    "join channel",
    "join our channel",
    "join now",
    "join t.me",
    "join telegram",
    # Urgency phrases
    "limited time",
    "hurry up",
    "act now",
    "don't miss",
    # Common patterns (Russian)
    "гарантированный доход",
    "пассивный доход",
    "удвоить депозит",
    "написать в лс",
    "вступай в канал",
    "бесплатный аирдроп",
    "бесплатные токены",
]


# =============================================================================
# Sandbox Mode Configuration
# =============================================================================

SANDBOX_DEFAULTS: dict[str, int | float] = {
    "duration_hours": 24,
    "message_limit": 5,
    "require_captcha": True,
    "auto_promote_after_approved_messages": 3,
}


# =============================================================================
# Rate Limits
# =============================================================================

RATE_LIMITS: dict[str, dict[str, int]] = {
    "messages_per_minute": {"limit": 20, "window_seconds": 60},
    "messages_per_hour": {"limit": 100, "window_seconds": 3600},
    "joins_per_minute": {"limit": 30, "window_seconds": 60},  # Raid detection
}


# =============================================================================
# LLM Gray Zone
# =============================================================================
# Score range where LLM review is triggered

LLM_GRAY_ZONE: tuple[int, int] = (35, 85)  # Expanded from (60, 80) for better detection
LLM_MAX_RETRIES: int = 2
LLM_TIMEOUT_SECONDS: int = 10

# Threshold for forcing LLM review on first messages from unestablished users
# This catches sophisticated spam that evades rule-based detection early
LLM_FIRST_MESSAGE_THRESHOLD: int = 25
