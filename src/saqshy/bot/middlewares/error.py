"""
SAQSHY Error Handling Middleware

Catches and handles errors gracefully.
Ensures exceptions never propagate to Telegram.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import ErrorEvent, TelegramObject

logger = structlog.get_logger(__name__)


class ErrorMiddleware(BaseMiddleware):
    """
    Error handling middleware (outer middleware).

    CRITICAL: This middleware MUST be registered as an outer middleware
    to catch all errors from inner middlewares and handlers.

    Responsibilities:
    - Catch ALL unhandled exceptions
    - Log errors with full context
    - Never let exceptions propagate to Telegram
    - Return gracefully on all errors
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Handle errors in the middleware chain.

        NEVER lets exceptions propagate. All errors are caught and logged.

        Args:
            handler: Next handler in chain.
            event: Incoming event.
            data: Handler context data.

        Returns:
            Handler result or None on error.
        """
        correlation_id = data.get("correlation_id", "unknown")

        try:
            return await handler(event, data)

        except TelegramRetryAfter as e:
            # Rate limited by Telegram - log and wait (don't retry)
            logger.warning(
                "telegram_retry_after",
                retry_after=e.retry_after,
                correlation_id=correlation_id,
            )
            return None

        except TelegramBadRequest as e:
            # Bad request (message deleted, user not found, etc.)
            # These are expected errors, log at warning level
            logger.warning(
                "telegram_bad_request",
                error=str(e),
                correlation_id=correlation_id,
            )
            return None

        except TelegramForbiddenError as e:
            # Bot was blocked or kicked from group
            logger.warning(
                "telegram_forbidden",
                error=str(e),
                correlation_id=correlation_id,
            )
            return None

        except TelegramNetworkError as e:
            # Network error - could retry but for simplicity just log
            logger.error(
                "telegram_network_error",
                error=str(e),
                correlation_id=correlation_id,
            )
            return None

        except TelegramAPIError as e:
            # Generic Telegram API error
            logger.error(
                "telegram_api_error",
                error=str(e),
                error_type=type(e).__name__,
                correlation_id=correlation_id,
            )
            return None

        except TimeoutError:
            # Timeout waiting for something
            logger.warning(
                "timeout_error",
                correlation_id=correlation_id,
            )
            return None

        except asyncio.CancelledError:
            # Task was cancelled - re-raise as this is control flow
            raise

        except Exception as e:
            # Catch-all for unexpected errors
            # Log with full stack trace
            logger.exception(
                "unhandled_error",
                error=str(e),
                error_type=type(e).__name__,
                correlation_id=correlation_id,
            )
            # Never propagate to Telegram
            return None


async def handle_error(event: ErrorEvent) -> None:
    """
    Global error handler for the dispatcher.

    This is the last line of defense for unhandled errors.

    Args:
        event: Error event with exception and update.
    """
    exception = event.exception
    update = event.update

    logger.error(
        "dispatcher_error",
        error=str(exception),
        error_type=type(exception).__name__,
        update_id=update.update_id if update else None,
    )


class CircuitBreaker:
    """
    Circuit breaker for external services.

    Prevents cascading failures when external services are down.
    Used for LLM, SpamDB, and other external dependencies.

    States:
    - closed: Normal operation, requests pass through
    - open: Circuit is tripped, requests fail fast
    - half-open: Testing if service recovered
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
    ):
        """
        Initialize circuit breaker.

        Args:
            name: Name of the service for logging.
            failure_threshold: Failures before opening circuit.
            recovery_timeout: Seconds before attempting recovery.
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time: float = 0
        self.state = "closed"

    async def call(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Async function to call.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Function result.

        Raises:
            CircuitBreakerOpen: If circuit is open and not recovered.
        """
        # Check if circuit should transition from open to half-open
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                logger.info(
                    "circuit_breaker_half_open",
                    service=self.name,
                )
                self.state = "half-open"
            else:
                raise CircuitBreakerOpen(f"Circuit breaker for {self.name} is open")

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result

        except Exception as e:
            self._on_failure(e)
            raise

    def _on_success(self) -> None:
        """Handle successful call."""
        if self.state == "half-open":
            logger.info(
                "circuit_breaker_closed",
                service=self.name,
            )
        self.failures = 0
        self.state = "closed"

    def _on_failure(self, error: Exception) -> None:
        """Handle failed call."""
        self.failures += 1
        self.last_failure_time = time.time()

        if self.failures >= self.failure_threshold:
            if self.state != "open":
                logger.warning(
                    "circuit_breaker_opened",
                    service=self.name,
                    failures=self.failures,
                    error=str(error),
                )
            self.state = "open"

    @property
    def is_open(self) -> bool:
        """Check if circuit is open."""
        return self.state == "open"


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open."""

    pass


class ServiceDegradation:
    """
    Service degradation manager.

    Tracks which services are degraded and provides fallback behavior.
    """

    def __init__(self):
        """Initialize degradation manager."""
        self.degraded_services: dict[str, float] = {}
        self.circuit_breakers: dict[str, CircuitBreaker] = {}

    def register_circuit_breaker(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
    ) -> CircuitBreaker:
        """
        Register a circuit breaker for a service.

        Args:
            name: Service name.
            failure_threshold: Failures before opening.
            recovery_timeout: Recovery timeout in seconds.

        Returns:
            CircuitBreaker instance.
        """
        cb = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
        self.circuit_breakers[name] = cb
        return cb

    def mark_degraded(self, service: str, duration: float = 60.0) -> None:
        """
        Mark a service as degraded.

        Args:
            service: Service name.
            duration: How long to consider degraded (seconds).
        """
        self.degraded_services[service] = time.time() + duration
        logger.warning(
            "service_marked_degraded",
            service=service,
            duration=duration,
        )

    def is_degraded(self, service: str) -> bool:
        """
        Check if a service is degraded.

        Args:
            service: Service name.

        Returns:
            True if service is degraded.
        """
        if service not in self.degraded_services:
            return False

        expiry = self.degraded_services[service]
        if time.time() > expiry:
            del self.degraded_services[service]
            return False

        return True

    def get_status(self) -> dict[str, Any]:
        """
        Get status of all tracked services.

        Returns:
            Dict with service statuses.
        """
        status = {}

        for name, cb in self.circuit_breakers.items():
            status[name] = {
                "circuit_state": cb.state,
                "failures": cb.failures,
                "degraded": self.is_degraded(name),
            }

        return status


# Global service degradation manager
degradation_manager = ServiceDegradation()


def get_degradation_manager() -> ServiceDegradation:
    """Get the global degradation manager."""
    return degradation_manager
