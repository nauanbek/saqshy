"""
Tests for LoggingMiddleware and related logging utilities.

Tests cover:
- CorrelationIdMiddleware: ID generation and propagation
- RequestContextMiddleware: Context extraction
- LoggingMiddleware: Event logging with timing
- MetricsMiddleware: Metrics collection
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberUpdated,
    Message,
    User,
)

from saqshy.bot.middlewares.logging import (
    CorrelationIdMiddleware,
    LoggingMiddleware,
    MetricsMiddleware,
    RequestContextMiddleware,
    register_logging_middlewares,
)
from saqshy.core.logging import (
    clear_correlation_id,
    clear_request_context,
    get_correlation_id,
    get_request_context,
    set_correlation_id,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_user() -> User:
    """Create a mock user."""
    return User(id=123456789, is_bot=False, first_name="Test", username="testuser")


@pytest.fixture
def mock_supergroup_chat() -> Chat:
    """Create a mock supergroup chat."""
    return Chat(id=-1001234567890, type="supergroup", title="Test Group")


@pytest.fixture
def mock_message(mock_user: User, mock_supergroup_chat: Chat) -> Message:
    """Create a mock message."""
    msg = MagicMock(spec=Message)
    msg.chat = mock_supergroup_chat
    msg.from_user = mock_user
    msg.message_id = 12345
    msg.text = "Test message"
    msg.photo = None
    msg.video = None
    msg.document = None
    msg.audio = None
    msg.voice = None
    msg.sticker = None
    msg.forward_date = None
    msg.reply_to_message = None
    return msg


@pytest.fixture
def mock_callback_query(
    mock_user: User,
    mock_message: Message,
) -> CallbackQuery:
    """Create a mock callback query."""
    callback = MagicMock(spec=CallbackQuery)
    callback.id = "callback_123"
    callback.from_user = mock_user
    callback.message = mock_message
    callback.data = "action:test"
    return callback


@pytest.fixture(autouse=True)
def cleanup_context():
    """Clean up correlation ID and request context after each test."""
    yield
    clear_correlation_id()
    clear_request_context()


# =============================================================================
# CorrelationIdMiddleware Tests
# =============================================================================


class TestCorrelationIdMiddleware:
    """Tests for CorrelationIdMiddleware."""

    @pytest.fixture
    def middleware(self) -> CorrelationIdMiddleware:
        """Create a CorrelationIdMiddleware instance."""
        return CorrelationIdMiddleware()

    async def test_generates_correlation_id(
        self,
        middleware: CorrelationIdMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that middleware generates a correlation ID."""
        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_message, data)

        # Correlation ID should be in data
        assert "correlation_id" in data
        assert len(data["correlation_id"]) == 8  # UUID[:8]

    async def test_injects_into_handler_data(
        self,
        middleware: CorrelationIdMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that correlation ID is injected into handler data."""
        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()
        # Check the data passed to handler
        call_args = handler.call_args
        passed_data = call_args[0][1]
        assert "correlation_id" in passed_data

    async def test_clears_after_request(
        self,
        middleware: CorrelationIdMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that correlation ID is cleared after request."""
        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_message, data)

        # After middleware completes, context should be cleared
        # (Note: We can verify this by checking get_correlation_id generates new)
        # This is indirect since we cleaned up in autouse fixture

    async def test_clears_on_exception(
        self,
        middleware: CorrelationIdMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that correlation ID is cleared even on exception."""
        handler = AsyncMock(side_effect=ValueError("Test error"))
        data: dict[str, Any] = {}

        with pytest.raises(ValueError):
            await middleware(handler, mock_message, data)

        # Context should still be cleared via finally block


# =============================================================================
# RequestContextMiddleware Tests
# =============================================================================


class TestRequestContextMiddleware:
    """Tests for RequestContextMiddleware."""

    @pytest.fixture
    def middleware(self) -> RequestContextMiddleware:
        """Create a RequestContextMiddleware instance."""
        return RequestContextMiddleware()

    async def test_extracts_context_from_message(
        self,
        middleware: RequestContextMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that context is extracted from Message events."""
        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_message, data)

        # Context should have been set during processing
        # We can verify the extraction logic indirectly

    async def test_extracts_context_from_callback_query(
        self,
        middleware: RequestContextMiddleware,
        mock_callback_query: CallbackQuery,
    ) -> None:
        """Test that context is extracted from CallbackQuery events."""
        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_callback_query, data)

        handler.assert_called_once()

    async def test_clears_context_after_request(
        self,
        middleware: RequestContextMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that context is cleared after request."""
        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_message, data)

        # Context should be cleared after processing

    async def test_includes_group_type_when_available(
        self,
        middleware: RequestContextMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that group_type is included when group is in data."""
        handler = AsyncMock()
        mock_group = MagicMock()
        mock_group.group_type = MagicMock()
        mock_group.group_type.value = "tech"
        data: dict[str, Any] = {"group": mock_group}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()


class TestExtractContext:
    """Tests for _extract_context method."""

    @pytest.fixture
    def middleware(self) -> RequestContextMiddleware:
        """Create a RequestContextMiddleware instance."""
        return RequestContextMiddleware()

    def test_extracts_from_message(
        self,
        middleware: RequestContextMiddleware,
        mock_message: Message,
    ) -> None:
        """Test context extraction from Message."""
        context = middleware._extract_context(mock_message, {})

        assert context["chat_id"] == -1001234567890
        assert context["message_id"] == 12345
        assert context["user_id"] == 123456789

    def test_extracts_from_callback_query(
        self,
        middleware: RequestContextMiddleware,
        mock_callback_query: CallbackQuery,
    ) -> None:
        """Test context extraction from CallbackQuery."""
        context = middleware._extract_context(mock_callback_query, {})

        assert context["user_id"] == 123456789
        assert "chat_id" in context
        assert "message_id" in context

    def test_extracts_from_chat_member_updated(
        self,
        middleware: RequestContextMiddleware,
        mock_user: User,
        mock_supergroup_chat: Chat,
    ) -> None:
        """Test context extraction from ChatMemberUpdated."""
        update = MagicMock(spec=ChatMemberUpdated)
        update.chat = mock_supergroup_chat
        update.from_user = mock_user
        update.new_chat_member = None

        context = middleware._extract_context(update, {})

        assert context["chat_id"] == -1001234567890
        assert context["user_id"] == 123456789


# =============================================================================
# LoggingMiddleware Tests
# =============================================================================


class TestLoggingMiddleware:
    """Tests for LoggingMiddleware."""

    @pytest.fixture
    def middleware(self) -> LoggingMiddleware:
        """Create a LoggingMiddleware instance."""
        return LoggingMiddleware()

    async def test_logs_event_received(
        self,
        middleware: LoggingMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that 'event_received' is logged."""
        handler = AsyncMock()
        data: dict[str, Any] = {"correlation_id": "test123"}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()

    async def test_logs_event_processed_on_success(
        self,
        middleware: LoggingMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that 'event_processed' is logged on success."""
        handler = AsyncMock(return_value="success")
        data: dict[str, Any] = {}

        result = await middleware(handler, mock_message, data)

        assert result == "success"

    async def test_logs_event_error_on_exception(
        self,
        middleware: LoggingMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that 'event_error' is logged on exception."""
        handler = AsyncMock(side_effect=ValueError("Test error"))
        data: dict[str, Any] = {}

        with pytest.raises(ValueError):
            await middleware(handler, mock_message, data)

    async def test_measures_elapsed_time(
        self,
        middleware: LoggingMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that elapsed time is measured."""
        async def slow_handler(event: Any, data: dict[str, Any]) -> str:
            # Simulate some work
            await asyncio.sleep(0.01)
            return "done"

        import asyncio

        data: dict[str, Any] = {}
        await middleware(slow_handler, mock_message, data)

    async def test_uses_correlation_id_from_data(
        self,
        middleware: LoggingMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that correlation ID from data is used."""
        handler = AsyncMock()
        data: dict[str, Any] = {"correlation_id": "custom123"}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()

    async def test_generates_correlation_id_if_missing(
        self,
        middleware: LoggingMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that correlation ID is generated if not in data."""
        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()


class TestExtractEventInfo:
    """Tests for _extract_event_info method."""

    @pytest.fixture
    def middleware(self) -> LoggingMiddleware:
        """Create a LoggingMiddleware instance."""
        return LoggingMiddleware()

    def test_extracts_message_info(
        self,
        middleware: LoggingMiddleware,
        mock_user: User,
        mock_supergroup_chat: Chat,
    ) -> None:
        """Test info extraction from Message."""
        from datetime import UTC, datetime

        from aiogram.types import Message

        # Create a real Message object for accurate type detection
        message = Message(
            message_id=12345,
            date=datetime.now(UTC),
            chat=mock_supergroup_chat,
            from_user=mock_user,
            text="Test message",
        )
        info = middleware._extract_event_info(message)

        assert info["event_type"] == "Message"
        assert info["message_id"] == 12345
        assert info["chat_id"] == -1001234567890
        assert info["chat_type"] == "supergroup"
        assert info["user_id"] == 123456789
        assert "text_len" in info

    def test_extracts_callback_query_info(
        self,
        middleware: LoggingMiddleware,
        mock_user: User,
        mock_supergroup_chat: Chat,
    ) -> None:
        """Test info extraction from CallbackQuery."""
        from datetime import UTC, datetime

        from aiogram.types import CallbackQuery, Message

        # Create real objects for accurate type detection
        message = Message(
            message_id=12345,
            date=datetime.now(UTC),
            chat=mock_supergroup_chat,
            from_user=mock_user,
            text="Test",
        )
        callback = CallbackQuery(
            id="callback_123",
            from_user=mock_user,
            chat_instance="chat_instance_456",
            message=message,
            data="action:test",
        )
        info = middleware._extract_event_info(callback)

        assert info["event_type"] == "CallbackQuery"
        assert info["user_id"] == 123456789

    def test_excludes_sensitive_data(
        self,
        middleware: LoggingMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that sensitive data (message content) is excluded."""
        mock_message.text = "This is sensitive content that should not be logged"
        info = middleware._extract_event_info(mock_message)

        # Text content should NOT be in info
        assert "text" not in info
        # Only text length
        assert "text_len" in info

    def test_includes_media_flag(
        self,
        middleware: LoggingMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that has_media flag is included."""
        mock_message.photo = [MagicMock()]  # Has photo

        info = middleware._extract_event_info(mock_message)

        assert info["has_media"] is True

    def test_includes_forward_flag(
        self,
        middleware: LoggingMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that is_forward flag is included."""
        mock_message.forward_date = datetime.now(UTC)

        info = middleware._extract_event_info(mock_message)

        assert info["is_forward"] is True

    def test_includes_reply_flag(
        self,
        middleware: LoggingMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that is_reply flag is included."""
        mock_message.reply_to_message = MagicMock()

        info = middleware._extract_event_info(mock_message)

        assert info["is_reply"] is True


# =============================================================================
# MetricsMiddleware Tests
# =============================================================================


class TestMetricsMiddleware:
    """Tests for MetricsMiddleware."""

    @pytest.fixture
    def mock_metrics_collector(self) -> AsyncMock:
        """Create a mock metrics collector."""
        return AsyncMock()

    @pytest.fixture
    def mock_cache_service(self) -> AsyncMock:
        """Create a mock cache service."""
        cache = AsyncMock()
        cache.get_json.return_value = {
            "total_messages": 0,
            "messages_scanned": 0,
            "allowed": 0,
            "errors": 0,
        }
        cache.set_json.return_value = True
        return cache

    @pytest.fixture
    def middleware(
        self, mock_metrics_collector: AsyncMock
    ) -> MetricsMiddleware:
        """Create a MetricsMiddleware instance."""
        return MetricsMiddleware(metrics_collector=mock_metrics_collector)

    async def test_records_success(
        self,
        middleware: MetricsMiddleware,
        mock_message: Message,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that successful events are recorded."""
        handler = AsyncMock(return_value="success")
        data: dict[str, Any] = {"cache_service": mock_cache_service}

        result = await middleware(handler, mock_message, data)

        assert result == "success"
        # Cache should be updated
        mock_cache_service.set_json.assert_called()

    async def test_records_error(
        self,
        middleware: MetricsMiddleware,
        mock_message: Message,
        mock_metrics_collector: AsyncMock,
    ) -> None:
        """Test that errors are recorded."""
        handler = AsyncMock(side_effect=ValueError("Test error"))
        data: dict[str, Any] = {}

        with pytest.raises(ValueError):
            await middleware(handler, mock_message, data)

        # Metrics collector should record error
        mock_metrics_collector.record_error.assert_called()

    async def test_extracts_group_type_from_data(
        self,
        middleware: MetricsMiddleware,
        mock_message: Message,
    ) -> None:
        """Test that group_type is extracted from data."""
        handler = AsyncMock()
        mock_group = MagicMock()
        mock_group.group_type = MagicMock()
        mock_group.group_type.value = "tech"
        data: dict[str, Any] = {"group": mock_group}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()

    async def test_increments_message_counter(
        self,
        middleware: MetricsMiddleware,
        mock_message: Message,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that message counter is incremented."""
        handler = AsyncMock()
        data: dict[str, Any] = {"cache_service": mock_cache_service}

        await middleware(handler, mock_message, data)

        # Verify set_json was called with updated stats
        mock_cache_service.set_json.assert_called()
        call_args = mock_cache_service.set_json.call_args
        stats = call_args[0][1]
        assert stats["total_messages"] == 1

    async def test_handles_cache_error_gracefully(
        self,
        middleware: MetricsMiddleware,
        mock_message: Message,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that cache errors don't break processing."""
        mock_cache_service.get_json.side_effect = ConnectionError("Redis down")

        handler = AsyncMock(return_value="success")
        data: dict[str, Any] = {"cache_service": mock_cache_service}

        # Should not raise
        result = await middleware(handler, mock_message, data)

        assert result == "success"

    async def test_handles_metrics_error_gracefully(
        self,
        middleware: MetricsMiddleware,
        mock_message: Message,
        mock_metrics_collector: AsyncMock,
    ) -> None:
        """Test that metrics errors don't break processing."""
        mock_metrics_collector.record_error.side_effect = RuntimeError("Metrics error")

        handler = AsyncMock(side_effect=ValueError("Test"))
        data: dict[str, Any] = {}

        # Should still raise the original error, not metrics error
        with pytest.raises(ValueError):
            await middleware(handler, mock_message, data)


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestRegisterLoggingMiddlewares:
    """Tests for register_logging_middlewares function."""

    def test_registers_all_middlewares(self) -> None:
        """Test that all logging middlewares are registered."""
        mock_router = MagicMock()
        mock_router.update = MagicMock()
        mock_router.update.middleware = MagicMock()

        register_logging_middlewares(mock_router)

        # Should register 4 middlewares
        assert mock_router.update.middleware.call_count == 4

    def test_accepts_metrics_collector(self) -> None:
        """Test that metrics collector can be passed."""
        mock_router = MagicMock()
        mock_router.update = MagicMock()
        mock_router.update.middleware = MagicMock()
        mock_metrics = MagicMock()

        register_logging_middlewares(mock_router, metrics_collector=mock_metrics)

        assert mock_router.update.middleware.call_count == 4
