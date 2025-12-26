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
TOTAL_PIPELINE_TIMEOUT = 5.0  # 5 second hard limit

# Cache configuration
DECISION_CACHE_TTL = 300  # 5 minutes


# =============================================================================
# Circuit Breaker
# =============================================================================


@dataclass
class CircuitBreakerState:
    """
    Track circuit breaker state for an analyzer.

    Implements the circuit breaker pattern to prevent repeated
    calls to failing services.
    """

    name: str
    failure_count: int = 0
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    last_failure_time: float = 0.0
    state: str = "closed"  # closed, open, half_open

    def record_failure(self) -> None:
        """Record a failure and potentially open the circuit."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.failure_count >= self.failure_threshold:
            if self.state != "open":
                logger.warning(
                    "circuit_breaker_opened",
                    analyzer=self.name,
                    failures=self.failure_count,
                )
            self.state = "open"

    def record_success(self) -> None:
        """Record a success and reset the circuit."""
        if self.state == "half_open":
            logger.info(
                "circuit_breaker_closed",
                analyzer=self.name,
            )
        self.failure_count = 0
        self.state = "closed"

    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        if self.state == "closed":
            return False

        if self.state == "open":
            # Check if recovery timeout has passed
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = "half_open"
                logger.info(
                    "circuit_breaker_half_open",
                    analyzer=self.name,
                )
                return False
            return True

        # half_open: allow one request
        return False


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

        logger.info(
            "pipeline_initialized",
            has_spam_db=spam_db is not None,
            has_llm=llm_service is not None,
            has_cache=cache_service is not None,
            has_channel_sub=channel_subscription is not None,
            has_metrics=metrics_collector is not None,
            has_audit=audit_trail is not None,
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
        1. Checks decision cache
        2. Runs all analyzers in parallel
        3. Calculates risk score
        4. Optionally calls LLM for gray zone
        5. Returns final verdict

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
            total_ms = (metrics.end_time - metrics.start_time) * 1000

            log.info(
                "pipeline_completed",
                correlation_id=correlation_id,
                verdict=result.verdict.value,
                score=result.score,
                **metrics.to_dict(),
            )

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
                **metrics.to_dict(),
            )

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
                **metrics.to_dict(),
            )

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

        # Check if LLM review is needed (gray zone)
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
                circuit_breaker.record_failure()

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
                circuit_breaker.record_failure()

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
                llm_circuit.record_failure()
            return result

        except Exception as e:
            metrics.llm_ms = (time.monotonic() - llm_start) * 1000
            log.exception(
                "llm_call_error",
                error=str(e),
            )
            if llm_circuit:
                llm_circuit.record_failure()
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
        return {
            name: {
                "state": cb.state,
                "failure_count": cb.failure_count,
                "failure_threshold": cb.failure_threshold,
            }
            for name, cb in self._circuit_breakers.items()
        }

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
