"""
Tests for ChannelSubscriptionService

Tests Telegram channel subscription checking, caching, rate limiting,
and error handling.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from saqshy.analyzers.behavior import ChannelSubscriptionChecker
from saqshy.services.channel_subscription import (
    CACHE_TTL_ERROR_SECONDS,
    CACHE_TTL_SECONDS,
    NOT_SUBSCRIBED_STATUSES,
    SUBSCRIBED_STATUSES,
    ChannelSubscriptionService,
    RateLimiter,
    SubscriptionRequirement,
    SubscriptionStatus,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_bot():
    """Create mock aiogram Bot."""
    mock = AsyncMock()
    mock.get_me.return_value = MagicMock(id=9999999)
    return mock


@pytest.fixture
def mock_cache():
    """Create mock CacheService."""
    mock = AsyncMock()
    mock.get.return_value = None
    mock.set.return_value = True
    mock.delete.return_value = True
    return mock


@pytest.fixture
def service(mock_bot, mock_cache):
    """Create ChannelSubscriptionService with mocks."""
    return ChannelSubscriptionService(
        bot=mock_bot,
        cache=mock_cache,
    )


@pytest.fixture
def service_no_cache(mock_bot):
    """Create ChannelSubscriptionService without cache."""
    return ChannelSubscriptionService(
        bot=mock_bot,
        cache=None,
    )


# =============================================================================
# Test Protocol Compliance
# =============================================================================


class TestProtocolCompliance:
    """Test that ChannelSubscriptionService satisfies Protocol."""

    def test_is_channel_subscription_checker(self, mock_bot, mock_cache):
        """Service should implement ChannelSubscriptionChecker protocol."""
        service = ChannelSubscriptionService(bot=mock_bot, cache=mock_cache)

        assert isinstance(service, ChannelSubscriptionChecker)

    def test_has_required_methods(self, mock_bot):
        """Service should have all required protocol methods."""
        service = ChannelSubscriptionService(bot=mock_bot)

        assert hasattr(service, "is_subscribed")
        assert hasattr(service, "get_subscription_duration_days")

        # All methods should be async
        import asyncio

        assert asyncio.iscoroutinefunction(service.is_subscribed)
        assert asyncio.iscoroutinefunction(service.get_subscription_duration_days)


# =============================================================================
# Test is_subscribed
# =============================================================================


class TestIsSubscribed:
    """Test is_subscribed method."""

    @pytest.mark.asyncio
    async def test_returns_true_for_member(self, service, mock_bot):
        """Should return True for member status."""
        mock_bot.get_chat_member.return_value = MagicMock(status="member")

        result = await service.is_subscribed(
            user_id=123,
            channel_id=-100999999,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_for_administrator(self, service, mock_bot):
        """Should return True for administrator status."""
        mock_bot.get_chat_member.return_value = MagicMock(status="administrator")

        result = await service.is_subscribed(
            user_id=123,
            channel_id=-100999999,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_for_creator(self, service, mock_bot):
        """Should return True for creator status."""
        mock_bot.get_chat_member.return_value = MagicMock(status="creator")

        result = await service.is_subscribed(
            user_id=123,
            channel_id=-100999999,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_for_left(self, service, mock_bot):
        """Should return False for left status."""
        mock_bot.get_chat_member.return_value = MagicMock(status="left")

        result = await service.is_subscribed(
            user_id=123,
            channel_id=-100999999,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_for_kicked(self, service, mock_bot):
        """Should return False for kicked status."""
        mock_bot.get_chat_member.return_value = MagicMock(status="kicked")

        result = await service.is_subscribed(
            user_id=123,
            channel_id=-100999999,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_api_error(self, service, mock_bot):
        """Should return False on Telegram API error."""
        mock_bot.get_chat_member.side_effect = TelegramBadRequest(
            method="getChatMember", message="Chat not found"
        )

        result = await service.is_subscribed(
            user_id=123,
            channel_id=-100999999,
        )

        assert result is False


# =============================================================================
# Test get_subscription_duration_days
# =============================================================================


class TestGetSubscriptionDurationDays:
    """Test get_subscription_duration_days method."""

    @pytest.mark.asyncio
    async def test_returns_zero_when_not_subscribed(self, service, mock_bot):
        """Should return 0 when user is not subscribed."""
        mock_bot.get_chat_member.return_value = MagicMock(status="left")

        result = await service.get_subscription_duration_days(
            user_id=123,
            channel_id=-100999999,
        )

        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_duration_from_first_seen(self, service, mock_bot, mock_cache):
        """Should calculate duration from first-seen timestamp."""
        mock_bot.get_chat_member.return_value = MagicMock(status="member")

        # First-seen 30 days ago
        first_seen = int(time.time()) - (30 * 86400)

        # Use a function to handle multiple get calls dynamically
        async def mock_get(key):
            if "first_seen" in key:
                return str(first_seen)
            return None

        mock_cache.get.side_effect = mock_get

        result = await service.get_subscription_duration_days(
            user_id=123,
            channel_id=-100999999,
        )

        assert result >= 29  # Allow for timing variations


# =============================================================================
# Test Caching
# =============================================================================


class TestCaching:
    """Test subscription status caching."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_value(self, service, mock_bot, mock_cache):
        """Should return cached value on cache hit."""
        mock_cache.get.return_value = "member:1"

        result = await service.is_subscribed(
            user_id=123,
            channel_id=-100999999,
        )

        assert result is True
        mock_bot.get_chat_member.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_calls_api(self, service, mock_bot, mock_cache):
        """Should call API on cache miss."""
        mock_cache.get.return_value = None
        mock_bot.get_chat_member.return_value = MagicMock(status="member")

        result = await service.is_subscribed(
            user_id=123,
            channel_id=-100999999,
        )

        assert result is True
        mock_bot.get_chat_member.assert_called_once()

    @pytest.mark.asyncio
    async def test_caches_successful_result(self, service, mock_bot, mock_cache):
        """Should cache successful API result."""
        mock_cache.get.return_value = None
        mock_bot.get_chat_member.return_value = MagicMock(status="member")

        await service.is_subscribed(
            user_id=123,
            channel_id=-100999999,
        )

        # Should have called set to cache the result
        mock_cache.set.assert_called()

    @pytest.mark.asyncio
    async def test_works_without_cache(self, service_no_cache, mock_bot):
        """Should work correctly without cache service."""
        mock_bot.get_chat_member.return_value = MagicMock(status="member")

        result = await service_no_cache.is_subscribed(
            user_id=123,
            channel_id=-100999999,
        )

        assert result is True


