"""
SAQSHY Logging Middleware

Production-grade logging middleware for aiogram handlers.

Features:
- Correlation ID generation and propagation
- Request context management (chat_id, user_id, group_type)
- Processing time measurement
- Structured logging with sensitive data filtering
- Integration with core logging and metrics modules

This middleware should be registered first in the middleware chain
to ensure correlation IDs are available for all downstream processing.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message, TelegramObject

from saqshy.core.logging import (
    clear_correlation_id,
    clear_request_context,
    generate_correlation_id,
    get_correlation_id,
    get_logger,
    set_correlation_id,
    set_request_context,
)

logger = get_logger(__name__)


class CorrelationIdMiddleware(BaseMiddleware):
    """
    Correlation ID middleware for request tracing.

    Generates a unique correlation ID for each incoming event and
    propagates it through the context for downstream logging.

    The correlation ID is:
    - Generated at the start of each request
    - Stored in contextvars for thread-safe access
    - Injected into handler data for explicit access
    - Automatically included in all log entries
    - Cleared after request completion

    Example:
        >>> dp.update.middleware(CorrelationIdMiddleware())
        >>> # In handler:
        >>> correlation_id = data["correlation_id"]
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Generate correlation ID and process event.

        Args:
            handler: Next handler in chain.
            event: Incoming Telegram event.
            data: Handler context data.

        Returns:
            Handler result.
        """
        # Generate new correlation ID for this request
        correlation_id = generate_correlation_id()
        set_correlation_id(correlation_id)

        # Inject into handler data for explicit access
        data["correlation_id"] = correlation_id

        try:
            return await handler(event, data)
        finally:
            # Clear correlation ID after request
            clear_correlation_id()


class RequestContextMiddleware(BaseMiddleware):
    """
    Request context middleware.

    Extracts context from the event (chat_id, user_id, etc.) and
    stores it for automatic inclusion in log entries.

    This middleware should run after CorrelationIdMiddleware but
    before LoggingMiddleware.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Extract and set request context.

        Args:
            handler: Next handler in chain.
            event: Incoming Telegram event.
            data: Handler context data.

        Returns:
            Handler result.
        """
        # Extract context from event
        context = self._extract_context(event, data)

        # Set in contextvars for automatic log inclusion
        set_request_context(context)

        try:
            return await handler(event, data)
        finally:
            # Clear context after request
            clear_request_context()

    def _extract_context(
        self,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Extract context fields from event.

        Args:
            event: Telegram event.
            data: Handler data.

        Returns:
            Context dictionary.
        """
        context: dict[str, Any] = {}

        if isinstance(event, Message):
            context["chat_id"] = event.chat.id
            context["message_id"] = event.message_id
            if event.from_user:
                context["user_id"] = event.from_user.id

        elif isinstance(event, CallbackQuery):
            if event.from_user:
                context["user_id"] = event.from_user.id
            if event.message:
                context["chat_id"] = event.message.chat.id
                context["message_id"] = event.message.message_id

        elif isinstance(event, ChatMemberUpdated):
            context["chat_id"] = event.chat.id
            if event.from_user:
                context["user_id"] = event.from_user.id

        # Add group_type if available from data
        if "group" in data and hasattr(data["group"], "group_type"):
            context["group_type"] = data["group"].group_type.value

        return context


class LoggingMiddleware(BaseMiddleware):
    """
    Comprehensive logging middleware.

    Logs incoming events with timing information and status.
    Works with CorrelationIdMiddleware for request tracing.

    Features:
    - Structured event logging
    - Processing time measurement
    - Error logging with full context
    - Sensitive data filtering (via core logging)

    Log Levels:
    - DEBUG: event_received, event_processed (success)
    - INFO: Significant events (new members, moderation actions)
    - WARNING: Non-fatal errors
    - ERROR: event_error (exceptions)
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Log event processing.

        Args:
            handler: Next handler in chain.
            event: Incoming Telegram event.
            data: Handler context data.

        Returns:
            Handler result.
        """
        start_time = time.perf_counter()
        correlation_id = data.get("correlation_id", get_correlation_id())

        # Extract event info for logging
        event_info = self._extract_event_info(event)

        # Create bound logger with event context
        log = logger.bind(
            correlation_id=correlation_id,
            **event_info,
        )

        log.debug("event_received")

        try:
            result = await handler(event, data)

            # Calculate elapsed time
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            log.debug(
                "event_processed",
                elapsed_ms=round(elapsed_ms, 2),
                status="success",
            )

            return result

        except Exception as e:
            # Calculate elapsed time
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            log.error(
                "event_error",
                error=str(e),
                error_type=type(e).__name__,
                elapsed_ms=round(elapsed_ms, 2),
                status="error",
                exc_info=e,
            )
            raise

    def _extract_event_info(self, event: TelegramObject) -> dict[str, Any]:
        """
        Extract relevant info from event for logging.

        Carefully avoids logging sensitive data like message content.

        Args:
            event: Telegram event object.

        Returns:
            Dict with safe event info.
        """
        info: dict[str, Any] = {
            "event_type": type(event).__name__,
        }

        if isinstance(event, Message):
            info["message_id"] = event.message_id
            info["chat_id"] = event.chat.id
            info["chat_type"] = event.chat.type

            if event.from_user:
                info["user_id"] = event.from_user.id
                # Don't log username - could be PII

            if event.text:
                # Only log text length, not content
                info["text_len"] = len(event.text)

            info["has_media"] = bool(
                event.photo
                or event.video
                or event.document
                or event.audio
                or event.voice
                or event.sticker
            )
            info["is_forward"] = bool(event.forward_date)
            info["is_reply"] = bool(event.reply_to_message)

        elif isinstance(event, CallbackQuery):
            # Don't log callback data - could be sensitive
            if event.from_user:
                info["user_id"] = event.from_user.id
            if event.message:
                info["message_id"] = event.message.message_id
                info["chat_id"] = event.message.chat.id

        elif isinstance(event, ChatMemberUpdated):
            info["chat_id"] = event.chat.id
            if event.from_user:
                info["user_id"] = event.from_user.id
            if event.new_chat_member:
                info["new_status"] = event.new_chat_member.status

        return info


