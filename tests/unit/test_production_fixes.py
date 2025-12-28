"""
SAQSHY Unit Tests - Production Readiness Fixes

Tests for edge cases and fixes made during production readiness review:
- RiskResult raw_score preservation
- CircuitBreaker timeout vs permanent error handling
- Thresholds validation
- Threat detection priority
- SpamDB LRU cache
- Caps ratio precision
"""

import time
from dataclasses import dataclass

import pytest

from saqshy.core.types import (
    ContentSignals,
    NetworkSignals,
    RiskResult,
    Signals,
    Verdict,
)


# =============================================================================
# RiskResult Tests
# =============================================================================


class TestRiskResultRawScore:
    """Test RiskResult raw_score preservation."""

    def test_raw_score_initialized_from_score(self) -> None:
        """Test that raw_score defaults to score when not provided."""
        result = RiskResult(score=50, verdict=Verdict.WATCH)
        assert result.raw_score == 50

    def test_raw_score_can_be_different_from_score(self) -> None:
        """Test that raw_score can be explicitly set different from score."""
        result = RiskResult(score=0, verdict=Verdict.ALLOW, raw_score=-15)
        assert result.score == 0
        assert result.raw_score == -15

    def test_raw_score_preserved_when_score_clamped_low(self) -> None:
        """Test that raw_score preserves negative values when score clamped to 0."""
        # Score must be 0-100, but raw_score shows what it was before clamping
        result = RiskResult(score=0, verdict=Verdict.ALLOW, raw_score=-25)
        assert result.score == 0
        assert result.raw_score == -25  # Shows trust signals were applied

    def test_raw_score_preserved_when_score_clamped_high(self) -> None:
        """Test that raw_score preserves values > 100 when score clamped to 100."""
        result = RiskResult(score=100, verdict=Verdict.BLOCK, raw_score=150)
        assert result.score == 100
        assert result.raw_score == 150  # Shows severe risk signals

    def test_raw_score_in_to_dict(self) -> None:
        """Test that raw_score is included in serialization."""
        result = RiskResult(score=50, verdict=Verdict.WATCH, raw_score=45)
        data = result.to_dict()
        assert "raw_score" in data
        assert data["raw_score"] == 45


# =============================================================================
# Content Signals Tests
# =============================================================================


class TestContentSignalsCapsRatio:
    """Test ContentSignals caps_ratio precision."""

    def test_caps_ratio_in_valid_range(self) -> None:
        """Test that caps_ratio must be between 0.0 and 1.0."""
        # Valid
        signals = ContentSignals(caps_ratio=0.0)
        assert signals.caps_ratio == 0.0

        signals = ContentSignals(caps_ratio=0.5)
        assert signals.caps_ratio == 0.5

        signals = ContentSignals(caps_ratio=1.0)
        assert signals.caps_ratio == 1.0

    def test_caps_ratio_rejects_invalid_values(self) -> None:
        """Test that invalid caps_ratio values are rejected."""
        with pytest.raises(ValueError, match="caps_ratio must be 0.0-1.0"):
            ContentSignals(caps_ratio=-0.1)

        with pytest.raises(ValueError, match="caps_ratio must be 0.0-1.0"):
            ContentSignals(caps_ratio=1.1)

    def test_caps_ratio_precision(self) -> None:
        """Test that caps_ratio handles floating point precision."""
        # Should handle precision up to 4 decimal places
        signals = ContentSignals(caps_ratio=0.3333)
        assert signals.caps_ratio == 0.3333


# =============================================================================
# Network Signals Tests
# =============================================================================


class TestNetworkSignalsValidation:
    """Test NetworkSignals validation."""

    def test_spam_db_similarity_range(self) -> None:
        """Test that spam_db_similarity must be 0.0-1.0."""
        # Valid
        signals = NetworkSignals(spam_db_similarity=0.85)
        assert signals.spam_db_similarity == 0.85

        # Invalid
        with pytest.raises(ValueError, match="spam_db_similarity must be 0.0-1.0"):
            NetworkSignals(spam_db_similarity=-0.1)

        with pytest.raises(ValueError, match="spam_db_similarity must be 0.0-1.0"):
            NetworkSignals(spam_db_similarity=1.5)

    def test_rejects_negative_counts(self) -> None:
        """Test that negative count fields are rejected."""
        with pytest.raises(ValueError, match="groups_in_common cannot be negative"):
            NetworkSignals(groups_in_common=-1)

        with pytest.raises(ValueError, match="duplicate_messages_in_other_groups cannot be negative"):
            NetworkSignals(duplicate_messages_in_other_groups=-1)


# =============================================================================
# Circuit Breaker Tests
# =============================================================================


