"""
SAQSHY Load Test Configuration

Pytest fixtures specifically for load testing.

Key differences from regular test fixtures:
- Module-scoped event loop for efficiency
- Bulk message generation utilities
- Metrics collection for performance analysis
- Mock services configured for load scenarios
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from saqshy.analyzers.behavior import BehaviorAnalyzer
from saqshy.analyzers.content import ContentAnalyzer
from saqshy.analyzers.profile import ProfileAnalyzer
from saqshy.bot.action_engine import ActionConfig, ActionEngine
from saqshy.bot.pipeline import MessagePipeline, PipelineCircuitBreaker
from saqshy.core.risk_calculator import RiskCalculator
from saqshy.core.types import (
    BehaviorSignals,
    ContentSignals,
    GroupType,
    MessageContext,
    NetworkSignals,
    ProfileSignals,
    RiskResult,
    Signals,
    ThreatType,
    Verdict,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from aiogram import Bot
    from aiogram.types import Chat, Message, User


# =============================================================================
# Load Test Metrics
# =============================================================================


@dataclass
class LoadTestMetrics:
    """
    Collect and analyze metrics during load tests.

    Provides insights into:
    - Throughput (messages per second)
    - Latency distribution (p50, p95, p99)
    - Error rates
    - Circuit breaker activations
    """

    start_time: float = 0.0
    end_time: float = 0.0
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    latencies: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    circuit_breaker_opens: int = 0

    def record_request(self, latency_ms: float, success: bool, error: str | None = None) -> None:
        """Record a single request's outcome."""
        self.total_requests += 1
        self.latencies.append(latency_ms)
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
            if error:
                self.errors.append(error)

    @property
    def throughput(self) -> float:
        """Requests per second."""
        duration = self.end_time - self.start_time
        if duration <= 0:
            return 0.0
        return self.total_requests / duration

    @property
    def success_rate(self) -> float:
        """Percentage of successful requests."""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100

    @property
    def p50_latency(self) -> float:
        """50th percentile latency in ms."""
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.5)
        return sorted_latencies[idx]

    @property
    def p95_latency(self) -> float:
        """95th percentile latency in ms."""
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]

    @property
    def p99_latency(self) -> float:
        """99th percentile latency in ms."""
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.99)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]

    def summary(self) -> dict:
        """Get summary statistics."""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": round(self.success_rate, 2),
            "throughput_rps": round(self.throughput, 2),
            "p50_latency_ms": round(self.p50_latency, 2),
            "p95_latency_ms": round(self.p95_latency, 2),
            "p99_latency_ms": round(self.p99_latency, 2),
            "circuit_breaker_opens": self.circuit_breaker_opens,
            "unique_errors": len(set(self.errors)),
        }


@pytest.fixture
def load_metrics() -> LoadTestMetrics:
    """Create fresh metrics collector for each test."""
    return LoadTestMetrics()


# =============================================================================
# Message Generation
# =============================================================================


def generate_spam_messages(
    count: int,
    base_chat_id: int = -1001234567890,
    users_count: int = 100,
    group_type: GroupType = GroupType.GENERAL,
) -> list[MessageContext]:
    """
    Generate a batch of spam-like messages for load testing.

    Creates realistic spam patterns with:
    - Rotating user IDs to simulate multiple attackers
    - Varied spam content patterns
    - Realistic timestamps

    Args:
        count: Number of messages to generate
        base_chat_id: Base chat ID for messages
        users_count: Number of unique users to simulate
        group_type: Type of group for context

    Returns:
        List of MessageContext objects
    """
    spam_templates = [
        "URGENT! Double your Bitcoin NOW! DM me for guaranteed profits!",
        "FREE crypto airdrop! Click here: t.me/scam_link",
        "Join our exclusive investment group! Limited spots!",
        "Make $10000/day working from home! Contact @scammer",
        "Claim your FREE tokens before they're gone!",
        "Hey! I found this amazing trading bot, guaranteed 500% returns!",
        "LIMITED TIME OFFER! Invest now and double your money!",
        "Join t.me/crypto_scam for free signals! Don't miss out!",
    ]

    messages = []
    for i in range(count):
        user_id = 1000 + (i % users_count)
        template_idx = i % len(spam_templates)

        messages.append(
            MessageContext(
                message_id=i + 1,
                chat_id=base_chat_id,
                user_id=user_id,
                text=f"{spam_templates[template_idx]} [MSG#{i}]",
                timestamp=datetime.now(UTC),
                username=f"user{user_id}",
                first_name="Spam",
                last_name=None,
                is_bot=False,
                is_premium=False,
                chat_type="supergroup",
                chat_title="Test Group",
                group_type=group_type,
                has_media=False,
                is_forward=i % 3 == 0,  # Every 3rd message is forwarded
            )
        )

    return messages