class MetricsMiddleware(BaseMiddleware):
    """
    Metrics collection middleware.

    Integrates with the MetricsCollector to record:
    - Event counts by type
    - Processing latencies
    - Error rates
    - Per-group statistics

    Uses both in-memory aggregation and Redis persistence.
    """

    def __init__(self, metrics_collector: Any | None = None) -> None:
        """
        Initialize metrics middleware.

        Args:
            metrics_collector: Optional MetricsCollector instance.
        """
        self.metrics = metrics_collector
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Collect metrics for events.

        Args:
            handler: Next handler in chain.
            event: Incoming Telegram event.
            data: Handler context data.

        Returns:
            Handler result.
        """
        start_time = time.perf_counter()
        event_type = type(event).__name__
        status = "success"
        group_type = "general"

        # Try to get group_type from data
        if "group" in data and hasattr(data["group"], "group_type"):
            group_type = data["group"].group_type.value

        try:
            result = await handler(event, data)
            return result

        except Exception as e:
            status = "error"
            logger.debug(
                "handler_exception_in_logging_middleware",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

        finally:
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Record to MetricsCollector if available
            if self.metrics:
                try:
                    if status == "error":
                        await self.metrics.record_error(
                            group_type=group_type,
                            error_type="handler_exception",
                        )
                except Exception as e:
                    # Never fail on metrics - but do log for debugging
                    logger.debug(
                        "metrics_recording_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                    )

            # Also record to cache service for backward compatibility
            cache_service = data.get("cache_service")
            if cache_service:
                await self._record_cache_metrics(
                    cache_service=cache_service,
                    event=event,
                    event_type=event_type,
                    status=status,
                    elapsed_ms=elapsed_ms,
                )

    async def _record_cache_metrics(
        self,
        cache_service: Any,
        event: TelegramObject,
        event_type: str,
        status: str,
        elapsed_ms: float,
    ) -> None:
        """
        Record metrics to Redis cache.

        Args:
            cache_service: Cache service instance.
            event: Telegram event.
            event_type: Type of event.
            status: Processing status.
            elapsed_ms: Processing time in milliseconds.
        """
        try:
            # Get chat_id for per-group metrics
            chat_id = None
            if isinstance(event, Message):
                chat_id = event.chat.id
            elif isinstance(event, CallbackQuery) and event.message:
                chat_id = event.message.chat.id

            if chat_id:
                # Increment per-group message counter
                stats_key = f"saqshy:stats:{chat_id}"
                stats = await cache_service.get_json(stats_key) or {
                    "total_messages": 0,
                    "messages_scanned": 0,
                    "allowed": 0,
                    "watching": 0,
                    "limited": 0,
                    "review": 0,
                    "blocked": 0,
                    "errors": 0,
                }

                stats["total_messages"] = stats.get("total_messages", 0) + 1

                if event_type == "Message":
                    stats["messages_scanned"] = stats.get("messages_scanned", 0) + 1

                if status == "error":
                    stats["errors"] = stats.get("errors", 0) + 1

                await cache_service.set_json(stats_key, stats, ttl=86400)  # 24h

        except ConnectionError as e:
            logger.debug(
                "metrics_cache_recording_connection_error",
                error=str(e),
            )
        except Exception as e:
            logger.debug(
                "metrics_cache_recording_unexpected_error",
                error=str(e),
                error_type=type(e).__name__,
            )


# =============================================================================
# Middleware Chain Helper
# =============================================================================


def register_logging_middlewares(
    router: Any,
    metrics_collector: Any | None = None,
) -> None:
    """
    Register all logging middlewares on a router in correct order.

    Order is important:
    1. CorrelationIdMiddleware - generates correlation ID
    2. RequestContextMiddleware - extracts request context
    3. LoggingMiddleware - logs events
    4. MetricsMiddleware - records metrics

    Args:
        router: aiogram Router or Dispatcher.
        metrics_collector: Optional MetricsCollector for metrics.

    Example:
        >>> from saqshy.bot.middlewares.logging import register_logging_middlewares
        >>> register_logging_middlewares(dp, metrics_collector=metrics)
    """
    router.update.middleware(CorrelationIdMiddleware())
    router.update.middleware(RequestContextMiddleware())
    router.update.middleware(LoggingMiddleware())
    router.update.middleware(MetricsMiddleware(metrics_collector=metrics_collector))
