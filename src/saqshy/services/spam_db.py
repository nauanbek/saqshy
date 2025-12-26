"""
SAQSHY Spam Database Service

Qdrant vector database for spam pattern matching using Cohere embeddings.
Provides semantic similarity search to detect spam patterns.

Key Features:
- Cohere embed-multilingual-v3.0 embeddings (1024 dimensions)
- Qdrant vector storage with cosine similarity
- Tiered similarity scoring for risk calculation
- In-memory embedding cache with TTL
- Comprehensive error handling with retries
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import cohere
import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qdrant_models
from qdrant_client.http.exceptions import UnexpectedResponse
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)


# =============================================================================
# Similarity Thresholds and Scoring
# =============================================================================

# Tiered similarity thresholds for spam matching
# Higher thresholds = more confidence = higher risk score
SIMILARITY_THRESHOLDS = {
    "near_exact": 0.95,  # Near-exact match
    "high": 0.88,  # High similarity (confident match)
    "medium": 0.80,  # Medium similarity (probable match)
    "low": 0.70,  # Low similarity (weak signal)
}

# Risk score points based on similarity tier
SIMILARITY_SCORES = {
    "near_exact": 50,  # +50 points for near-exact match
    "high": 45,  # +45 points for high similarity
    "medium": 35,  # +35 points for medium similarity
    "low": 25,  # +25 points for low similarity
}


def get_risk_score_for_similarity(similarity: float) -> int:
    """
    Calculate risk score points based on similarity value.

    Args:
        similarity: Cosine similarity score (0.0 to 1.0)

    Returns:
        Risk score points to add (0, 25, 35, 45, or 50)
    """
    if similarity >= SIMILARITY_THRESHOLDS["near_exact"]:
        return SIMILARITY_SCORES["near_exact"]
    elif similarity >= SIMILARITY_THRESHOLDS["high"]:
        return SIMILARITY_SCORES["high"]
    elif similarity >= SIMILARITY_THRESHOLDS["medium"]:
        return SIMILARITY_SCORES["medium"]
    elif similarity >= SIMILARITY_THRESHOLDS["low"]:
        return SIMILARITY_SCORES["low"]
    return 0


def get_similarity_tier(similarity: float) -> str | None:
    """
    Get the similarity tier name for a score.

    Args:
        similarity: Cosine similarity score (0.0 to 1.0)

    Returns:
        Tier name ("near_exact", "high", "medium", "low") or None
    """
    if similarity >= SIMILARITY_THRESHOLDS["near_exact"]:
        return "near_exact"
    elif similarity >= SIMILARITY_THRESHOLDS["high"]:
        return "high"
    elif similarity >= SIMILARITY_THRESHOLDS["medium"]:
        return "medium"
    elif similarity >= SIMILARITY_THRESHOLDS["low"]:
        return "low"
    return None


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class SpamMatch:
    """Result of a spam pattern match."""

    score: float  # Similarity score (0.0 to 1.0)
    text: str  # Matched spam pattern text
    threat_type: str  # Type of threat (crypto_scam, phishing, etc.)
    pattern_id: str  # Unique pattern ID
    risk_points: int = 0  # Risk score points based on similarity
    tier: str | None = None  # Similarity tier (near_exact, high, medium, low)
    source: str = ""  # Source of the pattern (manual, auto, report)
    language: str = ""  # Pattern language
    created_at: str = ""  # When pattern was added

    def __post_init__(self) -> None:
        """Calculate risk points and tier after initialization."""
        if self.risk_points == 0:
            self.risk_points = get_risk_score_for_similarity(self.score)
        if self.tier is None:
            self.tier = get_similarity_tier(self.score)


@dataclass
class CacheEntry:
    """Cached embedding entry with TTL."""

    embedding: list[float]
    created_at: float = field(default_factory=time.time)

    def is_expired(self, ttl_seconds: float) -> bool:
        """Check if cache entry has expired."""
        return (time.time() - self.created_at) > ttl_seconds


# =============================================================================
# SpamDB Service
# =============================================================================


class SpamDB:
    """
    Qdrant-based spam pattern database with Cohere embeddings.

    Provides semantic similarity search to detect messages that match
    known spam patterns. Uses tiered scoring to assign risk points
    based on similarity confidence.

    Usage:
        spam_db = SpamDB(
            qdrant_url="http://localhost:6333",
            cohere_api_key="your-key",
        )
        await spam_db.initialize()

        # Check if message is spam
        similarity, matched_text = await spam_db.check_spam("suspicious message")

        # Add new spam pattern
        pattern_id = await spam_db.add_spam_pattern(
            text="Known spam text",
            threat_type="crypto_scam",
        )

        await spam_db.close()
    """

    # Qdrant configuration
    DEFAULT_COLLECTION = "spam_embeddings"
    VECTOR_SIZE = 1024  # Cohere embed-multilingual-v3.0
    DISTANCE_METRIC = qdrant_models.Distance.COSINE

    # Cohere configuration
    EMBEDDING_MODEL = "embed-multilingual-v3.0"

    # Cache configuration
    DEFAULT_CACHE_TTL = 300  # 5 minutes

    # Minimum text length for processing
    MIN_TEXT_LENGTH = 10

    def __init__(
        self,
        qdrant_url: str,
        cohere_api_key: str,
        collection_name: str = DEFAULT_COLLECTION,
        qdrant_api_key: str | None = None,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL,
    ):
        """
        Initialize SpamDB service.

        Args:
            qdrant_url: Qdrant server URL (e.g., "http://localhost:6333")
            cohere_api_key: Cohere API key for embeddings
            collection_name: Qdrant collection name for spam patterns
            qdrant_api_key: Optional Qdrant API key for authentication
            cache_ttl_seconds: TTL for embedding cache entries
        """
        self.qdrant_url = qdrant_url
        self.cohere_api_key = cohere_api_key
        self.collection_name = collection_name
        self.qdrant_api_key = qdrant_api_key
        self.cache_ttl_seconds = cache_ttl_seconds

        # Clients (initialized lazily)
        self._qdrant_client: AsyncQdrantClient | None = None
        self._cohere_client: cohere.AsyncClient | None = None

        # In-memory embedding cache
        self._embedding_cache: dict[str, CacheEntry] = {}

        # Track initialization state
        self._initialized = False

        logger.debug(
            "spam_db_created",
            qdrant_url=qdrant_url,
            collection=collection_name,
            cache_ttl=cache_ttl_seconds,
        )

    # =========================================================================
    # Client Management
    # =========================================================================

    async def _get_qdrant_client(self) -> AsyncQdrantClient:
        """Get or create Qdrant async client."""
        if self._qdrant_client is None:
            self._qdrant_client = AsyncQdrantClient(
                url=self.qdrant_url,
                api_key=self.qdrant_api_key,
                timeout=30,
            )
            logger.debug("qdrant_client_created", url=self.qdrant_url)
        return self._qdrant_client

    async def _get_cohere_client(self) -> cohere.AsyncClient:
        """Get or create Cohere async client."""
        if self._cohere_client is None:
            self._cohere_client = cohere.AsyncClient(
                api_key=self.cohere_api_key,
                timeout=30,
            )
            logger.debug("cohere_client_created")
        return self._cohere_client

    # =========================================================================
    # Initialization
    # =========================================================================

    async def initialize(self) -> None:
        """
        Initialize the SpamDB service.

        Creates the Qdrant collection if it doesn't exist and verifies
        connectivity to both Qdrant and Cohere services.

        Raises:
            ConnectionError: If unable to connect to services
        """
        if self._initialized:
            logger.debug("spam_db_already_initialized")
            return

        try:
            # Initialize clients
            qdrant = await self._get_qdrant_client()
            cohere_client = await self._get_cohere_client()

            # Ensure collection exists
            await self._ensure_collection(qdrant)

            # Verify Cohere connectivity with a test embedding
            await self._verify_cohere(cohere_client)

            self._initialized = True
            logger.info(
                "spam_db_initialized",
                collection=self.collection_name,
                vector_size=self.VECTOR_SIZE,
            )

        except Exception as e:
            logger.error("spam_db_initialization_failed", error=str(e))
            raise ConnectionError(f"Failed to initialize SpamDB: {e}") from e

    async def _ensure_collection(self, client: AsyncQdrantClient) -> None:
        """
        Ensure the Qdrant collection exists with proper configuration.

        Creates the collection if it doesn't exist, otherwise verifies
        the existing collection has compatible settings.
        """
        try:
            # Check if collection exists
            collections = await client.get_collections()
            existing_names = [c.name for c in collections.collections]

            if self.collection_name in existing_names:
                # Verify collection configuration
                collection_info = await client.get_collection(self.collection_name)

                # Check vector size matches
                vectors_config = collection_info.config.params.vectors
                if isinstance(vectors_config, qdrant_models.VectorParams):
                    if vectors_config.size != self.VECTOR_SIZE:
                        raise ValueError(
                            f"Collection {self.collection_name} has vector size "
                            f"{vectors_config.size}, expected {self.VECTOR_SIZE}"
                        )

                logger.debug(
                    "collection_exists",
                    collection=self.collection_name,
                    points_count=collection_info.points_count,
                )
            else:
                # Create collection
                await client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qdrant_models.VectorParams(
                        size=self.VECTOR_SIZE,
                        distance=self.DISTANCE_METRIC,
                    ),
                )
                logger.info(
                    "collection_created",
                    collection=self.collection_name,
                    vector_size=self.VECTOR_SIZE,
                    distance=self.DISTANCE_METRIC.name,
                )

        except UnexpectedResponse as e:
            logger.error("qdrant_collection_error", error=str(e))
            raise

    async def _verify_cohere(self, client: cohere.AsyncClient) -> None:
        """Verify Cohere API connectivity with a test embedding."""
        try:
            response = await client.embed(
                texts=["test"],
                model=self.EMBEDDING_MODEL,
                input_type="search_query",
            )

            embeddings = list(response.embeddings) if response.embeddings else []
            if not embeddings or len(embeddings[0]) != self.VECTOR_SIZE:
                raise ValueError(
                    f"Unexpected embedding dimension: "
                    f"{len(embeddings[0]) if embeddings else 0}"
                )

            logger.debug("cohere_verified", model=self.EMBEDDING_MODEL)

        except cohere.CohereError as e:
            logger.error("cohere_verification_failed", error=str(e))
            raise

    # =========================================================================
    # Embedding Generation
    # =========================================================================

    def _get_cache_key(self, text: str, input_type: str) -> str:
        """Generate cache key for text embedding."""
        content = f"{input_type}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _clean_expired_cache(self) -> None:
        """Remove expired entries from embedding cache."""
        expired_keys = [
            key
            for key, entry in self._embedding_cache.items()
            if entry.is_expired(self.cache_ttl_seconds)
        ]
        for key in expired_keys:
            del self._embedding_cache[key]

        if expired_keys:
            logger.debug("cache_cleaned", removed_count=len(expired_keys))

    @retry(
        retry=retry_if_exception_type(
            (
                cohere.BadRequestError,
                cohere.InternalServerError,
                cohere.ServiceUnavailableError,
                cohere.TooManyRequestsError,
                TimeoutError,
            )
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _embed_text(
        self,
        text: str,
        input_type: str = "search_document",
    ) -> list[float]:
        """
        Generate embedding for text with caching and retries.

        Args:
            text: Text to embed
            input_type: Cohere input type ("search_document" or "search_query")

        Returns:
            Embedding vector (1024 dimensions)

        Raises:
            Exception: If embedding fails after retries
        """
        # Check cache first
        cache_key = self._get_cache_key(text, input_type)
        cached = self._embedding_cache.get(cache_key)

        if cached and not cached.is_expired(self.cache_ttl_seconds):
            logger.debug("embedding_cache_hit", cache_key=cache_key[:8])
            return cached.embedding

        # Generate embedding
        client = await self._get_cohere_client()

        # Truncate very long texts (Cohere has limits)
        truncated_text = text[:8000] if len(text) > 8000 else text

        response = await client.embed(
            texts=[truncated_text],
            model=self.EMBEDDING_MODEL,
            input_type=input_type,
        )

        embeddings_list = list(response.embeddings) if response.embeddings else []
        embedding: list[float] = [float(x) for x in embeddings_list[0]] if embeddings_list else []

        # Cache the embedding
        self._embedding_cache[cache_key] = CacheEntry(embedding=embedding)

        # Periodically clean expired cache entries
        if len(self._embedding_cache) > 1000:
            self._clean_expired_cache()

        logger.debug(
            "embedding_generated",
            text_length=len(text),
            input_type=input_type,
        )

        return embedding

    async def _embed_for_indexing(self, text: str) -> list[float]:
        """Generate embedding for indexing (adding to database)."""
        return await self._embed_text(text, input_type="search_document")

    async def _embed_for_search(self, text: str) -> list[float]:
        """Generate embedding for searching."""
        return await self._embed_text(text, input_type="search_query")

    # =========================================================================
    # Pattern Management
    # =========================================================================

    @staticmethod
    def _generate_pattern_id(text: str) -> str:
        """Generate deterministic ID for a spam pattern."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    async def add_spam_pattern(
        self,
        text: str,
        threat_type: str,
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Add a new spam pattern to the database.

        Args:
            text: Spam message text (minimum 10 characters)
            threat_type: Type of threat (crypto_scam, phishing, spam, etc.)
            source: Source of pattern (manual, auto, report)
            metadata: Additional metadata (language, tags, confidence, etc.)

        Returns:
            Pattern ID (hash-based, deterministic)

        Raises:
            ValueError: If text is too short
            RuntimeError: If service not initialized
        """
        if not self._initialized:
            raise RuntimeError("SpamDB not initialized. Call initialize() first.")

        if not text or len(text.strip()) < self.MIN_TEXT_LENGTH:
            raise ValueError(f"Text must be at least {self.MIN_TEXT_LENGTH} characters")

        text = text.strip()
        pattern_id = self._generate_pattern_id(text)

        try:
            # Generate embedding
            embedding = await self._embed_for_indexing(text)

            # Prepare payload
            now = datetime.now(UTC).isoformat()
            payload = {
                "text": text,
                "threat_type": threat_type,
                "source": source,
                "created_at": now,
                **(metadata or {}),
            }

            # Upsert to Qdrant (allows updating existing patterns)
            client = await self._get_qdrant_client()
            await client.upsert(
                collection_name=self.collection_name,
                points=[
                    qdrant_models.PointStruct(
                        id=pattern_id,
                        vector=embedding,
                        payload=payload,
                    )
                ],
            )

            logger.info(
                "spam_pattern_added",
                pattern_id=pattern_id,
                threat_type=threat_type,
                source=source,
                text_preview=text[:50],
            )

            return pattern_id

        except Exception as e:
            logger.error(
                "add_pattern_failed",
                error=str(e),
                threat_type=threat_type,
            )
            raise

    async def delete_pattern(self, pattern_id: str) -> bool:
        """
        Delete a spam pattern from the database.

        Args:
            pattern_id: Pattern ID to delete

        Returns:
            True if pattern was deleted, False if not found
        """
        if not self._initialized:
            raise RuntimeError("SpamDB not initialized. Call initialize() first.")

        try:
            client = await self._get_qdrant_client()

            # Delete by ID
            await client.delete(
                collection_name=self.collection_name,
                points_selector=qdrant_models.PointIdsList(
                    points=[pattern_id],
                ),
            )

            logger.info("spam_pattern_deleted", pattern_id=pattern_id)
            return True

        except UnexpectedResponse as e:
            if "not found" in str(e).lower():
                logger.warning("pattern_not_found", pattern_id=pattern_id)
                return False
            raise

    async def get_pattern(self, pattern_id: str) -> dict[str, Any] | None:
        """
        Retrieve a spam pattern by ID.

        Args:
            pattern_id: Pattern ID to retrieve

        Returns:
            Pattern payload dict or None if not found
        """
        if not self._initialized:
            raise RuntimeError("SpamDB not initialized. Call initialize() first.")

        try:
            client = await self._get_qdrant_client()

            results = await client.retrieve(
                collection_name=self.collection_name,
                ids=[pattern_id],
                with_payload=True,
            )

            if results:
                return dict(results[0].payload) if results[0].payload else None
            return None

        except Exception as e:
            logger.error("get_pattern_failed", pattern_id=pattern_id, error=str(e))
            return None

    # =========================================================================
    # Search and Matching
    # =========================================================================

    async def search_similar(
        self,
        text: str,
        threshold: float = 0.70,
        limit: int = 5,
    ) -> list[SpamMatch]:
        """
        Search for similar spam patterns.

        Args:
            text: Message text to search for
            threshold: Minimum similarity score (0.0 to 1.0)
            limit: Maximum number of results

        Returns:
            List of SpamMatch objects sorted by similarity (highest first)
        """
        if not self._initialized:
            logger.warning("spam_db_not_initialized")
            return []

        if not text or len(text.strip()) < self.MIN_TEXT_LENGTH:
            return []

        text = text.strip()

        try:
            # Generate query embedding
            embedding = await self._embed_for_search(text)

            # Search in Qdrant
            client = await self._get_qdrant_client()
            response = await client.query_points(
                collection_name=self.collection_name,
                query=embedding,
                limit=limit,
                score_threshold=threshold,
                with_payload=True,
            )
            results = response.points

            # Convert to SpamMatch objects
            matches = []
            for result in results:
                payload = result.payload or {}
                match = SpamMatch(
                    score=result.score,
                    text=payload.get("text", ""),
                    threat_type=payload.get("threat_type", "unknown"),
                    pattern_id=str(result.id),
                    source=payload.get("source", ""),
                    language=payload.get("language", ""),
                    created_at=payload.get("created_at", ""),
                )
                matches.append(match)

            logger.debug(
                "spam_search_completed",
                query_preview=text[:50],
                matches_found=len(matches),
                top_score=matches[0].score if matches else 0,
            )

            return matches

        except RetryError as e:
            logger.error("spam_search_retry_exhausted", error=str(e))
            return []
        except Exception as e:
            logger.error("spam_search_failed", error=str(e))
            return []

    async def check_spam(self, text: str) -> tuple[float, str | None]:
        """
        Check if text matches known spam patterns.

        This is the primary method for spam detection. Returns the highest
        similarity score and the matched pattern text.

        Args:
            text: Message text to check

        Returns:
            Tuple of (similarity_score, matched_pattern_text or None)
            Returns (0.0, None) on errors or no match
        """
        if not text or len(text.strip()) < self.MIN_TEXT_LENGTH:
            return 0.0, None

        try:
            matches = await self.search_similar(
                text=text,
                threshold=SIMILARITY_THRESHOLDS["low"],  # 0.70
                limit=1,
            )

            if matches:
                best_match = matches[0]
                logger.debug(
                    "spam_check_match",
                    similarity=best_match.score,
                    tier=best_match.tier,
                    risk_points=best_match.risk_points,
                    threat_type=best_match.threat_type,
                )
                return best_match.score, best_match.text

            return 0.0, None

        except Exception as e:
            logger.error("check_spam_failed", error=str(e))
            return 0.0, None

    async def check_spam_detailed(self, text: str) -> SpamMatch | None:
        """
        Check spam with detailed match information.

        Returns full SpamMatch object with risk points and tier info.

        Args:
            text: Message text to check

        Returns:
            SpamMatch object or None if no match
        """
        if not text or len(text.strip()) < self.MIN_TEXT_LENGTH:
            return None

        try:
            matches = await self.search_similar(
                text=text,
                threshold=SIMILARITY_THRESHOLDS["low"],
                limit=1,
            )

            return matches[0] if matches else None

        except Exception as e:
            logger.error("check_spam_detailed_failed", error=str(e))
            return None

    # =========================================================================
    # Utilities
    # =========================================================================

    async def get_collection_stats(self) -> dict[str, Any]:
        """
        Get statistics about the spam pattern collection.

        Returns:
            Dict with collection statistics
        """
        if not self._initialized:
            return {"error": "not_initialized"}

        try:
            client = await self._get_qdrant_client()
            info = await client.get_collection(self.collection_name)

            return {
                "collection_name": self.collection_name,
                "points_count": info.points_count,
                "indexed_vectors_count": info.indexed_vectors_count,
                "status": info.status.name if info.status else "unknown",
                "vector_size": self.VECTOR_SIZE,
                "cache_size": len(self._embedding_cache),
            }

        except Exception as e:
            logger.error("get_stats_failed", error=str(e))
            return {"error": str(e)}

    async def close(self) -> None:
        """
        Close all connections and cleanup resources.

        Should be called when shutting down the service.
        """
        try:
            if self._qdrant_client:
                await self._qdrant_client.close()
                self._qdrant_client = None

            if self._cohere_client:
                # Cohere client doesn't have explicit close
                self._cohere_client = None

            # Clear cache
            self._embedding_cache.clear()

            self._initialized = False
            logger.info("spam_db_closed")

        except Exception as e:
            logger.error("spam_db_close_failed", error=str(e))


# =============================================================================
# Alias for backwards compatibility
# =============================================================================

# The __init__.py expects SpamDBService
SpamDBService = SpamDB


# =============================================================================
# Cross-Group Detector
# =============================================================================


class CrossGroupDetector:
    """
    Detects duplicate messages across groups.

    Uses the spam database to find messages that appear
    in multiple groups, indicating coordinated spam.
    """

    def __init__(self, spam_db: SpamDB):
        """
        Initialize cross-group detector.

        Args:
            spam_db: SpamDB service instance
        """
        self.spam_db = spam_db

    async def check_duplicate(
        self,
        text: str,
        current_group_id: int,
    ) -> tuple[bool, int]:
        """
        Check if message appears in other groups.

        Args:
            text: Message text
            current_group_id: Current group ID (excluded from count)

        Returns:
            Tuple of (is_duplicate, duplicate_count)
        """
        # This requires a separate collection or payload filtering
        # to track messages by group. For now, return no duplicates.
        # Full implementation would search a "messages" collection
        # and filter by group_id != current_group_id

        logger.debug(
            "cross_group_check",
            text_preview=text[:30] if text else "",
            group_id=current_group_id,
        )

        return False, 0
