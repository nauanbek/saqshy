"""
Unit tests for SAQSHY Sandbox and Trust System.

Tests cover:
- SandboxState serialization/deserialization
- SandboxManager state transitions
- TrustManager level progression and regression
- SoftWatchMode evaluation
- Group type aware sandbox policy
- Channel subscription exit conditions
- Time-based expiry logic
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramAPIError

from saqshy.core.sandbox import (
    DEFAULT_APPROVED_MESSAGES_TO_RELEASE,
    DEFAULT_MIN_HOURS_IN_SANDBOX,
    DEFAULT_SANDBOX_DURATION_HOURS,
    DEFAULT_SOFT_WATCH_DURATION_HOURS,
    ReleaseReason,
    SandboxConfig,
    SandboxManager,
    SandboxState,
    SandboxStatus,
    SoftWatchMode,
    SoftWatchState,
    SoftWatchVerdict,
    TrustLevel,
    TrustManager,
)
from saqshy.core.types import (
    GroupType,
    NetworkSignals,
    RiskResult,
    Signals,
    Verdict,
)

# =============================================================================
# SandboxState Tests
# =============================================================================


class TestSandboxState:
    """Tests for SandboxState dataclass."""

    def test_sandbox_state_defaults(self):
        """Test SandboxState default values."""
        state = SandboxState(user_id=123, chat_id=-456)

        assert state.user_id == 123
        assert state.chat_id == -456
        assert state.messages_sent == 0
        assert state.approved_messages == 0
        assert state.is_released is False
        assert state.release_reason is None
        assert state.status == SandboxStatus.ACTIVE
        assert state.violations == 0
        # expires_at should be set by __post_init__
        assert state.expires_at is not None

    def test_sandbox_state_expiry_calculation(self):
        """Test that expires_at is calculated correctly from entered_at."""
        now = datetime.now(UTC)
        state = SandboxState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
        )

        expected_expiry = now + timedelta(hours=DEFAULT_SANDBOX_DURATION_HOURS)
        assert state.expires_at == expected_expiry

    def test_sandbox_state_to_dict(self):
        """Test serialization to dictionary."""
        now = datetime.now(UTC)
        expires = now + timedelta(hours=24)

        state = SandboxState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
            expires_at=expires,
            messages_sent=5,
            approved_messages=3,
            is_released=False,
            status=SandboxStatus.ACTIVE,
            violations=1,
        )

        data = state.to_dict()

        assert data["user_id"] == 123
        assert data["chat_id"] == -456
        assert data["entered_at"] == now.isoformat()
        assert data["expires_at"] == expires.isoformat()
        assert data["messages_sent"] == 5
        assert data["approved_messages"] == 3
        assert data["is_released"] is False
        assert data["status"] == "active"
        assert data["violations"] == 1

    def test_sandbox_state_from_dict(self):
        """Test deserialization from dictionary."""
        now = datetime.now(UTC)
        expires = now + timedelta(hours=24)

        data = {
            "user_id": 123,
            "chat_id": -456,
            "entered_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "messages_sent": 5,
            "approved_messages": 3,
            "is_released": True,
            "release_reason": "approved_messages",
            "status": "released",
            "violations": 0,
        }

        state = SandboxState.from_dict(data)

        assert state.user_id == 123
        assert state.chat_id == -456
        assert state.messages_sent == 5
        assert state.approved_messages == 3
        assert state.is_released is True
        assert state.release_reason == "approved_messages"
        assert state.status == SandboxStatus.RELEASED
        assert state.violations == 0

    def test_sandbox_state_is_expired(self):
        """Test is_expired method."""
        now = datetime.now(UTC)

        # Not expired
        state_active = SandboxState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
            expires_at=now + timedelta(hours=24),
        )
        assert state_active.is_expired() is False

        # Expired
        state_expired = SandboxState(
            user_id=123,
            chat_id=-456,
            entered_at=now - timedelta(hours=48),
            expires_at=now - timedelta(hours=24),
        )
        assert state_expired.is_expired() is True

    def test_sandbox_state_time_remaining(self):
        """Test time_remaining method."""
        now = datetime.now(UTC)

        # 12 hours remaining
        state = SandboxState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
            expires_at=now + timedelta(hours=12),
        )
        remaining = state.time_remaining()
        # Allow some tolerance for test execution time
        assert timedelta(hours=11, minutes=59) <= remaining <= timedelta(hours=12)

        # Already expired - should return 0
        state_expired = SandboxState(
            user_id=123,
            chat_id=-456,
            entered_at=now - timedelta(hours=48),
            expires_at=now - timedelta(hours=24),
        )
        assert state_expired.time_remaining() == timedelta(0)


# =============================================================================
# SandboxManager Tests
# =============================================================================


class TestSandboxManager:
    """Tests for SandboxManager class."""

    @pytest.fixture
    def mock_cache(self):
        """Create mock cache service."""
        cache = AsyncMock()
        cache.get_json.return_value = None
        cache.set_json.return_value = True
        cache.get.return_value = None
        cache.set.return_value = True
        return cache

    @pytest.fixture
    def mock_bot(self):
        """Create mock ChatRestrictionsProtocol."""
        bot = AsyncMock()
        bot.apply_sandbox_restrictions.return_value = True
        bot.remove_sandbox_restrictions.return_value = True
        return bot

    @pytest.fixture
    def mock_channel_service(self):
        """Create mock channel subscription service."""
        service = AsyncMock()
        service.is_subscribed.return_value = False
        return service

    @pytest.fixture
    def manager(self, mock_cache, mock_bot, mock_channel_service):
        """Create SandboxManager instance."""
        return SandboxManager(
            cache=mock_cache,
            restrictions=mock_bot,
            channel_subscription=mock_channel_service,
        )

    @pytest.mark.asyncio
    async def test_enter_sandbox_general_group(self, manager, mock_cache, mock_bot):
        """Test entering sandbox in a general group."""
        state = await manager.enter_sandbox(
            user_id=123,
            chat_id=-456,
            group_type=GroupType.GENERAL,
        )

        assert state.user_id == 123
        assert state.chat_id == -456
        assert state.status == SandboxStatus.ACTIVE
        assert state.is_released is False

        # Should save state to cache
        mock_cache.set_json.assert_called_once()

        # Should apply restrictions
        mock_bot.apply_sandbox_restrictions.assert_called_once()

    @pytest.mark.asyncio
    async def test_enter_sandbox_deals_group_soft_watch(self, manager, mock_cache, mock_bot):
        """Test that deals groups use Soft Watch mode (no restrictions)."""
        state = await manager.enter_sandbox(
            user_id=123,
            chat_id=-456,
            group_type=GroupType.DEALS,
        )

        assert state.status == SandboxStatus.SOFT_WATCH

        # Should save state to cache
        mock_cache.set_json.assert_called_once()

        # Should NOT apply restrictions for deals groups
        mock_bot.apply_sandbox_restrictions.assert_not_called()

    @pytest.mark.asyncio
    async def test_enter_sandbox_channel_subscriber_bypass(
        self, manager, mock_cache, mock_bot, mock_channel_service
    ):
        """Test that channel subscribers bypass sandbox."""
        mock_channel_service.is_subscribed.return_value = True

        state = await manager.enter_sandbox(
            user_id=123,
            chat_id=-456,
            group_type=GroupType.GENERAL,
            linked_channel_id=-789,
        )

        assert state.is_released is True
        assert state.release_reason == ReleaseReason.CHANNEL_SUBSCRIBER.value
        assert state.status == SandboxStatus.EXEMPT

        # Should NOT apply restrictions for channel subscribers
        mock_bot.apply_sandbox_restrictions.assert_not_called()

    @pytest.mark.asyncio
    async def test_enter_sandbox_already_sandboxed(self, manager, mock_cache):
        """Test that re-entering sandbox returns existing state."""
        existing_state = SandboxState(
            user_id=123,
            chat_id=-456,
            status=SandboxStatus.ACTIVE,
            is_released=False,
        )
        mock_cache.get_json.return_value = existing_state.to_dict()

        state = await manager.enter_sandbox(user_id=123, chat_id=-456)

        assert state.user_id == 123
        assert state.chat_id == -456
        # Should not call set_json again (returning existing state)
        mock_cache.set_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_is_sandboxed_active(self, manager, mock_cache):
        """Test is_sandboxed returns True for active sandbox."""
        now = datetime.now(UTC)
        state = SandboxState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
            expires_at=now + timedelta(hours=24),
            status=SandboxStatus.ACTIVE,
            is_released=False,
        )
        mock_cache.get_json.return_value = state.to_dict()

        is_sandboxed = await manager.is_sandboxed(user_id=123, chat_id=-456)

        assert is_sandboxed is True

    @pytest.mark.asyncio
    async def test_is_sandboxed_released(self, manager, mock_cache):
        """Test is_sandboxed returns False for released users."""
        state = SandboxState(
            user_id=123,
            chat_id=-456,
            status=SandboxStatus.RELEASED,
            is_released=True,
        )
        mock_cache.get_json.return_value = state.to_dict()

        is_sandboxed = await manager.is_sandboxed(user_id=123, chat_id=-456)

        assert is_sandboxed is False

    @pytest.mark.asyncio
    async def test_is_sandboxed_not_found(self, manager, mock_cache):
        """Test is_sandboxed returns False when not in sandbox."""
        mock_cache.get_json.return_value = None

        is_sandboxed = await manager.is_sandboxed(user_id=123, chat_id=-456)

        assert is_sandboxed is False

    @pytest.mark.asyncio
    async def test_record_message_increments_counters(self, manager, mock_cache):
        """Test that record_message increments message counters."""
        now = datetime.now(UTC)
        state = SandboxState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
            expires_at=now + timedelta(hours=24),
            messages_sent=0,
            approved_messages=0,
            violations=0,
        )
        mock_cache.get_json.return_value = state.to_dict()

        # Record approved message
        updated = await manager.record_message(user_id=123, chat_id=-456, approved=True)

        assert updated.messages_sent == 1
        assert updated.approved_messages == 1
        assert updated.violations == 0

    @pytest.mark.asyncio
    async def test_record_message_increments_violations(self, manager, mock_cache):
        """Test that rejected messages increment violations."""
        now = datetime.now(UTC)
        state = SandboxState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
            expires_at=now + timedelta(hours=24),
            messages_sent=0,
            approved_messages=0,
            violations=0,
        )
        mock_cache.get_json.return_value = state.to_dict()

        updated = await manager.record_message(user_id=123, chat_id=-456, approved=False)

        assert updated.messages_sent == 1
        assert updated.approved_messages == 0
        assert updated.violations == 1

    @pytest.mark.asyncio
    async def test_record_message_auto_release_on_approved_count(
        self, manager, mock_cache, mock_bot
    ):
        """Test auto-release when approved message threshold is reached."""
        # Set entered_at to more than MIN_HOURS ago
        now = datetime.now(UTC)
        entered_at = now - timedelta(hours=DEFAULT_MIN_HOURS_IN_SANDBOX + 1)

        state = SandboxState(
            user_id=123,
            chat_id=-456,
            entered_at=entered_at,
            expires_at=now + timedelta(hours=24),
            messages_sent=DEFAULT_APPROVED_MESSAGES_TO_RELEASE - 1,
            approved_messages=DEFAULT_APPROVED_MESSAGES_TO_RELEASE - 1,
            violations=0,
            status=SandboxStatus.ACTIVE,
        )
        mock_cache.get_json.return_value = state.to_dict()

        updated = await manager.record_message(user_id=123, chat_id=-456, approved=True)

        assert updated.is_released is True
        assert updated.release_reason == ReleaseReason.APPROVED_MESSAGES.value

        # Should remove restrictions
        mock_bot.remove_sandbox_restrictions.assert_called()

    @pytest.mark.asyncio
    async def test_release_from_sandbox(self, manager, mock_cache, mock_bot):
        """Test manual release from sandbox."""
        now = datetime.now(UTC)
        state = SandboxState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
            expires_at=now + timedelta(hours=24),
            status=SandboxStatus.ACTIVE,
        )
        mock_cache.get_json.return_value = state.to_dict()

        result = await manager.release_from_sandbox(
            user_id=123,
            chat_id=-456,
            reason=ReleaseReason.ADMIN_RELEASE.value,
        )

        assert result is True
        mock_bot.remove_sandbox_restrictions.assert_called()

    def test_get_sandbox_mode(self, manager):
        """Test get_sandbox_mode returns correct mode for group types."""
        assert manager.get_sandbox_mode(GroupType.GENERAL) == "sandbox"
        assert manager.get_sandbox_mode(GroupType.TECH) == "sandbox"
        assert manager.get_sandbox_mode(GroupType.CRYPTO) == "sandbox"
        assert manager.get_sandbox_mode(GroupType.DEALS) == "soft_watch"

    def test_should_apply_restrictions(self, manager):
        """Test should_apply_restrictions logic."""
        # Deals groups never restrict
        assert manager.should_apply_restrictions(GroupType.DEALS, "soft_watch") is False
        assert manager.should_apply_restrictions(GroupType.DEALS, "sandbox") is False

        # Other groups restrict in sandbox mode
        assert manager.should_apply_restrictions(GroupType.GENERAL, "sandbox") is True
        assert manager.should_apply_restrictions(GroupType.TECH, "sandbox") is True
        assert manager.should_apply_restrictions(GroupType.CRYPTO, "sandbox") is True


# =============================================================================
# SoftWatchMode Tests
# =============================================================================


class TestSoftWatchMode:
    """Tests for SoftWatchMode class."""

    @pytest.fixture
    def mock_cache(self):
        """Create mock cache service."""
        cache = AsyncMock()
        cache.get_json.return_value = None
        cache.set_json.return_value = True
        return cache

    @pytest.fixture
    def soft_watch(self, mock_cache):
        """Create SoftWatchMode instance."""
        return SoftWatchMode(cache=mock_cache)

    @pytest.mark.asyncio
    async def test_enter_soft_watch(self, soft_watch, mock_cache):
        """Test entering soft watch mode."""
        state = await soft_watch.enter_soft_watch(user_id=123, chat_id=-456)

        assert state.user_id == 123
        assert state.chat_id == -456
        assert state.messages_sent == 0
        assert state.is_completed is False

        mock_cache.set_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_message_increments_counters(self, soft_watch, mock_cache):
        """Test record_message increments counters."""
        now = datetime.now(UTC)
        state = SoftWatchState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
            expires_at=now + timedelta(hours=12),
            messages_sent=0,
        )
        mock_cache.get_json.return_value = state.to_dict()

        updated = await soft_watch.record_message(
            user_id=123,
            chat_id=-456,
            flagged=True,
            spam_db_match=True,
        )

        assert updated.messages_sent == 1
        assert updated.messages_flagged == 1
        assert updated.spam_db_matches == 1

    @pytest.mark.asyncio
    async def test_evaluate_allow_low_score(self, soft_watch, mock_cache):
        """Test evaluate returns 'allow' for low risk scores."""
        now = datetime.now(UTC)
        state = SoftWatchState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
        )
        mock_cache.get_json.return_value = state.to_dict()

        risk_result = RiskResult(
            score=30,
            verdict=Verdict.ALLOW,
            signals=Signals(network=NetworkSignals(spam_db_similarity=0.1)),
        )

        verdict = await soft_watch.evaluate(
            user_id=123,
            chat_id=-456,
            risk_result=risk_result,
        )

        assert verdict.action == "allow"
        assert verdict.should_delete is False
        assert verdict.should_notify_admin is False

    @pytest.mark.asyncio
    async def test_evaluate_consult_llm_medium_score(self, soft_watch, mock_cache):
        """Test evaluate returns 'consult_llm' for medium risk scores."""
        now = datetime.now(UTC)
        state = SoftWatchState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
        )
        mock_cache.get_json.return_value = state.to_dict()

        risk_result = RiskResult(
            score=55,  # Between 50 and 70
            verdict=Verdict.LIMIT,
            signals=Signals(network=NetworkSignals(spam_db_similarity=0.5)),
        )

        verdict = await soft_watch.evaluate(
            user_id=123,
            chat_id=-456,
            risk_result=risk_result,
        )

        assert verdict.action == "consult_llm"
        assert verdict.should_delete is False

    @pytest.mark.asyncio
    async def test_evaluate_flag_high_score(self, soft_watch, mock_cache):
        """Test evaluate returns 'flag' for high risk scores."""
        now = datetime.now(UTC)
        state = SoftWatchState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
        )
        mock_cache.get_json.return_value = state.to_dict()

        risk_result = RiskResult(
            score=75,  # Above 70
            verdict=Verdict.REVIEW,
            signals=Signals(network=NetworkSignals(spam_db_similarity=0.6)),
        )

        verdict = await soft_watch.evaluate(
            user_id=123,
            chat_id=-456,
            risk_result=risk_result,
        )

        assert verdict.action == "flag"
        assert verdict.should_delete is False
        assert verdict.should_notify_admin is True

    @pytest.mark.asyncio
    async def test_evaluate_delete_extreme_spam_match(self, soft_watch, mock_cache):
        """Test evaluate returns 'delete' for extreme spam DB matches."""
        now = datetime.now(UTC)
        state = SoftWatchState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
        )
        mock_cache.get_json.return_value = state.to_dict()

        risk_result = RiskResult(
            score=60,
            verdict=Verdict.LIMIT,
            signals=Signals(network=NetworkSignals(spam_db_similarity=0.96)),
        )

        verdict = await soft_watch.evaluate(
            user_id=123,
            chat_id=-456,
            risk_result=risk_result,
        )

        assert verdict.action == "delete"
        assert verdict.should_delete is True
        assert verdict.should_notify_admin is True


# =============================================================================
# TrustManager Tests
# =============================================================================


class TestTrustManager:
    """Tests for TrustManager class."""

    @pytest.fixture
    def mock_cache(self):
        """Create mock cache service."""
        cache = AsyncMock()
        cache.get.return_value = None
        cache.set.return_value = True
        return cache

    @pytest.fixture
    def trust_manager(self, mock_cache):
        """Create TrustManager instance."""
        return TrustManager(cache=mock_cache)

    @pytest.mark.asyncio
    async def test_get_trust_level_default(self, trust_manager, mock_cache):
        """Test get_trust_level returns UNTRUSTED by default."""
        mock_cache.get.return_value = None

        level = await trust_manager.get_trust_level(user_id=123, chat_id=-456)

        assert level == TrustLevel.UNTRUSTED

    @pytest.mark.asyncio
    async def test_get_trust_level_cached(self, trust_manager, mock_cache):
        """Test get_trust_level returns cached value."""
        mock_cache.get.return_value = "trusted"

        level = await trust_manager.get_trust_level(user_id=123, chat_id=-456)

        assert level == TrustLevel.TRUSTED

    @pytest.mark.asyncio
    async def test_set_trust_level(self, trust_manager, mock_cache):
        """Test set_trust_level saves to cache."""
        result = await trust_manager.set_trust_level(
            user_id=123, chat_id=-456, level=TrustLevel.PROVISIONAL
        )

        assert result is True
        mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_trust_block_regresses(self, trust_manager, mock_cache):
        """Test that BLOCK verdict regresses to UNTRUSTED."""
        mock_cache.get.return_value = "trusted"

        new_level = await trust_manager.update_trust(
            user_id=123,
            chat_id=-456,
            verdict=Verdict.BLOCK,
        )

        assert new_level == TrustLevel.UNTRUSTED

    @pytest.mark.asyncio
    async def test_update_trust_review_regresses(self, trust_manager, mock_cache):
        """Test that REVIEW verdict regresses to UNTRUSTED."""
        mock_cache.get.return_value = "established"

        new_level = await trust_manager.update_trust(
            user_id=123,
            chat_id=-456,
            verdict=Verdict.REVIEW,
        )

        assert new_level == TrustLevel.UNTRUSTED

    @pytest.mark.asyncio
    async def test_update_trust_limit_partial_regression(self, trust_manager, mock_cache):
        """Test that LIMIT verdict causes partial regression."""
        mock_cache.get.return_value = "established"

        new_level = await trust_manager.update_trust(
            user_id=123,
            chat_id=-456,
            verdict=Verdict.LIMIT,
        )

        assert new_level == TrustLevel.PROVISIONAL

    @pytest.mark.asyncio
    async def test_update_trust_allow_progression(self, trust_manager, mock_cache):
        """Test that ALLOW verdict allows progression."""
        mock_cache.get.return_value = "untrusted"

        # With enough approved messages, should progress
        new_level = await trust_manager.update_trust(
            user_id=123,
            chat_id=-456,
            verdict=Verdict.ALLOW,
            approved_messages=15,  # Above MESSAGES_FOR_TRUSTED
        )

        assert new_level == TrustLevel.TRUSTED

    @pytest.mark.asyncio
    async def test_update_trust_progression_to_established(self, trust_manager, mock_cache):
        """Test progression to ESTABLISHED level."""
        mock_cache.get.return_value = "trusted"

        new_level = await trust_manager.update_trust(
            user_id=123,
            chat_id=-456,
            verdict=Verdict.ALLOW,
            approved_messages=60,  # Above MESSAGES_FOR_ESTABLISHED
        )

        assert new_level == TrustLevel.ESTABLISHED

    def test_get_trust_score_adjustment(self, trust_manager):
        """Test trust score adjustments are correct."""
        assert trust_manager.get_trust_score_adjustment(TrustLevel.ESTABLISHED) == -20
        assert trust_manager.get_trust_score_adjustment(TrustLevel.TRUSTED) == -10
        assert trust_manager.get_trust_score_adjustment(TrustLevel.PROVISIONAL) == 0
        assert trust_manager.get_trust_score_adjustment(TrustLevel.UNTRUSTED) == 5


# =============================================================================
# SoftWatchVerdict Tests
# =============================================================================


class TestSoftWatchVerdict:
    """Tests for SoftWatchVerdict dataclass."""

    def test_verdict_to_dict(self):
        """Test serialization to dictionary."""
        verdict = SoftWatchVerdict(
            action="flag",
            reason="High risk score",
            confidence=0.8,
            should_delete=False,
            should_notify_admin=True,
        )

        data = verdict.to_dict()

        assert data["action"] == "flag"
        assert data["reason"] == "High risk score"
        assert data["confidence"] == 0.8
        assert data["should_delete"] is False
        assert data["should_notify_admin"] is True


# =============================================================================
# SoftWatchState Tests
# =============================================================================


class TestSoftWatchState:
    """Tests for SoftWatchState dataclass."""

    def test_soft_watch_state_defaults(self):
        """Test SoftWatchState default values."""
        state = SoftWatchState(user_id=123, chat_id=-456)

        assert state.user_id == 123
        assert state.chat_id == -456
        assert state.messages_sent == 0
        assert state.messages_flagged == 0
        assert state.spam_db_matches == 0
        assert state.is_completed is False
        assert state.expires_at is not None

    def test_soft_watch_state_to_dict(self):
        """Test serialization to dictionary."""
        now = datetime.now(UTC)
        state = SoftWatchState(
            user_id=123,
            chat_id=-456,
            entered_at=now,
            messages_sent=5,
            messages_flagged=2,
            spam_db_matches=1,
        )

        data = state.to_dict()

        assert data["user_id"] == 123
        assert data["chat_id"] == -456
        assert data["messages_sent"] == 5
        assert data["messages_flagged"] == 2
        assert data["spam_db_matches"] == 1

    def test_soft_watch_state_from_dict(self):
        """Test deserialization from dictionary."""
        now = datetime.now(UTC)
        expires = now + timedelta(hours=12)

        data = {
            "user_id": 123,
            "chat_id": -456,
            "entered_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "messages_sent": 10,
            "messages_flagged": 3,
            "spam_db_matches": 2,
            "is_completed": True,
        }

        state = SoftWatchState.from_dict(data)

        assert state.user_id == 123
        assert state.chat_id == -456
        assert state.messages_sent == 10
        assert state.messages_flagged == 3
        assert state.spam_db_matches == 2
        assert state.is_completed is True


# =============================================================================
# SandboxConfig Tests
# =============================================================================


class TestSandboxConfig:
    """Tests for SandboxConfig dataclass."""

    def test_sandbox_config_defaults(self):
        """Test SandboxConfig default values."""
        config = SandboxConfig()

        assert config.duration_hours == DEFAULT_SANDBOX_DURATION_HOURS
        assert config.soft_watch_duration_hours == DEFAULT_SOFT_WATCH_DURATION_HOURS
        assert config.approved_messages_to_release == DEFAULT_APPROVED_MESSAGES_TO_RELEASE
        assert config.min_hours_in_sandbox == DEFAULT_MIN_HOURS_IN_SANDBOX
        assert config.require_captcha is True
        assert config.allow_links is False
        assert config.allow_forwards is False
        assert config.allow_media is True
        assert config.auto_release_channel_subscribers is True
        assert config.linked_channel_id is None

    def test_sandbox_config_custom_values(self):
        """Test SandboxConfig with custom values."""
        config = SandboxConfig(
            duration_hours=48,
            approved_messages_to_release=5,
            allow_links=True,
            linked_channel_id=-789,
        )

        assert config.duration_hours == 48
        assert config.approved_messages_to_release == 5
        assert config.allow_links is True
        assert config.linked_channel_id == -789


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.fixture
    def mock_cache(self):
        """Create mock cache service."""
        cache = AsyncMock()
        cache.get_json.return_value = None
        cache.set_json.return_value = True
        cache.get.return_value = None
        cache.set.return_value = True
        return cache

    @pytest.fixture
    def mock_bot(self):
        """Create mock ChatRestrictionsProtocol."""
        bot = AsyncMock()
        bot.apply_sandbox_restrictions.return_value = True
        bot.remove_sandbox_restrictions.return_value = True
        return bot

    @pytest.mark.asyncio
    async def test_sandbox_manager_handles_cache_failure(self, mock_cache, mock_bot):
        """Test SandboxManager propagates cache failures.

        Note: Cache failures are expected to propagate up.
        The CacheService itself has circuit breaker handling.
        The SandboxManager relies on CacheService for resilience.
        """
        mock_cache.get_json.side_effect = Exception("Redis connection failed")

        manager = SandboxManager(cache=mock_cache, restrictions=mock_bot)

        # Exception should propagate up - caller should handle
        with pytest.raises(Exception, match="Redis connection failed"):
            await manager.get_sandbox_state(user_id=123, chat_id=-456)

    @pytest.mark.asyncio
    async def test_record_message_for_non_sandboxed_user(self, mock_cache, mock_bot):
        """Test record_message returns None for non-sandboxed users."""
        mock_cache.get_json.return_value = None

        manager = SandboxManager(cache=mock_cache, restrictions=mock_bot)

        result = await manager.record_message(user_id=123, chat_id=-456, approved=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_release_already_released_user(self, mock_cache, mock_bot):
        """Test releasing an already released user returns True."""
        state = SandboxState(
            user_id=123,
            chat_id=-456,
            is_released=True,
            status=SandboxStatus.RELEASED,
        )
        mock_cache.get_json.return_value = state.to_dict()

        manager = SandboxManager(cache=mock_cache, restrictions=mock_bot)

        result = await manager.release_from_sandbox(user_id=123, chat_id=-456)
        assert result is True

    @pytest.mark.asyncio
    async def test_trust_manager_handles_invalid_cached_value(self, mock_cache):
        """Test TrustManager handles invalid cached values."""
        mock_cache.get.return_value = "invalid_level"

        trust_manager = TrustManager(cache=mock_cache)

        level = await trust_manager.get_trust_level(user_id=123, chat_id=-456)
        assert level == TrustLevel.UNTRUSTED
