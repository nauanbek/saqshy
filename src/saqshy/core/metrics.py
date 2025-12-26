"""
SAQSHY Metrics Collection

Production-grade metrics for monitoring spam detection performance.

Key metrics tracked:
- Verdict distribution by group_type (ALLOW/WATCH/LIMIT/REVIEW/BLOCK)
- FP/TP rates by group_type for accuracy monitoring
- Processing latency (p50, p95, p99)
- LLM usage rate and latency
- Spam wave detection
- Error rates by type

Metrics are stored in Redis for real-time access and can be exported
to Prometheus or other monitoring systems.

Example:
    >>> from saqshy.core.metrics import MetricsCollector
    >>> metrics = MetricsCollector(cache_service)
    >>> await metrics.record_verdict("deals", "BLOCK", 85, "crypto_scam", 150.5)
    >>> fp_rate = await metrics.get_fp_rate("deals", window_hours=24)
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from saqshy.core.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Metric Types and Constants
# =============================================================================


class MetricType(str, Enum):
    """Types of metrics collected."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


# Redis key prefixes for metrics
METRIC_PREFIX = "saqshy:metrics"
KEY_VERDICTS = f"{METRIC_PREFIX}:verdicts"
KEY_LATENCY = f"{METRIC_PREFIX}:latency"
KEY_LLM_CALLS = f"{METRIC_PREFIX}:llm_calls"
KEY_LLM_LATENCY = f"{METRIC_PREFIX}:llm_latency"
KEY_FP_OVERRIDES = f"{METRIC_PREFIX}:fp_overrides"
KEY_TP_CONFIRMED = f"{METRIC_PREFIX}:tp_confirmed"
KEY_ERRORS = f"{METRIC_PREFIX}:errors"
KEY_SPAM_WAVE = f"{METRIC_PREFIX}:spam_wave"
KEY_THREAT_TYPES = f"{METRIC_PREFIX}:threat_types"

# Time windows for metrics
HOURLY_WINDOW = 3600  # 1 hour
DAILY_WINDOW = 86400  # 24 hours
WEEKLY_WINDOW = 604800  # 7 days

# Spam wave detection config
SPAM_WAVE_CONFIG = {
    "window_minutes": 5,
    "block_threshold": 10,  # 10+ BLOCKs in 5 min = potential wave
    "review_threshold": 20,  # 20+ REVIEWs in 5 min
    "alert_cooldown_minutes": 30,
}

