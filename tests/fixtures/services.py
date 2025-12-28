"""
SAQSHY Test Fixtures - Service Mocks

Provides mock fixtures for external services:
- LLM Service (Claude API)
- SpamDB Service (Qdrant embeddings)
- Cache Service (Redis)
- Embeddings Service (Cohere)
- Channel Subscription Service

These mocks enable deterministic unit testing without external dependencies.
All mocks return sensible defaults that can be overridden per-test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from saqshy.core.types import ThreatType, Verdict

if TYPE_CHECKING:
    from saqshy.services.cache import CacheService
    from saqshy.services.llm import LLMResult, LLMService
    from saqshy.services.spam_db import SpamDBService


# =============================================================================
# LLM Service Mocks
# =============================================================================


@dataclass
class MockLLMResult:
    """
    Mock LLM analysis result.

    Mirrors the structure of saqshy.services.llm.LLMResult
    for use in tests without importing the actual class.
    """

    verdict: Verdict
    confidence: float
    reason: str
    raw_response: str | None = None
    error: str | None = None
    injection_detected: bool = False
    injection_patterns: list[str] = field(default_factory=list)


def create_llm_result(
    verdict: Verdict = Verdict.ALLOW,
    confidence: float = 0.9,
    reason: str = "Legitimate message",
    error: str | None = None,
    injection_detected: bool = False,
) -> MockLLMResult:
    """
    Create a customizable LLM result.

    Args:
        verdict: The spam verdict (ALLOW, WATCH, LIMIT, REVIEW, BLOCK)
        confidence: Confidence level 0.0-1.0
        reason: Explanation for the verdict
        error: Error message if analysis failed
        injection_detected: Whether prompt injection was detected

    Returns:
        MockLLMResult configured as specified
    """
    return MockLLMResult(
        verdict=verdict,
        confidence=confidence,
        reason=reason,
        error=error,
        injection_detected=injection_detected,
    )


@pytest.fixture
def mock_llm_result_allow() -> MockLLMResult:
    """LLM result that allows the message."""
    return create_llm_result(
        verdict=Verdict.ALLOW,
        confidence=0.95,
        reason="Message appears to be legitimate conversation",
    )


@pytest.fixture
def mock_llm_result_block() -> MockLLMResult:
    """LLM result that blocks the message as spam."""
    return create_llm_result(
        verdict=Verdict.BLOCK,
        confidence=0.92,
        reason="Message contains crypto scam patterns and urgency manipulation",
    )


@pytest.fixture
def mock_llm_result_watch() -> MockLLMResult:
    """LLM result that flags for monitoring."""
    return create_llm_result(
        verdict=Verdict.WATCH,
        confidence=0.65,
        reason="Message has some promotional elements but may be legitimate",
    )


@pytest.fixture
def mock_llm_result_error() -> MockLLMResult:
    """LLM result representing an error with fallback."""
    return create_llm_result(
        verdict=Verdict.ALLOW,
        confidence=0.0,
        reason="LLM analysis failed, defaulting to allow",
        error="API timeout after 10 seconds",
    )


@pytest.fixture
def mock_llm_service(mock_llm_result_allow: MockLLMResult) -> MagicMock:
    """
    Create a mock LLM service with controlled responses.

    Default behavior: Returns ALLOW verdict for all messages.
    Override analyze_message.return_value for specific test cases.

    Usage:
        async def test_gray_zone(mock_llm_service):
            # Default: allows messages
            result = await mock_llm_service.analyze_message(context, signals, 50)
            assert result.verdict == Verdict.ALLOW

            # Override for specific test
            mock_llm_service.analyze_message.return_value = MockLLMResult(
                verdict=Verdict.BLOCK,
                confidence=0.95,
                reason="Spam detected",
            )
    """
    service = MagicMock()

    # Main analysis method
    service.analyze_message = AsyncMock(return_value=mock_llm_result_allow)

    # Health check
    service.is_healthy = AsyncMock(return_value=True)

    # Rate limit awareness
    service.is_near_rate_limit = MagicMock(return_value=False)

    # Circuit breaker state
    service.circuit_is_open = MagicMock(return_value=False)

    return service


@pytest.fixture
def mock_llm_service_unavailable() -> MagicMock:
    """
    Mock LLM service that simulates unavailability.

    Returns error results, useful for testing fallback behavior.
    """
    service = MagicMock()

    error_result = create_llm_result(
        verdict=Verdict.ALLOW,
        confidence=0.0,
        reason="LLM service unavailable",
        error="Circuit breaker open",
    )

    service.analyze_message = AsyncMock(return_value=error_result)
    service.is_healthy = AsyncMock(return_value=False)
    service.is_near_rate_limit = MagicMock(return_value=True)
    service.circuit_is_open = MagicMock(return_value=True)

    return service


# =============================================================================
# SpamDB Service Mocks
# =============================================================================


@dataclass
class SpamDBMatch:
    """Represents a spam database match result."""

    text: str
    similarity: float
    pattern_id: str
    category: str


@pytest.fixture
def mock_spam_db_service() -> MagicMock:
    """
    Create a mock SpamDB service with controlled responses.

    Default behavior: No spam matches found.
    Override search.return_value for specific test cases.

    Usage:
        async def test_spam_detection(mock_spam_db_service):
            # Default: no matches
            matches = await mock_spam_db_service.search("hello")
            assert matches == []

            # Override for spam match
            mock_spam_db_service.search.return_value = [
                SpamDBMatch(text="crypto scam", similarity=0.95, ...)
            ]
    """
    service = MagicMock()

    # Search returns no matches by default
    service.search = AsyncMock(return_value=[])

    # Get max similarity returns (0.0, None) by default
    service.get_max_similarity = AsyncMock(return_value=(0.0, None))

    # Health check
    service.is_healthy = AsyncMock(return_value=True)

    # Embedding generation (for when we need to add patterns)
    service.generate_embedding = AsyncMock(return_value=[0.0] * 1024)

    # Add pattern (for seeding tests)
    service.add_pattern = AsyncMock(return_value="pattern_123")

    return service


@pytest.fixture
def mock_spam_db_with_matches() -> MagicMock:
    """
    Mock SpamDB service that returns spam matches.

    Useful for testing high-risk scenarios.
    """
    service = MagicMock()

    matches = [
        SpamDBMatch(
            text="GUARANTEED PROFITS! Double your investment!",
            similarity=0.92,
            pattern_id="spam_001",
            category="crypto_scam",
        ),
    ]

    service.search = AsyncMock(return_value=matches)
    service.get_max_similarity = AsyncMock(
        return_value=(0.92, "Known crypto scam pattern")
    )
    service.is_healthy = AsyncMock(return_value=True)

    return service


# =============================================================================
# Cache Service Mocks
# =============================================================================


@pytest.fixture
def mock_cache_service() -> MagicMock:
    """
    Create a mock cache service with in-memory storage.

    Default behavior: Cache miss (returns None for gets).
    Uses an internal dict to simulate actual caching behavior.

    Usage:
        async def test_caching(mock_cache_service):
            # Default: cache miss
            result = await mock_cache_service.get("key")
            assert result is None

            # Set and get
            await mock_cache_service.set("key", "value")
            result = await mock_cache_service.get("key")
            assert result == "value"
    """
    service = MagicMock()
    _cache: dict[str, Any] = {}

    async def mock_get(key: str) -> Any | None:
        return _cache.get(key)

    async def mock_set(key: str, value: Any, ttl: int = 300) -> bool:
        _cache[key] = value
        return True

    async def mock_delete(key: str) -> bool:
        if key in _cache:
            del _cache[key]
            return True
        return False

    async def mock_get_json(key: str) -> dict | None:
        return _cache.get(key)

    async def mock_set_json(key: str, value: dict, ttl: int = 300) -> bool:
        _cache[key] = value
        return True

    service.get = AsyncMock(side_effect=mock_get)
    service.set = AsyncMock(side_effect=mock_set)
    service.delete = AsyncMock(side_effect=mock_delete)
    service.get_json = AsyncMock(side_effect=mock_get_json)
    service.set_json = AsyncMock(side_effect=mock_set_json)

    # Admin status cache
    service.get_admin_status = AsyncMock(return_value=None)
    service.set_admin_status = AsyncMock(return_value=True)

    # Channel subscription cache
    service.get_channel_subscription = AsyncMock(return_value=None)
    service.set_channel_subscription = AsyncMock(return_value=True)

    # Message history (for BehaviorAnalyzer)
    service.get_message_count_last_hour = AsyncMock(return_value=0)
    service.get_message_count_last_24h = AsyncMock(return_value=0)
    service.get_first_message_time = AsyncMock(return_value=None)
    service.get_join_time = AsyncMock(return_value=None)
    service.record_message = AsyncMock(return_value=True)

    # User stats
    service.get_user_stats = AsyncMock(
        return_value={"approved": 0, "flagged": 0, "blocked": 0}
    )
    service.increment_user_stat = AsyncMock(return_value=True)

    # Health check
    service.is_healthy = AsyncMock(return_value=True)

    # Expose internal cache for test assertions
    service._test_cache = _cache

    return service


@pytest.fixture
def mock_cache_service_with_history() -> MagicMock:
    """
    Mock cache service with pre-populated message history.

    Simulates a user with established activity.
    """
    service = MagicMock()

    service.get = AsyncMock(return_value=None)
    service.set = AsyncMock(return_value=True)
    service.get_json = AsyncMock(return_value=None)
    service.set_json = AsyncMock(return_value=True)

    # Pre-populated history
    service.get_admin_status = AsyncMock(return_value=False)
    service.get_channel_subscription = AsyncMock(return_value=True)

    # Active user with message history
    service.get_message_count_last_hour = AsyncMock(return_value=5)
    service.get_message_count_last_24h = AsyncMock(return_value=20)
    service.get_first_message_time = AsyncMock(return_value="2024-01-01T12:00:00Z")
    service.get_join_time = AsyncMock(return_value="2023-06-15T10:00:00Z")

    # Trusted user stats
    service.get_user_stats = AsyncMock(
        return_value={"approved": 50, "flagged": 0, "blocked": 0}
    )

    service.is_healthy = AsyncMock(return_value=True)

    return service


# =============================================================================
# Embeddings Service Mocks
# =============================================================================


@pytest.fixture
def mock_embeddings_service() -> MagicMock:
    """
    Create a mock embeddings service.

    Default behavior: Returns zero vectors of correct dimension.
    Override for specific similarity testing scenarios.

    Usage:
        async def test_embeddings(mock_embeddings_service):
            embedding = await mock_embeddings_service.embed_text("hello")
            assert len(embedding) == 1024
    """
    service = MagicMock()

    # Single text embedding
    service.embed_text = AsyncMock(return_value=[0.0] * 1024)

    # Batch text embedding
    service.embed_texts = AsyncMock(
        side_effect=lambda texts: [[0.0] * 1024 for _ in texts]
    )

    # Health check
    service.is_healthy = AsyncMock(return_value=True)

    return service


@pytest.fixture
def mock_embeddings_service_realistic() -> MagicMock:
    """
    Mock embeddings service with more realistic behavior.

    Returns different embeddings for different texts (simulated).
    """
    import hashlib

    service = MagicMock()

    def _generate_embedding(text: str) -> list[float]:
        """Generate deterministic pseudo-embedding from text hash."""
        hash_bytes = hashlib.sha256(text.encode()).digest()
        # Use first 1024 bytes of repeated hash as embedding values
        values = []
        for i in range(1024):
            byte_val = hash_bytes[i % len(hash_bytes)]
            # Normalize to [-1, 1] range
            values.append((byte_val / 127.5) - 1.0)
        return values

    service.embed_text = AsyncMock(side_effect=_generate_embedding)
    service.embed_texts = AsyncMock(
        side_effect=lambda texts: [_generate_embedding(t) for t in texts]
    )
    service.is_healthy = AsyncMock(return_value=True)

    return service


# =============================================================================
# Channel Subscription Service Mocks
# =============================================================================


@pytest.fixture
def mock_channel_subscription_service() -> MagicMock:
    """
    Create a mock channel subscription service.

    Default behavior: User is not subscribed to any channel.

    Usage:
        async def test_subscription(mock_channel_subscription_service):
            is_sub = await mock_channel_subscription_service.check_subscription(
                channel_id=-1001234567890,
                user_id=123456789,
            )
            assert is_sub is False

            # Override for subscribed user
            mock_channel_subscription_service.check_subscription.return_value = True
    """
    service = MagicMock()

    # Check if user is subscribed
    service.check_subscription = AsyncMock(return_value=False)

    # Get subscription duration (days)
    service.get_subscription_duration = AsyncMock(return_value=0)

    # Check if user is member of group
    service.check_group_membership = AsyncMock(return_value=True)

    # Get group membership duration (days)
    service.get_membership_duration = AsyncMock(return_value=0)

    # Health check
    service.is_healthy = AsyncMock(return_value=True)

    return service


@pytest.fixture
def mock_channel_subscription_service_subscribed() -> MagicMock:
    """
    Mock channel subscription service for subscribed user.

    Simulates a long-term channel subscriber.
    """
    service = MagicMock()

    service.check_subscription = AsyncMock(return_value=True)
    service.get_subscription_duration = AsyncMock(return_value=45)  # 45 days
    service.check_group_membership = AsyncMock(return_value=True)
    service.get_membership_duration = AsyncMock(return_value=90)  # 90 days
    service.is_healthy = AsyncMock(return_value=True)

    return service


# =============================================================================
# Combined Service Mocks
# =============================================================================


@pytest.fixture
def mock_all_services(
    mock_llm_service: MagicMock,
    mock_spam_db_service: MagicMock,
    mock_cache_service: MagicMock,
    mock_embeddings_service: MagicMock,
    mock_channel_subscription_service: MagicMock,
) -> dict[str, MagicMock]:
    """
    Get all service mocks as a dictionary.

    Useful for tests that need to inject multiple services.

    Usage:
        async def test_pipeline(mock_all_services):
            llm = mock_all_services["llm"]
            spam_db = mock_all_services["spam_db"]
            cache = mock_all_services["cache"]
            ...
    """
    return {
        "llm": mock_llm_service,
        "spam_db": mock_spam_db_service,
        "cache": mock_cache_service,
        "embeddings": mock_embeddings_service,
        "channel_subscription": mock_channel_subscription_service,
    }


# =============================================================================
# Context Manager for Service Patching
# =============================================================================


class ServicePatcher:
    """
    Context manager for patching multiple services at once.

    Usage:
        with ServicePatcher() as patcher:
            patcher.patch_llm(mock_llm_service)
            patcher.patch_cache(mock_cache_service)
            # Run tests with patched services
    """

    def __init__(self) -> None:
        self._patches: list = []
        self._mocks: dict[str, MagicMock] = {}

    def __enter__(self) -> "ServicePatcher":
        return self

    def __exit__(self, *args: Any) -> None:
        for p in self._patches:
            p.stop()
        self._patches.clear()

    def patch_llm(self, mock: MagicMock) -> None:
        """Patch the LLM service."""
        p = patch("saqshy.services.llm.LLMService", return_value=mock)
        self._patches.append(p)
        self._mocks["llm"] = p.start()

    def patch_spam_db(self, mock: MagicMock) -> None:
        """Patch the SpamDB service."""
        p = patch("saqshy.services.spam_db.SpamDBService", return_value=mock)
        self._patches.append(p)
        self._mocks["spam_db"] = p.start()

    def patch_cache(self, mock: MagicMock) -> None:
        """Patch the Cache service."""
        p = patch("saqshy.services.cache.CacheService", return_value=mock)
        self._patches.append(p)
        self._mocks["cache"] = p.start()

    def patch_embeddings(self, mock: MagicMock) -> None:
        """Patch the Embeddings service."""
        p = patch("saqshy.services.embeddings.EmbeddingsService", return_value=mock)
        self._patches.append(p)
        self._mocks["embeddings"] = p.start()

    @property
    def mocks(self) -> dict[str, MagicMock]:
        """Get all patched mocks."""
        return self._mocks


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # LLM fixtures
    "MockLLMResult",
    "create_llm_result",
    "mock_llm_result_allow",
    "mock_llm_result_block",
    "mock_llm_result_watch",
    "mock_llm_result_error",
    "mock_llm_service",
    "mock_llm_service_unavailable",
    # SpamDB fixtures
    "SpamDBMatch",
    "mock_spam_db_service",
    "mock_spam_db_with_matches",
    # Cache fixtures
    "mock_cache_service",
    "mock_cache_service_with_history",
    # Embeddings fixtures
    "mock_embeddings_service",
    "mock_embeddings_service_realistic",
    # Channel subscription fixtures
    "mock_channel_subscription_service",
    "mock_channel_subscription_service_subscribed",
    # Combined fixtures
    "mock_all_services",
    # Utilities
    "ServicePatcher",
]
