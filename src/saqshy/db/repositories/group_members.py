"""Repository for group member operations.

This module provides data access methods for the group_members table,
handling user membership, trust levels, and sandbox tracking.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from saqshy.db.models import GroupMember, TrustLevel
from saqshy.db.repositories.base import BaseRepository


class GroupMemberRepository(BaseRepository[GroupMember]):
    """Repository for GroupMember model operations.

    Handles all database operations related to user membership
    within groups, including trust levels and sandbox tracking.

    Example:
        >>> async with session_factory() as session:
        ...     repo = GroupMemberRepository(session)
        ...     member = await repo.get_member(
        ...         group_id=-1001234567890,
        ...         user_id=123456789,
        ...     )
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session.

        Args:
            session: SQLAlchemy async session
        """
        super().__init__(session, GroupMember)

    async def get_member(
        self,
        group_id: int,
        user_id: int,
    ) -> GroupMember | None:
        """Get a specific group member by composite key.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id

        Returns:
            GroupMember instance if found, None otherwise
        """
        stmt = select(GroupMember).where(
            and_(
                GroupMember.group_id == group_id,
                GroupMember.user_id == user_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_or_update_member(
        self,
        group_id: int,
        user_id: int,
        *,
        trust_level: TrustLevel | None = None,
        trust_score: int | None = None,
        sandbox_expires_at: datetime | None = None,
    ) -> tuple[GroupMember, bool]:
        """Create a new member or update existing one.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id
            trust_level: Initial/updated trust level
            trust_score: Initial/updated trust score
            sandbox_expires_at: When sandbox expires

        Returns:
            Tuple of (GroupMember instance, created flag)
        """
        existing = await self.get_member(group_id, user_id)

        if existing is not None:
            # Update existing member
            if trust_level is not None:
                existing.trust_level = trust_level
            if trust_score is not None:
                existing.trust_score = trust_score
            if sandbox_expires_at is not None:
                existing.sandbox_expires_at = sandbox_expires_at
            await self.session.flush()
            await self.session.refresh(existing)
            return existing, False
        else:
            # Create new member
            member = GroupMember(
                group_id=group_id,
                user_id=user_id,
                trust_level=trust_level or TrustLevel.NEW,
                trust_score=trust_score or 50,
                sandbox_expires_at=sandbox_expires_at,
            )
            self.session.add(member)
            await self.session.flush()
            await self.session.refresh(member)
            return member, True

    async def record_join(
        self,
        group_id: int,
        user_id: int,
        *,
        sandbox_hours: int = 24,
        start_in_sandbox: bool = True,
    ) -> GroupMember:
        """Record a user joining a group.

        Creates a new member record or updates existing one with
        fresh join timestamp and sandbox settings.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id
            sandbox_hours: Duration of sandbox period
            start_in_sandbox: Whether to start user in sandbox mode

        Returns:
            GroupMember instance
        """
        now = datetime.now(UTC)
        sandbox_expires = now + timedelta(hours=sandbox_hours) if start_in_sandbox else None
        trust_level = TrustLevel.SANDBOX if start_in_sandbox else TrustLevel.NEW

        existing = await self.get_member(group_id, user_id)
        if existing is not None:
            # User rejoined - reset sandbox
            existing.joined_at = now
            existing.trust_level = trust_level
            existing.sandbox_expires_at = sandbox_expires
            existing.messages_in_sandbox = 0
            existing.first_message_at = None
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        else:
            # New member
            member = GroupMember(
                group_id=group_id,
                user_id=user_id,
                joined_at=now,
                trust_level=trust_level,
                trust_score=50,
                sandbox_expires_at=sandbox_expires,
            )
            self.session.add(member)
            await self.session.flush()
            await self.session.refresh(member)
            return member

    async def record_message(
        self,
        group_id: int,
        user_id: int,
    ) -> GroupMember | None:
        """Record a message from a user.

        Updates message counts and timestamps. Creates member record
        if it doesn't exist.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id

        Returns:
            Updated GroupMember instance
        """
        now = datetime.now(UTC)
        member = await self.get_member(group_id, user_id)

        if member is None:
            # Create member record for users who joined before bot
            member = GroupMember(
                group_id=group_id,
                user_id=user_id,
                joined_at=now,
                trust_level=TrustLevel.NEW,
                trust_score=50,
                message_count=0,
                messages_in_sandbox=0,
            )
            self.session.add(member)

        # Update message tracking
        member.message_count += 1
        member.last_message_at = now

        if member.first_message_at is None:
            member.first_message_at = now

        # Track sandbox messages
        if member.is_in_sandbox:
            member.messages_in_sandbox += 1

        await self.session.flush()
        await self.session.refresh(member)
        return member

    async def update_trust_level(
        self,
        group_id: int,
        user_id: int,
        trust_level: TrustLevel,
    ) -> GroupMember | None:
        """Update a member's trust level.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id
            trust_level: New trust level

        Returns:
            Updated GroupMember, or None if not found
        """
        member = await self.get_member(group_id, user_id)
        if member is None:
            return None

        member.trust_level = trust_level

        # Clear sandbox if promoted past it
        if trust_level in (TrustLevel.LIMITED, TrustLevel.TRUSTED, TrustLevel.ADMIN):
            member.sandbox_expires_at = None

        await self.session.flush()
        await self.session.refresh(member)
        return member

    async def update_trust_score(
        self,
        group_id: int,
        user_id: int,
        delta: int,
    ) -> GroupMember | None:
        """Adjust a member's trust score.

        Score is clamped between 0 and 100.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id
            delta: Amount to add (positive) or subtract (negative)

        Returns:
            Updated GroupMember, or None if not found
        """
        member = await self.get_member(group_id, user_id)
        if member is None:
            return None

        new_score = max(0, min(100, member.trust_score + delta))
        member.trust_score = new_score

        await self.session.flush()
        await self.session.refresh(member)
        return member

    async def exit_sandbox(
        self,
        group_id: int,
        user_id: int,
    ) -> GroupMember | None:
        """Remove a member from sandbox mode.

        Promotes to LIMITED trust level and clears sandbox expiration.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id

        Returns:
            Updated GroupMember, or None if not found
        """
        member = await self.get_member(group_id, user_id)
        if member is None:
            return None

        member.trust_level = TrustLevel.LIMITED
        member.sandbox_expires_at = None

        await self.session.flush()
        await self.session.refresh(member)
        return member

    async def promote_to_trusted(
        self,
        group_id: int,
        user_id: int,
    ) -> GroupMember | None:
        """Promote a member to trusted status.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id

        Returns:
            Updated GroupMember, or None if not found
        """
        return await self.update_trust_level(group_id, user_id, TrustLevel.TRUSTED)

    async def set_admin(
        self,
        group_id: int,
        user_id: int,
    ) -> GroupMember | None:
        """Mark a member as group admin.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id

        Returns:
            Updated GroupMember, or None if not found
        """
        return await self.update_trust_level(group_id, user_id, TrustLevel.ADMIN)

    async def get_members_by_trust_level(
        self,
        group_id: int,
        trust_level: TrustLevel,
        *,
        limit: int | None = None,
    ) -> Sequence[GroupMember]:
        """Get all members with a specific trust level.

        Args:
            group_id: Telegram chat_id
            trust_level: Trust level to filter by
            limit: Maximum number of members to return

        Returns:
            Sequence of GroupMember instances
        """
        stmt: Select[tuple[GroupMember]] = (
            select(GroupMember)
            .where(
                and_(
                    GroupMember.group_id == group_id,
                    GroupMember.trust_level == trust_level,
                )
            )
            .order_by(GroupMember.joined_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_sandbox_members(
        self,
        group_id: int,
    ) -> Sequence[GroupMember]:
        """Get all members currently in sandbox.

        Args:
            group_id: Telegram chat_id

        Returns:
            Sequence of GroupMember instances in sandbox
        """
        now = datetime.now(UTC)
        stmt = (
            select(GroupMember)
            .where(
                and_(
                    GroupMember.group_id == group_id,
                    GroupMember.trust_level == TrustLevel.SANDBOX,
                    GroupMember.sandbox_expires_at > now,
                )
            )
            .order_by(GroupMember.sandbox_expires_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_expired_sandbox_members(
        self,
        group_id: int | None = None,
    ) -> Sequence[GroupMember]:
        """Get members whose sandbox has expired.

        Useful for batch processing sandbox expiration.

        Args:
            group_id: Optional filter by group

        Returns:
            Sequence of GroupMember instances with expired sandbox
        """
        now = datetime.now(UTC)
        conditions = [
            GroupMember.trust_level == TrustLevel.SANDBOX,
            GroupMember.sandbox_expires_at <= now,
        ]
        if group_id is not None:
            conditions.append(GroupMember.group_id == group_id)

        stmt = select(GroupMember).where(and_(*conditions))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_active_members(
        self,
        group_id: int,
        *,
        days: int = 7,
        limit: int = 100,
    ) -> Sequence[GroupMember]:
        """Get members active within the specified period.

        Args:
            group_id: Telegram chat_id
            days: Number of days to look back
            limit: Maximum number of members to return

        Returns:
            Sequence of active GroupMember instances
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(GroupMember)
            .where(
                and_(
                    GroupMember.group_id == group_id,
                    GroupMember.last_message_at >= cutoff,
                )
            )
            .order_by(GroupMember.last_message_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_member_with_user(
        self,
        group_id: int,
        user_id: int,
    ) -> GroupMember | None:
        """Get member with eagerly loaded user relationship.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id

        Returns:
            GroupMember with loaded user, or None
        """
        stmt = (
            select(GroupMember)
            .options(selectinload(GroupMember.user))
            .where(
                and_(
                    GroupMember.group_id == group_id,
                    GroupMember.user_id == user_id,
                )
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_member_stats(
        self,
        group_id: int,
    ) -> dict[str, Any]:
        """Get membership statistics for a group.

        Args:
            group_id: Telegram chat_id

        Returns:
            Dictionary with membership statistics
        """
        # Count by trust level
        trust_stmt = (
            select(GroupMember.trust_level, func.count())
            .where(GroupMember.group_id == group_id)
            .group_by(GroupMember.trust_level)
        )
        trust_result = await self.session.execute(trust_stmt)
        by_trust_level = {row[0].value: row[1] for row in trust_result.all()}

        # Total members
        total_stmt = (
            select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group_id)
        )
        total_result = await self.session.execute(total_stmt)
        total = total_result.scalar_one()

        # Active in last 24 hours
        cutoff_24h = datetime.now(UTC) - timedelta(hours=24)
        active_stmt = (
            select(func.count())
            .select_from(GroupMember)
            .where(
                and_(
                    GroupMember.group_id == group_id,
                    GroupMember.last_message_at >= cutoff_24h,
                )
            )
        )
        active_result = await self.session.execute(active_stmt)
        active_24h = active_result.scalar_one()

        # Average trust score
        avg_stmt = select(func.avg(GroupMember.trust_score)).where(GroupMember.group_id == group_id)
        avg_result = await self.session.execute(avg_stmt)
        avg_trust_score = avg_result.scalar_one()

        return {
            "total_members": total,
            "by_trust_level": by_trust_level,
            "active_last_24h": active_24h,
            "avg_trust_score": float(avg_trust_score) if avg_trust_score else None,
        }

    async def remove_member(
        self,
        group_id: int,
        user_id: int,
    ) -> bool:
        """Remove a member from a group.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id

        Returns:
            True if member was removed, False if not found
        """
        member = await self.get_member(group_id, user_id)
        if member is None:
            return False

        await self.session.delete(member)
        await self.session.flush()
        return True

    async def get_time_to_first_message(
        self,
        group_id: int,
        user_id: int,
    ) -> float | None:
        """Get time in seconds from join to first message.

        This is a key spam signal (TTFM - Time To First Message).

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id

        Returns:
            Seconds from join to first message, or None if no message
        """
        member = await self.get_member(group_id, user_id)
        if member is None or member.first_message_at is None:
            return None

        delta = member.first_message_at - member.joined_at
        return delta.total_seconds()

    async def batch_update_trust_scores(
        self,
        group_id: int,
        user_deltas: dict[int, int],
    ) -> int:
        """Batch update trust scores for multiple users.

        Args:
            group_id: Telegram chat_id
            user_deltas: Dictionary mapping user_id to score delta

        Returns:
            Number of updated records
        """
        updated = 0
        for user_id, delta in user_deltas.items():
            result = await self.update_trust_score(group_id, user_id, delta)
            if result is not None:
                updated += 1
        return updated

    async def count_user_groups(self, user_id: int) -> int:
        """Count how many groups a user is a member of.

        Args:
            user_id: Telegram user_id

        Returns:
            Number of groups where user is a member
        """
        stmt = select(func.count()).select_from(GroupMember).where(GroupMember.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def sum_user_messages(self, user_id: int) -> int:
        """Sum total messages across all groups for a user.

        Args:
            user_id: Telegram user_id

        Returns:
            Total message count across all groups
        """
        stmt = select(func.coalesce(func.sum(GroupMember.message_count), 0)).where(
            GroupMember.user_id == user_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    # =========================================================================
    # Explicit relationship loading methods
    # These methods are required since relationships use lazy="raise"
    # =========================================================================

    async def get_member_with_group(
        self,
        group_id: int,
        user_id: int,
    ) -> GroupMember | None:
        """Get member with eagerly loaded group relationship.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id

        Returns:
            GroupMember with loaded group, or None if not found
        """
        stmt = (
            select(GroupMember)
            .options(joinedload(GroupMember.group))
            .where(
                and_(
                    GroupMember.group_id == group_id,
                    GroupMember.user_id == user_id,
                )
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_member_with_all_relations(
        self,
        group_id: int,
        user_id: int,
    ) -> GroupMember | None:
        """Get member with both group and user relationships loaded.

        Args:
            group_id: Telegram chat_id
            user_id: Telegram user_id

        Returns:
            GroupMember with all relationships loaded, or None if not found
        """
        stmt = (
            select(GroupMember)
            .options(
                joinedload(GroupMember.group),
                joinedload(GroupMember.user),
            )
            .where(
                and_(
                    GroupMember.group_id == group_id,
                    GroupMember.user_id == user_id,
                )
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_members_by_trust_level_with_users(
        self,
        group_id: int,
        trust_level: TrustLevel,
        *,
        limit: int | None = None,
    ) -> Sequence[GroupMember]:
        """Get all members with a specific trust level with user data loaded.

        Args:
            group_id: Telegram chat_id
            trust_level: Trust level to filter by
            limit: Maximum number of members to return

        Returns:
            Sequence of GroupMember instances with users loaded
        """
        stmt: Select[tuple[GroupMember]] = (
            select(GroupMember)
            .options(joinedload(GroupMember.user))
            .where(
                and_(
                    GroupMember.group_id == group_id,
                    GroupMember.trust_level == trust_level,
                )
            )
            .order_by(GroupMember.joined_at.desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await self.session.execute(stmt)
        return result.scalars().unique().all()

    async def get_sandbox_members_with_users(
        self,
        group_id: int,
    ) -> Sequence[GroupMember]:
        """Get all members currently in sandbox with user data loaded.

        Args:
            group_id: Telegram chat_id

        Returns:
            Sequence of GroupMember instances in sandbox with users loaded
        """
        now = datetime.now(UTC)
        stmt = (
            select(GroupMember)
            .options(joinedload(GroupMember.user))
            .where(
                and_(
                    GroupMember.group_id == group_id,
                    GroupMember.trust_level == TrustLevel.SANDBOX,
                    GroupMember.sandbox_expires_at > now,
                )
            )
            .order_by(GroupMember.sandbox_expires_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().unique().all()

    async def get_active_members_with_users(
        self,
        group_id: int,
        *,
        days: int = 7,
        limit: int = 100,
    ) -> Sequence[GroupMember]:
        """Get members active within the specified period with user data.

        Args:
            group_id: Telegram chat_id
            days: Number of days to look back
            limit: Maximum number of members to return

        Returns:
            Sequence of active GroupMember instances with users loaded
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(GroupMember)
            .options(joinedload(GroupMember.user))
            .where(
                and_(
                    GroupMember.group_id == group_id,
                    GroupMember.last_message_at >= cutoff,
                )
            )
            .order_by(GroupMember.last_message_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().unique().all()

    async def get_user_memberships_with_groups(
        self,
        user_id: int,
    ) -> Sequence[GroupMember]:
        """Get all memberships for a user with group data loaded.

        Args:
            user_id: Telegram user_id

        Returns:
            Sequence of GroupMember instances with groups loaded
        """
        stmt = (
            select(GroupMember)
            .options(joinedload(GroupMember.group))
            .where(GroupMember.user_id == user_id)
            .order_by(GroupMember.joined_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().unique().all()
