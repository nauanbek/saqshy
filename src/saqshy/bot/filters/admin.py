"""
SAQSHY Admin Filters

Filters for checking admin permissions with caching support.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

if TYPE_CHECKING:
    from saqshy.services.cache import CacheService

logger = structlog.get_logger(__name__)

# Cache TTL for admin status (5 minutes)
ADMIN_CACHE_TTL = 300

# Timeout for Telegram API calls
API_TIMEOUT_SECONDS = 10.0


class AdminFilter(Filter):
    """
    Filter that checks if user is a group admin or creator.

    Uses caching to minimize Telegram API calls.
    Falls back to middleware-injected admin status if available.

    Usage:
        @router.message(Command("settings"), AdminFilter())
        async def admin_command(message: Message): ...
    """

    async def __call__(
        self,
        event: Message | CallbackQuery,
        bot: Bot | None = None,
        cache_service: CacheService | None = None,
        user_is_admin: bool | None = None,
        **kwargs: Any,
    ) -> bool:
        """
        Check if user is admin.

        First checks middleware-injected admin status.
        Falls back to cache, then to Telegram API.

        Args:
            event: Message or CallbackQuery.
            bot: Bot instance.
            cache_service: Optional cache service.
            user_is_admin: Pre-computed admin status from middleware.

        Returns:
            True if user is admin.
        """
        # Use middleware-injected status if available
        if user_is_admin is not None:
            return user_is_admin

        # Extract message from event
        user = event.from_user
        if user is None:
            return False

        if isinstance(event, CallbackQuery):
            message = event.message
            if not message:
                return False
        else:
            message = event

        # Private chats - user is always "admin"
        if message.chat.type == "private":
            return True

        # Must be a group/supergroup
        if message.chat.type not in ("group", "supergroup"):
            return False

        chat_id = message.chat.id
        user_id = user.id

        # Check cache first
        if cache_service:
            cache_key = f"saqshy:admin:{chat_id}:{user_id}"
            try:
                cached = await cache_service.get(cache_key)
                if cached is not None:
                    return cached == "1"
            except Exception as e:
                logger.debug("admin_cache_check_failed", error=str(e))

        # Check admin status via Telegram API
        if not bot:
            # Try to get bot from message
            try:
                member = await asyncio.wait_for(
                    message.chat.get_member(user_id),
                    timeout=API_TIMEOUT_SECONDS,
                )
                is_admin = member.status in ("creator", "administrator")

                # Cache result if cache service available
                if cache_service:
                    cache_key = f"saqshy:admin:{chat_id}:{user_id}"
                    try:
                        await cache_service.set(
                            cache_key,
                            "1" if is_admin else "0",
                            ttl=ADMIN_CACHE_TTL,
                        )
                    except Exception as e:
                        logger.debug(
                            "admin_cache_set_failed",
                            cache_key=cache_key,
                            error=str(e),
                        )

                return is_admin

            except TimeoutError:
                logger.warning("admin_check_timeout", user_id=user_id, chat_id=chat_id)
                return False

            except TelegramRetryAfter as e:
                logger.warning("admin_check_rate_limited", retry_after=e.retry_after)
                return False

            except TelegramBadRequest as e:
                logger.debug("admin_check_failed", error=str(e))
                return False

            except Exception as e:
                logger.warning("admin_check_error", error=str(e))
                return False

        # Use bot instance if provided
        try:
            member = await asyncio.wait_for(
                bot.get_chat_member(chat_id=chat_id, user_id=user_id),
                timeout=API_TIMEOUT_SECONDS,
            )
            is_admin = member.status in ("creator", "administrator")

            # Cache result
            if cache_service:
                cache_key = f"saqshy:admin:{chat_id}:{user_id}"
                try:
                    await cache_service.set(
                        cache_key,
                        "1" if is_admin else "0",
                        ttl=ADMIN_CACHE_TTL,
                    )
                except Exception as e:
                    logger.debug(
                        "admin_cache_set_failed",
                        cache_key=cache_key,
                        error=str(e),
                    )

            return is_admin

        except TimeoutError:
            logger.warning("admin_check_timeout", user_id=user_id, chat_id=chat_id)
            return False
        except TelegramBadRequest as e:
            logger.debug("admin_check_telegram_error", error=str(e))
            return False
        except Exception as e:
            logger.warning(
                "admin_check_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            return False


# Alias for backward compatibility
IsAdmin = AdminFilter


class IsGroupAdmin(Filter):
    """
    Filter that checks if user is admin in a GROUP (not private chat).

    Unlike AdminFilter, this returns False for private chats.
    """

    async def __call__(
        self,
        event: Message | CallbackQuery,
        user_is_admin: bool | None = None,
        **kwargs: Any,
    ) -> bool:
        """
        Check if user is group admin.

        Args:
            event: Message or CallbackQuery.
            user_is_admin: Pre-computed admin status from middleware.

        Returns:
            True if user is admin in a group.
        """
        if isinstance(event, CallbackQuery):
            message = event.message
            if not message or not isinstance(message, Message):
                return False
        else:
            message = event

        if not message.from_user:
            return False

        # Must be a group chat
        if message.chat.type not in ("group", "supergroup"):
            return False

        # Use middleware status if available
        if user_is_admin is not None:
            return user_is_admin

        # Fall back to API check
        try:
            member = await asyncio.wait_for(
                message.chat.get_member(message.from_user.id),
                timeout=API_TIMEOUT_SECONDS,
            )
            return member.status in ("creator", "administrator")
        except Exception as e:
            logger.warning("group_admin_check_failed", error=str(e))
            return False


class IsBotAdmin(Filter):
    """
    Filter that checks if the BOT is an admin in the group.

    Used to ensure bot has necessary permissions before taking actions.
    """

    def __init__(
        self,
        require_delete: bool = False,
        require_restrict: bool = False,
        require_ban: bool = False,
    ):
        """
        Initialize filter with required permissions.

        Args:
            require_delete: Require delete_messages permission.
            require_restrict: Require restrict_members permission.
            require_ban: Require ban_users permission.
        """
        self.require_delete = require_delete
        self.require_restrict = require_restrict
        self.require_ban = require_ban

    async def __call__(
        self,
        message: Message,
        bot: Bot,
        cache_service: CacheService | None = None,
    ) -> bool:
        """
        Check if bot is admin with required permissions.

        Args:
            message: Message object.
            bot: Bot instance.
            cache_service: Optional cache service.

        Returns:
            True if bot has required permissions.
        """
        if message.chat.type not in ("group", "supergroup"):
            return True  # Not applicable in private chats

        chat_id = message.chat.id

        # Check cache first
        if cache_service:
            cache_key = f"saqshy:bot_admin:{chat_id}"
            try:
                cached = await cache_service.get_json(cache_key)
                if cached:
                    # Verify required permissions
                    if self.require_delete and not cached.get("can_delete"):
                        return False
                    if self.require_restrict and not cached.get("can_restrict"):
                        return False
                    if self.require_ban and not cached.get("can_ban"):
                        return False
                    return True
            except Exception as e:
                logger.debug(
                    "bot_admin_cache_get_failed",
                    cache_key=cache_key,
                    error=str(e),
                )

        try:
            bot_info = await bot.get_me()
            bot_member = await asyncio.wait_for(
                bot.get_chat_member(chat_id=chat_id, user_id=bot_info.id),
                timeout=API_TIMEOUT_SECONDS,
            )

            if bot_member.status != "administrator":
                return False

            # Check specific permissions
            permissions = {
                "can_delete": getattr(bot_member, "can_delete_messages", False),
                "can_restrict": getattr(bot_member, "can_restrict_members", False),
                "can_ban": getattr(bot_member, "can_restrict_members", False),
            }

            # Cache bot permissions
            if cache_service:
                cache_key = f"saqshy:bot_admin:{chat_id}"
                try:
                    await cache_service.set_json(cache_key, permissions, ttl=ADMIN_CACHE_TTL)
                except Exception as e:
                    logger.debug(
                        "bot_admin_cache_set_failed",
                        cache_key=cache_key,
                        error=str(e),
                    )

            if self.require_delete and not permissions["can_delete"]:
                logger.warning("bot_missing_delete_permission", chat_id=chat_id)
                return False

            if self.require_restrict and not permissions["can_restrict"]:
                logger.warning("bot_missing_restrict_permission", chat_id=chat_id)
                return False

            if self.require_ban and not permissions["can_ban"]:
                logger.warning("bot_missing_ban_permission", chat_id=chat_id)
                return False

            return True

        except Exception as e:
            logger.warning("bot_admin_check_failed", chat_id=chat_id, error=str(e))
            return False


class IsCreator(Filter):
    """
    Filter that checks if user is the group CREATOR.

    Some actions should only be available to the creator.
    """

    async def __call__(
        self,
        message: Message,
        cache_service: CacheService | None = None,
    ) -> bool:
        """
        Check if user is creator.

        Args:
            message: Message object.
            cache_service: Optional cache service.

        Returns:
            True if user is creator.
        """
        if not message.from_user:
            return False

        if message.chat.type not in ("group", "supergroup"):
            return False

        chat_id = message.chat.id
        user_id = message.from_user.id

        # Check cache first
        if cache_service:
            cache_key = f"saqshy:creator:{chat_id}"
            try:
                creator_id = await cache_service.get(cache_key)
                if creator_id:
                    return int(creator_id) == user_id
            except ValueError as e:
                logger.debug(
                    "creator_cache_parse_failed",
                    cache_key=cache_key,
                    error=str(e),
                )
            except Exception as e:
                logger.debug(
                    "creator_cache_get_failed",
                    cache_key=cache_key,
                    error=str(e),
                )

        try:
            member = await asyncio.wait_for(
                message.chat.get_member(user_id),
                timeout=API_TIMEOUT_SECONDS,
            )

            is_creator = member.status == "creator"

            # Cache creator ID
            if is_creator and cache_service:
                cache_key = f"saqshy:creator:{chat_id}"
                try:
                    await cache_service.set(cache_key, str(user_id), ttl=ADMIN_CACHE_TTL * 2)
                except Exception as e:
                    logger.debug(
                        "creator_cache_set_failed",
                        cache_key=cache_key,
                        error=str(e),
                    )

            return is_creator

        except TimeoutError:
            logger.debug(
                "creator_check_timeout",
                chat_id=chat_id,
                user_id=user_id,
            )
            return False
        except TelegramBadRequest as e:
            logger.debug(
                "creator_check_telegram_error",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
            )
            return False
        except Exception as e:
            logger.warning(
                "creator_check_unexpected_error",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False


class IsWhitelisted(Filter):
    """
    Filter that checks if user is whitelisted in the group.
    """

    async def __call__(
        self,
        event: Message | CallbackQuery,
        user_is_whitelisted: bool | None = None,
        **kwargs: Any,
    ) -> bool:
        """
        Check if user is whitelisted.

        Args:
            event: Message or CallbackQuery.
            user_is_whitelisted: Pre-computed status from middleware.

        Returns:
            True if user is whitelisted.
        """
        if user_is_whitelisted is not None:
            return user_is_whitelisted
        return False
