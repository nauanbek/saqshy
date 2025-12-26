"""Base repository class with common CRUD operations.

This module provides a generic base repository that implements common
database operations using SQLAlchemy async sessions. All specific
repositories should inherit from BaseRepository.

Example:
    >>> class UserRepository(BaseRepository[User]):
    ...     def __init__(self, session: AsyncSession):
    ...         super().__init__(session, User)
    ...
    ...     async def find_by_username(self, username: str) -> User | None:
    ...         stmt = select(User).where(User.username == username)
    ...         result = await self.session.execute(stmt)
    ...         return result.scalar_one_or_none()
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from saqshy.db.database import Base

# Type variable for model classes
ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Generic base repository for database operations.

    Provides common CRUD operations that work with any SQLAlchemy model.
    Subclasses should define model-specific query methods.

    Attributes:
        session: SQLAlchemy async session for database operations
        model_class: The SQLAlchemy model class this repository manages

    Type Parameters:
        ModelT: The SQLAlchemy model type (must inherit from Base)
    """

    def __init__(self, session: AsyncSession, model_class: type[ModelT]) -> None:
        """Initialize repository with session and model class.

        Args:
            session: SQLAlchemy async session
            model_class: The model class to work with
        """
        self.session = session
        self.model_class = model_class

    async def get_by_id(self, id: int | str) -> ModelT | None:
        """Get a record by its primary key.

        Args:
            id: Primary key value (int for Telegram IDs, str for UUIDs)

        Returns:
            Model instance if found, None otherwise
        """
        return await self.session.get(self.model_class, id)

    async def get_all(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Sequence[ModelT]:
        """Get all records with optional pagination.

        Args:
            limit: Maximum number of records to return
            offset: Number of records to skip

        Returns:
            Sequence of model instances
        """
        stmt: Select[tuple[ModelT]] = select(self.model_class)
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self) -> int:
        """Get total count of records.

        Returns:
            Number of records in the table
        """
        stmt = select(func.count()).select_from(self.model_class)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def create(self, **kwargs: Any) -> ModelT:
        """Create a new record.

        Args:
            **kwargs: Column values for the new record

        Returns:
            The created model instance

        Raises:
            IntegrityError: If constraints are violated
        """
        instance = self.model_class(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(
        self,
        id: int | str,
        **kwargs: Any,
    ) -> ModelT | None:
        """Update an existing record by ID.

        Args:
            id: Primary key of record to update
            **kwargs: Column values to update

        Returns:
            Updated model instance if found, None otherwise
        """
        instance = await self.get_by_id(id)
        if instance is None:
            return None

        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)

        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, id: int | str) -> bool:
        """Delete a record by ID.

        Args:
            id: Primary key of record to delete

        Returns:
            True if record was deleted, False if not found
        """
        instance = await self.get_by_id(id)
        if instance is None:
            return False

        await self.session.delete(instance)
        await self.session.flush()
        return True

    async def exists(self, id: int | str) -> bool:
        """Check if a record with given ID exists.

        Args:
            id: Primary key to check

        Returns:
            True if record exists, False otherwise
        """
        instance = await self.get_by_id(id)
        return instance is not None

    async def upsert(
        self,
        id: int | str,
        **kwargs: Any,
    ) -> tuple[ModelT, bool]:
        """Insert or update a record.

        If a record with the given ID exists, update it.
        Otherwise, create a new record.

        Args:
            id: Primary key value
            **kwargs: Column values

        Returns:
            Tuple of (model instance, created flag)
            created is True if new record was created, False if updated
        """
        instance = await self.get_by_id(id)
        if instance is not None:
            # Update existing
            for key, value in kwargs.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            await self.session.flush()
            await self.session.refresh(instance)
            return instance, False
        else:
            # Create new - include the ID in kwargs
            # Get the primary key column name(s)
            pk_columns = [col.name for col in self.model_class.__table__.primary_key.columns]
            if len(pk_columns) == 1:
                kwargs[pk_columns[0]] = id
            instance = await self.create(**kwargs)
            return instance, True

    async def commit(self) -> None:
        """Commit the current transaction.

        Use this when you want to persist changes immediately.
        For most cases, let the session context manager handle commits.
        """
        await self.session.commit()

    async def rollback(self) -> None:
        """Rollback the current transaction.

        Use this to undo uncommitted changes on error.
        """
        await self.session.rollback()
