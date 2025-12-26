"""Repository for decision operations.

This module provides data access methods for the decisions table,
handling spam detection decision logging and statistics.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from saqshy.core.types import Verdict
from saqshy.db.models import Decision
from saqshy.db.repositories.base import BaseRepository


@dataclass
class DecisionStats:
    """Statistics for spam detection decisions.

    Attributes:
        total: Total number of decisions
        by_verdict: Count of decisions by verdict type
        llm_usage: Percentage of decisions that used LLM
        avg_processing_time_ms: Average processing time in milliseconds
        blocked_messages: Number of blocked messages
        banned_users: Number of banned users
    """

    total: int
    by_verdict: dict[str, int]
    llm_usage_percent: float
    avg_processing_time_ms: float | None
    blocked_messages: int
    banned_users: int


class DecisionRepository(BaseRepository[Decision]):
    """Repository for Decision model operations.

    Handles all database operations related to spam detection decisions,
    including logging, querying, overrides, and statistics.

    Example:
        >>> async with session_factory() as session:
        ...     repo = DecisionRepository(session)
        ...     decision = await repo.create_decision(
        ...         group_id=-1001234567890,
        ...         user_id=123456789,
        ...         message_id=42,
        ...         risk_score=85,
        ...         verdict=Verdict.BLOCK,
        ...     )
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session.

        Args:
            session: SQLAlchemy async session
        """
        super().__init__(session, Decision)

    async def create_decision(
        self,
        group_id: int,
        user_id: int,
        message_id: int | None,
        risk_score: int,
        verdict: Verdict,
        *,
        threat_type: str | None = None,
        profile_signals: dict[str, Any] | None = None,
        content_signals: dict[str, Any] | None = None,
        behavior_signals: dict[str, Any] | None = None,
        llm_used: bool = False,
        llm_response: dict[str, Any] | None = None,
        llm_latency_ms: int | None = None,
        action_taken: str | None = None,
        message_deleted: bool = False,
        user_banned: bool = False,
        user_restricted: bool = False,
        processing_time_ms: int | None = None,
    ) -> Decision:
        """Create a new decision record.

        This is the primary method for logging spam detection decisions.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id
            message_id: Telegram message_id (optional)
            risk_score: Calculated risk score (0-100)
            verdict: Final verdict (allow/watch/limit/review/block)
            threat_type: Type of detected threat
            profile_signals: Profile-based signals and scores
            content_signals: Content-based signals and scores
            behavior_signals: Behavior-based signals and scores
            llm_used: Whether LLM was consulted
            llm_response: LLM response payload
            llm_latency_ms: LLM response time in milliseconds
            action_taken: Description of action taken
            message_deleted: Whether message was deleted
            user_banned: Whether user was banned
            user_restricted: Whether user was restricted
            processing_time_ms: Total processing time

        Returns:
            Created Decision instance

        Example:
            >>> decision = await repo.create_decision(
            ...     group_id=-1001234567890,
            ...     user_id=123456789,
            ...     message_id=42,
            ...     risk_score=85,
            ...     verdict=Verdict.BLOCK,
            ...     threat_type="scam",
            ...     action_taken="delete_and_ban",
            ... )
        """
        decision = Decision(
            group_id=group_id,
            user_id=user_id,
            message_id=message_id,
            risk_score=risk_score,
            verdict=verdict,
            threat_type=threat_type,
            profile_signals=profile_signals or {},
            content_signals=content_signals or {},
            behavior_signals=behavior_signals or {},
            llm_used=llm_used,
            llm_response=llm_response,
            llm_latency_ms=llm_latency_ms,
            action_taken=action_taken,
            message_deleted=message_deleted,
            user_banned=user_banned,
            user_restricted=user_restricted,
            processing_time_ms=processing_time_ms,
        )
        self.session.add(decision)
        await self.session.flush()
        await self.session.refresh(decision)
        return decision

    async def get_by_group(
        self,
        group_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
        verdict: Verdict | None = None,
    ) -> Sequence[Decision]:
        """Get decisions for a group with optional filtering.

        Results are ordered by created_at descending (newest first).

        Args:
            group_id: Telegram chat_id
            limit: Maximum number of decisions to return
            offset: Number of decisions to skip
            verdict: Optional filter by verdict type

        Returns:
            Sequence of Decision instances
        """
        stmt: Select[tuple[Decision]] = (
            select(Decision)
            .where(Decision.group_id == group_id)
            .order_by(Decision.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if verdict is not None:
            stmt = stmt.where(Decision.verdict == verdict)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_user(
        self,
        user_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
        group_id: int | None = None,
    ) -> Sequence[Decision]:
        """Get decisions for a user with optional group filter.

        Results are ordered by created_at descending (newest first).

        Args:
            user_id: Telegram user_id
            limit: Maximum number of decisions to return
            offset: Number of decisions to skip
            group_id: Optional filter by group

        Returns:
            Sequence of Decision instances
        """
        stmt: Select[tuple[Decision]] = (
            select(Decision)
            .where(Decision.user_id == user_id)
            .order_by(Decision.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if group_id is not None:
            stmt = stmt.where(Decision.group_id == group_id)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_stats(
        self,
        group_id: int,
        days: int = 7,
    ) -> DecisionStats:
        """Get decision statistics for a group.

        Args:
            group_id: Telegram chat_id
            days: Number of days to include in stats

        Returns:
            DecisionStats with aggregated statistics
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)

        # Base filter for the time period and group
        base_filter = and_(
            Decision.group_id == group_id,
            Decision.created_at >= cutoff,
        )

        # Total count
        total_stmt = select(func.count()).select_from(Decision).where(base_filter)
        total_result = await self.session.execute(total_stmt)
        total = total_result.scalar_one()

        # Count by verdict
        verdict_stmt = (
            select(Decision.verdict, func.count()).where(base_filter).group_by(Decision.verdict)
        )
        verdict_result = await self.session.execute(verdict_stmt)
        by_verdict = {row[0].value: row[1] for row in verdict_result.all()}

        # LLM usage
        llm_stmt = (
            select(func.count())
            .select_from(Decision)
            .where(and_(base_filter, Decision.llm_used == True))  # noqa: E712
        )
        llm_result = await self.session.execute(llm_stmt)
        llm_count = llm_result.scalar_one()
        llm_usage_percent = (llm_count / total * 100) if total > 0 else 0.0

        # Average processing time
        avg_time_stmt = select(func.avg(Decision.processing_time_ms)).where(
            and_(base_filter, Decision.processing_time_ms.isnot(None))
        )
        avg_time_result = await self.session.execute(avg_time_stmt)
        avg_processing_time = avg_time_result.scalar_one()

        # Blocked messages count
        blocked_stmt = (
            select(func.count())
            .select_from(Decision)
            .where(and_(base_filter, Decision.message_deleted == True))  # noqa: E712
        )
        blocked_result = await self.session.execute(blocked_stmt)
        blocked_messages = blocked_result.scalar_one()

        # Banned users count
        banned_stmt = (
            select(func.count())
            .select_from(Decision)
            .where(and_(base_filter, Decision.user_banned == True))  # noqa: E712
        )
        banned_result = await self.session.execute(banned_stmt)
        banned_users = banned_result.scalar_one()

        return DecisionStats(
            total=total,
            by_verdict=by_verdict,
            llm_usage_percent=llm_usage_percent,
            avg_processing_time_ms=float(avg_processing_time) if avg_processing_time else None,
            blocked_messages=blocked_messages,
            banned_users=banned_users,
        )

    async def record_override(
        self,
        decision_id: UUID,
        admin_id: int,
        reason: str,
        *,
        new_action: str | None = None,
    ) -> Decision | None:
        """Record an admin override for a decision.

        Args:
            decision_id: UUID of the decision to override
            admin_id: Telegram user_id of the admin
            reason: Reason for the override

        Returns:
            Updated Decision instance, or None if not found
        """
        decision = await self.get_by_id(decision_id)
        if decision is None:
            return None

        decision.overridden_by = admin_id
        decision.overridden_at = datetime.now(UTC)
        decision.override_reason = reason
        if new_action is not None:
            decision.action_taken = new_action

        await self.session.flush()
        await self.session.refresh(decision)
        return decision

    async def get_recent_blocks(
        self,
        group_id: int,
        *,
        hours: int = 24,
        limit: int = 100,
    ) -> Sequence[Decision]:
        """Get recent block decisions for a group.

        Useful for reviewing recent spam detections.

        Args:
            group_id: Telegram chat_id
            hours: Number of hours to look back
            limit: Maximum number of decisions to return

        Returns:
            Sequence of blocked Decision instances
        """
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        stmt = (
            select(Decision)
            .where(
                and_(
                    Decision.group_id == group_id,
                    Decision.verdict == Verdict.BLOCK,
                    Decision.created_at >= cutoff,
                )
            )
            .order_by(Decision.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_false_positives(
        self,
        group_id: int,
        *,
        days: int = 7,
    ) -> Sequence[Decision]:
        """Get decisions that were overridden (potential false positives).

        Useful for analyzing and improving spam detection accuracy.

        Args:
            group_id: Telegram chat_id
            days: Number of days to look back

        Returns:
            Sequence of overridden Decision instances
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(Decision)
            .where(
                and_(
                    Decision.group_id == group_id,
                    Decision.overridden_at.isnot(None),
                    Decision.created_at >= cutoff,
                )
            )
            .order_by(Decision.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_pending_reviews(
        self,
        group_id: int,
    ) -> Sequence[Decision]:
        """Get decisions pending admin review.

        Returns decisions with verdict=REVIEW that haven't been overridden.

        Args:
            group_id: Telegram chat_id

        Returns:
            Sequence of Decision instances pending review
        """
        stmt = (
            select(Decision)
            .where(
                and_(
                    Decision.group_id == group_id,
                    Decision.verdict == Verdict.REVIEW,
                    Decision.overridden_at.is_(None),
                )
            )
            .order_by(Decision.created_at.asc())  # Oldest first
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_user_history_in_group(
        self,
        group_id: int,
        user_id: int,
        *,
        limit: int = 10,
    ) -> Sequence[Decision]:
        """Get a user's decision history within a specific group.

        Useful for understanding user behavior patterns.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id
            limit: Maximum number of decisions to return

        Returns:
            Sequence of Decision instances for the user
        """
        stmt = (
            select(Decision)
            .where(
                and_(
                    Decision.group_id == group_id,
                    Decision.user_id == user_id,
                )
            )
            .order_by(Decision.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_llm_decisions(
        self,
        group_id: int,
        *,
        days: int = 7,
        limit: int = 100,
    ) -> Sequence[Decision]:
        """Get decisions that used LLM analysis.

        Useful for analyzing LLM effectiveness and response times.

        Args:
            group_id: Telegram chat_id
            days: Number of days to look back
            limit: Maximum number of decisions to return

        Returns:
            Sequence of Decision instances that used LLM
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(Decision)
            .where(
                and_(
                    Decision.group_id == group_id,
                    Decision.llm_used == True,  # noqa: E712
                    Decision.created_at >= cutoff,
                )
            )
            .order_by(Decision.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_threat_type_distribution(
        self,
        group_id: int,
        days: int = 30,
    ) -> dict[str, int]:
        """Get distribution of threat types for a group.

        Args:
            group_id: Telegram chat_id
            days: Number of days to include

        Returns:
            Dictionary mapping threat_type to count
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(Decision.threat_type, func.count())
            .where(
                and_(
                    Decision.group_id == group_id,
                    Decision.threat_type.isnot(None),
                    Decision.created_at >= cutoff,
                )
            )
            .group_by(Decision.threat_type)
        )
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def cleanup_old_decisions(
        self,
        days: int = 90,
    ) -> int:
        """Delete decisions older than specified days.

        Use with caution - this permanently deletes data.

        Args:
            days: Delete decisions older than this many days

        Returns:
            Number of deleted records
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = Decision.__table__.delete().where(Decision.created_at < cutoff)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    # =========================================================================
    # Explicit relationship loading methods
    # These methods are required since relationships use lazy="raise"
    # =========================================================================

    async def get_by_id_with_group(
        self,
        decision_id: UUID,
    ) -> Decision | None:
        """Get decision with eagerly loaded group.

        Args:
            decision_id: UUID of the decision

        Returns:
            Decision with loaded group, or None if not found
        """
        stmt = (
            select(Decision).options(joinedload(Decision.group)).where(Decision.id == decision_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_user(
        self,
        decision_id: UUID,
    ) -> Decision | None:
        """Get decision with eagerly loaded user.

        Args:
            decision_id: UUID of the decision

        Returns:
            Decision with loaded user, or None if not found
        """
        stmt = select(Decision).options(joinedload(Decision.user)).where(Decision.id == decision_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_all_relations(
        self,
        decision_id: UUID,
    ) -> Decision | None:
        """Get decision with all relationships loaded.

        Args:
            decision_id: UUID of the decision

        Returns:
            Decision with all relationships loaded, or None if not found
        """
        stmt = (
            select(Decision)
            .options(
                joinedload(Decision.group),
                joinedload(Decision.user),
            )
            .where(Decision.id == decision_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_group_with_users(
        self,
        group_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
        verdict: Verdict | None = None,
    ) -> Sequence[Decision]:
        """Get decisions for a group with user data loaded.

        Results are ordered by created_at descending (newest first).

        Args:
            group_id: Telegram chat_id
            limit: Maximum number of decisions to return
            offset: Number of decisions to skip
            verdict: Optional filter by verdict type

        Returns:
            Sequence of Decision instances with users loaded
        """
        stmt: Select[tuple[Decision]] = (
            select(Decision)
            .options(joinedload(Decision.user))
            .where(Decision.group_id == group_id)
            .order_by(Decision.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if verdict is not None:
            stmt = stmt.where(Decision.verdict == verdict)

        result = await self.session.execute(stmt)
        return result.scalars().unique().all()

    async def get_by_user_with_groups(
        self,
        user_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Decision]:
        """Get decisions for a user with group data loaded.

        Results are ordered by created_at descending (newest first).

        Args:
            user_id: Telegram user_id
            limit: Maximum number of decisions to return
            offset: Number of decisions to skip

        Returns:
            Sequence of Decision instances with groups loaded
        """
        stmt: Select[tuple[Decision]] = (
            select(Decision)
            .options(joinedload(Decision.group))
            .where(Decision.user_id == user_id)
            .order_by(Decision.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().unique().all()

    async def get_recent_blocks_with_users(
        self,
        group_id: int,
        *,
        hours: int = 24,
        limit: int = 100,
    ) -> Sequence[Decision]:
        """Get recent block decisions with user data loaded.

        Useful for reviewing recent spam detections with user context.

        Args:
            group_id: Telegram chat_id
            hours: Number of hours to look back
            limit: Maximum number of decisions to return

        Returns:
            Sequence of blocked Decision instances with users loaded
        """
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        stmt = (
            select(Decision)
            .options(joinedload(Decision.user))
            .where(
                and_(
                    Decision.group_id == group_id,
                    Decision.verdict == Verdict.BLOCK,
                    Decision.created_at >= cutoff,
                )
            )
            .order_by(Decision.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().unique().all()

    async def get_pending_reviews_with_users(
        self,
        group_id: int,
    ) -> Sequence[Decision]:
        """Get decisions pending review with user data loaded.

        Returns decisions with verdict=REVIEW that haven't been overridden.

        Args:
            group_id: Telegram chat_id

        Returns:
            Sequence of Decision instances pending review with users loaded
        """
        stmt = (
            select(Decision)
            .options(joinedload(Decision.user))
            .where(
                and_(
                    Decision.group_id == group_id,
                    Decision.verdict == Verdict.REVIEW,
                    Decision.overridden_at.is_(None),
                )
            )
            .order_by(Decision.created_at.asc())  # Oldest first
        )
        result = await self.session.execute(stmt)
        return result.scalars().unique().all()
