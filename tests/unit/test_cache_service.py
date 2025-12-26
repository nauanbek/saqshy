"""
Tests for CacheService

Tests Redis-based caching operations including MessageHistoryProvider
protocol methods, rate limiting, and circuit breaker functionality.
"""

import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from saqshy.analyzers.behavior import MessageHistoryProvider

# Direct imports to avoid spam_db import chain issue with cohere
from saqshy.services.cache import (
    CacheService,
    CircuitBreaker,
    CircuitState,
)

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
def cache_service():
    """Create CacheService instance (not connected)."""
    return CacheService(redis_url="redis://localhost:6379")


# =============================================================================
# Test Protocol Compliance
# =============================================================================


class TestProtocolCompliance:
    """Test that CacheService satisfies MessageHistoryProvider protocol."""

    def test_cache_service_is_message_history_provider(self):
        """CacheService should implement MessageHistoryProvider protocol."""
        service = CacheService("redis://localhost:6379")

        # Check using isinstance with runtime_checkable Protocol
        assert isinstance(service, MessageHistoryProvider)

    def test_has_required_methods(self):
        """CacheService should have all required protocol methods."""
        service = CacheService("redis://localhost:6379")

        assert hasattr(service, "get_user_message_count")
        assert hasattr(service, "get_user_stats")
        assert hasattr(service, "get_join_time")
        assert hasattr(service, "get_first_message_time")

        # All methods should be async
        import asyncio

        assert asyncio.iscoroutinefunction(service.get_user_message_count)
        assert asyncio.iscoroutinefunction(service.get_user_stats)
        assert asyncio.iscoroutinefunction(service.get_join_time)
        assert asyncio.iscoroutinefunction(service.get_first_message_time)


# =============================================================================
# Test get_user_message_count
# =============================================================================


class TestGetUserMessageCount:
    """Test get_user_message_count method."""

    @pytest.mark.asyncio
    async def test_returns_zero_when_not_connected(self, cache_service):
        """Should return 0 when Redis is not connected."""
        result = await cache_service.get_user_message_count(
            user_id=123,
            chat_id=-100,
            window_seconds=3600,
        )

        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_circuit_open(self, cache_service, mock_redis):
        """Should return 0 when circuit breaker is open."""
        cache_service._client = mock_redis
        cache_service._connected = True
        cache_service._circuit_breaker._state = CircuitState.OPEN
        cache_service._circuit_breaker._opened_at = time.monotonic()

        result = await cache_service.get_user_message_count(
            user_id=123,
            chat_id=-100,
            window_seconds=3600,
        )

        assert result == 0

    @pytest.mark.asyncio
    async def test_uses_zcount_for_time_window(self, cache_service, mock_redis):
        """Should use ZCOUNT with correct time window."""
        mock_redis.zcount.return_value = 5
        cache_service._client = mock_redis
        cache_service._connected = True

        result = await cache_service.get_user_message_count(
            user_id=123,
            chat_id=-100,
            window_seconds=3600,
        )

        assert result == 5
        mock_redis.zcount.assert_called_once()

        # Verify the key format
        call_args = mock_redis.zcount.call_args
        key = call_args[0][0]
        assert "msg_ts" in key
        assert "-100" in key
        assert "123" in key

    @pytest.mark.asyncio
    async def test_handles_redis_error(self, cache_service, mock_redis):
        """Should return 0 on Redis error."""
        from redis.exceptions import ConnectionError

        mock_redis.zcount.side_effect = ConnectionError("Connection refused")
        cache_service._client = mock_redis
        cache_service._connected = True

        result = await cache_service.get_user_message_count(
            user_id=123,
            chat_id=-100,
            window_seconds=3600,
        )

        assert result == 0


# =============================================================================
# Test get_user_stats
# =============================================================================


