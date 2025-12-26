"""
SAQSHY Channel Subscription Service

Checks if users are subscribed to the group's linked channel.

This module implements the ChannelSubscriptionChecker protocol from
saqshy.analyzers.behavior, providing Telegram API integration for
checking channel membership status.

Channel subscription is the STRONGEST trust signal (-25 points).

Implementation Notes:
    - Uses aiogram Bot.get_chat_member() for subscription checks
    - Caches results in Redis for 1 hour to reduce API calls
    - Handles all Telegram API errors gracefully (returns False on error)
    - Implements rate limiting to avoid FloodWait errors
    - Never crashes - all errors are caught and logged

Rate Limiting:
    - Telegram API limit: ~30 requests/second
    - Uses asyncio.Semaphore to limit concurrent requests
    - Tracks request timestamps for rate limiting

Cache Strategy:
    - Cache key: saqshy:channel_sub:{channel_id}:{user_id}
    - TTL: 1 hour for positive results, 5 minutes for errors
    - Subscription duration tracked separately with first-seen timestamp
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import redis.asyncio
import structlog
from aiogram.exceptions import TelegramAPIError

if TYPE_CHECKING:
    from aiogram import Bot

    from saqshy.services.cache import CacheService

logger = structlog.get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Cache configuration
CACHE_KEY_PREFIX = "saqshy:channel_sub"
CACHE_TTL_SECONDS = 3600  # 1 hour for successful checks
CACHE_TTL_ERROR_SECONDS = 300  # 5 minutes for error results
CACHE_TTL_FIRST_SEEN = 86400 * 30  # 30 days for first-seen tracking

# Rate limiting configuration
MAX_CONCURRENT_REQUESTS = 10  # Maximum concurrent API requests
RATE_LIMIT_REQUESTS = 25  # Maximum requests per window
RATE_LIMIT_WINDOW_SECONDS = 1.0  # Window size in seconds

# Subscription statuses that indicate membership
SUBSCRIBED_STATUSES = frozenset({"creator", "administrator", "member"})

# Non-subscribed statuses
NOT_SUBSCRIBED_STATUSES = frozenset({"left", "kicked", "restricted"})


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class SubscriptionStatus:
    """
    Detailed subscription status for a user in a channel.

    Attributes:
        is_subscribed: Whether the user is subscribed to the channel.
        status: Raw status string from Telegram API.
            Values: "creator", "administrator", "member", "left", "kicked", "restricted"
        duration_days: How long the user has been subscribed (0 if unknown).
        cached: Whether this result came from cache.
        error: Error message if the check failed, None otherwise.
    """

    is_subscribed: bool
    status: str
    duration_days: int = 0
    cached: bool = False
    error: str | None = None


@dataclass
class RateLimiter:
    """
    Simple sliding window rate limiter.

    Tracks request timestamps and enforces rate limits.
    """

    max_requests: int = RATE_LIMIT_REQUESTS
    window_seconds: float = RATE_LIMIT_WINDOW_SECONDS
    _timestamps: list[float] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def acquire(self) -> None:
        """
        Acquire permission to make a request.

        Blocks if rate limit is exceeded until a slot becomes available.
        """
        async with self._lock:
            now = time.monotonic()

            # Remove expired timestamps
            cutoff = now - self.window_seconds
            self._timestamps = [ts for ts in self._timestamps if ts > cutoff]

            # Wait if at limit
            if len(self._timestamps) >= self.max_requests:
                oldest = self._timestamps[0]
                wait_time = oldest + self.window_seconds - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    # Clean up again after waiting
                    now = time.monotonic()
                    cutoff = now - self.window_seconds
                    self._timestamps = [ts for ts in self._timestamps if ts > cutoff]

            # Record this request
            self._timestamps.append(now)


# =============================================================================
# ChannelSubscriptionService
# =============================================================================


class ChannelSubscriptionService:
    """
    Checks Telegram channel subscriptions.

    Channel subscription is the STRONGEST trust signal (-25 weight).
    This service verifies if users are subscribed to the group's
    linked channel.

    Implements the ChannelSubscriptionChecker protocol from
    saqshy.analyzers.behavior.

    Thread Safety:
        This class is thread-safe when used with asyncio.
        Uses asyncio.Semaphore and Lock for concurrency control.

    Error Handling:
        All Telegram API errors are caught and logged.
        Returns False (not subscribed) on any error.
        This is a conservative approach - better to miss a trust bonus
        than to incorrectly apply it.

    Example:
        >>> from aiogram import Bot
        >>> from saqshy.services.channel_subscription import ChannelSubscriptionService
        >>> from saqshy.services.cache import CacheService
        >>>
        >>> bot = Bot(token="...")
        >>> cache = CacheService(redis_url="redis://localhost:6379")
        >>> service = ChannelSubscriptionService(bot=bot, cache=cache)
        >>>
        >>> # Check subscription
        >>> is_subscribed = await service.is_subscribed(user_id=123, channel_id=-100123456)
        >>> print(f"User is subscribed: {is_subscribed}")
        >>>
        >>> # Get detailed status
        >>> status = await service.check_subscription_with_details(
        ...     user_id=123,
        ...     channel_id=-100123456
        ... )
        >>> print(f"Status: {status.status}, Duration: {status.duration_days} days")
    """

    def __init__(
        self,
        bot: Bot,
        cache: CacheService | None = None,
        cache_ttl: int = CACHE_TTL_SECONDS,
        max_concurrent_requests: int = MAX_CONCURRENT_REQUESTS,
    ) -> None:
        """
        Initialize subscription service.

        Args:
            bot: aiogram Bot instance for API calls.
            cache: Optional cache service for storing subscription status.
                If None, no caching is performed.
            cache_ttl: TTL for cached subscription status in seconds.
                Defaults to 3600 (1 hour).
            max_concurrent_requests: Maximum concurrent Telegram API requests.
                Defaults to 10.
        """
        self._bot = bot
        self._cache = cache
        self._cache_ttl = cache_ttl
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)
        self._rate_limiter = RateLimiter()

    # =========================================================================
    # Protocol Methods (ChannelSubscriptionChecker)
    # =========================================================================

    async def is_subscribed(self, user_id: int, channel_id: int) -> bool:
        """
        Check if user is subscribed to channel.

        This method implements the ChannelSubscriptionChecker protocol.

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID (can be negative for channels).

        Returns:
            True if user is subscribed (member, administrator, or creator).
            False otherwise or on any error.
        """
        status = await self.check_subscription_with_details(user_id, channel_id)
        return status.is_subscribed

    async def get_subscription_duration_days(
        self,
        user_id: int,
        channel_id: int,
    ) -> int:
        """
        Get subscription duration in days.

        This method implements the ChannelSubscriptionChecker protocol.

        Note: Telegram doesn't provide subscription date directly.
        We track the first time we see a user as subscribed and
        calculate duration from that date.

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.

        Returns:
            Subscription duration in days.
            Returns 0 if:
                - User is not subscribed
                - Duration is unknown (first time checking)
                - Any error occurs
        """
        status = await self.check_subscription_with_details(user_id, channel_id)
        return status.duration_days

    # =========================================================================
    # Main API
    # =========================================================================

    async def check_subscription_with_details(
        self,
        user_id: int,
        channel_id: int,
    ) -> SubscriptionStatus:
        """
        Get detailed subscription status.

        This is the main method that performs the actual check.
        Other methods delegate to this one.

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.

        Returns:
            SubscriptionStatus with detailed information.
        """
        # Try cache first
        cached_status = await self._get_from_cache(user_id, channel_id)
        if cached_status is not None:
            return cached_status

        # Rate limit and concurrency control
        async with self._semaphore:
            await self._rate_limiter.acquire()

            # Call Telegram API
            status = await self._check_via_api(user_id, channel_id)

        # Cache the result
        await self._save_to_cache(user_id, channel_id, status)

        return status

    # =========================================================================
    # Cache Operations
    # =========================================================================

    def _get_cache_key(self, user_id: int, channel_id: int) -> str:
        """Generate cache key for subscription status."""
        return f"{CACHE_KEY_PREFIX}:{channel_id}:{user_id}"

    def _get_first_seen_key(self, user_id: int, channel_id: int) -> str:
        """Generate cache key for first-seen timestamp."""
        return f"{CACHE_KEY_PREFIX}:first_seen:{channel_id}:{user_id}"

    async def _get_from_cache(
        self,
        user_id: int,
        channel_id: int,
    ) -> SubscriptionStatus | None:
        """
        Get subscription status from cache.

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.

        Returns:
            Cached SubscriptionStatus or None if not cached.
        """
        if self._cache is None:
            return None

        try:
            cache_key = self._get_cache_key(user_id, channel_id)
            cached_value = await self._cache.get(cache_key)

            if cached_value is None:
                return None

            # Parse cached value: "status:is_subscribed"
            # e.g., "member:1" or "left:0"
            parts = cached_value.split(":")
            if len(parts) != 2:
                logger.warning(
                    "invalid_cache_format",
                    cache_key=cache_key,
                    value=cached_value,
                )
                return None

            status_str, subscribed_str = parts
            is_subscribed = subscribed_str == "1"

            # Get duration if subscribed
            duration_days = 0
            if is_subscribed:
                duration_days = await self._get_subscription_duration(user_id, channel_id)

            logger.debug(
                "cache_hit",
                user_id=user_id,
                channel_id=channel_id,
                is_subscribed=is_subscribed,
                status=status_str,
            )

            return SubscriptionStatus(
                is_subscribed=is_subscribed,
                status=status_str,
                duration_days=duration_days,
                cached=True,
            )

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            logger.warning(
                "cache_get_error",
                user_id=user_id,
                channel_id=channel_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    async def _save_to_cache(
        self,
        user_id: int,
        channel_id: int,
        status: SubscriptionStatus,
    ) -> None:
        """
        Save subscription status to cache.

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.
            status: Subscription status to cache.
        """
        if self._cache is None:
            return

        try:
            cache_key = self._get_cache_key(user_id, channel_id)

            # Format: "status:is_subscribed"
            subscribed_str = "1" if status.is_subscribed else "0"
            cache_value = f"{status.status}:{subscribed_str}"

            # Use shorter TTL for error results
            ttl = self._cache_ttl
            if status.error is not None:
                ttl = CACHE_TTL_ERROR_SECONDS

            await self._cache.set(cache_key, cache_value, ttl=ttl)

            # Track first-seen timestamp for duration calculation
            if status.is_subscribed:
                await self._record_first_seen(user_id, channel_id)

            logger.debug(
                "cache_set",
                user_id=user_id,
                channel_id=channel_id,
                is_subscribed=status.is_subscribed,
                status=status.status,
                ttl=ttl,
            )

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            logger.warning(
                "cache_set_error",
                user_id=user_id,
                channel_id=channel_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    async def _record_first_seen(
        self,
        user_id: int,
        channel_id: int,
    ) -> None:
        """
        Record first-seen timestamp for subscription duration tracking.

        Only records if not already present (first time seeing subscription).

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.
        """
        if self._cache is None:
            return

        try:
            first_seen_key = self._get_first_seen_key(user_id, channel_id)

            # Check if already recorded
            existing = await self._cache.get(first_seen_key)
            if existing is not None:
                return  # Already recorded

            # Record current timestamp
            timestamp = int(time.time())
            await self._cache.set(
                first_seen_key,
                str(timestamp),
                ttl=CACHE_TTL_FIRST_SEEN,
            )

            logger.debug(
                "first_seen_recorded",
                user_id=user_id,
                channel_id=channel_id,
                timestamp=timestamp,
            )

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            logger.warning(
                "first_seen_record_error",
                user_id=user_id,
                channel_id=channel_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    async def _get_subscription_duration(
        self,
        user_id: int,
        channel_id: int,
    ) -> int:
        """
        Calculate subscription duration in days from first-seen timestamp.

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.

        Returns:
            Duration in days, or 0 if unknown.
        """
        if self._cache is None:
            return 0

        try:
            first_seen_key = self._get_first_seen_key(user_id, channel_id)
            first_seen_str = await self._cache.get(first_seen_key)

            if first_seen_str is None:
                return 0

            first_seen = int(first_seen_str)
            now = int(time.time())
            duration_seconds = now - first_seen
            duration_days = duration_seconds // 86400

            return max(0, duration_days)

        except (ValueError, TypeError) as e:
            logger.warning(
                "duration_calculation_error",
                user_id=user_id,
                channel_id=channel_id,
                error=str(e),
            )
            return 0

    # =========================================================================
    # Telegram API Operations
    # =========================================================================

    async def _check_via_api(
        self,
        user_id: int,
        channel_id: int,
    ) -> SubscriptionStatus:
        """
        Check subscription via Telegram API.

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.

        Returns:
            SubscriptionStatus from API response.
        """
        try:
            member = await self._bot.get_chat_member(
                chat_id=channel_id,
                user_id=user_id,
            )

            status = member.status
            is_subscribed = status in SUBSCRIBED_STATUSES

            # Calculate duration if subscribed
            duration_days = 0
            if is_subscribed:
                duration_days = await self._get_subscription_duration(user_id, channel_id)

            logger.debug(
                "api_check_success",
                user_id=user_id,
                channel_id=channel_id,
                status=status,
                is_subscribed=is_subscribed,
            )

            return SubscriptionStatus(
                is_subscribed=is_subscribed,
                status=status,
                duration_days=duration_days,
                cached=False,
            )

        except TelegramAPIError as e:
            return await self._handle_api_error(e, user_id, channel_id)

    async def _handle_api_error(
        self,
        error: Exception,
        user_id: int,
        channel_id: int,
    ) -> SubscriptionStatus:
        """
        Handle Telegram API errors gracefully.

        All errors result in returning False (not subscribed).
        This is the conservative approach.

        Args:
            error: The exception that occurred.
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.

        Returns:
            SubscriptionStatus with is_subscribed=False.
        """
        error_str = str(error)
        error_type = type(error).__name__

        # Categorize errors for logging
        if "chat not found" in error_str.lower():
            # Channel doesn't exist or bot was removed
            logger.warning(
                "channel_not_found",
                user_id=user_id,
                channel_id=channel_id,
                error=error_str,
            )
            return SubscriptionStatus(
                is_subscribed=False,
                status="unknown",
                error="Channel not found",
            )

        elif "user not found" in error_str.lower():
            # User doesn't exist (rare)
            logger.warning(
                "user_not_found",
                user_id=user_id,
                channel_id=channel_id,
                error=error_str,
            )
            return SubscriptionStatus(
                is_subscribed=False,
                status="unknown",
                error="User not found",
            )

        elif "forbidden" in error_str.lower() or "kicked" in error_str.lower():
            # Bot was kicked from channel or lacks permissions
            # This could also mean user has privacy settings enabled
            logger.warning(
                "access_forbidden",
                user_id=user_id,
                channel_id=channel_id,
                error=error_str,
            )
            return SubscriptionStatus(
                is_subscribed=False,
                status="unknown",
                error="Access forbidden - bot may not be admin in channel",
            )

        elif "flood" in error_str.lower():
            # Rate limited by Telegram
            logger.error(
                "rate_limited",
                user_id=user_id,
                channel_id=channel_id,
                error=error_str,
            )
            return SubscriptionStatus(
                is_subscribed=False,
                status="unknown",
                error="Rate limited by Telegram",
            )

        elif "privacy" in error_str.lower():
            # User has strict privacy settings
            logger.debug(
                "user_privacy_restricted",
                user_id=user_id,
                channel_id=channel_id,
                error=error_str,
            )
            return SubscriptionStatus(
                is_subscribed=False,
                status="unknown",
                error="User privacy settings prevent checking",
            )

        else:
            # Unknown error
            logger.error(
                "api_error",
                user_id=user_id,
                channel_id=channel_id,
                error_type=error_type,
                error=error_str,
            )
            return SubscriptionStatus(
                is_subscribed=False,
                status="unknown",
                error=f"API error: {error_type}",
            )

    # =========================================================================
    # Utility Methods
    # =========================================================================

    async def invalidate_cache(
        self,
        user_id: int,
        channel_id: int,
    ) -> bool:
        """
        Invalidate cached subscription status.

        Use this when you know the subscription status has changed.

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.

        Returns:
            True if cache was invalidated, False otherwise.
        """
        if self._cache is None:
            return False

        try:
            cache_key = self._get_cache_key(user_id, channel_id)
            await self._cache.delete(cache_key)

            logger.debug(
                "cache_invalidated",
                user_id=user_id,
                channel_id=channel_id,
            )
            return True

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            logger.warning(
                "cache_invalidate_error",
                user_id=user_id,
                channel_id=channel_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def check_bot_access(self, channel_id: int) -> tuple[bool, str | None]:
        """
        Verify that bot can check subscriptions for a channel.

        Use this before linking a channel to a group.

        Args:
            channel_id: Telegram channel ID.

        Returns:
            Tuple of (is_valid, error_message).
            If is_valid is True, error_message is None.
        """
        try:
            # Try to get bot's own membership status
            bot_user = await self._bot.get_me()
            member = await self._bot.get_chat_member(
                chat_id=channel_id,
                user_id=bot_user.id,
            )

            # Bot should be admin to check other users' membership
            if member.status not in ("administrator", "creator"):
                return (
                    False,
                    "Bot must be an administrator in the channel to check subscriptions",
                )

            return (True, None)

        except TelegramAPIError as e:
            error_str = str(e)

            if "chat not found" in error_str.lower():
                return (False, "Channel not found")
            elif "forbidden" in error_str.lower():
                return (False, "Bot cannot access this channel. Make bot an admin first.")
            else:
                logger.warning(
                    "check_bot_access_failed",
                    channel_id=channel_id,
                    error=error_str,
                    error_type=type(e).__name__,
                )
                return (False, f"Cannot verify channel access: {error_str}")


# =============================================================================
# SubscriptionRequirement (for mandatory subscription enforcement)
# =============================================================================


class SubscriptionRequirement:
    """
    Manages mandatory channel subscription requirements.

    Some groups require users to subscribe to a channel
    before they can send messages.

    This is separate from the trust signal - it's for enforcement.
    """

    def __init__(
        self,
        subscription_service: ChannelSubscriptionService,
    ) -> None:
        """
        Initialize requirement manager.

        Args:
            subscription_service: Subscription checking service.
        """
        self._service = subscription_service

    async def check_requirement(
        self,
        user_id: int,
        channel_id: int,
    ) -> tuple[bool, SubscriptionStatus]:
        """
        Check if user meets subscription requirement.

        Args:
            user_id: Telegram user ID.
            channel_id: Required channel ID.

        Returns:
            Tuple of (meets_requirement, status).
        """
        status = await self._service.check_subscription_with_details(user_id, channel_id)
        return (status.is_subscribed, status)
