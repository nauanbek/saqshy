"""
SAQSHY Rate Limiting Middleware

Prevents abuse by limiting message frequency.
Uses Redis-backed CacheService for distributed rate limiting.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

if TYPE_CHECKING:
    from saqshy.services.cache import CacheService

logger = structlog.get_logger(__name__)


class RateLimitMiddleware(BaseMiddleware):
    """
    Rate limiting middleware.

    Uses CacheService for distributed rate limiting across instances.

    Limits:
    - Per-user message rate (prevents spam floods)
    - Per-group message rate (prevents group flooding)
    - Skips admins and whitelisted users
    """

    def __init__(
        self,
        cache_service: CacheService | None = None,
        user_limit: int = 20,
        user_window: int = 60,
        group_limit: int = 200,
        group_window: int = 60,
    ):
        """
        Initialize rate limiter.

        Args:
            cache_service: Redis cache service for rate limiting.
            user_limit: Max messages per user per window.
            user_window: Window size in seconds.
            group_limit: Max messages per group per window.
            group_window: Window size in seconds.
        """
        self.cache_service = cache_service
        self.user_limit = user_limit
        self.user_window = user_window
        self.group_limit = group_limit
        self.group_window = group_window

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Check rate limits for incoming events.

        Args:
            handler: Next handler in chain.
            event: Incoming event.
            data: Handler context data.

        Returns:
            Handler result or None if rate limited.
        """
        if not isinstance(event, Message):
            return await handler(event, data)

        message: Message = event

        if not message.from_user:
            return await handler(event, data)

        # Get cache service from data if not set in constructor
        cache_service = self.cache_service or data.get("cache_service")

        # Skip rate limiting for admins and whitelisted users
        if data.get("user_is_admin") or data.get("user_is_whitelisted"):
            data["is_rate_limited"] = False
            return await handler(event, data)

        # Check user rate limit
        is_user_limited = False
        if cache_service and message.chat.type in ("group", "supergroup"):
            is_user_limited = await self._check_user_rate(
                cache_service=cache_service,
                user_id=message.from_user.id,
                chat_id=message.chat.id,
            )

        if is_user_limited:
            logger.warning(
                "user_rate_limited",
                user_id=message.from_user.id,
                chat_id=message.chat.id,
            )
            data["is_rate_limited"] = True
            # Don't process rate-limited messages through spam detection
            # but still allow the handler to run for logging
            return None

        # Inject rate limit status into context
        data["is_rate_limited"] = False

        return await handler(event, data)

    async def _check_user_rate(
        self,
        cache_service: CacheService,
        user_id: int,
        chat_id: int,
    ) -> bool:
        """
        Check if user is rate limited.

        Uses sliding window rate limiting via CacheService.

        Args:
            cache_service: Redis cache service.
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            True if rate limited.
        """
        try:
            count = await cache_service.increment_rate(
                user_id=user_id,
                chat_id=chat_id,
                window_seconds=self.user_window,
            )

            return count > self.user_limit

        except TimeoutError:
            logger.warning(
                "rate_check_timeout",
                user_id=user_id,
                chat_id=chat_id,
            )
            # Fail-open: allow message through on timeout
            return False
        except ConnectionError as e:
            logger.warning(
                "rate_check_connection_error",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )
            # Fail-open: allow message through on connection error
            return False
        except Exception as e:
            logger.warning(
                "rate_check_unexpected_error",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            # Fail-open: allow message through on error
            return False

    async def check_group_rate(
        self,
        cache_service: CacheService,
        chat_id: int,
    ) -> bool:
        """
        Check if group is rate limited (being flooded).

        Args:
            cache_service: Redis cache service.
            chat_id: Telegram chat ID.

        Returns:
            True if group rate limit exceeded.
        """
        try:
            # Use user_id=0 for group-level rate limiting
            count = await cache_service.increment_rate(
                user_id=0,
                chat_id=chat_id,
                window_seconds=self.group_window,
            )

            return count > self.group_limit

        except TimeoutError:
            logger.warning(
                "group_rate_check_timeout",
                chat_id=chat_id,
            )
            return False
        except ConnectionError as e:
            logger.warning(
                "group_rate_check_connection_error",
                chat_id=chat_id,
                error=str(e),
            )
            return False
        except Exception as e:
            logger.warning(
                "group_rate_check_unexpected_error",
                chat_id=chat_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def check_raid_limit(
        self,
        cache_service: CacheService,
        chat_id: int,
        threshold: int = 10,
        window: int = 60,
    ) -> bool:
        """
        Check if group is being raided (mass joins).

        Args:
            cache_service: Redis cache service.
            chat_id: Telegram chat ID.
            threshold: Maximum joins in window before raid mode.
            window: Time window in seconds.

        Returns:
            True if raid detected.
        """
        try:
            # Check raid mode status
            raid_key = f"saqshy:raid:active:{chat_id}"
            is_raid = await cache_service.get(raid_key)
            return is_raid == "1"

        except TimeoutError:
            logger.warning(
                "raid_check_timeout",
                chat_id=chat_id,
            )
            return False
        except ConnectionError as e:
            logger.warning(
                "raid_check_connection_error",
                chat_id=chat_id,
                error=str(e),
            )
            return False
        except Exception as e:
            logger.warning(
                "raid_check_unexpected_error",
                chat_id=chat_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False


class AdaptiveRateLimiter:
    """
    Adaptive rate limiter that adjusts limits based on user behavior.

    Trusted users get higher limits, suspicious users get lower limits.
    """

    def __init__(
        self,
        cache_service: CacheService,
        base_limit: int = 20,
        trusted_multiplier: float = 2.0,
        suspicious_multiplier: float = 0.5,
    ):
        """
        Initialize adaptive rate limiter.

        Args:
            cache_service: Redis cache service.
            base_limit: Base message limit per minute.
            trusted_multiplier: Limit multiplier for trusted users.
            suspicious_multiplier: Limit multiplier for suspicious users.
        """
        self.cache_service = cache_service
        self.base_limit = base_limit
        self.trusted_multiplier = trusted_multiplier
        self.suspicious_multiplier = suspicious_multiplier

    async def get_user_limit(self, user_id: int, chat_id: int) -> int:
        """
        Get personalized rate limit for a user.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            Personalized rate limit.
        """
        try:
            # Get user trust score
            user_key = f"saqshy:user_stats:{user_id}"
            stats = await self.cache_service.get_json(user_key)

            if not stats:
                return self.base_limit

            approved = stats.get("approved", 0)
            blocked = stats.get("blocked", 0)
            total = approved + blocked

            if total == 0:
                return self.base_limit

            # Calculate trust ratio
            trust_ratio = approved / total

            if trust_ratio > 0.9:
                # Trusted user - higher limit
                return int(self.base_limit * self.trusted_multiplier)
            elif trust_ratio < 0.5:
                # Suspicious user - lower limit
                return int(self.base_limit * self.suspicious_multiplier)
            else:
                return self.base_limit

        except TimeoutError:
            logger.warning(
                "get_user_limit_timeout",
                user_id=user_id,
            )
            return self.base_limit
        except ConnectionError as e:
            logger.warning(
                "get_user_limit_connection_error",
                user_id=user_id,
                error=str(e),
            )
            return self.base_limit
        except Exception as e:
            logger.warning(
                "get_user_limit_unexpected_error",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return self.base_limit

    async def check_and_record(
        self,
        user_id: int,
        chat_id: int,
        window: int = 60,
    ) -> tuple[bool, int, int]:
        """
        Check rate limit and record message.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            window: Time window in seconds.

        Returns:
            Tuple of (is_limited, current_count, limit).
        """
        limit = await self.get_user_limit(user_id, chat_id)

        try:
            count = await self.cache_service.increment_rate(
                user_id=user_id,
                chat_id=chat_id,
                window_seconds=window,
            )

            return count > limit, count, limit

        except TimeoutError:
            logger.warning(
                "adaptive_rate_check_timeout",
                user_id=user_id,
            )
            return False, 0, limit
        except ConnectionError as e:
            logger.warning(
                "adaptive_rate_check_connection_error",
                user_id=user_id,
                error=str(e),
            )
            return False, 0, limit
        except Exception as e:
            logger.warning(
                "adaptive_rate_check_unexpected_error",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False, 0, limit
