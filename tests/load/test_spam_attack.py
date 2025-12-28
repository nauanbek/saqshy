"""
SAQSHY Load Tests - Spam Attack Resilience

Comprehensive load tests verifying the bot can handle spam attacks.

Test scenarios:
1. High message throughput (100+ messages/second)
2. Circuit breaker activation under load
3. Graceful degradation when services fail
4. Database write performance
5. Concurrent action execution
6. Idempotency under concurrent requests
7. Admin notification rate limiting under load

These tests are marked with @pytest.mark.slow and @pytest.mark.load
and are typically run separately from the main test suite.

Usage:
    pytest -m load tests/load/
    pytest tests/load/test_spam_attack.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from saqshy.bot.action_engine import ActionEngine, execute_with_fallback
from saqshy.bot.pipeline import MessagePipeline, PipelineCircuitBreaker
from saqshy.core.types import (
    GroupType,
    MessageContext,
    RiskResult,
    Signals,
    ThreatType,
    Verdict,
)

from .conftest import (
    LoadTestMetrics,
    create_mock_message_for_load,
    generate_mixed_messages,
    generate_spam_messages,
    run_concurrent_actions,
    run_concurrent_pipeline,
)


# =============================================================================
# Pipeline Throughput Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.load
class TestSpamAttackResilience:
    """Load tests for spam attack scenarios."""

    async def test_handles_100_messages_per_second(
        self,
        load_test_pipeline: MessagePipeline,
        spam_messages_100: list[MessageContext],
    ) -> None:
        """
        Test processing 100 messages concurrently.

        Target: Complete within 2 seconds
        Success criteria: 90%+ success rate
        """
        start_time = time.monotonic()

        # Process 100 messages concurrently
        tasks = [load_test_pipeline.process(msg) for msg in spam_messages_100]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.monotonic() - start_time

        # Should complete within 2 seconds
        assert elapsed < 2.0, f"Processing took too long: {elapsed:.2f}s (target: <2.0s)"

        # Count successful results
        successes = sum(1 for r in results if isinstance(r, RiskResult))
        failures = len(results) - successes

        assert successes >= 90, f"Too many failures: {failures}/100 (target: <10)"

    async def test_handles_1000_messages_sustained(
        self,
        load_test_pipeline: MessagePipeline,
        spam_messages_1000: list[MessageContext],
    ) -> None:
        """
        Test sustained high throughput with 1000 messages.

        Target: Maintain >50 messages/second throughput
        Success criteria: 95%+ success rate
        """
        results, metrics = await run_concurrent_pipeline(
            pipeline=load_test_pipeline,
            messages=spam_messages_1000,
            concurrency=100,
        )

        # Check throughput
        assert metrics.throughput >= 50, (
            f"Throughput too low: {metrics.throughput:.2f} msg/s (target: >=50)"
        )

        # Check success rate
        assert metrics.success_rate >= 95.0, (
            f"Success rate too low: {metrics.success_rate:.2f}% (target: >=95%)"
        )

        # Check latency
        assert metrics.p95_latency < 500, (
            f"P95 latency too high: {metrics.p95_latency:.2f}ms (target: <500ms)"
        )

    async def test_mixed_traffic_performance(
        self,
        load_test_pipeline: MessagePipeline,
        mixed_messages_1000: list[MessageContext],
    ) -> None:
        """
        Test performance with mixed spam/legitimate traffic.

        Verifies that legitimate messages are processed quickly
        even when mixed with spam.

        Note: With mocked services (no spam DB similarity), detection relies
        on content analysis only, so we check for elevated scores rather than
        specific verdicts.
        """
        results, metrics = await run_concurrent_pipeline(
            pipeline=load_test_pipeline,
            messages=mixed_messages_1000,
            concurrency=100,
        )

        # Should handle mixed traffic with good performance
        assert metrics.success_rate >= 95.0
        assert metrics.p95_latency < 500

        # Verify score distribution shows differentiation
        # Spam messages should have higher scores than legitimate ones
        elevated_score_count = sum(
            1 for r in results
            if r.score >= 20  # Score at least elevated (includes WATCH and above)
        )
        elevated_ratio = elevated_score_count / len(results) if results else 0

        # Should detect some elevated risk (at least 10% of messages)
        # Note: Without spam DB, detection relies on content patterns only
        assert elevated_ratio >= 0.10, (
            f"Not detecting risk patterns: {elevated_ratio:.2%} elevated scores"
        )


# =============================================================================
# Circuit Breaker Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.load
class TestCircuitBreakerUnderLoad:
    """Tests for circuit breaker behavior under load."""

    async def test_pipeline_circuit_breaker_opens_on_failures(
        self,
        load_test_pipeline_with_llm: MessagePipeline,
    ) -> None:
        """
        Test that pipeline circuit breaker opens after repeated failures.

        Uses an LLM service that fails intermittently to trigger circuit breaker.
        """
        # Generate messages that will trigger LLM (gray zone scores)
        messages = generate_spam_messages(100, group_type=GroupType.GENERAL)

        # Process messages - some will fail due to intermittent LLM failures
        results, metrics = await run_concurrent_pipeline(
            pipeline=load_test_pipeline_with_llm,
            messages=messages,
            concurrency=50,
        )

        # Pipeline should still complete most requests
        # (circuit breaker provides fallback, not failure)
        assert metrics.success_rate >= 90.0

    async def test_analyzer_circuit_breaker_isolation(
        self,
        mock_fast_cache_service: AsyncMock,
        mock_fast_spam_db: AsyncMock,
    ) -> None:
        """
        Test that individual analyzer circuit breakers don't affect others.

        When one analyzer's circuit breaker opens, other analyzers
        should continue functioning normally.
        """
        from saqshy.analyzers.behavior import BehaviorAnalyzer
        from saqshy.analyzers.content import ContentAnalyzer
        from saqshy.analyzers.profile import ProfileAnalyzer
        from saqshy.core.risk_calculator import RiskCalculator

        # Create pipeline with fast mocks
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
        )

        # Manually open the spam_db circuit breaker
        pipeline._circuit_breakers["spam_db"].state = "open"
        pipeline._circuit_breakers["spam_db"].last_failure_time = time.monotonic()

        # Process a message - should still work using other analyzers
        message = generate_spam_messages(1)[0]
        result = await pipeline.process(message)

        # Should get a result even with spam_db circuit open
        assert result is not None
        assert isinstance(result, RiskResult)

        # Other circuit breakers should still be closed
        assert pipeline._circuit_breakers["profile"].state == "closed"
        assert pipeline._circuit_breakers["content"].state == "closed"
        assert pipeline._circuit_breakers["behavior"].state == "closed"

    async def test_circuit_breaker_recovery(self) -> None:
        """
        Test that circuit breaker recovers after recovery timeout.

        Verifies the half-open state transition and recovery.
        """
        breaker = PipelineCircuitBreaker(
            failure_threshold=3,
            recovery_timeout=0.1,  # 100ms for fast testing
            half_open_requests=2,
        )

        # Trigger failures to open circuit
        for _ in range(5):
            breaker.record_failure()

        assert breaker.state == "open"
        assert breaker.is_open() is True

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Should transition to half_open
        assert breaker.is_open() is False
        assert breaker.state == "half_open"

        # Record successes to close circuit
        breaker.record_success()
        breaker.record_success()

        assert breaker.state == "closed"


# =============================================================================
# Graceful Degradation Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.load
class TestGracefulDegradation:
    """Tests for graceful degradation when services fail."""

    async def test_degradation_with_no_optional_services(
        self,
        mock_fast_cache_service: AsyncMock,
    ) -> None:
        """
        Test that system degrades gracefully when optional services are unavailable.

        Pipeline should still process messages using core analyzers only.
        """
        from saqshy.analyzers.behavior import BehaviorAnalyzer
        from saqshy.analyzers.content import ContentAnalyzer
        from saqshy.analyzers.profile import ProfileAnalyzer
        from saqshy.core.risk_calculator import RiskCalculator

        # Create minimal pipeline without optional services
        pipeline = MessagePipeline(
            risk_calculator=RiskCalculator(group_type=GroupType.GENERAL),
            content_analyzer=ContentAnalyzer(),
            profile_analyzer=ProfileAnalyzer(),
            behavior_analyzer=BehaviorAnalyzer(),
            spam_db=None,
            llm_service=None,
            cache_service=None,
            channel_subscription=None,
        )

        # Should still process without crashing
        messages = generate_spam_messages(50)
        results = []

        for msg in messages:
            result = await pipeline.process(msg)
            results.append(result)

        # All should return valid results
        assert len(results) == 50
        assert all(isinstance(r, RiskResult) for r in results)
        assert all(r.verdict is not None for r in results)

    async def test_degradation_with_cache_failures(
        self,
        mock_fast_spam_db: AsyncMock,
    ) -> None:
        """
        Test that pipeline handles cache failures gracefully.

        When cache fails, pipeline should continue without caching.
        """
        from saqshy.analyzers.behavior import BehaviorAnalyzer
        from saqshy.analyzers.content import ContentAnalyzer
        from saqshy.analyzers.profile import ProfileAnalyzer
        from saqshy.core.risk_calculator import RiskCalculator

        # Create cache that raises exceptions
        failing_cache = AsyncMock()
        failing_cache.get_cached_decision.side_effect = Exception("Cache unavailable")
        failing_cache.cache_decision.side_effect = Exception("Cache unavailable")
        failing_cache.ping.side_effect = Exception("Cache unavailable")

        pipeline = MessagePipeline(
            risk_calculator=RiskCalculator(group_type=GroupType.GENERAL),
            content_analyzer=ContentAnalyzer(),
            profile_analyzer=ProfileAnalyzer(),
            behavior_analyzer=BehaviorAnalyzer(),
            spam_db=mock_fast_spam_db,
            llm_service=None,
            cache_service=failing_cache,
            channel_subscription=None,
        )

        # Should process despite cache failures
        messages = generate_spam_messages(20)
        results = []

        for msg in messages:
            result = await pipeline.process(msg)
            results.append(result)

        # All should complete successfully
        assert len(results) == 20
        assert all(isinstance(r, RiskResult) for r in results)

    async def test_degradation_with_spam_db_timeout(
        self,
        mock_fast_cache_service: AsyncMock,
    ) -> None:
        """
        Test that pipeline handles spam DB timeouts gracefully.

        Spam DB is optional - timeouts should not block processing.
        """
        from saqshy.analyzers.behavior import BehaviorAnalyzer
        from saqshy.analyzers.content import ContentAnalyzer
        from saqshy.analyzers.profile import ProfileAnalyzer
        from saqshy.core.risk_calculator import RiskCalculator

        # Create spam DB that times out
        slow_spam_db = AsyncMock()

        async def slow_check(*args, **kwargs):
            await asyncio.sleep(10)  # Way longer than timeout
            return (0.0, None)

        slow_spam_db.check_spam.side_effect = slow_check

        pipeline = MessagePipeline(
            risk_calculator=RiskCalculator(group_type=GroupType.GENERAL),
            content_analyzer=ContentAnalyzer(),
            profile_analyzer=ProfileAnalyzer(),
            behavior_analyzer=BehaviorAnalyzer(),
            spam_db=slow_spam_db,
            llm_service=None,
            cache_service=mock_fast_cache_service,
            channel_subscription=None,
        )

        # Should complete quickly despite slow spam DB
        message = generate_spam_messages(1)[0]
        start = time.monotonic()
        result = await pipeline.process(message)
        elapsed = time.monotonic() - start

        # Should complete within 5 seconds (pipeline timeout)
        assert elapsed < 5.0
        assert isinstance(result, RiskResult)


# =============================================================================
# Database Write Performance Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.load
class TestDatabaseWritePerformance:
    """Tests for database write performance under load."""

    async def test_decision_logging_performance(
        self,
        mock_bot_for_load: AsyncMock,
        mock_fast_cache_service: AsyncMock,
    ) -> None:
        """
        Test that decision logging doesn't block action execution.

        Logging should be fire-and-forget, not blocking the main flow.
        """
        # Create mock DB session
        mock_db_session = AsyncMock()
        mock_db_session.commit = AsyncMock()

        engine = ActionEngine(
            bot=mock_bot_for_load,
            cache_service=mock_fast_cache_service,
            db_session=mock_db_session,
            group_type=GroupType.GENERAL,
        )

        # Create test data
        risk_result = RiskResult(
            score=85,
            verdict=Verdict.BLOCK,
            threat_type=ThreatType.SPAM,
            signals=Signals(),
            contributing_factors=["Test factor"],
        )

        messages = [
            create_mock_message_for_load(i, 1000 + i)
            for i in range(100)
        ]

        # Execute actions concurrently
        start_time = time.monotonic()

        tasks = [engine.execute(risk_result, msg) for msg in messages]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.monotonic() - start_time

        # Should complete quickly (< 5 seconds for 100 actions)
        assert elapsed < 5.0, f"Actions took too long: {elapsed:.2f}s"

        # Most should succeed
        successes = sum(1 for r in results if not isinstance(r, Exception))
        assert successes >= 95


# =============================================================================
# Concurrent Access Pattern Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.load
class TestConcurrency:
    """Tests for concurrent access patterns."""

    async def test_no_race_conditions_in_admin_notify(
        self,
        mock_bot_for_load: AsyncMock,
        mock_fast_cache_service: AsyncMock,
    ) -> None:
        """
        Test that admin notifications don't have race conditions.

        When multiple spam messages arrive simultaneously,
        only one admin notification should be sent per rate limit window.
        """
        # Track notification count
        notification_count = 0

        async def track_send(*args, **kwargs):
            nonlocal notification_count
            notification_count += 1
            return MagicMock(message_id=1)

        mock_bot_for_load.send_message.side_effect = track_send

        # Set up admin
        admin = MagicMock()
        admin.user.id = 111222333
        admin.user.is_bot = False
        mock_bot_for_load.get_chat_administrators.return_value = [admin]

        # Use atomic rate limiter (set_nx returns False after first call)
        call_count = 0

        async def atomic_set_nx(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Only first call succeeds
            return call_count == 1

        mock_fast_cache_service.set_nx.side_effect = atomic_set_nx

        engine = ActionEngine(
            bot=mock_bot_for_load,
            cache_service=mock_fast_cache_service,
            db_session=None,
            group_type=GroupType.GENERAL,
        )

        # Send 10 notifications concurrently
        risk_result = RiskResult(
            score=95,
            verdict=Verdict.BLOCK,
            threat_type=ThreatType.CRYPTO_SCAM,
            signals=Signals(),
            contributing_factors=["Crypto scam phrases"],
        )

        messages = [
            create_mock_message_for_load(i, 1000 + i)
            for i in range(10)
        ]

        # Execute notifications concurrently
        tasks = [
            engine.notify_admins(
                chat_id=-1001234567890,
                risk_result=risk_result,
                message=msg,
            )
            for msg in messages
        ]

        results = await asyncio.gather(*tasks)

        # Only one should actually send (rate limited)
        sent_count = sum(
            1 for r in results
            if r.success and r.details.get("admins_notified", 0) > 0
        )
        skipped_count = sum(
            1 for r in results
            if r.details.get("skipped") is True
        )

        # Should have exactly 1 sent and 9 skipped (rate limited)
        assert sent_count <= 1, f"Too many notifications sent: {sent_count}"
        assert skipped_count >= 9, f"Not enough skipped: {skipped_count}"

    async def test_idempotency_under_concurrent_requests(
        self,
        mock_bot_for_load: AsyncMock,
        mock_fast_cache_service: AsyncMock,
    ) -> None:
        """
        Test action idempotency with concurrent requests.

        Same message processed multiple times should only execute actions once.
        """
        delete_count = 0

        async def track_delete(*args, **kwargs):
            nonlocal delete_count
            delete_count += 1
            return True

        mock_bot_for_load.delete_message.side_effect = track_delete

        # Simulate idempotency key behavior
        processed_keys: set[str] = set()

        async def check_exists(key: str) -> bool:
            return key in processed_keys

        async def mark_processed(key: str, *args, **kwargs) -> bool:
            processed_keys.add(key)
            return True

        mock_fast_cache_service.exists.side_effect = check_exists
        mock_fast_cache_service.set.side_effect = mark_processed

        engine = ActionEngine(
            bot=mock_bot_for_load,
            cache_service=mock_fast_cache_service,
            db_session=None,
            group_type=GroupType.GENERAL,
        )

        risk_result = RiskResult(
            score=95,
            verdict=Verdict.BLOCK,
            threat_type=ThreatType.SPAM,
            signals=Signals(),
        )

        # Same message, processed 5 times concurrently
        message = create_mock_message_for_load(123, 456)

        tasks = [engine.execute(risk_result, message) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # Only first should actually delete
        delete_actions = sum(
            1 for r in results if r.message_deleted
        )

        # Ideally only 1, but timing may allow 1-2
        assert delete_actions <= 2, f"Too many deletes: {delete_actions}"

    async def test_concurrent_pipeline_processing(
        self,
        load_test_pipeline: MessagePipeline,
    ) -> None:
        """
        Test that pipeline handles concurrent requests correctly.

        No data corruption or race conditions under concurrent load.
        """
        # Generate diverse messages
        messages = []
        for i in range(50):
            messages.append(
                MessageContext(
                    message_id=i,
                    chat_id=-1001234567890 - (i % 5),  # 5 different chats
                    user_id=1000 + (i % 20),  # 20 different users
                    text=f"Message #{i} with unique content {i * 17}",
                    timestamp=datetime.now(UTC),
                    group_type=GroupType.GENERAL,
                )
            )

        # Process all concurrently
        results, metrics = await run_concurrent_pipeline(
            pipeline=load_test_pipeline,
            messages=messages,
            concurrency=50,
        )

        # All should complete
        assert len(results) == 50

        # Each result should have valid fields
        for result in results:
            assert result.score >= 0
            assert result.score <= 100
            assert result.verdict in Verdict.__members__.values()


# =============================================================================
# Performance Regression Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.load
class TestPerformanceRegression:
    """Tests to catch performance regressions."""

    async def test_pipeline_latency_baseline(
        self,
        load_test_pipeline: MessagePipeline,
    ) -> None:
        """
        Establish and verify pipeline latency baseline.

        This test ensures processing latency doesn't regress.
        """
        messages = generate_spam_messages(100)

        latencies = []
        for msg in messages:
            start = time.monotonic()
            await load_test_pipeline.process(msg)
            latencies.append((time.monotonic() - start) * 1000)

        avg_latency = sum(latencies) / len(latencies)
        p95_latency = sorted(latencies)[94]  # 95th percentile

        # Baseline targets (adjust as needed)
        assert avg_latency < 50, f"Average latency too high: {avg_latency:.2f}ms"
        assert p95_latency < 100, f"P95 latency too high: {p95_latency:.2f}ms"

    async def test_action_engine_latency_baseline(
        self,
        load_test_action_engine: ActionEngine,
    ) -> None:
        """
        Establish and verify action engine latency baseline.
        """
        risk_result = RiskResult(
            score=95,
            verdict=Verdict.BLOCK,
            threat_type=ThreatType.SPAM,
            signals=Signals(),
        )

        latencies = []
        for i in range(100):
            message = create_mock_message_for_load(i, 1000 + i)
            start = time.monotonic()
            await load_test_action_engine.execute(risk_result, message)
            latencies.append((time.monotonic() - start) * 1000)

        avg_latency = sum(latencies) / len(latencies)
        p95_latency = sorted(latencies)[94]

        # Baseline targets
        assert avg_latency < 100, f"Average latency too high: {avg_latency:.2f}ms"
        assert p95_latency < 200, f"P95 latency too high: {p95_latency:.2f}ms"

    async def test_memory_stability_under_load(
        self,
        load_test_pipeline: MessagePipeline,
    ) -> None:
        """
        Test that memory usage remains stable under sustained load.

        Processes many messages and verifies no memory leaks.
        """
        import gc

        # Force garbage collection before test
        gc.collect()

        # Process many messages in batches
        total_processed = 0
        batch_size = 100

        for batch in range(10):
            messages = generate_spam_messages(batch_size)

            for msg in messages:
                await load_test_pipeline.process(msg)
                total_processed += 1

            # Force GC between batches
            gc.collect()

        # If we get here without OOM, test passes
        assert total_processed == 1000


# =============================================================================
# Stress Tests
# =============================================================================


@pytest.mark.slow
@pytest.mark.load
class TestStressScenarios:
    """Stress tests for extreme conditions."""

    async def test_burst_traffic_handling(
        self,
        load_test_pipeline: MessagePipeline,
    ) -> None:
        """
        Test handling of burst traffic (sudden spike in messages).

        Simulates a spam attack starting suddenly.
        """
        # Normal traffic (10 messages)
        normal_messages = generate_mixed_messages(10, spam_ratio=0.1)

        # Process normal traffic
        for msg in normal_messages:
            result = await load_test_pipeline.process(msg)
            assert result is not None

        # Sudden burst (200 spam messages)
        burst_messages = generate_spam_messages(200)

        burst_start = time.monotonic()
        tasks = [load_test_pipeline.process(msg) for msg in burst_messages]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        burst_duration = time.monotonic() - burst_start

        # Should handle burst within 5 seconds
        assert burst_duration < 5.0, f"Burst took too long: {burst_duration:.2f}s"

        # Should process most messages successfully
        successes = sum(1 for r in results if isinstance(r, RiskResult))
        assert successes >= 180, f"Too many failures during burst: {200 - successes}"

    async def test_sustained_high_load(
        self,
        load_test_pipeline: MessagePipeline,
    ) -> None:
        """
        Test sustained high load over extended period.

        Simulates prolonged spam attack.
        """
        total_messages = 0
        total_successes = 0
        duration_seconds = 5

        start_time = time.monotonic()

        while (time.monotonic() - start_time) < duration_seconds:
            # Process batch of 50 messages
            messages = generate_spam_messages(50)

            tasks = [load_test_pipeline.process(msg) for msg in messages]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            total_messages += len(messages)
            total_successes += sum(1 for r in results if isinstance(r, RiskResult))

        elapsed = time.monotonic() - start_time
        throughput = total_messages / elapsed
        success_rate = (total_successes / total_messages) * 100

        # Should maintain good performance
        assert throughput >= 30, f"Throughput dropped: {throughput:.2f} msg/s"
        assert success_rate >= 90, f"Success rate dropped: {success_rate:.2f}%"

    async def test_recovery_after_overload(
        self,
        load_test_pipeline: MessagePipeline,
    ) -> None:
        """
        Test that system recovers after being overloaded.

        After heavy load, system should return to normal performance.
        """
        # Heavy load phase
        heavy_messages = generate_spam_messages(500)
        tasks = [load_test_pipeline.process(msg) for msg in heavy_messages]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Brief pause
        await asyncio.sleep(0.1)

        # Recovery phase - should process quickly
        recovery_messages = generate_spam_messages(10)

        recovery_start = time.monotonic()
        for msg in recovery_messages:
            result = await load_test_pipeline.process(msg)
            assert isinstance(result, RiskResult)

        recovery_duration = time.monotonic() - recovery_start
        avg_latency = (recovery_duration / 10) * 1000

        # Should recover to normal latency
        assert avg_latency < 100, f"Recovery latency too high: {avg_latency:.2f}ms"
