"""Integration tests for GroupMemberRepository.

Tests cover all repository methods for group membership management,
including trust levels, sandbox tracking, and activity monitoring.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from saqshy.core.types import GroupType
from saqshy.db.models import Group, GroupMember, TrustLevel, User
from saqshy.db.repositories.group_members import GroupMemberRepository
from saqshy.db.repositories.groups import GroupRepository
from saqshy.db.repositories.users import UserRepository


@pytest.mark.integration
class TestGroupMemberRepository:
    """Integration tests for GroupMemberRepository."""

    @pytest.fixture
    async def repo(self, db_session: AsyncSession) -> GroupMemberRepository:
        """Create repository instance with test session."""
        return GroupMemberRepository(db_session)

    @pytest.fixture
    async def group_repo(self, db_session: AsyncSession) -> GroupRepository:
        """Create GroupRepository for test data setup."""
        return GroupRepository(db_session)

    @pytest.fixture
    async def user_repo(self, db_session: AsyncSession) -> UserRepository:
        """Create UserRepository for test data setup."""
        return UserRepository(db_session)

    @pytest.fixture
    async def sample_group(self, group_repo: GroupRepository) -> Group:
        """Create a sample group for testing."""
        group, _ = await group_repo.create_or_update(
            chat_id=-1001234567890,
            title="Test Group",
            group_type=GroupType.GENERAL,
        )
        return group

    @pytest.fixture
    async def sample_user(self, user_repo: UserRepository) -> User:
        """Create a sample user for testing."""
        user, _ = await user_repo.create_or_update(
            user_id=123456789,
            username="testuser",
            first_name="Test",
            last_name="User",
        )
        return user

    @pytest.fixture
    async def sample_membership(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> GroupMember:
        """Create a sample membership for testing."""
        member, _ = await repo.create_or_update_member(
            group_id=sample_group.id,
            user_id=sample_user.id,
            trust_level=TrustLevel.NEW,
        )
        return member

    # =========================================================================
    # get_member tests
    # =========================================================================

    async def test_get_member(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test retrieving member by composite key."""
        found = await repo.get_member(
            sample_membership.group_id, sample_membership.user_id
        )

        assert found is not None
        assert found.group_id == sample_membership.group_id
        assert found.user_id == sample_membership.user_id

    async def test_get_member_returns_none_for_missing(
        self, repo: GroupMemberRepository, sample_group: Group
    ) -> None:
        """Test returns None for non-existent membership."""
        found = await repo.get_member(sample_group.id, 999999999)
        assert found is None

    # =========================================================================
    # create_or_update_member tests
    # =========================================================================

    async def test_create_or_update_creates_new_member(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test creating a new member."""
        member, created = await repo.create_or_update_member(
            group_id=sample_group.id,
            user_id=sample_user.id,
            trust_level=TrustLevel.LIMITED,
            trust_score=60,
        )

        assert created is True
        assert member.group_id == sample_group.id
        assert member.user_id == sample_user.id
        assert member.trust_level == TrustLevel.LIMITED
        assert member.trust_score == 60

    async def test_create_or_update_updates_existing_member(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test updating an existing member."""
        updated, created = await repo.create_or_update_member(
            group_id=sample_membership.group_id,
            user_id=sample_membership.user_id,
            trust_level=TrustLevel.TRUSTED,
            trust_score=90,
        )

        assert created is False
        assert updated.trust_level == TrustLevel.TRUSTED
        assert updated.trust_score == 90

    async def test_create_or_update_default_values(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test default values for new member."""
        member, created = await repo.create_or_update_member(
            group_id=sample_group.id,
            user_id=sample_user.id,
        )

        assert created is True
        assert member.trust_level == TrustLevel.NEW
        assert member.trust_score == 50
        assert member.sandbox_expires_at is None

    async def test_create_or_update_with_sandbox(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test creating member with sandbox expiration."""
        sandbox_expires = datetime.now(UTC) + timedelta(hours=24)

        member, created = await repo.create_or_update_member(
            group_id=sample_group.id,
            user_id=sample_user.id,
            trust_level=TrustLevel.SANDBOX,
            sandbox_expires_at=sandbox_expires,
        )

        assert created is True
        assert member.trust_level == TrustLevel.SANDBOX
        assert member.sandbox_expires_at is not None

    # =========================================================================
    # record_join tests
    # =========================================================================

    async def test_record_join_creates_new_member(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test recording a new join."""
        member = await repo.record_join(
            group_id=sample_group.id,
            user_id=sample_user.id,
            sandbox_hours=48,
            start_in_sandbox=True,
        )

        assert member.group_id == sample_group.id
        assert member.user_id == sample_user.id
        assert member.trust_level == TrustLevel.SANDBOX
        assert member.sandbox_expires_at is not None
        assert member.messages_in_sandbox == 0

    async def test_record_join_resets_returning_member(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test that rejoining resets sandbox status."""
        # First, update the member to have some history
        await repo.record_message(
            sample_membership.group_id, sample_membership.user_id
        )
        await repo.update_trust_level(
            sample_membership.group_id,
            sample_membership.user_id,
            TrustLevel.LIMITED,
        )

        # Now record a rejoin
        member = await repo.record_join(
            group_id=sample_membership.group_id,
            user_id=sample_membership.user_id,
            sandbox_hours=24,
            start_in_sandbox=True,
        )

        # Should be reset to sandbox
        assert member.trust_level == TrustLevel.SANDBOX
        assert member.messages_in_sandbox == 0
        assert member.first_message_at is None

    async def test_record_join_without_sandbox(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test joining without sandbox period."""
        member = await repo.record_join(
            group_id=sample_group.id,
            user_id=sample_user.id,
            start_in_sandbox=False,
        )

        assert member.trust_level == TrustLevel.NEW
        assert member.sandbox_expires_at is None

    # =========================================================================
    # record_message tests
    # =========================================================================

    async def test_record_message_updates_counts(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test recording a message updates counts."""
        initial_count = sample_membership.message_count

        member = await repo.record_message(
            sample_membership.group_id, sample_membership.user_id
        )

        assert member is not None
        assert member.message_count == initial_count + 1
        assert member.last_message_at is not None

    async def test_record_message_sets_first_message_at(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test that first message sets first_message_at."""
        assert sample_membership.first_message_at is None

        member = await repo.record_message(
            sample_membership.group_id, sample_membership.user_id
        )

        assert member is not None
        assert member.first_message_at is not None

    async def test_record_message_creates_missing_member(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test recording message for unknown member creates record."""
        member = await repo.record_message(sample_group.id, sample_user.id)

        assert member is not None
        assert member.trust_level == TrustLevel.NEW
        assert member.message_count == 1

    async def test_record_message_increments_sandbox_count(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test that messages in sandbox increment sandbox count."""
        # Create member in sandbox
        await repo.record_join(
            group_id=sample_group.id,
            user_id=sample_user.id,
            sandbox_hours=24,
            start_in_sandbox=True,
        )

        # Record messages
        await repo.record_message(sample_group.id, sample_user.id)
        member = await repo.record_message(sample_group.id, sample_user.id)

        assert member is not None
        assert member.messages_in_sandbox == 2

    # =========================================================================
    # update_trust_level tests
    # =========================================================================

    async def test_update_trust_level(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test updating trust level."""
        updated = await repo.update_trust_level(
            sample_membership.group_id,
            sample_membership.user_id,
            TrustLevel.TRUSTED,
        )

        assert updated is not None
        assert updated.trust_level == TrustLevel.TRUSTED

    async def test_update_trust_level_clears_sandbox(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test that promotion clears sandbox expiration."""
        # Create member in sandbox
        member = await repo.record_join(
            group_id=sample_group.id,
            user_id=sample_user.id,
            start_in_sandbox=True,
        )
        assert member.sandbox_expires_at is not None

        # Promote to LIMITED
        updated = await repo.update_trust_level(
            sample_group.id, sample_user.id, TrustLevel.LIMITED
        )

        assert updated is not None
        assert updated.sandbox_expires_at is None

    async def test_update_trust_level_returns_none_for_missing(
        self, repo: GroupMemberRepository, sample_group: Group
    ) -> None:
        """Test returns None for non-existent member."""
        result = await repo.update_trust_level(
            sample_group.id, 999999999, TrustLevel.TRUSTED
        )
        assert result is None

    # =========================================================================
    # update_trust_score tests
    # =========================================================================

    async def test_update_trust_score_positive(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test increasing trust score."""
        initial = sample_membership.trust_score

        updated = await repo.update_trust_score(
            sample_membership.group_id,
            sample_membership.user_id,
            delta=10,
        )

        assert updated is not None
        assert updated.trust_score == initial + 10

    async def test_update_trust_score_negative(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test decreasing trust score."""
        initial = sample_membership.trust_score

        updated = await repo.update_trust_score(
            sample_membership.group_id,
            sample_membership.user_id,
            delta=-20,
        )

        assert updated is not None
        assert updated.trust_score == initial - 20

    async def test_update_trust_score_capped_at_100(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test trust score is capped at 100."""
        updated = await repo.update_trust_score(
            sample_membership.group_id,
            sample_membership.user_id,
            delta=100,
        )

        assert updated is not None
        assert updated.trust_score == 100

    async def test_update_trust_score_capped_at_0(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test trust score is capped at 0."""
        updated = await repo.update_trust_score(
            sample_membership.group_id,
            sample_membership.user_id,
            delta=-100,
        )

        assert updated is not None
        assert updated.trust_score == 0

    async def test_update_trust_score_returns_none_for_missing(
        self, repo: GroupMemberRepository, sample_group: Group
    ) -> None:
        """Test returns None for non-existent member."""
        result = await repo.update_trust_score(sample_group.id, 999999999, 10)
        assert result is None

    # =========================================================================
    # exit_sandbox tests
    # =========================================================================

    async def test_exit_sandbox(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test exiting sandbox mode."""
        # Create member in sandbox
        await repo.record_join(
            group_id=sample_group.id,
            user_id=sample_user.id,
            start_in_sandbox=True,
        )

        # Exit sandbox
        member = await repo.exit_sandbox(sample_group.id, sample_user.id)

        assert member is not None
        assert member.trust_level == TrustLevel.LIMITED
        assert member.sandbox_expires_at is None

    async def test_exit_sandbox_returns_none_for_missing(
        self, repo: GroupMemberRepository, sample_group: Group
    ) -> None:
        """Test returns None for non-existent member."""
        result = await repo.exit_sandbox(sample_group.id, 999999999)
        assert result is None

    # =========================================================================
    # promote_to_trusted tests
    # =========================================================================

    async def test_promote_to_trusted(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test promoting member to trusted."""
        updated = await repo.promote_to_trusted(
            sample_membership.group_id, sample_membership.user_id
        )

        assert updated is not None
        assert updated.trust_level == TrustLevel.TRUSTED

    # =========================================================================
    # set_admin tests
    # =========================================================================

    async def test_set_admin(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test setting member as admin."""
        updated = await repo.set_admin(
            sample_membership.group_id, sample_membership.user_id
        )

        assert updated is not None
        assert updated.trust_level == TrustLevel.ADMIN

    # =========================================================================
    # get_members_by_trust_level tests
    # =========================================================================

    async def test_get_members_by_trust_level(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        user_repo: UserRepository,
    ) -> None:
        """Test retrieving members by trust level."""
        # Create users and memberships
        user1, _ = await user_repo.create_or_update(user_id=111111111)
        user2, _ = await user_repo.create_or_update(user_id=222222222)
        user3, _ = await user_repo.create_or_update(user_id=333333333)

        await repo.create_or_update_member(
            sample_group.id, user1.id, trust_level=TrustLevel.TRUSTED
        )
        await repo.create_or_update_member(
            sample_group.id, user2.id, trust_level=TrustLevel.TRUSTED
        )
        await repo.create_or_update_member(
            sample_group.id, user3.id, trust_level=TrustLevel.NEW
        )

        trusted = await repo.get_members_by_trust_level(
            sample_group.id, TrustLevel.TRUSTED
        )

        assert len(trusted) == 2
        assert all(m.trust_level == TrustLevel.TRUSTED for m in trusted)

    async def test_get_members_by_trust_level_with_limit(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        user_repo: UserRepository,
    ) -> None:
        """Test retrieving members with limit."""
        for i in range(5):
            user, _ = await user_repo.create_or_update(user_id=100000000 + i)
            await repo.create_or_update_member(
                sample_group.id, user.id, trust_level=TrustLevel.TRUSTED
            )

        members = await repo.get_members_by_trust_level(
            sample_group.id, TrustLevel.TRUSTED, limit=3
        )

        assert len(members) == 3

    # =========================================================================
    # get_sandbox_members tests
    # =========================================================================

    async def test_get_sandbox_members(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        user_repo: UserRepository,
    ) -> None:
        """Test retrieving members in sandbox."""
        user1, _ = await user_repo.create_or_update(user_id=111111111)
        user2, _ = await user_repo.create_or_update(user_id=222222222)
        user3, _ = await user_repo.create_or_update(user_id=333333333)

        await repo.record_join(
            sample_group.id, user1.id, sandbox_hours=24, start_in_sandbox=True
        )
        await repo.record_join(
            sample_group.id, user2.id, sandbox_hours=24, start_in_sandbox=True
        )
        await repo.record_join(
            sample_group.id, user3.id, sandbox_hours=24, start_in_sandbox=False
        )

        sandbox = await repo.get_sandbox_members(sample_group.id)

        assert len(sandbox) == 2
        assert all(m.trust_level == TrustLevel.SANDBOX for m in sandbox)

    # =========================================================================
    # get_expired_sandbox_members tests
    # =========================================================================

    async def test_get_expired_sandbox_members(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        user_repo: UserRepository,
    ) -> None:
        """Test retrieving members with expired sandbox."""
        user1, _ = await user_repo.create_or_update(user_id=111111111)

        # Create member with sandbox that expires immediately
        member, _ = await repo.create_or_update_member(
            group_id=sample_group.id,
            user_id=user1.id,
            trust_level=TrustLevel.SANDBOX,
            sandbox_expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        expired = await repo.get_expired_sandbox_members(sample_group.id)

        assert len(expired) == 1
        assert expired[0].user_id == user1.id

    async def test_get_expired_sandbox_members_global(
        self,
        repo: GroupMemberRepository,
        group_repo: GroupRepository,
        user_repo: UserRepository,
    ) -> None:
        """Test retrieving expired sandbox members across all groups."""
        group1, _ = await group_repo.create_or_update(-1001111111111, "Group 1")
        group2, _ = await group_repo.create_or_update(-1002222222222, "Group 2")
        user1, _ = await user_repo.create_or_update(user_id=111111111)
        user2, _ = await user_repo.create_or_update(user_id=222222222)

        # Create expired sandbox in different groups
        expired_time = datetime.now(UTC) - timedelta(hours=1)
        await repo.create_or_update_member(
            group_id=group1.id,
            user_id=user1.id,
            trust_level=TrustLevel.SANDBOX,
            sandbox_expires_at=expired_time,
        )
        await repo.create_or_update_member(
            group_id=group2.id,
            user_id=user2.id,
            trust_level=TrustLevel.SANDBOX,
            sandbox_expires_at=expired_time,
        )

        # Get all expired (no group filter)
        all_expired = await repo.get_expired_sandbox_members()
        assert len(all_expired) == 2

    # =========================================================================
    # get_active_members tests
    # =========================================================================

    async def test_get_active_members(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        user_repo: UserRepository,
    ) -> None:
        """Test retrieving active members."""
        user1, _ = await user_repo.create_or_update(user_id=111111111)
        user2, _ = await user_repo.create_or_update(user_id=222222222)

        # Record messages for both
        await repo.record_message(sample_group.id, user1.id)
        await repo.record_message(sample_group.id, user2.id)

        active = await repo.get_active_members(sample_group.id, days=7)

        assert len(active) == 2

    async def test_get_active_members_respects_time_window(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        user_repo: UserRepository,
    ) -> None:
        """Test that time window is respected."""
        user1, _ = await user_repo.create_or_update(user_id=111111111)

        # Record a message
        await repo.record_message(sample_group.id, user1.id)

        # Should find the active member within 24 hours
        active = await repo.get_active_members(sample_group.id, days=1)
        assert len(active) == 1

    # =========================================================================
    # get_member_stats tests
    # =========================================================================

    async def test_get_member_stats(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        user_repo: UserRepository,
    ) -> None:
        """Test getting member statistics."""
        user1, _ = await user_repo.create_or_update(user_id=111111111)
        user2, _ = await user_repo.create_or_update(user_id=222222222)
        user3, _ = await user_repo.create_or_update(user_id=333333333)

        await repo.create_or_update_member(
            sample_group.id, user1.id, trust_level=TrustLevel.TRUSTED, trust_score=80
        )
        await repo.create_or_update_member(
            sample_group.id, user2.id, trust_level=TrustLevel.NEW, trust_score=40
        )
        await repo.create_or_update_member(
            sample_group.id, user3.id, trust_level=TrustLevel.TRUSTED, trust_score=90
        )

        # Record activity for one member
        await repo.record_message(sample_group.id, user1.id)

        stats = await repo.get_member_stats(sample_group.id)

        assert stats["total_members"] == 3
        assert stats["by_trust_level"]["trusted"] == 2
        assert stats["by_trust_level"]["new"] == 1
        assert stats["active_last_24h"] == 1
        assert stats["avg_trust_score"] is not None
        assert stats["avg_trust_score"] == pytest.approx(70, rel=0.1)

    # =========================================================================
    # remove_member tests
    # =========================================================================

    async def test_remove_member(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test removing a member."""
        result = await repo.remove_member(
            sample_membership.group_id, sample_membership.user_id
        )
        assert result is True

        # Verify removed
        found = await repo.get_member(
            sample_membership.group_id, sample_membership.user_id
        )
        assert found is None

    async def test_remove_member_returns_false_for_missing(
        self, repo: GroupMemberRepository, sample_group: Group
    ) -> None:
        """Test returns False for non-existent member."""
        result = await repo.remove_member(sample_group.id, 999999999)
        assert result is False

    # =========================================================================
    # get_time_to_first_message tests
    # =========================================================================

    async def test_get_time_to_first_message(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test calculating time to first message."""
        # Record join and then a message
        await repo.record_join(sample_group.id, sample_user.id, start_in_sandbox=False)
        await repo.record_message(sample_group.id, sample_user.id)

        ttfm = await repo.get_time_to_first_message(sample_group.id, sample_user.id)

        assert ttfm is not None
        assert ttfm >= 0  # Should be non-negative

    async def test_get_time_to_first_message_returns_none_without_message(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test returns None if no message sent."""
        await repo.record_join(sample_group.id, sample_user.id, start_in_sandbox=False)

        ttfm = await repo.get_time_to_first_message(sample_group.id, sample_user.id)

        assert ttfm is None

    async def test_get_time_to_first_message_returns_none_for_missing(
        self, repo: GroupMemberRepository, sample_group: Group
    ) -> None:
        """Test returns None for non-existent member."""
        ttfm = await repo.get_time_to_first_message(sample_group.id, 999999999)
        assert ttfm is None

    # =========================================================================
    # batch_update_trust_scores tests
    # =========================================================================

    async def test_batch_update_trust_scores(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        user_repo: UserRepository,
    ) -> None:
        """Test batch updating trust scores."""
        user1, _ = await user_repo.create_or_update(user_id=111111111)
        user2, _ = await user_repo.create_or_update(user_id=222222222)
        user3, _ = await user_repo.create_or_update(user_id=333333333)

        await repo.create_or_update_member(
            sample_group.id, user1.id, trust_score=50
        )
        await repo.create_or_update_member(
            sample_group.id, user2.id, trust_score=50
        )
        await repo.create_or_update_member(
            sample_group.id, user3.id, trust_score=50
        )

        updates = {
            user1.id: 10,   # +10
            user2.id: -5,   # -5
            user3.id: 20,   # +20
        }

        count = await repo.batch_update_trust_scores(sample_group.id, updates)

        assert count == 3

        # Verify updates
        m1 = await repo.get_member(sample_group.id, user1.id)
        m2 = await repo.get_member(sample_group.id, user2.id)
        m3 = await repo.get_member(sample_group.id, user3.id)

        assert m1 is not None and m1.trust_score == 60
        assert m2 is not None and m2.trust_score == 45
        assert m3 is not None and m3.trust_score == 70

    # =========================================================================
    # count_user_groups tests
    # =========================================================================

    async def test_count_user_groups(
        self,
        repo: GroupMemberRepository,
        group_repo: GroupRepository,
        sample_user: User,
    ) -> None:
        """Test counting groups a user is member of."""
        group1, _ = await group_repo.create_or_update(-1001111111111, "Group 1")
        group2, _ = await group_repo.create_or_update(-1002222222222, "Group 2")
        group3, _ = await group_repo.create_or_update(-1003333333333, "Group 3")

        await repo.create_or_update_member(group1.id, sample_user.id)
        await repo.create_or_update_member(group2.id, sample_user.id)

        count = await repo.count_user_groups(sample_user.id)

        assert count == 2

    # =========================================================================
    # sum_user_messages tests
    # =========================================================================

    async def test_sum_user_messages(
        self,
        repo: GroupMemberRepository,
        group_repo: GroupRepository,
        sample_user: User,
    ) -> None:
        """Test summing messages across all groups."""
        group1, _ = await group_repo.create_or_update(-1001111111111, "Group 1")
        group2, _ = await group_repo.create_or_update(-1002222222222, "Group 2")

        # Record messages in different groups
        await repo.record_message(group1.id, sample_user.id)
        await repo.record_message(group1.id, sample_user.id)
        await repo.record_message(group2.id, sample_user.id)

        total = await repo.sum_user_messages(sample_user.id)

        assert total == 3

    async def test_sum_user_messages_returns_zero_for_no_messages(
        self, repo: GroupMemberRepository, sample_user: User
    ) -> None:
        """Test returns 0 for user with no messages."""
        total = await repo.sum_user_messages(sample_user.id)
        assert total == 0

    # =========================================================================
    # is_in_sandbox property tests
    # =========================================================================

    async def test_is_in_sandbox_true(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test is_in_sandbox returns True when in sandbox."""
        member = await repo.record_join(
            sample_group.id,
            sample_user.id,
            sandbox_hours=24,
            start_in_sandbox=True,
        )

        assert member.is_in_sandbox is True

    async def test_is_in_sandbox_false_no_expiry(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test is_in_sandbox returns False when no expiry set."""
        assert sample_membership.sandbox_expires_at is None
        assert sample_membership.is_in_sandbox is False

    async def test_is_in_sandbox_false_expired(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test is_in_sandbox returns False when sandbox expired."""
        member, _ = await repo.create_or_update_member(
            group_id=sample_group.id,
            user_id=sample_user.id,
            trust_level=TrustLevel.SANDBOX,
            sandbox_expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        assert member.is_in_sandbox is False

    # =========================================================================
    # Relationship loading tests
    # =========================================================================

    async def test_get_member_with_user(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test loading member with user relationship."""
        member = await repo.get_member_with_user(
            sample_membership.group_id, sample_membership.user_id
        )

        assert member is not None
        assert member.user is not None
        assert member.user.id == sample_membership.user_id

    async def test_get_member_with_group(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test loading member with group relationship."""
        member = await repo.get_member_with_group(
            sample_membership.group_id, sample_membership.user_id
        )

        assert member is not None
        assert member.group is not None
        assert member.group.id == sample_membership.group_id

    async def test_get_member_with_all_relations(
        self, repo: GroupMemberRepository, sample_membership: GroupMember
    ) -> None:
        """Test loading member with all relationships."""
        member = await repo.get_member_with_all_relations(
            sample_membership.group_id, sample_membership.user_id
        )

        assert member is not None
        assert member.user is not None
        assert member.group is not None

    async def test_get_members_by_trust_level_with_users(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        user_repo: UserRepository,
    ) -> None:
        """Test loading members with user data."""
        user1, _ = await user_repo.create_or_update(user_id=111111111)
        await repo.create_or_update_member(
            sample_group.id, user1.id, trust_level=TrustLevel.TRUSTED
        )

        members = await repo.get_members_by_trust_level_with_users(
            sample_group.id, TrustLevel.TRUSTED
        )

        assert len(members) == 1
        assert members[0].user is not None

    async def test_get_sandbox_members_with_users(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        user_repo: UserRepository,
    ) -> None:
        """Test loading sandbox members with user data."""
        user1, _ = await user_repo.create_or_update(user_id=111111111)
        await repo.record_join(
            sample_group.id, user1.id, sandbox_hours=24, start_in_sandbox=True
        )

        members = await repo.get_sandbox_members_with_users(sample_group.id)

        assert len(members) == 1
        assert members[0].user is not None

    async def test_get_active_members_with_users(
        self,
        repo: GroupMemberRepository,
        sample_group: Group,
        user_repo: UserRepository,
    ) -> None:
        """Test loading active members with user data."""
        user1, _ = await user_repo.create_or_update(user_id=111111111)
        await repo.record_message(sample_group.id, user1.id)

        members = await repo.get_active_members_with_users(sample_group.id)

        assert len(members) == 1
        assert members[0].user is not None

    async def test_get_user_memberships_with_groups(
        self,
        repo: GroupMemberRepository,
        group_repo: GroupRepository,
        sample_user: User,
    ) -> None:
        """Test loading user's memberships with group data."""
        group1, _ = await group_repo.create_or_update(-1001111111111, "Group 1")
        group2, _ = await group_repo.create_or_update(-1002222222222, "Group 2")

        await repo.create_or_update_member(group1.id, sample_user.id)
        await repo.create_or_update_member(group2.id, sample_user.id)

        memberships = await repo.get_user_memberships_with_groups(sample_user.id)

        assert len(memberships) == 2
        for m in memberships:
            assert m.group is not None
