"""
Tests for NetworkAnalyzer Service

Tests Redis-based cross-group behavior tracking including:
- Message hash generation and duplicate detection
- Ban and flag history tracking
- Global blocklist/whitelist management
- Full network analysis integration
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from saqshy.core.types import NetworkSignals
from saqshy.services.cache import CacheService, CircuitState
from saqshy.services.network import (
    TTL_BAN_HISTORY,
    TTL_FLAG_HISTORY,
    TTL_MESSAGE_HASH,
    TTL_USER_GROUPS,
    NetworkAnalyzer,
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
def mock_cache_service(mock_redis):
    """Create mock CacheService with connected Redis."""
    cache = CacheService(redis_url="redis://localhost:6379")
    cache._client = mock_redis
    cache._connected = True
    return cache


@pytest.fixture
def network_analyzer(mock_cache_service):
    """Create NetworkAnalyzer with mock cache."""
    return NetworkAnalyzer(mock_cache_service)


@pytest.fixture
def disconnected_network_analyzer():
    """Create NetworkAnalyzer without connected Redis."""
    cache = CacheService(redis_url="redis://localhost:6379")
    cache._connected = False
    return NetworkAnalyzer(cache)


# =============================================================================
# Test Message Hash Generation
# =============================================================================


class TestMessageHash:
    """Test message hash generation."""

    def test_hash_empty_text(self):
        """Should return empty string for empty text."""
        assert NetworkAnalyzer.hash_message("") == ""
        assert NetworkAnalyzer.hash_message(None) == ""

    def test_hash_consistency(self):
        """Same text should produce same hash."""
        text = "Buy crypto now! Best investment!"
        hash1 = NetworkAnalyzer.hash_message(text)
        hash2 = NetworkAnalyzer.hash_message(text)
        assert hash1 == hash2
        assert len(hash1) == 16  # Truncated SHA-256

    def test_hash_normalization(self):
        """Hash should normalize whitespace and case."""
        text1 = "Buy Crypto Now"
        text2 = "buy crypto now"
        text3 = "  BUY   CRYPTO   NOW  "

        hash1 = NetworkAnalyzer.hash_message(text1)
        hash2 = NetworkAnalyzer.hash_message(text2)
        hash3 = NetworkAnalyzer.hash_message(text3)

        assert hash1 == hash2 == hash3

    def test_hash_different_texts(self):
        """Different texts should produce different hashes."""
        hash1 = NetworkAnalyzer.hash_message("Hello world")
        hash2 = NetworkAnalyzer.hash_message("Goodbye world")
        assert hash1 != hash2


# =============================================================================
# Test Cross-Group Duplicate Detection
# =============================================================================


class TestDuplicateDetection:
    """Test cross-group duplicate message detection."""

    @pytest.mark.asyncio
    async def test_returns_zero_when_disconnected(self, disconnected_network_analyzer):
        """Should return 0 when Redis is not connected."""
        result = await disconnected_network_analyzer.record_message(
            message_hash="abc123",
            chat_id=-100123,
            user_id=456,
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_hash(self, network_analyzer):
        """Should return 0 for empty message hash."""
        result = await network_analyzer.record_message(
            message_hash="",
            chat_id=-100123,
            user_id=456,
        )
        assert result == 0

    @pytest.mark.asyncio
    async def test_records_message_with_pipeline(self, network_analyzer, mock_redis):
        """Should use pipeline for atomic message recording."""
        # Setup pipeline mock
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_pipeline.execute.return_value = [
            1,
            True,
            3,
            1,
            True,
        ]  # sadd, expire, scard, sadd, expire
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        result = await network_analyzer.record_message(
            message_hash="abc123",
            chat_id=-100123,
            user_id=456,
        )

        mock_redis.pipeline.assert_called_once()
        mock_pipeline.sadd.assert_called()  # For both message and user groups
        mock_pipeline.expire.assert_called()

        # Should return other groups count (scard - 1 = 3 - 1 = 2)
        assert result == 2

    @pytest.mark.asyncio
    async def test_first_message_returns_zero(self, network_analyzer, mock_redis):
        """First occurrence should return 0 other groups."""
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_pipeline.execute.return_value = [1, True, 1, 1, True]  # Only 1 group (current)
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        result = await network_analyzer.record_message(
            message_hash="abc123",
            chat_id=-100123,
            user_id=456,
        )

        assert result == 0

    @pytest.mark.asyncio
    async def test_get_message_group_count(self, network_analyzer, mock_redis):
        """Should return correct group count."""
        mock_redis.scard.return_value = 5

        result = await network_analyzer.get_message_group_count("abc123")

        assert result == 5
        mock_redis.scard.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_message_group_count_empty_hash(self, network_analyzer):
        """Should return 0 for empty hash."""
        result = await network_analyzer.get_message_group_count("")
        assert result == 0


# =============================================================================
# Test Ban and Flag Tracking
# =============================================================================


class TestBanTracking:
    """Test ban history tracking."""

    @pytest.mark.asyncio
    async def test_record_ban(self, network_analyzer, mock_redis):
        """Should record ban with pipeline and TTL."""
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        await network_analyzer.record_ban(user_id=123, chat_id=-100456)

        mock_redis.pipeline.assert_called_once()
        mock_pipeline.sadd.assert_called()
        mock_pipeline.expire.assert_called()

        # Verify TTL is set correctly
        expire_call = mock_pipeline.expire.call_args
        assert expire_call[0][1] == TTL_BAN_HISTORY

    @pytest.mark.asyncio
    async def test_record_ban_when_disconnected(self, disconnected_network_analyzer):
        """Should not raise when disconnected."""
        # Should complete without error
        await disconnected_network_analyzer.record_ban(user_id=123, chat_id=-100456)

    @pytest.mark.asyncio
    async def test_get_ban_count(self, network_analyzer, mock_redis):
        """Should return correct ban count."""
        mock_redis.scard.return_value = 3

        result = await network_analyzer.get_ban_count(user_id=123)

        assert result == 3


class TestFlagTracking:
    """Test flag history tracking."""

    @pytest.mark.asyncio
    async def test_record_flag(self, network_analyzer, mock_redis):
        """Should record flag with pipeline and TTL."""
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        await network_analyzer.record_flag(user_id=123, chat_id=-100456)

        mock_redis.pipeline.assert_called_once()

        # Verify TTL is flag history TTL
        expire_call = mock_pipeline.expire.call_args
        assert expire_call[0][1] == TTL_FLAG_HISTORY

    @pytest.mark.asyncio
    async def test_get_flag_count(self, network_analyzer, mock_redis):
        """Should return correct flag count."""
        mock_redis.scard.return_value = 2

        result = await network_analyzer.get_flag_count(user_id=123)

        assert result == 2


class TestGroupsInCommon:
    """Test groups in common tracking."""

    @pytest.mark.asyncio
    async def test_get_groups_in_common(self, network_analyzer, mock_redis):
        """Should return count of common groups."""
        mock_redis.scard.return_value = 7

        result = await network_analyzer.get_groups_in_common(user_id=123)

        assert result == 7

    @pytest.mark.asyncio
    async def test_get_groups_in_common_when_disconnected(self, disconnected_network_analyzer):
        """Should return 0 when disconnected."""
        result = await disconnected_network_analyzer.get_groups_in_common(user_id=123)
        assert result == 0


# =============================================================================
# Test Global Blocklist/Whitelist
# =============================================================================


class TestBlocklist:
    """Test global blocklist management."""

    @pytest.mark.asyncio
    async def test_add_to_blocklist(self, network_analyzer, mock_redis):
        """Should add user to blocklist."""
        mock_redis.sadd.return_value = 1

        result = await network_analyzer.add_to_blocklist(user_id=123)

        assert result is True
        mock_redis.sadd.assert_called_with(NetworkAnalyzer.KEY_BLOCKLIST, "123")

    @pytest.mark.asyncio
    async def test_add_to_blocklist_already_exists(self, network_analyzer, mock_redis):
        """Should return False if already in blocklist."""
        mock_redis.sadd.return_value = 0  # Already exists

        result = await network_analyzer.add_to_blocklist(user_id=123)

        assert result is False

    @pytest.mark.asyncio
    async def test_remove_from_blocklist(self, network_analyzer, mock_redis):
        """Should remove user from blocklist."""
        mock_redis.srem.return_value = 1

        result = await network_analyzer.remove_from_blocklist(user_id=123)

        assert result is True
        mock_redis.srem.assert_called_with(NetworkAnalyzer.KEY_BLOCKLIST, "123")

    @pytest.mark.asyncio
    async def test_is_blocklisted_true(self, network_analyzer, mock_redis):
        """Should return True if blocklisted."""
        mock_redis.sismember.return_value = True

        result = await network_analyzer.is_blocklisted(user_id=123)

        assert result is True

    @pytest.mark.asyncio
    async def test_is_blocklisted_false(self, network_analyzer, mock_redis):
        """Should return False if not blocklisted."""
        mock_redis.sismember.return_value = False

        result = await network_analyzer.is_blocklisted(user_id=123)

        assert result is False

    @pytest.mark.asyncio
    async def test_is_blocklisted_when_disconnected(self, disconnected_network_analyzer):
        """Should return False when disconnected (fail safe)."""
        result = await disconnected_network_analyzer.is_blocklisted(user_id=123)
        assert result is False


class TestWhitelist:
    """Test global whitelist management."""

    @pytest.mark.asyncio
    async def test_add_to_whitelist(self, network_analyzer, mock_redis):
        """Should add user to whitelist."""
        mock_redis.sadd.return_value = 1

        result = await network_analyzer.add_to_whitelist(user_id=123)

        assert result is True
        mock_redis.sadd.assert_called_with(NetworkAnalyzer.KEY_WHITELIST, "123")

    @pytest.mark.asyncio
    async def test_remove_from_whitelist(self, network_analyzer, mock_redis):
        """Should remove user from whitelist."""
        mock_redis.srem.return_value = 1

        result = await network_analyzer.remove_from_whitelist(user_id=123)

        assert result is True

    @pytest.mark.asyncio
    async def test_is_whitelisted_true(self, network_analyzer, mock_redis):
        """Should return True if whitelisted."""
        mock_redis.sismember.return_value = True

        result = await network_analyzer.is_whitelisted(user_id=123)

        assert result is True

    @pytest.mark.asyncio
    async def test_is_whitelisted_false(self, network_analyzer, mock_redis):
        """Should return False if not whitelisted."""
        mock_redis.sismember.return_value = False

        result = await network_analyzer.is_whitelisted(user_id=123)

        assert result is False


# =============================================================================
# Test Full Network Analysis
# =============================================================================


class TestAnalyze:
    """Test full network analysis method."""

    @pytest.mark.asyncio
    async def test_analyze_returns_default_when_disconnected(self, disconnected_network_analyzer):
        """Should return default signals when disconnected."""
        result = await disconnected_network_analyzer.analyze(
            user_id=123,
            chat_id=-100456,
            text="Hello world",
        )

        assert isinstance(result, NetworkSignals)
        assert result.groups_in_common == 0
        assert result.duplicate_messages_in_other_groups == 0

    @pytest.mark.asyncio
    async def test_analyze_blocklisted_user(self, network_analyzer, mock_redis):
        """Should return blocklist signal for blocklisted users."""
        mock_redis.sismember.return_value = True  # Is blocklisted

        result = await network_analyzer.analyze(
            user_id=123,
            chat_id=-100456,
            text="Hello world",
        )

        assert result.is_in_global_blocklist is True

    @pytest.mark.asyncio
    async def test_analyze_whitelisted_user(self, network_analyzer, mock_redis):
        """Should return whitelist signal for whitelisted users."""
        # Not blocklisted, but whitelisted
        mock_redis.sismember.side_effect = [False, True]  # blocklist check, whitelist check
        mock_redis.scard.return_value = 5  # groups in common

        # Setup pipeline for message recording
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_pipeline.execute.return_value = [1, True, 1, 1, True]
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        result = await network_analyzer.analyze(
            user_id=123,
            chat_id=-100456,
            text="Hello world",
        )

        assert result.is_in_global_whitelist is True
        assert result.is_in_global_blocklist is False

    @pytest.mark.asyncio
    async def test_analyze_with_spam_db_similarity(self, network_analyzer, mock_redis):
        """Should include spam DB results in signals."""
        mock_redis.sismember.return_value = False  # Not in lists
        mock_redis.scard.return_value = 3

        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_pipeline.execute.return_value = [1, True, 1, 1, True]
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        result = await network_analyzer.analyze(
            user_id=123,
            chat_id=-100456,
            text="Spam message",
            spam_db_similarity=0.92,
            spam_db_matched_pattern="Known spam pattern",
        )

        assert result.spam_db_similarity == 0.92
        assert result.spam_db_matched_pattern == "Known spam pattern"

    @pytest.mark.asyncio
    async def test_analyze_with_duplicates(self, network_analyzer, mock_redis):
        """Should detect cross-group duplicates."""
        mock_redis.sismember.return_value = False
        mock_redis.scard.return_value = 2  # groups in common

        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_pipeline.execute.return_value = [0, True, 4, 1, True]  # 4 groups = 3 other
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        result = await network_analyzer.analyze(
            user_id=123,
            chat_id=-100456,
            text="Duplicate spam message",
        )

        assert result.duplicate_messages_in_other_groups == 3

    @pytest.mark.asyncio
    async def test_analyze_without_text(self, network_analyzer, mock_redis):
        """Should work without text (no duplicate detection)."""
        mock_redis.sismember.return_value = False
        mock_redis.scard.return_value = 5

        result = await network_analyzer.analyze(
            user_id=123,
            chat_id=-100456,
            text=None,
        )

        assert result.duplicate_messages_in_other_groups == 0
        assert result.groups_in_common == 5


# =============================================================================
# Test Utility Methods
# =============================================================================


class TestUtilityMethods:
    """Test utility methods."""

    @pytest.mark.asyncio
    async def test_flush_user_network_data(self, network_analyzer, mock_redis):
        """Should delete all user network keys."""
        await network_analyzer.flush_user_network_data(user_id=123)

        mock_redis.delete.assert_called_once()
        # Should delete 4 keys: groups, bans, flags, reputation
        args = mock_redis.delete.call_args[0]
        assert len(args) == 4
        assert any("groups" in arg for arg in args)
        assert any("bans" in arg for arg in args)
        assert any("flags" in arg for arg in args)
        assert any("reputation" in arg for arg in args)

    @pytest.mark.asyncio
    async def test_get_stats(self, network_analyzer, mock_redis):
        """Should return stats with list sizes."""
        mock_redis.scard.side_effect = [100, 50]  # blocklist, whitelist

        result = await network_analyzer.get_stats()

        assert result["available"] is True
        assert result["blocklist_size"] == 100
        assert result["whitelist_size"] == 50

    @pytest.mark.asyncio
    async def test_get_stats_when_disconnected(self, disconnected_network_analyzer):
        """Should return unavailable status when disconnected."""
        result = await disconnected_network_analyzer.get_stats()

        assert result["available"] is False
        assert result["blocklist_size"] == 0


# =============================================================================
# Test Circuit Breaker Integration
# =============================================================================


class TestCircuitBreakerIntegration:
    """Test circuit breaker behavior with NetworkAnalyzer."""

    @pytest.mark.asyncio
    async def test_fails_safe_when_circuit_open(self, network_analyzer, mock_redis):
        """Should return safe defaults when circuit breaker is open."""
        # Open the circuit breaker
        network_analyzer._circuit_breaker._state = CircuitState.OPEN
        network_analyzer._circuit_breaker._opened_at = time.monotonic()

        # All operations should return safe defaults
        result = await network_analyzer.is_blocklisted(user_id=123)
        assert result is False  # Fail safe - not blocklisted

        count = await network_analyzer.get_ban_count(user_id=123)
        assert count == 0

        signals = await network_analyzer.analyze(
            user_id=123,
            chat_id=-100456,
            text="Test",
        )
        assert signals.groups_in_common == 0

    @pytest.mark.asyncio
    async def test_records_failure_on_redis_error(self, network_analyzer, mock_redis):
        """Should record failure on Redis error."""
        from redis.exceptions import ConnectionError

        mock_redis.scard.side_effect = ConnectionError("Connection lost")

        result = await network_analyzer.get_ban_count(user_id=123)

        assert result == 0
        # Circuit breaker should have recorded the failure
        assert network_analyzer._circuit_breaker._failure_count > 0


# =============================================================================
# Test Key Schema
# =============================================================================


class TestKeySchema:
    """Test Redis key naming conventions."""

    def test_key_prefixes(self, network_analyzer):
        """Should use correct key prefixes."""
        assert network_analyzer.PREFIX == "saqshy:net"
        assert "msg" in network_analyzer.KEY_MESSAGE
        assert "user" in network_analyzer.KEY_USER
        assert "blocklist" in network_analyzer.KEY_BLOCKLIST
        assert "whitelist" in network_analyzer.KEY_WHITELIST

    def test_keys_are_namespaced(self, network_analyzer):
        """All keys should be under saqshy:net namespace."""
        assert network_analyzer.KEY_MESSAGE.startswith("saqshy:net:")
        assert network_analyzer.KEY_USER.startswith("saqshy:net:")
        assert network_analyzer.KEY_BLOCKLIST.startswith("saqshy:net:")
        assert network_analyzer.KEY_WHITELIST.startswith("saqshy:net:")


# =============================================================================
# Test TTL Constants
# =============================================================================


class TestTTLConstants:
    """Test TTL configuration."""

    def test_message_hash_ttl(self):
        """Message hashes should expire in 24 hours."""
        assert TTL_MESSAGE_HASH == 86400

    def test_ban_history_ttl(self):
        """Ban history should expire in 30 days."""
        assert TTL_BAN_HISTORY == 86400 * 30

    def test_flag_history_ttl(self):
        """Flag history should expire in 14 days."""
        assert TTL_FLAG_HISTORY == 86400 * 14

    def test_user_groups_ttl(self):
        """User groups should expire in 7 days."""
        assert TTL_USER_GROUPS == 86400 * 7
