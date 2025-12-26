"""
Tests for SignalCache

Tests Redis-based caching of profile and behavior signals.
"""

from unittest.mock import AsyncMock, patch

import pytest

from saqshy.analyzers.signals import (
    TTL_BEHAVIOR_SIGNALS,
    TTL_PROFILE_SIGNALS,
    SignalCache,
)
from saqshy.core.types import BehaviorSignals, ProfileSignals
from saqshy.services.cache import CacheService

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_redis():
    """Create mock Redis client."""
    mock = AsyncMock()
    mock.ping.return_value = True
    return mock


@pytest.fixture
def mock_cache_service(mock_redis):
    """Create mock CacheService with connected Redis."""
    cache = CacheService(redis_url="redis://localhost:6379")
    cache._client = mock_redis
    cache._connected = True
    return cache


@pytest.fixture
def signal_cache(mock_cache_service):
    """Create SignalCache with mock cache."""
    return SignalCache(mock_cache_service)


@pytest.fixture
def disconnected_signal_cache():
    """Create SignalCache without connected Redis."""
    cache = CacheService(redis_url="redis://localhost:6379")
    cache._connected = False
    return SignalCache(cache)


# =============================================================================
# Test Profile Signals Caching
# =============================================================================


class TestProfileSignalsCache:
    """Test profile signals caching."""

    @pytest.mark.asyncio
    async def test_get_profile_signals_returns_none_when_disconnected(
        self, disconnected_signal_cache
    ):
        """Should return None when Redis is not connected."""
        result = await disconnected_signal_cache.get_profile_signals(user_id=123)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_profile_signals_returns_none_when_not_cached(
        self, signal_cache, mock_cache_service
    ):
        """Should return None when signals are not cached."""
        with patch.object(mock_cache_service, "get_json", return_value=None):
            result = await signal_cache.get_profile_signals(user_id=123)
            assert result is None

    @pytest.mark.asyncio
    async def test_get_profile_signals_returns_cached(self, signal_cache, mock_cache_service):
        """Should return cached ProfileSignals."""
        cached_data = {
            "account_age_days": 365,
            "has_username": True,
            "has_profile_photo": True,
            "has_bio": False,
            "has_first_name": True,
            "has_last_name": False,
            "is_premium": True,
            "is_bot": False,
            "username_has_random_chars": False,
            "bio_has_links": False,
            "bio_has_crypto_terms": False,
            "name_has_emoji_spam": False,
        }

        with patch.object(mock_cache_service, "get_json", return_value=cached_data):
            result = await signal_cache.get_profile_signals(user_id=123)

            assert result is not None
            assert result.account_age_days == 365
            assert result.has_username is True
            assert result.is_premium is True

    @pytest.mark.asyncio
    async def test_set_profile_signals_when_disconnected(self, disconnected_signal_cache):
        """Should not raise when disconnected."""
        signals = ProfileSignals(account_age_days=100, has_username=True)
        # Should complete without error
        await disconnected_signal_cache.set_profile_signals(user_id=123, signals=signals)

    @pytest.mark.asyncio
    async def test_set_profile_signals_with_correct_ttl(self, signal_cache, mock_cache_service):
        """Should set signals with correct TTL."""
        signals = ProfileSignals(account_age_days=100, has_username=True)

        with patch.object(mock_cache_service, "set_json") as mock_set:
            await signal_cache.set_profile_signals(user_id=123, signals=signals)

            mock_set.assert_called_once()
            call_args = mock_set.call_args
            assert call_args.kwargs["ttl"] == TTL_PROFILE_SIGNALS

    @pytest.mark.asyncio
    async def test_invalidate_profile(self, signal_cache, mock_cache_service):
        """Should delete cached profile signals."""
        with patch.object(mock_cache_service, "delete") as mock_delete:
            await signal_cache.invalidate_profile(user_id=123)

            mock_delete.assert_called_once()
            key = mock_delete.call_args[0][0]
            assert "profile" in key
            assert "123" in key


# =============================================================================
# Test Behavior Signals Caching
# =============================================================================


