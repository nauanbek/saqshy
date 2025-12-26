"""
Tests for BehaviorAnalyzer

Tests behavior analysis including TTFM, message history, channel subscription,
and interaction signals.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from saqshy.analyzers.behavior import (
    WINDOW_24H,
    WINDOW_HOUR,
    BehaviorAnalyzer,
    ChannelSubscriptionChecker,
    FloodDetector,
    MessageHistoryProvider,
)
from saqshy.core.types import BehaviorSignals, MessageContext

# =============================================================================
# Mock Implementations
# =============================================================================


class MockMessageHistoryProvider:
    """Mock implementation of MessageHistoryProvider for testing."""

    def __init__(
        self,
        message_count_1h: int = 0,
        message_count_24h: int = 0,
        total_messages: int = 0,
        approved: int = 0,
        flagged: int = 0,
        blocked: int = 0,
        join_time: datetime | None = None,
        first_message_time: datetime | None = None,
    ):
        self.message_count_1h = message_count_1h
        self.message_count_24h = message_count_24h
        self.total_messages = total_messages
        self.approved = approved
        self.flagged = flagged
        self.blocked = blocked
        self.join_time = join_time
        self.first_message_time = first_message_time

    async def get_user_message_count(self, user_id: int, chat_id: int, window_seconds: int) -> int:
        if window_seconds == WINDOW_HOUR:
            return self.message_count_1h
        elif window_seconds == WINDOW_24H:
            return self.message_count_24h
        return 0

    async def get_user_stats(self, user_id: int, chat_id: int) -> dict[str, int]:
        return {
            "total_messages": self.total_messages,
            "approved": self.approved,
            "flagged": self.flagged,
            "blocked": self.blocked,
        }

    async def get_join_time(self, user_id: int, chat_id: int) -> datetime | None:
        return self.join_time

    async def get_first_message_time(self, user_id: int, chat_id: int) -> datetime | None:
        return self.first_message_time


class MockChannelSubscriptionChecker:
    """Mock implementation of ChannelSubscriptionChecker for testing."""

    def __init__(
        self,
        is_subscribed: bool = False,
        duration_days: int = 0,
    ):
        self._is_subscribed = is_subscribed
        self._duration_days = duration_days

    async def is_subscribed(self, user_id: int, channel_id: int) -> bool:
        return self._is_subscribed

    async def get_subscription_duration_days(self, user_id: int, channel_id: int) -> int:
        return self._duration_days


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def base_context() -> MessageContext:
    """Create base message context for tests."""
    return MessageContext(
        message_id=1,
        chat_id=-100123456,
        user_id=123,
        text="Hello, world!",
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
def analyzer_no_providers() -> BehaviorAnalyzer:
    """Create analyzer without providers (graceful degradation test)."""
    return BehaviorAnalyzer()


@pytest.fixture
def analyzer_with_history() -> BehaviorAnalyzer:
    """Create analyzer with history provider only."""
    return BehaviorAnalyzer(
        history_provider=MockMessageHistoryProvider(
            message_count_1h=5,
            message_count_24h=20,
            total_messages=100,
            approved=95,
            flagged=3,
            blocked=2,
            join_time=datetime.now(UTC) - timedelta(days=30),
            first_message_time=datetime.now(UTC) - timedelta(days=29),
        )
    )


@pytest.fixture
def analyzer_with_subscription() -> BehaviorAnalyzer:
    """Create analyzer with subscription checker only."""
    return BehaviorAnalyzer(
        subscription_checker=MockChannelSubscriptionChecker(
            is_subscribed=True,
            duration_days=60,
        )
    )


@pytest.fixture
def analyzer_full() -> BehaviorAnalyzer:
    """Create analyzer with all providers."""
    return BehaviorAnalyzer(
        history_provider=MockMessageHistoryProvider(
            message_count_1h=5,
            message_count_24h=20,
            total_messages=100,
            approved=95,
            flagged=3,
            blocked=2,
            join_time=datetime.now(UTC) - timedelta(days=30),
            first_message_time=datetime.now(UTC) - timedelta(days=29),
        ),
        subscription_checker=MockChannelSubscriptionChecker(
            is_subscribed=True,
            duration_days=60,
        ),
    )


# =============================================================================
# Test BehaviorAnalyzer - Basic Operations
# =============================================================================


class TestBehaviorAnalyzerBasic:
    """Test basic BehaviorAnalyzer operations."""

    @pytest.mark.asyncio
    async def test_analyze_without_providers(
        self,
        analyzer_no_providers: BehaviorAnalyzer,
        base_context: MessageContext,
    ):
        """Analyzer should return defaults when providers are not configured."""
        signals = await analyzer_no_providers.analyze(base_context)

        assert isinstance(signals, BehaviorSignals)
        assert signals.is_first_message is True
        assert signals.messages_in_last_hour == 0
        assert signals.messages_in_last_24h == 0
        assert signals.previous_messages_approved == 0
        assert signals.is_channel_subscriber is False

    @pytest.mark.asyncio
    async def test_analyze_returns_behavior_signals(
        self,
        analyzer_full: BehaviorAnalyzer,
        base_context: MessageContext,
    ):
        """Analyzer should return BehaviorSignals dataclass."""
        signals = await analyzer_full.analyze(
            base_context,
            linked_channel_id=-100999999,
        )

        assert isinstance(signals, BehaviorSignals)


# =============================================================================
# Test History Signals
# =============================================================================


class TestHistorySignals:
    """Test message history signal extraction."""

    @pytest.mark.asyncio
    async def test_message_counts(
        self,
        analyzer_with_history: BehaviorAnalyzer,
        base_context: MessageContext,
    ):
        """Should extract message counts from history provider."""
        signals = await analyzer_with_history.analyze(base_context)

        assert signals.messages_in_last_hour == 5
        assert signals.messages_in_last_24h == 20

    @pytest.mark.asyncio
    async def test_approved_message_count(
        self,
        analyzer_with_history: BehaviorAnalyzer,
        base_context: MessageContext,
    ):
        """Should extract approved message count."""
        signals = await analyzer_with_history.analyze(base_context)

        assert signals.previous_messages_approved == 95
        assert signals.previous_messages_flagged == 3
        assert signals.previous_messages_blocked == 2

    @pytest.mark.asyncio
    async def test_is_first_message_false(
        self,
        analyzer_with_history: BehaviorAnalyzer,
        base_context: MessageContext,
    ):
        """User with prior messages should not be marked as first message."""
        signals = await analyzer_with_history.analyze(base_context)

        assert signals.is_first_message is False

    @pytest.mark.asyncio
    async def test_is_first_message_true(
        self,
        base_context: MessageContext,
    ):
        """New user should be marked as first message."""
        analyzer = BehaviorAnalyzer(
            history_provider=MockMessageHistoryProvider(
                total_messages=0,
                join_time=datetime.now(UTC) - timedelta(seconds=30),
            )
        )

        signals = await analyzer.analyze(base_context)

        assert signals.is_first_message is True


# =============================================================================
# Test TTFM (Time To First Message)
# =============================================================================


class TestTTFMSignals:
    """Test Time To First Message signal extraction."""

    @pytest.mark.asyncio
    async def test_ttfm_for_first_message(
        self,
        base_context: MessageContext,
    ):
        """TTFM should equal join_to_message for first message."""
        join_time = base_context.timestamp - timedelta(seconds=45)

        analyzer = BehaviorAnalyzer(
            history_provider=MockMessageHistoryProvider(
                total_messages=0,
                join_time=join_time,
            )
        )

        signals = await analyzer.analyze(base_context)

        assert signals.is_first_message is True
        assert signals.time_to_first_message_seconds is not None
        assert 40 <= signals.time_to_first_message_seconds <= 50  # Allow for test timing

    @pytest.mark.asyncio
    async def test_ttfm_under_60_seconds(
        self,
        base_context: MessageContext,
    ):
        """Detect suspicious fast TTFM (under 60 seconds)."""
        join_time = base_context.timestamp - timedelta(seconds=30)

        analyzer = BehaviorAnalyzer(
            history_provider=MockMessageHistoryProvider(
                total_messages=0,
                join_time=join_time,
            )
        )

        signals = await analyzer.analyze(base_context)

        assert signals.time_to_first_message_seconds is not None
        assert signals.time_to_first_message_seconds < 60

    @pytest.mark.asyncio
    async def test_join_to_message_seconds(
        self,
        base_context: MessageContext,
    ):
        """Should calculate join-to-message seconds correctly."""
        join_time = base_context.timestamp - timedelta(hours=2)

        analyzer = BehaviorAnalyzer(
            history_provider=MockMessageHistoryProvider(
                total_messages=10,
                join_time=join_time,
            )
        )

        signals = await analyzer.analyze(base_context)

        # 2 hours = 7200 seconds
        assert signals.join_to_message_seconds is not None
        assert 7195 <= signals.join_to_message_seconds <= 7205


# =============================================================================
# Test Channel Subscription Signals
# =============================================================================


class TestChannelSubscriptionSignals:
    """Test channel subscription signal extraction."""

    @pytest.mark.asyncio
    async def test_is_channel_subscriber_true(
        self,
        analyzer_with_subscription: BehaviorAnalyzer,
        base_context: MessageContext,
    ):
        """Should detect channel subscription."""
        signals = await analyzer_with_subscription.analyze(
            base_context,
            linked_channel_id=-100999999,
        )

        assert signals.is_channel_subscriber is True
        assert signals.channel_subscription_duration_days == 60

    @pytest.mark.asyncio
    async def test_is_channel_subscriber_false(
        self,
        base_context: MessageContext,
    ):
        """Should return False when not subscribed."""
        analyzer = BehaviorAnalyzer(
            subscription_checker=MockChannelSubscriptionChecker(
                is_subscribed=False,
            )
        )

        signals = await analyzer.analyze(
            base_context,
            linked_channel_id=-100999999,
        )

        assert signals.is_channel_subscriber is False
        assert signals.channel_subscription_duration_days == 0

    @pytest.mark.asyncio
    async def test_no_linked_channel(
        self,
        analyzer_with_subscription: BehaviorAnalyzer,
        base_context: MessageContext,
    ):
        """Should skip subscription check when no channel is linked."""
        signals = await analyzer_with_subscription.analyze(
            base_context,
            linked_channel_id=None,
        )

        assert signals.is_channel_subscriber is False


# =============================================================================
# Test Interaction Signals
# =============================================================================


class TestInteractionSignals:
    """Test interaction signal extraction."""

    @pytest.mark.asyncio
    async def test_is_reply(
        self,
        analyzer_no_providers: BehaviorAnalyzer,
    ):
        """Should detect reply messages."""
        context = MessageContext(
            message_id=2,
            chat_id=-100123456,
            user_id=123,
            text="Thanks for the info!",
            reply_to_message_id=1,
        )

        signals = await analyzer_no_providers.analyze(context)

        assert signals.is_reply is True

    @pytest.mark.asyncio
    async def test_is_not_reply(
        self,
        analyzer_no_providers: BehaviorAnalyzer,
        base_context: MessageContext,
    ):
        """Should detect non-reply messages."""
        signals = await analyzer_no_providers.analyze(base_context)

        assert signals.is_reply is False

    @pytest.mark.asyncio
    async def test_is_reply_to_admin(
        self,
        analyzer_no_providers: BehaviorAnalyzer,
    ):
        """Should detect replies to admin messages."""
        context = MessageContext(
            message_id=2,
            chat_id=-100123456,
            user_id=123,
            text="Thanks admin!",
            reply_to_message_id=1,
            raw_message={
                "reply_to_message": {
                    "from": {"id": 999},
                }
            },
        )

        admin_ids = {999, 888}
        signals = await analyzer_no_providers.analyze(
            context,
            admin_ids=admin_ids,
        )

        assert signals.is_reply is True
        assert signals.is_reply_to_admin is True

    @pytest.mark.asyncio
    async def test_mentioned_users_count(
        self,
        analyzer_no_providers: BehaviorAnalyzer,
    ):
        """Should count @mentions in message."""
        context = MessageContext(
            message_id=1,
            chat_id=-100123456,
            user_id=123,
            text="Hey @alice and @bob_smith, check this out!",
        )

        signals = await analyzer_no_providers.analyze(context)

        assert signals.mentioned_users_count == 2


# =============================================================================
# Test Error Handling / Graceful Degradation
# =============================================================================


class TestErrorHandling:
    """Test graceful degradation when providers fail."""

    @pytest.mark.asyncio
    async def test_history_provider_exception(
        self,
        base_context: MessageContext,
    ):
        """Should handle history provider exceptions gracefully."""
        mock_provider = AsyncMock()
        mock_provider.get_user_stats.side_effect = Exception("Redis connection failed")
        mock_provider.get_user_message_count.side_effect = Exception("Redis timeout")
        mock_provider.get_join_time.side_effect = Exception("Redis error")
        mock_provider.get_first_message_time.side_effect = Exception("Redis error")

        analyzer = BehaviorAnalyzer(history_provider=mock_provider)
        signals = await analyzer.analyze(base_context)

        # Should return defaults without crashing
        assert isinstance(signals, BehaviorSignals)
        assert signals.messages_in_last_hour == 0

    @pytest.mark.asyncio
    async def test_subscription_checker_exception(
        self,
        base_context: MessageContext,
    ):
        """Should handle subscription checker exceptions gracefully."""
        mock_checker = AsyncMock()
        mock_checker.is_subscribed.side_effect = Exception("Telegram API error")

        analyzer = BehaviorAnalyzer(subscription_checker=mock_checker)
        signals = await analyzer.analyze(
            base_context,
            linked_channel_id=-100999999,
        )

        # Should return defaults without crashing
        assert signals.is_channel_subscriber is False


# =============================================================================
# Test FloodDetector
# =============================================================================


class TestFloodDetector:
    """Test FloodDetector functionality."""

    @pytest.mark.asyncio
    async def test_check_flood_under_limit(self):
        """Should return False when under message limit."""
        history_provider = MockMessageHistoryProvider(message_count_1h=5)
        detector = FloodDetector(
            window_seconds=60,
            max_messages=10,
            history_provider=history_provider,
        )

        is_flooding = await detector.check_flood(user_id=123, chat_id=-100)

        assert is_flooding is False

    @pytest.mark.asyncio
    async def test_check_flood_at_limit(self):
        """Should return True when at or above message limit."""
        history_provider = MockMessageHistoryProvider(message_count_1h=10)
        detector = FloodDetector(
            window_seconds=WINDOW_HOUR,
            max_messages=10,
            history_provider=history_provider,
        )

        is_flooding = await detector.check_flood(user_id=123, chat_id=-100)

        assert is_flooding is True

    @pytest.mark.asyncio
    async def test_check_flood_no_provider(self):
        """Should return False when no history provider is configured."""
        detector = FloodDetector(
            window_seconds=60,
            max_messages=10,
            history_provider=None,
        )

        is_flooding = await detector.check_flood(user_id=123, chat_id=-100)

        assert is_flooding is False

    @pytest.mark.asyncio
    async def test_check_flood_provider_error(self):
        """Should return False on provider error."""
        mock_provider = AsyncMock()
        mock_provider.get_user_message_count.side_effect = Exception("Error")

        detector = FloodDetector(
            window_seconds=60,
            max_messages=10,
            history_provider=mock_provider,
        )

        is_flooding = await detector.check_flood(user_id=123, chat_id=-100)

        assert is_flooding is False


# =============================================================================
# Test Protocol Compliance
# =============================================================================


class TestProtocolCompliance:
    """Test that mock implementations satisfy Protocol requirements."""

    def test_history_provider_is_protocol_compliant(self):
        """MockMessageHistoryProvider should satisfy MessageHistoryProvider."""
        provider = MockMessageHistoryProvider()

        # Check using isinstance with runtime_checkable Protocol
        assert isinstance(provider, MessageHistoryProvider)

    def test_subscription_checker_is_protocol_compliant(self):
        """MockChannelSubscriptionChecker should satisfy ChannelSubscriptionChecker."""
        checker = MockChannelSubscriptionChecker()

        assert isinstance(checker, ChannelSubscriptionChecker)