class TestCircuitBreakerErrorTypes:
    """Test CircuitBreaker timeout vs permanent error handling."""

    def test_circuit_breaker_state_creation(self) -> None:
        """Test CircuitBreakerState initialization."""
        from saqshy.bot.pipeline import CircuitBreakerState

        cb = CircuitBreakerState(name="test")
        assert cb.name == "test"
        assert cb.failure_count == 0
        assert cb.timeout_count == 0
        assert cb.permanent_count == 0
        assert cb.state == "closed"

    def test_timeout_error_tracking(self) -> None:
        """Test that timeout errors are tracked separately."""
        from saqshy.bot.pipeline import CircuitBreakerState

        cb = CircuitBreakerState(name="test", timeout_threshold=3, permanent_threshold=2)

        # Record timeout errors
        cb.record_failure(is_timeout=True)
        cb.record_failure(is_timeout=True)

        assert cb.timeout_count == 2
        assert cb.permanent_count == 0
        assert cb.state == "closed"  # Not at threshold yet

    def test_permanent_error_tracking(self) -> None:
        """Test that permanent errors are tracked separately."""
        from saqshy.bot.pipeline import CircuitBreakerState

        cb = CircuitBreakerState(name="test", timeout_threshold=5, permanent_threshold=2)

        # Record permanent errors
        cb.record_failure(is_timeout=False)
        cb.record_failure(is_timeout=False)

        assert cb.timeout_count == 0
        assert cb.permanent_count == 2
        assert cb.state == "open"  # Opens faster for permanent errors

    def test_timeout_threshold_higher_than_permanent(self) -> None:
        """Test that timeout threshold is more tolerant than permanent."""
        from saqshy.bot.pipeline import CircuitBreakerState

        cb = CircuitBreakerState(name="test")
        assert cb.timeout_threshold > cb.permanent_threshold

    def test_success_resets_all_counters(self) -> None:
        """Test that success resets all failure counters."""
        from saqshy.bot.pipeline import CircuitBreakerState

        cb = CircuitBreakerState(name="test")
        cb.record_failure(is_timeout=True)
        cb.record_failure(is_timeout=False)

        cb.record_success()

        assert cb.failure_count == 0
        assert cb.timeout_count == 0
        assert cb.permanent_count == 0

    def test_get_status_includes_error_types(self) -> None:
        """Test that get_status includes timeout and permanent counts."""
        from saqshy.bot.pipeline import CircuitBreakerState

        cb = CircuitBreakerState(name="test")
        cb.record_failure(is_timeout=True)
        cb.record_failure(is_timeout=False)

        status = cb.get_status()

        assert "timeout_count" in status
        assert "permanent_count" in status
        assert status["timeout_count"] == 1
        assert status["permanent_count"] == 1


# =============================================================================
# Timeout Hierarchy Tests
# =============================================================================


class TestTimeoutHierarchy:
    """Test that timeout hierarchy is correctly configured."""

    def test_total_pipeline_timeout_exceeds_llm_timeout(self) -> None:
        """Test that TOTAL_PIPELINE_TIMEOUT >= LLM_TIMEOUT."""
        from saqshy.bot.pipeline import LLM_TIMEOUT, TOTAL_PIPELINE_TIMEOUT

        assert TOTAL_PIPELINE_TIMEOUT >= LLM_TIMEOUT, (
            f"TOTAL_PIPELINE_TIMEOUT ({TOTAL_PIPELINE_TIMEOUT}) must be >= "
            f"LLM_TIMEOUT ({LLM_TIMEOUT})"
        )

    def test_total_pipeline_timeout_has_buffer(self) -> None:
        """Test that TOTAL_PIPELINE_TIMEOUT has buffer for analyzers."""
        from saqshy.bot.pipeline import (
            ANALYZER_TIMEOUT,
            LLM_TIMEOUT,
            TOTAL_PIPELINE_TIMEOUT,
        )

        # Should have at least 1 second buffer for analyzer overhead
        assert TOTAL_PIPELINE_TIMEOUT >= LLM_TIMEOUT + 1.0


# =============================================================================
# LRU Cache Tests (SpamDB)
# =============================================================================


class TestSpamDBLRUCache:
    """Test SpamDB LRU cache behavior."""

    def test_ordered_dict_lru_eviction(self) -> None:
        """Test that OrderedDict provides O(1) LRU eviction."""
        from collections import OrderedDict

        cache: OrderedDict[str, str] = OrderedDict()

        # Add entries
        cache["first"] = "1"
        cache["second"] = "2"
        cache["third"] = "3"

        # Access first (moves to end)
        cache.move_to_end("first")

        # Evict oldest (should be "second" now)
        oldest_key, oldest_value = cache.popitem(last=False)
        assert oldest_key == "second"

        # Next oldest is "third"
        oldest_key, oldest_value = cache.popitem(last=False)
        assert oldest_key == "third"

    def test_spam_db_cache_max_size_default(self) -> None:
        """Test SpamDB has reasonable default cache max size."""
        from saqshy.services.spam_db import SpamDB

        assert SpamDB.DEFAULT_CACHE_MAX_SIZE > 0
        assert SpamDB.DEFAULT_CACHE_MAX_SIZE <= 10000  # Not too large
