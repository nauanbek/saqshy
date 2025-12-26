"""
SAQSHY Cache Service

Redis-based caching and rate limiting for the anti-spam system.

This service implements:
- MessageHistoryProvider protocol for BehaviorAnalyzer integration
- Sliding window rate limiting with atomic operations
- Decision caching for repeated message patterns
- Channel subscription status caching

Key Schema:
    saqshy:msg_ts:{chat_id}:{user_id}         # Sorted set: message timestamps
    saqshy:user_stats:{chat_id}:{user_id}     # Hash: approved, flagged, blocked, total
    saqshy:first_msg:{chat_id}:{user_id}      # String: ISO timestamp
    saqshy:join_time:{chat_id}:{user_id}      # String: ISO timestamp
    saqshy:rate:{chat_id}:{user_id}           # String: rate limit counter
    saqshy:decision_cache:{message_hash}      # String: JSON decision
    saqshy:sub:{channel_id}:{user_id}         # String: "1" or "0"
    saqshy:admin:{chat_id}:{user_id}          # String: "1" or "0"

TTL Strategy:
    - Message timestamps: 24 hours (sliding window cleanup)
    - User stats: 30 days
    - First message time: 7 days
    - Join time: 7 days
    - Rate limit: Window size (60s or 3600s)
    - Decision cache: 5 minutes (configurable)
    - Subscription cache: 1 hour

Circuit Breaker:
    - Tracks consecutive failures
    - Opens after 5 failures in 60 seconds
    - Half-open after 30 seconds for retry
    - Logs warnings but never crashes handlers
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import redis.asyncio as redis
import structlog
from redis.asyncio.connection import ConnectionPool
from redis.exceptions import ConnectionError, RedisError, TimeoutError

logger = structlog.get_logger(__name__)


# =============================================================================
# TTL Constants (seconds)
# =============================================================================

TTL_MESSAGE_TIMESTAMPS = 86400  # 24 hours
TTL_USER_STATS = 86400 * 30  # 30 days
TTL_FIRST_MESSAGE = 86400 * 7  # 7 days
TTL_JOIN_TIME = 86400 * 7  # 7 days
TTL_DECISION_CACHE = 300  # 5 minutes
TTL_SUBSCRIPTION_CACHE = 3600  # 1 hour
TTL_ADMIN_CACHE = 300  # 5 minutes

# Maximum entries in sorted sets (prevents unbounded growth)
MAX_MESSAGE_ENTRIES = 1000


# =============================================================================
# Circuit Breaker
# =============================================================================


class CircuitState(Enum):
    """Circuit breaker state."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker for Redis connection resilience.

    Prevents cascading failures by tracking consecutive errors
    and temporarily stopping requests when the failure threshold is reached.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        failure_window: float = 60.0,
    ) -> None:
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures to open circuit.
            recovery_timeout: Seconds before attempting recovery.
            failure_window: Window in seconds to count failures.
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_window = failure_window

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._opened_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        return self._state == CircuitState.OPEN

    async def record_success(self) -> None:
        """Record a successful operation."""
        async with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                logger.info("circuit_breaker_closed", reason="successful_operation")

    async def record_failure(self) -> None:
        """Record a failed operation."""
        async with self._lock:
            now = time.monotonic()

            # Reset if outside failure window
            if now - self._last_failure_time > self.failure_window:
                self._failure_count = 0

            self._failure_count += 1
            self._last_failure_time = now

            if self._state == CircuitState.HALF_OPEN:
                # Failed during recovery attempt
                self._state = CircuitState.OPEN
                self._opened_at = now
                logger.warning(
                    "circuit_breaker_reopened",
                    reason="failed_during_recovery",
                )
            elif (
                self._state == CircuitState.CLOSED and self._failure_count >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = now
                logger.warning(
                    "circuit_breaker_opened",
                    failure_count=self._failure_count,
                    threshold=self.failure_threshold,
                )

    async def allow_request(self) -> bool:
        """
        Check if a request should be allowed.

        Returns:
            True if request should proceed, False if circuit is open.
        """
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                now = time.monotonic()
                if now - self._opened_at >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    logger.info("circuit_breaker_half_open", reason="recovery_timeout")
                    return True
                return False

            # HALF_OPEN: allow one request for testing
            return True


# =============================================================================
# CacheService
# =============================================================================


class CacheService:
    """
    Redis-based caching and rate limiting service.

    Implements the MessageHistoryProvider protocol for integration
    with BehaviorAnalyzer. Provides atomic rate limiting, decision
    caching, and subscription status caching.

    Thread Safety:
        This class is thread-safe when used with asyncio.
        Redis operations are atomic or use pipelines/Lua scripts.

    Error Handling:
        All methods fail safely with default values on Redis errors.
        A circuit breaker prevents cascading failures.

    Connection Management:
        Call connect() before use and close() on shutdown.
        Auto-reconnect is handled by redis.asyncio.

    Example:
        >>> cache = CacheService("redis://localhost:6379")
        >>> await cache.connect()
        >>> count = await cache.get_user_message_count(user_id, chat_id, 3600)
        >>> await cache.close()
    """

    # Key prefixes for namespacing
    PREFIX = "saqshy"
    KEY_MSG_TIMESTAMPS = f"{PREFIX}:msg_ts"
    KEY_USER_STATS = f"{PREFIX}:user_stats"
    KEY_FIRST_MSG = f"{PREFIX}:first_msg"
    KEY_JOIN_TIME = f"{PREFIX}:join_time"
    KEY_RATE = f"{PREFIX}:rate"
    KEY_DECISION = f"{PREFIX}:decision_cache"
    KEY_SUBSCRIPTION = f"{PREFIX}:sub"
    KEY_ADMIN = f"{PREFIX}:admin"

    def __init__(
        self,
        redis_url: str,
        default_ttl: int = 300,
        pool_size: int = 10,
    ) -> None:
        """
        Initialize cache service.

        Args:
            redis_url: Redis connection URL (e.g., "redis://localhost:6379").
            default_ttl: Default TTL in seconds for generic cache operations.
            pool_size: Maximum connections in the pool.
        """
        self.redis_url = redis_url
        self.default_ttl = default_ttl
        self.pool_size = pool_size

        self._client: redis.Redis | None = None
        self._pool: ConnectionPool | None = None
        self._circuit_breaker = CircuitBreaker()
        self._connected = False

    # =========================================================================
    # Connection Management
    # =========================================================================

    async def connect(self) -> None:
        """
        Initialize connection pool and connect to Redis.

        Should be called once during application startup.
        """
        if self._connected:
            return

        try:
            self._pool = ConnectionPool.from_url(
                self.redis_url,
                max_connections=self.pool_size,
                decode_responses=True,
                socket_connect_timeout=5.0,
                socket_timeout=5.0,
                retry_on_timeout=True,
            )
            self._client = redis.Redis(connection_pool=self._pool)

            # Test connection
            await self._client.ping()
            self._connected = True
            logger.info(
                "redis_connected",
                url=self._sanitize_url(self.redis_url),
                pool_size=self.pool_size,
            )

        except (ConnectionError, TimeoutError) as e:
            logger.error("redis_connection_failed", error=str(e))
            # Don't raise - allow graceful degradation
            self._connected = False

    async def close(self) -> None:
        """
        Close Redis connections.

        Should be called during application shutdown.
        """
        if self._client:
            await self._client.aclose()
            self._client = None

        if self._pool:
            await self._pool.disconnect()
            self._pool = None

        self._connected = False
        logger.info("redis_disconnected")

    def _sanitize_url(self, url: str) -> str:
        """Remove password from URL for logging."""
        if "@" in url:
            # Format: redis://user:pass@host:port
            parts = url.split("@")
            return f"redis://***@{parts[-1]}"
        return url

    async def _execute(
        self,
        operation: str,
        *args: Any,
        default: Any = None,
        **kwargs: Any,
    ) -> Any:
        """
        Execute Redis operation with error handling and circuit breaker.

        Args:
            operation: Redis command name.
            *args: Command arguments.
            default: Value to return on failure.
            **kwargs: Command keyword arguments.

        Returns:
            Command result or default value on failure.
        """
        if not self._client or not self._connected:
            logger.debug("redis_not_connected", operation=operation)
            return default

        if not await self._circuit_breaker.allow_request():
            logger.debug("circuit_breaker_blocked", operation=operation)
            return default

        try:
            cmd = getattr(self._client, operation)
            result = await cmd(*args, **kwargs)
            await self._circuit_breaker.record_success()
            return result

        except (ConnectionError, TimeoutError, RedisError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "redis_operation_failed",
                operation=operation,
                error=str(e),
            )
            return default

    # =========================================================================
    # Generic Cache Operations
    # =========================================================================

    async def get(self, key: str) -> str | None:
        """
        Get a value from cache.

        Args:
            key: Cache key.

        Returns:
            Cached value or None.
        """
        return await self._execute("get", key, default=None)

    async def set(
        self,
        key: str,
        value: str,
        ttl: int | None = None,
    ) -> bool:
        """
        Set a value in cache.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Time-to-live in seconds.

        Returns:
            True if successful.
        """
        ttl = ttl or self.default_ttl
        result = await self._execute("set", key, value, ex=ttl, default=False)
        return result is not False

    async def delete(self, key: str) -> bool:
        """
        Delete a value from cache.

        Args:
            key: Cache key.

        Returns:
            True if key was deleted.
        """
        result = await self._execute("delete", key, default=0)
        return result > 0 if result else False

    async def exists(self, key: str) -> bool:
        """
        Check if key exists in cache.

        Args:
            key: Cache key.

        Returns:
            True if key exists.
        """
        result = await self._execute("exists", key, default=0)
        return result > 0 if result else False

    async def get_json(self, key: str) -> dict[str, Any] | None:
        """
        Get a JSON value from cache.

        Args:
            key: Cache key.

        Returns:
            Parsed JSON or None.
        """
        value = await self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                logger.warning("invalid_json_in_cache", key=key)
                return None
        return None

    async def set_json(
        self,
        key: str,
        value: dict[str, Any],
        ttl: int | None = None,
    ) -> bool:
        """
        Set a JSON value in cache.

        Args:
            key: Cache key.
            value: Dict to cache.
            ttl: Time-to-live in seconds.

        Returns:
            True if successful.
        """
        try:
            json_str = json.dumps(value, default=str)
            return await self.set(key, json_str, ttl)
        except (TypeError, ValueError) as e:
            logger.warning("json_serialization_failed", error=str(e))
            return False

    # =========================================================================
    # MessageHistoryProvider Implementation
    # =========================================================================

    async def get_user_message_count(
        self,
        user_id: int,
        chat_id: int,
        window_seconds: int,
    ) -> int:
        """
        Get count of user messages in the specified time window.

        Uses a sorted set with timestamps as scores for O(log N) lookups.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            window_seconds: Time window in seconds.

        Returns:
            Number of messages in the time window.
        """
        if not self._client or not self._connected:
            return 0

        if not await self._circuit_breaker.allow_request():
            return 0

        key = f"{self.KEY_MSG_TIMESTAMPS}:{chat_id}:{user_id}"
        now = time.time()
        min_score = now - window_seconds

        try:
            # Count entries within the time window
            count = await self._client.zcount(key, min_score, "+inf")
            await self._circuit_breaker.record_success()
            return int(count) if count else 0

        except (ConnectionError, TimeoutError, RedisError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "failed_get_message_count",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )
            return 0

    async def get_user_stats(
        self,
        user_id: int,
        chat_id: int,
    ) -> dict[str, int]:
        """
        Get user's message statistics in the group.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            Dict with keys: total_messages, approved, flagged, blocked.
        """
        default_stats = {
            "total_messages": 0,
            "approved": 0,
            "flagged": 0,
            "blocked": 0,
        }

        if not self._client or not self._connected:
            return default_stats

        if not await self._circuit_breaker.allow_request():
            return default_stats

        key = f"{self.KEY_USER_STATS}:{chat_id}:{user_id}"

        try:
            stats = await self._client.hgetall(key)
            await self._circuit_breaker.record_success()

            if not stats:
                return default_stats

            return {
                "total_messages": int(stats.get("total_messages", 0)),
                "approved": int(stats.get("approved", 0)),
                "flagged": int(stats.get("flagged", 0)),
                "blocked": int(stats.get("blocked", 0)),
            }

        except (ConnectionError, TimeoutError, RedisError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "failed_get_user_stats",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )
            return default_stats

    async def get_first_message_time(
        self,
        user_id: int,
        chat_id: int,
    ) -> datetime | None:
        """
        Get timestamp of user's first message in the group.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            Datetime of first message, or None if not recorded.
        """
        key = f"{self.KEY_FIRST_MSG}:{chat_id}:{user_id}"
        value = await self._execute("get", key, default=None)

        if value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                logger.warning(
                    "invalid_first_message_timestamp",
                    key=key,
                    value=value,
                )
        return None

    async def get_join_time(
        self,
        user_id: int,
        chat_id: int,
    ) -> datetime | None:
        """
        Get timestamp when user joined the group.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            Datetime of join event, or None if not recorded.
        """
        key = f"{self.KEY_JOIN_TIME}:{chat_id}:{user_id}"
        value = await self._execute("get", key, default=None)

        if value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                logger.warning(
                    "invalid_join_timestamp",
                    key=key,
                    value=value,
                )
        return None

    # =========================================================================
    # Recording Methods
    # =========================================================================

    async def record_message(
        self,
        user_id: int,
        chat_id: int,
        timestamp: datetime,
    ) -> None:
        """
        Record a message timestamp for sliding window counting.

        Atomically adds timestamp to sorted set and cleans old entries.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            timestamp: Message timestamp.
        """
        if not self._client or not self._connected:
            return

        if not await self._circuit_breaker.allow_request():
            return

        key = f"{self.KEY_MSG_TIMESTAMPS}:{chat_id}:{user_id}"
        first_msg_key = f"{self.KEY_FIRST_MSG}:{chat_id}:{user_id}"
        stats_key = f"{self.KEY_USER_STATS}:{chat_id}:{user_id}"

        ts = timestamp.timestamp() if isinstance(timestamp, datetime) else timestamp
        ts_iso = (
            timestamp.isoformat()
            if isinstance(timestamp, datetime)
            else datetime.fromtimestamp(ts, tz=UTC).isoformat()
        )

        try:
            async with self._client.pipeline(transaction=True) as pipe:
                # Add timestamp to sorted set (score = timestamp)
                pipe.zadd(key, {str(ts): ts})

                # Remove entries older than 24 hours
                cutoff = ts - TTL_MESSAGE_TIMESTAMPS
                pipe.zremrangebyscore(key, "-inf", cutoff)

                # Prevent unbounded growth by keeping only recent entries
                pipe.zremrangebyrank(key, 0, -MAX_MESSAGE_ENTRIES - 1)

                # Set TTL on the sorted set
                pipe.expire(key, TTL_MESSAGE_TIMESTAMPS)

                # Set first message time if not exists
                pipe.setnx(first_msg_key, ts_iso)
                pipe.expire(first_msg_key, TTL_FIRST_MESSAGE)

                # Increment total message count
                pipe.hincrby(stats_key, "total_messages", 1)
                pipe.expire(stats_key, TTL_USER_STATS)

                await pipe.execute()

            await self._circuit_breaker.record_success()

        except (ConnectionError, TimeoutError, RedisError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "failed_record_message",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )

    async def record_decision(
        self,
        user_id: int,
        chat_id: int,
        verdict: str,
    ) -> None:
        """
        Record a decision verdict for user stats.

        Increments the appropriate counter (approved, flagged, blocked).

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            verdict: Decision verdict (allow, watch, limit, review, block).
        """
        if not self._client or not self._connected:
            return

        if not await self._circuit_breaker.allow_request():
            return

        key = f"{self.KEY_USER_STATS}:{chat_id}:{user_id}"

        # Map verdicts to stat fields
        verdict_lower = verdict.lower()
        if verdict_lower in ("allow", "watch"):
            field = "approved"
        elif verdict_lower in ("limit", "review"):
            field = "flagged"
        elif verdict_lower == "block":
            field = "blocked"
        else:
            logger.debug("unknown_verdict", verdict=verdict)
            return

        try:
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.hincrby(key, field, 1)
                pipe.expire(key, TTL_USER_STATS)
                await pipe.execute()

            await self._circuit_breaker.record_success()

        except (ConnectionError, TimeoutError, RedisError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "failed_record_decision",
                user_id=user_id,
                chat_id=chat_id,
                verdict=verdict,
                error=str(e),
            )

    async def record_join(
        self,
        user_id: int,
        chat_id: int,
        timestamp: datetime,
    ) -> None:
        """
        Record user join timestamp.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            timestamp: Join timestamp.
        """
        key = f"{self.KEY_JOIN_TIME}:{chat_id}:{user_id}"
        ts_iso = timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp)

        await self._execute(
            "set",
            key,
            ts_iso,
            ex=TTL_JOIN_TIME,
            default=None,
        )

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    async def check_rate_limit(
        self,
        user_id: int,
        chat_id: int,
        limit: int,
        window_seconds: int,
    ) -> bool:
        """
        Check if user has exceeded rate limit.

        Uses sliding window counter pattern for accurate rate limiting.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            limit: Maximum allowed requests in window.
            window_seconds: Time window in seconds.

        Returns:
            True if within limit, False if rate limited.
        """
        if not self._client or not self._connected:
            # Fail open - allow request if Redis is unavailable
            return True

        if not await self._circuit_breaker.allow_request():
            return True

        key = f"{self.KEY_RATE}:{chat_id}:{user_id}:{window_seconds}"
        now = time.time()
        window_start = now - window_seconds

        try:
            async with self._client.pipeline(transaction=True) as pipe:
                # Remove old entries
                pipe.zremrangebyscore(key, "-inf", window_start)
                # Count current entries
                pipe.zcard(key)
                results = await pipe.execute()

            count = results[1] if results else 0
            await self._circuit_breaker.record_success()

            return count < limit

        except (ConnectionError, TimeoutError, RedisError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "rate_limit_check_failed",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )
            # Fail open
            return True

    async def increment_rate(
        self,
        user_id: int,
        chat_id: int,
        window_seconds: int,
    ) -> int:
        """
        Increment rate limit counter.

        Atomically adds entry and cleans old entries.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            window_seconds: Time window in seconds.

        Returns:
            New counter value.
        """
        if not self._client or not self._connected:
            return 0

        if not await self._circuit_breaker.allow_request():
            return 0

        key = f"{self.KEY_RATE}:{chat_id}:{user_id}:{window_seconds}"
        now = time.time()
        window_start = now - window_seconds

        try:
            async with self._client.pipeline(transaction=True) as pipe:
                # Add current timestamp
                pipe.zadd(key, {str(now): now})
                # Remove old entries
                pipe.zremrangebyscore(key, "-inf", window_start)
                # Get count
                pipe.zcard(key)
                # Set TTL
                pipe.expire(key, window_seconds)
                results = await pipe.execute()

            count = results[2] if len(results) > 2 else 0
            await self._circuit_breaker.record_success()
            return int(count)

        except (ConnectionError, TimeoutError, RedisError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "rate_limit_increment_failed",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )
            return 0

    # =========================================================================
    # Decision Caching
    # =========================================================================

    async def get_cached_decision(
        self,
        message_hash: str,
    ) -> dict[str, Any] | None:
        """
        Get cached risk decision for a message hash.

        Args:
            message_hash: Hash of message content.

        Returns:
            Cached decision dict or None.
        """
        key = f"{self.KEY_DECISION}:{message_hash}"
        return await self.get_json(key)

    async def cache_decision(
        self,
        message_hash: str,
        decision: dict[str, Any],
        ttl_seconds: int = TTL_DECISION_CACHE,
    ) -> None:
        """
        Cache a risk decision.

        Args:
            message_hash: Hash of message content.
            decision: Decision data to cache.
            ttl_seconds: TTL in seconds (default 5 minutes).
        """
        key = f"{self.KEY_DECISION}:{message_hash}"
        await self.set_json(key, decision, ttl=ttl_seconds)

    # =========================================================================
    # Channel Subscription Caching
    # =========================================================================

    async def get_subscription_status(
        self,
        user_id: int,
        channel_id: int,
    ) -> bool | None:
        """
        Get cached channel subscription status.

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.

        Returns:
            True/False or None if not cached.
        """
        key = f"{self.KEY_SUBSCRIPTION}:{channel_id}:{user_id}"
        value = await self._execute("get", key, default=None)

        if value is not None:
            return value == "1"
        return None

    async def cache_subscription_status(
        self,
        user_id: int,
        channel_id: int,
        is_subscribed: bool,
        ttl_seconds: int = TTL_SUBSCRIPTION_CACHE,
    ) -> None:
        """
        Cache channel subscription status.

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.
            is_subscribed: Whether user is subscribed.
            ttl_seconds: TTL in seconds (default 1 hour).
        """
        key = f"{self.KEY_SUBSCRIPTION}:{channel_id}:{user_id}"
        await self._execute(
            "set",
            key,
            "1" if is_subscribed else "0",
            ex=ttl_seconds,
            default=None,
        )

    # =========================================================================
    # Admin Status Caching
    # =========================================================================

    async def cache_admin_status(
        self,
        user_id: int,
        chat_id: int,
        is_admin: bool,
    ) -> None:
        """
        Cache user's admin status in a group.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            is_admin: Whether user is admin.
        """
        key = f"{self.KEY_ADMIN}:{chat_id}:{user_id}"
        await self._execute(
            "set",
            key,
            "1" if is_admin else "0",
            ex=TTL_ADMIN_CACHE,
            default=None,
        )

    async def get_admin_status(
        self,
        user_id: int,
        chat_id: int,
    ) -> bool | None:
        """
        Get cached admin status.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            True/False or None if not cached.
        """
        key = f"{self.KEY_ADMIN}:{chat_id}:{user_id}"
        value = await self._execute("get", key, default=None)

        if value is not None:
            return value == "1"
        return None

    # =========================================================================
    # Utility Methods
    # =========================================================================

    async def ping(self) -> bool:
        """
        Check Redis connectivity.

        Returns:
            True if Redis is reachable.
        """
        if not self._client:
            return False

        try:
            result = await self._client.ping()
            return result is True
        except (ConnectionError, TimeoutError, RedisError):
            return False

    async def flush_user_data(
        self,
        user_id: int,
        chat_id: int,
    ) -> None:
        """
        Remove all cached data for a user in a chat.

        Useful for GDPR compliance or user data cleanup.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
        """
        if not self._client or not self._connected:
            return

        keys = [
            f"{self.KEY_MSG_TIMESTAMPS}:{chat_id}:{user_id}",
            f"{self.KEY_USER_STATS}:{chat_id}:{user_id}",
            f"{self.KEY_FIRST_MSG}:{chat_id}:{user_id}",
            f"{self.KEY_JOIN_TIME}:{chat_id}:{user_id}",
            f"{self.KEY_ADMIN}:{chat_id}:{user_id}",
        ]

        # Also clean rate limit keys for common windows
        for window in [60, 3600]:
            keys.append(f"{self.KEY_RATE}:{chat_id}:{user_id}:{window}")

        try:
            await self._client.delete(*keys)
            logger.info(
                "user_data_flushed",
                user_id=user_id,
                chat_id=chat_id,
                keys_deleted=len(keys),
            )
        except (ConnectionError, TimeoutError, RedisError) as e:
            logger.warning(
                "flush_user_data_failed",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )

    async def get_stats(self) -> dict[str, Any]:
        """
        Get cache service statistics.

        Returns:
            Dict with connection and circuit breaker stats.
        """
        return {
            "connected": self._connected,
            "circuit_state": self._circuit_breaker.state.value,
            "redis_url": self._sanitize_url(self.redis_url),
        }
