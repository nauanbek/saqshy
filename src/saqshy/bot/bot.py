"""
SAQSHY Bot Initialization

Creates and configures the aiogram bot and dispatcher with full production setup.

Responsibilities:
- Create Bot instance with proper defaults
- Create Dispatcher with all routers and middlewares
- Setup webhook with secret token verification
- Manage startup/shutdown lifecycle hooks
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter

if TYPE_CHECKING:
    from saqshy.config import Settings
    from saqshy.services.cache import CacheService
    from saqshy.services.channel_subscription import ChannelSubscriptionService
    from saqshy.services.spam_db import SpamDB

logger = structlog.get_logger(__name__)


def create_bot(settings: Settings) -> Bot:
    """
    Create and configure the Telegram bot.

    Args:
        settings: Application settings.

    Returns:
        Configured Bot instance.
    """
    bot = Bot(
        token=settings.telegram.bot_token.get_secret_value(),
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True,
        ),
    )

    logger.info("bot_created")

    return bot


def create_dispatcher(
    cache_service: CacheService | None = None,
    spam_db: SpamDB | None = None,
    channel_subscription_service: ChannelSubscriptionService | None = None,
) -> Dispatcher:
    """
    Create and configure the dispatcher.

    Sets up all routers, handlers, and middlewares in the correct order.

    Middleware execution order (outer to inner):
    1. ErrorMiddleware (outer) - catches all errors, prevents propagation
    2. LoggingMiddleware - logs requests with correlation IDs
    3. AuthMiddleware - validates permissions, injects user context
    4. RateLimitMiddleware - prevents abuse, uses CacheService

    Args:
        cache_service: Redis cache service for rate limiting and caching.
        spam_db: SpamDB service for spam pattern matching.
        channel_subscription_service: Service for checking channel subscriptions.

    Returns:
        Configured Dispatcher instance.
    """
    dp = Dispatcher()

    # Store services in dispatcher workflow_data for access in handlers
    dp.workflow_data["cache_service"] = cache_service
    dp.workflow_data["spam_db"] = spam_db
    dp.workflow_data["channel_subscription_service"] = channel_subscription_service

    # Import the main router which already includes all sub-routers
    # (commands, callbacks, members, messages) in the correct priority order
    # See saqshy/bot/handlers/__init__.py for the router hierarchy
    from saqshy.bot.handlers import router as main_router

    # Register the main router (contains all handlers)
    dp.include_router(main_router)

    # Import middlewares
    from saqshy.bot.middlewares import (
        AuthMiddleware,
        ErrorMiddleware,
        LoggingMiddleware,
        RateLimitMiddleware,
    )

    # Register middlewares in execution order
    # Outer middlewares execute first on request, last on response

    # ErrorMiddleware as OUTER middleware - catches all errors from inner middlewares/handlers
    dp.message.outer_middleware(ErrorMiddleware())
    dp.callback_query.outer_middleware(ErrorMiddleware())
    dp.chat_member.outer_middleware(ErrorMiddleware())

    # Inner middlewares execute in registration order
    # LoggingMiddleware first - logs all requests with correlation ID
    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())
    dp.chat_member.middleware(LoggingMiddleware())

    # AuthMiddleware - validates permissions, injects user context
    dp.message.middleware(AuthMiddleware(cache_service=cache_service))
    dp.callback_query.middleware(AuthMiddleware(cache_service=cache_service))

    # RateLimitMiddleware - prevents abuse using CacheService
    dp.message.middleware(RateLimitMiddleware(cache_service=cache_service))

    logger.info(
        "dispatcher_created",
        router="main",
        sub_routers=["commands", "callbacks", "members", "messages"],
        middlewares=["error", "logging", "auth", "rate_limit"],
    )

    return dp


async def setup_webhook(
    bot: Bot,
    webhook_url: str,
    secret: str,
    drop_pending: bool = True,
    max_retries: int = 3,
) -> bool:
    """
    Set up webhook for the bot with retry logic.

    Args:
        bot: Bot instance.
        webhook_url: Full webhook URL (e.g., https://example.com/webhook).
        secret: Webhook secret token for verification.
        drop_pending: Whether to drop pending updates.
        max_retries: Maximum retry attempts on failure.

    Returns:
        True if webhook was set successfully.
    """
    # Allowed updates - only what we need
    allowed_updates = [
        "message",
        "callback_query",
        "chat_member",
        "my_chat_member",
    ]

    for attempt in range(max_retries):
        try:
            await bot.set_webhook(
                url=webhook_url,
                secret_token=secret if secret else None,
                allowed_updates=allowed_updates,
                drop_pending_updates=drop_pending,
            )

            logger.info(
                "webhook_set",
                url=webhook_url,
                allowed_updates=allowed_updates,
                drop_pending=drop_pending,
            )
            return True

        except TelegramRetryAfter as e:
            wait_time = e.retry_after
            logger.warning(
                "webhook_rate_limited",
                retry_after=wait_time,
                attempt=attempt + 1,
            )
            await asyncio.sleep(wait_time)

        except Exception as e:
            logger.error(
                "webhook_setup_failed",
                error=str(e),
                error_type=type(e).__name__,
                attempt=attempt + 1,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(2**attempt)  # Exponential backoff

    return False


async def remove_webhook(bot: Bot, drop_pending: bool = True) -> bool:
    """
    Remove webhook from the bot.

    Args:
        bot: Bot instance.
        drop_pending: Whether to drop pending updates.

    Returns:
        True if webhook was removed successfully.
    """
    try:
        await bot.delete_webhook(drop_pending_updates=drop_pending)
        logger.info("webhook_removed", drop_pending=drop_pending)
        return True

    except Exception as e:
        logger.error(
            "webhook_removal_failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


async def get_webhook_info(bot: Bot) -> dict[str, Any]:
    """
    Get current webhook configuration.

    Args:
        bot: Bot instance.

    Returns:
        Dictionary with webhook info.
    """
    try:
        info = await bot.get_webhook_info()
        return {
            "url": info.url,
            "has_custom_certificate": info.has_custom_certificate,
            "pending_update_count": info.pending_update_count,
            "last_error_date": info.last_error_date,
            "last_error_message": info.last_error_message,
            "max_connections": info.max_connections,
            "allowed_updates": info.allowed_updates,
        }
    except Exception as e:
        logger.error("get_webhook_info_failed", error=str(e))
        return {"error": str(e)}


async def on_startup(
    bot: Bot,
    cache_service: CacheService | None = None,
    spam_db: SpamDB | None = None,
) -> None:
    """
    Startup lifecycle hook.

    Called when the bot starts up. Initialize services and connections.

    Args:
        bot: Bot instance.
        cache_service: Redis cache service.
        spam_db: SpamDB service.
    """
    logger.info("bot_startup_begin")

    # Connect cache service
    if cache_service:
        try:
            await cache_service.connect()
            logger.info("cache_service_connected")
        except Exception as e:
            logger.error("cache_service_connection_failed", error=str(e))

    # Initialize spam database
    if spam_db:
        try:
            await spam_db.initialize()
            logger.info("spam_db_initialized")
        except Exception as e:
            logger.error("spam_db_initialization_failed", error=str(e))

    # Get bot info for logging
    try:
        bot_info = await bot.get_me()
        logger.info(
            "bot_startup_complete",
            bot_id=bot_info.id,
            bot_username=bot_info.username,
            bot_name=bot_info.first_name,
        )
    except Exception as e:
        logger.warning("bot_info_fetch_failed", error=str(e))


async def on_shutdown(
    bot: Bot,
    cache_service: CacheService | None = None,
    spam_db: SpamDB | None = None,
) -> None:
    """
    Shutdown lifecycle hook.

    Called when the bot shuts down. Close connections and cleanup.

    Args:
        bot: Bot instance.
        cache_service: Redis cache service.
        spam_db: SpamDB service.
    """
    logger.info("bot_shutdown_begin")

    # Close spam database
    if spam_db:
        try:
            await spam_db.close()
            logger.info("spam_db_closed")
        except Exception as e:
            logger.error("spam_db_close_failed", error=str(e))

    # Close cache service
    if cache_service:
        try:
            await cache_service.close()
            logger.info("cache_service_closed")
        except Exception as e:
            logger.error("cache_service_close_failed", error=str(e))

    # Close bot session
    try:
        await bot.session.close()
        logger.info("bot_session_closed")
    except Exception as e:
        logger.warning("bot_session_close_failed", error=str(e))

    logger.info("bot_shutdown_complete")


def verify_webhook_secret(received_secret: str | None, expected_secret: str) -> bool:
    """
    Verify webhook secret token.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        received_secret: Secret token from X-Telegram-Bot-Api-Secret-Token header.
        expected_secret: Expected secret token from configuration.

    Returns:
        True if secrets match (or no secret is configured).
    """
    import hmac

    # If no secret configured, allow all (not recommended for production)
    if not expected_secret:
        return True

    # If secret configured but not received, reject
    if not received_secret:
        logger.warning("webhook_secret_missing")
        return False

    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(received_secret, expected_secret)
