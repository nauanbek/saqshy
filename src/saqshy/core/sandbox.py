"""
SAQSHY Sandbox and Trust System

Implements the Trust State Machine for new users:

Trust State Machine:
    NEW -> SANDBOX -> LIMITED -> TRUSTED

    Transitions:
    - NEW -> SANDBOX: On first message (applies restrictions)
    - NEW -> TRUSTED: If is_channel_subscriber (skip sandbox)
    - NEW -> SOFT_WATCH: If group_type='deals' (no restrictions, only logging)
    - SANDBOX -> LIMITED: After N approved messages or time expired
    - LIMITED -> TRUSTED: After consistent good behavior
    - Any -> SANDBOX: On violation (regression)

Sandbox Mode (general/tech/crypto groups):
    - Restrict links, media, forwards
    - Monitor behavior closely
    - Release after N approved messages or time expiry

Soft Watch Mode (deals groups):
    - NO restrictions applied
    - Messages are logged and tracked
    - Only extreme cases (known spam DB match) trigger action
    - Links/promo content is NORMAL in deals groups

Channel Subscription Exit Condition:
    Users subscribed to linked_channel_id bypass sandbox entirely.
    This is the STRONGEST trust signal.

Redis Key Schema:
    saqshy:sandbox:{chat_id}:{user_id}     # JSON SandboxState, TTL = duration
    saqshy:trust:{chat_id}:{user_id}       # String trust level, TTL = 30 days
    saqshy:softwatch:{chat_id}:{user_id}   # JSON soft watch state

Architecture Note:
    This module has ZERO external dependencies beyond stdlib.
    All Telegram operations are delegated via ChatRestrictionsProtocol.
    All logging uses LoggerProtocol from log_facade.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from saqshy.core.log_facade import get_logger
from saqshy.core.protocols import (
    CacheProtocol,
    ChannelSubscriptionProtocol,
    ChatRestrictionsProtocol,
    LoggerProtocol,
    TelegramOperationError,
)
from saqshy.core.types import GroupType, RiskResult, Verdict

if TYPE_CHECKING:
    pass


# =============================================================================
# Constants
# =============================================================================

# Redis TTLs
TTL_SANDBOX_STATE = 86400 * 7  # 7 days (extended beyond duration for audit)
TTL_TRUST_LEVEL = 86400 * 30  # 30 days
TTL_SOFT_WATCH = 86400 * 7  # 7 days

# Redis key prefixes
KEY_PREFIX_SANDBOX = "saqshy:sandbox"
KEY_PREFIX_TRUST = "saqshy:trust"
KEY_PREFIX_SOFT_WATCH = "saqshy:softwatch"

# Default settings
DEFAULT_SANDBOX_DURATION_HOURS = 24
DEFAULT_SOFT_WATCH_DURATION_HOURS = 12
DEFAULT_APPROVED_MESSAGES_TO_RELEASE = 3
DEFAULT_MIN_HOURS_IN_SANDBOX = 1

# Trust score adjustments by level
TRUST_SCORE_ADJUSTMENTS: dict[str, int] = {
    "untrusted": 5,
    "provisional": 0,
    "trusted": -10,
    "established": -20,
}

# Soft watch mode thresholds (for deals groups)
# Lower than normal thresholds (60-80) because deals groups are more permissive
SOFT_WATCH_THRESHOLDS: dict[str, int] = {
    "consult_llm": 50,  # Lower than normal (60-80) for deals groups
    "flag_admin": 70,  # Alert admins but don't delete
    "delete": 85,  # Only extreme cases get deleted
}


# =============================================================================
# Serialization Mixin
# =============================================================================


class StateSerializationMixin:
    """
    Mixin providing JSON serialization for sandbox states.

    This mixin provides common to_dict() and from_dict() methods for
    dataclasses that need to be serialized to/from Redis.

    Handles:
    - datetime objects (to/from ISO format strings)
    - Enum values (to/from string values)
    - Optional fields with None values

    Usage:
        @dataclass(frozen=True)
        class MyState(StateSerializationMixin):
            user_id: int
            created_at: datetime
            status: MyEnum

        # Subclasses must define _ENUM_FIELDS mapping field names to enum classes
        _ENUM_FIELDS: ClassVar[dict[str, type[Enum]]] = {"status": MyEnum}
    """

    # Subclasses should override this to map field names to their Enum types
    _ENUM_FIELDS: ClassVar[dict[str, type[Enum]]] = {}

    def to_dict(self) -> dict[str, Any]:
        """
        Convert state to dictionary for Redis storage.

        Automatically handles:
        - datetime -> ISO format string
        - Enum -> string value
        - None values preserved as-is
        """
        data: dict[str, Any] = {}
        for f in fields(self):  # type: ignore[arg-type]
            value = getattr(self, f.name)
            if isinstance(value, datetime):
                data[f.name] = value.isoformat()
            elif isinstance(value, Enum):
                data[f.name] = value.value
            else:
                data[f.name] = value
        return data

    @classmethod
    def _parse_datetime(cls, value: str | datetime | None) -> datetime | None:
        """
        Parse datetime from string or return as-is.

        Args:
            value: ISO format string, datetime object, or None.

        Returns:
            Parsed datetime or None.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)


# =============================================================================
# Enums
# =============================================================================


class SandboxStatus(str, Enum):
    """User's sandbox status in a group."""

    ACTIVE = "active"  # User is in sandbox mode (restrictions applied)
    SOFT_WATCH = "soft_watch"  # Soft watch mode (deals groups, no restrictions)
    RELEASED = "released"  # User has been released from sandbox
    EXEMPT = "exempt"  # User is exempt (admin, channel subscriber, etc.)


