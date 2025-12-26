"""Repository for group operations.

This module provides data access methods for the groups table,
including settings management and statistics tracking.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from saqshy.core.types import GroupType  # Import from canonical source
from saqshy.db.models import Group
from saqshy.db.repositories.base import BaseRepository


class GroupRepository(BaseRepository[Group]):
    """Repository for Group model operations.

    Handles all database operations related to Telegram groups,
    including configuration, settings, and statistics.

    Example:
        >>> async with session_factory() as session:
        ...     repo = GroupRepository(session)
        ...     group = await repo.get_by_id(-1001234567890)
        ...     if group:
        ...         print(f"Group: {group.title}")
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session.

        Args:
            session: SQLAlchemy async session
        """
        super().__init__(session, Group)

    async def create_or_update(
        self,
        chat_id: int,
        title: str,
        *,
        username: str | None = None,
        group_type: GroupType = GroupType.GENERAL,
        linked_channel_id: int | None = None,
        members_count: int | None = None,
    ) -> tuple[Group, bool]:
        """Create a new group or update existing one.

        This is the primary method for registering groups when the bot
        is added to a new group or when group info changes.

        Args:
            chat_id: Telegram chat_id (negative for groups)
            title: Group display name
            username: Optional @username for public groups
            group_type: Type of group (general, tech, deals, crypto)
            linked_channel_id: Associated channel for subscription checks
            members_count: Number of members in the group

        Returns:
            Tuple of (Group instance, created flag)
            created is True if new group was created

        Example:
            >>> group, created = await repo.create_or_update(
            ...     chat_id=-1001234567890,
            ...     title="Python Developers",
            ...     group_type=GroupType.TECH,
            ... )
        """
        kwargs: dict[str, Any] = {
            "title": title,
            "username": username,
            "group_type": group_type,
        }
        if linked_channel_id is not None:
            kwargs["linked_channel_id"] = linked_channel_id
        if members_count is not None:
            kwargs["members_count"] = members_count

        existing = await self.get_by_id(chat_id)
        if existing is not None:
            # Update existing group
            for key, value in kwargs.items():
                setattr(existing, key, value)
            await self.session.flush()
            await self.session.refresh(existing)
            return existing, False
        else:
            # Create new group
            kwargs["id"] = chat_id
            group = await self.create(**kwargs)
            return group, True

    async def get_settings(self, chat_id: int) -> dict[str, Any] | None:
        """Get group settings as a dictionary.

        Returns configurable settings that affect spam detection behavior.

        Args:
            chat_id: Telegram chat_id

        Returns:
            Dictionary with settings, or None if group not found

        Example:
            >>> settings = await repo.get_settings(-1001234567890)
            >>> if settings:
            ...     print(f"Sensitivity: {settings['sensitivity']}")
        """
        group = await self.get_by_id(chat_id)
        if group is None:
            return None

        return {
            "group_type": group.group_type.value,
            "sensitivity": group.sensitivity,
            "sandbox_enabled": group.sandbox_enabled,
            "sandbox_duration_hours": group.sandbox_duration_hours,
            "link_whitelist": group.link_whitelist,
            "language": group.language,
            "linked_channel_id": group.linked_channel_id,
        }

    async def update_settings(
        self,
        chat_id: int,
        *,
        group_type: GroupType | None = None,
        sensitivity: int | None = None,
        sandbox_enabled: bool | None = None,
        sandbox_duration_hours: int | None = None,
        link_whitelist: list[str] | None = None,
        language: str | None = None,
        linked_channel_id: int | None = None,
    ) -> Group | None:
        """Update group settings.

        Only updates settings that are explicitly provided (not None).

        Args:
            chat_id: Telegram chat_id
            group_type: Type affecting spam thresholds
            sensitivity: Detection sensitivity (1-10)
            sandbox_enabled: Whether sandbox mode is active
            sandbox_duration_hours: Duration of sandbox period
            link_whitelist: List of whitelisted domains
            language: Primary group language
            linked_channel_id: Channel for subscription checks

        Returns:
            Updated Group instance, or None if not found

        Raises:
            ValueError: If sensitivity is out of range (1-10)

        Example:
            >>> group = await repo.update_settings(
            ...     chat_id=-1001234567890,
            ...     sensitivity=7,
            ...     sandbox_enabled=True,
            ... )
        """
        if sensitivity is not None and not (1 <= sensitivity <= 10):
            raise ValueError("Sensitivity must be between 1 and 10")

        group = await self.get_by_id(chat_id)
        if group is None:
            return None

        if group_type is not None:
            group.group_type = group_type
        if sensitivity is not None:
            group.sensitivity = sensitivity
        if sandbox_enabled is not None:
            group.sandbox_enabled = sandbox_enabled
        if sandbox_duration_hours is not None:
            group.sandbox_duration_hours = sandbox_duration_hours
        if link_whitelist is not None:
            group.link_whitelist = link_whitelist
        if language is not None:
            group.language = language
        if linked_channel_id is not None:
            group.linked_channel_id = linked_channel_id

        await self.session.flush()
        await self.session.refresh(group)
        return group

    async def increment_blocked_count(
        self,
        chat_id: int,
        amount: int = 1,
    ) -> bool:
        """Increment the blocked spam counter for a group.

        Uses atomic UPDATE to avoid race conditions in concurrent
        spam detection.

        Args:
            chat_id: Telegram chat_id
            amount: Amount to increment by (default 1)

        Returns:
            True if group was found and updated, False otherwise

        Example:
            >>> await repo.increment_blocked_count(-1001234567890)
        """
        stmt = (
            update(Group)
            .where(Group.id == chat_id)
            .values(blocked_count=Group.blocked_count + amount)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def update_members_count(
        self,
        chat_id: int,
        members_count: int,
    ) -> bool:
        """Update the cached member count for a group.

        Args:
            chat_id: Telegram chat_id
            members_count: New member count

        Returns:
            True if group was found and updated, False otherwise
        """
        stmt = update(Group).where(Group.id == chat_id).values(members_count=members_count)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def set_active(
        self,
        chat_id: int,
        is_active: bool,
    ) -> bool:
        """Set the active status of a group.

        Use this when the bot is kicked from a group or re-added.

        Args:
            chat_id: Telegram chat_id
            is_active: Whether bot is active in this group

        Returns:
            True if group was found and updated, False otherwise
        """
        stmt = update(Group).where(Group.id == chat_id).values(is_active=is_active)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def get_active_groups(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Group]:
        """Get all active groups.

        Args:
            limit: Maximum number of groups to return
            offset: Number of groups to skip

        Returns:
            List of active Group instances
        """
        stmt = select(Group).where(Group.is_active == True)  # noqa: E712
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_groups_by_type(
        self,
        group_type: GroupType,
        *,
        active_only: bool = True,
    ) -> list[Group]:
        """Get all groups of a specific type.

        Args:
            group_type: Type of groups to retrieve
            active_only: If True, only return active groups

        Returns:
            List of Group instances matching the type
        """
        stmt = select(Group).where(Group.group_type == group_type)
        if active_only:
            stmt = stmt.where(Group.is_active == True)  # noqa: E712
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_to_whitelist(
        self,
        chat_id: int,
        domain: str,
    ) -> bool:
        """Add a domain to the group's link whitelist.

        Args:
            chat_id: Telegram chat_id
            domain: Domain to whitelist (e.g., "github.com")

        Returns:
            True if added, False if group not found or already exists
        """
        group = await self.get_by_id(chat_id)
        if group is None:
            return False

        # Normalize domain
        domain = domain.lower().strip()
        if domain in group.link_whitelist:
            return False

        # Create new list with added domain
        new_whitelist = list(group.link_whitelist) + [domain]
        group.link_whitelist = new_whitelist
        await self.session.flush()
        return True

    async def remove_from_whitelist(
        self,
        chat_id: int,
        domain: str,
    ) -> bool:
        """Remove a domain from the group's link whitelist.

        Args:
            chat_id: Telegram chat_id
            domain: Domain to remove

        Returns:
            True if removed, False if group not found or not in list
        """
        group = await self.get_by_id(chat_id)
        if group is None:
            return False

        domain = domain.lower().strip()
        if domain not in group.link_whitelist:
            return False

        # Create new list without the domain
        new_whitelist = [d for d in group.link_whitelist if d != domain]
        group.link_whitelist = new_whitelist
        await self.session.flush()
        return True

    async def get_stats(
        self,
        chat_id: int,
    ) -> dict[str, Any] | None:
        """Get group statistics.

        Args:
            chat_id: Telegram chat_id

        Returns:
            Dictionary with stats, or None if group not found
        """
        group = await self.get_by_id(chat_id)
        if group is None:
            return None

        return {
            "members_count": group.members_count,
            "blocked_count": group.blocked_count,
            "created_at": group.created_at,
            "is_active": group.is_active,
        }

    # =========================================================================
    # Explicit relationship loading methods
    # These methods are required since relationships use lazy="raise"
    # =========================================================================

    async def get_by_id_with_members(
        self,
        chat_id: int,
    ) -> Group | None:
        """Get group with eagerly loaded members.

        Args:
            chat_id: Telegram chat_id

        Returns:
            Group with loaded members, or None if not found
        """
        stmt = select(Group).options(selectinload(Group.members)).where(Group.id == chat_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_decisions(
        self,
        chat_id: int,
    ) -> Group | None:
        """Get group with eagerly loaded decisions.

        Note: This loads ALL decisions for the group. For large groups,
        consider using DecisionRepository.get_by_group() instead which
        supports pagination.

        Args:
            chat_id: Telegram chat_id

        Returns:
            Group with loaded decisions, or None if not found
        """
        stmt = select(Group).options(selectinload(Group.decisions)).where(Group.id == chat_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_admin_actions(
        self,
        chat_id: int,
    ) -> Group | None:
        """Get group with eagerly loaded admin actions.

        Args:
            chat_id: Telegram chat_id

        Returns:
            Group with loaded admin_actions, or None if not found
        """
        stmt = select(Group).options(selectinload(Group.admin_actions)).where(Group.id == chat_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_all_relations(
        self,
        chat_id: int,
    ) -> Group | None:
        """Get group with all relationships loaded.

        Use sparingly - this loads a lot of data.
        Prefer specific loading methods when possible.

        Args:
            chat_id: Telegram chat_id

        Returns:
            Group with all relationships loaded, or None if not found
        """
        stmt = (
            select(Group)
            .options(
                selectinload(Group.members),
                selectinload(Group.decisions),
                selectinload(Group.admin_actions),
            )
            .where(Group.id == chat_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_groups_with_members(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[Group]:
        """Get all active groups with members loaded.

        Args:
            limit: Maximum number of groups to return
            offset: Number of groups to skip

        Returns:
            Sequence of active Group instances with members loaded
        """
        stmt = (
            select(Group).options(selectinload(Group.members)).where(Group.is_active == True)  # noqa: E712
        )
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
