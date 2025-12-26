"""
SAQSHY Signal Aggregator

Combines signals from all analyzers into a unified Signals object.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import TYPE_CHECKING

import structlog

from saqshy.analyzers.behavior import BehaviorAnalyzer
from saqshy.analyzers.content import ContentAnalyzer
from saqshy.analyzers.profile import ProfileAnalyzer
from saqshy.core.types import (
    BehaviorSignals,
    ContentSignals,
    GroupType,
    MessageContext,
    NetworkSignals,
    ProfileSignals,
    Signals,
)

if TYPE_CHECKING:
    from saqshy.services.cache import CacheService
    from saqshy.services.network import NetworkAnalyzer
    from saqshy.services.spam_db import SpamDB

logger = structlog.get_logger(__name__)


# TTL for signal caching
TTL_PROFILE_SIGNALS = 300  # 5 minutes - profile rarely changes
TTL_BEHAVIOR_SIGNALS = 60  # 1 minute - behavior is more dynamic


class SignalAggregator:
    """
    Aggregates signals from all analyzers.

    Runs analyzers in parallel for optimal performance.
    Integrates with NetworkAnalyzer for cross-group detection
    and SpamDB for spam pattern matching.
    """

    def __init__(
        self,
        group_type: GroupType = GroupType.GENERAL,
        profile_analyzer: ProfileAnalyzer | None = None,
        content_analyzer: ContentAnalyzer | None = None,
        behavior_analyzer: BehaviorAnalyzer | None = None,
        network_analyzer: NetworkAnalyzer | None = None,
        spam_db: SpamDB | None = None,
    ):
        """
        Initialize signal aggregator.

        Args:
            group_type: Type of group for analyzer configuration.
            profile_analyzer: Custom profile analyzer (optional).
            content_analyzer: Custom content analyzer (optional).
            behavior_analyzer: Custom behavior analyzer (optional).
            network_analyzer: NetworkAnalyzer for cross-group signals (optional).
            spam_db: SpamDB for spam pattern matching (optional).
        """
        self.group_type = group_type
        self.profile_analyzer = profile_analyzer or ProfileAnalyzer()
        self.content_analyzer = content_analyzer or ContentAnalyzer()
        self.behavior_analyzer = behavior_analyzer or BehaviorAnalyzer()
        self.network_analyzer = network_analyzer
        self.spam_db = spam_db

    async def aggregate(self, context: MessageContext) -> Signals:
        """
        Aggregate signals from all analyzers.

        Runs profile, content, behavior, and network analysis in parallel.

        Args:
            context: Message context with all relevant data.

        Returns:
            Combined Signals object.
        """
        # Run analyzers in parallel
        profile_task = asyncio.create_task(self._analyze_profile(context))
        content_task = asyncio.create_task(self._analyze_content(context))
        behavior_task = asyncio.create_task(self._analyze_behavior(context))
        network_task = asyncio.create_task(self._analyze_network(context))

        # Wait for all with timeout
        try:
            profile, content, behavior, network = await asyncio.wait_for(
                asyncio.gather(
                    profile_task,
                    content_task,
                    behavior_task,
                    network_task,
                    return_exceptions=True,
                ),
                timeout=5.0,  # 5 second timeout
            )
        except TimeoutError:
            logger.warning(
                "signal_aggregation_timeout",
                message_id=context.message_id,
            )
            # Return default signals on timeout
            return Signals()

        # Handle any exceptions from tasks
        if isinstance(profile, Exception):
            logger.error("profile_analysis_error", error=str(profile))
            profile = ProfileSignals()

        if isinstance(content, Exception):
            logger.error("content_analysis_error", error=str(content))
            content = ContentSignals()

        if isinstance(behavior, Exception):
            logger.error("behavior_analysis_error", error=str(behavior))
            behavior = BehaviorSignals()

        if isinstance(network, Exception):
            logger.error("network_analysis_error", error=str(network))
            network = NetworkSignals()

        return Signals(
            profile=profile,
            content=content,
            behavior=behavior,
            network=network,
        )

    async def _analyze_profile(self, context: MessageContext) -> ProfileSignals:
        """
        Run profile analysis.

        Args:
            context: Message context.

        Returns:
            ProfileSignals.
        """
        return await self.profile_analyzer.analyze(context)

    async def _analyze_content(self, context: MessageContext) -> ContentSignals:
        """
        Run content analysis.

        Args:
            context: Message context.

        Returns:
            ContentSignals.
        """
        return await self.content_analyzer.analyze(context)

    async def _analyze_behavior(self, context: MessageContext) -> BehaviorSignals:
        """
        Run behavior analysis.

        Args:
            context: Message context.

        Returns:
            BehaviorSignals.
        """
        return await self.behavior_analyzer.analyze(context)

    async def _analyze_network(self, context: MessageContext) -> NetworkSignals:
        """
        Run network analysis (spam database and cross-group behavior).

        Performs:
        - Spam database similarity check via SpamDB
        - Cross-group duplicate detection via NetworkAnalyzer
        - Ban/flag history across groups
        - Global blocklist/whitelist check

        Args:
            context: Message context.

        Returns:
            NetworkSignals with cross-group and spam database indicators.
        """
        # Get spam database results first (if available)
        spam_db_similarity = 0.0
        spam_db_matched_pattern: str | None = None

        if self.spam_db and context.text:
            try:
                spam_db_similarity, spam_db_matched_pattern = await self.spam_db.check_spam(
                    context.text
                )
            except Exception as e:
                logger.warning(
                    "spam_db_check_failed",
                    message_id=context.message_id,
                    error=str(e),
                )

        # If no network analyzer, return just spam DB results
        if not self.network_analyzer:
            return NetworkSignals(
                spam_db_similarity=spam_db_similarity,
                spam_db_matched_pattern=spam_db_matched_pattern,
            )

        # Run full network analysis
        try:
            return await self.network_analyzer.analyze(
                user_id=context.user_id,
                chat_id=context.chat_id,
                text=context.text,
                spam_db_similarity=spam_db_similarity,
                spam_db_matched_pattern=spam_db_matched_pattern,
            )
        except Exception as e:
            logger.warning(
                "network_analysis_failed",
                message_id=context.message_id,
                user_id=context.user_id,
                error=str(e),
            )
            # Return partial results with spam DB data
            return NetworkSignals(
                spam_db_similarity=spam_db_similarity,
                spam_db_matched_pattern=spam_db_matched_pattern,
            )


class SignalCache:
    """
    Redis-based signal cache to avoid redundant computation.

    Particularly useful for:
    - Multiple messages from same user (profile rarely changes)
    - Behavior signals within short windows

    Key Schema:
        saqshy:signals:profile:{user_id}           # JSON ProfileSignals
        saqshy:signals:behavior:{chat_id}:{user_id}  # JSON BehaviorSignals

    TTL Strategy:
        - Profile signals: 5 minutes (profile rarely changes)
        - Behavior signals: 1 minute (more dynamic)
    """

    PREFIX = "saqshy:signals"
    KEY_PROFILE = f"{PREFIX}:profile"
    KEY_BEHAVIOR = f"{PREFIX}:behavior"

    def __init__(
        self,
        cache_service: CacheService,
        profile_ttl: int = TTL_PROFILE_SIGNALS,
        behavior_ttl: int = TTL_BEHAVIOR_SIGNALS,
    ):
        """
        Initialize signal cache.

        Args:
            cache_service: Connected CacheService instance.
            profile_ttl: TTL for profile signals in seconds.
            behavior_ttl: TTL for behavior signals in seconds.
        """
        self.cache = cache_service
        self.profile_ttl = profile_ttl
        self.behavior_ttl = behavior_ttl

    def _is_available(self) -> bool:
        """Check if cache is available."""
        return self.cache._connected and self.cache._client is not None

    async def get_profile_signals(self, user_id: int) -> ProfileSignals | None:
        """
        Get cached profile signals.

        Args:
            user_id: Telegram user ID.

        Returns:
            Cached ProfileSignals or None if not cached/expired.
        """
        if not self._is_available():
            return None

        key = f"{self.KEY_PROFILE}:{user_id}"

        try:
            data = await self.cache.get_json(key)
            if data:
                return ProfileSignals(**data)
            return None

        except Exception as e:
            logger.warning(
                "get_profile_signals_failed",
                user_id=user_id,
                error=str(e),
            )
            return None

    async def set_profile_signals(self, user_id: int, signals: ProfileSignals) -> None:
        """
        Cache profile signals.

        Args:
            user_id: Telegram user ID.
            signals: ProfileSignals to cache.
        """
        if not self._is_available():
            return

        key = f"{self.KEY_PROFILE}:{user_id}"

        try:
            data = asdict(signals)
            await self.cache.set_json(key, data, ttl=self.profile_ttl)

        except Exception as e:
            logger.warning(
                "set_profile_signals_failed",
                user_id=user_id,
                error=str(e),
            )

    async def get_behavior_signals(self, user_id: int, chat_id: int) -> BehaviorSignals | None:
        """
        Get cached behavior signals.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            Cached BehaviorSignals or None if not cached/expired.
        """
        if not self._is_available():
            return None

        key = f"{self.KEY_BEHAVIOR}:{chat_id}:{user_id}"

        try:
            data = await self.cache.get_json(key)
            if data:
                return BehaviorSignals(**data)
            return None

        except Exception as e:
            logger.warning(
                "get_behavior_signals_failed",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )
            return None

    async def set_behavior_signals(
        self, user_id: int, chat_id: int, signals: BehaviorSignals
    ) -> None:
        """
        Cache behavior signals.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            signals: BehaviorSignals to cache.
        """
        if not self._is_available():
            return

        key = f"{self.KEY_BEHAVIOR}:{chat_id}:{user_id}"

        try:
            data = asdict(signals)
            await self.cache.set_json(key, data, ttl=self.behavior_ttl)

        except Exception as e:
            logger.warning(
                "set_behavior_signals_failed",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )

    async def invalidate_profile(self, user_id: int) -> None:
        """
        Invalidate cached profile signals.

        Call when user profile is updated.

        Args:
            user_id: Telegram user ID.
        """
        if not self._is_available():
            return

        key = f"{self.KEY_PROFILE}:{user_id}"

        try:
            await self.cache.delete(key)

        except Exception as e:
            logger.warning(
                "invalidate_profile_failed",
                user_id=user_id,
                error=str(e),
            )

    async def invalidate_behavior(self, user_id: int, chat_id: int) -> None:
        """
        Invalidate cached behavior signals.

        Call when user behavior changes significantly.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
        """
        if not self._is_available():
            return

        key = f"{self.KEY_BEHAVIOR}:{chat_id}:{user_id}"

        try:
            await self.cache.delete(key)

        except Exception as e:
            logger.warning(
                "invalidate_behavior_failed",
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
            )