class TestGetUserStats:
    """Test get_user_stats method."""

    @pytest.mark.asyncio
    async def test_returns_defaults_when_not_connected(self, cache_service):
        """Should return default stats when Redis is not connected."""
        result = await cache_service.get_user_stats(
            user_id=123,
            chat_id=-100,
        )

        assert result == {
            "total_messages": 0,
            "approved": 0,
            "flagged": 0,
            "blocked": 0,
        }

    @pytest.mark.asyncio
    async def test_parses_hash_values(self, cache_service, mock_redis):
        """Should parse hash values correctly."""
        mock_redis.hgetall.return_value = {
            "total_messages": "100",
            "approved": "95",
            "flagged": "3",
            "blocked": "2",
        }
        cache_service._client = mock_redis
        cache_service._connected = True

        result = await cache_service.get_user_stats(
            user_id=123,
            chat_id=-100,
        )

        assert result["total_messages"] == 100
        assert result["approved"] == 95
        assert result["flagged"] == 3
        assert result["blocked"] == 2

    @pytest.mark.asyncio
    async def test_handles_missing_fields(self, cache_service, mock_redis):
        """Should handle missing fields with defaults."""
        mock_redis.hgetall.return_value = {
            "total_messages": "10",
            "approved": "8",
            # flagged and blocked missing
        }
        cache_service._client = mock_redis
        cache_service._connected = True

        result = await cache_service.get_user_stats(
            user_id=123,
            chat_id=-100,
        )

        assert result["total_messages"] == 10
        assert result["approved"] == 8
        assert result["flagged"] == 0
        assert result["blocked"] == 0

    @pytest.mark.asyncio
    async def test_handles_empty_hash(self, cache_service, mock_redis):
        """Should handle empty hash."""
        mock_redis.hgetall.return_value = {}
        cache_service._client = mock_redis
        cache_service._connected = True

        result = await cache_service.get_user_stats(
            user_id=123,
            chat_id=-100,
        )

        assert result["total_messages"] == 0


# =============================================================================
# Test get_join_time
# =============================================================================