# =============================================================================
# Test Error Handling
# =============================================================================


class TestErrorHandling:
    """Test error handling for various failure scenarios."""

    @pytest.mark.asyncio
    async def test_handles_chat_not_found(self, service, mock_bot):
        """Should handle 'chat not found' error gracefully."""
        mock_bot.get_chat_member.side_effect = TelegramBadRequest(
            method="getChatMember", message="Chat not found"
        )

        status = await service.check_subscription_with_details(
            user_id=123,
            channel_id=-100999999,
        )

        assert status.is_subscribed is False
        assert "not found" in status.error.lower()

    @pytest.mark.asyncio
    async def test_handles_user_not_found(self, service, mock_bot):
        """Should handle 'user not found' error gracefully."""
        mock_bot.get_chat_member.side_effect = TelegramBadRequest(
            method="getChatMember", message="User not found"
        )

        status = await service.check_subscription_with_details(
            user_id=123,
            channel_id=-100999999,
        )

        assert status.is_subscribed is False

    @pytest.mark.asyncio
    async def test_handles_forbidden_error(self, service, mock_bot):
        """Should handle 'forbidden' error gracefully."""
        mock_bot.get_chat_member.side_effect = TelegramForbiddenError(
            method="getChatMember", message="Forbidden: bot was kicked"
        )

        status = await service.check_subscription_with_details(
            user_id=123,
            channel_id=-100999999,
        )

        assert status.is_subscribed is False
        assert "forbidden" in status.error.lower()

    @pytest.mark.asyncio
    async def test_handles_flood_wait(self, service, mock_bot):
        """Should handle flood wait error gracefully."""
        mock_bot.get_chat_member.side_effect = TelegramRetryAfter(
            method="getChatMember", message="Flood control exceeded", retry_after=60
        )

        status = await service.check_subscription_with_details(
            user_id=123,
            channel_id=-100999999,
        )

        assert status.is_subscribed is False
        assert "rate limited" in status.error.lower()

    @pytest.mark.asyncio
    async def test_handles_unknown_error(self, service, mock_bot):
        """Should handle unknown errors gracefully."""
        mock_bot.get_chat_member.side_effect = TelegramAPIError(
            method="getChatMember", message="Some unexpected error"
        )

        status = await service.check_subscription_with_details(
            user_id=123,
            channel_id=-100999999,
        )

        assert status.is_subscribed is False
        assert status.error is not None


# =============================================================================
# Test RateLimiter
# =============================================================================


class TestRateLimiter:
    """Test rate limiter functionality."""

    @pytest.mark.asyncio
    async def test_allows_requests_under_limit(self):
        """Should allow requests under rate limit."""
        limiter = RateLimiter(max_requests=10, window_seconds=1.0)

        # Should allow 10 requests without blocking
        for _ in range(10):
            await limiter.acquire()

        # All requests should have completed

    @pytest.mark.asyncio
    async def test_cleans_expired_timestamps(self):
        """Should clean expired timestamps from tracking."""
        limiter = RateLimiter(max_requests=5, window_seconds=0.1)

        # Make some requests
        for _ in range(3):
            await limiter.acquire()

        # Wait for window to expire
        import asyncio

        await asyncio.sleep(0.15)

        # Should allow more requests
        await limiter.acquire()

        # Timestamps should have been cleaned
        assert len(limiter._timestamps) == 1


