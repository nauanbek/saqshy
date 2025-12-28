"""
SAQSHY Message Processing Pipeline

Orchestrates the full message analysis pipeline with parallel execution,
timeouts, circuit breakers, and graceful degradation.

Pipeline Architecture:
    Message -> Preprocessor -> [Analyzers in parallel] -> RiskCalculator -> [Optional LLM] -> Decision
                                      |
                              [Profile, Content, Behavior, SpamDB]
                              (500ms timeout per analyzer, 5s total)

Design Principles:
    - No single analyzer failure should block the pipeline
    - Always return a result (never crash handlers)
    - Minimize LLM calls (only for gray zone 60-80)
    - Log all decisions for monitoring and debugging
    - Cache decisions to avoid redundant computation

Performance Targets:
    - p95 latency <200ms without LLM
    - p95 latency <5s with LLM
    - Never block on any single analyzer failure
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

from saqshy.analyzers.behavior import BehaviorAnalyzer
from saqshy.analyzers.content import ContentAnalyzer
from saqshy.analyzers.profile import ProfileAnalyzer
from saqshy.core.audit import AuditTrail
from saqshy.core.logging import get_correlation_id, get_logger
from saqshy.core.metrics import MetricsCollector
from saqshy.core.risk_calculator import RiskCalculator
from saqshy.core.constants import LLM_FIRST_MESSAGE_THRESHOLD
from saqshy.core.types import (
    BehaviorSignals,
    ContentSignals,
    MessageContext,
    NetworkSignals,
    ProfileSignals,
    RiskResult,
    Signals,
    Verdict,
)
from saqshy.services.cache import CacheService
from saqshy.services.channel_subscription import ChannelSubscriptionService
from saqshy.services.llm import LLMResult, LLMService
from saqshy.services.spam_db import SpamDB, SpamDBService

logger = get_logger(__name__)


# =============================================================================
# Pipeline Configuration
# =============================================================================

# Timeout configuration (seconds)
ANALYZER_TIMEOUT = 0.5  # 500ms per analyzer
SPAM_DB_TIMEOUT = 0.5  # 500ms for spam DB (includes embedding)
CHANNEL_SUB_TIMEOUT = 0.3  # 300ms for channel subscription check
LLM_TIMEOUT = 10.0  # 10 seconds for LLM
# CRITICAL: TOTAL must be >= LLM_TIMEOUT + analyzer overhead
# Otherwise LLM calls ALWAYS timeout (was 5.0, caused silent failures)
TOTAL_PIPELINE_TIMEOUT = 12.0  # 12 second hard limit (LLM + 2s buffer)

# Cache configuration
DECISION_CACHE_TTL = 300  # 5 minutes


# =============================================================================
# Pipeline-Level Circuit Breaker (Backpressure)
# =============================================================================


@dataclass
class PipelineCircuitBreaker:
    """
    Circuit breaker for the entire message processing pipeline.

    Opens when the system is overloaded (too many failures in a short time),
    preventing cascading failures during spam attacks or service degradation.

    States:
        - closed: Normal operation, all requests allowed
        - open: Circuit tripped, requests fail-fast with fallback
        - half_open: Testing recovery, limited requests allowed

    Usage:
        >>> breaker = PipelineCircuitBreaker()
        >>> if breaker.allow_request():
        ...     try:
        ...         result = await process_message(...)
        ...         breaker.record_success()
        ...     except Exception:
        ...         breaker.record_failure()
        ... else:
        ...     # Return fallback response
        ...     result = fallback_result()
    """

    failure_threshold: int = 10  # Failures before opening
    recovery_timeout: float = 30.0  # Seconds before trying half_open
    half_open_requests: int = 3  # Successful requests needed to close

    def __post_init__(self) -> None:
        """Initialize mutable state after dataclass creation."""
        self._failures: int = 0
        self._last_failure_time: float = 0.0
        self._state: str = "closed"  # closed, open, half_open
        self._half_open_successes: int = 0
        self._total_failures: int = 0  # Lifetime counter for metrics
        self._total_opens: int = 0  # Times circuit has opened

    @property
    def state(self) -> str:
        """Current circuit breaker state."""
        return self._state

    @property
    def failures(self) -> int:
        """Current failure count."""
        return self._failures

    @property
    def total_failures(self) -> int:
        """Lifetime failure count for metrics."""
        return self._total_failures

    @property
    def total_opens(self) -> int:
        """Number of times circuit has opened."""
        return self._total_opens

    def record_failure(self) -> None:
        """
        Record a pipeline failure.

        Increments failure counter and opens circuit if threshold exceeded.
        """
        self._failures += 1
        self._total_failures += 1
        self._last_failure_time = time.monotonic()

        if self._failures >= self.failure_threshold and self._state != "open":
            self._state = "open"
            self._total_opens += 1
            logger.warning(
                "pipeline_circuit_opened",
                failures=self._failures,
                threshold=self.failure_threshold,
                total_opens=self._total_opens,
            )

    def record_success(self) -> None:
        """
        Record a successful pipeline execution.

        In half_open state, counts towards recovery threshold.
        In closed state, decrements failure count (gradual recovery).
        """
        if self._state == "half_open":
            self._half_open_successes += 1
            if self._half_open_successes >= self.half_open_requests:
                self._state = "closed"
                self._failures = 0
                self._half_open_successes = 0
                logger.info(
                    "pipeline_circuit_closed",
                    half_open_successes=self.half_open_requests,
                )
        else:
            # Gradual recovery in closed state
            self._failures = max(0, self._failures - 1)

    def is_open(self) -> bool:
        """
        Check if circuit is currently open (blocking requests).

        Also handles transition from open to half_open when recovery
        timeout has elapsed.

        Returns:
            True if circuit is open and requests should be rejected.
        """
        if self._state == "open":
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = "half_open"
                self._half_open_successes = 0
                logger.info(
                    "pipeline_circuit_half_open",
                    recovery_timeout=self.recovery_timeout,
                )
                return False
            return True
        return False

    def allow_request(self) -> bool:
        """
        Check if a request should be allowed through.

        Returns:
            True if request should be processed, False if should fail-fast.
        """
        return not self.is_open()

    def reset(self) -> None:
        """
        Reset the circuit breaker to initial state.

        Useful for testing or manual recovery.
        """
        self._failures = 0
        self._state = "closed"
        self._half_open_successes = 0
        self._last_failure_time = 0.0

    def get_status(self) -> dict[str, Any]:
        """
        Get current circuit breaker status for monitoring.

        Returns:
            Dict with state, failure counts, and configuration.
        """
        return {
            "state": self._state,
            "failures": self._failures,
            "failure_threshold": self.failure_threshold,
            "half_open_successes": self._half_open_successes,
            "half_open_required": self.half_open_requests,
            "total_failures": self._total_failures,
            "total_opens": self._total_opens,
            "recovery_timeout": self.recovery_timeout,
        }


# =============================================================================
# Degradation Levels
# =============================================================================


class DegradationLevel:
    """
    Defines graceful degradation levels for the pipeline.

    When external services are unavailable or the system is overloaded,
    the pipeline can operate in reduced capacity modes.
    """

    FULL = "full"  # All analyzers enabled, LLM available
    REDUCED = "reduced"  # Core analyzers only, no LLM
    MINIMAL = "minimal"  # Content analysis only, fastest path
    EMERGENCY = "emergency"  # Fail-open, allow all messages


DEGRADATION_CONFIG: dict[str, dict[str, Any]] = {
    DegradationLevel.FULL: {
        "analyzers": ["profile", "content", "behavior", "spam_db", "channel_sub"],
        "llm_enabled": True,
        "description": "Full pipeline with all analyzers and LLM",
    },
    DegradationLevel.REDUCED: {
        "analyzers": ["profile", "content", "behavior"],
        "llm_enabled": False,
        "description": "Core analyzers only, external services skipped",
    },
    DegradationLevel.MINIMAL: {
        "analyzers": ["content"],
        "llm_enabled": False,
        "description": "Content analysis only for minimum latency",
    },
    DegradationLevel.EMERGENCY: {
        "analyzers": [],
        "llm_enabled": False,
        "description": "Emergency mode - fail-open, allow all messages",
    },
}


# =============================================================================
# Analyzer-Level Circuit Breaker
# =============================================================================


@dataclass
class CircuitBreakerState:
    """
    Track circuit breaker state for an analyzer.

    Implements the circuit breaker pattern to prevent repeated
    calls to failing services.

    Distinguishes between timeout errors (transient, recover quickly)
    and permanent errors (need longer recovery).
    """

    name: str
    failure_count: int = 0
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    last_failure_time: float = 0.0
    state: str = "closed"  # closed, open, half_open

    # Separate tracking for error types (H1 fix)
    timeout_count: int = 0
    permanent_count: int = 0
    timeout_threshold: int = 8  # More tolerant of transient timeouts
    permanent_threshold: int = 3  # Less tolerant of permanent errors
    timeout_recovery: float = 30.0  # Faster recovery for transient errors
    permanent_recovery: float = 120.0  # Slower recovery for permanent errors
    _last_error_was_timeout: bool = False

    def record_failure(self, is_timeout: bool = False) -> None:
        """
        Record a failure and potentially open the circuit.

        Args:
            is_timeout: True if failure was due to timeout (transient).
                       False for permanent errors (connection refused, etc).
        """
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        self._last_error_was_timeout = is_timeout

        if is_timeout:
            self.timeout_count += 1
            # Open only if timeout threshold exceeded
            if self.timeout_count >= self.timeout_threshold and self.state != "open":
                self.state = "open"
                logger.warning(
                    "circuit_breaker_opened",
                    analyzer=self.name,
                    failures=self.failure_count,
                    timeout_count=self.timeout_count,
                    error_type="timeout",
                )
        else:
            self.permanent_count += 1
            # Open immediately on permanent error threshold (stricter)
            if self.permanent_count >= self.permanent_threshold and self.state != "open":
                self.state = "open"
                logger.warning(
                    "circuit_breaker_opened",
                    analyzer=self.name,
                    failures=self.failure_count,
                    permanent_count=self.permanent_count,
                    error_type="permanent",
                )

        # Fallback to legacy threshold for backwards compatibility
        if self.failure_count >= self.failure_threshold and self.state != "open":
            self.state = "open"
            logger.warning(
                "circuit_breaker_opened",
                analyzer=self.name,
                failures=self.failure_count,
                error_type="combined",
            )

    def record_success(self) -> None:
        """Record a success and reset the circuit."""
        if self.state == "half_open":
            logger.info(
                "circuit_breaker_closed",
                analyzer=self.name,
            )
        self.failure_count = 0
        self.timeout_count = 0
        self.permanent_count = 0
        self.state = "closed"

    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        if self.state == "closed":
            return False

        if self.state == "open":
            # Use different recovery times based on last error type
            recovery = (
                self.timeout_recovery
                if self._last_error_was_timeout
                else self.permanent_recovery
            )

            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= recovery:
                self.state = "half_open"
                logger.info(
                    "circuit_breaker_half_open",
                    analyzer=self.name,
                    recovery_time=recovery,
                    error_type="timeout" if self._last_error_was_timeout else "permanent",
                )
                return False
            return True

        # half_open: allow one request
        return False

    def get_status(self) -> dict[str, Any]:
        """Get detailed status for monitoring."""
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "timeout_count": self.timeout_count,
            "permanent_count": self.permanent_count,
            "failure_threshold": self.failure_threshold,
            "timeout_threshold": self.timeout_threshold,
            "permanent_threshold": self.permanent_threshold,
        }


# =============================================================================
# Pipeline Metrics
# =============================================================================


@dataclass
class PipelineMetrics:
    """
    Metrics collected during pipeline execution.

    Used for monitoring, debugging, and performance analysis.
    """

    start_time: float = 0.0
    end_time: float = 0.0

    # Analyzer timings (milliseconds)
    profile_ms: float = 0.0
    content_ms: float = 0.0
    behavior_ms: float = 0.0
    spam_db_ms: float = 0.0
    channel_sub_ms: float = 0.0
    risk_calc_ms: float = 0.0
    llm_ms: float = 0.0

    # Analyzer status
    profile_success: bool = False
    content_success: bool = False
    behavior_success: bool = False
    spam_db_success: bool = False
    channel_sub_success: bool = False
    llm_called: bool = False
    llm_success: bool = False

    # Cache status
    cache_hit: bool = False

    @property
    def total_ms(self) -> float:
        """Total pipeline execution time in milliseconds."""
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary for logging."""
        return {
            "total_ms": round(self.total_ms, 2),
            "profile_ms": round(self.profile_ms, 2),
            "content_ms": round(self.content_ms, 2),
            "behavior_ms": round(self.behavior_ms, 2),
            "spam_db_ms": round(self.spam_db_ms, 2),
            "channel_sub_ms": round(self.channel_sub_ms, 2),
            "risk_calc_ms": round(self.risk_calc_ms, 2),
            "llm_ms": round(self.llm_ms, 2),
            "profile_success": self.profile_success,
            "content_success": self.content_success,
            "behavior_success": self.behavior_success,
            "spam_db_success": self.spam_db_success,
            "channel_sub_success": self.channel_sub_success,
            "llm_called": self.llm_called,
            "llm_success": self.llm_success,
            "cache_hit": self.cache_hit,
        }


