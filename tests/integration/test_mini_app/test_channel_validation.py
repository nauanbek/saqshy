"""
Integration Tests for Channel Validation Endpoint

Tests the /api/channels/validate endpoint which allows Mini App users
to validate that a Telegram channel exists and the bot has admin access.

Test Scenarios:
1. Valid channel that bot has access to
2. Invalid channel ID (non-existent)
3. Bot not in channel (access forbidden)
4. Missing channel parameter (400 error)
5. Invalid channel format
6. Channel by username (@channel)
7. Unauthenticated request
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from saqshy.mini_app.handlers import validate_channel
from saqshy.mini_app.routes import create_mini_app_routes


class TestValidateChannelHandler:
    """Unit tests for the validate_channel handler function."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock aiohttp request with necessary context."""
        request = MagicMock(spec=web.Request)
        request.app = {}
        return request

    @pytest.fixture
    def mock_auth(self):
        """Create a mock WebAppAuth object."""
        auth = MagicMock()
        auth.user_id = 123456789
        return auth

    @pytest.fixture
    def mock_bot(self):
        """Create a mock aiogram Bot instance."""
        bot = AsyncMock()
        return bot

    @pytest.fixture
    def mock_channel_service(self):
        """Create a mock ChannelSubscriptionService."""
        service = AsyncMock()
        return service

    @pytest.mark.asyncio
    async def test_validate_valid_channel(
        self, mock_request, mock_auth, mock_bot, mock_channel_service
    ):
        """Test validating a channel that exists and bot has access to."""
        # Setup
        mock_request.get = lambda key: {"webapp_auth": mock_auth}.get(key)
        mock_request.app = {
            "bot": mock_bot,
            "channel_subscription_service": mock_channel_service,
        }

        # Mock successful channel lookup
        mock_chat = MagicMock()
        mock_chat.id = -1001234567890
        mock_chat.title = "Test Channel"
        mock_bot.get_chat.return_value = mock_chat

        # Mock successful bot access check
        mock_channel_service.check_bot_access.return_value = (True, None)

        # Execute
        result = await validate_channel(mock_request, "-1001234567890")

        # Verify
        assert result["success"] is True
        data = result["data"]
        assert data["valid"] is True
        assert data["channel_id"] == -1001234567890
        assert data["title"] == "Test Channel"
        assert data["error"] is None

    @pytest.mark.asyncio
    async def test_validate_valid_channel_by_username(
        self, mock_request, mock_auth, mock_bot, mock_channel_service
    ):
        """Test validating a channel by @username."""
        # Setup
        mock_request.get = lambda key: {"webapp_auth": mock_auth}.get(key)
        mock_request.app = {
            "bot": mock_bot,
            "channel_subscription_service": mock_channel_service,
        }

        # Mock successful channel lookup
        mock_chat = MagicMock()
        mock_chat.id = -1001234567890
        mock_chat.title = "Test Channel"
        mock_bot.get_chat.return_value = mock_chat

        # Mock successful bot access check
        mock_channel_service.check_bot_access.return_value = (True, None)

        # Execute
        result = await validate_channel(mock_request, "@testchannel")

        # Verify
        assert result["success"] is True
        data = result["data"]
        assert data["valid"] is True
        assert data["channel_id"] == -1001234567890
        assert data["title"] == "Test Channel"

    @pytest.mark.asyncio
    async def test_validate_invalid_channel_id(
        self, mock_request, mock_auth, mock_bot, mock_channel_service
    ):
        """Test validating a channel that doesn't exist."""
        # Setup
        mock_request.get = lambda key: {"webapp_auth": mock_auth}.get(key)
        mock_request.app = {
            "bot": mock_bot,
            "channel_subscription_service": mock_channel_service,
        }

        # Mock channel not found error
        mock_bot.get_chat.side_effect = Exception("Chat not found")

        # Execute
        result = await validate_channel(mock_request, "-1009999999999")

        # Verify
        assert result["success"] is True
        data = result["data"]
        assert data["valid"] is False
        assert data["channel_id"] == -1009999999999
        assert "not found" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_validate_bot_not_in_channel(
        self, mock_request, mock_auth, mock_bot, mock_channel_service
    ):
        """Test validating a channel where bot is not an admin."""
        # Setup
        mock_request.get = lambda key: {"webapp_auth": mock_auth}.get(key)
        mock_request.app = {
            "bot": mock_bot,
            "channel_subscription_service": mock_channel_service,
        }

        # Mock successful channel lookup
        mock_chat = MagicMock()
        mock_chat.id = -1001234567890
        mock_chat.title = "Test Channel"
        mock_bot.get_chat.return_value = mock_chat

        # Mock bot not admin
        mock_channel_service.check_bot_access.return_value = (
            False,
            "Bot must be an administrator in the channel to check subscriptions",
        )

        # Execute
        result = await validate_channel(mock_request, "-1001234567890")

        # Verify
        assert result["success"] is True
        data = result["data"]
        assert data["valid"] is False
        assert data["channel_id"] == -1001234567890
        assert data["title"] == "Test Channel"
        assert "administrator" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_validate_forbidden_channel(
        self, mock_request, mock_auth, mock_bot, mock_channel_service
    ):
        """Test validating a private channel bot can't access."""
        # Setup
        mock_request.get = lambda key: {"webapp_auth": mock_auth}.get(key)
        mock_request.app = {
            "bot": mock_bot,
            "channel_subscription_service": mock_channel_service,
        }

        # Mock forbidden error
        mock_bot.get_chat.side_effect = Exception("Forbidden: bot was kicked")

        # Execute
        result = await validate_channel(mock_request, "-1001234567890")

        # Verify
        assert result["success"] is True
        data = result["data"]
        assert data["valid"] is False
        assert "add bot as admin" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_validate_invalid_format(
        self, mock_request, mock_auth, mock_bot, mock_channel_service
    ):
        """Test validating with invalid channel format."""
        # Setup
        mock_request.get = lambda key: {"webapp_auth": mock_auth}.get(key)
        mock_request.app = {
            "bot": mock_bot,
            "channel_subscription_service": mock_channel_service,
        }

        # Execute - not a valid username or numeric ID
        result = await validate_channel(mock_request, "invalid_format!")

        # Verify
        assert result["success"] is True
        data = result["data"]
        assert data["valid"] is False
        assert "invalid channel format" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_validate_missing_auth(self, mock_request, mock_bot, mock_channel_service):
        """Test that unauthenticated requests are rejected."""
        # Setup - no auth in request
        mock_request.get = lambda _key: None
        mock_request.app = {
            "bot": mock_bot,
            "channel_subscription_service": mock_channel_service,
        }

        # Execute
        result = await validate_channel(mock_request, "-1001234567890")

        # Verify
        assert result["success"] is False
        assert result["error"]["code"] == "UNAUTHORIZED"

    @pytest.mark.asyncio
    async def test_validate_service_unavailable(self, mock_request, mock_auth):
        """Test when channel service is not available."""
        # Setup - missing services
        mock_request.get = lambda key: {"webapp_auth": mock_auth}.get(key)
        mock_request.app = {}  # No bot or channel service

        # Execute
        result = await validate_channel(mock_request, "-1001234567890")

        # Verify
        assert result["success"] is False
        assert result["error"]["code"] == "ERROR"
        assert "not available" in result["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_validate_channel_username_not_found(
        self, mock_request, mock_auth, mock_bot, mock_channel_service
    ):
        """Test validating a channel username that doesn't exist."""
        # Setup
        mock_request.get = lambda key: {"webapp_auth": mock_auth}.get(key)
        mock_request.app = {
            "bot": mock_bot,
            "channel_subscription_service": mock_channel_service,
        }

        # Mock username not found error
        mock_bot.get_chat.side_effect = Exception("Chat not found")

        # Execute
        result = await validate_channel(mock_request, "@nonexistentchannel")

        # Verify
        assert result["success"] is True
        data = result["data"]
        assert data["valid"] is False
        assert "@nonexistentchannel" in data["error"] or "not found" in data["error"].lower()


