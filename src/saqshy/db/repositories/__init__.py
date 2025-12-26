"""Repository pattern implementations for SAQSHY.

This module provides data access layer abstractions that encapsulate
all database operations. Repositories handle:
- CRUD operations for all models
- Complex queries and aggregations
- Transaction management
- Type-safe query methods

Usage:
    >>> from saqshy.db import get_engine, get_session_factory
    >>> from saqshy.db.repositories import GroupRepository, UserRepository
    >>>
    >>> engine = get_engine(database_url)
    >>> session_factory = get_session_factory(engine)
    >>>
    >>> async with session_factory() as session:
    ...     group_repo = GroupRepository(session)
    ...     user_repo = UserRepository(session)
    ...
    ...     group, created = await group_repo.create_or_update(
    ...         chat_id=-1001234567890,
    ...         title="Python Developers",
    ...     )
    ...     await session.commit()
"""

from saqshy.db.repositories.base import BaseRepository
from saqshy.db.repositories.decisions import DecisionRepository, DecisionStats
from saqshy.db.repositories.group_members import GroupMemberRepository
from saqshy.db.repositories.groups import GroupRepository
from saqshy.db.repositories.users import UserRepository

__all__ = [
    # Base
    "BaseRepository",
    # Repositories
    "GroupRepository",
    "UserRepository",
    "GroupMemberRepository",
    "DecisionRepository",
    # Data classes
    "DecisionStats",
]
