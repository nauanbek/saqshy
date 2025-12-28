"""SQLAlchemy ORM models for SAQSHY.

This module defines all database tables using SQLAlchemy 2.0 declarative style
with Mapped type hints for full type safety and IDE support.

Tables:
    - groups: Telegram group configurations and settings
    - users: Telegram user profiles (cached)
    - group_members: User membership and trust tracking per group
    - decisions: Spam detection decisions and audit log
    - admin_actions: Admin action audit log
    - spam_patterns: Known spam patterns for ML training

Note: Domain enums (GroupType, Verdict) are imported from core/types.py
to maintain a single source of truth. Only DB-specific enums (TrustLevel)
are defined here.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Import domain types from canonical source (core/types.py)
from saqshy.core.types import GroupType, Verdict
from saqshy.db.database import Base

# =============================================================================
# DB-Specific Enums (not in core/types.py)
# =============================================================================


class TrustLevel(str, enum.Enum):
    """User trust level within a group.

    Trust levels progress from 'new' to 'trusted' as users demonstrate
    legitimate behavior. Higher trust = fewer restrictions.

    Note: This enum is DB-specific (tracks user progression within groups)
    and is defined here rather than in core/types.py.
    """

    NEW = "new"  # Just joined, no messages yet
    SANDBOX = "sandbox"  # In sandbox period, limited actions
    LIMITED = "limited"  # Past sandbox but still restricted
    TRUSTED = "trusted"  # Established member, minimal checks
    ADMIN = "admin"  # Group administrator, bypasses checks


# Note: Verdict enum is imported from core/types.py (canonical source)
# See core/types.py for the full verdict definitions


# =============================================================================
# Mixins
# =============================================================================


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamps.

    Both fields use timezone-aware timestamps with server-side defaults.
    updated_at is automatically updated on every row modification.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when the record was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the record was last updated",
    )


# =============================================================================
# Models
# =============================================================================


class Group(TimestampMixin, Base):
    """Telegram group configuration and settings.

    The primary key is the Telegram chat_id (BIGINT) which is assigned
    by Telegram and guaranteed to be unique.

    Attributes:
        id: Telegram chat_id
        title: Group display name
        username: Optional @username for public groups
        group_type: Type affecting spam thresholds
        linked_channel_id: Associated channel for subscription checks
        sensitivity: 1-10 scale for detection strictness
        sandbox_enabled: Whether sandbox mode is active
        sandbox_duration_hours: How long sandbox lasts
        link_whitelist: Array of whitelisted domains
        language: Primary language for the group
        members_count: Cached member count
        blocked_count: Number of blocked spam attempts
        is_active: Whether bot is active in this group
    """

    __tablename__ = "groups"

    # Primary key (Telegram chat_id)
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        doc="Telegram chat_id",
    )

    # Group info
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Group display name",
    )
    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Group @username (for public groups)",
    )

    # Group type context
    group_type: Mapped[GroupType] = mapped_column(
        Enum(
            GroupType,
            name="group_type_enum",
            create_constraint=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        default=GroupType.GENERAL,
        server_default="general",
        nullable=False,
        doc="Group type affecting spam detection thresholds",
    )
    linked_channel_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        doc="Linked channel ID for subscription checks",
    )

    # Settings
    sensitivity: Mapped[int] = mapped_column(
        Integer,
        default=5,
        server_default="5",
        nullable=False,
        doc="Detection sensitivity (1=lenient, 10=strict)",
    )
    sandbox_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        doc="Whether sandbox mode is enabled for new users",
    )
    sandbox_duration_hours: Mapped[int] = mapped_column(
        Integer,
        default=24,
        server_default="24",
        nullable=False,
        doc="Duration of sandbox period in hours",
    )
    link_whitelist: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=list,
        server_default="{}",
        nullable=False,
        doc="Array of whitelisted domains for links",
    )
    language: Mapped[str] = mapped_column(
        String(10),
        default="ru",
        server_default="ru",
        nullable=False,
        doc="Primary group language (ISO 639-1)",
    )

    # Statistics
    members_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Cached member count",
    )
    blocked_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Total spam messages blocked",
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        doc="Whether bot is active in this group",
    )

    # Relationships
    # NOTE: All relationships use lazy="raise" to prevent N+1 queries.
    # Use explicit loading (selectinload/joinedload) in repositories when needed.
    members: Mapped[list[GroupMember]] = relationship(
        "GroupMember",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    decisions: Mapped[list[Decision]] = relationship(
        "Decision",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    admin_actions: Mapped[list[AdminAction]] = relationship(
        "AdminAction",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "sensitivity >= 1 AND sensitivity <= 10",
            name="ck_groups_sensitivity_range",
        ),
    )

    def __repr__(self) -> str:
        return f"Group(id={self.id}, title={self.title!r}, group_type={self.group_type.value})"


class User(Base):
    """Telegram user profile (cached data).

    Stores basic user profile information fetched from Telegram API.
    This data is periodically refreshed and used for profile-based
    spam signals.

    Attributes:
        id: Telegram user_id
        username: Optional @username
        first_name: User's first name
        last_name: Optional last name
        has_photo: Whether user has profile photo
        is_premium: Whether user has Telegram Premium
        bio: User bio text (fetched via getChat)
        account_age_days: Estimated account age in days
        first_seen_at: When we first saw this user
        updated_at: When profile was last updated
    """

    __tablename__ = "users"

    # Primary key (Telegram user_id)
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        doc="Telegram user_id",
    )

    # Profile info
    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Telegram @username",
    )
    first_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="User's first name",
    )
    last_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="User's last name",
    )

    # Profile data (cached from Telegram)
    has_photo: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        doc="Whether user has profile photo",
    )
    is_premium: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        doc="Whether user has Telegram Premium",
    )
    bio: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="User bio text",
    )

    # Calculated fields
    account_age_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc="Estimated account age in days",
    )

    # Timestamps
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="When we first encountered this user",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="When profile was last updated",
    )

    # Relationships
    # NOTE: All relationships use lazy="raise" to prevent N+1 queries.
    # Use explicit loading (selectinload/joinedload) in repositories when needed.
    memberships: Mapped[list[GroupMember]] = relationship(
        "GroupMember",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    decisions: Mapped[list[Decision]] = relationship(
        "Decision",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:
        name = self.username or self.first_name or str(self.id)
        return f"User(id={self.id}, name={name!r})"

    @property
    def display_name(self) -> str:
        """Return the best available display name for the user."""
        if self.first_name:
            if self.last_name:
                return f"{self.first_name} {self.last_name}"
            return self.first_name
        if self.username:
            return f"@{self.username}"
        return str(self.id)


class GroupMember(Base):
    """User membership and trust tracking within a group.

    This is a many-to-many association table between groups and users,
    with additional fields for tracking trust level and sandbox status.

    Attributes:
        group_id: Reference to groups.id
        user_id: Reference to users.id
        joined_at: When user joined the group
        first_message_at: When user sent their first message
        trust_level: Current trust level
        trust_score: Numeric trust score (0-100)
        sandbox_expires_at: When sandbox period ends
        messages_in_sandbox: Messages sent during sandbox
        message_count: Total messages sent
        last_message_at: When user last sent a message
    """

    __tablename__ = "group_members"

    # Composite primary key
    group_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
        doc="Reference to groups.id",
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        doc="Reference to users.id",
    )

    # Join info
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="When user joined the group",
    )
    first_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When user sent their first message",
    )

    # Trust status
    trust_level: Mapped[TrustLevel] = mapped_column(
        Enum(
            TrustLevel,
            name="trust_level_enum",
            create_constraint=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        default=TrustLevel.NEW,
        server_default="new",
        nullable=False,
        doc="User's trust level in this group",
    )
    trust_score: Mapped[int] = mapped_column(
        Integer,
        default=50,
        server_default="50",
        nullable=False,
        doc="Numeric trust score (0-100)",
    )

    # Sandbox tracking
    sandbox_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When sandbox period expires",
    )
    messages_in_sandbox: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Number of messages sent during sandbox",
    )

    # Activity stats
    message_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Total messages sent in this group",
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When user last sent a message",
    )

    # Relationships
    # NOTE: All relationships use lazy="raise" to prevent N+1 queries.
    # Use explicit loading (selectinload/joinedload) in repositories when needed.
    group: Mapped[Group] = relationship(
        "Group",
        back_populates="members",
        lazy="raise",
    )
    user: Mapped[User] = relationship(
        "User",
        back_populates="memberships",
        lazy="raise",
    )

    # Indexes
    __table_args__ = (
        Index(
            "idx_group_members_trust",
            "group_id",
            "trust_level",
            postgresql_using="btree",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"GroupMember(group_id={self.group_id}, user_id={self.user_id}, "
            f"trust_level={self.trust_level.value})"
        )

    @property
    def is_in_sandbox(self) -> bool:
        """Check if user is currently in sandbox period."""
        if self.sandbox_expires_at is None:
            return False
        return datetime.now(UTC) < self.sandbox_expires_at


class Decision(Base):
    """Spam detection decision and audit log.

    Records every spam detection decision made by the system,
    including the signals that contributed to the decision and
    any admin overrides.

    Attributes:
        id: UUID primary key
        group_id: Reference to groups.id
        user_id: Reference to users.id
        message_id: Telegram message_id
        risk_score: Calculated risk score (0-100)
        verdict: Final verdict (allow/watch/limit/review/block)
        threat_type: Type of detected threat
        profile_signals: JSONB of profile-based signals
        content_signals: JSONB of content-based signals
        behavior_signals: JSONB of behavior-based signals
        llm_used: Whether LLM was consulted
        llm_response: JSONB of LLM response (if used)
        llm_latency_ms: LLM response time in milliseconds
        action_taken: Description of action taken
        message_deleted: Whether message was deleted
        user_banned: Whether user was banned
        user_restricted: Whether user was restricted
        overridden_by: Admin who overrode the decision
        overridden_at: When decision was overridden
        override_reason: Reason for override
        created_at: When decision was made
        processing_time_ms: Total processing time
    """

    __tablename__ = "decisions"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.uuid_generate_v4(),
        doc="Unique decision identifier",
    )

    # References
    group_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Reference to groups.id",
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Reference to users.id",
    )
    message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        doc="Telegram message_id",
    )

    # Decision data
    risk_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Calculated risk score (0-100)",
    )
    verdict: Mapped[Verdict] = mapped_column(
        Enum(
            Verdict,
            name="verdict_enum",
            create_constraint=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        doc="Final verdict",
    )
    threat_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="Type of detected threat (spam, scam, phishing, etc.)",
    )

    # Signal breakdown (JSONB for flexibility)
    profile_signals: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
        doc="Profile-based signals and scores",
    )
    content_signals: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
        doc="Content-based signals and scores",
    )
    behavior_signals: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
        doc="Behavior-based signals and scores",
    )

    # LLM analysis (if used)
    llm_used: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Whether LLM was consulted for this decision",
    )
    llm_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="LLM response payload",
    )
    llm_latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc="LLM response time in milliseconds",
    )

    # Action taken
    action_taken: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="Description of action taken",
    )
    message_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Whether message was deleted",
    )
    user_banned: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Whether user was banned",
    )
    user_restricted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Whether user was restricted",
    )

    # Admin override
    overridden_by: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        doc="Admin user_id who overrode the decision",
    )
    overridden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="When decision was overridden",
    )
    override_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Reason for override",
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="When decision was made",
    )
    processing_time_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc="Total processing time in milliseconds",
    )

    # Relationships
    # NOTE: All relationships use lazy="raise" to prevent N+1 queries.
    # Use explicit loading (selectinload/joinedload) in repositories when needed.
    group: Mapped[Group] = relationship(
        "Group",
        back_populates="decisions",
        lazy="raise",
    )
    user: Mapped[User] = relationship(
        "User",
        back_populates="decisions",
        lazy="raise",
    )

    # Indexes for common queries
    __table_args__ = (
        Index(
            "idx_decisions_group_created",
            "group_id",
            created_at.desc(),
            postgresql_using="btree",
        ),
        Index(
            "idx_decisions_user_created",
            "user_id",
            created_at.desc(),
            postgresql_using="btree",
        ),
        Index(
            "idx_decisions_verdict_created",
            "verdict",
            created_at.desc(),
            postgresql_using="btree",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"Decision(id={self.id}, group_id={self.group_id}, "
            f"verdict={self.verdict.value}, risk_score={self.risk_score})"
        )


class AdminAction(Base):
    """Admin action audit log.

    Records all administrative actions taken in groups for
    accountability and debugging purposes.

    Attributes:
        id: UUID primary key
        group_id: Reference to groups.id
        admin_id: Telegram user_id of admin
        action_type: Type of action performed
        target_user_id: User affected by the action (if applicable)
        details: JSONB with additional action details
        created_at: When action was performed
    """

    __tablename__ = "admin_actions"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.uuid_generate_v4(),
        doc="Unique action identifier",
    )

    # References
    group_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Reference to groups.id",
    )
    admin_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
        doc="Telegram user_id of admin performing the action",
    )

    # Action data
    action_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Type of action (e.g., 'override', 'ban', 'unban', 'settings_change')",
    )
    target_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        doc="User affected by the action",
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
        doc="Additional action details",
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="When action was performed",
    )

    # Relationships
    # NOTE: All relationships use lazy="raise" to prevent N+1 queries.
    # Use explicit loading (selectinload/joinedload) in repositories when needed.
    group: Mapped[Group] = relationship(
        "Group",
        back_populates="admin_actions",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return (
            f"AdminAction(id={self.id}, group_id={self.group_id}, action_type={self.action_type!r})"
        )


class SpamPattern(Base):
    """Known spam pattern for ML training and similarity matching.

    Stores confirmed spam patterns with their embeddings for use
    in similarity-based spam detection via Qdrant vector search.

    Attributes:
        id: UUID primary key
        text_hash: SHA-256 hash of original text (unique)
        original_text: The spam message text
        embedding_id: Reference to Qdrant point ID
        threat_type: Classification of the threat
        confidence: Confidence score (0.0-1.0)
        detection_count: How many times this pattern was detected
        first_seen_at: When pattern was first detected
        last_seen_at: When pattern was last detected
        reported_by_group_id: Group that first reported this pattern
        verified: Whether pattern was manually verified
    """

    __tablename__ = "spam_patterns"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=func.uuid_generate_v4(),
        doc="Unique pattern identifier",
    )

    # Pattern identification
    text_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        doc="SHA-256 hash of original_text",
    )
    original_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="The spam message text",
    )
    embedding_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="Reference to Qdrant point ID",
    )

    # Classification
    threat_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Type of threat (spam, scam, phishing, promotion, etc.)",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Classification confidence (0.0-1.0)",
    )

    # Statistics
    detection_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        doc="Number of times this pattern was detected",
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="When pattern was first detected",
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="When pattern was last detected",
    )

    # Source tracking
    reported_by_group_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        doc="Group that first reported this pattern",
    )
    verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Whether pattern was manually verified by admin",
    )

    # Indexes
    __table_args__ = (
        Index(
            "idx_spam_patterns_hash",
            "text_hash",
            postgresql_using="btree",
        ),
        Index(
            "idx_spam_patterns_type",
            "threat_type",
            postgresql_using="btree",
        ),
    )

    def __repr__(self) -> str:
        preview = (
            self.original_text[:30] + "..." if len(self.original_text) > 30 else self.original_text
        )
        return f"SpamPattern(id={self.id}, threat_type={self.threat_type!r}, preview={preview!r})"
