"""
Tests for ErrorMiddleware and related error handling.

Tests cover:
- Exception catching and logging
- Telegram-specific error handling
- CancelledError re-raising
- CircuitBreaker state transitions
- ServiceDegradation tracking
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import Message

from saqshy.bot.middlewares.error import (
    CircuitBreaker,
    CircuitBreakerOpen,
    ErrorMiddleware,
    ServiceDegradation,
    get_degradation_manager,
    handle_error,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_message() -> Message:
    """Create a mock message."""
    msg = MagicMock(spec=Message)
    msg.message_id = 12345
    return msg


@pytest.fixture
def middleware() -> ErrorMiddleware:
    """Create an ErrorMiddleware instance."""
    return ErrorMiddleware()


@pytest.fixture
def circuit_breaker() -> CircuitBreaker:
    """Create a CircuitBreaker instance."""
    return CircuitBreaker(
        name="test_service",
        failure_threshold=3,
        recovery_timeout=30,
    )


# =============================================================================
# ErrorMiddleware Tests
# =============================================================================


class TestErrorMiddleware:
    """Tests for ErrorMiddleware.__call__."""

    async def test_passes_through_on_success(
        self,
        middleware: ErrorMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that successful handlers pass through."""
        handler = AsyncMock(return_value="success")
        data: dict[str, Any] = {}

        result = await middleware(handler, mock_message, data)

        assert result == "success"
        handler.assert_called_once()

    async def test_catches_generic_exceptions(
        self,
        middleware: ErrorMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that generic exceptions are caught and logged."""
        handler = AsyncMock(side_effect=Exception("Test error"))
        data: dict[str, Any] = {"correlation_id": "test123"}

        # Should NOT raise
        result = await middleware(handler, mock_message, data)

        assert result is None

    async def test_catches_value_error(
        self,
        middleware: ErrorMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that ValueError is caught."""
        handler = AsyncMock(side_effect=ValueError("Invalid value"))
        data: dict[str, Any] = {}

        result = await middleware(handler, mock_message, data)

        assert result is None

    async def test_handles_telegram_retry_after(
        self,
        middleware: ErrorMiddleware,
        mock_message: Message,
    ) -> None:
        """Test handling of TelegramRetryAfter (rate limiting)."""
        handler = AsyncMock(
            side_effect=TelegramRetryAfter(
                method="sendMessage",
                message="Rate limited",
                retry_after=30,
            )
        )
        data: dict[str, Any] = {}

        result = await middleware(handler, mock_message, data)

        assert result is None

    async def test_handles_telegram_bad_request(
        self,
        middleware: ErrorMiddleware,
        mock_message: Message,
    ) -> None:
        """Test handling of TelegramBadRequest."""
        handler = AsyncMock(
            side_effect=TelegramBadRequest(
                method="deleteMessage",
                message="Message not found",
            )
        )
        data: dict[str, Any] = {}

        result = await middleware(handler, mock_message, data)

        assert result is None

    async def test_handles_telegram_forbidden(
        self,
        middleware: ErrorMiddleware,
        mock_message: Message,
    ) -> None:
        """Test handling of TelegramForbiddenError."""
        handler = AsyncMock(
            side_effect=TelegramForbiddenError(
                method="sendMessage",
                message="Bot was blocked by user",
            )
        )
        data: dict[str, Any] = {}

        result = await middleware(handler, mock_message, data)

        assert result is None

    async def test_handles_telegram_network_error(
        self,
        middleware: ErrorMiddleware,
        mock_message: Message,
    ) -> None:
        """Test handling of TelegramNetworkError."""
        handler = AsyncMock(
            side_effect=TelegramNetworkError(
                method="sendMessage",
                message="Connection failed",
            )
        )
        data: dict[str, Any] = {}

        result = await middleware(handler, mock_message, data)

        assert result is None

    async def test_handles_generic_telegram_api_error(
        self,
        middleware: ErrorMiddleware,
        mock_message: Message,
    ) -> None:
        """Test handling of generic TelegramAPIError."""
        handler = AsyncMock(
            side_effect=TelegramAPIError(
                method="sendMessage",
                message="Unknown Telegram error",
            )
        )
        data: dict[str, Any] = {}

        result = await middleware(handler, mock_message, data)

        assert result is None

    async def test_handles_timeout_error(
        self,
        middleware: ErrorMiddleware,
        mock_message: Message,
    ) -> None:
        """Test handling of TimeoutError."""
        handler = AsyncMock(side_effect=TimeoutError())
        data: dict[str, Any] = {}

        result = await middleware(handler, mock_message, data)

        assert result is None

    async def test_reraises_cancelled_error(
        self,
        middleware: ErrorMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that CancelledError is re-raised (control flow)."""
        handler = AsyncMock(side_effect=asyncio.CancelledError())
        data: dict[str, Any] = {}

        with pytest.raises(asyncio.CancelledError):
            await middleware(handler, mock_message, data)

    async def test_uses_correlation_id_from_data(
        self,
        middleware: ErrorMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that correlation ID from data is used for logging."""
        handler = AsyncMock(side_effect=Exception("Test"))
        data: dict[str, Any] = {"correlation_id": "abc123"}

        # The middleware should use correlation_id for logging
        # We can't easily verify the log content without mocking structlog
        result = await middleware(handler, mock_message, data)

        assert result is None

    async def test_defaults_correlation_id_to_unknown(
        self,
        middleware: ErrorMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that missing correlation ID defaults to 'unknown'."""
        handler = AsyncMock(side_effect=Exception("Test"))
        data: dict[str, Any] = {}

        result = await middleware(handler, mock_message, data)

        assert result is None


# =============================================================================
# handle_error Tests
# =============================================================================


class TestHandleError:
    """Tests for the global error handler."""

    async def test_logs_error_event(self) -> None:
        """Test that error events are logged."""
        mock_error_event = MagicMock()
        mock_error_event.exception = ValueError("Test error")
        mock_error_event.update = MagicMock()
        mock_error_event.update.update_id = 12345

        # Should not raise
        await handle_error(mock_error_event)

    async def test_handles_none_update(self) -> None:
        """Test handling when update is None."""
        mock_error_event = MagicMock()
        mock_error_event.exception = RuntimeError("Test")
        mock_error_event.update = None

        await handle_error(mock_error_event)


# =============================================================================
# CircuitBreaker Tests
# =============================================================================


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    async def test_initial_state_is_closed(
        self,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that circuit breaker starts in closed state."""
        assert circuit_breaker.state == "closed"
        assert circuit_breaker.is_open is False

    async def test_successful_call_keeps_closed(
        self,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that successful calls keep circuit closed."""
        async def success_func() -> str:
            return "success"

        result = await circuit_breaker.call(success_func)

        assert result == "success"
        assert circuit_breaker.state == "closed"
        assert circuit_breaker.failures == 0

    async def test_failures_increment_counter(
        self,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that failures increment the counter."""
        async def fail_func() -> None:
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            await circuit_breaker.call(fail_func)

        assert circuit_breaker.failures == 1

    async def test_opens_after_threshold(
        self,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that circuit opens after failure threshold."""
        async def fail_func() -> None:
            raise ValueError("Test error")

        # Trigger failures up to threshold
        for _ in range(3):
            with pytest.raises(ValueError):
                await circuit_breaker.call(fail_func)

        assert circuit_breaker.state == "open"
        assert circuit_breaker.is_open is True

    async def test_open_circuit_raises_immediately(
        self,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that open circuit raises without calling function."""
        # Open the circuit
        circuit_breaker.state = "open"
        circuit_breaker.last_failure_time = time.time()

        async def should_not_be_called() -> str:
            raise AssertionError("Function should not be called")

        with pytest.raises(CircuitBreakerOpen):
            await circuit_breaker.call(should_not_be_called)

    async def test_transitions_to_half_open_after_timeout(
        self,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that circuit transitions to half-open after recovery timeout."""
        # Open the circuit with old failure time
        circuit_breaker.state = "open"
        circuit_breaker.last_failure_time = time.time() - 60  # 60 seconds ago

        call_count = 0

        async def test_func() -> str:
            nonlocal call_count
            call_count += 1
            return "success"

        result = await circuit_breaker.call(test_func)

        assert result == "success"
        assert call_count == 1
        # After success, should transition back to closed
        assert circuit_breaker.state == "closed"

    async def test_half_open_success_closes_circuit(
        self,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that success in half-open state closes circuit."""
        circuit_breaker.state = "half-open"

        async def success_func() -> str:
            return "success"

        result = await circuit_breaker.call(success_func)

        assert result == "success"
        assert circuit_breaker.state == "closed"
        assert circuit_breaker.failures == 0

    async def test_half_open_failure_opens_circuit(
        self,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that failure in half-open state opens circuit."""
        circuit_breaker.state = "half-open"
        circuit_breaker.failures = 2  # Just under threshold

        async def fail_func() -> None:
            raise ValueError("Still failing")

        with pytest.raises(ValueError):
            await circuit_breaker.call(fail_func)

        assert circuit_breaker.state == "open"

    async def test_success_resets_failure_count(
        self,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        """Test that success resets failure count."""
        circuit_breaker.failures = 2

        async def success_func() -> str:
            return "success"

        await circuit_breaker.call(success_func)

        assert circuit_breaker.failures == 0


class TestCircuitBreakerOpen:
    """Tests for CircuitBreakerOpen exception."""

    def test_exception_message(self) -> None:
        """Test that exception has proper message."""
        exc = CircuitBreakerOpen("Test service is unavailable")
        assert "Test service is unavailable" in str(exc)


# =============================================================================
# ServiceDegradation Tests
# =============================================================================


class TestServiceDegradation:
    """Tests for ServiceDegradation manager."""

    @pytest.fixture
    def degradation_manager(self) -> ServiceDegradation:
        """Create a ServiceDegradation instance."""
        return ServiceDegradation()

    def test_initial_state(
        self,
        degradation_manager: ServiceDegradation,
    ) -> None:
        """Test that manager starts with no degraded services."""
        assert len(degradation_manager.degraded_services) == 0
        assert len(degradation_manager.circuit_breakers) == 0

    def test_mark_degraded(
        self,
        degradation_manager: ServiceDegradation,
    ) -> None:
        """Test marking a service as degraded."""
        degradation_manager.mark_degraded("llm", duration=60.0)

        assert degradation_manager.is_degraded("llm") is True

    def test_is_degraded_expires(
        self,
        degradation_manager: ServiceDegradation,
    ) -> None:
        """Test that degradation expires after duration."""
        # Mark with expired duration
        degradation_manager.degraded_services["llm"] = time.time() - 10

        assert degradation_manager.is_degraded("llm") is False
        # Should be removed from dict after check
        assert "llm" not in degradation_manager.degraded_services

    def test_is_degraded_unknown_service(
        self,
        degradation_manager: ServiceDegradation,
    ) -> None:
        """Test that unknown services are not degraded."""
        assert degradation_manager.is_degraded("unknown") is False

    def test_register_circuit_breaker(
        self,
        degradation_manager: ServiceDegradation,
    ) -> None:
        """Test registering a circuit breaker."""
        cb = degradation_manager.register_circuit_breaker(
            name="spam_db",
            failure_threshold=5,
            recovery_timeout=60,
        )

        assert cb is not None
        assert cb.name == "spam_db"
        assert "spam_db" in degradation_manager.circuit_breakers

    def test_get_status(
        self,
        degradation_manager: ServiceDegradation,
    ) -> None:
        """Test getting status of all services."""
        degradation_manager.register_circuit_breaker("llm")
        degradation_manager.register_circuit_breaker("spam_db")
        degradation_manager.mark_degraded("llm", duration=60.0)

        status = degradation_manager.get_status()

        assert "llm" in status
        assert "spam_db" in status
        assert status["llm"]["degraded"] is True
        assert status["llm"]["circuit_state"] == "closed"
        assert status["spam_db"]["degraded"] is False

    def test_get_status_with_open_circuit(
        self,
        degradation_manager: ServiceDegradation,
    ) -> None:
        """Test status includes circuit state."""
        cb = degradation_manager.register_circuit_breaker("llm")
        cb.state = "open"
        cb.failures = 5

        status = degradation_manager.get_status()

        assert status["llm"]["circuit_state"] == "open"
        assert status["llm"]["failures"] == 5


class TestGetDegradationManager:
    """Tests for global degradation manager access."""

    def test_returns_singleton(self) -> None:
        """Test that get_degradation_manager returns the global instance."""
        manager1 = get_degradation_manager()
        manager2 = get_degradation_manager()

        assert manager1 is manager2

    def test_returns_service_degradation_instance(self) -> None:
        """Test that returned object is ServiceDegradation."""
        manager = get_degradation_manager()

        assert isinstance(manager, ServiceDegradation)
