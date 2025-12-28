"""
Tests for ConfigMiddleware.

Tests cover:
- Configuration injection into handler data
- Multiple config values
- Handler receiving injected values
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, Message, User

from saqshy.bot.middlewares.config import ConfigMiddleware


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
    return msg


# =============================================================================
# ConfigMiddleware Tests
# =============================================================================


class TestConfigMiddleware:
    """Tests for ConfigMiddleware."""

    async def test_injects_single_config_value(
        self,
        mock_message: Message,
    ) -> None:
        """Test that a single config value is injected."""
        middleware = ConfigMiddleware(mini_app_url="https://miniapp.example.com")
        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_message, data)

        assert data["mini_app_url"] == "https://miniapp.example.com"
        handler.assert_called_once()

    async def test_injects_multiple_config_values(
        self,
        mock_message: Message,
    ) -> None:
        """Test that multiple config values are injected."""
        middleware = ConfigMiddleware(
            mini_app_url="https://miniapp.example.com",
            bot_username="saqshy_bot",
            version="1.0.0",
            debug=True,
        )
        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_message, data)

        assert data["mini_app_url"] == "https://miniapp.example.com"
        assert data["bot_username"] == "saqshy_bot"
        assert data["version"] == "1.0.0"
        assert data["debug"] is True

    async def test_handler_receives_config_values(
        self,
        mock_message: Message,
    ) -> None:
        """Test that handler receives the config values in data."""
        middleware = ConfigMiddleware(test_value="hello")

        captured_data: dict[str, Any] = {}

        async def capturing_handler(event: Any, data: dict[str, Any]) -> str:
            captured_data.update(data)
            return "done"

        data: dict[str, Any] = {}
        await middleware(capturing_handler, mock_message, data)

        assert captured_data["test_value"] == "hello"

    async def test_does_not_overwrite_existing_data(
        self,
        mock_message: Message,
    ) -> None:
        """Test that existing data keys are overwritten by config."""
        middleware = ConfigMiddleware(existing_key="new_value")
        handler = AsyncMock()
        data: dict[str, Any] = {"existing_key": "old_value"}

        await middleware(handler, mock_message, data)

        # Config should overwrite existing value
        assert data["existing_key"] == "new_value"

    async def test_preserves_existing_data(
        self,
        mock_message: Message,
    ) -> None:
        """Test that existing data keys not in config are preserved."""
        middleware = ConfigMiddleware(new_key="new_value")
        handler = AsyncMock()
        data: dict[str, Any] = {"existing_key": "preserved_value"}

        await middleware(handler, mock_message, data)

        assert data["existing_key"] == "preserved_value"
        assert data["new_key"] == "new_value"

    async def test_returns_handler_result(
        self,
        mock_message: Message,
    ) -> None:
        """Test that middleware returns the handler's result."""
        middleware = ConfigMiddleware(test="value")
        handler = AsyncMock(return_value="handler_result")
        data: dict[str, Any] = {}

        result = await middleware(handler, mock_message, data)

        assert result == "handler_result"

    async def test_propagates_handler_exception(
        self,
        mock_message: Message,
    ) -> None:
        """Test that handler exceptions are propagated."""
        middleware = ConfigMiddleware(test="value")
        handler = AsyncMock(side_effect=ValueError("Test error"))
        data: dict[str, Any] = {}

        with pytest.raises(ValueError, match="Test error"):
            await middleware(handler, mock_message, data)

    async def test_empty_config(
        self,
        mock_message: Message,
    ) -> None:
        """Test middleware with no config values."""
        middleware = ConfigMiddleware()
        handler = AsyncMock()
        data: dict[str, Any] = {"preserved": "value"}

        await middleware(handler, mock_message, data)

        # Original data should be preserved
        assert data["preserved"] == "value"
        handler.assert_called_once()

    async def test_works_with_different_event_types(
        self,
    ) -> None:
        """Test that middleware works with any event type."""
        from aiogram.types import CallbackQuery

        middleware = ConfigMiddleware(config_key="config_value")
        handler = AsyncMock()

        # Create a mock CallbackQuery
        callback = MagicMock(spec=CallbackQuery)
        data: dict[str, Any] = {}

        await middleware(handler, callback, data)

        assert data["config_key"] == "config_value"
        handler.assert_called_once()

    async def test_config_values_are_accessible_as_typed(
        self,
        mock_message: Message,
    ) -> None:
        """Test that config values maintain their types."""
        middleware = ConfigMiddleware(
            string_value="text",
            int_value=42,
            float_value=3.14,
            bool_value=True,
            list_value=[1, 2, 3],
            dict_value={"nested": "value"},
            none_value=None,
        )
        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_message, data)

        assert isinstance(data["string_value"], str)
        assert isinstance(data["int_value"], int)
        assert isinstance(data["float_value"], float)
        assert isinstance(data["bool_value"], bool)
        assert isinstance(data["list_value"], list)
        assert isinstance(data["dict_value"], dict)
        assert data["none_value"] is None


class TestConfigMiddlewareIntegration:
    """Integration tests for ConfigMiddleware."""

    async def test_config_available_in_handler_params(
        self,
        mock_message: Message,
    ) -> None:
        """Test simulating how config would be used as handler param."""
        middleware = ConfigMiddleware(mini_app_url="https://app.example.com")

        received_url: str | None = None

        async def handler_with_params(
            event: Message,
            data: dict[str, Any],
        ) -> str:
            nonlocal received_url
            # In real handlers, mini_app_url would be injected as a parameter
            received_url = data.get("mini_app_url")
            return "handled"

        data: dict[str, Any] = {}
        await middleware(handler_with_params, mock_message, data)

        assert received_url == "https://app.example.com"

    async def test_multiple_middlewares_chain(
        self,
        mock_message: Message,
    ) -> None:
        """Test that config middleware works in a chain."""
        # First middleware adds some config
        config_middleware = ConfigMiddleware(
            app_url="https://app.example.com",
        )

        # Simulate another middleware that might also modify data
        async def next_middleware(
            handler: Any,
            event: Any,
            data: dict[str, Any],
        ) -> Any:
            data["added_by_next"] = True
            return await handler(event, data)

        final_data: dict[str, Any] = {}

        async def final_handler(event: Any, data: dict[str, Any]) -> str:
            final_data.update(data)
            return "done"

        # Run config middleware, then next middleware, then handler
        async def chained_handler(event: Any, data: dict[str, Any]) -> Any:
            return await next_middleware(final_handler, event, data)

        data: dict[str, Any] = {}
        await config_middleware(chained_handler, mock_message, data)

        assert final_data["app_url"] == "https://app.example.com"
        assert final_data["added_by_next"] is True