def generate_mixed_messages(
    count: int,
    spam_ratio: float = 0.3,
    base_chat_id: int = -1001234567890,
) -> list[MessageContext]:
    """
    Generate a mix of spam and legitimate messages.

    Args:
        count: Total number of messages
        spam_ratio: Fraction of messages that are spam (0.0-1.0)
        base_chat_id: Base chat ID

    Returns:
        List of MessageContext objects with mixed content
    """
    legitimate_templates = [
        "Hi everyone, how's it going?",
        "Thanks for the help earlier!",
        "Has anyone seen the latest update?",
        "I have a question about the project...",
        "Great discussion today!",
        "Can someone help me with this?",
        "I agree with what was said above.",
        "Looking forward to the next meeting.",
    ]

    spam_count = int(count * spam_ratio)
    spam_messages = generate_spam_messages(spam_count, base_chat_id)

    legitimate_messages = []
    for i in range(count - spam_count):
        user_id = 5000 + (i % 50)
        template_idx = i % len(legitimate_templates)

        legitimate_messages.append(
            MessageContext(
                message_id=spam_count + i + 1,
                chat_id=base_chat_id,
                user_id=user_id,
                text=legitimate_templates[template_idx],
                timestamp=datetime.now(UTC),
                username=f"realuser{user_id}",
                first_name="Legitimate",
                last_name="User",
                is_bot=False,
                is_premium=False,
                chat_type="supergroup",
                chat_title="Test Group",
                group_type=GroupType.GENERAL,
                has_media=False,
                is_forward=False,
            )
        )

    # Interleave spam and legitimate messages
    import random

    all_messages = spam_messages + legitimate_messages
    random.shuffle(all_messages)
    return all_messages


@pytest.fixture
def spam_messages_100() -> list[MessageContext]:
    """Generate 100 spam messages for load testing."""
    return generate_spam_messages(100)


@pytest.fixture
def spam_messages_1000() -> list[MessageContext]:
    """Generate 1000 spam messages for load testing."""
    return generate_spam_messages(1000)


@pytest.fixture
def mixed_messages_1000() -> list[MessageContext]:
    """Generate 1000 mixed messages (30% spam)."""
    return generate_mixed_messages(1000, spam_ratio=0.3)


# =============================================================================
# Mock Services for Load Testing
# =============================================================================


@pytest.fixture
def mock_fast_cache_service() -> AsyncMock:
    """
    Create a fast-responding mock cache service.

    Configured for minimal latency to test pure processing speed.
    Implements the MessageHistoryProvider interface expected by BehaviorAnalyzer.
    """
    cache = AsyncMock()

    # Basic cache operations
    cache.get.return_value = None
    cache.set.return_value = True
    cache.exists.return_value = False
    cache.get_cached_decision.return_value = None
    cache.cache_decision.return_value = None
    cache.ping.return_value = True
    cache.set_nx.return_value = True
    cache.set_json.return_value = True

    # MessageHistoryProvider interface for BehaviorAnalyzer
    cache.get_user_message_count.return_value = 0
    cache.get_user_stats.return_value = {
        "total_messages": 0,
        "approved": 0,
        "flagged": 0,
        "blocked": 0,
    }
    cache.get_first_message_time.return_value = None
    cache.get_join_time.return_value = None

    return cache


@pytest.fixture
def mock_slow_cache_service() -> AsyncMock:
    """
    Create a slow-responding mock cache service.

    Simulates network latency to test timeout handling.
    """

    async def slow_get(*args, **kwargs):
        await asyncio.sleep(0.05)  # 50ms latency
        return None

    async def slow_set(*args, **kwargs):
        await asyncio.sleep(0.05)
        return True

    cache = AsyncMock()
    cache.get.side_effect = slow_get
    cache.set.side_effect = slow_set
    cache.exists.return_value = False
    cache.get_cached_decision.side_effect = slow_get
    cache.cache_decision.side_effect = slow_set
    cache.ping.return_value = True
    cache.set_nx.return_value = True
    return cache


