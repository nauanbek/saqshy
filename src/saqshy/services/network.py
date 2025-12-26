"""
SAQSHY Network Analysis Service

Redis-based tracking for cross-group behavior analysis and network signals.

This service implements:
- Cross-group duplicate message detection
- User reputation tracking across all SAQSHY-protected groups
- Ban history tracking
- Global blocklist/whitelist management

Key Schema:
    saqshy:net:msg:{message_hash}              # SET of group_ids where message was seen
    saqshy:net:user:{user_id}:groups           # SET of group_ids user is active in
    saqshy:net:user:{user_id}:bans             # SET of group_ids user was banned from
    saqshy:net:user:{user_id}:flags            # SET of group_ids user was flagged in
    saqshy:net:user:{user_id}:reputation       # HASH {score, last_updated, groups_count}
    saqshy:net:blocklist                       # SET of blocked user_ids (global)
    saqshy:net:whitelist                       # SET of whitelisted user_ids (global)

TTL Strategy:
    - Message hashes: 24 hours (detect same-day coordinated spam)
    - User groups: 7 days (sliding window)
    - Ban history: 30 days
    - Flag history: 14 days
    - Reputation: 30 days
    - Blocklist/Whitelist: No TTL (persistent)

Atomic Operations:
    - Uses pipelines for multi-step operations
    - SADD with EXPIRE for bounded set growth
    - SCARD for counting without fetching all members
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import redis.asyncio
import structlog

if TYPE_CHECKING:
    from saqshy.services.cache import CacheService

from saqshy.core.types import NetworkSignals

logger = structlog.get_logger(__name__)


# =============================================================================
# TTL Constants (seconds)
# =============================================================================

TTL_MESSAGE_HASH = 86400  # 24 hours - detect same-day spam campaigns
TTL_USER_GROUPS = 86400 * 7  # 7 days - recent group activity
TTL_BAN_HISTORY = 86400 * 30  # 30 days - ban history
TTL_FLAG_HISTORY = 86400 * 14  # 14 days - flag history
TTL_REPUTATION = 86400 * 30  # 30 days - reputation score

# Maximum entries to prevent unbounded growth
MAX_GROUPS_PER_MESSAGE = 100  # Max groups a message can appear in
MAX_GROUPS_PER_USER = 500  # Max groups to track per user


# =============================================================================
# NetworkAnalyzer Service
# =============================================================================


class NetworkAnalyzer:
    """
    Redis-based network analysis for cross-group spam detection.

    Tracks user behavior across multiple SAQSHY-protected groups to detect
    coordinated spam attacks. Provides signals for:
    - Duplicate messages posted to multiple groups
    - Users banned/flagged in other groups
    - Global blocklist/whitelist status
    - Cross-group reputation scoring

    Thread Safety:
        This class is thread-safe when used with asyncio.
        Redis operations are atomic or use pipelines.

    Error Handling:
        All methods fail safely with default values on Redis errors.
        Uses the CacheService's circuit breaker for connection resilience.

    Example:
        >>> network = NetworkAnalyzer(cache_service)
        >>> signals = await network.analyze(
        ...     user_id=123456,
        ...     chat_id=-100123,
        ...     text="Buy crypto now!",
        ... )
        >>> print(signals.duplicate_messages_in_other_groups)
    """

    # Key prefixes
    PREFIX = "saqshy:net"
    KEY_MESSAGE = f"{PREFIX}:msg"
    KEY_USER = f"{PREFIX}:user"
    KEY_BLOCKLIST = f"{PREFIX}:blocklist"
    KEY_WHITELIST = f"{PREFIX}:whitelist"

    def __init__(self, cache_service: CacheService) -> None:
        """
        Initialize NetworkAnalyzer.

        Args:
            cache_service: Connected CacheService instance for Redis access.
        """
        self.cache = cache_service
        self._connected = False

    @property
    def _client(self):
        """Get Redis client from cache service."""
        return self.cache._client

    @property
    def _circuit_breaker(self):
        """Get circuit breaker from cache service."""
        return self.cache._circuit_breaker

    def _is_available(self) -> bool:
        """Check if Redis is available for operations."""
        return self.cache._connected and self.cache._client is not None

    # =========================================================================
    # Message Hash Generation
    # =========================================================================

    @staticmethod
    def hash_message(text: str) -> str:
        """
        Generate hash for message content.

        Uses SHA-256 truncated to 16 characters for compact storage
        while maintaining collision resistance for practical use.

        Args:
            text: Message text to hash.

        Returns:
            16-character hex hash of normalized text.
        """
        if not text:
            return ""

        # Normalize: lowercase, strip whitespace, collapse multiple spaces
        normalized = " ".join(text.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    # =========================================================================
    # Cross-Group Duplicate Detection
    # =========================================================================

    async def record_message(
        self,
        message_hash: str,
        chat_id: int,
        user_id: int,
    ) -> int:
        """
        Record message occurrence in a group.

        Atomically adds group to the set of groups where this message hash
        has been seen, and updates user's active groups.

        Args:
            message_hash: Hash of the message content.
            chat_id: Telegram chat ID.
            user_id: Telegram user ID.

        Returns:
            Number of OTHER groups where this message was seen (excludes current).
        """
        if not self._is_available() or not message_hash:
            return 0

        if not await self._circuit_breaker.allow_request():
            return 0

        msg_key = f"{self.KEY_MESSAGE}:{message_hash}"
        user_groups_key = f"{self.KEY_USER}:{user_id}:groups"
        chat_id_str = str(chat_id)

        try:
            async with self._client.pipeline(transaction=True) as pipe:
                # Add this group to message's group set
                pipe.sadd(msg_key, chat_id_str)
                pipe.expire(msg_key, TTL_MESSAGE_HASH)

                # Get count of groups BEFORE adding (to get "other groups" count)
                # We'll calculate this after the pipeline
                pipe.scard(msg_key)

                # Track user's active groups
                pipe.sadd(user_groups_key, chat_id_str)
                pipe.expire(user_groups_key, TTL_USER_GROUPS)

                results = await pipe.execute()

            await self._circuit_breaker.record_success()

            # results[2] is scard (total groups including current)
            total_groups = results[2] if len(results) > 2 else 0
            # Subtract 1 for current group (if it was just added, sadd returns 1)
            other_groups = max(0, total_groups - 1)

            if other_groups > 0:
                logger.info(
                    "duplicate_message_detected",
                    message_hash=message_hash,
                    user_id=user_id,
                    chat_id=chat_id,
                    other_groups_count=other_groups,
                )

            return other_groups

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "record_message_failed",
                message_hash=message_hash,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return 0

    async def get_message_group_count(self, message_hash: str) -> int:
        """
        Get count of groups where message was seen.

        Args:
            message_hash: Hash of the message content.

        Returns:
            Number of unique groups.
        """
        if not self._is_available() or not message_hash:
            return 0

        if not await self._circuit_breaker.allow_request():
            return 0

        msg_key = f"{self.KEY_MESSAGE}:{message_hash}"

        try:
            count = await self._client.scard(msg_key)
            await self._circuit_breaker.record_success()
            return int(count) if count else 0

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "get_message_group_count_failed",
                message_hash=message_hash,
                error=str(e),
                error_type=type(e).__name__,
            )
            return 0

    # =========================================================================
    # Ban and Flag Tracking
    # =========================================================================

    async def record_ban(self, user_id: int, chat_id: int) -> None:
        """
        Record user ban in a group.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
        """
        if not self._is_available():
            return

        if not await self._circuit_breaker.allow_request():
            return

        bans_key = f"{self.KEY_USER}:{user_id}:bans"
        chat_id_str = str(chat_id)

        try:
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.sadd(bans_key, chat_id_str)
                pipe.expire(bans_key, TTL_BAN_HISTORY)
                await pipe.execute()

            await self._circuit_breaker.record_success()

            logger.info(
                "ban_recorded",
                user_id=user_id,
                chat_id=chat_id,
            )

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "record_ban_failed",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    async def record_flag(self, user_id: int, chat_id: int) -> None:
        """
        Record user flag (suspicious activity) in a group.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
        """
        if not self._is_available():
            return

        if not await self._circuit_breaker.allow_request():
            return

        flags_key = f"{self.KEY_USER}:{user_id}:flags"
        chat_id_str = str(chat_id)

        try:
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.sadd(flags_key, chat_id_str)
                pipe.expire(flags_key, TTL_FLAG_HISTORY)
                await pipe.execute()

            await self._circuit_breaker.record_success()

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "record_flag_failed",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    async def get_ban_count(self, user_id: int) -> int:
        """
        Get count of groups where user was banned.

        Args:
            user_id: Telegram user ID.

        Returns:
            Number of groups where user was banned.
        """
        if not self._is_available():
            return 0

        if not await self._circuit_breaker.allow_request():
            return 0

        bans_key = f"{self.KEY_USER}:{user_id}:bans"

        try:
            count = await self._client.scard(bans_key)
            await self._circuit_breaker.record_success()
            return int(count) if count else 0

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "get_ban_count_failed",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return 0

    async def get_flag_count(self, user_id: int) -> int:
        """
        Get count of groups where user was flagged.

        Args:
            user_id: Telegram user ID.

        Returns:
            Number of groups where user was flagged.
        """
        if not self._is_available():
            return 0

        if not await self._circuit_breaker.allow_request():
            return 0

        flags_key = f"{self.KEY_USER}:{user_id}:flags"

        try:
            count = await self._client.scard(flags_key)
            await self._circuit_breaker.record_success()
            return int(count) if count else 0

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "get_flag_count_failed",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return 0

    async def get_groups_in_common(self, user_id: int) -> int:
        """
        Get count of SAQSHY-protected groups user is active in.

        Args:
            user_id: Telegram user ID.

        Returns:
            Number of groups.
        """
        if not self._is_available():
            return 0

        if not await self._circuit_breaker.allow_request():
            return 0

        groups_key = f"{self.KEY_USER}:{user_id}:groups"

        try:
            count = await self._client.scard(groups_key)
            await self._circuit_breaker.record_success()
            return int(count) if count else 0

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "get_groups_in_common_failed",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return 0

    # =========================================================================
    # Global Blocklist/Whitelist
    # =========================================================================

    async def add_to_blocklist(self, user_id: int) -> bool:
        """
        Add user to global blocklist.

        Args:
            user_id: Telegram user ID.

        Returns:
            True if added (was not already in list).
        """
        if not self._is_available():
            return False

        if not await self._circuit_breaker.allow_request():
            return False

        try:
            result = await self._client.sadd(self.KEY_BLOCKLIST, str(user_id))
            await self._circuit_breaker.record_success()

            if result:
                logger.info("user_blocklisted", user_id=user_id)

            return result > 0 if result else False

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "add_to_blocklist_failed",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def remove_from_blocklist(self, user_id: int) -> bool:
        """
        Remove user from global blocklist.

        Args:
            user_id: Telegram user ID.

        Returns:
            True if removed (was in list).
        """
        if not self._is_available():
            return False

        if not await self._circuit_breaker.allow_request():
            return False

        try:
            result = await self._client.srem(self.KEY_BLOCKLIST, str(user_id))
            await self._circuit_breaker.record_success()

            if result:
                logger.info("user_unblocklisted", user_id=user_id)

            return result > 0 if result else False

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "remove_from_blocklist_failed",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def is_blocklisted(self, user_id: int) -> bool:
        """
        Check if user is in global blocklist.

        Args:
            user_id: Telegram user ID.

        Returns:
            True if blocklisted.
        """
        if not self._is_available():
            return False

        if not await self._circuit_breaker.allow_request():
            return False

        try:
            result = await self._client.sismember(self.KEY_BLOCKLIST, str(user_id))
            await self._circuit_breaker.record_success()
            return bool(result)

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "is_blocklisted_failed",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def add_to_whitelist(self, user_id: int) -> bool:
        """
        Add user to global whitelist.

        Args:
            user_id: Telegram user ID.

        Returns:
            True if added (was not already in list).
        """
        if not self._is_available():
            return False

        if not await self._circuit_breaker.allow_request():
            return False

        try:
            result = await self._client.sadd(self.KEY_WHITELIST, str(user_id))
            await self._circuit_breaker.record_success()

            if result:
                logger.info("user_whitelisted", user_id=user_id)

            return result > 0 if result else False

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "add_to_whitelist_failed",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def remove_from_whitelist(self, user_id: int) -> bool:
        """
        Remove user from global whitelist.

        Args:
            user_id: Telegram user ID.

        Returns:
            True if removed (was in list).
        """
        if not self._is_available():
            return False

        if not await self._circuit_breaker.allow_request():
            return False

        try:
            result = await self._client.srem(self.KEY_WHITELIST, str(user_id))
            await self._circuit_breaker.record_success()

            if result:
                logger.info("user_unwhitelisted", user_id=user_id)

            return result > 0 if result else False

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "remove_from_whitelist_failed",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def is_whitelisted(self, user_id: int) -> bool:
        """
        Check if user is in global whitelist.

        Args:
            user_id: Telegram user ID.

        Returns:
            True if whitelisted.
        """
        if not self._is_available():
            return False

        if not await self._circuit_breaker.allow_request():
            return False

        try:
            result = await self._client.sismember(self.KEY_WHITELIST, str(user_id))
            await self._circuit_breaker.record_success()
            return bool(result)

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            await self._circuit_breaker.record_failure()
            logger.warning(
                "is_whitelisted_failed",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    # =========================================================================
    # Main Analysis Method
    # =========================================================================

    async def analyze(
        self,
        user_id: int,
        chat_id: int,
        text: str | None = None,
        spam_db_similarity: float = 0.0,
        spam_db_matched_pattern: str | None = None,
    ) -> NetworkSignals:
        """
        Perform full network analysis for a message.

        Analyzes cross-group behavior, checks blocklist/whitelist,
        and records the message for future detection.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            text: Message text (for duplicate detection).
            spam_db_similarity: Similarity score from spam database.
            spam_db_matched_pattern: Matched pattern from spam database.

        Returns:
            NetworkSignals with all network-based risk indicators.
        """
        if not self._is_available():
            logger.debug("network_analyzer_unavailable")
            return NetworkSignals(
                spam_db_similarity=spam_db_similarity,
                spam_db_matched_pattern=spam_db_matched_pattern,
            )

        # Check blocklist/whitelist first (fast path)
        is_blocklisted = await self.is_blocklisted(user_id)
        if is_blocklisted:
            logger.info(
                "blocklisted_user_detected",
                user_id=user_id,
                chat_id=chat_id,
            )
            return NetworkSignals(
                is_in_global_blocklist=True,
                spam_db_similarity=spam_db_similarity,
                spam_db_matched_pattern=spam_db_matched_pattern,
            )

        is_whitelisted = await self.is_whitelisted(user_id)

        # Get cross-group statistics
        groups_in_common = await self.get_groups_in_common(user_id)
        flagged_count = await self.get_flag_count(user_id)
        banned_count = await self.get_ban_count(user_id)

        # Check for duplicate messages across groups
        duplicate_count = 0
        if text:
            message_hash = self.hash_message(text)
            if message_hash:
                # Record and get count of other groups
                duplicate_count = await self.record_message(
                    message_hash=message_hash,
                    chat_id=chat_id,
                    user_id=user_id,
                )

        return NetworkSignals(
            groups_in_common=groups_in_common,
            duplicate_messages_in_other_groups=duplicate_count,
            flagged_in_other_groups=flagged_count,
            blocked_in_other_groups=banned_count,
            spam_db_similarity=spam_db_similarity,
            spam_db_matched_pattern=spam_db_matched_pattern,
            is_in_global_blocklist=False,
            is_in_global_whitelist=is_whitelisted,
        )

    # =========================================================================
    # Utility Methods
    # =========================================================================

    async def flush_user_network_data(self, user_id: int) -> None:
        """
        Remove all network tracking data for a user.

        Useful for GDPR compliance or user data cleanup.
        Does NOT remove from blocklist/whitelist (those are admin decisions).

        Args:
            user_id: Telegram user ID.
        """
        if not self._is_available():
            return

        keys = [
            f"{self.KEY_USER}:{user_id}:groups",
            f"{self.KEY_USER}:{user_id}:bans",
            f"{self.KEY_USER}:{user_id}:flags",
            f"{self.KEY_USER}:{user_id}:reputation",
        ]

        try:
            await self._client.delete(*keys)
            logger.info(
                "user_network_data_flushed",
                user_id=user_id,
                keys_deleted=len(keys),
            )

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            logger.warning(
                "flush_user_network_data_failed",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    async def get_stats(self) -> dict:
        """
        Get network analyzer statistics.

        Returns:
            Dict with blocklist/whitelist sizes and connection status.
        """
        if not self._is_available():
            return {
                "available": False,
                "blocklist_size": 0,
                "whitelist_size": 0,
            }

        try:
            blocklist_size = await self._client.scard(self.KEY_BLOCKLIST) or 0
            whitelist_size = await self._client.scard(self.KEY_WHITELIST) or 0

            return {
                "available": True,
                "blocklist_size": int(blocklist_size),
                "whitelist_size": int(whitelist_size),
            }

        except (redis.asyncio.RedisError, ConnectionError, TimeoutError) as e:
            logger.warning(
                "get_stats_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            return {
                "available": False,
                "error": str(e),
            }
