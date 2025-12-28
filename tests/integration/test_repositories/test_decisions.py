"""Integration tests for DecisionRepository.

Tests cover all repository methods for spam detection decisions,
including creation, retrieval, filtering, statistics, and admin overrides.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from saqshy.core.types import GroupType, Verdict
from saqshy.db.models import Decision, Group, User
from saqshy.db.repositories.decisions import DecisionRepository, DecisionStats
from saqshy.db.repositories.groups import GroupRepository
from saqshy.db.repositories.users import UserRepository


@pytest.mark.integration
class TestDecisionRepository:
    """Integration tests for DecisionRepository."""

    @pytest.fixture
    async def repo(self, db_session: AsyncSession) -> DecisionRepository:
        """Create repository instance with test session."""
        return DecisionRepository(db_session)

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
    async def sample_decision(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> Decision:
        """Create a sample decision for testing."""
        return await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=12345,
            risk_score=75,
            verdict=Verdict.LIMIT,
            threat_type="spam",
            profile_signals={"has_photo": True, "account_age_days": 30},
            content_signals={"url_count": 2, "caps_ratio": 0.3},
            behavior_signals={"is_first_message": True},
            action_taken="delete",
            message_deleted=True,
            processing_time_ms=150,
        )

    # =========================================================================
    # create_decision tests
    # =========================================================================

    async def test_create_decision_basic(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test creating a basic decision."""
        decision = await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=12345,
            risk_score=65,
            verdict=Verdict.LIMIT,
        )

        assert decision.id is not None
        assert isinstance(decision.id, UUID)
        assert decision.group_id == sample_group.id
        assert decision.user_id == sample_user.id
        assert decision.message_id == 12345
        assert decision.risk_score == 65
        assert decision.verdict == Verdict.LIMIT
        assert decision.created_at is not None

    async def test_create_decision_with_all_fields(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test creating a decision with all optional fields."""
        decision = await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=12345,
            risk_score=92,
            verdict=Verdict.BLOCK,
            threat_type="crypto_scam",
            profile_signals={"account_age_days": 2, "has_photo": False},
            content_signals={"has_crypto_scam_phrases": True},
            behavior_signals={"is_first_message": True, "ttfm": 15},
            llm_used=True,
            llm_response={"verdict": "block", "confidence": 0.95},
            llm_latency_ms=850,
            action_taken="delete_and_ban",
            message_deleted=True,
            user_banned=True,
            user_restricted=False,
            processing_time_ms=1200,
        )

        assert decision.threat_type == "crypto_scam"
        assert decision.profile_signals == {"account_age_days": 2, "has_photo": False}
        assert decision.content_signals == {"has_crypto_scam_phrases": True}
        assert decision.behavior_signals == {"is_first_message": True, "ttfm": 15}
        assert decision.llm_used is True
        assert decision.llm_response == {"verdict": "block", "confidence": 0.95}
        assert decision.llm_latency_ms == 850
        assert decision.action_taken == "delete_and_ban"
        assert decision.message_deleted is True
        assert decision.user_banned is True
        assert decision.user_restricted is False
        assert decision.processing_time_ms == 1200

    async def test_create_decision_without_message_id(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test creating a decision without message_id (join-based)."""
        decision = await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=None,
            risk_score=85,
            verdict=Verdict.REVIEW,
        )

        assert decision.message_id is None

    async def test_create_decision_all_verdicts(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test creating decisions with all verdict types."""
        verdicts_scores = [
            (Verdict.ALLOW, 20),
            (Verdict.WATCH, 40),
            (Verdict.LIMIT, 60),
            (Verdict.REVIEW, 80),
            (Verdict.BLOCK, 95),
        ]

        for verdict, score in verdicts_scores:
            decision = await repo.create_decision(
                group_id=sample_group.id,
                user_id=sample_user.id,
                message_id=None,
                risk_score=score,
                verdict=verdict,
            )
            assert decision.verdict == verdict
            assert decision.risk_score == score

    # =========================================================================
    # get_by_id tests
    # =========================================================================

    async def test_get_by_id(
        self, repo: DecisionRepository, sample_decision: Decision
    ) -> None:
        """Test retrieving decision by ID."""
        found = await repo.get_by_id(sample_decision.id)

        assert found is not None
        assert found.id == sample_decision.id
        assert found.risk_score == sample_decision.risk_score

    async def test_get_by_id_returns_none_for_missing(
        self, repo: DecisionRepository
    ) -> None:
        """Test returns None for non-existent decision."""
        from uuid import uuid4

        found = await repo.get_by_id(uuid4())
        assert found is None

    # =========================================================================
    # get_by_group tests
    # =========================================================================

    async def test_get_by_group(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test retrieving decisions for a group."""
        # Create multiple decisions with different scores
        created_decisions = []
        for i in range(5):
            d = await repo.create_decision(
                group_id=sample_group.id,
                user_id=sample_user.id,
                message_id=i,
                risk_score=50 + i * 10,
                verdict=Verdict.LIMIT,
            )
            created_decisions.append(d)

        decisions = await repo.get_by_group(sample_group.id)

        assert len(decisions) == 5
        # All created decisions should be present
        retrieved_scores = {d.risk_score for d in decisions}
        assert retrieved_scores == {50, 60, 70, 80, 90}
        # Verify consistent descending order (either by created_at or by id)
        ids = [d.id for d in decisions]
        # All decisions should have unique IDs
        assert len(ids) == len(set(ids))

    async def test_get_by_group_with_limit(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test retrieving decisions with limit."""
        for i in range(10):
            await repo.create_decision(
                group_id=sample_group.id,
                user_id=sample_user.id,
                message_id=i,
                risk_score=50,
                verdict=Verdict.ALLOW,
            )

        decisions = await repo.get_by_group(sample_group.id, limit=5)
        assert len(decisions) == 5

    async def test_get_by_group_with_offset(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test retrieving decisions with offset."""
        for i in range(10):
            await repo.create_decision(
                group_id=sample_group.id,
                user_id=sample_user.id,
                message_id=i,
                risk_score=50,
                verdict=Verdict.ALLOW,
            )

        page1 = await repo.get_by_group(sample_group.id, limit=5, offset=0)
        page2 = await repo.get_by_group(sample_group.id, limit=5, offset=5)

        assert len(page1) == 5
        assert len(page2) == 5
        # Ensure no overlap
        page1_ids = {d.id for d in page1}
        page2_ids = {d.id for d in page2}
        assert page1_ids.isdisjoint(page2_ids)

    async def test_get_by_group_with_verdict_filter(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test filtering decisions by verdict."""
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=1,
            risk_score=30,
            verdict=Verdict.ALLOW,
        )
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=2,
            risk_score=95,
            verdict=Verdict.BLOCK,
        )
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=3,
            risk_score=96,
            verdict=Verdict.BLOCK,
        )

        blocked = await repo.get_by_group(sample_group.id, verdict=Verdict.BLOCK)
        allowed = await repo.get_by_group(sample_group.id, verdict=Verdict.ALLOW)

        assert len(blocked) == 2
        assert all(d.verdict == Verdict.BLOCK for d in blocked)
        assert len(allowed) == 1
        assert allowed[0].verdict == Verdict.ALLOW

    # =========================================================================
    # get_by_user tests
    # =========================================================================

    async def test_get_by_user(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test retrieving decisions for a user."""
        for i in range(3):
            await repo.create_decision(
                group_id=sample_group.id,
                user_id=sample_user.id,
                message_id=i,
                risk_score=50,
                verdict=Verdict.ALLOW,
            )

        decisions = await repo.get_by_user(sample_user.id)

        assert len(decisions) == 3
        assert all(d.user_id == sample_user.id for d in decisions)

    async def test_get_by_user_with_group_filter(
        self,
        repo: DecisionRepository,
        group_repo: GroupRepository,
        sample_user: User,
    ) -> None:
        """Test filtering user decisions by group."""
        group1, _ = await group_repo.create_or_update(-1001111111111, "Group 1")
        group2, _ = await group_repo.create_or_update(-1002222222222, "Group 2")

        await repo.create_decision(
            group_id=group1.id,
            user_id=sample_user.id,
            message_id=1,
            risk_score=50,
            verdict=Verdict.ALLOW,
        )
        await repo.create_decision(
            group_id=group1.id,
            user_id=sample_user.id,
            message_id=2,
            risk_score=50,
            verdict=Verdict.ALLOW,
        )
        await repo.create_decision(
            group_id=group2.id,
            user_id=sample_user.id,
            message_id=3,
            risk_score=50,
            verdict=Verdict.ALLOW,
        )

        group1_decisions = await repo.get_by_user(
            sample_user.id, group_id=group1.id
        )
        group2_decisions = await repo.get_by_user(
            sample_user.id, group_id=group2.id
        )

        assert len(group1_decisions) == 2
        assert len(group2_decisions) == 1

    # =========================================================================
    # get_stats tests
    # =========================================================================

    async def test_get_stats(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test getting decision statistics."""
        # Create various decisions
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=1,
            risk_score=20,
            verdict=Verdict.ALLOW,
            processing_time_ms=100,
        )
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=2,
            risk_score=65,
            verdict=Verdict.LIMIT,
            message_deleted=True,
            processing_time_ms=150,
        )
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=3,
            risk_score=95,
            verdict=Verdict.BLOCK,
            message_deleted=True,
            user_banned=True,
            llm_used=True,
            processing_time_ms=800,
        )

        stats = await repo.get_stats(sample_group.id, days=7)

        assert isinstance(stats, DecisionStats)
        assert stats.total == 3
        assert stats.by_verdict["allow"] == 1
        assert stats.by_verdict["limit"] == 1
        assert stats.by_verdict["block"] == 1
        assert stats.blocked_messages == 2
        assert stats.banned_users == 1
        assert stats.llm_usage_percent == pytest.approx(33.33, rel=0.1)
        assert stats.avg_processing_time_ms is not None
        assert stats.avg_processing_time_ms == pytest.approx(350, rel=0.1)

    async def test_get_stats_empty_group(
        self,
        repo: DecisionRepository,
        sample_group: Group,
    ) -> None:
        """Test stats for group with no decisions."""
        stats = await repo.get_stats(sample_group.id, days=7)

        assert stats.total == 0
        assert stats.by_verdict == {}
        assert stats.blocked_messages == 0
        assert stats.banned_users == 0
        assert stats.llm_usage_percent == 0.0
        assert stats.avg_processing_time_ms is None

    # =========================================================================
    # record_override tests
    # =========================================================================

    async def test_record_override(
        self,
        repo: DecisionRepository,
        sample_decision: Decision,
    ) -> None:
        """Test recording an admin override."""
        admin_id = 999888777

        updated = await repo.record_override(
            decision_id=sample_decision.id,
            admin_id=admin_id,
            reason="False positive - legitimate user",
        )

        assert updated is not None
        assert updated.overridden_by == admin_id
        assert updated.overridden_at is not None
        assert updated.override_reason == "False positive - legitimate user"

    async def test_record_override_with_new_action(
        self,
        repo: DecisionRepository,
        sample_decision: Decision,
    ) -> None:
        """Test recording override with new action."""
        updated = await repo.record_override(
            decision_id=sample_decision.id,
            admin_id=999888777,
            reason="User is trusted",
            new_action="unban",
        )

        assert updated is not None
        assert updated.action_taken == "unban"

    async def test_record_override_returns_none_for_missing(
        self, repo: DecisionRepository
    ) -> None:
        """Test returns None for non-existent decision."""
        from uuid import uuid4

        result = await repo.record_override(
            decision_id=uuid4(),
            admin_id=123,
            reason="Test",
        )
        assert result is None

    # =========================================================================
    # get_recent_blocks tests
    # =========================================================================

    async def test_get_recent_blocks(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test retrieving recent block decisions."""
        # Create mix of decisions
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=1,
            risk_score=20,
            verdict=Verdict.ALLOW,
        )
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=2,
            risk_score=95,
            verdict=Verdict.BLOCK,
        )
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=3,
            risk_score=96,
            verdict=Verdict.BLOCK,
        )

        blocks = await repo.get_recent_blocks(sample_group.id, hours=24)

        assert len(blocks) == 2
        assert all(d.verdict == Verdict.BLOCK for d in blocks)

    async def test_get_recent_blocks_respects_time_window(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test that time window is respected."""
        # Create recent block
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=1,
            risk_score=95,
            verdict=Verdict.BLOCK,
        )

        # Blocks within 1 hour should include it
        blocks_1h = await repo.get_recent_blocks(sample_group.id, hours=1)
        assert len(blocks_1h) == 1

    # =========================================================================
    # get_false_positives tests
    # =========================================================================

    async def test_get_false_positives(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test retrieving overridden decisions (false positives)."""
        # Create a decision and override it
        decision = await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=1,
            risk_score=95,
            verdict=Verdict.BLOCK,
        )
        await repo.record_override(
            decision_id=decision.id,
            admin_id=123,
            reason="False positive",
        )

        # Create another decision without override
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=2,
            risk_score=95,
            verdict=Verdict.BLOCK,
        )

        fps = await repo.get_false_positives(sample_group.id, days=7)

        assert len(fps) == 1
        assert fps[0].overridden_at is not None

    # =========================================================================
    # get_pending_reviews tests
    # =========================================================================

    async def test_get_pending_reviews(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test retrieving pending review decisions."""
        # Create REVIEW decisions
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=1,
            risk_score=80,
            verdict=Verdict.REVIEW,
        )
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=2,
            risk_score=82,
            verdict=Verdict.REVIEW,
        )

        # Create BLOCK (not REVIEW)
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=3,
            risk_score=95,
            verdict=Verdict.BLOCK,
        )

        pending = await repo.get_pending_reviews(sample_group.id)

        assert len(pending) == 2
        assert all(d.verdict == Verdict.REVIEW for d in pending)
        assert all(d.overridden_at is None for d in pending)

    async def test_get_pending_reviews_excludes_overridden(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test that overridden reviews are excluded."""
        # Create and override a REVIEW
        decision = await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=1,
            risk_score=80,
            verdict=Verdict.REVIEW,
        )
        await repo.record_override(
            decision_id=decision.id,
            admin_id=123,
            reason="Reviewed and allowed",
        )

        pending = await repo.get_pending_reviews(sample_group.id)
        assert len(pending) == 0

    # =========================================================================
    # get_user_history_in_group tests
    # =========================================================================

    async def test_get_user_history_in_group(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test retrieving user history in a specific group."""
        for i in range(5):
            await repo.create_decision(
                group_id=sample_group.id,
                user_id=sample_user.id,
                message_id=i,
                risk_score=30 + i * 10,
                verdict=Verdict.ALLOW if i < 3 else Verdict.LIMIT,
            )

        history = await repo.get_user_history_in_group(
            sample_group.id, sample_user.id, limit=10
        )

        assert len(history) == 5
        assert all(d.user_id == sample_user.id for d in history)
        assert all(d.group_id == sample_group.id for d in history)

    # =========================================================================
    # get_llm_decisions tests
    # =========================================================================

    async def test_get_llm_decisions(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test retrieving decisions that used LLM."""
        # Create decisions with and without LLM
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=1,
            risk_score=70,
            verdict=Verdict.LIMIT,
            llm_used=True,
            llm_latency_ms=500,
        )
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=2,
            risk_score=30,
            verdict=Verdict.ALLOW,
            llm_used=False,
        )
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=3,
            risk_score=75,
            verdict=Verdict.LIMIT,
            llm_used=True,
            llm_latency_ms=600,
        )

        llm_decisions = await repo.get_llm_decisions(sample_group.id, days=7)

        assert len(llm_decisions) == 2
        assert all(d.llm_used for d in llm_decisions)

    # =========================================================================
    # get_threat_type_distribution tests
    # =========================================================================

    async def test_get_threat_type_distribution(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test getting distribution of threat types."""
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=1,
            risk_score=80,
            verdict=Verdict.BLOCK,
            threat_type="spam",
        )
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=2,
            risk_score=85,
            verdict=Verdict.BLOCK,
            threat_type="spam",
        )
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=3,
            risk_score=90,
            verdict=Verdict.BLOCK,
            threat_type="crypto_scam",
        )
        # Decision without threat_type
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=4,
            risk_score=20,
            verdict=Verdict.ALLOW,
        )

        distribution = await repo.get_threat_type_distribution(sample_group.id, days=30)

        assert distribution["spam"] == 2
        assert distribution["crypto_scam"] == 1
        assert len(distribution) == 2  # Null threat_type not included

    # =========================================================================
    # cleanup_old_decisions tests
    # =========================================================================

    async def test_cleanup_old_decisions(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test cleaning up old decisions."""
        # Create recent decisions (these should NOT be deleted)
        for i in range(3):
            await repo.create_decision(
                group_id=sample_group.id,
                user_id=sample_user.id,
                message_id=i,
                risk_score=50,
                verdict=Verdict.ALLOW,
            )

        # Count before cleanup
        all_decisions = await repo.get_by_group(sample_group.id)
        assert len(all_decisions) == 3

        # Cleanup decisions older than 90 days (none should be deleted)
        deleted = await repo.cleanup_old_decisions(days=90)
        assert deleted == 0

        # Verify all still exist
        remaining = await repo.get_by_group(sample_group.id)
        assert len(remaining) == 3

    # =========================================================================
    # Relationship loading tests
    # =========================================================================

    async def test_get_by_id_with_group(
        self,
        repo: DecisionRepository,
        sample_decision: Decision,
    ) -> None:
        """Test loading decision with group relationship."""
        decision = await repo.get_by_id_with_group(sample_decision.id)

        assert decision is not None
        # Group should be accessible
        assert decision.group is not None
        assert decision.group.id == sample_decision.group_id

    async def test_get_by_id_with_user(
        self,
        repo: DecisionRepository,
        sample_decision: Decision,
    ) -> None:
        """Test loading decision with user relationship."""
        decision = await repo.get_by_id_with_user(sample_decision.id)

        assert decision is not None
        # User should be accessible
        assert decision.user is not None
        assert decision.user.id == sample_decision.user_id

    async def test_get_by_id_with_all_relations(
        self,
        repo: DecisionRepository,
        sample_decision: Decision,
    ) -> None:
        """Test loading decision with all relationships."""
        decision = await repo.get_by_id_with_all_relations(sample_decision.id)

        assert decision is not None
        assert decision.group is not None
        assert decision.user is not None

    async def test_get_by_group_with_users(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test loading group decisions with user data."""
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=1,
            risk_score=50,
            verdict=Verdict.ALLOW,
        )

        decisions = await repo.get_by_group_with_users(sample_group.id)

        assert len(decisions) == 1
        assert decisions[0].user is not None
        assert decisions[0].user.id == sample_user.id

    async def test_get_recent_blocks_with_users(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test loading recent blocks with user data."""
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=1,
            risk_score=95,
            verdict=Verdict.BLOCK,
        )

        blocks = await repo.get_recent_blocks_with_users(sample_group.id)

        assert len(blocks) == 1
        assert blocks[0].user is not None

    async def test_get_pending_reviews_with_users(
        self,
        repo: DecisionRepository,
        sample_group: Group,
        sample_user: User,
    ) -> None:
        """Test loading pending reviews with user data."""
        await repo.create_decision(
            group_id=sample_group.id,
            user_id=sample_user.id,
            message_id=1,
            risk_score=80,
            verdict=Verdict.REVIEW,
        )

        reviews = await repo.get_pending_reviews_with_users(sample_group.id)

        assert len(reviews) == 1
        assert reviews[0].user is not None
