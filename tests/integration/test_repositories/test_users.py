"""Integration tests for UserRepository.

Tests cover all repository methods for Telegram user profile management,
including creation, updates, queries, and relationship loading.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from saqshy.db.models import User
from saqshy.db.repositories.users import UserRepository


@pytest.mark.integration
class TestUserRepository:
    """Integration tests for UserRepository."""

    @pytest.fixture
    async def repo(self, db_session: AsyncSession) -> UserRepository:
        """Create repository instance with test session."""
        return UserRepository(db_session)

    @pytest.fixture
    async def sample_user(self, repo: UserRepository) -> User:
        """Create a sample user for testing."""
        user, _ = await repo.create_or_update(
            user_id=123456789,
            username="testuser",
            first_name="Test",
            last_name="User",
            has_photo=True,
            is_premium=False,
            bio="A test user bio",
            account_age_days=365,
        )
        return user

    # =========================================================================
    # create_or_update tests
    # =========================================================================

    async def test_create_or_update_creates_new_user(
        self, repo: UserRepository
    ) -> None:
        """Test creating a new user."""
        user, created = await repo.create_or_update(
            user_id=111111111,
            username="newuser",
            first_name="New",
            last_name="User",
        )

        assert created is True
        assert user.id == 111111111
        assert user.username == "newuser"
        assert user.first_name == "New"
        assert user.last_name == "User"
        assert user.first_seen_at is not None

    async def test_create_or_update_updates_existing_user(
        self, repo: UserRepository, sample_user: User
    ) -> None:
        """Test updating an existing user."""
        updated, created = await repo.create_or_update(
            user_id=sample_user.id,
            username="updatedusername",
            first_name="Updated",
        )

        assert created is False
        assert updated.id == sample_user.id
        assert updated.username == "updatedusername"
        assert updated.first_name == "Updated"
        # Original last_name should be preserved
        assert updated.last_name == sample_user.last_name

    async def test_create_or_update_with_all_fields(
        self, repo: UserRepository
    ) -> None:
        """Test creating a user with all fields."""
        user, created = await repo.create_or_update(
            user_id=222222222,
            username="fullprofile",
            first_name="Full",
            last_name="Profile",
            has_photo=True,
            is_premium=True,
            bio="Full profile with premium",
            account_age_days=730,
        )

        assert created is True
        assert user.username == "fullprofile"
        assert user.has_photo is True
        assert user.is_premium is True
        assert user.bio == "Full profile with premium"
        assert user.account_age_days == 730

    async def test_create_or_update_minimal_user(self, repo: UserRepository) -> None:
        """Test creating a user with minimal info."""
        user, created = await repo.create_or_update(user_id=333333333)

        assert created is True
        assert user.id == 333333333
        assert user.username is None
        assert user.first_name is None
        assert user.last_name is None

    async def test_create_or_update_preserves_first_seen_at(
        self, repo: UserRepository
    ) -> None:
        """Test that first_seen_at is not modified on update."""
        user, _ = await repo.create_or_update(user_id=444444444, first_name="First")
        original_first_seen = user.first_seen_at

        # Update the user
        updated, created = await repo.create_or_update(
            user_id=444444444, first_name="Updated"
        )

        assert created is False
        assert updated.first_seen_at == original_first_seen

    # =========================================================================
    # get_by_id tests
    # =========================================================================

    async def test_get_by_id_returns_user(
        self, repo: UserRepository, sample_user: User
    ) -> None:
        """Test retrieving user by ID."""
        found = await repo.get_by_id(sample_user.id)

        assert found is not None
        assert found.id == sample_user.id
        assert found.username == sample_user.username

    async def test_get_by_id_returns_none_for_missing(
        self, repo: UserRepository
    ) -> None:
        """Test returns None for non-existent user."""
        found = await repo.get_by_id(9999999999)
        assert found is None

    # =========================================================================
    # update_profile tests
    # =========================================================================

    async def test_update_profile_updates_fields(
        self, repo: UserRepository, sample_user: User
    ) -> None:
        """Test updating specific profile fields."""
        updated = await repo.update_profile(
            user_id=sample_user.id,
            is_premium=True,
            bio="Updated bio text",
        )

        assert updated is not None
        assert updated.is_premium is True
        assert updated.bio == "Updated bio text"
        # Other fields unchanged
        assert updated.username == sample_user.username

    async def test_update_profile_all_fields(
        self, repo: UserRepository, sample_user: User
    ) -> None:
        """Test updating all profile fields."""
        updated = await repo.update_profile(
            user_id=sample_user.id,
            username="newusername",
            first_name="NewFirst",
            last_name="NewLast",
            has_photo=False,
            is_premium=True,
            bio="Completely new bio",
            account_age_days=1000,
        )

        assert updated is not None
        assert updated.username == "newusername"
        assert updated.first_name == "NewFirst"
        assert updated.last_name == "NewLast"
        assert updated.has_photo is False
        assert updated.is_premium is True
        assert updated.bio == "Completely new bio"
        assert updated.account_age_days == 1000

    async def test_update_profile_returns_none_for_missing(
        self, repo: UserRepository
    ) -> None:
        """Test returns None for non-existent user."""
        result = await repo.update_profile(user_id=9999999999, bio="Test")
        assert result is None

    # =========================================================================
    # get_by_username tests
    # =========================================================================

    async def test_get_by_username(
        self, repo: UserRepository, sample_user: User
    ) -> None:
        """Test retrieving user by username."""
        found = await repo.get_by_username(sample_user.username or "")

        assert found is not None
        assert found.id == sample_user.id

    async def test_get_by_username_with_at_prefix(
        self, repo: UserRepository, sample_user: User
    ) -> None:
        """Test retrieving user by username with @ prefix."""
        found = await repo.get_by_username(f"@{sample_user.username}")

        assert found is not None
        assert found.id == sample_user.id

    async def test_get_by_username_returns_none_for_missing(
        self, repo: UserRepository
    ) -> None:
        """Test returns None for non-existent username."""
        found = await repo.get_by_username("nonexistentuser")
        assert found is None

    # =========================================================================
    # get_premium_users tests
    # =========================================================================

    async def test_get_premium_users(self, repo: UserRepository) -> None:
        """Test retrieving premium users."""
        await repo.create_or_update(user_id=111111111, is_premium=True)
        await repo.create_or_update(user_id=222222222, is_premium=True)
        await repo.create_or_update(user_id=333333333, is_premium=False)

        premium = await repo.get_premium_users()

        assert len(premium) == 2
        assert all(u.is_premium for u in premium)

    async def test_get_premium_users_with_limit(self, repo: UserRepository) -> None:
        """Test retrieving premium users with limit."""
        for i in range(5):
            await repo.create_or_update(user_id=100000000 + i, is_premium=True)

        premium = await repo.get_premium_users(limit=3)
        assert len(premium) == 3

    # =========================================================================
    # get_users_without_photo tests
    # =========================================================================

    async def test_get_users_without_photo(self, repo: UserRepository) -> None:
        """Test retrieving users without profile photos."""
        await repo.create_or_update(user_id=111111111, has_photo=False)
        await repo.create_or_update(user_id=222222222, has_photo=False)
        await repo.create_or_update(user_id=333333333, has_photo=True)

        no_photo = await repo.get_users_without_photo()

        assert len(no_photo) == 2
        assert all(u.has_photo is False for u in no_photo)

    async def test_get_users_without_photo_with_limit(
        self, repo: UserRepository
    ) -> None:
        """Test retrieving users without photo with limit."""
        for i in range(5):
            await repo.create_or_update(user_id=100000000 + i, has_photo=False)

        no_photo = await repo.get_users_without_photo(limit=2)
        assert len(no_photo) == 2

    # =========================================================================
    # get_new_users tests
    # =========================================================================

    async def test_get_new_users(self, repo: UserRepository) -> None:
        """Test retrieving recently seen users."""
        # Create some users (they will have first_seen_at set to now)
        await repo.create_or_update(user_id=111111111, first_name="New1")
        await repo.create_or_update(user_id=222222222, first_name="New2")

        new_users = await repo.get_new_users(days=7)

        assert len(new_users) == 2

    async def test_get_new_users_with_limit(self, repo: UserRepository) -> None:
        """Test retrieving new users with limit."""
        for i in range(5):
            await repo.create_or_update(user_id=100000000 + i)

        new_users = await repo.get_new_users(days=7, limit=3)
        assert len(new_users) == 3

    # =========================================================================
    # get_profile_for_analysis tests
    # =========================================================================

    async def test_get_profile_for_analysis(
        self, repo: UserRepository, sample_user: User
    ) -> None:
        """Test getting profile data formatted for analysis."""
        profile = await repo.get_profile_for_analysis(sample_user.id)

        assert profile is not None
        assert profile["user_id"] == sample_user.id
        assert profile["username"] == sample_user.username
        assert profile["first_name"] == sample_user.first_name
        assert profile["last_name"] == sample_user.last_name
        assert profile["display_name"] is not None
        assert profile["has_photo"] == sample_user.has_photo
        assert profile["is_premium"] == sample_user.is_premium
        assert profile["bio"] == sample_user.bio
        assert profile["account_age_days"] == sample_user.account_age_days
        assert "first_seen_at" in profile

    async def test_get_profile_for_analysis_returns_none_for_missing(
        self, repo: UserRepository
    ) -> None:
        """Test returns None for non-existent user."""
        profile = await repo.get_profile_for_analysis(9999999999)
        assert profile is None

    # =========================================================================
    # bulk_get_by_ids tests
    # =========================================================================

    async def test_bulk_get_by_ids(self, repo: UserRepository) -> None:
        """Test bulk retrieval of users by IDs."""
        await repo.create_or_update(user_id=111111111, first_name="User1")
        await repo.create_or_update(user_id=222222222, first_name="User2")
        await repo.create_or_update(user_id=333333333, first_name="User3")

        users = await repo.bulk_get_by_ids([111111111, 222222222])

        assert len(users) == 2
        assert 111111111 in users
        assert 222222222 in users
        assert 333333333 not in users

    async def test_bulk_get_by_ids_empty_list(self, repo: UserRepository) -> None:
        """Test bulk get with empty list returns empty dict."""
        users = await repo.bulk_get_by_ids([])
        assert users == {}

    async def test_bulk_get_by_ids_partial_match(self, repo: UserRepository) -> None:
        """Test bulk get when some IDs don't exist."""
        await repo.create_or_update(user_id=111111111, first_name="User1")

        users = await repo.bulk_get_by_ids([111111111, 999999999])

        assert len(users) == 1
        assert 111111111 in users

    # =========================================================================
    # mark_stale_profiles tests
    # =========================================================================

    async def test_mark_stale_profiles(self, repo: UserRepository) -> None:
        """Test counting stale profiles."""
        # Create some users (recently updated)
        await repo.create_or_update(user_id=111111111)
        await repo.create_or_update(user_id=222222222)

        # Count stale profiles (older than 7 days)
        stale_count = await repo.mark_stale_profiles(days=7)

        # Recently created users should not be stale
        assert stale_count == 0

    # =========================================================================
    # search_by_name tests
    # =========================================================================

    async def test_search_by_name_matches_first_name(
        self, repo: UserRepository
    ) -> None:
        """Test searching by first name."""
        await repo.create_or_update(user_id=111111111, first_name="Alice")
        await repo.create_or_update(user_id=222222222, first_name="Bob")
        await repo.create_or_update(user_id=333333333, first_name="Alicia")

        results = await repo.search_by_name("Ali")

        assert len(results) == 2
        first_names = [u.first_name for u in results]
        assert "Alice" in first_names
        assert "Alicia" in first_names

    async def test_search_by_name_matches_last_name(
        self, repo: UserRepository
    ) -> None:
        """Test searching by last name."""
        await repo.create_or_update(user_id=111111111, first_name="John", last_name="Smith")
        await repo.create_or_update(user_id=222222222, first_name="Jane", last_name="Smithson")
        await repo.create_or_update(user_id=333333333, first_name="Bob", last_name="Jones")

        results = await repo.search_by_name("Smith")

        assert len(results) == 2

    async def test_search_by_name_matches_username(
        self, repo: UserRepository
    ) -> None:
        """Test searching by username."""
        await repo.create_or_update(user_id=111111111, username="pythondev")
        await repo.create_or_update(user_id=222222222, username="python_master")
        await repo.create_or_update(user_id=333333333, username="rubydev")

        results = await repo.search_by_name("python")

        assert len(results) == 2

    async def test_search_by_name_case_insensitive(
        self, repo: UserRepository
    ) -> None:
        """Test that search is case-insensitive."""
        await repo.create_or_update(user_id=111111111, first_name="ALICE")
        await repo.create_or_update(user_id=222222222, first_name="alice")

        results = await repo.search_by_name("Alice")

        assert len(results) == 2

    async def test_search_by_name_with_limit(self, repo: UserRepository) -> None:
        """Test search with limit."""
        for i in range(5):
            await repo.create_or_update(user_id=100000000 + i, first_name=f"Test{i}")

        results = await repo.search_by_name("Test", limit=3)
        assert len(results) == 3

    # =========================================================================
    # Relationship loading tests
    # =========================================================================

    async def test_get_by_id_with_memberships(
        self, repo: UserRepository, sample_user: User
    ) -> None:
        """Test loading user with memberships relationship."""
        user = await repo.get_by_id_with_memberships(sample_user.id)

        assert user is not None
        # Memberships should be accessible (empty for new user)
        assert user.memberships == []

    async def test_get_by_id_with_decisions(
        self, repo: UserRepository, sample_user: User
    ) -> None:
        """Test loading user with decisions relationship."""
        user = await repo.get_by_id_with_decisions(sample_user.id)

        assert user is not None
        # Decisions should be accessible (empty for new user)
        assert user.decisions == []

    async def test_get_by_id_with_all_relations(
        self, repo: UserRepository, sample_user: User
    ) -> None:
        """Test loading user with all relationships."""
        user = await repo.get_by_id_with_all_relations(sample_user.id)

        assert user is not None
        assert user.memberships == []
        assert user.decisions == []

    async def test_bulk_get_by_ids_with_memberships(
        self, repo: UserRepository
    ) -> None:
        """Test bulk get with memberships loaded."""
        await repo.create_or_update(user_id=111111111)
        await repo.create_or_update(user_id=222222222)

        users = await repo.bulk_get_by_ids_with_memberships([111111111, 222222222])

        assert len(users) == 2
        for user in users.values():
            # Memberships should be accessible
            assert user.memberships == []

    # =========================================================================
    # display_name property tests
    # =========================================================================

    async def test_display_name_full_name(self, repo: UserRepository) -> None:
        """Test display_name with first and last name."""
        user, _ = await repo.create_or_update(
            user_id=111111111,
            first_name="John",
            last_name="Doe",
        )
        assert user.display_name == "John Doe"

    async def test_display_name_first_name_only(self, repo: UserRepository) -> None:
        """Test display_name with first name only."""
        user, _ = await repo.create_or_update(
            user_id=222222222,
            first_name="Alice",
        )
        assert user.display_name == "Alice"

    async def test_display_name_username_only(self, repo: UserRepository) -> None:
        """Test display_name with username only."""
        user, _ = await repo.create_or_update(
            user_id=333333333,
            username="cooluser",
        )
        assert user.display_name == "@cooluser"

    async def test_display_name_id_fallback(self, repo: UserRepository) -> None:
        """Test display_name falls back to ID."""
        user, _ = await repo.create_or_update(user_id=444444444)
        assert user.display_name == "444444444"

    # =========================================================================
    # Base repository tests (inherited methods)
    # =========================================================================

    async def test_exists_returns_true(
        self, repo: UserRepository, sample_user: User
    ) -> None:
        """Test exists returns True for existing user."""
        exists = await repo.exists(sample_user.id)
        assert exists is True

    async def test_exists_returns_false(self, repo: UserRepository) -> None:
        """Test exists returns False for non-existent user."""
        exists = await repo.exists(9999999999)
        assert exists is False

    async def test_count(self, repo: UserRepository) -> None:
        """Test counting all users."""
        await repo.create_or_update(user_id=111111111)
        await repo.create_or_update(user_id=222222222)
        await repo.create_or_update(user_id=333333333)

        count = await repo.count()
        assert count == 3

    async def test_get_all(self, repo: UserRepository) -> None:
        """Test getting all users."""
        await repo.create_or_update(user_id=111111111)
        await repo.create_or_update(user_id=222222222)

        all_users = await repo.get_all()
        assert len(all_users) == 2

    async def test_get_all_with_pagination(self, repo: UserRepository) -> None:
        """Test pagination on get_all."""
        for i in range(5):
            await repo.create_or_update(user_id=100000000 + i)

        page1 = await repo.get_all(limit=2, offset=0)
        page2 = await repo.get_all(limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2

    async def test_delete_user(self, repo: UserRepository) -> None:
        """Test deleting a user."""
        user, _ = await repo.create_or_update(user_id=555555555)

        result = await repo.delete(user.id)
        assert result is True

        deleted = await repo.get_by_id(user.id)
        assert deleted is None

    async def test_delete_returns_false_for_missing(
        self, repo: UserRepository
    ) -> None:
        """Test delete returns False for non-existent user."""
        result = await repo.delete(9999999999)
        assert result is False
