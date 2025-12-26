"""Initial database schema for SAQSHY.

Revision ID: 001_initial
Revises:
Create Date: 2024-12-25

This migration creates the complete initial schema including:
- PostgreSQL extensions (uuid-ossp, pg_trgm)
- Enum types (group_type, trust_level, verdict)
- All tables (groups, users, group_members, decisions, admin_actions, spam_patterns)
- All indexes for optimized query performance
- Full-text search index on spam_patterns
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create initial database schema."""
    # ==========================================================================
    # PostgreSQL Extensions
    # ==========================================================================
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')

    # ==========================================================================
    # Enum Types
    # ==========================================================================
    group_type_enum = postgresql.ENUM(
        "general",
        "tech",
        "deals",
        "crypto",
        name="group_type_enum",
        create_type=False,
    )
    group_type_enum.create(op.get_bind(), checkfirst=True)

    trust_level_enum = postgresql.ENUM(
        "new",
        "sandbox",
        "limited",
        "trusted",
        "admin",
        name="trust_level_enum",
        create_type=False,
    )
    trust_level_enum.create(op.get_bind(), checkfirst=True)

    verdict_enum = postgresql.ENUM(
        "allow",
        "watch",
        "limit",
        "review",
        "block",
        name="verdict_enum",
        create_type=False,
    )
    verdict_enum.create(op.get_bind(), checkfirst=True)

    # ==========================================================================
    # Table: groups
    # ==========================================================================
    op.create_table(
        "groups",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="Telegram chat_id"),
        sa.Column("title", sa.String(255), nullable=False, comment="Group display name"),
        sa.Column(
            "username",
            sa.String(255),
            nullable=True,
            comment="Group @username (for public groups)",
        ),
        sa.Column(
            "group_type",
            group_type_enum,
            nullable=False,
            server_default="general",
            comment="Group type affecting spam detection thresholds",
        ),
        sa.Column(
            "linked_channel_id",
            sa.BigInteger(),
            nullable=True,
            comment="Linked channel ID for subscription checks",
        ),
        sa.Column(
            "sensitivity",
            sa.Integer(),
            nullable=False,
            server_default="5",
            comment="Detection sensitivity (1=lenient, 10=strict)",
        ),
        sa.Column(
            "sandbox_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="Whether sandbox mode is enabled for new users",
        ),
        sa.Column(
            "sandbox_duration_hours",
            sa.Integer(),
            nullable=False,
            server_default="24",
            comment="Duration of sandbox period in hours",
        ),
        sa.Column(
            "link_whitelist",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Array of whitelisted domains for links",
        ),
        sa.Column(
            "language",
            sa.String(10),
            nullable=False,
            server_default="ru",
            comment="Primary group language (ISO 639-1)",
        ),
        sa.Column(
            "members_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Cached member count",
        ),
        sa.Column(
            "blocked_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Total spam messages blocked",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="Timestamp when the record was created",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="Timestamp when the record was last updated",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="Whether bot is active in this group",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "sensitivity >= 1 AND sensitivity <= 10",
            name="ck_groups_sensitivity_range",
        ),
    )

    # ==========================================================================
    # Table: users
    # ==========================================================================
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False, comment="Telegram user_id"),
        sa.Column("username", sa.String(255), nullable=True, comment="Telegram @username"),
        sa.Column("first_name", sa.String(255), nullable=True, comment="User's first name"),
        sa.Column("last_name", sa.String(255), nullable=True, comment="User's last name"),
        sa.Column(
            "has_photo",
            sa.Boolean(),
            nullable=True,
            comment="Whether user has profile photo",
        ),
        sa.Column(
            "is_premium",
            sa.Boolean(),
            nullable=True,
            comment="Whether user has Telegram Premium",
        ),
        sa.Column("bio", sa.Text(), nullable=True, comment="User bio text"),
        sa.Column(
            "account_age_days",
            sa.Integer(),
            nullable=True,
            comment="Estimated account age in days",
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="When we first encountered this user",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="When profile was last updated",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ==========================================================================
    # Table: group_members
    # ==========================================================================
    op.create_table(
        "group_members",
        sa.Column(
            "group_id",
            sa.BigInteger(),
            nullable=False,
            comment="Reference to groups.id",
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
            comment="Reference to users.id",
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="When user joined the group",
        ),
        sa.Column(
            "first_message_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When user sent their first message",
        ),
        sa.Column(
            "trust_level",
            trust_level_enum,
            nullable=False,
            server_default="new",
            comment="User's trust level in this group",
        ),
        sa.Column(
            "trust_score",
            sa.Integer(),
            nullable=False,
            server_default="50",
            comment="Numeric trust score (0-100)",
        ),
        sa.Column(
            "sandbox_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When sandbox period expires",
        ),
        sa.Column(
            "messages_in_sandbox",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Number of messages sent during sandbox",
        ),
        sa.Column(
            "message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Total messages sent in this group",
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When user last sent a message",
        ),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name="fk_group_members_group_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_group_members_user_id",
            ondelete="CASCADE",
        ),
    )

    # Index for querying members by trust level
    op.create_index(
        "idx_group_members_trust",
        "group_members",
        ["group_id", "trust_level"],
        postgresql_using="btree",
    )

    # ==========================================================================
    # Table: decisions
    # ==========================================================================
    op.create_table(
        "decisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Unique decision identifier",
        ),
        sa.Column(
            "group_id",
            sa.BigInteger(),
            nullable=False,
            comment="Reference to groups.id",
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            nullable=False,
            comment="Reference to users.id",
        ),
        sa.Column(
            "message_id",
            sa.BigInteger(),
            nullable=True,
            comment="Telegram message_id",
        ),
        sa.Column(
            "risk_score",
            sa.Integer(),
            nullable=False,
            comment="Calculated risk score (0-100)",
        ),
        sa.Column(
            "verdict",
            verdict_enum,
            nullable=False,
            comment="Final verdict",
        ),
        sa.Column(
            "threat_type",
            sa.String(50),
            nullable=True,
            comment="Type of detected threat (spam, scam, phishing, etc.)",
        ),
        sa.Column(
            "profile_signals",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Profile-based signals and scores",
        ),
        sa.Column(
            "content_signals",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Content-based signals and scores",
        ),
        sa.Column(
            "behavior_signals",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Behavior-based signals and scores",
        ),
        sa.Column(
            "llm_used",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Whether LLM was consulted for this decision",
        ),
        sa.Column(
            "llm_response",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="LLM response payload",
        ),
        sa.Column(
            "llm_latency_ms",
            sa.Integer(),
            nullable=True,
            comment="LLM response time in milliseconds",
        ),
        sa.Column(
            "action_taken",
            sa.String(50),
            nullable=True,
            comment="Description of action taken",
        ),
        sa.Column(
            "message_deleted",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Whether message was deleted",
        ),
        sa.Column(
            "user_banned",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Whether user was banned",
        ),
        sa.Column(
            "user_restricted",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Whether user was restricted",
        ),
        sa.Column(
            "overridden_by",
            sa.BigInteger(),
            nullable=True,
            comment="Admin user_id who overrode the decision",
        ),
        sa.Column(
            "overridden_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When decision was overridden",
        ),
        sa.Column(
            "override_reason",
            sa.Text(),
            nullable=True,
            comment="Reason for override",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="When decision was made",
        ),
        sa.Column(
            "processing_time_ms",
            sa.Integer(),
            nullable=True,
            comment="Total processing time in milliseconds",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name="fk_decisions_group_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_decisions_user_id",
            ondelete="CASCADE",
        ),
    )

    # Indexes for common query patterns
    op.create_index(
        "idx_decisions_group_created",
        "decisions",
        ["group_id", sa.text("created_at DESC")],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_decisions_user_created",
        "decisions",
        ["user_id", sa.text("created_at DESC")],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_decisions_verdict_created",
        "decisions",
        ["verdict", sa.text("created_at DESC")],
        postgresql_using="btree",
    )

    # ==========================================================================
    # Table: admin_actions
    # ==========================================================================
    op.create_table(
        "admin_actions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Unique action identifier",
        ),
        sa.Column(
            "group_id",
            sa.BigInteger(),
            nullable=False,
            comment="Reference to groups.id",
        ),
        sa.Column(
            "admin_id",
            sa.BigInteger(),
            nullable=False,
            comment="Telegram user_id of admin performing the action",
        ),
        sa.Column(
            "action_type",
            sa.String(50),
            nullable=False,
            comment="Type of action (e.g., 'override', 'ban', 'unban', 'settings_change')",
        ),
        sa.Column(
            "target_user_id",
            sa.BigInteger(),
            nullable=True,
            comment="User affected by the action",
        ),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="Additional action details",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="When action was performed",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name="fk_admin_actions_group_id",
            ondelete="CASCADE",
        ),
    )

    # Index for querying admin actions by group and admin
    op.create_index(
        "idx_admin_actions_group_id",
        "admin_actions",
        ["group_id"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_admin_actions_admin_id",
        "admin_actions",
        ["admin_id"],
        postgresql_using="btree",
    )

    # ==========================================================================
    # Table: spam_patterns
    # ==========================================================================
    op.create_table(
        "spam_patterns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Unique pattern identifier",
        ),
        sa.Column(
            "text_hash",
            sa.String(64),
            nullable=False,
            unique=True,
            comment="SHA-256 hash of original_text",
        ),
        sa.Column(
            "original_text",
            sa.Text(),
            nullable=False,
            comment="The spam message text",
        ),
        sa.Column(
            "embedding_id",
            sa.String(64),
            nullable=True,
            comment="Reference to Qdrant point ID",
        ),
        sa.Column(
            "threat_type",
            sa.String(50),
            nullable=False,
            comment="Type of threat (spam, scam, phishing, promotion, etc.)",
        ),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            comment="Classification confidence (0.0-1.0)",
        ),
        sa.Column(
            "detection_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="Number of times this pattern was detected",
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="When pattern was first detected",
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="When pattern was last detected",
        ),
        sa.Column(
            "reported_by_group_id",
            sa.BigInteger(),
            nullable=True,
            comment="Group that first reported this pattern",
        ),
        sa.Column(
            "verified",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Whether pattern was manually verified by admin",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Indexes for spam patterns
    op.create_index(
        "idx_spam_patterns_hash",
        "spam_patterns",
        ["text_hash"],
        postgresql_using="btree",
    )
    op.create_index(
        "idx_spam_patterns_type",
        "spam_patterns",
        ["threat_type"],
        postgresql_using="btree",
    )

    # Full-text search index for Russian text
    op.execute("""
        CREATE INDEX idx_spam_patterns_text
        ON spam_patterns
        USING gin(to_tsvector('russian', original_text))
    """)


def downgrade() -> None:
    """Drop all tables and types in reverse order."""
    # Drop full-text search index first
    op.execute("DROP INDEX IF EXISTS idx_spam_patterns_text")

    # Drop tables in reverse dependency order
    op.drop_table("spam_patterns")
    op.drop_table("admin_actions")
    op.drop_table("decisions")
    op.drop_table("group_members")
    op.drop_table("users")
    op.drop_table("groups")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS verdict_enum")
    op.execute("DROP TYPE IF EXISTS trust_level_enum")
    op.execute("DROP TYPE IF EXISTS group_type_enum")

    # Note: We don't drop the uuid-ossp and pg_trgm extensions
    # as they might be used by other applications in the same database
