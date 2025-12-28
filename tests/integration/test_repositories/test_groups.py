"""Integration tests for GroupRepository.

Tests cover all repository methods with real PostgreSQL database operations,
ensuring proper CRUD functionality, settings management, and relationship handling.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from saqshy.core.types import GroupType
from saqshy.db.models import Group
from saqshy.db.repositories.groups import GroupRepository


@pytest.mark.integration
class TestGroupRepository:
    """Integration tests for GroupRepository."""

    @pytest.fixture
    async def repo(self, db_session: AsyncSession) -> GroupRepository:
        """Create repository instance with test session."""
        return GroupRepository(db_session)

    @pytest.fixture
    async def sample_group(self, repo: GroupRepository) -> Group:
        """Create a sample group for testing."""
        group, _ = await repo.create_or_update(
            chat_id=-1001234567890,
            title="Test Group",
            username="testgroup",
            group_type=GroupType.GENERAL,
        )
        return group

    # =========================================================================
    # create_or_update tests
    # =========================================================================

    async def test_create_or_update_creates_new_group(
        self, repo: GroupRepository
    ) -> None:
        """Test creating a new group."""
        group, created = await repo.create_or_update(
            chat_id=-1001111111111,
            title="New Group",
            username="newgroup",
            group_type=GroupType.TECH,
        )

        assert created is True
        assert group.id == -1001111111111
        assert group.title == "New Group"
        assert group.username == "newgroup"
        assert group.group_type == GroupType.TECH
        assert group.is_active is True
        assert group.sensitivity == 5  # Default value
        assert group.sandbox_enabled is True  # Default value

    async def test_create_or_update_updates_existing_group(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test updating an existing group."""
        updated, created = await repo.create_or_update(
            chat_id=sample_group.id,
            title="Updated Title",
            username="updated",
            group_type=GroupType.DEALS,
        )

        assert created is False
        assert updated.id == sample_group.id
        assert updated.title == "Updated Title"
        assert updated.username == "updated"
        assert updated.group_type == GroupType.DEALS

    async def test_create_or_update_with_linked_channel(
        self, repo: GroupRepository
    ) -> None:
        """Test creating a group with linked channel."""
        group, created = await repo.create_or_update(
            chat_id=-1002222222222,
            title="Group with Channel",
            linked_channel_id=-1009999999999,
            members_count=150,
        )

        assert created is True
        assert group.linked_channel_id == -1009999999999
        assert group.members_count == 150

    async def test_create_or_update_all_group_types(
        self, repo: GroupRepository
    ) -> None:
        """Test creating groups with all group types."""
        for i, group_type in enumerate(GroupType):
            chat_id = -1001000000000 - i
            group, created = await repo.create_or_update(
                chat_id=chat_id,
                title=f"{group_type.value} Group",
                group_type=group_type,
            )
            assert group.group_type == group_type

    # =========================================================================
    # get_by_id tests
    # =========================================================================

    async def test_get_by_id_returns_group(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test retrieving group by ID."""
        found = await repo.get_by_id(sample_group.id)

        assert found is not None
        assert found.id == sample_group.id
        assert found.title == sample_group.title

    async def test_get_by_id_returns_none_for_missing(
        self, repo: GroupRepository
    ) -> None:
        """Test that get_by_id returns None for non-existent group."""
        found = await repo.get_by_id(-9999999999999)
        assert found is None

    # =========================================================================
    # get_settings tests
    # =========================================================================

    async def test_get_settings_returns_settings_dict(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test retrieving group settings."""
        settings = await repo.get_settings(sample_group.id)

        assert settings is not None
        assert settings["group_type"] == sample_group.group_type.value
        assert settings["sensitivity"] == sample_group.sensitivity
        assert settings["sandbox_enabled"] == sample_group.sandbox_enabled
        assert settings["sandbox_duration_hours"] == sample_group.sandbox_duration_hours
        assert settings["link_whitelist"] == sample_group.link_whitelist
        assert settings["language"] == sample_group.language
        assert settings["linked_channel_id"] == sample_group.linked_channel_id

    async def test_get_settings_returns_none_for_missing_group(
        self, repo: GroupRepository
    ) -> None:
        """Test that get_settings returns None for non-existent group."""
        settings = await repo.get_settings(-9999999999999)
        assert settings is None

    # =========================================================================
    # update_settings tests
    # =========================================================================

    async def test_update_settings_sensitivity(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test updating sensitivity setting."""
        updated = await repo.update_settings(
            sample_group.id,
            sensitivity=8,
        )

        assert updated is not None
        assert updated.sensitivity == 8

    async def test_update_settings_validates_sensitivity_range(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test that sensitivity must be between 1 and 10."""
        with pytest.raises(ValueError, match="Sensitivity must be between 1 and 10"):
            await repo.update_settings(
                sample_group.id,
                sensitivity=15,
            )

        with pytest.raises(ValueError, match="Sensitivity must be between 1 and 10"):
            await repo.update_settings(
                sample_group.id,
                sensitivity=0,
            )

    async def test_update_settings_sandbox(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test updating sandbox settings."""
        updated = await repo.update_settings(
            sample_group.id,
            sandbox_enabled=False,
            sandbox_duration_hours=48,
        )

        assert updated is not None
        assert updated.sandbox_enabled is False
        assert updated.sandbox_duration_hours == 48

    async def test_update_settings_group_type(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test updating group type."""
        updated = await repo.update_settings(
            sample_group.id,
            group_type=GroupType.CRYPTO,
        )

        assert updated is not None
        assert updated.group_type == GroupType.CRYPTO

    async def test_update_settings_link_whitelist(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test updating link whitelist."""
        whitelist = ["github.com", "stackoverflow.com"]
        updated = await repo.update_settings(
            sample_group.id,
            link_whitelist=whitelist,
        )

        assert updated is not None
        assert updated.link_whitelist == whitelist

    async def test_update_settings_language(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test updating language setting."""
        updated = await repo.update_settings(
            sample_group.id,
            language="en",
        )

        assert updated is not None
        assert updated.language == "en"

    async def test_update_settings_linked_channel(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test updating linked channel."""
        channel_id = -1009876543210
        updated = await repo.update_settings(
            sample_group.id,
            linked_channel_id=channel_id,
        )

        assert updated is not None
        assert updated.linked_channel_id == channel_id

    async def test_update_settings_multiple_fields(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test updating multiple settings at once."""
        updated = await repo.update_settings(
            sample_group.id,
            sensitivity=7,
            sandbox_enabled=True,
            group_type=GroupType.DEALS,
            language="kz",
        )

        assert updated is not None
        assert updated.sensitivity == 7
        assert updated.sandbox_enabled is True
        assert updated.group_type == GroupType.DEALS
        assert updated.language == "kz"

    async def test_update_settings_returns_none_for_missing_group(
        self, repo: GroupRepository
    ) -> None:
        """Test that update_settings returns None for non-existent group."""
        result = await repo.update_settings(
            -9999999999999,
            sensitivity=5,
        )
        assert result is None

    # =========================================================================
    # increment_blocked_count tests
    # =========================================================================

    async def test_increment_blocked_count(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test incrementing blocked count."""
        initial = sample_group.blocked_count

        result = await repo.increment_blocked_count(sample_group.id)
        assert result is True

        refreshed = await repo.get_by_id(sample_group.id)
        assert refreshed is not None
        assert refreshed.blocked_count == initial + 1

    async def test_increment_blocked_count_by_amount(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test incrementing blocked count by specific amount."""
        initial = sample_group.blocked_count

        result = await repo.increment_blocked_count(sample_group.id, amount=5)
        assert result is True

        refreshed = await repo.get_by_id(sample_group.id)
        assert refreshed is not None
        assert refreshed.blocked_count == initial + 5

    async def test_increment_blocked_count_multiple_times(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test atomic increment of blocked count (multiple calls)."""
        initial = sample_group.blocked_count

        await repo.increment_blocked_count(sample_group.id)
        await repo.increment_blocked_count(sample_group.id)
        await repo.increment_blocked_count(sample_group.id)

        refreshed = await repo.get_by_id(sample_group.id)
        assert refreshed is not None
        assert refreshed.blocked_count == initial + 3

    async def test_increment_blocked_count_returns_false_for_missing(
        self, repo: GroupRepository
    ) -> None:
        """Test increment returns False for non-existent group."""
        result = await repo.increment_blocked_count(-9999999999999)
        assert result is False

    # =========================================================================
    # update_members_count tests
    # =========================================================================

    async def test_update_members_count(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test updating member count."""
        result = await repo.update_members_count(sample_group.id, 500)
        assert result is True

        refreshed = await repo.get_by_id(sample_group.id)
        assert refreshed is not None
        assert refreshed.members_count == 500

    async def test_update_members_count_returns_false_for_missing(
        self, repo: GroupRepository
    ) -> None:
        """Test returns False for non-existent group."""
        result = await repo.update_members_count(-9999999999999, 100)
        assert result is False

    # =========================================================================
    # set_active tests
    # =========================================================================

    async def test_set_active_to_false(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test deactivating a group."""
        result = await repo.set_active(sample_group.id, is_active=False)
        assert result is True

        refreshed = await repo.get_by_id(sample_group.id)
        assert refreshed is not None
        assert refreshed.is_active is False

    async def test_set_active_to_true(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test reactivating a group."""
        await repo.set_active(sample_group.id, is_active=False)
        result = await repo.set_active(sample_group.id, is_active=True)
        assert result is True

        refreshed = await repo.get_by_id(sample_group.id)
        assert refreshed is not None
        assert refreshed.is_active is True

    async def test_set_active_returns_false_for_missing(
        self, repo: GroupRepository
    ) -> None:
        """Test returns False for non-existent group."""
        result = await repo.set_active(-9999999999999, is_active=False)
        assert result is False

    # =========================================================================
    # get_active_groups tests
    # =========================================================================

    async def test_get_active_groups(self, repo: GroupRepository) -> None:
        """Test retrieving active groups."""
        # Create multiple groups
        await repo.create_or_update(-1001111111111, "Active 1")
        await repo.create_or_update(-1002222222222, "Active 2")
        g3, _ = await repo.create_or_update(-1003333333333, "Inactive")
        await repo.set_active(g3.id, is_active=False)

        active_groups = await repo.get_active_groups()

        assert len(active_groups) == 2
        assert all(g.is_active for g in active_groups)

    async def test_get_active_groups_with_limit(self, repo: GroupRepository) -> None:
        """Test retrieving active groups with limit."""
        for i in range(5):
            await repo.create_or_update(-1001000000000 - i, f"Group {i}")

        groups = await repo.get_active_groups(limit=3)
        assert len(groups) == 3

    async def test_get_active_groups_with_offset(self, repo: GroupRepository) -> None:
        """Test retrieving active groups with offset."""
        for i in range(5):
            await repo.create_or_update(-1001000000000 - i, f"Group {i}")

        groups = await repo.get_active_groups(limit=2, offset=2)
        assert len(groups) == 2

    # =========================================================================
    # get_groups_by_type tests
    # =========================================================================

    async def test_get_groups_by_type(self, repo: GroupRepository) -> None:
        """Test retrieving groups by type."""
        await repo.create_or_update(
            -1001111111111, "Tech Group", group_type=GroupType.TECH
        )
        await repo.create_or_update(
            -1002222222222, "Another Tech", group_type=GroupType.TECH
        )
        await repo.create_or_update(
            -1003333333333, "Deals Group", group_type=GroupType.DEALS
        )

        tech_groups = await repo.get_groups_by_type(GroupType.TECH)

        assert len(tech_groups) == 2
        assert all(g.group_type == GroupType.TECH for g in tech_groups)

    async def test_get_groups_by_type_excludes_inactive(
        self, repo: GroupRepository
    ) -> None:
        """Test that inactive groups are excluded by default."""
        g1, _ = await repo.create_or_update(
            -1001111111111, "Active Tech", group_type=GroupType.TECH
        )
        g2, _ = await repo.create_or_update(
            -1002222222222, "Inactive Tech", group_type=GroupType.TECH
        )
        await repo.set_active(g2.id, is_active=False)

        tech_groups = await repo.get_groups_by_type(GroupType.TECH, active_only=True)
        assert len(tech_groups) == 1
        assert tech_groups[0].id == g1.id

    async def test_get_groups_by_type_includes_inactive(
        self, repo: GroupRepository
    ) -> None:
        """Test including inactive groups."""
        await repo.create_or_update(
            -1001111111111, "Active Tech", group_type=GroupType.TECH
        )
        g2, _ = await repo.create_or_update(
            -1002222222222, "Inactive Tech", group_type=GroupType.TECH
        )
        await repo.set_active(g2.id, is_active=False)

        tech_groups = await repo.get_groups_by_type(GroupType.TECH, active_only=False)
        assert len(tech_groups) == 2

    # =========================================================================
    # add_to_whitelist / remove_from_whitelist tests
    # =========================================================================

    async def test_add_to_whitelist(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test adding domain to whitelist."""
        result = await repo.add_to_whitelist(sample_group.id, "github.com")
        assert result is True

        refreshed = await repo.get_by_id(sample_group.id)
        assert refreshed is not None
        assert "github.com" in refreshed.link_whitelist

    async def test_add_to_whitelist_normalizes_domain(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test that domain is normalized (lowercase, stripped)."""
        result = await repo.add_to_whitelist(sample_group.id, "  GitHub.COM  ")
        assert result is True

        refreshed = await repo.get_by_id(sample_group.id)
        assert refreshed is not None
        assert "github.com" in refreshed.link_whitelist

    async def test_add_to_whitelist_prevents_duplicates(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test that duplicate domains are not added."""
        await repo.add_to_whitelist(sample_group.id, "github.com")
        result = await repo.add_to_whitelist(sample_group.id, "github.com")
        assert result is False

        refreshed = await repo.get_by_id(sample_group.id)
        assert refreshed is not None
        assert refreshed.link_whitelist.count("github.com") == 1

    async def test_add_to_whitelist_multiple_domains(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test adding multiple domains."""
        await repo.add_to_whitelist(sample_group.id, "github.com")
        await repo.add_to_whitelist(sample_group.id, "stackoverflow.com")
        await repo.add_to_whitelist(sample_group.id, "python.org")

        refreshed = await repo.get_by_id(sample_group.id)
        assert refreshed is not None
        assert len(refreshed.link_whitelist) == 3
        assert "github.com" in refreshed.link_whitelist
        assert "stackoverflow.com" in refreshed.link_whitelist
        assert "python.org" in refreshed.link_whitelist

    async def test_add_to_whitelist_returns_false_for_missing_group(
        self, repo: GroupRepository
    ) -> None:
        """Test returns False for non-existent group."""
        result = await repo.add_to_whitelist(-9999999999999, "github.com")
        assert result is False

    async def test_remove_from_whitelist(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test removing domain from whitelist."""
        await repo.add_to_whitelist(sample_group.id, "github.com")
        result = await repo.remove_from_whitelist(sample_group.id, "github.com")
        assert result is True

        refreshed = await repo.get_by_id(sample_group.id)
        assert refreshed is not None
        assert "github.com" not in refreshed.link_whitelist

    async def test_remove_from_whitelist_normalizes_domain(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test that domain is normalized for removal."""
        await repo.add_to_whitelist(sample_group.id, "github.com")
        result = await repo.remove_from_whitelist(sample_group.id, "  GitHub.COM  ")
        assert result is True

        refreshed = await repo.get_by_id(sample_group.id)
        assert refreshed is not None
        assert "github.com" not in refreshed.link_whitelist

    async def test_remove_from_whitelist_returns_false_if_not_in_list(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test returns False if domain not in whitelist."""
        result = await repo.remove_from_whitelist(sample_group.id, "notinlist.com")
        assert result is False

    async def test_remove_from_whitelist_returns_false_for_missing_group(
        self, repo: GroupRepository
    ) -> None:
        """Test returns False for non-existent group."""
        result = await repo.remove_from_whitelist(-9999999999999, "github.com")
        assert result is False

    # =========================================================================
    # get_stats tests
    # =========================================================================

    async def test_get_stats(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test retrieving group statistics."""
        # Update some stats
        await repo.update_members_count(sample_group.id, 250)
        await repo.increment_blocked_count(sample_group.id, 10)

        stats = await repo.get_stats(sample_group.id)

        assert stats is not None
        assert stats["members_count"] == 250
        assert stats["blocked_count"] == 10
        assert stats["is_active"] is True
        assert "created_at" in stats

    async def test_get_stats_returns_none_for_missing_group(
        self, repo: GroupRepository
    ) -> None:
        """Test returns None for non-existent group."""
        stats = await repo.get_stats(-9999999999999)
        assert stats is None

    # =========================================================================
    # Relationship loading tests
    # =========================================================================

    async def test_get_by_id_with_members(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test loading group with members relationship."""
        group = await repo.get_by_id_with_members(sample_group.id)

        assert group is not None
        # Members list should be accessible (empty for new group)
        assert group.members == []

    async def test_get_by_id_with_decisions(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test loading group with decisions relationship."""
        group = await repo.get_by_id_with_decisions(sample_group.id)

        assert group is not None
        # Decisions list should be accessible (empty for new group)
        assert group.decisions == []

    async def test_get_by_id_with_admin_actions(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test loading group with admin_actions relationship."""
        group = await repo.get_by_id_with_admin_actions(sample_group.id)

        assert group is not None
        # Admin actions list should be accessible (empty for new group)
        assert group.admin_actions == []

    async def test_get_by_id_with_all_relations(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test loading group with all relationships."""
        group = await repo.get_by_id_with_all_relations(sample_group.id)

        assert group is not None
        # All lists should be accessible
        assert group.members == []
        assert group.decisions == []
        assert group.admin_actions == []

    async def test_get_active_groups_with_members(
        self, repo: GroupRepository
    ) -> None:
        """Test loading active groups with members."""
        await repo.create_or_update(-1001111111111, "Group 1")
        await repo.create_or_update(-1002222222222, "Group 2")

        groups = await repo.get_active_groups_with_members()

        assert len(groups) == 2
        # Members should be accessible on each group
        for group in groups:
            assert group.members == []

    # =========================================================================
    # Base repository tests (inherited methods)
    # =========================================================================

    async def test_exists_returns_true(
        self, repo: GroupRepository, sample_group: Group
    ) -> None:
        """Test exists returns True for existing group."""
        exists = await repo.exists(sample_group.id)
        assert exists is True

    async def test_exists_returns_false(self, repo: GroupRepository) -> None:
        """Test exists returns False for non-existent group."""
        exists = await repo.exists(-9999999999999)
        assert exists is False

    async def test_count(self, repo: GroupRepository) -> None:
        """Test counting all groups."""
        await repo.create_or_update(-1001111111111, "Group 1")
        await repo.create_or_update(-1002222222222, "Group 2")
        await repo.create_or_update(-1003333333333, "Group 3")

        count = await repo.count()
        assert count == 3

    async def test_get_all(self, repo: GroupRepository) -> None:
        """Test getting all groups."""
        await repo.create_or_update(-1001111111111, "Group 1")
        await repo.create_or_update(-1002222222222, "Group 2")

        all_groups = await repo.get_all()
        assert len(all_groups) == 2

    async def test_get_all_with_pagination(self, repo: GroupRepository) -> None:
        """Test pagination on get_all."""
        for i in range(5):
            await repo.create_or_update(-1001000000000 - i, f"Group {i}")

        page1 = await repo.get_all(limit=2, offset=0)
        page2 = await repo.get_all(limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2

    async def test_delete_group(self, repo: GroupRepository) -> None:
        """Test deleting a group."""
        group, _ = await repo.create_or_update(-1001111111111, "To Delete")

        result = await repo.delete(group.id)
        assert result is True

        deleted = await repo.get_by_id(group.id)
        assert deleted is None

    async def test_delete_returns_false_for_missing(
        self, repo: GroupRepository
    ) -> None:
        """Test delete returns False for non-existent group."""
        result = await repo.delete(-9999999999999)
        assert result is False