class TestBehaviorSignalsCache:
    """Test behavior signals caching."""

    @pytest.mark.asyncio
    async def test_get_behavior_signals_returns_none_when_disconnected(
        self, disconnected_signal_cache
    ):
        """Should return None when Redis is not connected."""
        result = await disconnected_signal_cache.get_behavior_signals(user_id=123, chat_id=-100456)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_behavior_signals_returns_none_when_not_cached(
        self, signal_cache, mock_cache_service
    ):
        """Should return None when signals are not cached."""
        with patch.object(mock_cache_service, "get_json", return_value=None):
            result = await signal_cache.get_behavior_signals(user_id=123, chat_id=-100456)
            assert result is None

    @pytest.mark.asyncio
    async def test_get_behavior_signals_returns_cached(self, signal_cache, mock_cache_service):
        """Should return cached BehaviorSignals."""
        cached_data = {
            "time_to_first_message_seconds": 30,
            "messages_in_last_hour": 5,
            "messages_in_last_24h": 20,
            "join_to_message_seconds": 60,
            "previous_messages_approved": 15,
            "previous_messages_flagged": 1,
            "previous_messages_blocked": 0,
            "is_first_message": False,
            "is_channel_subscriber": True,
            "channel_subscription_duration_days": 30,
            "is_reply": False,
            "is_reply_to_admin": False,
            "mentioned_users_count": 0,
        }

        with patch.object(mock_cache_service, "get_json", return_value=cached_data):
            result = await signal_cache.get_behavior_signals(user_id=123, chat_id=-100456)

            assert result is not None
            assert result.time_to_first_message_seconds == 30
            assert result.is_channel_subscriber is True
            assert result.previous_messages_approved == 15

    @pytest.mark.asyncio
    async def test_set_behavior_signals_with_correct_ttl(self, signal_cache, mock_cache_service):
        """Should set signals with correct TTL."""
        signals = BehaviorSignals(
            messages_in_last_hour=10,
            is_first_message=False,
        )

        with patch.object(mock_cache_service, "set_json") as mock_set:
            await signal_cache.set_behavior_signals(user_id=123, chat_id=-100456, signals=signals)

            mock_set.assert_called_once()
            call_args = mock_set.call_args
            assert call_args.kwargs["ttl"] == TTL_BEHAVIOR_SIGNALS

    @pytest.mark.asyncio
    async def test_invalidate_behavior(self, signal_cache, mock_cache_service):
        """Should delete cached behavior signals."""
        with patch.object(mock_cache_service, "delete") as mock_delete:
            await signal_cache.invalidate_behavior(user_id=123, chat_id=-100456)

            mock_delete.assert_called_once()
            key = mock_delete.call_args[0][0]
            assert "behavior" in key
            assert "-100456" in key
            assert "123" in key


# =============================================================================
# Test Key Schema
# =============================================================================


class TestKeySchema:
    """Test Redis key naming conventions."""

    def test_profile_key_format(self, signal_cache):
        """Profile key should include user_id."""
        assert "profile" in signal_cache.KEY_PROFILE
        assert signal_cache.PREFIX == "saqshy:signals"

    def test_behavior_key_format(self, signal_cache):
        """Behavior key should include chat_id and user_id."""
        assert "behavior" in signal_cache.KEY_BEHAVIOR


# =============================================================================
# Test TTL Constants
# =============================================================================


class TestTTLConstants:
    """Test TTL configuration."""

    def test_profile_ttl(self):
        """Profile signals should have 5 minute TTL."""
        assert TTL_PROFILE_SIGNALS == 300

    def test_behavior_ttl(self):
        """Behavior signals should have 1 minute TTL."""
        assert TTL_BEHAVIOR_SIGNALS == 60

    def test_behavior_ttl_shorter_than_profile(self):
        """Behavior TTL should be shorter than profile TTL."""
        assert TTL_BEHAVIOR_SIGNALS < TTL_PROFILE_SIGNALS


# =============================================================================
# Test Error Handling
# =============================================================================


class TestErrorHandling:
    """Test error handling in SignalCache."""

    @pytest.mark.asyncio
    async def test_get_profile_signals_handles_exception(self, signal_cache, mock_cache_service):
        """Should return None on exception."""
        with patch.object(mock_cache_service, "get_json", side_effect=Exception("Redis error")):
            result = await signal_cache.get_profile_signals(user_id=123)
            assert result is None

    @pytest.mark.asyncio
    async def test_set_profile_signals_handles_exception(self, signal_cache, mock_cache_service):
        """Should not raise on exception."""
        signals = ProfileSignals()
        with patch.object(mock_cache_service, "set_json", side_effect=Exception("Redis error")):
            # Should complete without raising
            await signal_cache.set_profile_signals(user_id=123, signals=signals)

    @pytest.mark.asyncio
    async def test_get_behavior_signals_handles_exception(self, signal_cache, mock_cache_service):
        """Should return None on exception."""
        with patch.object(mock_cache_service, "get_json", side_effect=Exception("Redis error")):
            result = await signal_cache.get_behavior_signals(user_id=123, chat_id=-100456)
            assert result is None

    @pytest.mark.asyncio
    async def test_set_behavior_signals_handles_exception(self, signal_cache, mock_cache_service):
        """Should not raise on exception."""
        signals = BehaviorSignals()
        with patch.object(mock_cache_service, "set_json", side_effect=Exception("Redis error")):
            # Should complete without raising
            await signal_cache.set_behavior_signals(user_id=123, chat_id=-100456, signals=signals)


# =============================================================================
# Test Custom TTL Configuration
# =============================================================================


class TestCustomTTL:
    """Test custom TTL configuration."""

    @pytest.mark.asyncio
    async def test_custom_profile_ttl(self, mock_cache_service):
        """Should use custom profile TTL."""
        cache = SignalCache(mock_cache_service, profile_ttl=600)
        signals = ProfileSignals()

        with patch.object(mock_cache_service, "set_json") as mock_set:
            await cache.set_profile_signals(user_id=123, signals=signals)

            call_args = mock_set.call_args
            assert call_args.kwargs["ttl"] == 600

    @pytest.mark.asyncio
    async def test_custom_behavior_ttl(self, mock_cache_service):
        """Should use custom behavior TTL."""
        cache = SignalCache(mock_cache_service, behavior_ttl=120)
        signals = BehaviorSignals()

        with patch.object(mock_cache_service, "set_json") as mock_set:
            await cache.set_behavior_signals(user_id=123, chat_id=-100456, signals=signals)

            call_args = mock_set.call_args
            assert call_args.kwargs["ttl"] == 120
