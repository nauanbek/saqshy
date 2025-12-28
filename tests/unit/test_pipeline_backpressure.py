"""
Tests for Pipeline Backpressure Handling

Tests the pipeline-level circuit breaker, semaphore-based concurrency limiting,
queue depth monitoring, and graceful degradation under load.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from saqshy.bot.pipeline import (
    DEGRADATION_CONFIG,
    DegradationLevel,
    MessagePipeline,
    PipelineCircuitBreaker,
)
from saqshy.core.types import GroupType, MessageContext, RiskResult, Signals, Verdict

# =============================================================================
# PipelineCircuitBreaker Tests
# =============================================================================


class TestPipelineCircuitBreaker:
    """Test suite for PipelineCircuitBreaker."""

    def test_initial_state_is_closed(self):
        """Circuit breaker starts in closed state."""
        breaker = PipelineCircuitBreaker()

        assert breaker.state == "closed"
        assert breaker.failures == 0
        assert breaker.allow_request() is True

    def test_circuit_breaker_opens_after_failures(self):
        """Circuit breaker opens after threshold failures."""
        breaker = PipelineCircuitBreaker(failure_threshold=5)

        # Record failures below threshold
        for i in range(4):
            breaker.record_failure()
            assert breaker.state == "closed", f"Should still be closed after {i+1} failures"

        # One more failure should open the circuit
        breaker.record_failure()
        assert breaker.state == "open"
        assert breaker.failures == 5
        assert breaker.allow_request() is False

    def test_circuit_breaker_recovers_after_timeout(self):
        """Circuit breaker transitions to half_open after recovery timeout."""
        breaker = PipelineCircuitBreaker(
            failure_threshold=3,
            recovery_timeout=0.1,  # 100ms for fast test
        )

        # Open the circuit
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == "open"
        assert breaker.is_open() is True

        # Wait for recovery timeout
        time.sleep(0.15)

        # Should now be half_open and allow requests
        assert breaker.is_open() is False
        assert breaker.state == "half_open"
        assert breaker.allow_request() is True

    def test_half_open_state_allows_limited_requests(self):
        """Half-open state allows limited requests for testing recovery."""
        breaker = PipelineCircuitBreaker(
            failure_threshold=3,
            recovery_timeout=0.01,
            half_open_requests=2,
        )

        # Open the circuit
        for _ in range(3):
            breaker.record_failure()

        # Wait for recovery
        time.sleep(0.02)
        assert breaker.is_open() is False
        assert breaker.state == "half_open"

        # First success
        breaker.record_success()
        assert breaker.state == "half_open"

        # Second success should close the circuit
        breaker.record_success()
        assert breaker.state == "closed"
        assert breaker.failures == 0

    def test_half_open_failure_reopens_circuit(self):
        """Failure in half-open state reopens the circuit."""
        breaker = PipelineCircuitBreaker(
            failure_threshold=3,
            recovery_timeout=0.01,
        )

        # Open the circuit
        for _ in range(3):
            breaker.record_failure()

        # Wait for recovery to half_open
        time.sleep(0.02)
        # Must call is_open() to trigger transition to half_open
        assert breaker.is_open() is False
        assert breaker.state == "half_open"

        # Failure should reopen
        breaker.record_failure()
        assert breaker.state == "open"

    def test_success_in_closed_state_decrements_failures(self):
        """Success in closed state gradually decrements failure count."""
        breaker = PipelineCircuitBreaker(failure_threshold=10)

        # Record some failures (but not enough to open)
        for _ in range(5):
            breaker.record_failure()
        assert breaker.failures == 5

        # Successes should decrement
        for _ in range(3):
            breaker.record_success()
        assert breaker.failures == 2

        # More successes bring it to 0
        for _ in range(5):
            breaker.record_success()
        assert breaker.failures == 0

    def test_reset_clears_state(self):
        """Reset returns circuit breaker to initial state."""
        breaker = PipelineCircuitBreaker(failure_threshold=3)

        # Open the circuit
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == "open"

        # Reset
        breaker.reset()
        assert breaker.state == "closed"
        assert breaker.failures == 0
        assert breaker.allow_request() is True

    def test_get_status_returns_complete_info(self):
        """get_status returns comprehensive circuit breaker state."""
        breaker = PipelineCircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            half_open_requests=3,
        )

        # Record some failures
        breaker.record_failure()
        breaker.record_failure()

        status = breaker.get_status()

        assert status["state"] == "closed"
        assert status["failures"] == 2
        assert status["failure_threshold"] == 5
        assert status["half_open_required"] == 3
        assert status["recovery_timeout"] == 30.0
        assert "total_failures" in status
        assert "total_opens" in status

    def test_total_opens_tracked(self):
        """Track total number of times circuit has opened."""
        breaker = PipelineCircuitBreaker(
            failure_threshold=2,
            recovery_timeout=0.01,
            half_open_requests=1,
        )

        # Open circuit first time
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.total_opens == 1

        # Recover
        time.sleep(0.02)
        breaker.is_open()  # Triggers transition to half_open
        breaker.record_success()  # Close it

        # Open again
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.total_opens == 2


# =============================================================================
# DegradationLevel Tests
# =============================================================================


class TestDegradationLevel:
    """Test suite for degradation levels."""

    def test_degradation_levels_defined(self):
        """All degradation levels are properly defined."""
        assert DegradationLevel.FULL == "full"
        assert DegradationLevel.REDUCED == "reduced"
        assert DegradationLevel.MINIMAL == "minimal"
        assert DegradationLevel.EMERGENCY == "emergency"

    def test_degradation_config_complete(self):
        """Each degradation level has complete configuration."""
        for level in [
            DegradationLevel.FULL,
            DegradationLevel.REDUCED,
            DegradationLevel.MINIMAL,
            DegradationLevel.EMERGENCY,
        ]:
            config = DEGRADATION_CONFIG[level]
            assert "analyzers" in config
            assert "llm_enabled" in config
            assert "description" in config

    def test_full_mode_has_all_analyzers(self):
        """Full mode enables all analyzers."""
        config = DEGRADATION_CONFIG[DegradationLevel.FULL]
        assert "profile" in config["analyzers"]
        assert "content" in config["analyzers"]
        assert "behavior" in config["analyzers"]
        assert "spam_db" in config["analyzers"]
        assert config["llm_enabled"] is True

    def test_minimal_mode_has_content_only(self):
        """Minimal mode only uses content analyzer."""
        config = DEGRADATION_CONFIG[DegradationLevel.MINIMAL]
        assert config["analyzers"] == ["content"]
        assert config["llm_enabled"] is False

    def test_emergency_mode_has_no_analyzers(self):
        """Emergency mode has no analyzers (fail-open)."""
        config = DEGRADATION_CONFIG[DegradationLevel.EMERGENCY]
        assert config["analyzers"] == []
        assert config["llm_enabled"] is False


# =============================================================================
# MessagePipeline Backpressure Tests
# =============================================================================


class TestMessagePipelineBackpressure:
    """Test suite for MessagePipeline backpressure handling."""

    @pytest.fixture
    def mock_pipeline(self):
        """Create a mock pipeline for testing."""
        from saqshy.analyzers.behavior import BehaviorAnalyzer
        from saqshy.analyzers.content import ContentAnalyzer
        from saqshy.analyzers.profile import ProfileAnalyzer
        from saqshy.core.risk_calculator import RiskCalculator

        pipeline = MessagePipeline(
            risk_calculator=RiskCalculator(group_type=GroupType.GENERAL),
            content_analyzer=ContentAnalyzer(),
            profile_analyzer=ProfileAnalyzer(),
            behavior_analyzer=BehaviorAnalyzer(),
            max_concurrent_requests=10,
        )
        return pipeline

    @pytest.fixture
    def sample_context(self) -> MessageContext:
        """Create sample message context."""
        from datetime import UTC, datetime

        return MessageContext(
            message_id=1,
            chat_id=-1001234567890,
            user_id=123456789,
            text="Test message",
            timestamp=datetime.now(UTC),
            chat_type="supergroup",
            group_type=GroupType.GENERAL,
        )

    def test_pipeline_has_circuit_breaker(self, mock_pipeline):
        """Pipeline should have a circuit breaker instance."""
        assert hasattr(mock_pipeline, "circuit_breaker")
        assert isinstance(mock_pipeline.circuit_breaker, PipelineCircuitBreaker)

    def test_pipeline_has_request_semaphore(self, mock_pipeline):
        """Pipeline should have a request semaphore."""
        assert hasattr(mock_pipeline, "request_semaphore")
        assert isinstance(mock_pipeline.request_semaphore, asyncio.Semaphore)

    def test_pipeline_tracks_active_requests(self, mock_pipeline):
        """Pipeline should track active request count."""
        assert mock_pipeline.active_requests == 0
        assert mock_pipeline._peak_active_requests == 0
        assert mock_pipeline._total_requests_processed == 0

    def test_pipeline_starts_in_full_mode(self, mock_pipeline):
        """Pipeline should start in full degradation mode."""
        assert mock_pipeline.degradation_level == DegradationLevel.FULL

    @pytest.mark.asyncio
    async def test_process_rejects_when_circuit_open(self, mock_pipeline, sample_context):
        """Process should fail-open when circuit breaker is open."""
        # Open the circuit breaker
        for _ in range(mock_pipeline.circuit_breaker.failure_threshold):
            mock_pipeline.circuit_breaker.record_failure()

        assert mock_pipeline.circuit_breaker.is_open() is True

        # Process should return ALLOW immediately
        result = await mock_pipeline.process(sample_context)

        assert result.verdict == Verdict.ALLOW
        assert "Backpressure" in str(result.contributing_factors)
        assert mock_pipeline._requests_rejected_by_backpressure >= 1

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_requests(self, mock_pipeline, sample_context):
        """Semaphore should limit concurrent request processing."""
        # Track concurrent request count
        max_concurrent_seen = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def slow_process_internal(*_args, **_kwargs):
            nonlocal max_concurrent_seen, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent_seen:
                    max_concurrent_seen = current_concurrent

            # Simulate some processing time
            await asyncio.sleep(0.05)

            async with lock:
                current_concurrent -= 1

            return RiskResult(
                score=0,
                verdict=Verdict.ALLOW,
                signals=Signals(),
            )

        mock_pipeline._process_internal = slow_process_internal

        # Create more requests than the semaphore allows
        max_concurrent = mock_pipeline._max_concurrent_requests
        tasks = [
            asyncio.create_task(mock_pipeline.process(sample_context))
            for _ in range(max_concurrent * 2)
        ]

        await asyncio.gather(*tasks)

        # Should never exceed semaphore limit
        assert max_concurrent_seen <= max_concurrent

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_overload(self, mock_pipeline):
        """Pipeline should degrade gracefully under high load."""
        # Simulate high queue utilization by setting active requests
        mock_pipeline._active_requests = int(
            mock_pipeline._max_concurrent_requests * 0.6
        )

        # Trigger degradation check
        log = MagicMock()
        mock_pipeline._check_degradation_threshold(log)

        # Should be in reduced mode at 60% utilization
        assert mock_pipeline.degradation_level == DegradationLevel.REDUCED

        # Increase to critical level
        mock_pipeline._active_requests = int(
            mock_pipeline._max_concurrent_requests * 0.85
        )
        mock_pipeline._check_degradation_threshold(log)

        # Should be in minimal mode at 85% utilization
        assert mock_pipeline.degradation_level == DegradationLevel.MINIMAL

        # Decrease load
        mock_pipeline._active_requests = int(
            mock_pipeline._max_concurrent_requests * 0.3
        )
        mock_pipeline._check_degradation_threshold(log)

        # Should return to full mode
        assert mock_pipeline.degradation_level == DegradationLevel.FULL

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_success_on_completion(
        self, mock_pipeline, sample_context
    ):
        """Circuit breaker should record success on successful processing."""
        # Add some failures first
        mock_pipeline.circuit_breaker.record_failure()
        mock_pipeline.circuit_breaker.record_failure()
        initial_failures = mock_pipeline.circuit_breaker.failures

        # Mock internal processing to succeed
        mock_pipeline._process_internal = AsyncMock(
            return_value=RiskResult(
                score=0,
                verdict=Verdict.ALLOW,
                signals=Signals(),
            )
        )

        await mock_pipeline.process(sample_context)

        # Should have decremented failures
        assert mock_pipeline.circuit_breaker.failures < initial_failures

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failure_on_timeout(
        self, mock_pipeline, sample_context
    ):
        """Circuit breaker should record failure on timeout."""
        initial_failures = mock_pipeline.circuit_breaker.failures

        # Mock internal processing to timeout
        async def slow_process(*_args, **_kwargs):
            await asyncio.sleep(10)  # Longer than pipeline timeout
            return RiskResult(score=0, verdict=Verdict.ALLOW, signals=Signals())

        mock_pipeline._process_internal = slow_process

        # Patch timeout to be very short
        with patch("saqshy.bot.pipeline.TOTAL_PIPELINE_TIMEOUT", 0.01):
            result = await mock_pipeline.process(sample_context)

        # Should have incremented failures
        assert mock_pipeline.circuit_breaker.failures > initial_failures
        # Should return WATCH on timeout
        assert result.verdict == Verdict.WATCH

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failure_on_exception(
        self, mock_pipeline, sample_context
    ):
        """Circuit breaker should record failure on exception."""
        initial_failures = mock_pipeline.circuit_breaker.failures

        # Mock internal processing to raise exception
        mock_pipeline._process_internal = AsyncMock(
            side_effect=RuntimeError("Test error")
        )

        result = await mock_pipeline.process(sample_context)

        # Should have incremented failures
        assert mock_pipeline.circuit_breaker.failures > initial_failures
        # Should return ALLOW on error (fail-open)
        assert result.verdict == Verdict.ALLOW

    def test_get_backpressure_status(self, mock_pipeline):
        """get_backpressure_status should return complete metrics."""
        # Simulate some activity
        mock_pipeline._active_requests = 5
        mock_pipeline._peak_active_requests = 10
        mock_pipeline._total_requests_processed = 100
        mock_pipeline._requests_rejected_by_backpressure = 3
        mock_pipeline.circuit_breaker.record_failure()

        status = mock_pipeline.get_backpressure_status()

        assert "circuit_breaker" in status
        assert "queue_depth" in status
        assert "degradation_level" in status
        assert "totals" in status

        assert status["queue_depth"]["active_requests"] == 5
        assert status["queue_depth"]["peak_active_requests"] == 10
        assert status["totals"]["total_requests_processed"] == 100
        assert status["totals"]["requests_rejected_by_backpressure"] == 3

    def test_is_under_pressure_property(self, mock_pipeline):
        """is_under_pressure should reflect current load state."""
        # Initial state should not be under pressure
        assert mock_pipeline.is_under_pressure is False

        # Set high queue utilization
        mock_pipeline._active_requests = int(
            mock_pipeline._max_concurrent_requests * 0.6
        )
        assert mock_pipeline.is_under_pressure is True

        # Reset
        mock_pipeline._active_requests = 0
        assert mock_pipeline.is_under_pressure is False

        # Open circuit breaker
        for _ in range(mock_pipeline.circuit_breaker.failure_threshold):
            mock_pipeline.circuit_breaker.record_failure()
        assert mock_pipeline.is_under_pressure is True

    def test_set_degradation_level_manual(self, mock_pipeline):
        """Manual degradation level setting should work."""
        assert mock_pipeline.degradation_level == DegradationLevel.FULL

        mock_pipeline.set_degradation_level(DegradationLevel.MINIMAL)
        assert mock_pipeline.degradation_level == DegradationLevel.MINIMAL

        # Invalid level should be ignored
        mock_pipeline.set_degradation_level("invalid")
        assert mock_pipeline.degradation_level == DegradationLevel.MINIMAL

    @pytest.mark.asyncio
    async def test_health_check_includes_pipeline_circuit(self, mock_pipeline):
        """Health check should include pipeline circuit breaker status."""
        health = await mock_pipeline.health_check()

        assert "pipeline_circuit" in health
        assert health["pipeline_circuit"] is True

        # Open the circuit
        for _ in range(mock_pipeline.circuit_breaker.failure_threshold):
            mock_pipeline.circuit_breaker.record_failure()

        health = await mock_pipeline.health_check()
        assert health["pipeline_circuit"] is False


# =============================================================================
# Integration Tests
# =============================================================================


class TestBackpressureIntegration:
    """Integration tests for backpressure handling."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_processed_correctly(self):
        """Multiple concurrent requests should be processed correctly."""
        from datetime import UTC, datetime

        from saqshy.analyzers.behavior import BehaviorAnalyzer
        from saqshy.analyzers.content import ContentAnalyzer
        from saqshy.analyzers.profile import ProfileAnalyzer
        from saqshy.core.risk_calculator import RiskCalculator

        pipeline = MessagePipeline(
            risk_calculator=RiskCalculator(group_type=GroupType.GENERAL),
            content_analyzer=ContentAnalyzer(),
            profile_analyzer=ProfileAnalyzer(),
            behavior_analyzer=BehaviorAnalyzer(),
            max_concurrent_requests=5,
        )

        contexts = [
            MessageContext(
                message_id=i,
                chat_id=-1001234567890,
                user_id=123456789 + i,
                text=f"Test message {i}",
                timestamp=datetime.now(UTC),
                chat_type="supergroup",
                group_type=GroupType.GENERAL,
            )
            for i in range(10)
        ]

        # Process all concurrently
        results = await asyncio.gather(
            *[pipeline.process(ctx) for ctx in contexts]
        )

        # All should complete with valid verdicts
        assert len(results) == 10
        for result in results:
            assert isinstance(result, RiskResult)
            assert result.verdict in list(Verdict)

        # Stats should reflect processing
        assert pipeline._total_requests_processed == 10
        assert pipeline._peak_active_requests <= 5  # Limited by semaphore

    @pytest.mark.asyncio
    async def test_circuit_opens_and_recovers_under_load(self):
        """Circuit should open under errors and recover after timeout."""
        from datetime import UTC, datetime

        from saqshy.analyzers.behavior import BehaviorAnalyzer
        from saqshy.analyzers.content import ContentAnalyzer
        from saqshy.analyzers.profile import ProfileAnalyzer
        from saqshy.core.risk_calculator import RiskCalculator

        pipeline = MessagePipeline(
            risk_calculator=RiskCalculator(group_type=GroupType.GENERAL),
            content_analyzer=ContentAnalyzer(),
            profile_analyzer=ProfileAnalyzer(),
            behavior_analyzer=BehaviorAnalyzer(),
            max_concurrent_requests=10,
        )

        # Configure fast recovery for test
        pipeline.circuit_breaker = PipelineCircuitBreaker(
            failure_threshold=3,
            recovery_timeout=0.1,
            half_open_requests=1,
        )

        context = MessageContext(
            message_id=1,
            chat_id=-1001234567890,
            user_id=123456789,
            text="Test message",
            timestamp=datetime.now(UTC),
            chat_type="supergroup",
            group_type=GroupType.GENERAL,
        )

        # Cause failures to open circuit
        async def failing_process(*_args, **_kwargs):
            raise RuntimeError("Simulated failure")

        pipeline._process_internal = failing_process

        for _ in range(3):
            await pipeline.process(context)

        assert pipeline.circuit_breaker.state == "open"

        # Requests should be rejected while open
        result = await pipeline.process(context)
        assert "Backpressure" in str(result.contributing_factors)

        # Wait for recovery
        await asyncio.sleep(0.15)

        # Fix the processing
        pipeline._process_internal = AsyncMock(
            return_value=RiskResult(
                score=0,
                verdict=Verdict.ALLOW,
                signals=Signals(),
            )
        )

        # Should now process successfully
        result = await pipeline.process(context)
        assert result.verdict == Verdict.ALLOW
        assert "Backpressure" not in str(result.contributing_factors)

        # Circuit should be closed after success
        assert pipeline.circuit_breaker.state == "closed"
