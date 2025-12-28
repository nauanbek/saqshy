"""
Tests for AuthMiddleware.

Tests cover:
- Admin status checking and caching
- Whitelist/blacklist lookups
- Private chat handling
- Telegram API error handling (timeout, bad request, rate limit)
- Cache key generation
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramRetryAfter,
)
from aiogram.types import Chat, ChatMemberMember, ChatMemberOwner, Message, User

from saqshy.bot.middlewares.auth import (
    ADMIN_CACHE_TTL,
    AuthMiddleware,
    check_user_is_admin,
    refresh_admin_cache,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_cache_service() -> AsyncMock:
    """Create a mock cache service with standard responses."""
    cache = AsyncMock()
    cache.get.return_value = None
    cache.set.return_value = True
    cache.get_json.return_value = None
    cache.set_json.return_value = True
    return cache


@pytest.fixture
def mock_bot() -> AsyncMock:
    """Create a mock bot with standard responses."""
    bot = AsyncMock()
    # Default: user is a regular member
    mock_user = User(id=123456789, is_bot=False, first_name="Test")
    mock_member = ChatMemberMember(user=mock_user, status="member")
    bot.get_chat_member.return_value = mock_member
    bot.get_chat_administrators.return_value = []
    return bot


@pytest.fixture
def mock_supergroup_chat() -> Chat:
    """Create a mock supergroup chat."""
    return Chat(id=-1001234567890, type="supergroup", title="Test Group")


@pytest.fixture
def mock_private_chat() -> Chat:
    """Create a mock private chat."""
    return Chat(id=123456789, type="private", first_name="Test")


@pytest.fixture
def mock_user() -> User:
    """Create a mock user."""
    return User(id=123456789, is_bot=False, first_name="Test", username="testuser")


@pytest.fixture
def mock_message(mock_user: User, mock_supergroup_chat: Chat) -> Message:
    """Create a mock message in a supergroup."""
    msg = MagicMock(spec=Message)
    msg.chat = mock_supergroup_chat
    msg.from_user = mock_user
    msg.message_id = 12345
    return msg


@pytest.fixture
def mock_private_message(mock_user: User, mock_private_chat: Chat) -> Message:
    """Create a mock message in a private chat."""
    msg = MagicMock(spec=Message)
    msg.chat = mock_private_chat
    msg.from_user = mock_user
    msg.message_id = 12345
    return msg


@pytest.fixture
def middleware(mock_cache_service: AsyncMock) -> AuthMiddleware:
    """Create an AuthMiddleware instance."""
    return AuthMiddleware(cache_service=mock_cache_service)


# =============================================================================
# AuthMiddleware Tests
# =============================================================================


class TestAuthMiddleware:
    """Tests for AuthMiddleware.__call__."""

    async def test_injects_permissions_into_context(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
    ) -> None:
        """Test that middleware injects permission flags into handler data."""
        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()
        assert "user_is_admin" in data
        assert "user_is_whitelisted" in data
        assert "user_is_blacklisted" in data
        assert "bot_is_admin" in data

    async def test_regular_user_is_not_admin(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
    ) -> None:
        """Test that regular users are correctly identified as non-admin."""
        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        assert data["user_is_admin"] is False

    async def test_admin_user_is_identified(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
        mock_user: User,
    ) -> None:
        """Test that admin users are correctly identified."""
        # Set up bot to return admin status
        admin_member = ChatMemberOwner(
            user=mock_user, status="creator", is_anonymous=False
        )
        mock_bot.get_chat_member.return_value = admin_member

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        assert data["user_is_admin"] is True

    async def test_skips_private_chats(
        self,
        middleware: AuthMiddleware,
        mock_private_message: Message,
        mock_bot: AsyncMock,
    ) -> None:
        """Test that private chats skip admin check and set defaults."""
        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_private_message, data)

        # Should not call Telegram API for private chats
        mock_bot.get_chat_member.assert_not_called()
        # Default values for private chats
        assert data["user_is_admin"] is False
        assert data["bot_is_admin"] is True

    async def test_caches_admin_status(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that admin status is cached after lookup."""
        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        # Verify cache was set
        mock_cache_service.set.assert_called()
        call_args = mock_cache_service.set.call_args
        # Check cache key format
        key = call_args[0][0]
        assert "saqshy:admin:" in key

    async def test_uses_cached_admin_status(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that cached admin status is used when available."""
        # Cache says user is admin
        mock_cache_service.get.return_value = "1"

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        # Should NOT call Telegram API since we have cached value
        mock_bot.get_chat_member.assert_not_called()
        assert data["user_is_admin"] is True

    async def test_handles_telegram_api_timeout(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
    ) -> None:
        """Test graceful handling of Telegram API timeout."""
        mock_bot.get_chat_member.side_effect = asyncio.TimeoutError()

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        # Should not raise, should continue
        await middleware(handler, mock_message, data)

        handler.assert_called_once()
        # Defaults to non-admin on timeout
        assert data["user_is_admin"] is False

    async def test_handles_telegram_bad_request(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
    ) -> None:
        """Test graceful handling of TelegramBadRequest."""
        mock_bot.get_chat_member.side_effect = TelegramBadRequest(
            method="getChatMember",
            message="User not found",
        )

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()
        assert data["user_is_admin"] is False

    async def test_handles_telegram_retry_after(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
    ) -> None:
        """Test graceful handling of rate limiting."""
        mock_bot.get_chat_member.side_effect = TelegramRetryAfter(
            method="getChatMember",
            message="Rate limited",
            retry_after=30,
        )

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()
        assert data["user_is_admin"] is False

    async def test_handles_generic_telegram_api_error(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
    ) -> None:
        """Test graceful handling of generic Telegram API errors."""
        mock_bot.get_chat_member.side_effect = TelegramAPIError(
            method="getChatMember",
            message="Unknown error",
        )

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()
        assert data["user_is_admin"] is False

    async def test_uses_cache_service_from_data(
        self,
        mock_message: Message,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that cache service can be injected via data dict."""
        # Create middleware without cache service
        middleware = AuthMiddleware(cache_service=None)
        mock_cache_service.get.return_value = "1"  # Cached as admin

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot, "cache_service": mock_cache_service}

        await middleware(handler, mock_message, data)

        # Should have used the cache from data
        mock_cache_service.get.assert_called()
        assert data["user_is_admin"] is True