# =============================================================================
# Test SubscriptionStatus
# =============================================================================


class TestSubscriptionStatus:
    """Test SubscriptionStatus dataclass."""

    def test_subscribed_status(self):
        """Should correctly represent subscribed status."""
        status = SubscriptionStatus(
            is_subscribed=True,
            status="member",
            duration_days=30,
            cached=False,
        )

        assert status.is_subscribed is True
        assert status.status == "member"
        assert status.duration_days == 30
        assert status.error is None

    def test_error_status(self):
        """Should correctly represent error status."""
        status = SubscriptionStatus(
            is_subscribed=False,
            status="unknown",
            error="Channel not found",
        )

        assert status.is_subscribed is False
        assert status.error is not None


# =============================================================================
# Test SubscriptionRequirement
# =============================================================================


class TestSubscriptionRequirement:
    """Test SubscriptionRequirement class."""

    @pytest.mark.asyncio
    async def test_check_requirement_met(self, service, mock_bot):
        """Should return True when requirement is met."""
        mock_bot.get_chat_member.return_value = MagicMock(status="member")
        requirement = SubscriptionRequirement(service)

        meets, status = await requirement.check_requirement(
            user_id=123,
            channel_id=-100999999,
        )

        assert meets is True
        assert status.is_subscribed is True

    @pytest.mark.asyncio
    async def test_check_requirement_not_met(self, service, mock_bot):
        """Should return False when requirement is not met."""
        mock_bot.get_chat_member.return_value = MagicMock(status="left")
        requirement = SubscriptionRequirement(service)

        meets, status = await requirement.check_requirement(
            user_id=123,
            channel_id=-100999999,
        )

        assert meets is False
        assert status.is_subscribed is False


# =============================================================================
# Test Cache Invalidation
# =============================================================================


class TestCacheInvalidation:
    """Test cache invalidation functionality."""

    @pytest.mark.asyncio
    async def test_invalidate_cache(self, service, mock_cache):
        """Should delete cache key on invalidation."""
        result = await service.invalidate_cache(
            user_id=123,
            channel_id=-100999999,
        )

        assert result is True
        mock_cache.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalidate_cache_without_cache_service(self, service_no_cache):
        """Should return False when no cache service."""
        result = await service_no_cache.invalidate_cache(
            user_id=123,
            channel_id=-100999999,
        )

        assert result is False


# =============================================================================
# Test Bot Access Verification
# =============================================================================


class TestBotAccessVerification:
    """Test bot access verification for channels."""

    @pytest.mark.asyncio
    async def test_check_bot_access_valid(self, service, mock_bot):
        """Should return True when bot has admin access."""
        mock_bot.get_chat_member.return_value = MagicMock(status="administrator")

        is_valid, error = await service.check_bot_access(
            channel_id=-100999999,
        )

        assert is_valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_check_bot_access_not_admin(self, service, mock_bot):
        """Should return False when bot is not admin."""
        mock_bot.get_chat_member.return_value = MagicMock(status="member")

        is_valid, error = await service.check_bot_access(
            channel_id=-100999999,
        )

        assert is_valid is False
        assert "administrator" in error.lower()

    @pytest.mark.asyncio
    async def test_check_bot_access_channel_not_found(self, service, mock_bot):
        """Should return False when channel not found."""
        mock_bot.get_chat_member.side_effect = TelegramBadRequest(
            method="getChatMember", message="Chat not found"
        )

        is_valid, error = await service.check_bot_access(
            channel_id=-100999999,
        )

        assert is_valid is False
        assert "not found" in error.lower()


# =============================================================================
# Test Constants
# =============================================================================


class TestConstants:
    """Test constant values."""

    def test_subscribed_statuses(self):
        """Should include correct subscribed statuses."""
        assert "member" in SUBSCRIBED_STATUSES
        assert "administrator" in SUBSCRIBED_STATUSES
        assert "creator" in SUBSCRIBED_STATUSES

    def test_not_subscribed_statuses(self):
        """Should include correct not-subscribed statuses."""
        assert "left" in NOT_SUBSCRIBED_STATUSES
        assert "kicked" in NOT_SUBSCRIBED_STATUSES
        assert "restricted" in NOT_SUBSCRIBED_STATUSES

    def test_cache_ttl_values(self):
        """Should have reasonable TTL values."""
        assert CACHE_TTL_SECONDS == 3600  # 1 hour
        assert CACHE_TTL_ERROR_SECONDS == 300  # 5 minutes
