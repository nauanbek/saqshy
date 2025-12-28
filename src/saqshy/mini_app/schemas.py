"""
SAQSHY Mini App API Schemas

Pydantic models for request/response validation.
All API responses follow a consistent format:
{
    "success": true/false,
    "data": {...} or null,
    "error": {"code": "...", "message": "..."} or null
}
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Telegram ID Validation Constants
# =============================================================================

# Telegram user/chat ID range (based on observed values)
# User IDs: positive integers, typically up to ~7 billion as of 2024
# Chat IDs: negative for groups/channels (supergroup: -100XXXXXXXXXX)
TELEGRAM_USER_ID_MIN = 1
TELEGRAM_USER_ID_MAX = 10_000_000_000  # 10 billion upper limit

TELEGRAM_CHAT_ID_MIN = -10_000_000_000_000  # Supergroups can have very negative IDs
TELEGRAM_CHAT_ID_MAX = 10_000_000_000  # Positive for users, private chats


def validate_telegram_user_id(user_id: int) -> int:
    """Validate Telegram user ID is within reasonable bounds."""
    if not isinstance(user_id, int):
        raise ValueError("user_id must be an integer")
    if user_id < TELEGRAM_USER_ID_MIN or user_id > TELEGRAM_USER_ID_MAX:
        raise ValueError(
            f"user_id must be between {TELEGRAM_USER_ID_MIN} and {TELEGRAM_USER_ID_MAX}"
        )
    return user_id


def validate_telegram_chat_id(chat_id: int) -> int:
    """Validate Telegram chat ID is within reasonable bounds."""
    if not isinstance(chat_id, int):
        raise ValueError("chat_id must be an integer")
    if chat_id < TELEGRAM_CHAT_ID_MIN or chat_id > TELEGRAM_CHAT_ID_MAX:
        raise ValueError(
            f"chat_id must be between {TELEGRAM_CHAT_ID_MIN} and {TELEGRAM_CHAT_ID_MAX}"
        )
    return chat_id

# =============================================================================
# Type Aliases
# =============================================================================

GroupTypeEnum = Literal["general", "tech", "deals", "crypto"]
VerdictEnum = Literal["allow", "watch", "limit", "review", "block"]
TrustLevelEnum = Literal["new", "sandbox", "limited", "trusted", "admin"]
OverrideActionEnum = Literal["approve", "confirm_block"]


# =============================================================================
# Base Response Models
# =============================================================================


class ErrorDetail(BaseModel):
    """Error detail in API responses."""

    code: str = Field(..., description="Error code (e.g., 'UNAUTHORIZED', 'NOT_FOUND')")
    message: str = Field(..., description="Human-readable error message")


class APIResponse(BaseModel):
    """Base API response wrapper."""

    success: bool = Field(..., description="Whether the request succeeded")
    data: Any | None = Field(default=None, description="Response data on success")
    error: ErrorDetail | None = Field(default=None, description="Error details on failure")

    @classmethod
    def ok(cls, data: Any = None) -> "APIResponse":
        """Create a successful response."""
        return cls(success=True, data=data, error=None)

    @classmethod
    def fail(cls, code: str, message: str) -> "APIResponse":
        """Create a failure response."""
        return cls(success=False, data=None, error=ErrorDetail(code=code, message=message))


# =============================================================================
# Group Settings
# =============================================================================


class GroupSettingsRequest(BaseModel):
    """Request schema for updating group settings.

    All fields are optional - only provided fields will be updated.
    """

    group_type: GroupTypeEnum | None = Field(
        None,
        description="Group type affecting spam thresholds",
    )
    sensitivity: int | None = Field(
        None,
        ge=1,
        le=10,
        description="Detection sensitivity (1=lenient, 10=strict)",
    )
    sandbox_enabled: bool | None = Field(
        None,
        description="Whether sandbox mode is enabled for new users",
    )
    sandbox_duration_hours: int | None = Field(
        None,
        ge=1,
        le=168,
        description="Duration of sandbox period in hours (1-168)",
    )
    linked_channel_id: int | None = Field(
        None,
        description="Linked channel ID for subscription checks",
    )
    admin_alert_chat_id: int | None = Field(
        None,
        description="Chat ID to send admin alerts to",
    )
    link_whitelist: list[str] | None = Field(
        None,
        description="List of whitelisted domains for links",
    )
    language: str | None = Field(
        None,
        max_length=10,
        description="Primary group language (ISO 639-1)",
    )


class GroupSettingsResponse(BaseModel):
    """Response schema for group settings."""

    group_id: int = Field(..., description="Telegram chat_id")
    title: str = Field(..., description="Group display name")
    username: str | None = Field(None, description="Group @username (for public groups)")
    group_type: GroupTypeEnum = Field(..., description="Group type")
    sensitivity: int = Field(..., description="Detection sensitivity (1-10)")
    sandbox_enabled: bool = Field(..., description="Whether sandbox mode is enabled")
    sandbox_duration_hours: int = Field(..., description="Sandbox duration in hours")
    linked_channel_id: int | None = Field(None, description="Linked channel ID")
    link_whitelist: list[str] = Field(default_factory=list, description="Whitelisted domains")
    language: str = Field(..., description="Primary group language")
    members_count: int = Field(0, description="Cached member count")
    blocked_count: int = Field(0, description="Total spam messages blocked")
    is_active: bool = Field(True, description="Whether bot is active")
    created_at: str = Field(..., description="When group was registered")
    updated_at: str = Field(..., description="When settings were last updated")


class GroupInfoResponse(BaseModel):
    """Minimal group info for list views."""

    group_id: int
    title: str
    username: str | None = None
    group_type: GroupTypeEnum
    members_count: int = 0
    is_active: bool = True


# =============================================================================
# Group Statistics
# =============================================================================


class ThreatTypeCount(BaseModel):
    """Threat type with count."""

    type: str = Field(..., description="Threat type (e.g., 'crypto_scam', 'phishing')")
    count: int = Field(..., description="Number of occurrences")


class GroupStatsResponse(BaseModel):
    """Response schema for group statistics.

    Includes verdict counts and accuracy metrics for the specified period.
    """

    group_id: int = Field(..., description="Telegram chat_id")
    group_type: GroupTypeEnum = Field(..., description="Group type")
    period_days: int = Field(..., description="Statistics period in days")

    # Verdict counts
    total_messages: int = Field(0, description="Total messages processed")
    allowed: int = Field(0, description="Messages allowed")
    watched: int = Field(0, description="Messages in watch state")
    limited: int = Field(0, description="Messages with limited actions")
    reviewed: int = Field(0, description="Messages queued for review")
    blocked: int = Field(0, description="Messages blocked")

    # Accuracy metrics
    fp_count: int = Field(0, description="False positives (admin overrides)")
    tp_count: int = Field(0, description="True positives (confirmed spam)")
    fp_rate: float = Field(0.0, description="False positive rate (fp_count / blocked)")

    # Performance metrics
    avg_processing_time_ms: float | None = Field(
        None,
        description="Average processing time in milliseconds",
    )
    llm_usage_percent: float = Field(
        0.0,
        description="Percentage of decisions that used LLM",
    )

    # Top threats
    top_threat_types: list[ThreatTypeCount] = Field(
        default_factory=list,
        description="Most common threat types",
    )

    # Member stats
    users_in_sandbox: int = Field(0, description="Users currently in sandbox")
    active_users_24h: int = Field(0, description="Users active in last 24 hours")


# =============================================================================
# Decisions / Review Queue
# =============================================================================


class ReviewItem(BaseModel):
    """Item in the review queue."""

    decision_id: str = Field(..., description="UUID of the decision")
    user_id: int = Field(..., description="Telegram user_id")
    username: str | None = Field(None, description="User's @username")
    first_name: str | None = Field(None, description="User's first name")
    message_id: int | None = Field(None, description="Telegram message_id")
    message_preview: str | None = Field(None, description="First 100 chars of message")
    risk_score: int = Field(..., description="Risk score (0-100)")
    verdict: VerdictEnum = Field(..., description="Current verdict")
    threat_type: str | None = Field(None, description="Detected threat type")
    created_at: str = Field(..., description="When decision was made")
    is_overridden: bool = Field(False, description="Whether decision was overridden")


class ReviewQueueResponse(BaseModel):
    """Response for review queue listing."""

    items: list[ReviewItem] = Field(default_factory=list)
    total: int = Field(0, description="Total items in queue")
    limit: int = Field(50, description="Page size")
    offset: int = Field(0, description="Page offset")


class DecisionOverrideRequest(BaseModel):
    """Request schema for overriding a decision."""

    action: OverrideActionEnum = Field(
        ...,
        description="Override action: 'approve' to allow message, 'confirm_block' to confirm spam",
    )
    reason: str | None = Field(
        None,
        max_length=500,
        description="Reason for the override (optional)",
    )


class DecisionOverrideResponse(BaseModel):
    """Response for decision override."""

    decision_id: str = Field(..., description="UUID of the overridden decision")
    previous_verdict: VerdictEnum = Field(..., description="Verdict before override")
    new_action: str = Field(..., description="Action taken")
    overridden_by: int = Field(..., description="Admin user_id who overrode")
    overridden_at: str = Field(..., description="When override occurred")


class DecisionDetail(BaseModel):
    """Detailed spam decision for detail views."""

    id: str = Field(..., description="UUID of the decision")
    group_id: int = Field(..., description="Telegram chat_id")
    user_id: int = Field(..., description="Telegram user_id")
    username: str | None = None
    first_name: str | None = None
    message_id: int | None = None
    risk_score: int = Field(..., ge=0, le=100)
    verdict: VerdictEnum
    threat_type: str | None = None

    # Signal breakdown
    profile_signals: dict[str, Any] = Field(default_factory=dict)
    content_signals: dict[str, Any] = Field(default_factory=dict)
    behavior_signals: dict[str, Any] = Field(default_factory=dict)

    # LLM analysis
    llm_used: bool = False
    llm_response: dict[str, Any] | None = None
    llm_latency_ms: int | None = None

    # Actions taken
    action_taken: str | None = None
    message_deleted: bool = False
    user_banned: bool = False
    user_restricted: bool = False

    # Override info
    overridden_by: int | None = None
    overridden_at: str | None = None
    override_reason: str | None = None

    # Timestamps
    created_at: str
    processing_time_ms: int | None = None


class DecisionListResponse(BaseModel):
    """Response for decision listing."""

    decisions: list[ReviewItem] = Field(default_factory=list)
    total: int = Field(0)
    limit: int = Field(50)
    offset: int = Field(0)


# =============================================================================
# User Management
# =============================================================================


class UserProfileResponse(BaseModel):
    """Response schema for user profile in a group."""

    user_id: int = Field(..., description="Telegram user_id")
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    display_name: str = Field(..., description="Best available display name")

    # Trust info
    trust_level: TrustLevelEnum = Field(..., description="User's trust level")
    trust_score: int = Field(..., ge=0, le=100, description="Numeric trust score")

    # Activity
    message_count: int = Field(0, description="Total messages in this group")
    last_message_at: str | None = None
    joined_at: str | None = None
    first_message_at: str | None = None

    # Sandbox
    is_in_sandbox: bool = Field(False, description="Whether user is in sandbox")
    sandbox_expires_at: str | None = None
    messages_in_sandbox: int = Field(0, description="Messages sent during sandbox")

    # Profile signals
    has_photo: bool | None = None
    is_premium: bool | None = None
    bio: str | None = None
    account_age_days: int | None = None


class UserStatsResponse(BaseModel):
    """Response schema for user stats across groups."""

    user_id: int
    username: str | None = None
    first_name: str | None = None

    # Aggregate stats
    total_groups: int = Field(0, description="Groups where user is a member")
    total_messages: int = Field(0, description="Total messages across groups")
    total_blocks: int = Field(0, description="Times user was blocked")
    total_reviews: int = Field(0, description="Times user was reviewed")

    # Recent decisions
    recent_decisions: list[ReviewItem] = Field(default_factory=list)


class UserListRequest(BaseModel):
    """Request schema for listing users."""

    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0)
    trust_level: TrustLevelEnum | None = None
    sort_by: Literal["joined_at", "message_count", "trust_score"] = "joined_at"
    sort_order: Literal["asc", "desc"] = "desc"


class UserListResponse(BaseModel):
    """Response for user listing."""

    users: list[UserProfileResponse] = Field(default_factory=list)
    total: int = Field(0)
    limit: int = Field(50)
    offset: int = Field(0)


# =============================================================================
# Whitelist/Blacklist
# =============================================================================


class WhitelistEntry(BaseModel):
    """Whitelist entry."""

    user_id: int
    username: str | None = None
    added_by: int = Field(..., description="Admin who added this entry")
    added_at: str
    reason: str | None = None


class BlacklistEntry(BaseModel):
    """Blacklist entry."""

    user_id: int
    username: str | None = None
    added_by: int = Field(..., description="Admin who added this entry")
    added_at: str
    reason: str | None = None
    expires_at: str | None = Field(None, description="None = permanent ban")


class ListModifyRequest(BaseModel):
    """Request schema for adding to whitelist/blacklist."""

    reason: str = Field("", max_length=500)
    duration_hours: int | None = Field(
        None,
        ge=1,
        description="For blacklist only, None = permanent",
    )


class ListModifyResponse(BaseModel):
    """Response for whitelist/blacklist modification."""

    success: bool
    user_id: int
    action: Literal["added", "removed", "already_exists", "not_found"]


# =============================================================================
# Admin Actions
# =============================================================================


class AdminActionLog(BaseModel):
    """Admin action audit log entry."""

    id: str = Field(..., description="UUID of the action")
    group_id: int
    admin_id: int
    admin_username: str | None = None
    action_type: str = Field(..., description="e.g., 'override', 'whitelist', 'settings_change'")
    target_user_id: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AdminActionListResponse(BaseModel):
    """Response for admin action listing."""

    actions: list[AdminActionLog] = Field(default_factory=list)
    total: int = Field(0)
    limit: int = Field(50)
    offset: int = Field(0)


# =============================================================================
# Validation Request Schemas
# =============================================================================


class ValidateLinkedChannelRequest(BaseModel):
    """Request to validate a linked channel."""

    channel_id: int = Field(..., description="Channel ID to validate")


class ValidateLinkedChannelResponse(BaseModel):
    """Response for linked channel validation."""

    valid: bool = Field(..., description="Whether bot has access to channel")
    channel_title: str | None = Field(None, description="Channel title if accessible")
    error: str | None = Field(None, description="Error message if not valid")


class ChannelValidateResponse(BaseModel):
    """Response for channel validation endpoint.

    This schema is used by the /api/channels/validate endpoint
    which accepts channel username (@channel) or numeric ID as query param.
    """

    valid: bool = Field(..., description="Whether the channel is valid and accessible")
    channel_id: int = Field(..., description="Numeric channel ID")
    title: str | None = Field(None, description="Channel title if accessible")
    error: str | None = Field(None, description="Error message if validation failed")
