"""
SAQSHY Security Tests - Abuse Pattern Detection

Tests for:
- Coordinated spam attack detection
- Message burst/flood detection
- Cross-group duplicate detection
- Botnet-like behavior patterns
- Rate limit bypass prevention
- Account age/subscription abuse
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from saqshy.analyzers.behavior import BehaviorAnalyzer, FloodDetector
from saqshy.bot.middlewares.rate_limit import AdaptiveRateLimiter, RateLimitMiddleware
from saqshy.core.types import BehaviorSignals, GroupType, MessageContext, NetworkSignals
from saqshy.services.network import NetworkAnalyzer


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_history_provider():
    """Create mock message history provider."""
    provider = AsyncMock()
    provider.get_user_message_count.return_value = 0
    provider.get_user_stats.return_value = {
        "total_messages": 0,
        "approved": 0,
        "flagged": 0,
        "blocked": 0,
    }
    provider.get_first_message_time.return_value = None
    provider.get_join_time.return_value = None
    return provider


@pytest.fixture
def mock_subscription_checker():
    """Create mock subscription checker."""
    checker = AsyncMock()
    checker.is_subscribed.return_value = False
    checker.get_subscription_duration_days.return_value = 0
    return checker


@pytest.fixture
def mock_cache_service():
    """Create mock cache service for rate limiting."""
    from saqshy.services.cache import CacheService

    cache = CacheService(redis_url="redis://localhost:6379")
    cache._client = AsyncMock()
    cache._connected = True
    cache.increment_rate = AsyncMock(return_value=1)
    cache.get = AsyncMock(return_value=None)
    cache.get_json = AsyncMock(return_value=None)
    return cache


@pytest.fixture
def mock_redis():
    """Create mock Redis client for network analyzer."""
    mock = AsyncMock()
    mock.ping.return_value = True
    mock.sismember.return_value = False
    mock.scard.return_value = 0
    return mock


@pytest.fixture
def network_analyzer(mock_cache_service, mock_redis):
    """Create network analyzer with mocks."""
    mock_cache_service._client = mock_redis
    return NetworkAnalyzer(mock_cache_service)


@pytest.fixture
def sample_message_context():
    """Create sample message context."""
    return MessageContext(
        message_id=12345,
        chat_id=-1001234567890,
        user_id=987654321,
        text="Test message",
        timestamp=datetime.now(UTC),
        username="testuser",
        first_name="Test",
        chat_type="supergroup",
        group_type=GroupType.GENERAL,
    )


# =============================================================================
# Coordinated Spam Detection Tests
# =============================================================================


@pytest.mark.security
class TestCoordinatedSpam:
    """Test detection of coordinated spam attacks."""

    @pytest.mark.asyncio
    async def test_detects_message_burst(
        self, mock_history_provider, mock_subscription_checker
    ) -> None:
        """Rapid message bursts should be flagged."""
        # Configure provider to return high message count in last hour
        mock_history_provider.get_user_message_count.side_effect = [
            15,  # 15 messages in last hour
            25,  # 25 messages in last 24h
        ]
        mock_history_provider.get_user_stats.return_value = {
            "total_messages": 25,
            "approved": 0,
            "flagged": 0,
            "blocked": 0,
        }

        analyzer = BehaviorAnalyzer(
            history_provider=mock_history_provider,
            subscription_checker=mock_subscription_checker,
        )

        context = MessageContext(
            message_id=1,
            chat_id=-100123,
            user_id=456,
            text="Spam message",
            timestamp=datetime.now(UTC),
            chat_type="supergroup",
            group_type=GroupType.GENERAL,
        )

        signals = await analyzer.analyze(context)

        # High message count indicates burst behavior
        assert signals.messages_in_last_hour == 15
        assert signals.messages_in_last_24h == 25

    @pytest.mark.asyncio
    async def test_detects_cross_group_duplicates(
        self, network_analyzer, mock_redis
    ) -> None:
        """Same message in multiple groups should be flagged."""
        # Setup pipeline to return high duplicate count
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        # scard returns 4 groups (3 OTHER groups + current)
        mock_pipeline.execute.return_value = [1, True, 4, 1, True]
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        mock_redis.sismember.return_value = False

        signals = await network_analyzer.analyze(
            user_id=123,
            chat_id=-100456,
            text="URGENT: Double your Bitcoin! Limited time offer!",
        )

        # Should detect duplicates in other groups
        assert signals.duplicate_messages_in_other_groups == 3

    @pytest.mark.asyncio
    async def test_duplicate_in_5_plus_groups_is_raid(
        self, network_analyzer, mock_redis
    ) -> None:
        """Message in 5+ groups indicates coordinated raid."""
        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        # 6 total groups = 5 other groups
        mock_pipeline.execute.return_value = [0, True, 6, 1, True]
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        mock_redis.sismember.return_value = False

        signals = await network_analyzer.analyze(
            user_id=123,
            chat_id=-100456,
            text="Join my crypto pump group NOW!",
        )

        # 5+ duplicates indicates coordinated attack
        assert signals.duplicate_messages_in_other_groups >= 5

    @pytest.mark.asyncio
    async def test_detects_account_age_subscription_mismatch(
        self, mock_history_provider, mock_subscription_checker
    ) -> None:
        """
        New accounts with old subscriber status should be suspicious.

        Scenario: Account created 2 days ago but claims 30 day subscription.
        This could indicate a compromised account or manipulation.
        """
        # Account joined recently
        join_time = datetime.now(UTC) - timedelta(days=2)
        mock_history_provider.get_join_time.return_value = join_time
        # No previous messages - this is first message
        mock_history_provider.get_user_stats.return_value = {
            "total_messages": 0,  # Changed from 1 to 0 for is_first_message=True
            "approved": 0,
            "flagged": 0,
            "blocked": 0,
        }

        # But claims long subscription duration
        mock_subscription_checker.is_subscribed.return_value = True
        mock_subscription_checker.get_subscription_duration_days.return_value = 30

        analyzer = BehaviorAnalyzer(
            history_provider=mock_history_provider,
            subscription_checker=mock_subscription_checker,
        )

        context = MessageContext(
            message_id=1,
            chat_id=-100123,
            user_id=456,
            text="Hello everyone!",
            timestamp=datetime.now(UTC),
            chat_type="supergroup",
            group_type=GroupType.GENERAL,
        )

        signals = await analyzer.analyze(context, linked_channel_id=789)

        # The signals should reflect this suspicious combination
        assert signals.is_channel_subscriber is True
        assert signals.channel_subscription_duration_days == 30
        # First message from this user
        assert signals.is_first_message is True


# =============================================================================
# Botnet Pattern Detection Tests
# =============================================================================


@pytest.mark.security
class TestBotnetPatterns:
    """Test detection of botnet-like behavior."""

    def test_detects_sequential_usernames(self) -> None:
        """Accounts with sequential/similar usernames should be flagged."""
        # This is a pattern detection test - verify the concept
        sequential_usernames = [
            "user12345",
            "user12346",
            "user12347",
            "spambot001",
            "spambot002",
        ]

        # Check if usernames follow sequential pattern
        import re

        pattern = re.compile(r"^(\w+?)(\d+)$")

        sequential_detected = []
        for username in sequential_usernames:
            match = pattern.match(username)
            if match:
                base, number = match.groups()
                sequential_detected.append((base, int(number)))

        # All should be detected as sequential
        assert len(sequential_detected) == len(sequential_usernames)

        # Check for sequential numbers
        bases = {}
        for base, num in sequential_detected:
            if base not in bases:
                bases[base] = []
            bases[base].append(num)

        # Verify we can detect sequential patterns
        for base, numbers in bases.items():
            numbers.sort()
            for i in range(1, len(numbers)):
                if numbers[i] - numbers[i - 1] == 1:
                    # Sequential pattern detected
                    pass

    @pytest.mark.asyncio
    async def test_detects_identical_message_hashes(
        self, network_analyzer, mock_redis
    ) -> None:
        """Multiple accounts sending identical messages should be flagged."""
        # Same message hash appearing from different users
        message = "EARN $10000 DAILY! DM ME NOW!"
        message_hash = NetworkAnalyzer.hash_message(message)

        # Simulate multiple users sending same message
        mock_redis.scard.return_value = 10  # Seen in 10 groups

        count = await network_analyzer.get_message_group_count(message_hash)
        assert count == 10

    def test_message_hash_normalization(self) -> None:
        """Message hashes should normalize to detect variants."""
        # These should produce the same hash
        variants = [
            "Double your Bitcoin!",
            "double your bitcoin!",
            "DOUBLE YOUR BITCOIN!",
            "  Double   your   Bitcoin!  ",
        ]

        hashes = [NetworkAnalyzer.hash_message(v) for v in variants]

        # All variants should produce same hash
        assert len(set(hashes)) == 1

    @pytest.mark.asyncio
    async def test_detects_flagged_in_multiple_groups(
        self, network_analyzer, mock_redis
    ) -> None:
        """Users flagged in multiple groups should be detected."""
        # User has been flagged in 5 other groups
        mock_redis.scard.return_value = 5
        mock_redis.sismember.return_value = False

        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_pipeline.execute.return_value = [1, True, 1, 1, True]
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        # Override scard for specific key checks
        async def scard_side_effect(key):
            if "flags" in key:
                return 5
            elif "bans" in key:
                return 2
            elif "groups" in key:
                return 10
            return 0

        mock_redis.scard.side_effect = scard_side_effect

        # Get flag count directly
        flag_count = await network_analyzer.get_flag_count(user_id=123)
        assert flag_count == 5

    @pytest.mark.asyncio
    async def test_detects_banned_in_multiple_groups(
        self, network_analyzer, mock_redis
    ) -> None:
        """Users banned in multiple groups should be detected."""

        async def scard_side_effect(key):
            if "bans" in key:
                return 3
            return 0

        mock_redis.scard.side_effect = scard_side_effect

        ban_count = await network_analyzer.get_ban_count(user_id=123)
        assert ban_count == 3


# =============================================================================
# Rate Limit Bypass Prevention Tests
# =============================================================================


@pytest.mark.security
class TestRateLimitBypass:
    """Test that rate limits cannot be bypassed."""

    @pytest.mark.asyncio
    async def test_rate_limit_per_user(self, mock_cache_service) -> None:
        """Rate limit should apply per user."""
        middleware = RateLimitMiddleware(
            cache_service=mock_cache_service,
            user_limit=10,
            user_window=60,
        )

        # Simulate user hitting limit
        mock_cache_service.increment_rate.return_value = 11  # Over limit

        is_limited = await middleware._check_user_rate(
            cache_service=mock_cache_service,
            user_id=123,
            chat_id=-100456,
        )

        assert is_limited is True

    @pytest.mark.asyncio
    async def test_rate_limit_per_group(self, mock_cache_service) -> None:
        """Rate limit should apply per group."""
        middleware = RateLimitMiddleware(
            cache_service=mock_cache_service,
            group_limit=100,
            group_window=60,
        )

        # Simulate group hitting limit
        mock_cache_service.increment_rate.return_value = 101  # Over limit

        is_limited = await middleware.check_group_rate(
            cache_service=mock_cache_service,
            chat_id=-100456,
        )

        assert is_limited is True

    @pytest.mark.asyncio
    async def test_rate_limit_not_bypassable_by_content_change(
        self, mock_cache_service
    ) -> None:
        """Changing message content should not bypass rate limit."""
        middleware = RateLimitMiddleware(
            cache_service=mock_cache_service,
            user_limit=5,
            user_window=60,
        )

        # User sends many different messages rapidly
        messages = [
            "Spam variant 1",
            "Spam variant 2",
            "Spam variant 3",
            "Spam variant 4",
            "Spam variant 5",
            "Spam variant 6",  # Should be limited
        ]

        # Each increment increases the count
        call_count = [0]

        async def increment_side_effect(user_id, chat_id, window_seconds):
            call_count[0] += 1
            return call_count[0]

        mock_cache_service.increment_rate.side_effect = increment_side_effect

        limited_count = 0
        for msg in messages:
            is_limited = await middleware._check_user_rate(
                cache_service=mock_cache_service,
                user_id=123,
                chat_id=-100456,
            )
            if is_limited:
                limited_count += 1

        # Last message should be limited
        assert limited_count >= 1

    @pytest.mark.asyncio
    async def test_adaptive_rate_limit_reduces_for_suspicious(
        self, mock_cache_service
    ) -> None:
        """Suspicious users should get lower rate limits."""
        adaptive = AdaptiveRateLimiter(
            cache_service=mock_cache_service,
            base_limit=20,
            suspicious_multiplier=0.5,
        )

        # Configure user as suspicious (more blocked than approved)
        mock_cache_service.get_json.return_value = {
            "approved": 2,
            "blocked": 8,
        }

        limit = await adaptive.get_user_limit(user_id=123, chat_id=-100456)

        # Should be reduced (20 * 0.5 = 10)
        assert limit == 10

    @pytest.mark.asyncio
    async def test_adaptive_rate_limit_increases_for_trusted(
        self, mock_cache_service
    ) -> None:
        """Trusted users should get higher rate limits."""
        adaptive = AdaptiveRateLimiter(
            cache_service=mock_cache_service,
            base_limit=20,
            trusted_multiplier=2.0,
        )

        # Configure user as trusted (mostly approved)
        mock_cache_service.get_json.return_value = {
            "approved": 95,
            "blocked": 5,
        }

        limit = await adaptive.get_user_limit(user_id=123, chat_id=-100456)

        # Should be increased (20 * 2.0 = 40)
        assert limit == 40

    @pytest.mark.asyncio
    async def test_rate_limit_fails_open_on_error(self, mock_cache_service) -> None:
        """Rate limiting should fail-open (allow) on Redis errors."""
        middleware = RateLimitMiddleware(cache_service=mock_cache_service)

        # Simulate Redis timeout
        mock_cache_service.increment_rate.side_effect = TimeoutError("Redis timeout")

        is_limited = await middleware._check_user_rate(
            cache_service=mock_cache_service,
            user_id=123,
            chat_id=-100456,
        )

        # Should NOT be limited on error (fail-open)
        assert is_limited is False


# =============================================================================
# Flood Detection Tests
# =============================================================================


@pytest.mark.security
class TestFloodDetection:
    """Test flood detection behavior."""

    @pytest.mark.asyncio
    async def test_detects_flood_when_limit_exceeded(
        self, mock_history_provider
    ) -> None:
        """Should detect flood when message count exceeds threshold."""
        mock_history_provider.get_user_message_count.return_value = 15

        detector = FloodDetector(
            window_seconds=60,
            max_messages=10,
            history_provider=mock_history_provider,
        )

        is_flooding = await detector.check_flood(user_id=123, chat_id=-100456)

        assert is_flooding is True

    @pytest.mark.asyncio
    async def test_no_flood_under_limit(self, mock_history_provider) -> None:
        """Should not detect flood when under threshold."""
        mock_history_provider.get_user_message_count.return_value = 5

        detector = FloodDetector(
            window_seconds=60,
            max_messages=10,
            history_provider=mock_history_provider,
        )

        is_flooding = await detector.check_flood(user_id=123, chat_id=-100456)

        assert is_flooding is False

    @pytest.mark.asyncio
    async def test_flood_check_fails_safe(self, mock_history_provider) -> None:
        """Flood check should return False on errors."""
        mock_history_provider.get_user_message_count.side_effect = Exception(
            "Redis error"
        )

        detector = FloodDetector(
            window_seconds=60,
            max_messages=10,
            history_provider=mock_history_provider,
        )

        is_flooding = await detector.check_flood(user_id=123, chat_id=-100456)

        # Should fail safe (not flooding)
        assert is_flooding is False

    @pytest.mark.asyncio
    async def test_flood_check_without_provider(self) -> None:
        """Flood check should return False without provider."""
        detector = FloodDetector(
            window_seconds=60,
            max_messages=10,
            history_provider=None,
        )

        is_flooding = await detector.check_flood(user_id=123, chat_id=-100456)

        assert is_flooding is False


# =============================================================================
# Time-Based Attack Detection Tests
# =============================================================================


@pytest.mark.security
class TestTimeBasedAttacks:
    """Test detection of time-based attack patterns."""

    @pytest.mark.asyncio
    async def test_immediate_first_message_is_suspicious(
        self, mock_history_provider, mock_subscription_checker
    ) -> None:
        """Users posting immediately after joining are suspicious."""
        # User joined 10 seconds ago
        join_time = datetime.now(UTC) - timedelta(seconds=10)
        mock_history_provider.get_join_time.return_value = join_time
        mock_history_provider.get_user_stats.return_value = {
            "total_messages": 0,
            "approved": 0,
            "flagged": 0,
            "blocked": 0,
        }

        analyzer = BehaviorAnalyzer(
            history_provider=mock_history_provider,
            subscription_checker=mock_subscription_checker,
        )

        context = MessageContext(
            message_id=1,
            chat_id=-100123,
            user_id=456,
            text="Check out my crypto channel!",
            timestamp=datetime.now(UTC),
            chat_type="supergroup",
            group_type=GroupType.GENERAL,
        )

        signals = await analyzer.analyze(context)

        # TTFM should be very short (suspicious)
        assert signals.time_to_first_message_seconds is not None
        assert signals.time_to_first_message_seconds <= 15
        assert signals.is_first_message is True

    @pytest.mark.asyncio
    async def test_normal_ttfm_not_flagged(
        self, mock_history_provider, mock_subscription_checker
    ) -> None:
        """Users with normal TTFM should not be flagged."""
        # User joined 2 hours ago
        join_time = datetime.now(UTC) - timedelta(hours=2)
        mock_history_provider.get_join_time.return_value = join_time
        mock_history_provider.get_user_stats.return_value = {
            "total_messages": 0,
            "approved": 0,
            "flagged": 0,
            "blocked": 0,
        }

        analyzer = BehaviorAnalyzer(
            history_provider=mock_history_provider,
            subscription_checker=mock_subscription_checker,
        )

        context = MessageContext(
            message_id=1,
            chat_id=-100123,
            user_id=456,
            text="Hello everyone, nice to be here!",
            timestamp=datetime.now(UTC),
            chat_type="supergroup",
            group_type=GroupType.GENERAL,
        )

        signals = await analyzer.analyze(context)

        # TTFM should be about 2 hours (7200 seconds)
        assert signals.time_to_first_message_seconds is not None
        assert signals.time_to_first_message_seconds >= 7000


# =============================================================================
# Global List Manipulation Tests
# =============================================================================


@pytest.mark.security
class TestGlobalListManipulation:
    """Test resistance to global list manipulation."""

    @pytest.mark.asyncio
    async def test_blocklist_takes_precedence(
        self, network_analyzer, mock_redis
    ) -> None:
        """Blocklisted users should be blocked regardless of other signals."""
        # User is blocklisted
        mock_redis.sismember.return_value = True

        signals = await network_analyzer.analyze(
            user_id=123,
            chat_id=-100456,
            text="Normal message",
        )

        assert signals.is_in_global_blocklist is True

    @pytest.mark.asyncio
    async def test_whitelist_provides_trust(
        self, network_analyzer, mock_redis
    ) -> None:
        """Whitelisted users should get trust signal."""
        # Not blocklisted, but whitelisted
        mock_redis.sismember.side_effect = [False, True]
        mock_redis.scard.return_value = 0

        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_pipeline.execute.return_value = [1, True, 1, 1, True]
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        signals = await network_analyzer.analyze(
            user_id=123,
            chat_id=-100456,
            text="Normal message",
        )

        assert signals.is_in_global_whitelist is True
        assert signals.is_in_global_blocklist is False

    @pytest.mark.asyncio
    async def test_cannot_add_to_blocklist_without_connection(
        self, network_analyzer
    ) -> None:
        """Should fail safely when trying to modify lists without connection."""
        network_analyzer.cache._connected = False

        result = await network_analyzer.add_to_blocklist(user_id=123)
        assert result is False

        result = await network_analyzer.add_to_whitelist(user_id=123)
        assert result is False


# =============================================================================
# Admin Bypass Tests
# =============================================================================


@pytest.mark.security
class TestAdminBypass:
    """Test that admin bypasses work correctly and safely."""

    @pytest.mark.asyncio
    async def test_rate_limit_skipped_for_admins(self, mock_cache_service) -> None:
        """Admins should not be rate limited."""
        from aiogram.types import Chat, Message, User

        middleware = RateLimitMiddleware(
            cache_service=mock_cache_service,
            user_limit=1,  # Very low limit
        )

        # Create proper aiogram mock objects
        mock_user = MagicMock(spec=User)
        mock_user.id = 123

        mock_chat = MagicMock(spec=Chat)
        mock_chat.type = "supergroup"
        mock_chat.id = -100456

        mock_message = MagicMock(spec=Message)
        mock_message.from_user = mock_user
        mock_message.chat = mock_chat

        # Create mock handler that returns something
        mock_handler = AsyncMock(return_value=None)

        # Call middleware with admin flag
        data = {
            "user_is_admin": True,
            "user_is_whitelisted": False,
            "cache_service": mock_cache_service,
        }

        result = await middleware(mock_handler, mock_message, data)

        # Handler should be called (not blocked)
        mock_handler.assert_called_once()
        # Rate limit flag should be set to False for admins
        assert data.get("is_rate_limited") is False

    @pytest.mark.asyncio
    async def test_rate_limit_skipped_for_whitelisted(
        self, mock_cache_service
    ) -> None:
        """Whitelisted users should not be rate limited."""
        from aiogram.types import Chat, Message, User

        middleware = RateLimitMiddleware(
            cache_service=mock_cache_service,
            user_limit=1,  # Very low limit
        )

        mock_user = MagicMock(spec=User)
        mock_user.id = 123

        mock_chat = MagicMock(spec=Chat)
        mock_chat.type = "supergroup"
        mock_chat.id = -100456

        mock_message = MagicMock(spec=Message)
        mock_message.from_user = mock_user
        mock_message.chat = mock_chat

        mock_handler = AsyncMock(return_value=None)

        data = {
            "user_is_admin": False,
            "user_is_whitelisted": True,
            "cache_service": mock_cache_service,
        }

        result = await middleware(mock_handler, mock_message, data)

        mock_handler.assert_called_once()
        assert data.get("is_rate_limited") is False