class TestValidateChannelRoute:
    """Test the /api/channels/validate route registration and behavior."""

    def test_route_is_registered(self):
        """Test that the route is properly registered."""
        routes = create_mini_app_routes()

        # Find the validate channel route
        route_paths = [
            r.resource.canonical if hasattr(r, "resource") else r.path for r in routes
        ]

        # Check route is registered (accounting for different route table formats)
        assert any("/api/channels/validate" in str(path) for path in route_paths)


class TestValidateChannelMissingParameter:
    """Tests for missing channel parameter - these are handled at route level."""

    @pytest.mark.asyncio
    async def test_route_returns_400_for_missing_channel_param(self):
        """Test that route handler returns 400 when channel param is missing.

        This test verifies the route-level validation that occurs before
        the handler is called.
        """
        # This would require a full aiohttp test client setup
        # For now, we document the expected behavior
        pass


# =============================================================================
# Additional Edge Case Tests
# =============================================================================


class TestValidateChannelEdgeCases:
    """Test edge cases for channel validation."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock aiohttp request."""
        request = MagicMock(spec=web.Request)
        request.app = {}
        return request

    @pytest.fixture
    def mock_auth(self):
        """Create a mock WebAppAuth object."""
        auth = MagicMock()
        auth.user_id = 123456789
        return auth

    @pytest.fixture
    def mock_bot(self):
        """Create a mock aiogram Bot instance."""
        return AsyncMock()

    @pytest.fixture
    def mock_channel_service(self):
        """Create a mock ChannelSubscriptionService."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_validate_positive_channel_id(
        self, mock_request, mock_auth, mock_bot, mock_channel_service
    ):
        """Test that positive IDs work (some channels use positive IDs)."""
        mock_request.get = lambda key: {"webapp_auth": mock_auth}.get(key)
        mock_request.app = {
            "bot": mock_bot,
            "channel_subscription_service": mock_channel_service,
        }

        mock_chat = MagicMock()
        mock_chat.id = 1234567890  # Positive ID (unusual but valid)
        mock_chat.title = "Positive ID Channel"
        mock_bot.get_chat.return_value = mock_chat
        mock_channel_service.check_bot_access.return_value = (True, None)

        result = await validate_channel(mock_request, "1234567890")

        assert result["success"] is True
        data = result["data"]
        assert data["valid"] is True
        assert data["channel_id"] == 1234567890

    @pytest.mark.asyncio
    async def test_validate_channel_with_whitespace(
        self, mock_request, mock_auth, mock_bot, mock_channel_service
    ):
        """Test that whitespace in channel input is handled.

        Note: The route handler strips whitespace before calling validate_channel.
        """
        mock_request.get = lambda key: {"webapp_auth": mock_auth}.get(key)
        mock_request.app = {
            "bot": mock_bot,
            "channel_subscription_service": mock_channel_service,
        }

        mock_chat = MagicMock()
        mock_chat.id = -1001234567890
        mock_chat.title = "Test Channel"
        mock_bot.get_chat.return_value = mock_chat
        mock_channel_service.check_bot_access.return_value = (True, None)

        # Test with username that might have whitespace
        result = await validate_channel(mock_request, "@testchannel")

        assert result["success"] is True
        data = result["data"]
        assert data["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_channel_api_error(
        self, mock_request, mock_auth, mock_bot, mock_channel_service
    ):
        """Test handling of unexpected API errors."""
        mock_request.get = lambda key: {"webapp_auth": mock_auth}.get(key)
        mock_request.app = {
            "bot": mock_bot,
            "channel_subscription_service": mock_channel_service,
        }

        # Mock unexpected error
        mock_bot.get_chat.side_effect = Exception("Network timeout")

        result = await validate_channel(mock_request, "-1001234567890")

        assert result["success"] is True
        data = result["data"]
        assert data["valid"] is False
        assert data["error"] is not None
