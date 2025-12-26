"""
SAQSHY Behavior Analyzer

Analyzes user behavior patterns for risk signals.

This module extracts behavior-based signals for the risk scoring system.
It uses dependency injection via Protocol classes to allow flexible
integration with different storage backends (Redis, PostgreSQL) and
external services (Telegram API).

Signal Categories:
    Time-based: TTFM, join-to-message timing, message frequency
    History: approved/flagged/blocked message counts
    Channel subscription: strongest trust signal (-25 points)
    Interaction: replies, reply-to-admin, mentions

Implementation Notes:
    - All external dependencies are injected via Protocols
    - Graceful degradation when providers are unavailable
    - All operations are async for consistency
    - Designed for O(1) Redis operations on hot path
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

import structlog

from saqshy.core.types import BehaviorSignals, MessageContext

logger = structlog.get_logger(__name__)


# =============================================================================
# Protocol Definitions
# =============================================================================


@runtime_checkable
class MessageHistoryProvider(Protocol):
    """
    Protocol for message history storage.

    Implementations should use Redis for hot data (recent messages, timestamps)
    and PostgreSQL for permanent history (approved/flagged/blocked counts).

    Redis Key Schema (recommended):
        approved_msgs:{chat_id}:{user_id}     TTL: 30d   # Approved message count
        ttfm:{chat_id}:{user_id}              TTL: 7d    # First message timestamp
        join:{chat_id}:{user_id}              TTL: 7d    # Join timestamp
        msg_count_hour:{chat_id}:{user_id}    TTL: 1h    # Messages in last hour
        msg_count_day:{chat_id}:{user_id}     TTL: 24h   # Messages in last 24h

    All methods should be O(1) or use bounded time windows.
    """

    async def get_user_message_count(self, user_id: int, chat_id: int, window_seconds: int) -> int:
        """
        Get count of user messages in the specified time window.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            window_seconds: Time window in seconds (e.g., 3600 for 1 hour).

        Returns:
            Number of messages in the time window.
        """
        ...

    async def get_user_stats(self, user_id: int, chat_id: int) -> dict[str, int]:
        """
        Get user's message statistics in the group.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            Dict with keys:
                - "total_messages": Total message count
                - "approved": Count of approved messages
                - "flagged": Count of flagged messages
                - "blocked": Count of blocked messages
        """
        ...

    async def get_first_message_time(self, user_id: int, chat_id: int) -> datetime | None:
        """
        Get timestamp of user's first message in the group.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            Datetime of first message, or None if no messages recorded.
        """
        ...

    async def get_join_time(self, user_id: int, chat_id: int) -> datetime | None:
        """
        Get timestamp when user joined the group.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            Datetime of join event, or None if not recorded.
        """
        ...


@runtime_checkable
class ChannelSubscriptionChecker(Protocol):
    """
    Protocol for checking channel subscription.

    Implementations should cache results in Redis to avoid Telegram API rate limits.
    Recommended cache TTL: 1 hour.

    Redis Key Schema (recommended):
        channel_sub:{channel_id}:{user_id}        TTL: 1h   # "1" or "0"
        channel_sub_since:{channel_id}:{user_id}  TTL: 1h   # Join timestamp (if available)
    """

    async def is_subscribed(self, user_id: int, channel_id: int) -> bool:
        """
        Check if user is subscribed to the channel.

        Should check cache first, then call Telegram API if not cached.
        Valid subscription statuses: member, administrator, creator.

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.

        Returns:
            True if user is subscribed to the channel.
        """
        ...

    async def get_subscription_duration_days(self, user_id: int, channel_id: int) -> int:
        """
        Get how long user has been subscribed to the channel.

        Note: Telegram API doesn't always provide this information.
        Return 0 if duration is unknown but user is subscribed.

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.

        Returns:
            Subscription duration in days, or 0 if unknown.
        """
        ...


# =============================================================================
# Constants
# =============================================================================

# Time windows for message counting (in seconds)
WINDOW_HOUR = 3600
WINDOW_24H = 86400

# Mention pattern for counting @mentions in text
MENTION_PATTERN = re.compile(r"@[a-zA-Z][a-zA-Z0-9_]{4,31}")


# =============================================================================
# Internal Data Classes
# =============================================================================


@dataclass
class _HistorySignalsData:
    """
    Internal dataclass to hold intermediate history signal values.

    Used to pass mutable signal data between extraction sub-methods,
    avoiding large tuple returns and making the code more maintainable.
    """

    time_to_first_message_seconds: int | None = None
    join_to_message_seconds: int | None = None
    messages_in_last_hour: int = 0
    messages_in_last_24h: int = 0
    previous_messages_approved: int = 0
    previous_messages_flagged: int = 0
    previous_messages_blocked: int = 0
    is_first_message: bool = True
    join_time: datetime | None = field(default=None, repr=False)

    def to_tuple(
        self,
    ) -> tuple[int | None, int | None, int, int, int, int, int, bool]:
        """Convert to tuple for backward compatibility with existing return type."""
        return (
            self.time_to_first_message_seconds,
            self.join_to_message_seconds,
            self.messages_in_last_hour,
            self.messages_in_last_24h,
            self.previous_messages_approved,
            self.previous_messages_flagged,
            self.previous_messages_blocked,
            self.is_first_message,
        )


# =============================================================================
# BehaviorAnalyzer
# =============================================================================


class BehaviorAnalyzer:
    """
    Analyzes user behavior patterns for risk signals.

    This analyzer extracts behavior-based signals that are critical for
    spam detection. The strongest trust signal is channel subscription
    (-25 points), and the strongest risk signals are related to
    message timing and history.

    Dependency Injection:
        Both providers are optional. If not provided, the analyzer will
        return default values for the corresponding signals and log warnings.
        This allows graceful degradation in case of service failures.

    Thread Safety:
        This class is stateless and thread-safe when providers are thread-safe.

    Performance:
        All operations are designed to be fast (<50ms) when providers
        use Redis with O(1) operations.

    Example:
        >>> from saqshy.analyzers.behavior import BehaviorAnalyzer
        >>> analyzer = BehaviorAnalyzer(
        ...     history_provider=redis_history,
        ...     subscription_checker=subscription_service,
        ... )
        >>> signals = await analyzer.analyze(
        ...     context=message_context,
        ...     linked_channel_id=channel_id,
        ...     admin_ids={admin1_id, admin2_id},
        ... )
        >>> print(signals.is_channel_subscriber, signals.previous_messages_approved)
    """

    def __init__(
        self,
        history_provider: MessageHistoryProvider | None = None,
        subscription_checker: ChannelSubscriptionChecker | None = None,
    ) -> None:
        """
        Initialize BehaviorAnalyzer with optional dependency providers.

        Args:
            history_provider: Provider for message history data.
                If None, history-related signals will have default values.
            subscription_checker: Checker for channel subscription status.
                If None, subscription signals will have default values.
        """
        self._history_provider = history_provider
        self._subscription_checker = subscription_checker

    async def analyze(
        self,
        context: MessageContext,
        linked_channel_id: int | None = None,
        admin_ids: set[int] | None = None,
    ) -> BehaviorSignals:
        """
        Analyze user behavior and extract signals.

        This is the main entry point for behavior analysis. It extracts all
        signals defined in BehaviorSignals dataclass and returns them.

        Args:
            context: MessageContext containing message and user data.
            linked_channel_id: ID of the group's linked channel (if any).
                Used for channel subscription checking.
            admin_ids: Set of admin user IDs in the group.
                Used for is_reply_to_admin detection.

        Returns:
            BehaviorSignals with all extracted signals populated.

        Note:
            If providers are unavailable or calls fail, corresponding signals
            will have default values (False, 0, None) rather than raising.
        """
        user_id = context.user_id
        chat_id = context.chat_id
        message_timestamp = context.timestamp

        # Extract time-based and history signals
        (
            time_to_first_message_seconds,
            join_to_message_seconds,
            messages_in_last_hour,
            messages_in_last_24h,
            previous_messages_approved,
            previous_messages_flagged,
            previous_messages_blocked,
            is_first_message,
        ) = await self._extract_history_signals(user_id, chat_id, message_timestamp)

        # Extract channel subscription signals
        (
            is_channel_subscriber,
            channel_subscription_duration_days,
        ) = await self._extract_subscription_signals(user_id, linked_channel_id)

        # Extract interaction signals (from MessageContext, no external calls)
        is_reply = self._check_is_reply(context)
        is_reply_to_admin = self._check_is_reply_to_admin(context, admin_ids)
        mentioned_users_count = self._count_mentions(context.text)

        return BehaviorSignals(
            time_to_first_message_seconds=time_to_first_message_seconds,
            messages_in_last_hour=messages_in_last_hour,
            messages_in_last_24h=messages_in_last_24h,
            join_to_message_seconds=join_to_message_seconds,
            previous_messages_approved=previous_messages_approved,
            previous_messages_flagged=previous_messages_flagged,
            previous_messages_blocked=previous_messages_blocked,
            is_first_message=is_first_message,
            is_channel_subscriber=is_channel_subscriber,
            channel_subscription_duration_days=channel_subscription_duration_days,
            is_reply=is_reply,
            is_reply_to_admin=is_reply_to_admin,
            mentioned_users_count=mentioned_users_count,
        )

    async def _extract_history_signals(
        self,
        user_id: int,
        chat_id: int,
        message_timestamp: datetime,
    ) -> tuple[int | None, int | None, int, int, int, int, int, bool]:
        """
        Extract time-based and history signals using history provider.

        This method orchestrates extraction of all history-related signals by
        delegating to focused sub-methods. Each sub-method handles its own
        error recovery and logs failures independently.

        Returns:
            Tuple of:
                - time_to_first_message_seconds
                - join_to_message_seconds
                - messages_in_last_hour
                - messages_in_last_24h
                - previous_messages_approved
                - previous_messages_flagged
                - previous_messages_blocked
                - is_first_message
        """
        signals = _HistorySignalsData()

        if self._history_provider is None:
            logger.debug(
                "history_provider_not_configured",
                user_id=user_id,
                chat_id=chat_id,
            )
            return signals.to_tuple()

        # Extract individual signal types
        await self._extract_user_stats_signals(user_id, chat_id, signals)
        await self._extract_message_count_signals(user_id, chat_id, signals)
        await self._extract_join_time_signal(user_id, chat_id, message_timestamp, signals)
        await self._extract_ttfm_signal(user_id, chat_id, signals)

        return signals.to_tuple()

    async def _extract_user_stats_signals(
        self,
        user_id: int,
        chat_id: int,
        signals: _HistorySignalsData,
    ) -> None:
        """
        Extract user statistics signals (approved, flagged, blocked counts).

        Updates signals in place with:
            - previous_messages_approved
            - previous_messages_flagged
            - previous_messages_blocked
            - is_first_message

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            signals: Mutable signals data object to update.

        Note:
            Caller must ensure _history_provider is not None before calling.
        """
        assert self._history_provider is not None  # Guaranteed by caller
        try:
            stats = await self._history_provider.get_user_stats(user_id, chat_id)
            total_messages = stats.get("total_messages", 0)
            signals.previous_messages_approved = stats.get("approved", 0)
            signals.previous_messages_flagged = stats.get("flagged", 0)
            signals.previous_messages_blocked = stats.get("blocked", 0)
            signals.is_first_message = total_messages == 0
        except Exception as e:
            logger.warning(
                "failed_to_get_user_stats",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )

    async def _extract_message_count_signals(
        self,
        user_id: int,
        chat_id: int,
        signals: _HistorySignalsData,
    ) -> None:
        """
        Extract message count signals for time windows.

        Updates signals in place with:
            - messages_in_last_hour
            - messages_in_last_24h

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            signals: Mutable signals data object to update.

        Note:
            Caller must ensure _history_provider is not None before calling.
        """
        assert self._history_provider is not None  # Guaranteed by caller
        try:
            signals.messages_in_last_hour = await self._history_provider.get_user_message_count(
                user_id, chat_id, WINDOW_HOUR
            )
            signals.messages_in_last_24h = await self._history_provider.get_user_message_count(
                user_id, chat_id, WINDOW_24H
            )
        except Exception as e:
            logger.warning(
                "failed_to_get_message_counts",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )

    async def _extract_join_time_signal(
        self,
        user_id: int,
        chat_id: int,
        message_timestamp: datetime,
        signals: _HistorySignalsData,
    ) -> None:
        """
        Extract join-to-message time signal.

        Updates signals in place with:
            - join_to_message_seconds
            - join_time (stored for TTFM calculation)

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            message_timestamp: Current message timestamp.
            signals: Mutable signals data object to update.

        Note:
            Caller must ensure _history_provider is not None before calling.
        """
        assert self._history_provider is not None  # Guaranteed by caller
        try:
            join_time = await self._history_provider.get_join_time(user_id, chat_id)
            if join_time is not None:
                msg_ts = self._ensure_utc(message_timestamp)
                join_ts = self._ensure_utc(join_time)
                signals.join_to_message_seconds = max(0, int((msg_ts - join_ts).total_seconds()))
                signals.join_time = join_time
        except Exception as e:
            logger.warning(
                "failed_to_get_join_time",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )

    async def _extract_ttfm_signal(
        self,
        user_id: int,
        chat_id: int,
        signals: _HistorySignalsData,
    ) -> None:
        """
        Extract time-to-first-message (TTFM) signal.

        TTFM is calculated differently based on whether this is the user's
        first message or not:
            - First message: TTFM equals join_to_message_seconds
            - Not first: Calculate from stored first message time

        Updates signals in place with:
            - time_to_first_message_seconds

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            signals: Mutable signals data object to update.

        Note:
            Caller must ensure _history_provider is not None before calling.
        """
        assert self._history_provider is not None  # Guaranteed by caller
        try:
            if signals.is_first_message and signals.join_to_message_seconds is not None:
                # First message: TTFM equals join_to_message
                signals.time_to_first_message_seconds = signals.join_to_message_seconds
            elif not signals.is_first_message:
                # Not first message: get actual first message time
                first_msg_time = await self._history_provider.get_first_message_time(
                    user_id, chat_id
                )
                if first_msg_time is not None and signals.join_time is not None:
                    first_ts = self._ensure_utc(first_msg_time)
                    join_ts = self._ensure_utc(signals.join_time)
                    signals.time_to_first_message_seconds = max(
                        0, int((first_ts - join_ts).total_seconds())
                    )
        except Exception as e:
            logger.warning(
                "failed_to_calculate_ttfm",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )

    async def _extract_subscription_signals(
        self,
        user_id: int,
        linked_channel_id: int | None,
    ) -> tuple[bool, int]:
        """
        Extract channel subscription signals using subscription checker.

        Returns:
            Tuple of (is_channel_subscriber, channel_subscription_duration_days).
        """
        is_channel_subscriber = False
        channel_subscription_duration_days = 0

        if linked_channel_id is None:
            # No linked channel, skip subscription check
            return is_channel_subscriber, channel_subscription_duration_days

        if self._subscription_checker is None:
            logger.debug(
                "subscription_checker_not_configured",
                user_id=user_id,
                channel_id=linked_channel_id,
            )
            return is_channel_subscriber, channel_subscription_duration_days

        try:
            is_channel_subscriber = await self._subscription_checker.is_subscribed(
                user_id, linked_channel_id
            )

            if is_channel_subscriber:
                channel_subscription_duration_days = (
                    await self._subscription_checker.get_subscription_duration_days(
                        user_id, linked_channel_id
                    )
                )

        except Exception as e:
            logger.warning(
                "failed_to_check_subscription",
                user_id=user_id,
                channel_id=linked_channel_id,
                error=str(e),
            )

        return is_channel_subscriber, channel_subscription_duration_days

    def _check_is_reply(self, context: MessageContext) -> bool:
        """
        Check if message is a reply to another message.

        Args:
            context: MessageContext with reply metadata.

        Returns:
            True if message is a reply.
        """
        return context.reply_to_message_id is not None

    def _check_is_reply_to_admin(
        self,
        context: MessageContext,
        admin_ids: set[int] | None,
    ) -> bool:
        """
        Check if message is a reply to an admin.

        Args:
            context: MessageContext with reply and raw_message data.
            admin_ids: Set of admin user IDs.

        Returns:
            True if message is a reply to an admin.
        """
        if not self._check_is_reply(context):
            return False

        if admin_ids is None or len(admin_ids) == 0:
            return False

        # Try to get replied-to user ID from raw_message
        raw_msg = context.raw_message or {}
        reply_to_message = raw_msg.get("reply_to_message", {})

        if not reply_to_message:
            return False

        replied_to_user = reply_to_message.get("from", {})
        replied_to_user_id = replied_to_user.get("id")

        if replied_to_user_id is None:
            return False

        return replied_to_user_id in admin_ids

    def _count_mentions(self, text: str | None) -> int:
        """
        Count @ mentions in message text.

        Counts valid Telegram username mentions (5-32 chars after @).

        Args:
            text: Message text.

        Returns:
            Number of @mentions found.
        """
        if not text:
            return 0

        matches = MENTION_PATTERN.findall(text)
        return len(matches)

    def _ensure_utc(self, dt: datetime) -> datetime:
        """
        Ensure datetime is timezone-aware (UTC).

        Args:
            dt: Datetime object (may or may not be timezone-aware).

        Returns:
            Timezone-aware datetime in UTC.
        """
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt


# =============================================================================
# FloodDetector
# =============================================================================


class FloodDetector:
    """
    Detects message flooding behavior.

    Uses sliding window rate limiting to detect users sending
    too many messages too quickly. Designed for Redis sorted sets.

    Redis Implementation:
        Key: flood:{chat_id}:{user_id}
        Members: message timestamps (Unix seconds)
        Operations:
            - ZADD: Add new message timestamp
            - ZREMRANGEBYSCORE: Remove old entries
            - ZCARD: Count entries in window

    Example:
        >>> detector = FloodDetector(window_seconds=60, max_messages=10)
        >>> is_flooding = await detector.check_flood(user_id, chat_id)
        >>> if not is_flooding:
        ...     await detector.record_message(user_id, chat_id)
    """

    def __init__(
        self,
        window_seconds: int = 60,
        max_messages: int = 10,
        history_provider: MessageHistoryProvider | None = None,
    ) -> None:
        """
        Initialize flood detector.

        Args:
            window_seconds: Time window in seconds.
            max_messages: Max messages allowed in window.
            history_provider: Provider for message history (for counting).
        """
        self.window_seconds = window_seconds
        self.max_messages = max_messages
        self._history_provider = history_provider

    async def check_flood(self, user_id: int, chat_id: int) -> bool:
        """
        Check if user is flooding.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            True if user is flooding (exceeded max_messages in window).
        """
        if self._history_provider is None:
            return False

        try:
            count = await self._history_provider.get_user_message_count(
                user_id, chat_id, self.window_seconds
            )
            return count >= self.max_messages

        except Exception as e:
            logger.warning(
                "flood_check_failed",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )
            return False

    async def record_message(self, user_id: int, chat_id: int) -> None:
        """
        Record a message for flood detection.

        Note: This is a placeholder. Actual recording should be done
        by the history provider implementation using Redis ZADD.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
        """
        # Recording is handled by the history provider
        # This method exists for interface compatibility
        pass
