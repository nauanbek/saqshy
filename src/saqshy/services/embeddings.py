"""
SAQSHY Embeddings Service

Cohere embeddings for spam pattern matching.

Uses embed-multilingual-v3.0 model (1024 dimensions) for:
- Converting messages to embeddings for spam DB search
- Semantic similarity matching against known spam patterns

Key Features:
- Async Cohere API integration with retries
- Redis-based embedding cache to reduce API calls
- Rate limiting to respect Cohere API limits
- Graceful degradation on API failures
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

import cohere
import cohere.core
import structlog
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

if TYPE_CHECKING:
    import redis.asyncio as redis

logger = structlog.get_logger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Cohere embed-multilingual-v3.0 configuration
EMBEDDING_MODEL = "embed-multilingual-v3.0"
EMBEDDING_DIMENSION = 1024

# Rate limiting (Cohere has limits on requests per minute)
MAX_TEXTS_PER_BATCH = 96  # Cohere limit per request
DEFAULT_RATE_LIMIT_RPM = 100  # Requests per minute
MIN_REQUEST_INTERVAL = 0.6  # Minimum seconds between requests (100 RPM)

# Text preprocessing
MAX_TEXT_LENGTH = 4096  # Truncate texts longer than this

# Cache TTL
TTL_EMBEDDING_CACHE = 3600  # 1 hour


# =============================================================================
# Exceptions
# =============================================================================


class EmbeddingError(Exception):
    """Base exception for embedding operations."""

    pass


class EmbeddingRateLimitError(EmbeddingError):
    """Rate limit exceeded."""

    pass


class EmbeddingAPIError(EmbeddingError):
    """API call failed."""

    pass


# =============================================================================
# Helper Functions for Error Handling
# =============================================================================


def _is_retryable_error(exc: BaseException) -> bool:
    """
    Check if an exception is retryable.

    Server errors (5xx) and some connection errors are retryable.
    Rate limit errors are not retried (handled separately).
    Bad request errors are not retried (client error).
    """
    # Check for Cohere API errors by status code
    if hasattr(exc, "status_code"):
        status = exc.status_code
        # Retry on server errors (5xx)
        return 500 <= status < 600

    # Check for connection/timeout errors
    error_name = type(exc).__name__.lower()
    return any(keyword in error_name for keyword in ["timeout", "connection", "unavailable"])


def _is_rate_limit_error(exc: BaseException) -> bool:
    """Check if an exception is a rate limit error."""
    if hasattr(exc, "status_code"):
        return exc.status_code == 429
    error_name = type(exc).__name__.lower()
    return "ratelimit" in error_name or "toomany" in error_name


def _is_bad_request_error(exc: BaseException) -> bool:
    """Check if an exception is a bad request error."""
    if hasattr(exc, "status_code"):
        return exc.status_code == 400
    error_name = type(exc).__name__.lower()
    return "badrequest" in error_name


# =============================================================================
# EmbeddingsService
# =============================================================================


class EmbeddingsService:
    """
    Cohere embeddings service for spam pattern matching.

    Used for:
    - Converting messages to embeddings
    - Semantic similarity search in spam database

    Thread Safety:
        This class is thread-safe when used with asyncio.
        Uses locks for rate limiting and client initialization.

    Example:
        >>> service = EmbeddingsService(api_key="cohere-api-key")
        >>> embedding = await service.embed_text("spam message")
        >>> query_embedding = await service.embed_query("search query")
    """

    def __init__(
        self,
        api_key: str,
        model: str = EMBEDDING_MODEL,
        input_type: str = "search_document",
        rate_limit_rpm: int = DEFAULT_RATE_LIMIT_RPM,
        cache: EmbeddingCache | None = None,
    ):
        """
        Initialize embeddings service.

        Args:
            api_key: Cohere API key.
            model: Embedding model to use (default: embed-multilingual-v3.0).
            input_type: Type of input (search_document or search_query).
            rate_limit_rpm: Maximum requests per minute.
            cache: Optional embedding cache instance.
        """
        self.api_key = api_key
        self.model = model
        self.input_type = input_type
        self.rate_limit_rpm = rate_limit_rpm
        self.cache = cache

        self._client: cohere.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        self._rate_limit_lock = asyncio.Lock()
        self._last_request_time: float = 0.0
        self._min_request_interval = 60.0 / rate_limit_rpm

    async def _get_client(self) -> cohere.AsyncClient:
        """
        Get or create the Cohere async client.

        Returns:
            Initialized Cohere AsyncClient.

        Thread-safe initialization using asyncio.Lock.
        """
        if self._client is None:
            async with self._client_lock:
                # Double-check after acquiring lock
                if self._client is None:
                    self._client = cohere.AsyncClient(api_key=self.api_key)
                    logger.info(
                        "cohere_client_initialized",
                        model=self.model,
                    )
        return self._client

    async def _rate_limit(self) -> None:
        """
        Enforce rate limiting between API calls.

        Uses a simple token bucket approach with minimum interval.
        """
        async with self._rate_limit_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time

            if elapsed < self._min_request_interval:
                wait_time = self._min_request_interval - elapsed
                logger.debug(
                    "rate_limit_waiting",
                    wait_seconds=round(wait_time, 3),
                )
                await asyncio.sleep(wait_time)

            self._last_request_time = time.monotonic()

    def _preprocess_text(self, text: str) -> str:
        """
        Preprocess text before embedding.

        Args:
            text: Raw input text.

        Returns:
            Normalized and truncated text.
        """
        # Normalize whitespace
        text = " ".join(text.split())

        # Truncate if too long
        if len(text) > MAX_TEXT_LENGTH:
            text = text[:MAX_TEXT_LENGTH]
            logger.debug(
                "text_truncated",
                original_length=len(text),
                truncated_to=MAX_TEXT_LENGTH,
            )

        return text

    def _preprocess_texts(self, texts: list[str]) -> list[str]:
        """Preprocess multiple texts."""
        return [self._preprocess_text(t) for t in texts]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable_error),
        reraise=True,
    )
    async def embed_text(self, text: str) -> list[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector (1024 dimensions for multilingual-v3).

        Raises:
            EmbeddingAPIError: If API call fails after retries.
        """
        # Check cache first
        if self.cache:
            cached = await self.cache.get(text)
            if cached is not None:
                logger.debug("embedding_cache_hit", text_length=len(text))
                return cached

        # Generate embedding
        embeddings = await self._embed_texts_internal([text], self.input_type)

        if embeddings:
            result = embeddings[0]
            # Cache the result
            if self.cache:
                await self.cache.set(text, result)
            return result

        return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable_error),
        reraise=True,
    )
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            EmbeddingAPIError: If API call fails after retries.
        """
        if not texts:
            return []

        # Check cache for each text
        results: list[list[float] | None] = [None] * len(texts)
        texts_to_embed: list[tuple[int, str]] = []

        if self.cache:
            for i, text in enumerate(texts):
                cached = await self.cache.get(text)
                if cached is not None:
                    results[i] = cached
                else:
                    texts_to_embed.append((i, text))
        else:
            texts_to_embed = list(enumerate(texts))

        if texts_to_embed:
            # Extract just the texts for embedding
            indices = [idx for idx, _ in texts_to_embed]
            texts_only = [text for _, text in texts_to_embed]

            # Batch embed uncached texts
            embeddings = await self._embed_texts_batched(texts_only, self.input_type)

            # Place results back and cache
            for i, (original_idx, text) in enumerate(zip(indices, texts_only)):
                if i < len(embeddings):
                    results[original_idx] = embeddings[i]
                    if self.cache:
                        await self.cache.set(text, embeddings[i])

        # Replace None with empty lists (shouldn't happen normally)
        return [r if r is not None else [] for r in results]

    async def embed_query(self, query: str) -> list[float]:
        """
        Generate embedding for a search query.

        Uses input_type="search_query" for better similarity search.
        Cohere recommends using different input types for documents vs queries
        for optimal retrieval performance.

        Args:
            query: Query text.

        Returns:
            Query embedding vector.

        Raises:
            EmbeddingAPIError: If API call fails after retries.
        """
        # Queries use different input_type for better retrieval
        embeddings = await self._embed_texts_internal([query], "search_query")
        return embeddings[0] if embeddings else []

    async def _embed_texts_internal(
        self,
        texts: list[str],
        input_type: str,
    ) -> list[list[float]]:
        """
        Internal method to embed texts with the Cohere API.

        Args:
            texts: Preprocessed texts to embed.
            input_type: Cohere input type (search_document or search_query).

        Returns:
            List of embedding vectors.
        """
        if not texts:
            return []

        # Preprocess texts
        processed_texts = self._preprocess_texts(texts)

        # Filter out empty texts
        non_empty = [(i, t) for i, t in enumerate(processed_texts) if t.strip()]
        if not non_empty:
            logger.warning("all_texts_empty_after_preprocessing")
            return [[0.0] * EMBEDDING_DIMENSION for _ in texts]

        # Enforce rate limit
        await self._rate_limit()

        try:
            client = await self._get_client()

            logger.debug(
                "generating_embeddings",
                count=len(non_empty),
                model=self.model,
                input_type=input_type,
            )

            response = await client.embed(
                texts=[t for _, t in non_empty],
                model=self.model,
                input_type=input_type,
            )

            # Build result with zeros for empty texts
            result: list[list[float]] = [[0.0] * EMBEDDING_DIMENSION for _ in texts]
            embeddings = response.embeddings
            # Handle both list[list[float]] and EmbedByTypeResponseEmbeddings
            if hasattr(embeddings, "__iter__") and not isinstance(embeddings, dict):
                embeddings_list = list(embeddings)
                for i, (original_idx, _) in enumerate(non_empty):
                    if i < len(embeddings_list):
                        result[original_idx] = [float(x) for x in embeddings_list[i]]

            logger.info(
                "embeddings_generated",
                count=len(non_empty),
                dimension=EMBEDDING_DIMENSION,
            )

            return result

        except Exception as e:
            # Handle errors by checking status code or exception type
            if _is_rate_limit_error(e):
                logger.warning("cohere_rate_limit_exceeded", error=str(e))
                raise EmbeddingRateLimitError(f"Rate limit exceeded: {e}") from e

            if _is_bad_request_error(e):
                logger.error("cohere_bad_request", error=str(e))
                raise EmbeddingAPIError(f"Bad request: {e}") from e

            if _is_retryable_error(e):
                logger.error("cohere_server_error", error=str(e))
                raise EmbeddingAPIError(f"Server error: {e}") from e

            logger.error(
                "embedding_generation_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise EmbeddingAPIError(f"Embedding failed: {e}") from e

    async def _embed_texts_batched(
        self,
        texts: list[str],
        input_type: str,
    ) -> list[list[float]]:
        """
        Embed texts in batches to respect API limits.

        Args:
            texts: Texts to embed.
            input_type: Cohere input type.

        Returns:
            List of embedding vectors.
        """
        if len(texts) <= MAX_TEXTS_PER_BATCH:
            return await self._embed_texts_internal(texts, input_type)

        # Split into batches
        results: list[list[float]] = []
        for i in range(0, len(texts), MAX_TEXTS_PER_BATCH):
            batch = texts[i : i + MAX_TEXTS_PER_BATCH]
            batch_embeddings = await self._embed_texts_internal(batch, input_type)
            results.extend(batch_embeddings)

            logger.debug(
                "batch_embedded",
                batch_num=i // MAX_TEXTS_PER_BATCH + 1,
                batch_size=len(batch),
                total=len(texts),
            )

        return results

    async def close(self) -> None:
        """Close the Cohere client connection."""
        if self._client:
            # Cohere client doesn't have explicit close, but we can clear reference
            self._client = None
            logger.info("embeddings_service_closed")


# =============================================================================
# EmbeddingCache
# =============================================================================


class EmbeddingCache:
    """
    Caches embeddings to reduce API calls.

    Uses content hash as key to cache embeddings for
    frequently seen spam patterns.

    Supports two backends:
    - Redis: For production use with persistence
    - In-memory dict: For testing and development

    Example:
        >>> # Redis-backed cache
        >>> cache = EmbeddingCache(redis_client=redis_client)

        >>> # In-memory cache
        >>> cache = EmbeddingCache()

        >>> await cache.set("spam text", [0.1, 0.2, ...])
        >>> embedding = await cache.get("spam text")
    """

    # Redis key prefix
    KEY_PREFIX = "saqshy:emb"

    def __init__(
        self,
        redis_client: redis.Redis | None = None,
        ttl_seconds: int = TTL_EMBEDDING_CACHE,
        max_memory_entries: int = 1000,
    ):
        """
        Initialize embedding cache.

        Args:
            redis_client: Optional Redis client for persistent cache.
            ttl_seconds: Time-to-live for cached embeddings.
            max_memory_entries: Max entries for in-memory cache (LRU eviction).
        """
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds
        self.max_memory_entries = max_memory_entries

        # In-memory cache as fallback or for testing
        self._memory_cache: dict[str, tuple[list[float], float]] = {}
        self._memory_lock = asyncio.Lock()

    def _hash_text(self, text: str) -> str:
        """
        Generate hash for text.

        Uses SHA-256 truncated to 16 chars for compact keys.
        """
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def _make_key(self, text: str) -> str:
        """Generate Redis key for text."""
        return f"{self.KEY_PREFIX}:{self._hash_text(text)}"

    async def get(self, text: str) -> list[float] | None:
        """
        Get cached embedding for text.

        Checks Redis first, falls back to memory cache.

        Args:
            text: Original text.

        Returns:
            Cached embedding or None.
        """
        text_hash = self._hash_text(text)

        # Try Redis first
        if self.redis:
            try:
                key = self._make_key(text)
                value = await self.redis.get(key)
                if value:
                    embedding = json.loads(value)
                    logger.debug("embedding_cache_hit_redis", hash=text_hash)
                    return embedding
            except Exception as e:
                logger.warning(
                    "redis_cache_get_failed",
                    error=str(e),
                    hash=text_hash,
                )

        # Check memory cache
        async with self._memory_lock:
            if text_hash in self._memory_cache:
                embedding, timestamp = self._memory_cache[text_hash]
                if time.time() - timestamp < self.ttl_seconds:
                    logger.debug("embedding_cache_hit_memory", hash=text_hash)
                    return embedding
                else:
                    # Expired
                    del self._memory_cache[text_hash]

        return None

    async def set(self, text: str, embedding: list[float]) -> None:
        """
        Cache embedding for text.

        Stores in both Redis and memory cache.

        Args:
            text: Original text.
            embedding: Embedding vector.
        """
        text_hash = self._hash_text(text)

        # Store in Redis
        if self.redis:
            try:
                key = self._make_key(text)
                value = json.dumps(embedding)
                await self.redis.set(key, value, ex=self.ttl_seconds)
                logger.debug("embedding_cached_redis", hash=text_hash)
            except Exception as e:
                logger.warning(
                    "redis_cache_set_failed",
                    error=str(e),
                    hash=text_hash,
                )

        # Store in memory cache
        async with self._memory_lock:
            # Simple LRU: remove oldest if at capacity
            if len(self._memory_cache) >= self.max_memory_entries:
                # Remove oldest entry
                oldest_hash = min(
                    self._memory_cache.keys(),
                    key=lambda k: self._memory_cache[k][1],
                )
                del self._memory_cache[oldest_hash]

            self._memory_cache[text_hash] = (embedding, time.time())

    async def clear(self) -> None:
        """Clear all cached embeddings."""
        async with self._memory_lock:
            self._memory_cache.clear()

        logger.info("embedding_cache_cleared")

    async def stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with cache stats.
        """
        async with self._memory_lock:
            memory_size = len(self._memory_cache)

        return {
            "memory_entries": memory_size,
            "max_memory_entries": self.max_memory_entries,
            "ttl_seconds": self.ttl_seconds,
            "redis_enabled": self.redis is not None,
        }


# =============================================================================
# Factory Function
# =============================================================================


def create_embeddings_service(
    api_key: str,
    redis_client: redis.Redis | None = None,
    rate_limit_rpm: int = DEFAULT_RATE_LIMIT_RPM,
) -> EmbeddingsService:
    """
    Factory function to create an embeddings service with cache.

    Args:
        api_key: Cohere API key.
        redis_client: Optional Redis client for caching.
        rate_limit_rpm: Maximum requests per minute.

    Returns:
        Configured EmbeddingsService instance.

    Example:
        >>> service = create_embeddings_service(
        ...     api_key=os.environ["COHERE_API_KEY"],
        ...     redis_client=redis_client,
        ... )
    """
    cache = EmbeddingCache(redis_client=redis_client)
    return EmbeddingsService(
        api_key=api_key,
        cache=cache,
        rate_limit_rpm=rate_limit_rpm,
    )
