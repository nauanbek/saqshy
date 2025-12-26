"""
SAQSHY Authentication Middleware

Validates user permissions and injects user context into handlers.

Responsibilities:
- Check if bot is admin in the group
- Check if user is an admin
- Check if user is whitelisted/blacklisted
- Inject user context into handler data
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import structlog
from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramRetryAfter,
)
from aiogram.types import CallbackQuery, Message, TelegramObject

if TYPE_CHECKING:
    from saqshy.services.cache import CacheService

logger = structlog.get_logger(__name__)

# Cache TTL for admin status (5 minutes)
ADMIN_CACHE_TTL = 300

# Timeout for Telegram API calls
API_TIMEOUT_SECONDS = 10.0


class AuthMiddleware(BaseMiddleware):
    """
    Authentication middleware.

    Responsibilities:
    - Check if bot is admin in the group
    - Check if user is admin
    - Check if user is banned/whitelisted
    - Inject user permissions into handler context
    """

    def __init__(self, cache_service: CacheService | None = None):
        """
        Initialize auth middleware.

        Args:
            cache_service: Redis cache service for caching admin status.
        """
        self.cache_service = cache_service

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Process authentication for incoming events.

        Injects the following into handler data:
        - user_is_admin: Whether user is a group admin
        - user_is_whitelisted: Whether user is in group whitelist
        - user_is_blacklisted: Whether user is in group blacklist
        - bot_is_admin: Whether bot has admin privileges

        Args:
            handler: Next handler in chain.
            event: Incoming event (Message, CallbackQuery, etc.).
            data: Handler context data.

        Returns:
            Handler result.
        """
        # Get cache service from data if not set in constructor
        cache_service = self.cache_service or data.get("cache_service")

        # Extract chat_id and user_id from event
        chat_id, user_id = self._extract_ids(event)

        # Skip processing for private chats
        if chat_id is None or user_id is None:
            data["user_is_admin"] = False
            data["user_is_whitelisted"] = False
            data["user_is_blacklisted"] = False
            data["bot_is_admin"] = True  # Always true for private chats
            return await handler(event, data)

        # Check user permissions
        user_is_admin = await self._check_user_is_admin(
            event=event,
            chat_id=chat_id,
            user_id=user_id,
            cache_service=cache_service,
            data=data,
        )

        user_is_whitelisted = await self._check_user_whitelist(
            chat_id=chat_id,
            user_id=user_id,
            cache_service=cache_service,
        )

        user_is_blacklisted = await self._check_user_blacklist(
            chat_id=chat_id,
            user_id=user_id,
            cache_service=cache_service,
        )

        # Inject permissions into context
        data["user_is_admin"] = user_is_admin
        data["user_is_whitelisted"] = user_is_whitelisted
        data["user_is_blacklisted"] = user_is_blacklisted
        data["bot_is_admin"] = True  # Assume bot is admin, check on error

        return await handler(event, data)

    def _extract_ids(self, event: TelegramObject) -> tuple[int | None, int | None]:
        """
        Extract chat_id and user_id from event.

        Args:
            event: Telegram event object.

        Returns:
            Tuple of (chat_id, user_id) or (None, None).
        """
        if isinstance(event, Message):
            if event.chat.type not in ("group", "supergroup"):
                return None, None
            return event.chat.id, event.from_user.id if event.from_user else None

        if isinstance(event, CallbackQuery):
            if event.message and event.message.chat.type in ("group", "supergroup"):
                return event.message.chat.id, event.from_user.id if event.from_user else None

        return None, None

    async def _check_user_is_admin(
        self,
        event: TelegramObject,
        chat_id: int,
        user_id: int,
        cache_service: CacheService | None,
        data: dict[str, Any],
    ) -> bool:
        """
        Check if user is admin in the chat.

        Uses cache to avoid hitting Telegram API on every message.

        Args:
            event: Telegram event.
            chat_id: Chat ID.
            user_id: User ID.
            cache_service: Redis cache service.
            data: Handler data containing bot instance.

        Returns:
            True if user is admin.
        """
        # Check cache first
        if cache_service:
            cache_key = f"saqshy:admin:{chat_id}:{user_id}"
            cached = await cache_service.get(cache_key)
            if cached is not None:
                return cached == "1"

        # Get bot from data
        bot: Bot | None = data.get("bot")
        if not bot:
            return False

        try:
            member = await asyncio.wait_for(
                bot.get_chat_member(chat_id=chat_id, user_id=user_id),
                timeout=API_TIMEOUT_SECONDS,
            )

            is_admin = member.status in ("creator", "administrator")

            # Cache the result
            if cache_service:
                cache_key = f"saqshy:admin:{chat_id}:{user_id}"
                await cache_service.set(
                    cache_key,
                    "1" if is_admin else "0",
                    ttl=ADMIN_CACHE_TTL,
                )

            return is_admin

        except TimeoutError:
            logger.warning(
                "admin_check_timeout",
                chat_id=chat_id,
                user_id=user_id,
            )
            return False

        except TelegramBadRequest as e:
            # User not in chat or other error
            logger.debug(
                "admin_check_failed",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
            )
            return False

        except TelegramRetryAfter as e:
            logger.warning(
                "admin_check_rate_limited",
                chat_id=chat_id,
                user_id=user_id,
                retry_after=e.retry_after,
            )
            return False

        except TelegramAPIError as e:
            logger.warning(
                "admin_check_telegram_api_error",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

        except Exception as e:
            logger.error(
                "admin_check_unexpected_error",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def _check_user_whitelist(
        self,
        chat_id: int,
        user_id: int,
        cache_service: CacheService | None,
    ) -> bool:
        """
        Check if user is whitelisted in this group.

        Args:
            chat_id: Chat ID.
            user_id: User ID.
            cache_service: Redis cache service.

        Returns:
            True if user is whitelisted.
        """
        if not cache_service:
            return False

        try:
            whitelist_key = f"saqshy:whitelist:{chat_id}"
            whitelist = await cache_service.get_json(whitelist_key)

            if not whitelist or "users" not in whitelist:
                return False

            for entry in whitelist["users"]:
                if entry.get("user_id") == user_id:
                    return True

            return False

        except TimeoutError:
            logger.warning(
                "whitelist_check_timeout",
                chat_id=chat_id,
                user_id=user_id,
            )
            return False
        except ConnectionError as e:
            logger.warning(
                "whitelist_check_connection_error",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
            )
            return False
        except Exception as e:
            logger.warning(
                "whitelist_check_unexpected_error",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def _check_user_blacklist(
        self,
        chat_id: int,
        user_id: int,
        cache_service: CacheService | None,
    ) -> bool:
        """
        Check if user is blacklisted in this group.

        Args:
            chat_id: Chat ID.
            user_id: User ID.
            cache_service: Redis cache service.

        Returns:
            True if user is blacklisted.
        """
        if not cache_service:
            return False

        try:
            blacklist_key = f"saqshy:blacklist:{chat_id}"
            blacklist = await cache_service.get_json(blacklist_key)

            if not blacklist or "users" not in blacklist:
                return False

            for entry in blacklist["users"]:
                if entry.get("user_id") == user_id:
                    return True

            return False

        except TimeoutError:
            logger.warning(
                "blacklist_check_timeout",
                chat_id=chat_id,
                user_id=user_id,
            )
            return False
        except ConnectionError as e:
            logger.warning(
                "blacklist_check_connection_error",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
            )
            return False
        except Exception as e:
            logger.warning(
                "blacklist_check_unexpected_error",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False


async def check_user_is_admin(
    bot: Bot,
    chat_id: int,
    user_id: int,
    cache_service: CacheService | None = None,
) -> bool:
    """
    Check if user is an admin in the chat.

    Standalone function for use outside middleware.

    Args:
        bot: Bot instance.
        chat_id: Chat ID.
        user_id: User ID.
        cache_service: Optional cache service.

    Returns:
        True if user is admin.
    """
    # Check cache first
    if cache_service:
        cache_key = f"saqshy:admin:{chat_id}:{user_id}"
        cached = await cache_service.get(cache_key)
        if cached is not None:
            return cached == "1"

    try:
        member = await asyncio.wait_for(
            bot.get_chat_member(chat_id=chat_id, user_id=user_id),
            timeout=API_TIMEOUT_SECONDS,
        )

        is_admin = member.status in ("creator", "administrator")

        # Cache the result
        if cache_service:
            cache_key = f"saqshy:admin:{chat_id}:{user_id}"
            await cache_service.set(
                cache_key,
                "1" if is_admin else "0",
                ttl=ADMIN_CACHE_TTL,
            )

        return is_admin

    except TimeoutError:
        logger.warning(
            "admin_check_timeout",
            chat_id=chat_id,
            user_id=user_id,
            timeout=API_TIMEOUT_SECONDS,
        )
        return False
    except TelegramBadRequest as e:
        logger.debug(
            "admin_check_telegram_error",
            chat_id=chat_id,
            user_id=user_id,
            error=str(e),
        )
        return False
    except Exception as e:
        logger.warning(
            "admin_check_unexpected_error",
            chat_id=chat_id,
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


async def refresh_admin_cache(
    bot: Bot,
    chat_id: int,
    cache_service: CacheService,
) -> set[int]:
    """
    Refresh the admin cache for a chat.

    Fetches all admins and caches their status.

    Args:
        bot: Bot instance.
        chat_id: Chat ID.
        cache_service: Cache service.

    Returns:
        Set of admin user IDs.
    """
    try:
        admins = await asyncio.wait_for(
            bot.get_chat_administrators(chat_id=chat_id),
            timeout=API_TIMEOUT_SECONDS,
        )

        admin_ids = set()
        for admin in admins:
            if admin.user:
                admin_ids.add(admin.user.id)
                cache_key = f"saqshy:admin:{chat_id}:{admin.user.id}"
                await cache_service.set(cache_key, "1", ttl=ADMIN_CACHE_TTL)

        # Store admin list for quick lookup
        await cache_service.set(
            f"group_admins:{chat_id}",
            ",".join(str(x) for x in admin_ids),
            ttl=ADMIN_CACHE_TTL,
        )

        logger.info(
            "admin_cache_refreshed",
            chat_id=chat_id,
            admin_count=len(admin_ids),
        )

        return admin_ids

    except TimeoutError:
        logger.warning(
            "admin_cache_refresh_timeout",
            chat_id=chat_id,
            timeout=API_TIMEOUT_SECONDS,
        )
        return set()
    except TelegramBadRequest as e:
        logger.warning(
            "admin_cache_refresh_bad_request",
            chat_id=chat_id,
            error=str(e),
        )
        return set()
    except TelegramAPIError as e:
        logger.warning(
            "admin_cache_refresh_telegram_error",
            chat_id=chat_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return set()
    except ConnectionError as e:
        logger.warning(
            "admin_cache_refresh_connection_error",
            chat_id=chat_id,
            error=str(e),
        )
        return set()
    except Exception as e:
        logger.error(
            "admin_cache_refresh_unexpected_error",
            chat_id=chat_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return set()