class TrustLevel(str, Enum):
    """User trust level within a group."""

    UNTRUSTED = "untrusted"  # New users, sandboxed
    PROVISIONAL = "provisional"  # Passed sandbox, limited trust
    TRUSTED = "trusted"  # Several approved messages
    ESTABLISHED = "established"  # Long history, full trust


class ReleaseReason(str, Enum):
    """Reason for releasing a user from sandbox."""

    TIME_EXPIRED = "time_expired"
    APPROVED_MESSAGES = "approved_messages"
    CHANNEL_SUBSCRIBER = "channel_subscriber"
    ADMIN_RELEASE = "admin_release"
    ADMIN_EXEMPT = "admin_exempt"
    PREMIUM_USER = "premium_user"


# =============================================================================
# Data Classes (Immutable)
# =============================================================================


@dataclass(frozen=True)
class SandboxState(StateSerializationMixin):
    """
    Immutable sandbox state for a user in a group.

    This state is persisted in Redis and used to track user progression
    through the sandbox system. Being frozen ensures thread-safety
    and prevents accidental mutations.

    Use with_* methods to create modified copies:
        new_state = state.with_message_recorded(approved=True)
        released_state = state.with_released("time_expired")

    Attributes:
        user_id: Telegram user ID.
        chat_id: Telegram chat/group ID.
        entered_at: When user entered sandbox (UTC).
        expires_at: When sandbox expires (UTC).
        messages_sent: Total messages sent while in sandbox.
        approved_messages: Messages that passed spam checks.
        is_released: Whether user has been released from sandbox.
        release_reason: Why user was released (if released).
        status: Current sandbox status.
        violations: Number of violations during sandbox.
    """

    # Enum field mapping for deserialization
    _ENUM_FIELDS: ClassVar[dict[str, type[Enum]]] = {"status": SandboxStatus}

    user_id: int
    chat_id: int
    entered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    messages_sent: int = 0
    approved_messages: int = 0
    is_released: bool = False
    release_reason: str | None = None
    status: SandboxStatus = SandboxStatus.ACTIVE
    violations: int = 0

    def __post_init__(self) -> None:
        """Set default expiry and validate fields."""
        # For frozen dataclass, use object.__setattr__ for initialization
        if self.expires_at is None:
            default_expiry = self.entered_at + timedelta(hours=DEFAULT_SANDBOX_DURATION_HOURS)
            object.__setattr__(self, "expires_at", default_expiry)

        # Validation
        if self.messages_sent < 0:
            raise ValueError("messages_sent cannot be negative")
        if self.approved_messages < 0:
            raise ValueError("approved_messages cannot be negative")
        if self.violations < 0:
            raise ValueError("violations cannot be negative")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SandboxState:
        """Deserialize from dictionary."""
        return cls(
            user_id=data["user_id"],
            chat_id=data["chat_id"],
            entered_at=cls._parse_datetime(data["entered_at"]),  # type: ignore[arg-type]
            expires_at=cls._parse_datetime(data.get("expires_at")),
            messages_sent=data.get("messages_sent", 0),
            approved_messages=data.get("approved_messages", 0),
            is_released=data.get("is_released", False),
            release_reason=data.get("release_reason"),
            status=SandboxStatus(data.get("status", "active")),
            violations=data.get("violations", 0),
        )

    def is_expired(self) -> bool:
        """Check if sandbox period has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= self.expires_at

    def time_remaining(self) -> timedelta:
        """Get time remaining in sandbox."""
        if self.expires_at is None:
            return timedelta(hours=DEFAULT_SANDBOX_DURATION_HOURS)
        remaining = self.expires_at - datetime.now(UTC)
        return max(remaining, timedelta(0))

    # =========================================================================
    # Immutable Update Methods
    # =========================================================================

    def with_message_recorded(self, approved: bool) -> SandboxState:
        """
        Return new state with message recorded.

        Args:
            approved: Whether the message was approved (not spam).

        Returns:
            New SandboxState with updated counters.
        """
        return replace(
            self,
            messages_sent=self.messages_sent + 1,
            approved_messages=self.approved_messages + (1 if approved else 0),
            violations=self.violations + (0 if approved else 1),
        )

    def with_released(self, reason: str) -> SandboxState:
        """
        Return new state marked as released.

        Args:
            reason: Reason for release (from ReleaseReason enum values).

        Returns:
            New SandboxState marked as released.
        """
        return replace(
            self,
            is_released=True,
            release_reason=reason,
            status=SandboxStatus.RELEASED,
        )


@dataclass
class SandboxConfig:
    """Configuration for sandbox mode."""

    # Duration settings
    duration_hours: int = DEFAULT_SANDBOX_DURATION_HOURS
    soft_watch_duration_hours: int = DEFAULT_SOFT_WATCH_DURATION_HOURS

    # Message limits while in sandbox
    message_limit_per_hour: int = 5
    message_limit_per_day: int = 20

    # Release requirements
    approved_messages_to_release: int = DEFAULT_APPROVED_MESSAGES_TO_RELEASE
    min_hours_in_sandbox: int = DEFAULT_MIN_HOURS_IN_SANDBOX

    # Features
    require_captcha: bool = True
    allow_links: bool = False
    allow_forwards: bool = False
    allow_media: bool = True

    # Auto-actions
    auto_release_channel_subscribers: bool = True
    auto_release_premium_users: bool = True

    # Linked channel for trust verification
    linked_channel_id: int | None = None


@dataclass
class SoftWatchVerdict:
    """
    Verdict from Soft Watch mode evaluation.

    Used for deals groups where restrictions are not applied,
    but behavior is still tracked.

    Attributes:
        action: What action to take ("allow", "flag", "hold", "consult_llm").
        reason: Human-readable explanation.
        confidence: Confidence in the verdict (0.0-1.0).
        should_delete: Whether to delete the message (extreme cases only).
        should_notify_admin: Whether to notify admins.
    """

    action: str  # "allow", "flag", "hold", "consult_llm"
    reason: str
    confidence: float = 1.0
    should_delete: bool = False
    should_notify_admin: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "action": self.action,
            "reason": self.reason,
            "confidence": self.confidence,
            "should_delete": self.should_delete,
            "should_notify_admin": self.should_notify_admin,
        }


@dataclass(frozen=True)
class SoftWatchState(StateSerializationMixin):
    """
    Immutable soft watch state for a user in a deals group.

    Tracks behavior without applying restrictions.
    Use with_* methods to create modified copies.
    """

    user_id: int
    chat_id: int
    entered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    messages_sent: int = 0
    messages_flagged: int = 0
    spam_db_matches: int = 0
    is_completed: bool = False

    def __post_init__(self) -> None:
        """Set default expiry and validate fields."""
        if self.expires_at is None:
            default_expiry = self.entered_at + timedelta(hours=DEFAULT_SOFT_WATCH_DURATION_HOURS)
            object.__setattr__(self, "expires_at", default_expiry)

        # Validation
        if self.messages_sent < 0:
            raise ValueError("messages_sent cannot be negative")
        if self.messages_flagged < 0:
            raise ValueError("messages_flagged cannot be negative")
        if self.spam_db_matches < 0:
            raise ValueError("spam_db_matches cannot be negative")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SoftWatchState:
        """Deserialize from dictionary."""
        return cls(
            user_id=data["user_id"],
            chat_id=data["chat_id"],
            entered_at=cls._parse_datetime(data["entered_at"]),  # type: ignore[arg-type]
            expires_at=cls._parse_datetime(data.get("expires_at")),
            messages_sent=data.get("messages_sent", 0),
            messages_flagged=data.get("messages_flagged", 0),
            spam_db_matches=data.get("spam_db_matches", 0),
            is_completed=data.get("is_completed", False),
        )

    def with_message_recorded(
        self,
        flagged: bool = False,
        spam_db_match: bool = False,
    ) -> SoftWatchState:
        """
        Return new state with message recorded.

        Args:
            flagged: Whether the message was flagged as suspicious.
            spam_db_match: Whether message matched spam DB.

        Returns:
            New SoftWatchState with updated counters.
        """
        return replace(
            self,
            messages_sent=self.messages_sent + 1,
            messages_flagged=self.messages_flagged + (1 if flagged else 0),
            spam_db_matches=self.spam_db_matches + (1 if spam_db_match else 0),
        )

    def with_completed(self) -> SoftWatchState:
        """Return new state marked as completed."""
        return replace(self, is_completed=True)


# =============================================================================
# Sandbox Manager
# =============================================================================


class SandboxManager:
    """
    Manages sandbox mode for users across groups.

    This class coordinates:
    - Entering users into sandbox on first message
    - Tracking message counts and violations
    - Applying/removing Telegram restrictions (via ChatRestrictionsProtocol)
    - Checking release conditions
    - Channel subscription verification

    Architecture:
        Uses protocol-based dependency injection for:
        - CacheProtocol: Redis operations
        - ChatRestrictionsProtocol: Telegram API calls
        - ChannelSubscriptionProtocol: Channel membership checks
        - LoggerProtocol: Structured logging

    Thread Safety:
        This class is thread-safe when used with asyncio.
        Redis operations are atomic or use transactions.

    Error Handling:
        All Telegram API and Redis errors are caught and logged.
        Failures do not leave user in an inconsistent state.
        On error, defaults to allowing the message (fail open).

    Example:
        >>> from saqshy.core.sandbox import SandboxManager
        >>> from saqshy.services.cache import CacheService
        >>> from saqshy.bot.adapters import TelegramRestrictionsAdapter
        >>>
        >>> cache = CacheService(redis_url="redis://localhost:6379")
        >>> restrictions = TelegramRestrictionsAdapter(bot)
        >>> manager = SandboxManager(cache, restrictions)
        >>>
        >>> # Put user in sandbox
        >>> state = await manager.enter_sandbox(user_id=123, chat_id=-100456)
        >>>
        >>> # Record a message
        >>> state = await manager.record_message(
        ...     user_id=123, chat_id=-100456, approved=True
        ... )
    """

    def __init__(
        self,
        cache: CacheProtocol,
        restrictions: ChatRestrictionsProtocol | None = None,
        channel_subscription: ChannelSubscriptionProtocol | None = None,
        logger: LoggerProtocol | None = None,
    ) -> None:
        """
        Initialize the sandbox manager.

        Args:
            cache: Cache service for state persistence (required).
            restrictions: Adapter for Telegram restrictions (optional).
            channel_subscription: Service for channel subscription checks (optional).
            logger: Logger instance (optional, uses default if not provided).
        """
        self._cache = cache
        self._restrictions = restrictions
        self._channel_service = channel_subscription
        self._logger = logger or get_logger(__name__)

    # =========================================================================
    # Redis Key Management
    # =========================================================================

    def _sandbox_key(self, chat_id: int, user_id: int) -> str:
        """Generate Redis key for sandbox state."""
        return f"{KEY_PREFIX_SANDBOX}:{chat_id}:{user_id}"

    def _trust_key(self, chat_id: int, user_id: int) -> str:
        """Generate Redis key for trust level."""
        return f"{KEY_PREFIX_TRUST}:{chat_id}:{user_id}"

    def _soft_watch_key(self, chat_id: int, user_id: int) -> str:
        """Generate Redis key for soft watch state."""
        return f"{KEY_PREFIX_SOFT_WATCH}:{chat_id}:{user_id}"

    # =========================================================================
    # Sandbox Entry
    # =========================================================================

    async def enter_sandbox(
        self,
        user_id: int,
        chat_id: int,
        duration_hours: int = DEFAULT_SANDBOX_DURATION_HOURS,
        group_type: GroupType = GroupType.GENERAL,
        linked_channel_id: int | None = None,
    ) -> SandboxState:
        """
        Put user in sandbox mode.

        This method:
        1. Checks if user is already sandboxed
        2. Checks for channel subscription (bypass if subscribed)
        3. Creates sandbox state and persists to Redis
        4. Applies Telegram restrictions (for non-deals groups)

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            duration_hours: Sandbox duration in hours.
            group_type: Type of group (affects restrictions).
            linked_channel_id: Channel to check for subscription.

        Returns:
            SandboxState with current status.
        """
        log = self._logger.bind(user_id=user_id, chat_id=chat_id, group_type=group_type.value)

        # Check if user is already sandboxed
        existing_state = await self._validate_sandbox_entry(user_id, chat_id, log)
        if existing_state is not None:
            return existing_state

        # Check for channel subscription bypass
        exempt_state = await self._check_channel_subscription_bypass(
            user_id=user_id,
            chat_id=chat_id,
            linked_channel_id=linked_channel_id,
            log=log,
        )
        if exempt_state is not None:
            return exempt_state

        # Create and persist sandbox state
        state = self._create_sandbox_state(
            user_id=user_id,
            chat_id=chat_id,
            duration_hours=duration_hours,
            group_type=group_type,
        )
        await self._persist_sandbox_state(state)

        # Apply restrictions if needed
        await self._apply_initial_restrictions(state)

        log.info(
            "user_entered_sandbox",
            status=state.status.value,
            duration_hours=duration_hours,
            expires_at=state.expires_at.isoformat() if state.expires_at else None,
        )

        return state

    async def _validate_sandbox_entry(
        self,
        user_id: int,
        chat_id: int,
        log: LoggerProtocol,
    ) -> SandboxState | None:
        """
        Validate if user can enter sandbox.

        Returns existing state if user is already sandboxed.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            log: Bound logger with context.

        Returns:
            Existing SandboxState if already sandboxed, None otherwise.
        """
        existing_state = await self.get_sandbox_state(user_id, chat_id)
        if existing_state is not None and not existing_state.is_released:
            log.debug("user_already_sandboxed")
            return existing_state
        return None

    async def _check_channel_subscription_bypass(
        self,
        user_id: int,
        chat_id: int,
        linked_channel_id: int | None,
        log: LoggerProtocol,
    ) -> SandboxState | None:
        """
        Check if user should bypass sandbox due to channel subscription.

        Channel subscription is the STRONGEST trust signal.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            linked_channel_id: Channel to check for subscription.
            log: Bound logger with context.

        Returns:
            Exempt SandboxState if subscribed, None otherwise.
        """
        if not linked_channel_id or not self._channel_service:
            return None

        is_subscriber = await self._channel_service.is_subscribed(
            user_id=user_id, channel_id=linked_channel_id
        )

        if is_subscriber:
            log.info(
                "sandbox_bypassed_channel_subscriber",
                channel_id=linked_channel_id,
            )
            state = SandboxState(
                user_id=user_id,
                chat_id=chat_id,
                is_released=True,
                release_reason=ReleaseReason.CHANNEL_SUBSCRIBER.value,
                status=SandboxStatus.EXEMPT,
            )
            await self._save_sandbox_state(state)
            return state

        return None

    def _create_sandbox_state(
        self,
        user_id: int,
        chat_id: int,
        duration_hours: int,
        group_type: GroupType,
    ) -> SandboxState:
        """
        Create sandbox state based on group type.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            duration_hours: Sandbox duration in hours.
            group_type: Type of group (affects sandbox mode).

        Returns:
            New SandboxState configured for the group type.
        """
        # Determine sandbox mode based on group type
        if group_type == GroupType.DEALS:
            status = SandboxStatus.SOFT_WATCH
            effective_duration = DEFAULT_SOFT_WATCH_DURATION_HOURS
        else:
            status = SandboxStatus.ACTIVE
            effective_duration = duration_hours

        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=effective_duration)

        return SandboxState(
            user_id=user_id,
            chat_id=chat_id,
            entered_at=now,
            expires_at=expires_at,
            status=status,
        )

    async def _persist_sandbox_state(self, state: SandboxState) -> None:
        """
        Persist sandbox state to Redis.

        Args:
            state: SandboxState to persist.
        """
        await self._save_sandbox_state(state)

    async def _apply_initial_restrictions(self, state: SandboxState) -> None:
        """
        Apply initial Telegram restrictions for sandboxed user.

        Only applies restrictions for ACTIVE sandbox status.
        SOFT_WATCH mode (deals groups) does not apply restrictions.

        Args:
            state: Current SandboxState.
        """
        if state.status == SandboxStatus.ACTIVE and self._restrictions:
            try:
                await self._restrictions.apply_sandbox_restrictions(state.user_id, state.chat_id)
            except TelegramOperationError as e:
                self._logger.warning(
                    "apply_restrictions_failed",
                    user_id=state.user_id,
                    chat_id=state.chat_id,
                    error_type=e.error_type,
                )
                # Fail open - continue without restrictions

    # =========================================================================
    # Sandbox State Management
    # =========================================================================

    async def is_sandboxed(self, user_id: int, chat_id: int) -> bool:
        """
        Check if user is currently sandboxed.

        Returns True if user is in active sandbox or soft watch mode.
        Returns False if user is released, exempt, or not in sandbox.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            True if user is currently sandboxed.
        """
        state = await self.get_sandbox_state(user_id, chat_id)
        if state is None:
            return False

        # Check if released
        if state.is_released:
            return False

        # Check if expired
        if state.is_expired():
            # Auto-release on expiry check
            await self.release_from_sandbox(
                user_id, chat_id, reason=ReleaseReason.TIME_EXPIRED.value
            )
            return False

        return state.status in (SandboxStatus.ACTIVE, SandboxStatus.SOFT_WATCH)

    async def get_sandbox_state(self, user_id: int, chat_id: int) -> SandboxState | None:
        """
        Get current sandbox state from Redis.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            SandboxState or None if not found.
        """
        key = self._sandbox_key(chat_id, user_id)
        data = await self._cache.get_json(key)

        if data is None:
            return None

        try:
            return SandboxState.from_dict(data)
        except (KeyError, ValueError) as e:
            self._logger.warning(
                "invalid_sandbox_state",
                key=key,
                error=str(e),
            )
            return None

    async def _save_sandbox_state(self, state: SandboxState) -> bool:
        """
        Save sandbox state to Redis.

        Args:
            state: SandboxState to save.

        Returns:
            True if saved successfully.
        """
        key = self._sandbox_key(state.chat_id, state.user_id)
        return await self._cache.set_json(key, state.to_dict(), ttl=TTL_SANDBOX_STATE)

    # =========================================================================
    # Message Recording
    # =========================================================================

    async def record_message(
        self,
        user_id: int,
        chat_id: int,
        approved: bool,
    ) -> SandboxState | None:
        """
        Record a message and check for release conditions.

        This method:
        1. Gets current sandbox state
        2. Creates new state with updated counters
        3. Checks if user should be released
        4. Saves new state to Redis
        5. Removes restrictions if released

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            approved: Whether the message was approved (not spam).

        Returns:
            Updated SandboxState or None if not sandboxed.
        """
        state = await self.get_sandbox_state(user_id, chat_id)
        if state is None:
            return None

        if state.is_released:
            return state

        # Create new immutable state with updated counters
        new_state = state.with_message_recorded(approved)

        # Check release conditions
        should_release, reason = await self._check_release_conditions(new_state)
        if should_release and reason:
            new_state = new_state.with_released(reason)

            # Remove restrictions
            if state.status != SandboxStatus.SOFT_WATCH and self._restrictions:
                try:
                    await self._restrictions.remove_sandbox_restrictions(user_id, chat_id)
                except TelegramOperationError:
                    pass  # Log handled in adapter

            self._logger.info(
                "user_released_from_sandbox",
                user_id=user_id,
                chat_id=chat_id,
                reason=reason,
                messages_sent=new_state.messages_sent,
                approved_messages=new_state.approved_messages,
            )

        # Save updated state
        await self._save_sandbox_state(new_state)

        return new_state

    async def _check_release_conditions(self, state: SandboxState) -> tuple[bool, str | None]:
        """
        Check if user should be released from sandbox.

        Release conditions:
        1. Time expired with no violations
        2. N approved messages reached
        3. Channel subscriber (already handled at entry)
        4. Admin release (handled separately)

        Args:
            state: Current sandbox state.

        Returns:
            Tuple of (should_release, reason).
        """
        # Condition 1: Time expired with good behavior
        if state.is_expired() and state.violations == 0:
            return True, ReleaseReason.TIME_EXPIRED.value

        # Condition 2: Enough approved messages
        if state.approved_messages >= DEFAULT_APPROVED_MESSAGES_TO_RELEASE:
            # Check minimum time requirement
            min_time = state.entered_at + timedelta(hours=DEFAULT_MIN_HOURS_IN_SANDBOX)
            if datetime.now(UTC) >= min_time:
                return True, ReleaseReason.APPROVED_MESSAGES.value

        return False, None

    # =========================================================================
    # Sandbox Release
    # =========================================================================

    async def release_from_sandbox(
        self,
        user_id: int,
        chat_id: int,
        reason: str = "manual",
    ) -> bool:
        """
        Release user from sandbox.

        This method:
        1. Updates sandbox state to released
        2. Removes Telegram restrictions
        3. Updates trust level

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            reason: Reason for release (for audit log).

        Returns:
            True if released successfully.
        """
        state = await self.get_sandbox_state(user_id, chat_id)
        if state is None:
            self._logger.debug(
                "release_failed_not_sandboxed",
                user_id=user_id,
                chat_id=chat_id,
            )
            return False

        if state.is_released:
            self._logger.debug(
                "user_already_released",
                user_id=user_id,
                chat_id=chat_id,
            )
            return True

        # Create new released state
        new_state = state.with_released(reason)

        # Save state
        await self._save_sandbox_state(new_state)

        # Remove Telegram restrictions
        if self._restrictions:
            try:
                await self._restrictions.remove_sandbox_restrictions(user_id, chat_id)
            except TelegramOperationError:
                pass  # Fail silently, state is already saved

        self._logger.info(
            "user_released_from_sandbox",
            user_id=user_id,
            chat_id=chat_id,
            reason=reason,
        )

        return True

    # =========================================================================
    # Channel Subscription Check
    # =========================================================================

    async def check_channel_subscription_exit(
        self,
        user_id: int,
        chat_id: int,
        linked_channel_id: int,
    ) -> bool:
        """
        Check if user should exit sandbox due to channel subscription.

        This is the STRONGEST trust signal and provides immediate exit
        from sandbox if user is subscribed to the linked channel.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            linked_channel_id: Channel to check for subscription.

        Returns:
            True if user should exit sandbox (is subscribed).
        """
        if not self._channel_service:
            self._logger.debug(
                "channel_subscription_service_not_configured",
                user_id=user_id,
                chat_id=chat_id,
            )
            return False

        is_subscribed = await self._channel_service.is_subscribed(
            user_id=user_id, channel_id=linked_channel_id
        )

        if is_subscribed:
            # Release user from sandbox
            await self.release_from_sandbox(
                user_id=user_id,
                chat_id=chat_id,
                reason=ReleaseReason.CHANNEL_SUBSCRIBER.value,
            )
            self._logger.info(
                "sandbox_exit_channel_subscriber",
                user_id=user_id,
                chat_id=chat_id,
                channel_id=linked_channel_id,
            )
            return True

        return False

    # =========================================================================
    # Group Type Helpers
    # =========================================================================

    def get_sandbox_mode(self, group_type: GroupType) -> str:
        """
        Get sandbox mode for a group type.

        Args:
            group_type: Type of group.

        Returns:
            "soft_watch" for deals groups, "sandbox" otherwise.
        """
        if group_type == GroupType.DEALS:
            return "soft_watch"
        return "sandbox"

    def should_apply_restrictions(self, group_type: GroupType, sandbox_mode: str) -> bool:
        """
        Check if restrictions should be applied for a group type.

        Args:
            group_type: Type of group.
            sandbox_mode: Current sandbox mode.

        Returns:
            False for deals groups (soft watch), True otherwise.
        """
        # Deals groups NEVER restrict - only log
        if group_type == GroupType.DEALS:
            return False
        return sandbox_mode == "sandbox"


# =============================================================================
# Soft Watch Mode
# =============================================================================


class SoftWatchMode:
    """
    Soft Watch mode for deals groups.

    In deals groups, promotional content and links are NORMAL.
    We don't want to restrict legitimate deal posts.

    Instead of restricting users, we:
    - Track their messages more closely
    - Lower the threshold for LLM consultation
    - Flag suspicious patterns but don't auto-block
    - Alert admins for edge cases
    - Only delete messages for extreme cases (known spam DB match)

    Thread Safety:
        This class is thread-safe when used with asyncio.

    Example:
        >>> from saqshy.core.sandbox import SoftWatchMode
        >>> soft_watch = SoftWatchMode(cache_service=cache)
        >>>
        >>> verdict = await soft_watch.evaluate(
        ...     user_id=123,
        ...     chat_id=-100456,
        ...     risk_result=risk_result,
        ... )
        >>> print(f"Action: {verdict.action}, Reason: {verdict.reason}")
    """

    # Thresholds for soft watch mode (from module-level SOFT_WATCH_THRESHOLDS)
    THRESHOLD_CONSULT_LLM = SOFT_WATCH_THRESHOLDS["consult_llm"]
    THRESHOLD_FLAG_ADMIN = SOFT_WATCH_THRESHOLDS["flag_admin"]
    THRESHOLD_DELETE = SOFT_WATCH_THRESHOLDS["delete"]

    def __init__(
        self,
        cache: CacheProtocol,
        logger: LoggerProtocol | None = None,
    ) -> None:
        """
        Initialize soft watch mode.

        Args:
            cache: Cache service for state persistence.
            logger: Logger instance (optional).
        """
        self._cache = cache
        self._logger = logger or get_logger(__name__)

    def _soft_watch_key(self, chat_id: int, user_id: int) -> str:
        """Generate Redis key for soft watch state."""
        return f"{KEY_PREFIX_SOFT_WATCH}:{chat_id}:{user_id}"

    async def get_state(self, user_id: int, chat_id: int) -> SoftWatchState | None:
        """
        Get soft watch state from Redis.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            SoftWatchState or None if not found.
        """
        key = self._soft_watch_key(chat_id, user_id)
        data = await self._cache.get_json(key)

        if data is None:
            return None

        try:
            return SoftWatchState.from_dict(data)
        except (KeyError, ValueError) as e:
            self._logger.warning(
                "invalid_soft_watch_state",
                key=key,
                error=str(e),
            )
            return None

    async def _save_state(self, state: SoftWatchState) -> bool:
        """
        Save soft watch state to Redis.

        Args:
            state: SoftWatchState to save.

        Returns:
            True if saved successfully.
        """
        key = self._soft_watch_key(state.chat_id, state.user_id)
        return await self._cache.set_json(key, state.to_dict(), ttl=TTL_SOFT_WATCH)

    async def enter_soft_watch(
        self,
        user_id: int,
        chat_id: int,
        duration_hours: int = DEFAULT_SOFT_WATCH_DURATION_HOURS,
    ) -> SoftWatchState:
        """
        Put user in soft watch mode.

        Unlike regular sandbox, this does NOT apply restrictions.
        Only tracks behavior for monitoring.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            duration_hours: Duration in hours.

        Returns:
            SoftWatchState.
        """
        # Check if already in soft watch
        existing = await self.get_state(user_id, chat_id)
        if existing is not None and not existing.is_completed:
            return existing

        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=duration_hours)

        state = SoftWatchState(
            user_id=user_id,
            chat_id=chat_id,
            entered_at=now,
            expires_at=expires_at,
        )

        await self._save_state(state)

        self._logger.info(
            "user_entered_soft_watch",
            user_id=user_id,
            chat_id=chat_id,
            duration_hours=duration_hours,
        )

        return state

    async def record_message(
        self,
        user_id: int,
        chat_id: int,
        flagged: bool = False,
        spam_db_match: bool = False,
    ) -> SoftWatchState | None:
        """
        Record a message in soft watch mode.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            flagged: Whether the message was flagged as suspicious.
            spam_db_match: Whether message matched spam DB.

        Returns:
            Updated SoftWatchState or None if not in soft watch.
        """
        state = await self.get_state(user_id, chat_id)
        if state is None:
            return None

        # Create new immutable state with updated counters
        new_state = state.with_message_recorded(flagged=flagged, spam_db_match=spam_db_match)
        await self._save_state(new_state)

        return new_state

    async def evaluate(
        self,
        user_id: int,
        chat_id: int,
        risk_result: RiskResult,
    ) -> SoftWatchVerdict:
        """
        Evaluate message in soft watch mode.

        Unlike regular sandbox which blocks, soft watch:
        - Logs behavior
        - Consults LLM at lower threshold
        - Flags admins for edge cases
        - Only deletes for extreme spam DB matches

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            risk_result: Risk calculation result.

        Returns:
            SoftWatchVerdict with recommended action.
        """
        score = risk_result.score
        spam_db_similarity = risk_result.signals.network.spam_db_similarity

        # Record the message
        flagged = score >= self.THRESHOLD_CONSULT_LLM
        spam_db_match = spam_db_similarity >= 0.88
        await self.record_message(
            user_id=user_id,
            chat_id=chat_id,
            flagged=flagged,
            spam_db_match=spam_db_match,
        )

        # Route to appropriate verdict handler
        return self._determine_verdict(
            user_id=user_id,
            chat_id=chat_id,
            score=score,
            spam_db_similarity=spam_db_similarity,
        )

    def _determine_verdict(
        self,
        user_id: int,
        chat_id: int,
        score: float,
        spam_db_similarity: float,
    ) -> SoftWatchVerdict:
        """
        Route to appropriate verdict based on score and spam similarity.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            score: Risk score from analysis.
            spam_db_similarity: Spam database similarity score.

        Returns:
            SoftWatchVerdict with recommended action.
        """
        # Extreme case: High spam DB similarity = delete
        if spam_db_similarity >= 0.95:
            return self._extreme_spam_verdict(
                user_id=user_id,
                chat_id=chat_id,
                spam_db_similarity=spam_db_similarity,
            )

        # High score: Flag for admin review
        if score >= self.THRESHOLD_FLAG_ADMIN:
            return self._flag_admin_verdict(score=score)

        # Medium score: Consult LLM
        if score >= self.THRESHOLD_CONSULT_LLM:
            return self._consult_llm_verdict(score=score)

        # Low score: Allow
        return self._allow_verdict()

    def _extreme_spam_verdict(
        self,
        user_id: int,
        chat_id: int,
        spam_db_similarity: float,
    ) -> SoftWatchVerdict:
        """
        Handle extreme spam DB match (similarity >= 0.95).

        This is the only case where soft watch mode deletes messages.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            spam_db_similarity: Spam database similarity score.

        Returns:
            SoftWatchVerdict with delete action.
        """
        self._logger.warning(
            "soft_watch_extreme_spam",
            user_id=user_id,
            chat_id=chat_id,
            spam_db_similarity=spam_db_similarity,
        )
        return SoftWatchVerdict(
            action="delete",
            reason=f"Extreme spam DB match ({spam_db_similarity:.2%})",
            confidence=spam_db_similarity,
            should_delete=True,
            should_notify_admin=True,
        )

    def _flag_admin_verdict(self, score: float) -> SoftWatchVerdict:
        """
        Handle high risk score (>= THRESHOLD_FLAG_ADMIN).

        Flags message for admin review without deletion.

        Args:
            score: Risk score from analysis.

        Returns:
            SoftWatchVerdict with flag action.
        """
        return SoftWatchVerdict(
            action="flag",
            reason=f"High risk score ({score}) in soft watch mode",
            confidence=0.7,
            should_delete=False,
            should_notify_admin=True,
        )

    def _consult_llm_verdict(self, score: float) -> SoftWatchVerdict:
        """
        Handle medium risk score (>= THRESHOLD_CONSULT_LLM).

        Recommends LLM consultation for final decision.

        Args:
            score: Risk score from analysis.

        Returns:
            SoftWatchVerdict with consult_llm action.
        """
        return SoftWatchVerdict(
            action="consult_llm",
            reason=f"Medium risk score ({score}), needs LLM review",
            confidence=0.5,
            should_delete=False,
            should_notify_admin=False,
        )

    def _allow_verdict(self) -> SoftWatchVerdict:
        """
        Handle low risk score (normal activity).

        Allows message without any action.

        Returns:
            SoftWatchVerdict with allow action.
        """
        return SoftWatchVerdict(
            action="allow",
            reason="Normal activity in deals group",
            confidence=1.0,
            should_delete=False,
            should_notify_admin=False,
        )


# =============================================================================
# Trust Manager
# =============================================================================


class TrustManager:
    """
    Manages user trust levels within groups.

    Trust levels progress based on behavior:
    - UNTRUSTED: New users, in sandbox
    - PROVISIONAL: Passed sandbox, limited trust
    - TRUSTED: Several approved messages
    - ESTABLISHED: Long history, full trust

    Each level provides a risk score adjustment:
    - ESTABLISHED: -20 (significantly reduces risk)
    - TRUSTED: -10 (reduces risk)
    - PROVISIONAL: 0 (neutral)
    - UNTRUSTED: +5 (slightly increases risk)

    Thread Safety:
        This class is thread-safe when used with asyncio.

    Example:
        >>> from saqshy.core.sandbox import TrustManager
        >>> trust = TrustManager(cache=cache_service)
        >>>
        >>> level = await trust.get_trust_level(user_id=123, chat_id=-100456)
        >>> adjustment = trust.get_trust_score_adjustment(level)
        >>> print(f"Trust level: {level.value}, Adjustment: {adjustment}")
    """

    # Messages required for trust level progression
    MESSAGES_FOR_PROVISIONAL = 3  # After sandbox
    MESSAGES_FOR_TRUSTED = 10
    MESSAGES_FOR_ESTABLISHED = 50

    def __init__(
        self,
        cache: CacheProtocol,
        logger: LoggerProtocol | None = None,
    ) -> None:
        """
        Initialize trust manager.

        Args:
            cache: Cache service for state persistence.
            logger: Logger instance (optional).
        """
        self._cache = cache
        self._logger = logger or get_logger(__name__)

    def _trust_key(self, chat_id: int, user_id: int) -> str:
        """Generate Redis key for trust level."""
        return f"{KEY_PREFIX_TRUST}:{chat_id}:{user_id}"

    async def get_trust_level(self, user_id: int, chat_id: int) -> TrustLevel:
        """
        Get user's current trust level.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            Current TrustLevel (defaults to UNTRUSTED if not set).
        """
        key = self._trust_key(chat_id, user_id)
        value = await self._cache.get(key)

        if value is None:
            return TrustLevel.UNTRUSTED

        try:
            return TrustLevel(value)
        except ValueError:
            self._logger.warning(
                "invalid_trust_level",
                key=key,
                value=value,
            )
            return TrustLevel.UNTRUSTED

    async def set_trust_level(
        self,
        user_id: int,
        chat_id: int,
        level: TrustLevel,
    ) -> bool:
        """
        Set user's trust level.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            level: TrustLevel to set.

        Returns:
            True if saved successfully.
        """
        key = self._trust_key(chat_id, user_id)
        return await self._cache.set(key, level.value, ttl=TTL_TRUST_LEVEL)

    async def update_trust(
        self,
        user_id: int,
        chat_id: int,
        verdict: Verdict,
        approved_messages: int = 0,
    ) -> TrustLevel:
        """
        Update trust level based on verdict.

        Trust progression:
        - ALLOW/WATCH: Can progress if enough approved messages
        - LIMIT: May regress to UNTRUSTED
        - REVIEW/BLOCK: Regress to UNTRUSTED

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            verdict: Verdict from spam detection.
            approved_messages: Total approved messages (for progression).

        Returns:
            New TrustLevel after update.
        """
        current = await self.get_trust_level(user_id, chat_id)

        # Handle negative verdicts - regress trust
        if verdict in (Verdict.BLOCK, Verdict.REVIEW):
            new_level = TrustLevel.UNTRUSTED
            await self.set_trust_level(user_id, chat_id, new_level)
            self._logger.info(
                "trust_regressed",
                user_id=user_id,
                chat_id=chat_id,
                old_level=current.value,
                new_level=new_level.value,
                reason=verdict.value,
            )
            return new_level

        if verdict == Verdict.LIMIT:
            # Partial regression for LIMIT verdict
            if current in (TrustLevel.TRUSTED, TrustLevel.ESTABLISHED):
                new_level = TrustLevel.PROVISIONAL
                await self.set_trust_level(user_id, chat_id, new_level)
                self._logger.info(
                    "trust_partial_regression",
                    user_id=user_id,
                    chat_id=chat_id,
                    old_level=current.value,
                    new_level=new_level.value,
                )
                return new_level
            return current

        # Handle positive verdicts - potential progression
        if verdict in (Verdict.ALLOW, Verdict.WATCH):
            new_level = self._calculate_progression(current, approved_messages)
            if new_level != current:
                await self.set_trust_level(user_id, chat_id, new_level)
                self._logger.info(
                    "trust_progressed",
                    user_id=user_id,
                    chat_id=chat_id,
                    old_level=current.value,
                    new_level=new_level.value,
                    approved_messages=approved_messages,
                )
            return new_level

        return current

    def _calculate_progression(
        self,
        current: TrustLevel,
        approved_messages: int,
    ) -> TrustLevel:
        """
        Calculate trust level progression based on message count.

        Args:
            current: Current trust level.
            approved_messages: Total approved messages.

        Returns:
            New trust level (may be same as current).
        """
        if approved_messages >= self.MESSAGES_FOR_ESTABLISHED:
            return TrustLevel.ESTABLISHED
        elif approved_messages >= self.MESSAGES_FOR_TRUSTED:
            return max(current, TrustLevel.TRUSTED, key=self._level_order)
        elif approved_messages >= self.MESSAGES_FOR_PROVISIONAL:
            return max(current, TrustLevel.PROVISIONAL, key=self._level_order)
        return current

    def _level_order(self, level: TrustLevel) -> int:
        """Get numeric order for trust level comparison."""
        order = {
            TrustLevel.UNTRUSTED: 0,
            TrustLevel.PROVISIONAL: 1,
            TrustLevel.TRUSTED: 2,
            TrustLevel.ESTABLISHED: 3,
        }
        return order.get(level, 0)

    def get_trust_score_adjustment(self, level: TrustLevel) -> int:
        """
        Get risk score adjustment based on trust level.

        Higher trust levels reduce the risk score.

        Args:
            level: Current trust level.

        Returns:
            Score adjustment to add to risk score.
            Negative = reduces risk, Positive = increases risk.
        """
        return TRUST_SCORE_ADJUSTMENTS.get(level.value, 0)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Enums
    "SandboxStatus",
    "TrustLevel",
    "ReleaseReason",
    # Mixins
    "StateSerializationMixin",
    # Data classes
    "SandboxState",
    "SandboxConfig",
    "SoftWatchVerdict",
    "SoftWatchState",
    # Managers
    "SandboxManager",
    "SoftWatchMode",
    "TrustManager",
    # Constants
    "DEFAULT_SANDBOX_DURATION_HOURS",
    "DEFAULT_SOFT_WATCH_DURATION_HOURS",
    "DEFAULT_APPROVED_MESSAGES_TO_RELEASE",
    "TRUST_SCORE_ADJUSTMENTS",
    "SOFT_WATCH_THRESHOLDS",
]