# =============================================================================
# Message Pipeline
# =============================================================================


class MessagePipeline:
    """
    Orchestrates the complete message processing pipeline.

    Runs all analyzers in parallel, calculates risk score,
    and optionally calls LLM for gray zone decisions.

    Thread Safety:
        This class is thread-safe when used with asyncio.
        All state is per-request, with shared services being thread-safe.

    Error Handling:
        Never raises exceptions to callers. All errors are caught,
        logged, and result in graceful degradation with default values.

    Example:
        >>> pipeline = MessagePipeline(
        ...     risk_calculator=risk_calc,
        ...     content_analyzer=content_analyzer,
        ...     profile_analyzer=profile_analyzer,
        ...     behavior_analyzer=behavior_analyzer,
        ...     spam_db=spam_db_service,
        ...     llm_service=llm_service,
        ...     cache_service=cache_service,
        ... )
        >>>
        >>> result = await pipeline.process(
        ...     context=message_context,
        ...     linked_channel_id=channel_id,
        ...     admin_ids={admin_id},
        ... )
        >>> print(f"Verdict: {result.verdict}, Score: {result.score}")
    """

    # Default configuration for backpressure handling
    DEFAULT_MAX_CONCURRENT_REQUESTS = 100
    DEFAULT_QUEUE_WARNING_THRESHOLD = 50
    DEFAULT_QUEUE_CRITICAL_THRESHOLD = 80

    def __init__(
        self,
        risk_calculator: RiskCalculator,
        content_analyzer: ContentAnalyzer,
        profile_analyzer: ProfileAnalyzer,
        behavior_analyzer: BehaviorAnalyzer,
        spam_db: SpamDB | SpamDBService | None = None,
        llm_service: LLMService | None = None,
        cache_service: CacheService | None = None,
        channel_subscription: ChannelSubscriptionService | None = None,
        metrics_collector: MetricsCollector | None = None,
        audit_trail: AuditTrail | None = None,
        max_concurrent_requests: int | None = None,
    ) -> None:
        """
        Initialize the message pipeline.

        Args:
            risk_calculator: RiskCalculator instance for score calculation.
            content_analyzer: ContentAnalyzer for message text analysis.
            profile_analyzer: ProfileAnalyzer for user profile analysis.
            behavior_analyzer: BehaviorAnalyzer for user behavior analysis.
            spam_db: Optional SpamDB service for similarity search.
            llm_service: Optional LLMService for gray zone decisions.
            cache_service: Optional CacheService for decision caching.
            channel_subscription: Optional service for channel subscription checks.
            metrics_collector: Optional MetricsCollector for observability.
            audit_trail: Optional AuditTrail for decision logging.
            max_concurrent_requests: Maximum concurrent pipeline executions (default: 100).
        """
        self.risk_calculator = risk_calculator
        self.content_analyzer = content_analyzer
        self.profile_analyzer = profile_analyzer
        self.behavior_analyzer = behavior_analyzer
        self.spam_db = spam_db
        self.llm_service = llm_service
        self.cache_service = cache_service
        self.channel_subscription = channel_subscription
        self.metrics_collector = metrics_collector
        self.audit_trail = audit_trail

        # Circuit breakers for each analyzer
        self._circuit_breakers: dict[str, CircuitBreakerState] = {
            "profile": CircuitBreakerState(name="profile"),
            "content": CircuitBreakerState(name="content"),
            "behavior": CircuitBreakerState(name="behavior"),
            "spam_db": CircuitBreakerState(name="spam_db"),
            "channel_sub": CircuitBreakerState(name="channel_sub"),
            "llm": CircuitBreakerState(name="llm", failure_threshold=3, recovery_timeout=60.0),
        }

        # Pipeline-level circuit breaker for backpressure
        self.circuit_breaker = PipelineCircuitBreaker()

        # Semaphore for limiting concurrent requests
        max_concurrent = max_concurrent_requests or self.DEFAULT_MAX_CONCURRENT_REQUESTS
        self.request_semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent_requests = max_concurrent

        # Queue depth tracking
        self._active_requests: int = 0
        self._peak_active_requests: int = 0
        self._total_requests_processed: int = 0
        self._requests_rejected_by_backpressure: int = 0

        # Degradation level
        self._degradation_level: str = DegradationLevel.FULL

        logger.info(
            "pipeline_initialized",
            has_spam_db=spam_db is not None,
            has_llm=llm_service is not None,
            has_cache=cache_service is not None,
            has_channel_sub=channel_subscription is not None,
            has_metrics=metrics_collector is not None,
            has_audit=audit_trail is not None,
            max_concurrent_requests=max_concurrent,
        )

    # =========================================================================
    # Main Pipeline Entry Point
    # =========================================================================

    async def process(
        self,
        context: MessageContext,
        linked_channel_id: int | None = None,
        admin_ids: set[int] | None = None,
    ) -> RiskResult:
        """
        Process a message through the full pipeline.

        This is the main entry point for message analysis. It:
        1. Checks backpressure (circuit breaker and concurrency limit)
        2. Checks decision cache
        3. Runs all analyzers in parallel
        4. Calculates risk score
        5. Optionally calls LLM for gray zone
        6. Returns final verdict

        Args:
            context: MessageContext with message data.
            linked_channel_id: Optional ID of linked channel for subscription check.
            admin_ids: Optional set of admin user IDs for reply-to-admin detection.

        Returns:
            RiskResult with verdict, score, and signal breakdown.
        """
        metrics = PipelineMetrics(start_time=time.monotonic())

        log = logger.bind(
            message_id=context.message_id,
            chat_id=context.chat_id,
            user_id=context.user_id,
        )

        # Get correlation ID for tracing
        correlation_id = get_correlation_id()

        # Check pipeline circuit breaker (backpressure)
        if not self.circuit_breaker.allow_request():
            self._requests_rejected_by_backpressure += 1
            log.warning(
                "pipeline_circuit_open_rejected",
                correlation_id=correlation_id,
                rejected_count=self._requests_rejected_by_backpressure,
                circuit_state=self.circuit_breaker.state,
            )

            # Record rejection in metrics
            if self.metrics_collector:
                await self.metrics_collector.record_error(
                    group_type=context.group_type.value,
                    error_type="backpressure_rejected",
                )

            # Fail-open: allow message through when overloaded
            return RiskResult(
                score=0,
                verdict=Verdict.ALLOW,
                signals=Signals(),
                contributing_factors=["Backpressure - pipeline circuit open"],
            )

        # Check if we're at degradation threshold
        self._check_degradation_threshold(log)

        # Acquire semaphore for concurrent request limiting
        # Try to acquire semaphore with minimal timeout for backpressure
        # If we can't acquire within 10ms, apply graceful degradation
        try:
            # Only timeout on semaphore acquisition, not processing
            await asyncio.wait_for(
                self.request_semaphore.acquire(),
                timeout=0.01,  # 10ms timeout for semaphore acquisition only
            )
        except TimeoutError:
            # At capacity - graceful degradation
            log.warning(
                "pipeline_at_capacity_degradation",
                active_requests=self._active_requests,
                max_concurrent=self._max_concurrent_requests,
            )
            return RiskResult(
                score=0,
                verdict=Verdict.ALLOW,
                signals=Signals(),
                contributing_factors=["Backpressure - graceful degradation (semaphore timeout)"],
            )

        # Semaphore acquired - process the request
        try:
            return await self._process_with_tracking(
                context=context,
                linked_channel_id=linked_channel_id,
                admin_ids=admin_ids,
                metrics=metrics,
                log=log,
                correlation_id=correlation_id,
            )
        finally:
            # Always release the semaphore
            self.request_semaphore.release()

    async def _process_with_tracking(
        self,
        context: MessageContext,
        linked_channel_id: int | None,
        admin_ids: set[int] | None,
        metrics: PipelineMetrics,
        log: Any,
        correlation_id: str,
    ) -> RiskResult:
        """
        Process message with active request tracking.

        Wraps the internal processing with queue depth tracking
        and circuit breaker recording.

        Args:
            context: Message context.
            linked_channel_id: Linked channel ID.
            admin_ids: Admin user IDs.
            metrics: Metrics collector.
            log: Bound logger.
            correlation_id: Request correlation ID.

        Returns:
            RiskResult from the pipeline.
        """
        # Track active requests
        self._active_requests += 1
        self._total_requests_processed += 1
        if self._active_requests > self._peak_active_requests:
            self._peak_active_requests = self._active_requests

        try:
            # Apply total pipeline timeout
            result = await asyncio.wait_for(
                self._process_internal(
                    context=context,
                    linked_channel_id=linked_channel_id,
                    admin_ids=admin_ids,
                    metrics=metrics,
                    log=log,
                ),
                timeout=TOTAL_PIPELINE_TIMEOUT,
            )

            metrics.end_time = time.monotonic()

            log.info(
                "pipeline_completed",
                correlation_id=correlation_id,
                verdict=result.verdict.value,
                score=result.score,
                active_requests=self._active_requests,
                degradation_level=self._degradation_level,
                **metrics.to_dict(),
            )

            # Record success on circuit breaker
            self.circuit_breaker.record_success()

            # Record metrics and audit trail
            await self._record_observability(
                correlation_id=correlation_id,
                context=context,
                result=result,
                metrics=metrics,
            )

            return result

        except TimeoutError:
            metrics.end_time = time.monotonic()
            log.error(
                "pipeline_timeout",
                correlation_id=correlation_id,
                timeout_seconds=TOTAL_PIPELINE_TIMEOUT,
                active_requests=self._active_requests,
                **metrics.to_dict(),
            )

            # Record timeout failure on circuit breaker (transient, recovers faster)
            self.circuit_breaker.record_failure()

            # Record error in metrics
            if self.metrics_collector:
                await self.metrics_collector.record_error(
                    group_type=context.group_type.value,
                    error_type="pipeline_timeout",
                )

            # Return conservative WATCH verdict on timeout
            return RiskResult(
                score=50,
                verdict=Verdict.WATCH,
                signals=Signals(),
                contributing_factors=["Pipeline timeout - conservative verdict"],
            )

        except Exception as e:
            metrics.end_time = time.monotonic()
            log.exception(
                "pipeline_error",
                correlation_id=correlation_id,
                error=str(e),
                error_type=type(e).__name__,
                active_requests=self._active_requests,
                **metrics.to_dict(),
            )

            # Record failure on circuit breaker
            self.circuit_breaker.record_failure()

            # Record error in metrics
            if self.metrics_collector:
                await self.metrics_collector.record_error(
                    group_type=context.group_type.value,
                    error_type=type(e).__name__,
                )

            # Return ALLOW on unexpected errors (fail-open for user experience)
            return RiskResult(
                score=0,
                verdict=Verdict.ALLOW,
                signals=Signals(),
                contributing_factors=["Pipeline error - defaulting to allow"],
            )

        finally:
            # Always decrement active request count
            self._active_requests -= 1

    def _check_degradation_threshold(self, log: Any) -> None:
        """
        Check if we should change degradation level based on queue depth.

        Args:
            log: Bound logger for warnings.
        """
        queue_utilization = (
            self._active_requests / self._max_concurrent_requests * 100
            if self._max_concurrent_requests > 0
            else 0
        )

        old_level = self._degradation_level

        if queue_utilization >= self.DEFAULT_QUEUE_CRITICAL_THRESHOLD:
            self._degradation_level = DegradationLevel.MINIMAL
        elif queue_utilization >= self.DEFAULT_QUEUE_WARNING_THRESHOLD:
            self._degradation_level = DegradationLevel.REDUCED
        else:
            self._degradation_level = DegradationLevel.FULL

        if old_level != self._degradation_level:
            log.warning(
                "degradation_level_changed",
                old_level=old_level,
                new_level=self._degradation_level,
                queue_utilization=round(queue_utilization, 1),
                active_requests=self._active_requests,
            )

    async def _record_observability(
        self,
        correlation_id: str,
        context: MessageContext,
        result: RiskResult,
        metrics: PipelineMetrics,
    ) -> None:
        """
        Record metrics and audit trail for a decision.

        Args:
            correlation_id: Request correlation ID.
            context: Message context.
            result: Pipeline result.
            metrics: Pipeline metrics.
        """
        total_ms = (metrics.end_time - metrics.start_time) * 1000

        # Build metrics dict for audit trail
        pipeline_metrics = {
            "total_ms": total_ms,
            "profile_ms": metrics.profile_ms,
            "content_ms": metrics.content_ms,
            "behavior_ms": metrics.behavior_ms,
            "spam_db_ms": metrics.spam_db_ms,
            "llm_ms": metrics.llm_ms if metrics.llm_called else None,
        }

        # Record to MetricsCollector
        if self.metrics_collector:
            try:
                await self.metrics_collector.record_verdict(
                    group_type=context.group_type.value,
                    verdict=result.verdict.value,
                    risk_score=result.score,
                    threat_type=result.threat_type.value if result.threat_type else "none",
                    latency_ms=total_ms,
                    llm_called=metrics.llm_called,
                    llm_latency_ms=metrics.llm_ms if metrics.llm_called else None,
                )
            except Exception as e:
                logger.debug("metrics_recording_failed", error=str(e))

        # Record to AuditTrail (persists to database)
        if self.audit_trail:
            try:
                await self.audit_trail.log_decision(
                    correlation_id=correlation_id,
                    context=context,
                    result=result,
                    pipeline_metrics=pipeline_metrics,
                )
            except Exception as e:
                logger.debug("audit_trail_recording_failed", error=str(e))

    async def _process_internal(
        self,
        context: MessageContext,
        linked_channel_id: int | None,
        admin_ids: set[int] | None,
        metrics: PipelineMetrics,
        log: Any,
    ) -> RiskResult:
        """
        Internal pipeline processing logic.

        Args:
            context: Message context.
            linked_channel_id: Linked channel ID.
            admin_ids: Admin user IDs.
            metrics: Metrics collector.
            log: Bound logger.

        Returns:
            RiskResult from the pipeline.
        """
        # Check decision cache first
        message_hash = self._get_message_hash(context)
        cached_decision = await self._check_cache(message_hash, metrics)

        if cached_decision is not None:
            log.debug("cache_hit", message_hash=message_hash[:8])
            return cached_decision

        # Collect signals from all analyzers in parallel
        signals = await self._collect_signals(
            context=context,
            linked_channel_id=linked_channel_id,
            admin_ids=admin_ids,
            metrics=metrics,
        )

        # Calculate risk score
        calc_start = time.monotonic()
        result = self.risk_calculator.calculate(signals)
        metrics.risk_calc_ms = (time.monotonic() - calc_start) * 1000

        # Force LLM for risky first messages from unestablished users
        # This catches sophisticated spam that evades rule-based detection
        if (
            signals.behavior.is_first_message
            and signals.behavior.previous_messages_approved < 3
            and result.score >= LLM_FIRST_MESSAGE_THRESHOLD
            and not result.needs_llm  # Don't double-set
            and self.llm_service is not None
        ):
            result.needs_llm = True
            log.info(
                "forcing_llm_for_first_message",
                score=result.score,
                threshold=LLM_FIRST_MESSAGE_THRESHOLD,
                previous_approved=signals.behavior.previous_messages_approved,
            )

        # Check if LLM review is needed (gray zone or forced for first messages)
        if result.needs_llm and self.llm_service is not None:
            result = await self._call_llm_for_gray_zone(
                context=context,
                signals=signals,
                result=result,
                metrics=metrics,
                log=log,
            )

        # Cache the decision
        await self._cache_decision(message_hash, result, metrics)

        return result

    # =========================================================================
    # Signal Collection
    # =========================================================================

    async def _collect_signals(
        self,
        context: MessageContext,
        linked_channel_id: int | None,
        admin_ids: set[int] | None,
        metrics: PipelineMetrics,
    ) -> Signals:
        """
        Collect signals from all analyzers in parallel.

        Uses asyncio.gather with return_exceptions=True for fault tolerance.
        Each analyzer has its own timeout and circuit breaker.

        Args:
            context: Message context.
            linked_channel_id: Linked channel ID.
            admin_ids: Admin user IDs.
            metrics: Metrics collector.

        Returns:
            Aggregated Signals from all analyzers.
        """
        # Create tasks for each analyzer
        tasks: list[asyncio.Task[Any]] = [
            asyncio.create_task(
                self._run_profile_analyzer(context, metrics),
                name="profile",
            ),
            asyncio.create_task(
                self._run_content_analyzer(context, metrics),
                name="content",
            ),
            asyncio.create_task(
                self._run_behavior_analyzer(context, linked_channel_id, admin_ids, metrics),
                name="behavior",
            ),
            asyncio.create_task(
                self._run_spam_db_analyzer(context, metrics),
                name="spam_db",
            ),
        ]

        # Run all tasks in parallel, handling exceptions
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results, using defaults for failures
        profile_signals = self._process_result(results[0], ProfileSignals, "profile")
        content_signals = self._process_result(results[1], ContentSignals, "content")
        behavior_signals = self._process_result(results[2], BehaviorSignals, "behavior")
        network_signals = self._process_result(results[3], NetworkSignals, "spam_db")

        # Update metrics with success status
        metrics.profile_success = not isinstance(results[0], (Exception, BaseException))
        metrics.content_success = not isinstance(results[1], (Exception, BaseException))
        metrics.behavior_success = not isinstance(results[2], (Exception, BaseException))
        metrics.spam_db_success = not isinstance(results[3], (Exception, BaseException))

        return Signals(
            profile=profile_signals,
            content=content_signals,
            behavior=behavior_signals,
            network=network_signals,
        )

    def _process_result(
        self,
        result: Any,
        default_type: type,
        analyzer_name: str,
    ) -> Any:
        """
        Process analyzer result, returning default on failure.

        Args:
            result: Result from asyncio.gather (may be exception).
            default_type: Default dataclass type to return on failure.
            analyzer_name: Name of analyzer for logging.

        Returns:
            Result or default instance.
        """
        if isinstance(result, (Exception, BaseException)):
            logger.warning(
                "analyzer_failed",
                analyzer=analyzer_name,
                error=str(result),
                error_type=type(result).__name__,
            )
            return default_type()
        return result

    # =========================================================================
    # Individual Analyzer Runners
    # =========================================================================

    async def _run_profile_analyzer(
        self,
        context: MessageContext,
        metrics: PipelineMetrics,
    ) -> ProfileSignals:
        """Run profile analyzer with timeout and circuit breaker."""
        return await self._run_with_timeout(
            coro=self.profile_analyzer.analyze(context),
            timeout=ANALYZER_TIMEOUT,
            analyzer_name="profile",
            metrics_attr="profile_ms",
            metrics=metrics,
            default=ProfileSignals(),
        )

    async def _run_content_analyzer(
        self,
        context: MessageContext,
        metrics: PipelineMetrics,
    ) -> ContentSignals:
        """Run content analyzer with timeout and circuit breaker."""
        return await self._run_with_timeout(
            coro=self.content_analyzer.analyze(context),
            timeout=ANALYZER_TIMEOUT,
            analyzer_name="content",
            metrics_attr="content_ms",
            metrics=metrics,
            default=ContentSignals(),
        )

    async def _run_behavior_analyzer(
        self,
        context: MessageContext,
        linked_channel_id: int | None,
        admin_ids: set[int] | None,
        metrics: PipelineMetrics,
    ) -> BehaviorSignals:
        """Run behavior analyzer with timeout and circuit breaker."""
        return await self._run_with_timeout(
            coro=self.behavior_analyzer.analyze(
                context=context,
                linked_channel_id=linked_channel_id,
                admin_ids=admin_ids,
            ),
            timeout=ANALYZER_TIMEOUT,
            analyzer_name="behavior",
            metrics_attr="behavior_ms",
            metrics=metrics,
            default=BehaviorSignals(),
        )

    async def _run_spam_db_analyzer(
        self,
        context: MessageContext,
        metrics: PipelineMetrics,
    ) -> NetworkSignals:
        """Run spam database analyzer with timeout and circuit breaker."""
        if self.spam_db is None:
            return NetworkSignals()

        return await self._run_with_timeout(
            coro=self._check_spam_db(context),
            timeout=SPAM_DB_TIMEOUT,
            analyzer_name="spam_db",
            metrics_attr="spam_db_ms",
            metrics=metrics,
            default=NetworkSignals(),
        )

    async def _run_with_timeout(
        self,
        coro: Coroutine[Any, Any, Any],
        timeout: float,
        analyzer_name: str,
        metrics_attr: str,
        metrics: PipelineMetrics,
        default: Any,
    ) -> Any:
        """
        Run a coroutine with timeout and circuit breaker.

        Args:
            coro: Coroutine to run.
            timeout: Timeout in seconds.
            analyzer_name: Name for logging and circuit breaker.
            metrics_attr: Attribute name on metrics to store timing.
            metrics: Metrics collector.
            default: Default value to return on failure.

        Returns:
            Coroutine result or default on timeout/error.
        """
        circuit_breaker = self._circuit_breakers.get(analyzer_name)

        # Check circuit breaker
        if circuit_breaker and circuit_breaker.is_open():
            logger.debug(
                "circuit_breaker_skipped",
                analyzer=analyzer_name,
            )
            return default

        start_time = time.monotonic()

        try:
            result = await asyncio.wait_for(coro, timeout=timeout)

            # Record timing
            elapsed_ms = (time.monotonic() - start_time) * 1000
            setattr(metrics, metrics_attr, elapsed_ms)

            # Record success
            if circuit_breaker:
                circuit_breaker.record_success()

            return result

        except TimeoutError:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            setattr(metrics, metrics_attr, elapsed_ms)

            logger.warning(
                "analyzer_timeout",
                analyzer=analyzer_name,
                timeout=timeout,
                elapsed_ms=round(elapsed_ms, 2),
            )

            if circuit_breaker:
                # Timeout is transient - more tolerant threshold, faster recovery
                circuit_breaker.record_failure(is_timeout=True)

            return default

        except Exception as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            setattr(metrics, metrics_attr, elapsed_ms)

            logger.warning(
                "analyzer_error",
                analyzer=analyzer_name,
                error=str(e),
                error_type=type(e).__name__,
            )

            if circuit_breaker:
                # Permanent error - stricter threshold, slower recovery
                circuit_breaker.record_failure(is_timeout=False)

            return default

    # =========================================================================
    # Spam Database Check
    # =========================================================================

    async def _check_spam_db(self, context: MessageContext) -> NetworkSignals:
        """
        Check message against spam database.

        Uses embeddings to find similar spam patterns.

        Args:
            context: Message context.

        Returns:
            NetworkSignals with spam_db_similarity populated.
        """
        if not context.text or len(context.text.strip()) < 10:
            return NetworkSignals()

        try:
            similarity, matched_text = await self.spam_db.check_spam(context.text)

            if similarity > 0:
                logger.debug(
                    "spam_db_match",
                    similarity=round(similarity, 3),
                    matched_preview=matched_text[:50] if matched_text else None,
                )

            return NetworkSignals(
                spam_db_similarity=similarity,
                spam_db_matched_pattern=matched_text,
            )

        except Exception as e:
            logger.warning(
                "spam_db_check_error",
                error=str(e),
            )
            return NetworkSignals()

    # =========================================================================
    # LLM Gray Zone Handling
    # =========================================================================

    async def _call_llm_for_gray_zone(
        self,
        context: MessageContext,
        signals: Signals,
        result: RiskResult,
        metrics: PipelineMetrics,
        log: Any,
    ) -> RiskResult:
        """
        Call LLM for gray zone decisions (score 60-80).

        Args:
            context: Message context.
            signals: Collected signals.
            result: Initial risk result.
            metrics: Metrics collector.
            log: Bound logger.

        Returns:
            Updated RiskResult with LLM verdict.
        """
        metrics.llm_called = True

        # Check circuit breaker
        llm_circuit = self._circuit_breakers.get("llm")
        if llm_circuit and llm_circuit.is_open():
            log.debug("llm_circuit_open_skipped")
            return result

        # Build summaries for LLM
        profile_summary = self._build_profile_summary(signals, context)
        behavior_summary = self._build_behavior_summary(signals, context)

        llm_start = time.monotonic()

        try:
            llm_result: LLMResult = await asyncio.wait_for(
                self.llm_service.analyze_message(
                    message_text=context.text or "",
                    profile_summary=profile_summary,
                    behavior_summary=behavior_summary,
                    current_score=result.score,
                    group_type=context.group_type.value,
                ),
                timeout=LLM_TIMEOUT,
            )

            metrics.llm_ms = (time.monotonic() - llm_start) * 1000

            if llm_result.error:
                log.warning(
                    "llm_error",
                    error=llm_result.error,
                )
                if llm_circuit:
                    llm_circuit.record_failure()
                return result

            # Record success
            if llm_circuit:
                llm_circuit.record_success()
            metrics.llm_success = True

            # Update result with LLM verdict
            result.llm_verdict = llm_result.verdict
            result.llm_explanation = llm_result.reason
            result.confidence = llm_result.confidence

            # If LLM says BLOCK, update verdict
            if llm_result.verdict == Verdict.BLOCK:
                result.verdict = Verdict.BLOCK
                result.contributing_factors.append(
                    f"LLM verdict: BLOCK (confidence: {llm_result.confidence:.2f})"
                )
            elif llm_result.verdict == Verdict.ALLOW:
                # LLM says ALLOW, reduce to WATCH if currently higher
                if result.verdict in (Verdict.LIMIT, Verdict.REVIEW, Verdict.BLOCK):
                    result.verdict = Verdict.WATCH
                    result.mitigating_factors.append(
                        f"LLM verdict: ALLOW (confidence: {llm_result.confidence:.2f})"
                    )

            log.info(
                "llm_verdict",
                llm_verdict=llm_result.verdict.value,
                confidence=llm_result.confidence,
                reason=llm_result.reason[:100] if llm_result.reason else None,
                final_verdict=result.verdict.value,
            )

            return result

        except TimeoutError:
            metrics.llm_ms = (time.monotonic() - llm_start) * 1000
            log.warning(
                "llm_timeout",
                timeout=LLM_TIMEOUT,
            )
            if llm_circuit:
                # Timeout is transient - more tolerant, faster recovery
                llm_circuit.record_failure(is_timeout=True)
            return result

        except Exception as e:
            metrics.llm_ms = (time.monotonic() - llm_start) * 1000
            log.exception(
                "llm_call_error",
                error=str(e),
            )
            if llm_circuit:
                # Permanent error - stricter threshold
                llm_circuit.record_failure(is_timeout=False)
            return result

    # =========================================================================
    # LLM Summary Builders
    # =========================================================================

    def _build_profile_summary(
        self,
        signals: Signals,
        context: MessageContext,
    ) -> str:
        """
        Build human-readable profile summary for LLM.

        Args:
            signals: Collected signals.
            context: Message context.

        Returns:
            Profile summary string.
        """
        profile = signals.profile
        parts: list[str] = []

        # Account age
        if profile.account_age_days >= 365:
            years = profile.account_age_days // 365
            parts.append(f"Account age: ~{years} year(s) (established)")
        elif profile.account_age_days >= 30:
            months = profile.account_age_days // 30
            parts.append(f"Account age: ~{months} month(s)")
        elif profile.account_age_days >= 7:
            parts.append(f"Account age: {profile.account_age_days} days")
        else:
            parts.append(f"Account age: {profile.account_age_days} days (NEW)")

        # Profile completeness
        completeness: list[str] = []
        if profile.has_username:
            completeness.append("username")
        if profile.has_profile_photo:
            completeness.append("photo")
        if profile.has_bio:
            completeness.append("bio")
        if profile.is_premium:
            completeness.append("Premium")

        if completeness:
            parts.append(f"Profile: {', '.join(completeness)}")
        else:
            parts.append("Profile: minimal (no photo, no username)")

        # Risk signals
        risk_signals: list[str] = []
        if profile.username_has_random_chars:
            risk_signals.append("random username")
        if profile.bio_has_crypto_terms:
            risk_signals.append("crypto terms in bio")
        if profile.bio_has_links:
            risk_signals.append("links in bio")
        if profile.name_has_emoji_spam:
            risk_signals.append("emoji spam in name")

        if risk_signals:
            parts.append(f"Risk signals: {', '.join(risk_signals)}")

        return "\n".join(parts)

    def _build_behavior_summary(
        self,
        signals: Signals,
        context: MessageContext,
    ) -> str:
        """
        Build human-readable behavior summary for LLM.

        Args:
            signals: Collected signals.
            context: Message context.

        Returns:
            Behavior summary string.
        """
        behavior = signals.behavior
        parts: list[str] = []

        # Channel subscription (strongest trust signal)
        if behavior.is_channel_subscriber:
            if behavior.channel_subscription_duration_days > 0:
                parts.append(
                    f"Channel subscriber: YES ({behavior.channel_subscription_duration_days} days)"
                )
            else:
                parts.append("Channel subscriber: YES")
        else:
            parts.append("Channel subscriber: NO")

        # Message history
        if behavior.previous_messages_approved > 0:
            parts.append(f"Previous approved messages: {behavior.previous_messages_approved}")
        if behavior.previous_messages_flagged > 0:
            parts.append(f"Previous flagged messages: {behavior.previous_messages_flagged}")
        if behavior.previous_messages_blocked > 0:
            parts.append(f"Previous blocked messages: {behavior.previous_messages_blocked}")

        # First message indicator
        if behavior.is_first_message:
            parts.append("First message in this group: YES")

        # Timing signals
        if behavior.time_to_first_message_seconds is not None:
            if behavior.time_to_first_message_seconds < 30:
                parts.append(
                    f"Time to first message: {behavior.time_to_first_message_seconds}s (VERY FAST)"
                )
            elif behavior.time_to_first_message_seconds < 300:
                parts.append(
                    f"Time to first message: {behavior.time_to_first_message_seconds}s (fast)"
                )

        # Reply context
        if behavior.is_reply:
            if behavior.is_reply_to_admin:
                parts.append("Reply: to admin (trust signal)")
            else:
                parts.append("Reply: yes")

        # Message rate
        if behavior.messages_in_last_hour >= 5:
            parts.append(f"Messages in last hour: {behavior.messages_in_last_hour} (high rate)")

        return "\n".join(parts)

    # =========================================================================
    # Caching
    # =========================================================================

    def _get_message_hash(self, context: MessageContext) -> str:
        """
        Generate hash for message caching.

        Hash is based on:
        - Message text (normalized)
        - User ID
        - Group type

        Args:
            context: Message context.

        Returns:
            SHA-256 hash string (first 32 chars).
        """
        text = (context.text or "").strip().lower()
        content = f"{context.user_id}:{context.group_type.value}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    async def _check_cache(
        self,
        message_hash: str,
        metrics: PipelineMetrics,
    ) -> RiskResult | None:
        """
        Check cache for existing decision.

        Args:
            message_hash: Message hash.
            metrics: Metrics collector.

        Returns:
            Cached RiskResult or None.
        """
        if self.cache_service is None:
            return None

        try:
            cached = await self.cache_service.get_cached_decision(message_hash)

            if cached is not None:
                metrics.cache_hit = True

                # Reconstruct RiskResult from cached data
                return RiskResult(
                    score=cached.get("score", 0),
                    verdict=Verdict(cached.get("verdict", "allow")),
                    profile_score=cached.get("profile_score", 0),
                    content_score=cached.get("content_score", 0),
                    behavior_score=cached.get("behavior_score", 0),
                    network_score=cached.get("network_score", 0),
                    contributing_factors=cached.get("contributing_factors", []),
                    mitigating_factors=cached.get("mitigating_factors", []),
                )

        except Exception as e:
            logger.warning(
                "cache_check_error",
                error=str(e),
            )

        return None

    async def _cache_decision(
        self,
        message_hash: str,
        result: RiskResult,
        metrics: PipelineMetrics,
    ) -> None:
        """
        Cache decision for future lookups.

        Args:
            message_hash: Message hash.
            result: RiskResult to cache.
            metrics: Metrics collector.
        """
        if self.cache_service is None:
            return

        try:
            cache_data = {
                "score": result.score,
                "verdict": result.verdict.value,
                "profile_score": result.profile_score,
                "content_score": result.content_score,
                "behavior_score": result.behavior_score,
                "network_score": result.network_score,
                "contributing_factors": result.contributing_factors,
                "mitigating_factors": result.mitigating_factors,
            }

            await self.cache_service.cache_decision(
                message_hash=message_hash,
                decision=cache_data,
                ttl_seconds=DECISION_CACHE_TTL,
            )

        except Exception as e:
            logger.warning(
                "cache_set_error",
                error=str(e),
            )

    # =========================================================================
    # Health and Status
    # =========================================================================

    def get_circuit_breaker_status(self) -> dict[str, dict[str, Any]]:
        """
        Get status of all circuit breakers.

        Returns:
            Dict mapping analyzer name to circuit breaker status.
        """
        return {name: cb.get_status() for name, cb in self._circuit_breakers.items()}

    def get_backpressure_status(self) -> dict[str, Any]:
        """
        Get current backpressure and queue depth status.

        Returns:
            Dict with pipeline backpressure metrics including:
            - circuit_breaker: Pipeline-level circuit breaker status
            - queue_depth: Current and peak active requests
            - degradation_level: Current degradation level
            - totals: Total requests processed and rejected
        """
        queue_utilization = (
            self._active_requests / self._max_concurrent_requests * 100
            if self._max_concurrent_requests > 0
            else 0
        )

        return {
            "circuit_breaker": self.circuit_breaker.get_status(),
            "queue_depth": {
                "active_requests": self._active_requests,
                "peak_active_requests": self._peak_active_requests,
                "max_concurrent_requests": self._max_concurrent_requests,
                "utilization_percent": round(queue_utilization, 1),
            },
            "degradation_level": self._degradation_level,
            "totals": {
                "total_requests_processed": self._total_requests_processed,
                "requests_rejected_by_backpressure": self._requests_rejected_by_backpressure,
            },
        }

    @property
    def degradation_level(self) -> str:
        """Current degradation level."""
        return self._degradation_level

    @property
    def active_requests(self) -> int:
        """Number of currently active requests."""
        return self._active_requests

    @property
    def is_under_pressure(self) -> bool:
        """
        Check if pipeline is under backpressure.

        Returns:
            True if circuit is open or queue utilization is above warning threshold.
        """
        if self.circuit_breaker.is_open():
            return True
        queue_utilization = (
            self._active_requests / self._max_concurrent_requests * 100
            if self._max_concurrent_requests > 0
            else 0
        )
        return queue_utilization >= self.DEFAULT_QUEUE_WARNING_THRESHOLD

    def set_degradation_level(self, level: str) -> None:
        """
        Manually set degradation level (for testing or manual override).

        Args:
            level: One of DegradationLevel constants.
        """
        if level in (
            DegradationLevel.FULL,
            DegradationLevel.REDUCED,
            DegradationLevel.MINIMAL,
            DegradationLevel.EMERGENCY,
        ):
            old_level = self._degradation_level
            self._degradation_level = level
            if old_level != level:
                logger.info(
                    "degradation_level_manually_set",
                    old_level=old_level,
                    new_level=level,
                )

    async def health_check(self) -> dict[str, bool]:
        """
        Check health of all pipeline components.

        Returns:
            Dict mapping component name to health status.
        """
        health: dict[str, bool] = {
            "risk_calculator": True,  # Always available (no external deps)
            "content_analyzer": True,  # Always available (no external deps)
            "profile_analyzer": True,  # Always available (no external deps)
            "behavior_analyzer": True,  # Always available (providers may be missing)
            "pipeline_circuit": not self.circuit_breaker.is_open(),
        }

        # Check optional services
        if self.spam_db is not None:
            try:
                stats = await self.spam_db.get_collection_stats()
                health["spam_db"] = "error" not in stats
            except Exception as e:
                logger.debug(
                    "health_check_spam_db_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                health["spam_db"] = False

        if self.llm_service is not None:
            try:
                health["llm"] = await self.llm_service.health_check()
            except Exception as e:
                logger.debug(
                    "health_check_llm_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                health["llm"] = False

        if self.cache_service is not None:
            try:
                health["cache"] = await self.cache_service.ping()
            except Exception as e:
                logger.debug(
                    "health_check_cache_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                health["cache"] = False

        return health


# =============================================================================
# Pipeline Factory
# =============================================================================


def create_pipeline(
    group_type: str,
    cache_service: CacheService | None = None,
    spam_db: SpamDB | SpamDBService | None = None,
    channel_subscription_service: ChannelSubscriptionService | None = None,
    llm_service: LLMService | None = None,
    metrics_collector: MetricsCollector | None = None,
    audit_trail: AuditTrail | None = None,
) -> MessagePipeline:
    """
    Factory function to create a MessagePipeline from middleware-injected services.

    This function creates all necessary analyzers and wires them together
    with the provided services. Use this instead of constructing MessagePipeline
    directly when working with aiogram handlers.

    Args:
        group_type: Group type string (general/tech/deals/crypto) for RiskCalculator.
        cache_service: Optional CacheService for caching decisions and user history.
        spam_db: Optional SpamDB service for vector similarity search.
        channel_subscription_service: Optional service for checking channel subscriptions.
        llm_service: Optional LLMService for gray zone (60-80 score) decisions.
        metrics_collector: Optional MetricsCollector for observability.
        audit_trail: Optional AuditTrail for decision logging.

    Returns:
        Configured MessagePipeline instance ready for processing.

    Example:
        >>> from saqshy.bot.pipeline import create_pipeline
        >>>
        >>> # In aiogram handler:
        >>> pipeline = create_pipeline(
        ...     group_type="deals",
        ...     cache_service=cache_service,
        ...     spam_db=spam_db,
        ...     llm_service=llm_service,
        ... )
        >>> result = await pipeline.process(context)
    """
    from saqshy.core.types import GroupType

    # Convert string to GroupType enum
    try:
        group_type_enum = GroupType(group_type.lower())
    except ValueError:
        logger.warning(
            "invalid_group_type_defaulting",
            provided=group_type,
            default="general",
        )
        group_type_enum = GroupType.GENERAL

    # Create analyzers
    content_analyzer = ContentAnalyzer()
    profile_analyzer = ProfileAnalyzer()
    behavior_analyzer = BehaviorAnalyzer(
        history_provider=cache_service,
        subscription_checker=channel_subscription_service,
    )

    # Create risk calculator with group type
    risk_calculator = RiskCalculator(group_type=group_type_enum)

    # Create and return the pipeline
    return MessagePipeline(
        risk_calculator=risk_calculator,
        content_analyzer=content_analyzer,
        profile_analyzer=profile_analyzer,
        behavior_analyzer=behavior_analyzer,
        spam_db=spam_db,
        llm_service=llm_service,
        cache_service=cache_service,
        channel_subscription=channel_subscription_service,
        metrics_collector=metrics_collector,
        audit_trail=audit_trail,
    )
