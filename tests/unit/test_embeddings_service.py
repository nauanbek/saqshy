"""
Unit Tests for Embeddings Service

Tests the Cohere embeddings integration with:
- Mock API responses
- Caching behavior
- Rate limiting
- Error handling
- Text preprocessing

These tests use deterministic mock embeddings to ensure
legitimate crypto discussions are not matched as spam.
"""

import asyncio
import hashlib
import time
from unittest.mock import AsyncMock, patch

import pytest

from saqshy.services.embeddings import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    MAX_TEXT_LENGTH,
    MAX_TEXTS_PER_BATCH,
    EmbeddingAPIError,
    EmbeddingCache,
    EmbeddingRateLimitError,
    EmbeddingsService,
    create_embeddings_service,
)

# =============================================================================
# Deterministic Test Embeddings
# =============================================================================

# Deterministic embeddings for testing similarity behavior
# These are simplified 1024-dim vectors with known similarity properties


def make_deterministic_embedding(seed: int, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    """Create a deterministic embedding based on a seed value."""
    import random

    rng = random.Random(seed)
    return [rng.random() for _ in range(dimension)]


# Known embeddings for test cases
TEST_EMBEDDINGS = {
    # Crypto scam patterns (should have high similarity to each other)
    "crypto_scam_1": make_deterministic_embedding(1001),
    "crypto_scam_2": make_deterministic_embedding(1002),  # Similar to scam_1
    # Legitimate crypto discussion (should NOT match scam patterns)
    "legitimate_btc_discussion": make_deterministic_embedding(2001),
    # Deals/promo (should NOT match crypto scam)
    "deals_promo": make_deterministic_embedding(3001),
    # General message
    "general_message": make_deterministic_embedding(4001),
}


# =============================================================================
# Mock Cohere Client
# =============================================================================


class MockCohereResponse:
    """Mock Cohere embed response."""

    def __init__(self, embeddings: list[list[float]]):
        self.embeddings = embeddings


def create_mock_cohere_client(
    default_embedding: list[float] | None = None,
    embeddings_map: dict[str, list[float]] | None = None,
    should_fail: bool = False,
    fail_exception: type[Exception] | None = None,
) -> AsyncMock:
    """
    Create a mock Cohere AsyncClient.

    Args:
        default_embedding: Default embedding to return.
        embeddings_map: Map of text to specific embeddings.
        should_fail: If True, raise exception on embed().
        fail_exception: Exception type to raise.
    """
    mock_client = AsyncMock()

    async def mock_embed(texts: list[str], model: str, input_type: str) -> MockCohereResponse:
        if should_fail:
            exc = fail_exception or Exception("Mock failure")
            raise exc("API Error")

        embeddings = []
        for text in texts:
            if embeddings_map and text in embeddings_map:
                embeddings.append(embeddings_map[text])
            elif default_embedding:
                embeddings.append(default_embedding)
            else:
                # Generate deterministic embedding based on text hash
                seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
                embeddings.append(make_deterministic_embedding(seed))

        return MockCohereResponse(embeddings)

    mock_client.embed = mock_embed
    return mock_client


# =============================================================================
# Test EmbeddingsService
# =============================================================================


class TestEmbeddingsServiceInit:
    """Test EmbeddingsService initialization."""

    def test_init_defaults(self):
        """Service initializes with correct defaults."""
        service = EmbeddingsService(api_key="test-key")

        assert service.api_key == "test-key"
        assert service.model == EMBEDDING_MODEL
        assert service.input_type == "search_document"
        assert service._client is None

    def test_init_custom_model(self):
        """Service accepts custom model."""
        service = EmbeddingsService(
            api_key="test-key",
            model="custom-model",
        )

        assert service.model == "custom-model"

    def test_init_with_cache(self):
        """Service accepts cache instance."""
        cache = EmbeddingCache()
        service = EmbeddingsService(
            api_key="test-key",
            cache=cache,
        )

        assert service.cache is cache


class TestEmbeddingsServiceClient:
    """Test Cohere client initialization."""

    @pytest.mark.asyncio
    async def test_get_client_lazy_init(self):
        """Client is lazily initialized on first use."""
        service = EmbeddingsService(api_key="test-key")

        assert service._client is None

        with patch("cohere.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = AsyncMock()
            client = await service._get_client()

            mock_client_cls.assert_called_once_with(api_key="test-key")
            assert client is not None
            assert service._client is client

    @pytest.mark.asyncio
    async def test_get_client_reuses_instance(self):
        """Client instance is reused across calls."""
        service = EmbeddingsService(api_key="test-key")

        with patch("cohere.AsyncClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_client_cls.return_value = mock_instance

            client1 = await service._get_client()
            client2 = await service._get_client()

            # Should only create once
            mock_client_cls.assert_called_once()
            assert client1 is client2


class TestTextPreprocessing:
    """Test text preprocessing."""

    def test_preprocess_whitespace(self):
        """Whitespace is normalized."""
        service = EmbeddingsService(api_key="test-key")

        result = service._preprocess_text("  hello   world  \n\t foo  ")
        assert result == "hello world foo"

    def test_preprocess_truncation(self):
        """Long text is truncated."""
        service = EmbeddingsService(api_key="test-key")

        long_text = "x" * (MAX_TEXT_LENGTH + 100)
        result = service._preprocess_text(long_text)

        assert len(result) == MAX_TEXT_LENGTH

    def test_preprocess_empty(self):
        """Empty text returns empty string."""
        service = EmbeddingsService(api_key="test-key")

        assert service._preprocess_text("") == ""
        assert service._preprocess_text("   ") == ""


class TestEmbedText:
    """Test single text embedding."""

    @pytest.mark.asyncio
    async def test_embed_text_returns_vector(self):
        """embed_text returns correct dimension vector."""
        service = EmbeddingsService(api_key="test-key")
        mock_client = create_mock_cohere_client()
        service._client = mock_client

        embedding = await service.embed_text("test message")

        assert len(embedding) == EMBEDDING_DIMENSION
        assert all(isinstance(v, float) for v in embedding)

    @pytest.mark.asyncio
    async def test_embed_text_uses_cache(self):
        """embed_text checks cache first."""
        cache = EmbeddingCache()
        cached_embedding = [0.5] * EMBEDDING_DIMENSION
        await cache.set("test message", cached_embedding)

        service = EmbeddingsService(api_key="test-key", cache=cache)
        mock_client = create_mock_cohere_client()
        service._client = mock_client

        result = await service.embed_text("test message")

        assert result == cached_embedding

    @pytest.mark.asyncio
    async def test_embed_text_caches_result(self):
        """embed_text caches the result."""
        cache = EmbeddingCache()
        service = EmbeddingsService(api_key="test-key", cache=cache)

        mock_client = create_mock_cohere_client(default_embedding=[0.1] * EMBEDDING_DIMENSION)
        service._client = mock_client

        await service.embed_text("new message")

        cached = await cache.get("new message")
        assert cached is not None
        assert cached == [0.1] * EMBEDDING_DIMENSION


class TestEmbedTexts:
    """Test batch text embedding."""

    @pytest.mark.asyncio
    async def test_embed_texts_empty_list(self):
        """embed_texts handles empty list."""
        service = EmbeddingsService(api_key="test-key")

        result = await service.embed_texts([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_texts_batch(self):
        """embed_texts processes multiple texts."""
        service = EmbeddingsService(api_key="test-key")
        mock_client = create_mock_cohere_client()
        service._client = mock_client

        texts = ["message 1", "message 2", "message 3"]
        embeddings = await service.embed_texts(texts)

        assert len(embeddings) == 3
        for emb in embeddings:
            assert len(emb) == EMBEDDING_DIMENSION

    @pytest.mark.asyncio
    async def test_embed_texts_partial_cache(self):
        """embed_texts uses cache for some texts."""
        cache = EmbeddingCache()
        await cache.set("cached text", [0.9] * EMBEDDING_DIMENSION)

        service = EmbeddingsService(api_key="test-key", cache=cache)
        mock_client = create_mock_cohere_client(default_embedding=[0.1] * EMBEDDING_DIMENSION)
        service._client = mock_client

        texts = ["cached text", "new text"]
        embeddings = await service.embed_texts(texts)

        assert embeddings[0] == [0.9] * EMBEDDING_DIMENSION  # From cache
        assert embeddings[1] == [0.1] * EMBEDDING_DIMENSION  # From API


class TestEmbedQuery:
    """Test query embedding."""

    @pytest.mark.asyncio
    async def test_embed_query_uses_search_query_type(self):
        """embed_query uses search_query input type."""
        service = EmbeddingsService(api_key="test-key")

        # Track the input_type used
        called_input_type = None

        async def mock_embed(texts, model, input_type):
            nonlocal called_input_type
            called_input_type = input_type
            return MockCohereResponse([[0.1] * EMBEDDING_DIMENSION])

        mock_client = AsyncMock()
        mock_client.embed = mock_embed
        service._client = mock_client

        await service.embed_query("search query")

        assert called_input_type == "search_query"


class TestRateLimiting:
    """Test rate limiting behavior."""

    @pytest.mark.asyncio
    async def test_rate_limit_enforces_interval(self):
        """Rate limiter enforces minimum interval."""
        # Use high RPM to make interval short but measurable
        service = EmbeddingsService(api_key="test-key", rate_limit_rpm=600)

        mock_client = create_mock_cohere_client(default_embedding=[0.1] * EMBEDDING_DIMENSION)
        service._client = mock_client

        # Make two quick requests
        start = time.monotonic()
        await service.embed_text("text 1")
        await service.embed_text("text 2")
        elapsed = time.monotonic() - start

        # With 600 RPM, interval is 0.1 seconds
        # Should take at least 0.1 seconds for 2 requests
        assert elapsed >= 0.1


class TestBatching:
    """Test batch size handling."""

    @pytest.mark.asyncio
    async def test_large_batch_splits(self):
        """Large batches are split correctly."""
        service = EmbeddingsService(api_key="test-key")

        call_count = 0
        call_sizes = []

        async def mock_embed(texts, model, input_type):
            nonlocal call_count
            call_count += 1
            call_sizes.append(len(texts))
            return MockCohereResponse([[0.1] * EMBEDDING_DIMENSION for _ in texts])

        mock_client = AsyncMock()
        mock_client.embed = mock_embed
        service._client = mock_client

        # Create batch larger than MAX_TEXTS_PER_BATCH
        texts = [f"text {i}" for i in range(MAX_TEXTS_PER_BATCH + 10)]

        result = await service._embed_texts_batched(texts, "search_document")

        assert len(result) == MAX_TEXTS_PER_BATCH + 10
        assert call_count == 2
        assert call_sizes[0] == MAX_TEXTS_PER_BATCH
        assert call_sizes[1] == 10


class MockAPIError(Exception):
    """Mock API error with status_code attribute."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class TestErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_rate_limit_error_raised(self):
        """Rate limit error is raised with proper type."""
        service = EmbeddingsService(api_key="test-key")

        mock_client = AsyncMock()
        mock_client.embed.side_effect = MockAPIError("Rate limited", status_code=429)
        service._client = mock_client

        with pytest.raises(EmbeddingRateLimitError):
            await service.embed_text("test")

    @pytest.mark.asyncio
    async def test_bad_request_error_raised(self):
        """Bad request error is raised with proper type."""
        service = EmbeddingsService(api_key="test-key")

        mock_client = AsyncMock()
        mock_client.embed.side_effect = MockAPIError("Bad request", status_code=400)
        service._client = mock_client

        with pytest.raises(EmbeddingAPIError):
            await service.embed_text("test")

    @pytest.mark.asyncio
    async def test_server_error_raised(self):
        """Server error is raised with proper type."""
        service = EmbeddingsService(api_key="test-key")

        mock_client = AsyncMock()
        mock_client.embed.side_effect = MockAPIError("Server error", status_code=500)
        service._client = mock_client

        with pytest.raises(EmbeddingAPIError):
            await service.embed_text("test")


# =============================================================================
# Test EmbeddingCache
# =============================================================================


class TestEmbeddingCacheInit:
    """Test EmbeddingCache initialization."""

    def test_init_defaults(self):
        """Cache initializes with correct defaults."""
        cache = EmbeddingCache()

        assert cache.ttl_seconds == 3600
        assert cache.max_memory_entries == 1000
        assert cache.redis is None

    def test_init_with_redis(self):
        """Cache accepts Redis client."""
        mock_redis = AsyncMock()
        cache = EmbeddingCache(redis_client=mock_redis)

        assert cache.redis is mock_redis


class TestEmbeddingCacheHashing:
    """Test cache key hashing."""

    def test_hash_consistency(self):
        """Same text produces same hash."""
        cache = EmbeddingCache()

        hash1 = cache._hash_text("test text")
        hash2 = cache._hash_text("test text")

        assert hash1 == hash2

    def test_hash_uniqueness(self):
        """Different texts produce different hashes."""
        cache = EmbeddingCache()

        hash1 = cache._hash_text("text one")
        hash2 = cache._hash_text("text two")

        assert hash1 != hash2

    def test_hash_length(self):
        """Hash is 16 characters."""
        cache = EmbeddingCache()

        text_hash = cache._hash_text("any text")
        assert len(text_hash) == 16


class TestEmbeddingCacheMemory:
    """Test in-memory caching."""

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        """Can set and get embedding from memory cache."""
        cache = EmbeddingCache()

        embedding = [0.1, 0.2, 0.3]
        await cache.set("test text", embedding)

        result = await cache.get("test text")
        assert result == embedding

    @pytest.mark.asyncio
    async def test_get_missing(self):
        """Missing key returns None."""
        cache = EmbeddingCache()

        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expiration(self):
        """Expired entries return None."""
        cache = EmbeddingCache(ttl_seconds=0)  # Immediate expiration

        await cache.set("test", [0.1])
        await asyncio.sleep(0.1)

        result = await cache.get("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        """Oldest entries are evicted at capacity."""
        cache = EmbeddingCache(max_memory_entries=2)

        await cache.set("text1", [0.1])
        await asyncio.sleep(0.01)
        await cache.set("text2", [0.2])
        await asyncio.sleep(0.01)
        await cache.set("text3", [0.3])  # Should evict text1

        assert await cache.get("text1") is None
        assert await cache.get("text2") == [0.2]
        assert await cache.get("text3") == [0.3]


class TestEmbeddingCacheRedis:
    """Test Redis caching."""

    @pytest.mark.asyncio
    async def test_redis_set_and_get(self):
        """Can set and get from Redis."""
        import json

        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps([0.1, 0.2, 0.3])

        cache = EmbeddingCache(redis_client=mock_redis)

        result = await cache.get("test text")
        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_redis_set_calls_redis(self):
        """set() calls Redis with correct key and TTL."""
        mock_redis = AsyncMock()
        cache = EmbeddingCache(redis_client=mock_redis, ttl_seconds=600)

        await cache.set("test text", [0.1, 0.2])

        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args.kwargs["ex"] == 600

    @pytest.mark.asyncio
    async def test_redis_failure_falls_back_to_memory(self):
        """Redis failure falls back to memory cache."""
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = Exception("Redis down")

        cache = EmbeddingCache(redis_client=mock_redis)

        # Set in memory
        await cache.set("test", [0.1])

        # Get should fall back to memory
        mock_redis.get.reset_mock()
        mock_redis.get.side_effect = Exception("Redis down")

        result = await cache.get("test")
        assert result == [0.1]  # From memory


class TestEmbeddingCacheStats:
    """Test cache statistics."""

    @pytest.mark.asyncio
    async def test_stats_memory_only(self):
        """Stats show memory cache info."""
        cache = EmbeddingCache(max_memory_entries=500)
        await cache.set("text1", [0.1])
        await cache.set("text2", [0.2])

        stats = await cache.stats()

        assert stats["memory_entries"] == 2
        assert stats["max_memory_entries"] == 500
        assert stats["redis_enabled"] is False

    @pytest.mark.asyncio
    async def test_stats_with_redis(self):
        """Stats show Redis enabled."""
        mock_redis = AsyncMock()
        cache = EmbeddingCache(redis_client=mock_redis)

        stats = await cache.stats()
        assert stats["redis_enabled"] is True


# =============================================================================
# Test Factory Function
# =============================================================================


class TestCreateEmbeddingsService:
    """Test factory function."""

    def test_creates_service_with_cache(self):
        """Factory creates service with cache."""
        service = create_embeddings_service(api_key="test-key")

        assert service.api_key == "test-key"
        assert service.cache is not None
        assert isinstance(service.cache, EmbeddingCache)

    def test_creates_service_with_redis(self):
        """Factory passes Redis to cache."""
        mock_redis = AsyncMock()
        service = create_embeddings_service(
            api_key="test-key",
            redis_client=mock_redis,
        )

        assert service.cache.redis is mock_redis


# =============================================================================
# Test Spam Pattern Detection Requirements
# =============================================================================


class TestSpamPatternRequirements:
    """
    Test that embeddings work correctly for spam detection.

    These tests verify:
    1. Crypto scam patterns generate valid embeddings
    2. Legitimate discussions generate different embeddings
    3. The service can handle the expected message types
    """

    @pytest.mark.asyncio
    async def test_crypto_scam_generates_embedding(self):
        """Crypto scam message generates valid embedding."""
        service = EmbeddingsService(api_key="test-key")
        mock_client = create_mock_cohere_client()
        service._client = mock_client

        scam_text = "Double your Bitcoin in 24 hours! DM me for the secret method"
        embedding = await service.embed_text(scam_text)

        assert len(embedding) == EMBEDDING_DIMENSION
        assert not all(v == 0.0 for v in embedding)  # Not all zeros

    @pytest.mark.asyncio
    async def test_legitimate_crypto_generates_embedding(self):
        """Legitimate crypto discussion generates valid embedding."""
        service = EmbeddingsService(api_key="test-key")
        mock_client = create_mock_cohere_client()
        service._client = mock_client

        legit_text = "What's the current Bitcoin price? I'm tracking the market."
        embedding = await service.embed_text(legit_text)

        assert len(embedding) == EMBEDDING_DIMENSION
        assert not all(v == 0.0 for v in embedding)

    @pytest.mark.asyncio
    async def test_deals_promo_generates_embedding(self):
        """Deals/promo message generates valid embedding."""
        service = EmbeddingsService(api_key="test-key")
        mock_client = create_mock_cohere_client()
        service._client = mock_client

        promo_text = "Ozon promo code BLACKFRIDAY for 20% off"
        embedding = await service.embed_text(promo_text)

        assert len(embedding) == EMBEDDING_DIMENSION
        assert not all(v == 0.0 for v in embedding)

    @pytest.mark.asyncio
    async def test_multilingual_support(self):
        """Russian text generates valid embedding."""
        service = EmbeddingsService(api_key="test-key")
        mock_client = create_mock_cohere_client()
        service._client = mock_client

        russian_text = "Гарантированный доход от 500$ в день!"
        embedding = await service.embed_text(russian_text)

        assert len(embedding) == EMBEDDING_DIMENSION
        assert not all(v == 0.0 for v in embedding)

    @pytest.mark.asyncio
    async def test_embedding_dimension_constant(self):
        """Embedding dimension matches expected value."""
        assert EMBEDDING_DIMENSION == 1024

    @pytest.mark.asyncio
    async def test_model_name_constant(self):
        """Model name matches expected value."""
        assert EMBEDDING_MODEL == "embed-multilingual-v3.0"