@pytest.fixture
def mock_failing_llm_service() -> AsyncMock:
    """
    Create an LLM service that fails intermittently.

    Used to test circuit breaker behavior under load.
    """
    call_count = 0

    async def intermittent_failure(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Fail every 3rd call
        if call_count % 3 == 0:
            raise asyncio.TimeoutError("LLM service timeout")
        return MagicMock(
            verdict=Verdict.WATCH,
            confidence=0.7,
            reason="Test response",
            error=None,
        )

    service = AsyncMock()
    service.analyze_message.side_effect = intermittent_failure
    service.health_check.return_value = True
    return service


@pytest.fixture
def mock_fast_spam_db() -> AsyncMock:
    """Create a fast-responding mock spam database."""
    service = AsyncMock()
    service.check_spam.return_value = (0.0, None)
    service.get_collection_stats.return_value = {"vectors_count": 1000}
    return service


@pytest.fixture
def mock_high_similarity_spam_db() -> AsyncMock:
    """Create a spam DB that returns high similarity for all messages."""
    service = AsyncMock()
    service.check_spam.return_value = (0.92, "Known spam pattern")
    service.get_collection_stats.return_value = {"vectors_count": 1000}
    return service


# =============================================================================
# Pipeline Fixtures for Load Testing
# =============================================================================


@pytest.fixture
def load_test_pipeline(
    mock_fast_cache_service: AsyncMock,
    mock_fast_spam_db: AsyncMock,
) -> MessagePipeline:
    """
    Create a pipeline configured for load testing.

    Uses fast mocks to measure pure processing throughput.
    Creates a fresh pipeline with reset circuit breakers for each test.
    """
    risk_calculator = RiskCalculator(group_type=GroupType.GENERAL)
    content_analyzer = ContentAnalyzer()
    profile_analyzer = ProfileAnalyzer()
    behavior_analyzer = BehaviorAnalyzer(
        history_provider=mock_fast_cache_service,
        subscription_checker=None,
    )

    pipeline = MessagePipeline(
        risk_calculator=risk_calculator,
        content_analyzer=content_analyzer,
        profile_analyzer=profile_analyzer,
        behavior_analyzer=behavior_analyzer,
        spam_db=mock_fast_spam_db,
        llm_service=None,
        cache_service=mock_fast_cache_service,
        channel_subscription=None,
        max_concurrent_requests=200,
    )

    # Reset all circuit breakers to ensure clean state
    pipeline.circuit_breaker.reset()
    for cb in pipeline._circuit_breakers.values():
        cb.failure_count = 0
        cb.state = "closed"
        cb.last_failure_time = 0.0

    # Also reset internal counters
    pipeline._active_requests = 0
    pipeline._requests_rejected_by_backpressure = 0

    return pipeline


@pytest.fixture
def load_test_pipeline_with_llm(
    mock_fast_cache_service: AsyncMock,
    mock_fast_spam_db: AsyncMock,
    mock_failing_llm_service: AsyncMock,
) -> MessagePipeline:
    """
    Create a pipeline with intermittently failing LLM.

    Used to test circuit breaker activation under load.
    Creates a fresh pipeline with reset circuit breakers for each test.
    """
    risk_calculator = RiskCalculator(group_type=GroupType.GENERAL)
    content_analyzer = ContentAnalyzer()
    profile_analyzer = ProfileAnalyzer()
    behavior_analyzer = BehaviorAnalyzer(
        history_provider=mock_fast_cache_service,
        subscription_checker=None,
    )

    pipeline = MessagePipeline(
        risk_calculator=risk_calculator,
        content_analyzer=content_analyzer,
        profile_analyzer=profile_analyzer,
        behavior_analyzer=behavior_analyzer,
        spam_db=mock_fast_spam_db,
        llm_service=mock_failing_llm_service,
        cache_service=mock_fast_cache_service,
        channel_subscription=None,
        max_concurrent_requests=200,
    )

    # Reset all circuit breakers to ensure clean state
    pipeline.circuit_breaker.reset()
    for cb in pipeline._circuit_breakers.values():
        cb.failure_count = 0
        cb.state = "closed"
        cb.last_failure_time = 0.0

    # Also reset internal counters
    pipeline._active_requests = 0
    pipeline._requests_rejected_by_backpressure = 0

    return pipeline


# =============================================================================
# Action Engine Fixtures for Load Testing
# =============================================================================


def create_mock_message_for_load(
    message_id: int,
    user_id: int,
    chat_id: int = -1001234567890,
    text: str = "Test message",
) -> MagicMock:
    """Create a mock Telegram message for load testing."""
    from aiogram.types import Chat, Message, User

    user = MagicMock(spec=User)
    user.id = user_id
    user.username = f"user{user_id}"
    user.first_name = "Test"
    user.is_bot = False

    chat = MagicMock(spec=Chat)
    chat.id = chat_id
    chat.type = "supergroup"
    chat.title = "Test Group"

    message = MagicMock(spec=Message)
    message.message_id = message_id
    message.from_user = user
    message.chat = chat
    message.text = text
    message.caption = None
    message.date = datetime.now(UTC)

    return message


@pytest.fixture
def mock_bot_for_load() -> AsyncMock:
    """Create a mock bot optimized for load testing."""
    bot = AsyncMock()
    bot.delete_message.return_value = True
    bot.restrict_chat_member.return_value = True
    bot.ban_chat_member.return_value = True
    bot.send_message.return_value = MagicMock(message_id=1)
    bot.get_chat_administrators.return_value = []
    return bot


@pytest.fixture
def load_test_action_engine(
    mock_bot_for_load: AsyncMock,
    mock_fast_cache_service: AsyncMock,
) -> ActionEngine:
    """Create an ActionEngine for load testing."""
    return ActionEngine(
        bot=mock_bot_for_load,
        cache_service=mock_fast_cache_service,
        db_session=None,
        group_type=GroupType.GENERAL,
        config=ActionConfig(
            admin_notify_rate_limit=1,  # Fast rate limit for testing
        ),
    )


# =============================================================================
# Utility Functions
# =============================================================================


async def run_concurrent_pipeline(
    pipeline: MessagePipeline,
    messages: list[MessageContext],
    concurrency: int = 100,
) -> tuple[list[RiskResult], LoadTestMetrics]:
    """
    Run messages through pipeline with controlled concurrency.

    Args:
        pipeline: The MessagePipeline to test
        messages: List of messages to process
        concurrency: Maximum concurrent requests

    Returns:
        Tuple of (results, metrics)
    """
    metrics = LoadTestMetrics()
    metrics.start_time = time.monotonic()

    semaphore = asyncio.Semaphore(concurrency)
    results: list[RiskResult | BaseException] = []

    async def process_with_semaphore(msg: MessageContext) -> RiskResult | BaseException:
        async with semaphore:
            start = time.monotonic()
            try:
                result = await pipeline.process(msg)
                latency_ms = (time.monotonic() - start) * 1000
                metrics.record_request(latency_ms, success=True)
                return result
            except Exception as e:
                latency_ms = (time.monotonic() - start) * 1000
                metrics.record_request(latency_ms, success=False, error=str(e))
                return e

    tasks = [process_with_semaphore(msg) for msg in messages]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_time = time.monotonic()

    # Filter out exceptions for return
    valid_results = [r for r in results if isinstance(r, RiskResult)]
    return valid_results, metrics


async def run_concurrent_actions(
    engine: ActionEngine,
    risk_results: list[RiskResult],
    messages: list[MagicMock],
    concurrency: int = 50,
) -> LoadTestMetrics:
    """
    Run action execution with controlled concurrency.

    Args:
        engine: The ActionEngine to test
        risk_results: Risk results for each message
        messages: Mock messages corresponding to risk results
        concurrency: Maximum concurrent requests

    Returns:
        LoadTestMetrics with execution statistics
    """
    metrics = LoadTestMetrics()
    metrics.start_time = time.monotonic()

    semaphore = asyncio.Semaphore(concurrency)

    async def execute_with_semaphore(
        risk_result: RiskResult, message: MagicMock
    ) -> None:
        async with semaphore:
            start = time.monotonic()
            try:
                await engine.execute(risk_result, message)
                latency_ms = (time.monotonic() - start) * 1000
                metrics.record_request(latency_ms, success=True)
            except Exception as e:
                latency_ms = (time.monotonic() - start) * 1000
                metrics.record_request(latency_ms, success=False, error=str(e))

    tasks = [
        execute_with_semaphore(result, msg) for result, msg in zip(risk_results, messages)
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    metrics.end_time = time.monotonic()
    return metrics