# Latency buckets for histogram (milliseconds)
LATENCY_BUCKETS = [10, 25, 50, 100, 200, 500, 1000, 2000, 5000, 10000]


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class VerdictMetrics:
    """Metrics for verdict distribution."""

    allow: int = 0
    watch: int = 0
    limit: int = 0
    review: int = 0
    block: int = 0
    total: int = 0

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary."""
        return {
            "allow": self.allow,
            "watch": self.watch,
            "limit": self.limit,
            "review": self.review,
            "block": self.block,
            "total": self.total,
        }


@dataclass
class LatencyMetrics:
    """Metrics for processing latency."""

    count: int = 0
    sum_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0
    buckets: dict[int, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def avg_ms(self) -> float:
        """Average latency in milliseconds."""
        return self.sum_ms / self.count if self.count > 0 else 0.0

    def record(self, latency_ms: float) -> None:
        """Record a latency measurement."""
        self.count += 1
        self.sum_ms += latency_ms
        self.min_ms = min(self.min_ms, latency_ms)
        self.max_ms = max(self.max_ms, latency_ms)

        # Update histogram buckets
        for bucket in LATENCY_BUCKETS:
            if latency_ms <= bucket:
                self.buckets[bucket] += 1
                break
        else:
            # Value exceeds all buckets
            self.buckets[max(LATENCY_BUCKETS) + 1] += 1

    def get_percentile(self, p: float) -> float:
        """
        Estimate percentile from histogram buckets.

        Args:
            p: Percentile (0.0 - 1.0), e.g., 0.95 for p95.

        Returns:
            Estimated latency at percentile.
        """
        if self.count == 0:
            return 0.0

        target = int(self.count * p)
        cumulative = 0

        for bucket in sorted(self.buckets.keys()):
            cumulative += self.buckets[bucket]
            if cumulative >= target:
                return float(bucket)

        return self.max_ms

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "count": self.count,
            "avg_ms": round(self.avg_ms, 2),
            "min_ms": round(self.min_ms, 2) if self.min_ms != float("inf") else 0.0,
            "max_ms": round(self.max_ms, 2),
            "p50_ms": round(self.get_percentile(0.5), 2),
            "p95_ms": round(self.get_percentile(0.95), 2),
            "p99_ms": round(self.get_percentile(0.99), 2),
        }


@dataclass
class AccuracyMetrics:
    """Metrics for FP/TP tracking."""

    blocks: int = 0
    fp_overrides: int = 0  # Admin approved after block
    tp_confirmed: int = 0  # Admin banned after review

    @property
    def fp_rate(self) -> float:
        """False positive rate."""
        if self.blocks == 0:
            return 0.0
        return self.fp_overrides / self.blocks

    @property
    def tp_rate(self) -> float:
        """True positive confirmation rate."""
        if self.blocks == 0:
            return 0.0
        return self.tp_confirmed / self.blocks

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "blocks": self.blocks,
            "fp_overrides": self.fp_overrides,
            "tp_confirmed": self.tp_confirmed,
            "fp_rate": round(self.fp_rate, 4),
            "tp_rate": round(self.tp_rate, 4),
        }


@dataclass
class GroupMetrics:
    """Complete metrics for a group type."""

    group_type: str
    verdicts: VerdictMetrics = field(default_factory=VerdictMetrics)
    latency: LatencyMetrics = field(default_factory=LatencyMetrics)
    accuracy: AccuracyMetrics = field(default_factory=AccuracyMetrics)
    llm_calls: int = 0
    llm_latency: LatencyMetrics = field(default_factory=LatencyMetrics)
    threat_types: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "group_type": self.group_type,
            "verdicts": self.verdicts.to_dict(),
            "latency": self.latency.to_dict(),
            "accuracy": self.accuracy.to_dict(),
            "llm_calls": self.llm_calls,
            "llm_latency": self.llm_latency.to_dict(),
            "threat_types": dict(self.threat_types),
            "errors": dict(self.errors),
        }


# =============================================================================
# In-Memory Metrics (for fast local aggregation)
# =============================================================================


class InMemoryMetrics:
    """
    In-memory metrics aggregation for fast local collection.

    Metrics are aggregated locally and periodically flushed to Redis.
    This reduces Redis operations while maintaining accurate counts.
    """

    def __init__(self) -> None:
        """Initialize in-memory metrics storage."""
        self._metrics: dict[str, GroupMetrics] = {}
        self._global_latency = LatencyMetrics()
        self._global_llm_latency = LatencyMetrics()
        self._last_flush = time.monotonic()
        self._flush_interval = 60.0  # Flush every 60 seconds

    def get_group_metrics(self, group_type: str) -> GroupMetrics:
        """Get or create metrics for a group type."""
        if group_type not in self._metrics:
            self._metrics[group_type] = GroupMetrics(group_type=group_type)
        return self._metrics[group_type]

    def record_verdict(
        self,
        group_type: str,
        verdict: str,
        risk_score: int,
        threat_type: str,
        latency_ms: float,
    ) -> None:
        """
        Record a moderation verdict.

        Args:
            group_type: Group type (general/tech/deals/crypto).
            verdict: Verdict string (ALLOW/WATCH/LIMIT/REVIEW/BLOCK).
            risk_score: Risk score (0-100).
            threat_type: Detected threat type.
            latency_ms: Processing latency in milliseconds.
        """
        metrics = self.get_group_metrics(group_type)

        # Update verdict counters
        verdict_lower = verdict.lower()
        if verdict_lower == "allow":
            metrics.verdicts.allow += 1
        elif verdict_lower == "watch":
            metrics.verdicts.watch += 1
        elif verdict_lower == "limit":
            metrics.verdicts.limit += 1
        elif verdict_lower == "review":
            metrics.verdicts.review += 1
        elif verdict_lower == "block":
            metrics.verdicts.block += 1
            metrics.accuracy.blocks += 1
        metrics.verdicts.total += 1

        # Update latency
        metrics.latency.record(latency_ms)
        self._global_latency.record(latency_ms)

        # Update threat types
        if threat_type and threat_type != "none":
            metrics.threat_types[threat_type] += 1

    def record_llm_call(
        self,
        group_type: str,
        latency_ms: float,
        success: bool = True,
    ) -> None:
        """
        Record an LLM call.

        Args:
            group_type: Group type.
            latency_ms: LLM response time in milliseconds.
            success: Whether the call succeeded.
        """
        metrics = self.get_group_metrics(group_type)
        metrics.llm_calls += 1
        metrics.llm_latency.record(latency_ms)
        self._global_llm_latency.record(latency_ms)

        if not success:
            metrics.errors["llm_error"] += 1

    def record_fp_override(self, group_type: str, threat_type: str) -> None:
        """
        Record a false positive override (admin approved blocked message).

        Args:
            group_type: Group type.
            threat_type: Original threat type that was overridden.
        """
        metrics = self.get_group_metrics(group_type)
        metrics.accuracy.fp_overrides += 1

    def record_tp_confirmed(self, group_type: str, threat_type: str) -> None:
        """
        Record a true positive confirmation (admin banned after review).

        Args:
            group_type: Group type.
            threat_type: Threat type that was confirmed.
        """
        metrics = self.get_group_metrics(group_type)
        metrics.accuracy.tp_confirmed += 1

    def record_error(self, group_type: str, error_type: str) -> None:
        """
        Record an error.

        Args:
            group_type: Group type.
            error_type: Type of error.
        """
        metrics = self.get_group_metrics(group_type)
        metrics.errors[error_type] += 1

    def get_all_metrics(self) -> dict[str, Any]:
        """Get all collected metrics."""
        return {
            "by_group_type": {gt: m.to_dict() for gt, m in self._metrics.items()},
            "global": {
                "latency": self._global_latency.to_dict(),
                "llm_latency": self._global_llm_latency.to_dict(),
            },
            "last_flush": self._last_flush,
        }

    def reset(self) -> dict[str, Any]:
        """
        Reset metrics and return final snapshot.

        Returns:
            Metrics snapshot before reset.
        """
        snapshot = self.get_all_metrics()
        self._metrics.clear()
        self._global_latency = LatencyMetrics()
        self._global_llm_latency = LatencyMetrics()
        self._last_flush = time.monotonic()
        return snapshot


# =============================================================================
# Redis-Backed Metrics Collector
# =============================================================================


class MetricsCollector:
    """
    Redis-backed metrics collector for production monitoring.

    Provides:
    - Real-time verdict distribution by group_type
    - FP/TP rate tracking for accuracy monitoring
    - Latency percentiles (p50, p95, p99)
    - LLM usage and latency tracking
    - Spam wave detection
    - Error rate tracking

    Example:
        >>> metrics = MetricsCollector(cache_service)
        >>> await metrics.record_verdict("deals", "BLOCK", 85, "crypto_scam", 150.5)
        >>> stats = await metrics.get_stats("deals", window_hours=24)
    """

    def __init__(self, cache_service: Any) -> None:
        """
        Initialize metrics collector.

        Args:
            cache_service: CacheService instance for Redis operations.
        """
        self.cache = cache_service
        self._local = InMemoryMetrics()
        self._logger = get_logger(__name__)

    # =========================================================================
    # Recording Methods
    # =========================================================================

    async def record_verdict(
        self,
        group_type: str,
        verdict: str,
        risk_score: int,
        threat_type: str,
        latency_ms: float,
        *,
        llm_called: bool = False,
        llm_latency_ms: float | None = None,
    ) -> None:
        """
        Record a moderation verdict.

        This is the primary method for recording spam detection outcomes.
        Updates both local cache and Redis for durability.

        Args:
            group_type: Group type (general/tech/deals/crypto).
            verdict: Verdict (ALLOW/WATCH/LIMIT/REVIEW/BLOCK).
            risk_score: Risk score (0-100).
            threat_type: Detected threat type.
            latency_ms: Total processing time in milliseconds.
            llm_called: Whether LLM was invoked.
            llm_latency_ms: LLM latency if called.
        """
        # Record locally for fast aggregation
        self._local.record_verdict(group_type, verdict, risk_score, threat_type, latency_ms)

        if llm_called and llm_latency_ms:
            self._local.record_llm_call(group_type, llm_latency_ms)

        # Record to Redis for persistence
        try:
            now = datetime.now(UTC)
            hour_key = now.strftime("%Y%m%d%H")

            # Increment verdict counter
            verdict_key = f"{KEY_VERDICTS}:{group_type}:{verdict.lower()}:{hour_key}"
            await self._increment(verdict_key, ttl=WEEKLY_WINDOW)

            # Record latency in sorted set for percentile calculation
            latency_key = f"{KEY_LATENCY}:{group_type}:{hour_key}"
            await self._add_latency(latency_key, latency_ms, ttl=DAILY_WINDOW)

            # Track threat type distribution
            if threat_type and threat_type != "none":
                threat_key = f"{KEY_THREAT_TYPES}:{group_type}:{threat_type}:{hour_key}"
                await self._increment(threat_key, ttl=WEEKLY_WINDOW)

            # Track LLM usage
            if llm_called:
                llm_key = f"{KEY_LLM_CALLS}:{group_type}:{hour_key}"
                await self._increment(llm_key, ttl=WEEKLY_WINDOW)

                if llm_latency_ms:
                    llm_latency_key = f"{KEY_LLM_LATENCY}:{group_type}:{hour_key}"
                    await self._add_latency(llm_latency_key, llm_latency_ms, ttl=DAILY_WINDOW)

            # Check for spam wave
            if verdict.lower() == "block":
                await self._check_spam_wave(group_type, now)

        except Exception as e:
            self._logger.warning(
                "metrics_recording_failed",
                error=str(e),
                group_type=group_type,
                verdict=verdict,
            )

    async def record_fp_override(
        self,
        group_type: str,
        threat_type: str,
        decision_id: str,
    ) -> None:
        """
        Record a false positive override.

        Called when an admin approves a previously blocked message.
        Critical for FP rate tracking.

        Args:
            group_type: Group type.
            threat_type: Original threat type.
            decision_id: Decision ID that was overridden.
        """
        self._local.record_fp_override(group_type, threat_type)

        try:
            now = datetime.now(UTC)
            hour_key = now.strftime("%Y%m%d%H")
            fp_key = f"{KEY_FP_OVERRIDES}:{group_type}:{threat_type}:{hour_key}"
            await self._increment(fp_key, ttl=WEEKLY_WINDOW)

            self._logger.info(
                "fp_override_recorded",
                group_type=group_type,
                threat_type=threat_type,
                decision_id=decision_id,
            )

        except Exception as e:
            self._logger.warning(
                "fp_override_recording_failed",
                error=str(e),
            )

    async def record_tp_confirmed(
        self,
        group_type: str,
        threat_type: str,
        decision_id: str,
    ) -> None:
        """
        Record a true positive confirmation.

        Called when an admin bans a user after REVIEW verdict.

        Args:
            group_type: Group type.
            threat_type: Confirmed threat type.
            decision_id: Decision ID that was confirmed.
        """
        self._local.record_tp_confirmed(group_type, threat_type)

        try:
            now = datetime.now(UTC)
            hour_key = now.strftime("%Y%m%d%H")
            tp_key = f"{KEY_TP_CONFIRMED}:{group_type}:{threat_type}:{hour_key}"
            await self._increment(tp_key, ttl=WEEKLY_WINDOW)

        except Exception as e:
            self._logger.warning(
                "tp_confirmed_recording_failed",
                error=str(e),
            )

    async def record_error(
        self,
        group_type: str,
        error_type: str,
        error_message: str | None = None,
    ) -> None:
        """
        Record an error.

        Args:
            group_type: Group type.
            error_type: Error type/category.
            error_message: Optional error message.
        """
        self._local.record_error(group_type, error_type)

        try:
            now = datetime.now(UTC)
            hour_key = now.strftime("%Y%m%d%H")
            error_key = f"{KEY_ERRORS}:{group_type}:{error_type}:{hour_key}"
            await self._increment(error_key, ttl=DAILY_WINDOW)

        except Exception as e:
            self._logger.debug(
                "error_recording_failed",
                error=str(e),
            )

    # =========================================================================
    # Query Methods
    # =========================================================================

    async def get_verdict_stats(
        self,
        group_type: str,
        window_hours: int = 24,
    ) -> VerdictMetrics:
        """
        Get verdict distribution for a group type.

        Args:
            group_type: Group type to query.
            window_hours: Time window in hours.

        Returns:
            VerdictMetrics with counts.
        """
        metrics = VerdictMetrics()

        try:
            now = datetime.now(UTC)
            verdicts = ["allow", "watch", "limit", "review", "block"]

            for verdict in verdicts:
                count = await self._sum_hourly_keys(
                    f"{KEY_VERDICTS}:{group_type}:{verdict}",
                    window_hours,
                    now,
                )
                setattr(metrics, verdict, count)
                metrics.total += count

        except Exception as e:
            self._logger.warning(
                "verdict_stats_query_failed",
                error=str(e),
                group_type=group_type,
            )

        return metrics

    async def get_fp_rate(
        self,
        group_type: str,
        window_hours: int = 24,
    ) -> float:
        """
        Get false positive rate for a group type.

        FP rate = overrides / blocks

        Args:
            group_type: Group type.
            window_hours: Time window in hours.

        Returns:
            FP rate (0.0 - 1.0).
        """
        try:
            now = datetime.now(UTC)

            # Get block count
            blocks = await self._sum_hourly_keys(
                f"{KEY_VERDICTS}:{group_type}:block",
                window_hours,
                now,
            )

            if blocks == 0:
                return 0.0

            # Get override count (sum all threat types)
            # This is simplified - in production you'd scan keys
            overrides = await self._sum_hourly_keys_pattern(
                f"{KEY_FP_OVERRIDES}:{group_type}:*",
                window_hours,
                now,
            )

            return overrides / blocks

        except Exception as e:
            self._logger.warning(
                "fp_rate_query_failed",
                error=str(e),
                group_type=group_type,
            )
            return 0.0

    async def get_latency_stats(
        self,
        group_type: str,
        window_hours: int = 1,
    ) -> dict[str, float]:
        """
        Get latency statistics for a group type.

        Args:
            group_type: Group type.
            window_hours: Time window in hours.

        Returns:
            Dictionary with p50, p95, p99, avg, min, max.
        """
        # Return local metrics for now (Redis latency tracking is expensive)
        metrics = self._local.get_group_metrics(group_type)
        return metrics.latency.to_dict()

    async def get_llm_stats(
        self,
        group_type: str,
        window_hours: int = 24,
    ) -> dict[str, Any]:
        """
        Get LLM usage statistics.

        Args:
            group_type: Group type.
            window_hours: Time window in hours.

        Returns:
            Dictionary with call count, latency stats, rate.
        """
        try:
            now = datetime.now(UTC)

            # Get LLM call count
            llm_calls = await self._sum_hourly_keys(
                f"{KEY_LLM_CALLS}:{group_type}",
                window_hours,
                now,
            )

            # Get total messages for rate calculation
            total = 0
            for verdict in ["allow", "watch", "limit", "review", "block"]:
                total += await self._sum_hourly_keys(
                    f"{KEY_VERDICTS}:{group_type}:{verdict}",
                    window_hours,
                    now,
                )

            # Get latency from local metrics
            metrics = self._local.get_group_metrics(group_type)

            return {
                "calls": llm_calls,
                "rate": llm_calls / total if total > 0 else 0.0,
                "latency": metrics.llm_latency.to_dict(),
            }

        except Exception as e:
            self._logger.warning(
                "llm_stats_query_failed",
                error=str(e),
            )
            return {"calls": 0, "rate": 0.0, "latency": {}}

    async def get_threat_type_distribution(
        self,
        group_type: str,
        window_hours: int = 24,
    ) -> dict[str, int]:
        """
        Get distribution of threat types.

        Args:
            group_type: Group type.
            window_hours: Time window in hours.

        Returns:
            Dictionary mapping threat_type to count.
        """
        # Return local metrics for simplicity
        metrics = self._local.get_group_metrics(group_type)
        return dict(metrics.threat_types)

    async def get_all_stats(self, window_hours: int = 24) -> dict[str, Any]:
        """
        Get comprehensive statistics for all group types.

        Args:
            window_hours: Time window in hours.

        Returns:
            Dictionary with all metrics by group type.
        """
        stats = {
            "window_hours": window_hours,
            "collected_at": datetime.now(UTC).isoformat(),
            "by_group_type": {},
            "global": self._local.get_all_metrics().get("global", {}),
        }

        for group_type in ["general", "tech", "deals", "crypto"]:
            stats["by_group_type"][group_type] = {
                "verdicts": (await self.get_verdict_stats(group_type, window_hours)).to_dict(),
                "fp_rate": await self.get_fp_rate(group_type, window_hours),
                "latency": await self.get_latency_stats(group_type, window_hours),
                "llm": await self.get_llm_stats(group_type, window_hours),
                "threat_types": await self.get_threat_type_distribution(group_type, window_hours),
            }

        return stats

    # =========================================================================
    # Spam Wave Detection
    # =========================================================================

    async def _check_spam_wave(
        self,
        group_type: str,
        timestamp: datetime,
    ) -> bool:
        """
        Check if current activity indicates a spam wave.

        Args:
            group_type: Group type.
            timestamp: Current timestamp.

        Returns:
            True if spam wave detected.
        """
        try:
            window_seconds = SPAM_WAVE_CONFIG["window_minutes"] * 60
            threshold = SPAM_WAVE_CONFIG["block_threshold"]

            # Use sliding window in Redis
            wave_key = f"{KEY_SPAM_WAVE}:{group_type}"
            ts = timestamp.timestamp()

            if self.cache._client:
                # Add current timestamp
                await self.cache._client.zadd(wave_key, {str(ts): ts})

                # Remove old entries
                cutoff = ts - window_seconds
                await self.cache._client.zremrangebyscore(wave_key, "-inf", cutoff)

                # Count entries
                count = await self.cache._client.zcard(wave_key)

                # Set TTL
                await self.cache._client.expire(wave_key, window_seconds * 2)

                if count >= threshold:
                    self._logger.warning(
                        "spam_wave_detected",
                        group_type=group_type,
                        block_count_5m=count,
                        threshold=threshold,
                    )
                    return True

        except Exception as e:
            self._logger.debug(
                "spam_wave_check_failed",
                error=str(e),
            )

        return False

    async def is_spam_wave_active(self, group_type: str) -> bool:
        """
        Check if a spam wave is currently active.

        Args:
            group_type: Group type.

        Returns:
            True if spam wave is active.
        """
        try:
            wave_key = f"{KEY_SPAM_WAVE}:{group_type}"
            window_seconds = SPAM_WAVE_CONFIG["window_minutes"] * 60
            threshold = SPAM_WAVE_CONFIG["block_threshold"]

            if self.cache._client:
                now = time.time()
                count = await self.cache._client.zcount(
                    wave_key,
                    now - window_seconds,
                    "+inf",
                )
                return count >= threshold

        except Exception as e:
            logger.debug(
                "spam_wave_check_failed",
                wave_key=wave_key,
                error=str(e),
                error_type=type(e).__name__,
            )

        return False

    # =========================================================================
    # Redis Helper Methods
    # =========================================================================

    async def _increment(self, key: str, ttl: int = DAILY_WINDOW) -> int:
        """Increment a counter in Redis."""
        if not self.cache._client:
            return 0

        try:
            result = await self.cache._client.incr(key)
            await self.cache._client.expire(key, ttl)
            return int(result)
        except Exception as e:
            logger.debug(
                "redis_increment_failed",
                key=key,
                error=str(e),
                error_type=type(e).__name__,
            )
            return 0

    async def _add_latency(
        self,
        key: str,
        latency_ms: float,
        ttl: int = DAILY_WINDOW,
    ) -> None:
        """
        Add a latency value to a sorted set.

        Uses unique member (timestamp + UUID suffix) with latency as score.
        This allows ZRANGEBYSCORE for percentile calculation without collisions.
        """
        if not self.cache._client:
            return

        try:
            ts = time.time()
            # Use unique member with latency as score for percentile queries
            # Format: "{timestamp}:{uuid_suffix}" -> score is latency_ms
            member = f"{ts}:{uuid.uuid4().hex[:8]}"
            await self.cache._client.zadd(key, {member: latency_ms})
            await self.cache._client.expire(key, ttl)
        except Exception as e:
            logger.debug(
                "redis_add_latency_failed",
                key=key,
                latency_ms=latency_ms,
                error=str(e),
                error_type=type(e).__name__,
            )

    async def _get_latency_percentile(
        self,
        key: str,
        percentile: float,
    ) -> float:
        """
        Get latency at given percentile from ZSET.

        Since latency values are stored as scores, we use ZRANGE with BYSCORE
        to efficiently calculate percentiles.

        Args:
            key: Redis key for the latency ZSET
            percentile: Percentile to calculate (0.0 - 1.0, e.g., 0.95 for p95)

        Returns:
            Latency value at the given percentile, or 0.0 if unavailable
        """
        if not self.cache._client:
            return 0.0

        try:
            # Get total count
            count = await self.cache._client.zcard(key)
            if count == 0:
                return 0.0

            # Calculate rank for percentile
            rank = int(count * percentile)
            rank = min(rank, count - 1)  # Ensure within bounds

            # Get member at rank with score (score is the latency)
            result = await self.cache._client.zrange(
                key,
                rank,
                rank,
                withscores=True,
            )

            if result:
                # Result is list of (member, score) tuples, score is latency
                return float(result[0][1])

            return 0.0

        except Exception as e:
            logger.debug(
                "latency_percentile_query_failed",
                key=key,
                percentile=percentile,
                error=str(e),
                error_type=type(e).__name__,
            )
            return 0.0

    async def _sum_hourly_keys(
        self,
        prefix: str,
        hours: int,
        now: datetime,
    ) -> int:
        """Sum values across hourly keys."""
        if not self.cache._client:
            return 0

        total = 0
        for i in range(hours):
            hour = now - timedelta(hours=i)
            hour_key = hour.strftime("%Y%m%d%H")
            key = f"{prefix}:{hour_key}"
            try:
                value = await self.cache._client.get(key)
                if value:
                    total += int(value)
            except ValueError as e:
                logger.debug(
                    "redis_hourly_key_parse_failed",
                    key=key,
                    error=str(e),
                )
            except Exception as e:
                logger.debug(
                    "redis_hourly_key_get_failed",
                    key=key,
                    error=str(e),
                    error_type=type(e).__name__,
                )

        return total

    async def _sum_hourly_keys_pattern(
        self,
        pattern: str,
        hours: int,
        now: datetime,
    ) -> int:
        """
        Sum values across hourly keys matching a pattern.

        Uses Redis SCAN to iterate keys matching the pattern for each hour
        in the time window. Pattern should contain a wildcard (*) for the
        variable component (e.g., threat_type).

        Args:
            pattern: Redis key pattern with wildcard (e.g., "prefix:group:*")
            hours: Number of hours to look back
            now: Current timestamp

        Returns:
            Sum of all matching key values
        """
        if not self.cache._client:
            return 0

        total = 0

        for i in range(hours):
            hour = now - timedelta(hours=i)
            hour_key = hour.strftime("%Y%m%d%H")

            # Build the full pattern for this hour
            # Pattern format: "prefix:group_type:*" -> "prefix:group_type:*:YYYYMMDDHH"
            hour_pattern = f"{pattern}:{hour_key}"

            try:
                # Use SCAN to find keys matching the pattern
                cursor = 0
                while True:
                    cursor, keys = await self.cache._client.scan(
                        cursor=cursor,
                        match=hour_pattern,
                        count=100,
                    )

                    for key in keys:
                        try:
                            # Decode key if bytes
                            if isinstance(key, bytes):
                                key = key.decode("utf-8")
                            value = await self.cache._client.get(key)
                            if value:
                                if isinstance(value, bytes):
                                    value = value.decode("utf-8")
                                total += int(value)
                        except (ValueError, TypeError) as e:
                            logger.debug(
                                "redis_pattern_value_parse_failed",
                                key=key,
                                error=str(e),
                            )

                    # cursor is 0 when scan is complete
                    if cursor == 0:
                        break

            except Exception as e:
                logger.debug(
                    "redis_scan_pattern_failed",
                    pattern=hour_pattern,
                    error=str(e),
                    error_type=type(e).__name__,
                )

        return total


# =============================================================================
# Alert Rules
# =============================================================================


@dataclass
class AlertRule:
    """Configuration for an alert rule."""

    name: str
    condition: str
    threshold: float
    severity: str  # info, warning, critical
    group_types: list[str] | None = None  # None means all
    cooldown_minutes: int = 30


ALERT_RULES = [
    AlertRule(
        name="high_fp_rate",
        condition="fp_rate",
        threshold=0.10,  # >10% FP rate
        severity="warning",
        group_types=["deals"],  # Especially important for deals
    ),
    AlertRule(
        name="very_high_fp_rate",
        condition="fp_rate",
        threshold=0.20,  # >20% FP rate
        severity="critical",
    ),
    AlertRule(
        name="high_latency_p95",
        condition="latency_p95",
        threshold=2000,  # >2s p95
        severity="warning",
    ),
    AlertRule(
        name="very_high_latency_p95",
        condition="latency_p95",
        threshold=5000,  # >5s p95
        severity="critical",
    ),
    AlertRule(
        name="high_llm_error_rate",
        condition="llm_error_rate",
        threshold=0.05,  # >5% LLM errors
        severity="critical",
    ),
    AlertRule(
        name="spam_wave",
        condition="spam_wave",
        threshold=1,  # Any spam wave
        severity="info",
    ),
]


async def check_alerts(
    metrics: MetricsCollector,
    group_type: str,
) -> list[dict[str, Any]]:
    """
    Check alert rules against current metrics.

    Args:
        metrics: MetricsCollector instance.
        group_type: Group type to check.

    Returns:
        List of triggered alerts.
    """
    triggered = []

    fp_rate = await metrics.get_fp_rate(group_type)
    latency_stats = await metrics.get_latency_stats(group_type)
    llm_stats = await metrics.get_llm_stats(group_type)
    is_wave = await metrics.is_spam_wave_active(group_type)

    for rule in ALERT_RULES:
        # Check if rule applies to this group type
        if rule.group_types and group_type not in rule.group_types:
            continue

        # Evaluate condition
        value = 0.0
        if rule.condition == "fp_rate":
            value = fp_rate
        elif rule.condition == "latency_p95":
            value = latency_stats.get("p95_ms", 0)
        elif rule.condition == "llm_error_rate":
            # Calculate from local metrics
            local = metrics._local.get_group_metrics(group_type)
            if local.llm_calls > 0:
                value = local.errors.get("llm_error", 0) / local.llm_calls
        elif rule.condition == "spam_wave":
            value = 1.0 if is_wave else 0.0

        if value >= rule.threshold:
            triggered.append(
                {
                    "rule": rule.name,
                    "severity": rule.severity,
                    "condition": rule.condition,
                    "threshold": rule.threshold,
                    "current_value": value,
                    "group_type": group_type,
                }
            )

    return triggered
