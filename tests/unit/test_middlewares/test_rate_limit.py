"""
Tests for RateLimitMiddleware.

Tests cover:
- Normal rate allowing messages through
- Blocking excessive rates
- Per-user rate limiting
- Per-group rate limiting
- Admin/whitelist bypass
- Fail-open behavior on errors
- AdaptiveRateLimiter personalized limits
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, Message, User

from saqshy.bot.middlewares.rate_limit import (
    AdaptiveRateLimiter,
    RateLimitMiddleware,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_cache_service() -> AsyncMock:
    """Create a mock cache service."""
    cache = AsyncMock()
    cache.increment_rate.return_value = 1  # First message
    cache.get.return_value = None
    cache.get_json.return_value = None
    return cache


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
def middleware(mock_cache_service: AsyncMock) -> RateLimitMiddleware:
    """Create a RateLimitMiddleware instance."""
    return RateLimitMiddleware(
        cache_service=mock_cache_service,
        user_limit=20,
        user_window=60,
        group_limit=200,
        group_window=60,
    )


# =============================================================================
# RateLimitMiddleware Tests
# =============================================================================


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware.__call__."""

    async def test_allows_normal_rate(
        self,
        middleware: RateLimitMiddleware,
        mock_message: Message,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that normal message rate is allowed."""
        mock_cache_service.increment_rate.return_value = 5  # Under limit

        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()
        assert data["is_rate_limited"] is False

    async def test_blocks_excessive_rate(
        self,
        middleware: RateLimitMiddleware,
        mock_message: Message,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that excessive rate is blocked."""
        mock_cache_service.increment_rate.return_value = 25  # Over limit of 20

        handler = AsyncMock()
        data: dict[str, Any] = {}

        result = await middleware(handler, mock_message, data)

        # Handler should NOT be called
        handler.assert_not_called()
        assert data["is_rate_limited"] is True
        assert result is None

    async def test_skips_admins(
        self,
        middleware: RateLimitMiddleware,
        mock_message: Message,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that admins bypass rate limiting."""
        mock_cache_service.increment_rate.return_value = 100  # Way over limit

        handler = AsyncMock()
        data: dict[str, Any] = {"user_is_admin": True}

        await middleware(handler, mock_message, data)

        # Admin should bypass rate limit
        handler.assert_called_once()
        assert data["is_rate_limited"] is False
        # Rate check should not be called for admins
        mock_cache_service.increment_rate.assert_not_called()

    async def test_skips_whitelisted_users(
        self,
        middleware: RateLimitMiddleware,
        mock_message: Message,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that whitelisted users bypass rate limiting."""
        mock_cache_service.increment_rate.return_value = 100  # Way over limit

        handler = AsyncMock()
        data: dict[str, Any] = {"user_is_whitelisted": True}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()
        assert data["is_rate_limited"] is False

    async def test_passes_non_message_events(
        self,
        middleware: RateLimitMiddleware,
    ) -> None:
        """Test that non-Message events pass through without rate check."""
        # Create a mock CallbackQuery instead of Message
        callback = MagicMock()
        callback.__class__.__name__ = "CallbackQuery"

        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, callback, data)

        handler.assert_called_once()

    async def test_passes_messages_without_user(
        self,
        middleware: RateLimitMiddleware,
        mock_supergroup_chat: Chat,
    ) -> None:
        """Test that messages without from_user pass through."""
        msg = MagicMock(spec=Message)
        msg.chat = mock_supergroup_chat
        msg.from_user = None

        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, msg, data)

        handler.assert_called_once()

    async def test_skips_private_chats(
        self,
        middleware: RateLimitMiddleware,
        mock_private_message: Message,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that private chats are not rate limited."""
        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_private_message, data)

        handler.assert_called_once()
        # Rate check should not be called for private chats
        mock_cache_service.increment_rate.assert_not_called()

    async def test_uses_cache_service_from_data(
        self,
        mock_message: Message,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that cache service can be injected via data dict."""
        middleware = RateLimitMiddleware(cache_service=None)
        mock_cache_service.increment_rate.return_value = 5

        handler = AsyncMock()
        data: dict[str, Any] = {"cache_service": mock_cache_service}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()
        mock_cache_service.increment_rate.assert_called_once()


class TestRateLimitFailOpen:
    """Tests for fail-open behavior on errors."""

    async def test_allows_on_timeout(
        self,
        middleware: RateLimitMiddleware,
        mock_message: Message,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that messages are allowed on cache timeout."""
        mock_cache_service.increment_rate.side_effect = TimeoutError()

        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_message, data)

        # Should fail-open (allow through)
        handler.assert_called_once()
        assert data["is_rate_limited"] is False

    async def test_allows_on_connection_error(
        self,
        middleware: RateLimitMiddleware,
        mock_message: Message,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that messages are allowed on cache connection error."""
        mock_cache_service.increment_rate.side_effect = ConnectionError(
            "Redis unavailable"
        )

        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()
        assert data["is_rate_limited"] is False

    async def test_allows_on_unexpected_error(
        self,
        middleware: RateLimitMiddleware,
        mock_message: Message,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that messages are allowed on unexpected errors."""
        mock_cache_service.increment_rate.side_effect = RuntimeError("Unexpected")

        handler = AsyncMock()
        data: dict[str, Any] = {}

        await middleware(handler, mock_message, data)

        handler.assert_called_once()
        assert data["is_rate_limited"] is False


class TestGroupRateLimit:
    """Tests for group-level rate limiting."""

    async def test_check_group_rate_under_limit(
        self,
        middleware: RateLimitMiddleware,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test group rate check when under limit."""
        mock_cache_service.increment_rate.return_value = 50  # Under 200

        result = await middleware.check_group_rate(
            cache_service=mock_cache_service,
            chat_id=-1001234567890,
        )

        assert result is False  # Not rate limited

    async def test_check_group_rate_over_limit(
        self,
        middleware: RateLimitMiddleware,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test group rate check when over limit."""
        mock_cache_service.increment_rate.return_value = 250  # Over 200

        result = await middleware.check_group_rate(
            cache_service=mock_cache_service,
            chat_id=-1001234567890,
        )

        assert result is True  # Rate limited

    async def test_check_group_rate_timeout(
        self,
        middleware: RateLimitMiddleware,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test group rate check handles timeout gracefully."""
        mock_cache_service.increment_rate.side_effect = TimeoutError()

        result = await middleware.check_group_rate(
            cache_service=mock_cache_service,
            chat_id=-1001234567890,
        )

        assert result is False  # Fail-open


class TestRaidLimit:
    """Tests for raid detection."""

    async def test_check_raid_limit_not_active(
        self,
        middleware: RateLimitMiddleware,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test raid check when raid mode is not active."""
        mock_cache_service.get.return_value = None

        result = await middleware.check_raid_limit(
            cache_service=mock_cache_service,
            chat_id=-1001234567890,
        )

        assert result is False

    async def test_check_raid_limit_active(
        self,
        middleware: RateLimitMiddleware,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test raid check when raid mode is active."""
        mock_cache_service.get.return_value = "1"

        result = await middleware.check_raid_limit(
            cache_service=mock_cache_service,
            chat_id=-1001234567890,
        )

        assert result is True

    async def test_check_raid_limit_timeout(
        self,
        middleware: RateLimitMiddleware,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test raid check handles timeout gracefully."""
        mock_cache_service.get.side_effect = TimeoutError()

        result = await middleware.check_raid_limit(
            cache_service=mock_cache_service,
            chat_id=-1001234567890,
        )

        assert result is False


# =============================================================================
# AdaptiveRateLimiter Tests
# =============================================================================


class TestAdaptiveRateLimiter:
    """Tests for AdaptiveRateLimiter."""

    @pytest.fixture
    def adaptive_limiter(
        self, mock_cache_service: AsyncMock
    ) -> AdaptiveRateLimiter:
        """Create an AdaptiveRateLimiter instance."""
        return AdaptiveRateLimiter(
            cache_service=mock_cache_service,
            base_limit=20,
            trusted_multiplier=2.0,
            suspicious_multiplier=0.5,
        )

    async def test_get_user_limit_new_user(
        self,
        adaptive_limiter: AdaptiveRateLimiter,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test limit for new user with no history."""
        mock_cache_service.get_json.return_value = None

        limit = await adaptive_limiter.get_user_limit(
            user_id=123456789,
            chat_id=-1001234567890,
        )

        assert limit == 20  # Base limit

    async def test_get_user_limit_trusted_user(
        self,
        adaptive_limiter: AdaptiveRateLimiter,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test limit for trusted user (>90% approved)."""
        mock_cache_service.get_json.return_value = {
            "approved": 95,
            "blocked": 5,
        }

        limit = await adaptive_limiter.get_user_limit(
            user_id=123456789,
            chat_id=-1001234567890,
        )

        assert limit == 40  # 20 * 2.0 (trusted multiplier)

    async def test_get_user_limit_suspicious_user(
        self,
        adaptive_limiter: AdaptiveRateLimiter,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test limit for suspicious user (<50% approved)."""
        mock_cache_service.get_json.return_value = {
            "approved": 30,
            "blocked": 70,
        }

        limit = await adaptive_limiter.get_user_limit(
            user_id=123456789,
            chat_id=-1001234567890,
        )

        assert limit == 10  # 20 * 0.5 (suspicious multiplier)

    async def test_get_user_limit_normal_user(
        self,
        adaptive_limiter: AdaptiveRateLimiter,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test limit for normal user (between 50-90% approved)."""
        mock_cache_service.get_json.return_value = {
            "approved": 70,
            "blocked": 30,
        }

        limit = await adaptive_limiter.get_user_limit(
            user_id=123456789,
            chat_id=-1001234567890,
        )

        assert limit == 20  # Base limit

    async def test_get_user_limit_timeout(
        self,
        adaptive_limiter: AdaptiveRateLimiter,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test limit defaults to base on timeout."""
        mock_cache_service.get_json.side_effect = TimeoutError()

        limit = await adaptive_limiter.get_user_limit(
            user_id=123456789,
            chat_id=-1001234567890,
        )

        assert limit == 20  # Base limit

    async def test_check_and_record_under_limit(
        self,
        adaptive_limiter: AdaptiveRateLimiter,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test check_and_record when under limit."""
        mock_cache_service.get_json.return_value = None
        mock_cache_service.increment_rate.return_value = 10

        is_limited, count, limit = await adaptive_limiter.check_and_record(
            user_id=123456789,
            chat_id=-1001234567890,
        )

        assert is_limited is False
        assert count == 10
        assert limit == 20

    async def test_check_and_record_over_limit(
        self,
        adaptive_limiter: AdaptiveRateLimiter,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test check_and_record when over limit."""
        mock_cache_service.get_json.return_value = None
        mock_cache_service.increment_rate.return_value = 25

        is_limited, count, limit = await adaptive_limiter.check_and_record(
            user_id=123456789,
            chat_id=-1001234567890,
        )

        assert is_limited is True
        assert count == 25
        assert limit == 20

    async def test_check_and_record_timeout(
        self,
        adaptive_limiter: AdaptiveRateLimiter,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test check_and_record handles timeout gracefully."""
        mock_cache_service.get_json.return_value = None
        mock_cache_service.increment_rate.side_effect = TimeoutError()

        is_limited, count, limit = await adaptive_limiter.check_and_record(
            user_id=123456789,
            chat_id=-1001234567890,
        )

        # Fail-open
        assert is_limited is False
        assert count == 0
        assert limit == 20

    async def test_check_and_record_trusted_user_higher_limit(
        self,
        adaptive_limiter: AdaptiveRateLimiter,
        mock_cache_service: AsyncMock,
    ) -> None:
        """Test that trusted users get higher limits."""
        mock_cache_service.get_json.return_value = {
            "approved": 95,
            "blocked": 5,
        }
        mock_cache_service.increment_rate.return_value = 30

        is_limited, count, limit = await adaptive_limiter.check_and_record(
            user_id=123456789,
            chat_id=-1001234567890,
        )

        # 30 messages is under trusted limit of 40
        assert is_limited is False
        assert count == 30
        assert limit == 40