class TestWhitelistCheck:
    """Tests for whitelist checking."""

    async def test_checks_whitelist(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that whitelist is checked."""
        # User is in whitelist
        mock_cache_service.get_json.return_value = {
            "users": [{"user_id": 123456789, "added_by": 111, "reason": "trusted"}]
        }

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        assert data["user_is_whitelisted"] is True

    async def test_whitelist_user_not_found(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test whitelist when user is not in list."""
        mock_cache_service.get_json.return_value = {
            "users": [{"user_id": 999999, "added_by": 111, "reason": "other"}]
        }

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        assert data["user_is_whitelisted"] is False

    async def test_whitelist_empty(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test whitelist when no whitelist exists."""
        mock_cache_service.get_json.return_value = None

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        assert data["user_is_whitelisted"] is False

    async def test_whitelist_timeout_fails_gracefully(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that whitelist check timeout is handled gracefully."""
        mock_cache_service.get_json.side_effect = TimeoutError()

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        # Should default to not whitelisted
        assert data["user_is_whitelisted"] is False


class TestBlacklistCheck:
    """Tests for blacklist checking."""

    async def test_checks_blacklist(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that blacklist is checked."""
        # Set up mock to return whitelist first (None), then blacklist
        mock_cache_service.get_json.side_effect = [
            None,  # whitelist
            {"users": [{"user_id": 123456789, "reason": "spam"}]},  # blacklist
        ]

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        assert data["user_is_blacklisted"] is True

    async def test_blacklist_user_not_found(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test blacklist when user is not in list."""
        mock_cache_service.get_json.side_effect = [
            None,  # whitelist
            {"users": [{"user_id": 999999, "reason": "spam"}]},  # blacklist
        ]

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        assert data["user_is_blacklisted"] is False

    async def test_blacklist_connection_error(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that blacklist connection error is handled gracefully."""
        mock_cache_service.get_json.side_effect = [
            None,  # whitelist
            ConnectionError("Redis unavailable"),  # blacklist
        ]

        handler = AsyncMock()
        data: dict[str, Any] = {"bot": mock_bot}

        await middleware(handler, mock_message, data)

        # Should default to not blacklisted
        assert data["user_is_blacklisted"] is False


class TestExtractIds:
    """Tests for ID extraction from events."""

    def test_extracts_ids_from_message(
        self,
        middleware: AuthMiddleware,
        mock_message: Message,
    ) -> None:
        """Test ID extraction from a Message event."""
        chat_id, user_id = middleware._extract_ids(mock_message)

        assert chat_id == -1001234567890
        assert user_id == 123456789

    def test_returns_none_for_private_chat(
        self,
        middleware: AuthMiddleware,
        mock_private_message: Message,
    ) -> None:
        """Test that private chats return None IDs."""
        chat_id, user_id = middleware._extract_ids(mock_private_message)

        assert chat_id is None
        assert user_id is None

    def test_returns_none_for_message_without_user(
        self,
        middleware: AuthMiddleware,
        mock_supergroup_chat: Chat,
    ) -> None:
        """Test handling of messages without from_user."""
        msg = MagicMock(spec=Message)
        msg.chat = mock_supergroup_chat
        msg.from_user = None

        chat_id, user_id = middleware._extract_ids(msg)

        # Chat ID is extracted but user_id is None
        assert chat_id == -1001234567890
        assert user_id is None


# =============================================================================
# Standalone Function Tests
# =============================================================================


class TestCheckUserIsAdmin:
    """Tests for the standalone check_user_is_admin function."""

    async def test_returns_true_for_admin(
        self,
        mock_bot: AsyncMock,
        mock_user: User,
    ) -> None:
        """Test that function returns True for admin users."""
        admin_member = ChatMemberOwner(
            user=mock_user, status="creator", is_anonymous=False
        )
        mock_bot.get_chat_member.return_value = admin_member

        result = await check_user_is_admin(
            bot=mock_bot,
            chat_id=-1001234567890,
            user_id=123456789,
        )

        assert result is True

    async def test_returns_false_for_regular_member(
        self,
        mock_bot: AsyncMock,
        mock_user: User,
    ) -> None:
        """Test that function returns False for regular members."""
        member = ChatMemberMember(user=mock_user, status="member")
        mock_bot.get_chat_member.return_value = member

        result = await check_user_is_admin(
            bot=mock_bot,
            chat_id=-1001234567890,
            user_id=123456789,
        )

        assert result is False

    async def test_uses_cache_when_available(
        self,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that cached value is used when available."""
        mock_cache_service.get.return_value = "1"

        result = await check_user_is_admin(
            bot=mock_bot,
            chat_id=-1001234567890,
            user_id=123456789,
            cache_service=mock_cache_service,
        )

        assert result is True
        mock_bot.get_chat_member.assert_not_called()

    async def test_handles_timeout(
        self,
        mock_bot: AsyncMock,
    ) -> None:
        """Test that timeout is handled gracefully."""
        mock_bot.get_chat_member.side_effect = asyncio.TimeoutError()

        result = await check_user_is_admin(
            bot=mock_bot,
            chat_id=-1001234567890,
            user_id=123456789,
        )

        assert result is False


class TestRefreshAdminCache:
    """Tests for the refresh_admin_cache function."""

    async def test_caches_all_admins(
        self,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
        mock_user: User,
    ) -> None:
        """Test that all admins are cached."""
        admin1 = ChatMemberOwner(user=mock_user, status="creator", is_anonymous=False)
        admin2_user = User(id=999999, is_bot=False, first_name="Admin2")
        admin2 = MagicMock()
        admin2.user = admin2_user

        mock_bot.get_chat_administrators.return_value = [admin1, admin2]

        result = await refresh_admin_cache(
            bot=mock_bot,
            chat_id=-1001234567890,
            cache_service=mock_cache_service,
        )

        # Should return set of admin IDs
        assert 123456789 in result
        assert 999999 in result
        # Cache should be set for each admin
        assert mock_cache_service.set.call_count >= 2

    async def test_handles_timeout(
        self,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that timeout returns empty set."""
        mock_bot.get_chat_administrators.side_effect = asyncio.TimeoutError()

        result = await refresh_admin_cache(
            bot=mock_bot,
            chat_id=-1001234567890,
            cache_service=mock_cache_service,
        )

        assert result == set()

    async def test_handles_telegram_bad_request(
        self,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that TelegramBadRequest returns empty set."""
        mock_bot.get_chat_administrators.side_effect = TelegramBadRequest(
            method="getChatAdministrators",
            message="Chat not found",
        )

        result = await refresh_admin_cache(
            bot=mock_bot,
            chat_id=-1001234567890,
            cache_service=mock_cache_service,
        )

        assert result == set()

    async def test_stores_admin_list(
        self,
        mock_bot: AsyncMock,
        mock_cache_service: AsyncMock,
        mock_user: User,
    ) -> None:
        """Test that admin list is stored with correct key."""
        admin = ChatMemberOwner(user=mock_user, status="creator", is_anonymous=False)
        mock_bot.get_chat_administrators.return_value = [admin]

        await refresh_admin_cache(
            bot=mock_bot,
            chat_id=-1001234567890,
            cache_service=mock_cache_service,
        )

        # Check that group_admins key was set
        calls = mock_cache_service.set.call_args_list
        admin_list_call = next(
            (c for c in calls if "group_admins:" in str(c)), None
        )
        assert admin_list_call is not None
