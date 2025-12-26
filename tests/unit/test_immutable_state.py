"""
Unit tests for immutable state classes.

Tests:
- Frozen dataclass behavior
- with_* helper methods
- Validation errors
- Serialization
"""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from saqshy.core.sandbox import (
    DEFAULT_SANDBOX_DURATION_HOURS,
    ReleaseReason,
    SandboxState,
    SandboxStatus,
    SoftWatchState,
)


class TestSandboxStateImmutability:
    """Tests for SandboxState frozen behavior."""

    def test_sandbox_state_is_frozen(self):
        """SandboxState should not allow direct mutation."""
        state = SandboxState(user_id=123, chat_id=-456)

        with pytest.raises(FrozenInstanceError):
            state.messages_sent = 10

    def test_sandbox_state_with_message_recorded_approved(self):
        """with_message_recorded should return new state with updated counters."""
        state = SandboxState(user_id=123, chat_id=-456)

        new_state = state.with_message_recorded(approved=True)

        # Original unchanged
        assert state.messages_sent == 0
        assert state.approved_messages == 0
        assert state.violations == 0

        # New state updated
        assert new_state.messages_sent == 1
        assert new_state.approved_messages == 1
        assert new_state.violations == 0
        assert new_state.user_id == 123  # Other fields preserved

    def test_sandbox_state_with_message_recorded_rejected(self):
        """with_message_recorded(approved=False) should increment violations."""
        state = SandboxState(user_id=123, chat_id=-456)

        new_state = state.with_message_recorded(approved=False)

        assert new_state.messages_sent == 1
        assert new_state.approved_messages == 0
        assert new_state.violations == 1

    def test_sandbox_state_with_released(self):
        """with_released should return new state marked as released."""
        state = SandboxState(user_id=123, chat_id=-456)

        new_state = state.with_released(ReleaseReason.TIME_EXPIRED.value)

        # Original unchanged
        assert not state.is_released
        assert state.status == SandboxStatus.ACTIVE

        # New state released
        assert new_state.is_released
        assert new_state.release_reason == "time_expired"
        assert new_state.status == SandboxStatus.RELEASED

    def test_sandbox_state_chained_updates(self):
        """Multiple with_* calls should chain correctly."""
        state = SandboxState(user_id=123, chat_id=-456)

        # Record three messages
        state = state.with_message_recorded(approved=True)
        state = state.with_message_recorded(approved=True)
        state = state.with_message_recorded(approved=False)

        assert state.messages_sent == 3
        assert state.approved_messages == 2
        assert state.violations == 1

        # Then release
        state = state.with_released("approved_messages")

        assert state.is_released
        assert state.messages_sent == 3


class TestSandboxStateDefaults:
    """Tests for SandboxState default values."""

    def test_default_expires_at(self):
        """expires_at should default to entered_at + duration."""
        before = datetime.now(UTC)
        state = SandboxState(user_id=123, chat_id=-456)
        after = datetime.now(UTC)

        expected_min = before + timedelta(hours=DEFAULT_SANDBOX_DURATION_HOURS)
        expected_max = after + timedelta(hours=DEFAULT_SANDBOX_DURATION_HOURS)

        assert state.expires_at is not None
        assert expected_min <= state.expires_at <= expected_max

    def test_custom_entered_at(self):
        """Custom entered_at should affect expires_at calculation."""
        entered = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        state = SandboxState(user_id=123, chat_id=-456, entered_at=entered)

        expected = entered + timedelta(hours=DEFAULT_SANDBOX_DURATION_HOURS)
        assert state.expires_at == expected

    def test_custom_expires_at(self):
        """Custom expires_at should override default."""
        entered = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        expires = datetime(2024, 1, 1, 14, 0, 0, tzinfo=UTC)

        state = SandboxState(
            user_id=123, chat_id=-456, entered_at=entered, expires_at=expires
        )

        assert state.expires_at == expires


class TestSandboxStateValidation:
    """Tests for SandboxState validation."""

    def test_negative_messages_sent_raises(self):
        """Negative messages_sent should raise ValueError."""
        with pytest.raises(ValueError, match="messages_sent cannot be negative"):
            SandboxState(user_id=123, chat_id=-456, messages_sent=-1)

    def test_negative_approved_messages_raises(self):
        """Negative approved_messages should raise ValueError."""
        with pytest.raises(ValueError, match="approved_messages cannot be negative"):
            SandboxState(user_id=123, chat_id=-456, approved_messages=-1)

    def test_negative_violations_raises(self):
        """Negative violations should raise ValueError."""
        with pytest.raises(ValueError, match="violations cannot be negative"):
            SandboxState(user_id=123, chat_id=-456, violations=-1)

    def test_valid_state_does_not_raise(self):
        """Valid state should not raise."""
        state = SandboxState(
            user_id=123,
            chat_id=-456,
            messages_sent=10,
            approved_messages=8,
            violations=2,
        )
        assert state.messages_sent == 10


