"""Database module for SAQSHY.

This module provides:
- SQLAlchemy async engine and session management
- ORM models for all database tables
- Repository pattern for data access
- Alembic migrations

Note: GroupType and Verdict are re-exported from core/types.py (canonical source).
TrustLevel is defined in db/models.py as it's DB-specific.

Usage:
    >>> from saqshy.db import get_engine, get_session_factory
    >>> from saqshy.db import GroupRepository, UserRepository
    >>>
    >>> engine = get_engine("postgresql://user:pass@localhost/saqshy")
    >>> session_factory = get_session_factory(engine)
    >>>
    >>> async with session_factory() as session:
    ...     repo = GroupRepository(session)
    ...     group, created = await repo.create_or_update(
    ...         chat_id=-1001234567890,
    ...         title="Python Developers",
    ...     )
    ...     await session.commit()
"""

# Re-export domain types from canonical source (these are also re-exported by db/models.py)
from saqshy.core.types import GroupType, Verdict
from saqshy.db.database import (
    AsyncSessionFactory,
    Base,
    get_engine,
    get_session,
    get_session_factory,
)
from saqshy.db.models import (
    AdminAction,
    Decision,
    Group,
    GroupMember,
    SpamPattern,
    TrustLevel,
    User,
)
from saqshy.db.repositories import (
    BaseRepository,
    DecisionRepository,
    DecisionStats,
    GroupMemberRepository,
    GroupRepository,
    UserRepository,
)

__all__ = [
    # Database
    "Base",
    "get_engine",
    "get_session_factory",
    "get_session",
    "AsyncSessionFactory",
    # Models
    "Group",
    "User",
    "GroupMember",
    "Decision",
    "AdminAction",
    "SpamPattern",
    # Enums
    "GroupType",
    "TrustLevel",
    "Verdict",
    # Repositories
    "BaseRepository",
    "GroupRepository",
    "UserRepository",
    "GroupMemberRepository",
    "DecisionRepository",
    "DecisionStats",
]
