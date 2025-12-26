"""
SAQSHY Core Types

Shared type definitions used across the application.
This module has ZERO external dependencies beyond the standard library.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class GroupType(str, Enum):
    """
    Group type determines threshold calibration and weight adjustments.

    Each group type has different thresholds and signal weights optimized
    for the typical content in that type of community.
    """

    GENERAL = "general"  # Standard community groups
    TECH = "tech"  # Developer/technology groups
    DEALS = "deals"  # Shopping/deals groups
    CRYPTO = "crypto"  # Cryptocurrency groups


class Verdict(str, Enum):
    """
    Risk verdict determines what action to take on a message.

    Verdicts are ordered from least restrictive to most restrictive.
    The thresholds for each verdict depend on the group type.
    """

    ALLOW = "allow"  # Score 0-30: Message is allowed through
    WATCH = "watch"  # Score 30-50: Message allowed, user flagged for monitoring
    LIMIT = "limit"  # Score 50-75: Restrict user capabilities
    REVIEW = "review"  # Score 75-92: Send to admin review queue
    BLOCK = "block"  # Score 92+: Block message immediately


class ThreatType(str, Enum):
    """
    Type of spam/threat detected.

    Used for analytics and to customize response messages.
    """

    NONE = "none"
    SPAM = "spam"
    SCAM = "scam"
    CRYPTO_SCAM = "crypto_scam"
    PHISHING = "phishing"
    PROMOTION = "promotion"
    FLOOD = "flood"
    RAID = "raid"
    BOT = "bot"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProfileSignals:
    """
    Signals extracted from user profile analysis.

    All fields are optional with sensible defaults.
    Negative weights = trust signals (reduce risk).
    Positive weights = risk signals (increase risk).
    """

    # Trust signals (negative = reduce risk)
    account_age_days: int = 0
    has_username: bool = False
    has_profile_photo: bool = False
    has_bio: bool = False
    has_first_name: bool = False
    has_last_name: bool = False
    is_premium: bool = False

    # Risk signals (positive = increase risk)
    is_bot: bool = False
    username_has_random_chars: bool = False
    bio_has_links: bool = False
    bio_has_crypto_terms: bool = False
    name_has_emoji_spam: bool = False


@dataclass(frozen=True)
class ContentSignals:
    """
    Signals extracted from message content analysis.

    Analyzes URLs, text patterns, and media.
    """

    # Text analysis
    text_length: int = 0
    word_count: int = 0
    caps_ratio: float = 0.0
    emoji_count: int = 0
    has_cyrillic: bool = False
    has_latin: bool = False
    language: str = ""

    # URL analysis
    url_count: int = 0
    has_shortened_urls: bool = False
    has_whitelisted_urls: bool = False
    has_suspicious_tld: bool = False
    unique_domains: int = 0

    # Pattern matching
    has_crypto_scam_phrases: bool = False
    has_money_patterns: bool = False
    has_urgency_patterns: bool = False
    has_phone_numbers: bool = False
    has_wallet_addresses: bool = False

    # Media
    has_media: bool = False
    has_forward: bool = False
    forward_from_channel: bool = False


@dataclass(frozen=True)
class BehaviorSignals:
    """
    Signals from user behavior analysis.

    Tracks message timing, history, and interaction patterns.
    """

    # Time-based
    time_to_first_message_seconds: int | None = None
    messages_in_last_hour: int = 0
    messages_in_last_24h: int = 0
    join_to_message_seconds: int | None = None

    # History
    previous_messages_approved: int = 0
    previous_messages_flagged: int = 0
    previous_messages_blocked: int = 0
    is_first_message: bool = True

    # Channel subscription (strongest trust signal)
    is_channel_subscriber: bool = False
    channel_subscription_duration_days: int = 0

    # Interaction
    is_reply: bool = False
    is_reply_to_admin: bool = False
    mentioned_users_count: int = 0


@dataclass(frozen=True)
class NetworkSignals:
    """
    Signals from cross-group and network analysis.

    Detects coordinated spam attacks.
    """

    # Cross-group behavior
    groups_in_common: int = 0
    duplicate_messages_in_other_groups: int = 0
    flagged_in_other_groups: int = 0
    blocked_in_other_groups: int = 0

    # Spam database
    spam_db_similarity: float = 0.0
    spam_db_matched_pattern: str | None = None

    # Known lists
    is_in_global_blocklist: bool = False
    is_in_global_whitelist: bool = False


@dataclass
class Signals:
    """
    Combined signals from all analyzers.

    This is the main input to the RiskCalculator.
    """

    profile: ProfileSignals = field(default_factory=ProfileSignals)
    content: ContentSignals = field(default_factory=ContentSignals)
    behavior: BehaviorSignals = field(default_factory=BehaviorSignals)
    network: NetworkSignals = field(default_factory=NetworkSignals)

    def to_dict(self) -> dict[str, Any]:
        """Convert signals to dictionary for serialization."""
        from dataclasses import asdict

        return {
            "profile": asdict(self.profile),
            "content": asdict(self.content),
            "behavior": asdict(self.behavior),
            "network": asdict(self.network),
        }


@dataclass
class RiskResult:
    """
    Result of risk calculation.

    Contains the final score, verdict, and detailed breakdown.
    """

    score: int  # 0-100 cumulative risk score
    verdict: Verdict
    threat_type: ThreatType = ThreatType.NONE

    # Score breakdown by category
    profile_score: int = 0
    content_score: int = 0
    behavior_score: int = 0
    network_score: int = 0

    # Signals used in calculation
    signals: Signals = field(default_factory=Signals)

    # Additional metadata
    needs_llm: bool = False  # Gray zone (60-80), needs LLM review
    llm_verdict: Verdict | None = None
    llm_explanation: str | None = None
    confidence: float = 1.0

    # Contributing factors (for explainability)
    contributing_factors: list[str] = field(default_factory=list)
    mitigating_factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            "score": self.score,
            "verdict": self.verdict.value,
            "threat_type": self.threat_type.value,
            "profile_score": self.profile_score,
            "content_score": self.content_score,
            "behavior_score": self.behavior_score,
            "network_score": self.network_score,
            "needs_llm": self.needs_llm,
            "llm_verdict": self.llm_verdict.value if self.llm_verdict else None,
            "llm_explanation": self.llm_explanation,
            "confidence": self.confidence,
            "contributing_factors": self.contributing_factors,
            "mitigating_factors": self.mitigating_factors,
        }


@dataclass
class MessageContext:
    """
    Context for a message being processed.

    Contains all information needed to analyze a message.
    """

    # Message info
    message_id: int
    chat_id: int
    user_id: int
    text: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # User info
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_bot: bool = False
    is_premium: bool = False

    # Chat info
    chat_type: str = "group"
    chat_title: str | None = None
    group_type: GroupType = GroupType.GENERAL

    # Message metadata
    has_media: bool = False
    media_type: str | None = None
    is_forward: bool = False
    forward_from_chat_id: int | None = None
    reply_to_message_id: int | None = None

    # Raw data for detailed analysis
    raw_message: dict[str, Any] = field(default_factory=dict)
    raw_user: dict[str, Any] = field(default_factory=dict)
    raw_chat: dict[str, Any] = field(default_factory=dict)


@dataclass
class Action:
    """
    Action to be taken based on risk verdict.

    Used by the ActionEngine to execute the appropriate response.
    """

    action_type: str  # "delete", "restrict", "ban", "warn", "notify_admin"
    target_user_id: int
    target_chat_id: int
    message_id: int | None = None

    # Action parameters
    duration_seconds: int | None = None  # For temporary restrictions
    reason: str | None = None
    notify_user: bool = True
    notify_admins: bool = False
    log_decision: bool = True

    # Metadata
    risk_result: RiskResult | None = None