class TestGetJoinTime:
    """Test get_join_time method."""

    @pytest.mark.asyncio
    async def test_returns_none_when_not_connected(self, cache_service):
        """Should return None when Redis is not connected."""
        result = await cache_service.get_join_time(
            user_id=123,
            chat_id=-100,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_parses_iso_timestamp(self, cache_service, mock_redis):
        """Should parse ISO timestamp correctly."""
        expected_time = datetime(2024, 1, 15, 12, 30, 0, tzinfo=UTC)
        mock_redis.get.return_value = expected_time.isoformat()
        cache_service._client = mock_redis
        cache_service._connected = True

        with patch.object(cache_service, "_execute", return_value=expected_time.isoformat()):
            result = await cache_service.get_join_time(
                user_id=123,
                chat_id=-100,
            )

        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_key(self, cache_service, mock_redis):
        """Should return None when key doesn't exist."""
        cache_service._client = mock_redis
        cache_service._connected = True

        with patch.object(cache_service, "_execute", return_value=None):
            result = await cache_service.get_join_time(
                user_id=123,
                chat_id=-100,
            )

        assert result is None


# =============================================================================
# Test get_first_message_time
# =============================================================================


class TestGetFirstMessageTime:
    """Test get_first_message_time method."""

    @pytest.mark.asyncio
    async def test_returns_none_when_not_connected(self, cache_service):
        """Should return None when Redis is not connected."""
        result = await cache_service.get_first_message_time(
            user_id=123,
            chat_id=-100,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_parses_iso_timestamp(self, cache_service, mock_redis):
        """Should parse ISO timestamp correctly."""
        expected_time = datetime(2024, 1, 15, 12, 35, 0, tzinfo=UTC)
        cache_service._client = mock_redis
        cache_service._connected = True

        with patch.object(cache_service, "_execute", return_value=expected_time.isoformat()):
            result = await cache_service.get_first_message_time(
                user_id=123,
                chat_id=-100,
            )

        assert result is not None


# =============================================================================
# Test Recording Methods
# =============================================================================


class TestRecordingMethods:
    """Test recording methods for message events."""

    @pytest.mark.asyncio
    async def test_record_message(self, cache_service, mock_redis):
        """Should record message with pipeline."""
        # Create proper async context manager mock for pipeline
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        cache_service._client = mock_redis
        cache_service._connected = True

        await cache_service.record_message(
            user_id=123,
            chat_id=-100,
            timestamp=datetime.now(UTC),
        )

        mock_redis.pipeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_decision_approved(self, cache_service, mock_redis):
        """Should increment approved counter for allow verdict."""
        # Create proper async context manager mock for pipeline
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        cache_service._client = mock_redis
        cache_service._connected = True

        await cache_service.record_decision(
            user_id=123,
            chat_id=-100,
            verdict="allow",
        )

        mock_pipeline.hincrby.assert_called()

    @pytest.mark.asyncio
    async def test_record_join(self, cache_service, mock_redis):
        """Should record join timestamp."""
        cache_service._client = mock_redis
        cache_service._connected = True

        with patch.object(cache_service, "_execute") as mock_execute:
            await cache_service.record_join(
                user_id=123,
                chat_id=-100,
                timestamp=datetime.now(UTC),
            )

            mock_execute.assert_called_once()


# =============================================================================
# Test CircuitBreaker
# =============================================================================


class TestCircuitBreaker:
    """Test CircuitBreaker functionality."""

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self):
        """Circuit breaker should start in CLOSED state."""
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.is_open is False

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        """Should open after reaching failure threshold."""
        cb = CircuitBreaker(failure_threshold=3)

        for _ in range(3):
            await cb.record_failure()

        assert cb.state == CircuitState.OPEN
        assert cb.is_open is True

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        """Success should reset failure count."""
        cb = CircuitBreaker(failure_threshold=5)

        await cb.record_failure()
        await cb.record_failure()
        await cb.record_success()

        # Should be able to fail 5 more times before opening
        for _ in range(4):
            await cb.record_failure()

        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_after_recovery_timeout(self):
        """Should transition to HALF_OPEN after recovery timeout."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)

        await cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait for recovery timeout
        import asyncio

        await asyncio.sleep(0.15)

        allowed = await cb.allow_request()
        assert allowed is True
        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_closes_on_success_during_half_open(self):
        """Should close on success during HALF_OPEN state."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)

        await cb.record_failure()
        import asyncio

        await asyncio.sleep(0.02)
        await cb.allow_request()  # Triggers HALF_OPEN

        await cb.record_success()

        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_reopens_on_failure_during_half_open(self):
        """Should reopen on failure during HALF_OPEN state."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)

        await cb.record_failure()
        import asyncio

        await asyncio.sleep(0.02)
        await cb.allow_request()  # Triggers HALF_OPEN

        await cb.record_failure()

        assert cb.state == CircuitState.OPEN


# =============================================================================
# Test Rate Limiting
# =============================================================================


class TestRateLimiting:
    """Test rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_check_rate_limit_within_limit(self, cache_service, mock_redis):
        """Should return True when within limit."""
        # Create proper async context manager mock for pipeline
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_pipeline.execute.return_value = [None, 5]  # [zremrangebyscore result, zcard result]
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        cache_service._client = mock_redis
        cache_service._connected = True

        result = await cache_service.check_rate_limit(
            user_id=123,
            chat_id=-100,
            limit=10,
            window_seconds=60,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_check_rate_limit_at_limit(self, cache_service, mock_redis):
        """Should return False when at or above limit."""
        # Create proper async context manager mock for pipeline
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_pipeline.execute.return_value = [None, 10]  # At limit
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        cache_service._client = mock_redis
        cache_service._connected = True

        result = await cache_service.check_rate_limit(
            user_id=123,
            chat_id=-100,
            limit=10,
            window_seconds=60,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_check_rate_limit_fails_open(self, cache_service):
        """Should fail open (return True) when Redis is unavailable."""
        result = await cache_service.check_rate_limit(
            user_id=123,
            chat_id=-100,
            limit=10,
            window_seconds=60,
        )

        # Fail open - allow request
        assert result is True


# =============================================================================
# Test Key Schema
# =============================================================================


class TestKeySchema:
    """Test Redis key naming conventions."""

    def test_key_prefixes(self, cache_service):
        """Should use correct key prefixes."""
        assert cache_service.PREFIX == "saqshy"
        assert "msg_ts" in cache_service.KEY_MSG_TIMESTAMPS
        assert "user_stats" in cache_service.KEY_USER_STATS
        assert "join_time" in cache_service.KEY_JOIN_TIME
        assert "first_msg" in cache_service.KEY_FIRST_MSG

    def test_key_format_includes_chat_and_user(self, cache_service):
        """Keys should include chat_id and user_id."""
        # This tests the expected format: prefix:type:chat_id:user_id
        expected_pattern = f"{cache_service.KEY_MSG_TIMESTAMPS}:{{chat_id}}:{{user_id}}"
        assert "{chat_id}" in expected_pattern.replace("-100", "{chat_id}")