class TestSandboxStateSerialization:
    """Tests for SandboxState serialization."""

    def test_to_dict_includes_all_fields(self):
        """to_dict should include all fields."""
        state = SandboxState(
            user_id=123,
            chat_id=-456,
            messages_sent=5,
            approved_messages=4,
            violations=1,
        )

        data = state.to_dict()

        assert data["user_id"] == 123
        assert data["chat_id"] == -456
        assert data["messages_sent"] == 5
        assert data["approved_messages"] == 4
        assert data["violations"] == 1
        assert data["is_released"] is False
        assert data["status"] == "active"
        assert "entered_at" in data
        assert "expires_at" in data

    def test_from_dict_round_trip(self):
        """from_dict(to_dict()) should produce equivalent state."""
        original = SandboxState(
            user_id=123,
            chat_id=-456,
            messages_sent=5,
            approved_messages=4,
            violations=1,
            is_released=True,
            release_reason="test",
            status=SandboxStatus.RELEASED,
        )

        data = original.to_dict()
        restored = SandboxState.from_dict(data)

        assert restored.user_id == original.user_id
        assert restored.chat_id == original.chat_id
        assert restored.messages_sent == original.messages_sent
        assert restored.approved_messages == original.approved_messages
        assert restored.violations == original.violations
        assert restored.is_released == original.is_released
        assert restored.release_reason == original.release_reason
        assert restored.status == original.status


class TestSandboxStateExpiry:
    """Tests for SandboxState expiry checking."""

    def test_is_expired_false_when_not_expired(self):
        """is_expired should return False for non-expired state."""
        state = SandboxState(user_id=123, chat_id=-456)
        assert not state.is_expired()

    def test_is_expired_true_when_expired(self):
        """is_expired should return True for expired state."""
        past = datetime.now(UTC) - timedelta(hours=1)
        state = SandboxState(
            user_id=123,
            chat_id=-456,
            entered_at=past - timedelta(hours=25),
            expires_at=past,
        )
        assert state.is_expired()

    def test_time_remaining_positive(self):
        """time_remaining should return positive timedelta."""
        state = SandboxState(user_id=123, chat_id=-456)
        remaining = state.time_remaining()
        assert remaining > timedelta(0)
        assert remaining <= timedelta(hours=DEFAULT_SANDBOX_DURATION_HOURS)

    def test_time_remaining_zero_when_expired(self):
        """time_remaining should return zero for expired state."""
        past = datetime.now(UTC) - timedelta(hours=1)
        state = SandboxState(
            user_id=123,
            chat_id=-456,
            entered_at=past - timedelta(hours=25),
            expires_at=past,
        )
        assert state.time_remaining() == timedelta(0)


class TestSoftWatchStateImmutability:
    """Tests for SoftWatchState frozen behavior."""

    def test_soft_watch_state_is_frozen(self):
        """SoftWatchState should not allow direct mutation."""
        state = SoftWatchState(user_id=123, chat_id=-456)

        with pytest.raises(FrozenInstanceError):
            state.messages_sent = 10

    def test_with_message_recorded_no_flags(self):
        """with_message_recorded without flags should only increment messages."""
        state = SoftWatchState(user_id=123, chat_id=-456)

        new_state = state.with_message_recorded()

        assert new_state.messages_sent == 1
        assert new_state.messages_flagged == 0
        assert new_state.spam_db_matches == 0

    def test_with_message_recorded_flagged(self):
        """with_message_recorded(flagged=True) should increment flagged."""
        state = SoftWatchState(user_id=123, chat_id=-456)

        new_state = state.with_message_recorded(flagged=True)

        assert new_state.messages_sent == 1
        assert new_state.messages_flagged == 1
        assert new_state.spam_db_matches == 0

    def test_with_message_recorded_spam_match(self):
        """with_message_recorded(spam_db_match=True) should increment matches."""
        state = SoftWatchState(user_id=123, chat_id=-456)

        new_state = state.with_message_recorded(spam_db_match=True)

        assert new_state.messages_sent == 1
        assert new_state.messages_flagged == 0
        assert new_state.spam_db_matches == 1

    def test_with_completed(self):
        """with_completed should mark state as completed."""
        state = SoftWatchState(user_id=123, chat_id=-456)

        new_state = state.with_completed()

        assert not state.is_completed
        assert new_state.is_completed


class TestSoftWatchStateValidation:
    """Tests for SoftWatchState validation."""

    def test_negative_messages_sent_raises(self):
        """Negative messages_sent should raise ValueError."""
        with pytest.raises(ValueError, match="messages_sent cannot be negative"):
            SoftWatchState(user_id=123, chat_id=-456, messages_sent=-1)

    def test_negative_messages_flagged_raises(self):
        """Negative messages_flagged should raise ValueError."""
        with pytest.raises(ValueError, match="messages_flagged cannot be negative"):
            SoftWatchState(user_id=123, chat_id=-456, messages_flagged=-1)

    def test_negative_spam_db_matches_raises(self):
        """Negative spam_db_matches should raise ValueError."""
        with pytest.raises(ValueError, match="spam_db_matches cannot be negative"):
            SoftWatchState(user_id=123, chat_id=-456, spam_db_matches=-1)


class TestSoftWatchStateSerialization:
    """Tests for SoftWatchState serialization."""

    def test_from_dict_round_trip(self):
        """from_dict(to_dict()) should produce equivalent state."""
        original = SoftWatchState(
            user_id=123,
            chat_id=-456,
            messages_sent=5,
            messages_flagged=2,
            spam_db_matches=1,
            is_completed=True,
        )

        data = original.to_dict()
        restored = SoftWatchState.from_dict(data)

        assert restored.user_id == original.user_id
        assert restored.chat_id == original.chat_id
        assert restored.messages_sent == original.messages_sent
        assert restored.messages_flagged == original.messages_flagged
        assert restored.spam_db_matches == original.spam_db_matches
        assert restored.is_completed == original.is_completed
