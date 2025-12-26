"""Repository for user operations.

This module provides data access methods for the users table,
handling Telegram user profile caching and updates.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from saqshy.db.models import User
from saqshy.db.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User model operations.

    Handles all database operations related to Telegram users,
    including profile caching and updates.

    Example:
        >>> async with session_factory() as session:
        ...     repo = UserRepository(session)
        ...     user = await repo.get_by_id(123456789)
        ...     if user:
        ...         print(f"User: {user.display_name}")
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with session.

        Args:
            session: SQLAlchemy async session
        """
        super().__init__(session, User)

    async def create_or_update(
        self,
        user_id: int,
        *,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        has_photo: bool | None = None,
        is_premium: bool | None = None,
        bio: str | None = None,
        account_age_days: int | None = None,
    ) -> tuple[User, bool]:
        """Create a new user or update existing one.

        This is the primary method for caching user profile data
        received from Telegram API.

        Args:
            user_id: Telegram user_id
            username: Optional @username
            first_name: User's first name
            last_name: User's last name
            has_photo: Whether user has profile photo
            is_premium: Whether user has Telegram Premium
            bio: User bio text
            account_age_days: Estimated account age

        Returns:
            Tuple of (User instance, created flag)
            created is True if new user was created

        Example:
            >>> user, created = await repo.create_or_update(
            ...     user_id=123456789,
            ...     username="johndoe",
            ...     first_name="John",
            ... )
        """
        existing = await self.get_by_id(user_id)

        kwargs: dict[str, Any] = {}
        if username is not None:
            kwargs["username"] = username
        if first_name is not None:
            kwargs["first_name"] = first_name
        if last_name is not None:
            kwargs["last_name"] = last_name
        if has_photo is not None:
            kwargs["has_photo"] = has_photo
        if is_premium is not None:
            kwargs["is_premium"] = is_premium
        if bio is not None:
            kwargs["bio"] = bio
        if account_age_days is not None:
            kwargs["account_age_days"] = account_age_days

        if existing is not None:
            # Update existing user
            for key, value in kwargs.items():
                setattr(existing, key, value)
            existing.updated_at = datetime.now(UTC)
            await self.session.flush()
            await self.session.refresh(existing)
            return existing, False
        else:
            # Create new user
            kwargs["id"] = user_id
            user = await self.create(**kwargs)
            return user, True

    async def update_profile(
        self,
        user_id: int,
        *,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        has_photo: bool | None = None,
        is_premium: bool | None = None,
        bio: str | None = None,
        account_age_days: int | None = None,
    ) -> User | None:
        """Update user profile data.

        Only updates fields that are explicitly provided (not None).

        Args:
            user_id: Telegram user_id
            username: Optional @username
            first_name: User's first name
            last_name: User's last name
            has_photo: Whether user has profile photo
            is_premium: Whether user has Telegram Premium
            bio: User bio text
            account_age_days: Estimated account age

        Returns:
            Updated User instance, or None if not found

        Example:
            >>> user = await repo.update_profile(
            ...     user_id=123456789,
            ...     is_premium=True,
            ...     bio="Python developer",
            ... )
        """
        user = await self.get_by_id(user_id)
        if user is None:
            return None

        if username is not None:
            user.username = username
        if first_name is not None:
            user.first_name = first_name
        if last_name is not None:
            user.last_name = last_name
        if has_photo is not None:
            user.has_photo = has_photo
        if is_premium is not None:
            user.is_premium = is_premium
        if bio is not None:
            user.bio = bio
        if account_age_days is not None:
            user.account_age_days = account_age_days

        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def get_by_username(self, username: str) -> User | None:
        """Get user by username.

        Args:
            username: Telegram @username (with or without @)

        Returns:
            User instance if found, None otherwise
        """
        # Remove @ prefix if present
        username = username.lstrip("@")
        stmt = select(User).where(User.username == username)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_premium_users(
        self,
        *,
        limit: int | None = None,
    ) -> Sequence[User]:
        """Get all users with Telegram Premium.

        Args:
            limit: Maximum number of users to return

        Returns:
            Sequence of premium User instances
        """
        stmt = select(User).where(User.is_premium == True)  # noqa: E712
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_users_without_photo(
        self,
        *,
        limit: int | None = None,
    ) -> Sequence[User]:
        """Get users without profile photos.

        Useful for spam detection as many spam bots lack profile photos.

        Args:
            limit: Maximum number of users to return

        Returns:
            Sequence of User instances without photos
        """
        stmt = select(User).where(User.has_photo == False)  # noqa: E712
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_new_users(
        self,
        days: int = 7,
        *,
        limit: int | None = None,
    ) -> Sequence[User]:
        """Get users first seen within the specified number of days.

        Args:
            days: Number of days to look back
            limit: Maximum number of users to return

        Returns:
            Sequence of recently seen User instances
        """
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = select(User).where(User.first_seen_at >= cutoff).order_by(User.first_seen_at.desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_profile_for_analysis(
        self,
        user_id: int,
    ) -> dict[str, Any] | None:
        """Get user profile data formatted for spam analysis.

        Returns a dictionary suitable for passing to ProfileAnalyzer.

        Args:
            user_id: Telegram user_id

        Returns:
            Dictionary with profile signals, or None if not found
        """
        user = await self.get_by_id(user_id)
        if user is None:
            return None

        return {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "display_name": user.display_name,
            "has_photo": user.has_photo,
            "is_premium": user.is_premium,
            "bio": user.bio,
            "account_age_days": user.account_age_days,
            "first_seen_at": user.first_seen_at.isoformat() if user.first_seen_at else None,
        }

    async def bulk_get_by_ids(
        self,
        user_ids: list[int],
    ) -> dict[int, User]:
        """Get multiple users by their IDs.

        Args:
            user_ids: List of Telegram user_ids

        Returns:
            Dictionary mapping user_id to User instance
        """
        if not user_ids:
            return {}

        stmt = select(User).where(User.id.in_(user_ids))
        result = await self.session.execute(stmt)
        users = result.scalars().all()
        return {user.id: user for user in users}

    async def mark_stale_profiles(
        self,
        days: int = 7,
    ) -> int:
        """Get count of profiles that haven't been updated recently.

        Useful for scheduling profile refresh jobs.

        Args:
            days: Number of days since last update

        Returns:
            Count of stale profiles
        """
        from datetime import timedelta

        from sqlalchemy import func

        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = select(func.count()).select_from(User).where(User.updated_at < cutoff)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def search_by_name(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> Sequence[User]:
        """Search users by name or username.

        Uses case-insensitive ILIKE matching.

        Args:
            query: Search query
            limit: Maximum results to return

        Returns:
            Sequence of matching User instances
        """
        pattern = f"%{query}%"
        stmt = (
            select(User)
            .where(
                (User.first_name.ilike(pattern))
                | (User.last_name.ilike(pattern))
                | (User.username.ilike(pattern))
            )
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    # =========================================================================
    # Explicit relationship loading methods
    # These methods are required since relationships use lazy="raise"
    # =========================================================================

    async def get_by_id_with_memberships(
        self,
        user_id: int,
    ) -> User | None:
        """Get user with eagerly loaded group memberships.

        Args:
            user_id: Telegram user_id

        Returns:
            User with loaded memberships, or None if not found
        """
        stmt = select(User).options(selectinload(User.memberships)).where(User.id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_decisions(
        self,
        user_id: int,
    ) -> User | None:
        """Get user with eagerly loaded decisions.

        Note: This loads ALL decisions. For large histories,
        use DecisionRepository.get_by_user() which supports pagination.

        Args:
            user_id: Telegram user_id

        Returns:
            User with loaded decisions, or None if not found
        """
        stmt = select(User).options(selectinload(User.decisions)).where(User.id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_all_relations(
        self,
        user_id: int,
    ) -> User | None:
        """Get user with all relationships loaded.

        Use sparingly - this loads a lot of data.
        Prefer specific loading methods when possible.

        Args:
            user_id: Telegram user_id

        Returns:
            User with all relationships loaded, or None if not found
        """
        stmt = (
            select(User)
            .options(
                selectinload(User.memberships),
                selectinload(User.decisions),
            )
            .where(User.id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def bulk_get_by_ids_with_memberships(
        self,
        user_ids: list[int],
    ) -> dict[int, User]:
        """Get multiple users by their IDs with memberships loaded.

        Args:
            user_ids: List of Telegram user_ids

        Returns:
            Dictionary mapping user_id to User instance with memberships
        """
        if not user_ids:
            return {}

        stmt = select(User).options(selectinload(User.memberships)).where(User.id.in_(user_ids))
        result = await self.session.execute(stmt)
        users = result.scalars().all()
        return {user.id: user for user in users}
