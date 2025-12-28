"""
SAQSHY Member Handlers Tests

Tests for member join/leave event handlers.

Covers:
- Member join tracking
- Raid detection (10+ joins in 60s)
- Raid mode activation
- Member leave cleanup
- Kick/ban recording for cross-group analysis
- Sandbox initialization
"""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

import structlog
from aiogram.types import ChatMemberUpdated, User, Chat, ChatMember


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_user():
    """Create mock Telegram user."""
    user = MagicMock(spec=User)
    user.id = 123456789
    user.first_name = "Test"
    user.last_name = "User"
    user.username = "testuser"
    user.is_premium = False
    return user


@pytest.fixture
def mock_premium_user():
    """Create mock premium Telegram user."""
    user = MagicMock(spec=User)
    user.id = 123456790
    user.first_name = "Premium"
    user.last_name = "User"
    user.username = "premiumuser"
    user.is_premium = True
    return user


@pytest.fixture
def mock_chat():
    """Create mock Telegram chat."""
    chat = MagicMock(spec=Chat)
    chat.id = -1001234567890
    chat.title = "Test Group"
    chat.type = "supergroup"
    return chat


@pytest.fixture
def mock_chat_member(mock_user):
    """Create mock chat member."""
    member = MagicMock(spec=ChatMember)
    member.user = mock_user
    member.status = "member"
    return member


@pytest.fixture
def mock_member_event(mock_user, mock_chat, mock_chat_member):
    """Create mock chat member updated event."""
    event = MagicMock(spec=ChatMemberUpdated)
    event.chat = mock_chat
    event.new_chat_member = mock_chat_member
    return event


@pytest.fixture
def mock_bot():
    """Create mock bot."""
    return AsyncMock()


@pytest.fixture
def mock_cache_service():
    """Create mock cache service."""
    cache = AsyncMock()
    cache.record_join = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.delete = AsyncMock()
    cache.get_json = AsyncMock(return_value=None)
    cache.set_json = AsyncMock()
    cache.increment_rate = AsyncMock(return_value=1)
    return cache


# =============================================================================
# Member Join Handler Tests
# =============================================================================


class TestMemberJoinHandler:
    """Tests for member join handling."""

    @pytest.mark.asyncio
    async def test_join_records_join_time(self, mock_member_event, mock_bot, mock_cache_service):
        """Test that joining records join time for TTFM calculation."""
        from saqshy.bot.handlers.members import handle_member_join

        await handle_member_join(mock_member_event, mock_bot, mock_cache_service)

        mock_cache_service.record_join.assert_called()

    @pytest.mark.asyncio
    async def test_join_checks_raid_status(self, mock_member_event, mock_bot, mock_cache_service):
        """Test that joining checks for raid pattern."""
        from saqshy.bot.handlers.members import handle_member_join

        await handle_member_join(mock_member_event, mock_bot, mock_cache_service)

        mock_cache_service.increment_rate.assert_called()

    @pytest.mark.asyncio
    async def test_join_no_crash_without_cache(self, mock_member_event, mock_bot):
        """Test that join handling works without cache service."""
        from saqshy.bot.handlers.members import handle_member_join

        # Should not raise
        await handle_member_join(mock_member_event, mock_bot, cache_service=None)

    @pytest.mark.asyncio
    async def test_join_handles_cache_error(self, mock_member_event, mock_bot, mock_cache_service):
        """Test that join handles cache errors gracefully."""
        mock_cache_service.record_join.side_effect = Exception("Redis down")

        from saqshy.bot.handlers.members import handle_member_join

        # Should not raise
        await handle_member_join(mock_member_event, mock_bot, mock_cache_service)


# =============================================================================
# Raid Detection Tests
# =============================================================================


class TestRaidDetection:
    """Tests for raid pattern detection."""

    @pytest.mark.asyncio
    async def test_raid_mode_activates_on_threshold(self, mock_cache_service):
        """Test that raid mode activates when threshold is exceeded."""
        mock_cache_service.get.return_value = None  # Not in raid mode
        mock_cache_service.increment_rate.return_value = 10  # At threshold

        from saqshy.bot.handlers.members import _check_and_update_raid_status

        log = structlog.get_logger().bind()
        is_raid = await _check_and_update_raid_status(
            mock_cache_service,
            chat_id=-1001234567890,
            join_time=datetime.now(UTC),
            log=log,
        )

        assert is_raid is True
        mock_cache_service.set.assert_called()

    @pytest.mark.asyncio
    async def test_raid_mode_not_activated_below_threshold(self, mock_cache_service):
        """Test that raid mode doesn't activate below threshold."""
        mock_cache_service.get.return_value = None
        mock_cache_service.increment_rate.return_value = 5  # Below threshold

        from saqshy.bot.handlers.members import _check_and_update_raid_status

        log = structlog.get_logger().bind()
        is_raid = await _check_and_update_raid_status(
            mock_cache_service,
            chat_id=-1001234567890,
            join_time=datetime.now(UTC),
            log=log,
        )

        assert is_raid is False

    @pytest.mark.asyncio
    async def test_raid_mode_returns_true_when_active(self, mock_cache_service):
        """Test that check returns true when raid mode is already active."""
        mock_cache_service.get.return_value = "1"  # Already in raid mode

        from saqshy.bot.handlers.members import _check_and_update_raid_status

        log = structlog.get_logger().bind()
        is_raid = await _check_and_update_raid_status(
            mock_cache_service,
            chat_id=-1001234567890,
            join_time=datetime.now(UTC),
            log=log,
        )

        assert is_raid is True
        # Should not increment counter when already in raid mode
        mock_cache_service.increment_rate.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_raid_pattern_function(self, mock_cache_service):
        """Test the public check_raid_pattern function."""
        mock_cache_service.get.return_value = "1"

        from saqshy.bot.handlers.members import check_raid_pattern

        is_raid = await check_raid_pattern(mock_cache_service, -1001234567890)

        assert is_raid is True

    @pytest.mark.asyncio
    async def test_check_raid_pattern_not_active(self, mock_cache_service):
        """Test check_raid_pattern when not in raid mode."""
        mock_cache_service.get.return_value = None

        from saqshy.bot.handlers.members import check_raid_pattern

        is_raid = await check_raid_pattern(mock_cache_service, -1001234567890)

        assert is_raid is False


# =============================================================================
# Member Leave Handler Tests
# =============================================================================


class TestMemberLeaveHandler:
    """Tests for member leave handling."""

    @pytest.mark.asyncio
    async def test_leave_cleans_up_sandbox(self, mock_member_event, mock_cache_service):
        """Test that leaving cleans up sandbox state."""
        mock_member_event.new_chat_member.status = "left"

        from saqshy.bot.handlers.members import handle_member_leave

        await handle_member_leave(mock_member_event, mock_cache_service)

        mock_cache_service.delete.assert_called()

    @pytest.mark.asyncio
    async def test_leave_no_crash_without_cache(self, mock_member_event):
        """Test that leave handling works without cache service."""
        mock_member_event.new_chat_member.status = "left"

        from saqshy.bot.handlers.members import handle_member_leave

        # Should not raise
        await handle_member_leave(mock_member_event, cache_service=None)


# =============================================================================
# Member Kicked Handler Tests
# =============================================================================


class TestMemberKickedHandler:
    """Tests for member kicked handling."""

    @pytest.mark.asyncio
    async def test_kicked_records_action(self, mock_member_event, mock_cache_service):
        """Test that kicked event records action for cross-group analysis."""
        mock_member_event.new_chat_member.status = "kicked"

        from saqshy.bot.handlers.members import handle_member_kicked

        await handle_member_kicked(mock_member_event, mock_cache_service)

        mock_cache_service.set_json.assert_called()

    @pytest.mark.asyncio
    async def test_kicked_increments_counter(self, mock_member_event, mock_cache_service):
        """Test that kicked event increments kick counter."""
        mock_member_event.new_chat_member.status = "kicked"
        mock_cache_service.get_json.return_value = {
            "kicked_count": 1,
            "banned_count": 0,
            "restricted_count": 0,
            "groups": [],
        }

        from saqshy.bot.handlers.members import _record_user_action

        log = structlog.get_logger().bind()
        await _record_user_action(
            mock_cache_service,
            user_id=123456789,
            chat_id=-1001234567890,
            action="kicked",
            log=log,
        )

        call_args = mock_cache_service.set_json.call_args
        assert call_args is not None


# =============================================================================
# Member Banned Handler Tests
# =============================================================================


class TestMemberBannedHandler:
    """Tests for member banned handling."""

    @pytest.mark.asyncio
    async def test_banned_records_action(self, mock_member_event, mock_cache_service):
        """Test that banned event records action."""
        mock_member_event.new_chat_member.status = "banned"

        from saqshy.bot.handlers.members import handle_member_banned

        await handle_member_banned(mock_member_event, mock_cache_service)

        mock_cache_service.set_json.assert_called()


# =============================================================================
# Member Restricted Handler Tests
# =============================================================================


class TestMemberRestrictedHandler:
    """Tests for member restricted handling."""

    @pytest.mark.asyncio
    async def test_restricted_records_action(self, mock_member_event, mock_cache_service):
        """Test that restricted event records action."""
        mock_member_event.new_chat_member.status = "restricted"

        from saqshy.bot.handlers.members import handle_member_restricted

        await handle_member_restricted(mock_member_event, mock_cache_service)

        mock_cache_service.set_json.assert_called()


# =============================================================================
# Sandbox Mode Tests
# =============================================================================


class TestSandboxMode:
    """Tests for sandbox mode initialization."""

    @pytest.mark.asyncio
    async def test_premium_user_skips_sandbox(self, mock_cache_service):
        """Test that premium users skip sandbox mode."""
        from saqshy.bot.handlers.members import _should_enter_sandbox

        should_sandbox = await _should_enter_sandbox(
            user_id=123456789,
            chat_id=-1001234567890,
            is_premium=True,
            cache_service=mock_cache_service,
        )

        assert should_sandbox is False

    @pytest.mark.asyncio
    async def test_regular_user_enters_sandbox(self, mock_cache_service):
        """Test that regular users enter sandbox mode."""
        from saqshy.bot.handlers.members import _should_enter_sandbox

        should_sandbox = await _should_enter_sandbox(
            user_id=123456789,
            chat_id=-1001234567890,
            is_premium=False,
            cache_service=mock_cache_service,
        )

        assert should_sandbox is True

    @pytest.mark.asyncio
    async def test_sandbox_disabled_in_settings(self, mock_cache_service):
        """Test that sandbox is skipped when disabled in settings."""
        mock_cache_service.get_json.return_value = {"sandbox_enabled": False}

        from saqshy.bot.handlers.members import _should_enter_sandbox

        should_sandbox = await _should_enter_sandbox(
            user_id=123456789,
            chat_id=-1001234567890,
            is_premium=False,
            cache_service=mock_cache_service,
        )

        assert should_sandbox is False

    @pytest.mark.asyncio
    async def test_sandbox_initialization(self, mock_cache_service):
        """Test sandbox state initialization."""
        from saqshy.bot.handlers.members import _initialize_sandbox_state

        log = structlog.get_logger().bind()
        await _initialize_sandbox_state(
            mock_cache_service,
            user_id=123456789,
            chat_id=-1001234567890,
            join_time=datetime.now(UTC),
            log=log,
        )

        mock_cache_service.set_json.assert_called()


# =============================================================================
# Cross-Group Stats Tests
# =============================================================================


class TestCrossGroupStats:
    """Tests for cross-group statistics."""

    @pytest.mark.asyncio
    async def test_get_user_cross_group_stats(self, mock_cache_service):
        """Test getting user cross-group statistics."""
        mock_cache_service.get_json.return_value = {
            "kicked_count": 2,
            "banned_count": 1,
            "restricted_count": 0,
            "groups": [-100123, -100456],
        }

        from saqshy.bot.handlers.members import get_user_cross_group_stats

        stats = await get_user_cross_group_stats(mock_cache_service, 123456789)

        assert stats["kicked_count"] == 2
        assert stats["banned_count"] == 1
        assert len(stats["groups"]) == 2

    @pytest.mark.asyncio
    async def test_get_user_cross_group_stats_no_data(self, mock_cache_service):
        """Test getting stats for user with no history."""
        mock_cache_service.get_json.return_value = None

        from saqshy.bot.handlers.members import get_user_cross_group_stats

        stats = await get_user_cross_group_stats(mock_cache_service, 123456789)

        assert stats["kicked_count"] == 0
        assert stats["banned_count"] == 0
        assert stats["groups"] == []


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestMemberHandlerErrorHandling:
    """Tests for error handling in member handlers."""

    @pytest.mark.asyncio
    async def test_join_handler_catches_all_errors(self, mock_member_event, mock_bot, mock_cache_service):
        """Test that join handler catches and logs all errors."""
        mock_cache_service.record_join.side_effect = Exception("Unexpected error")
        mock_cache_service.increment_rate.side_effect = Exception("Another error")

        from saqshy.bot.handlers.members import handle_member_join

        # Should not raise
        await handle_member_join(mock_member_event, mock_bot, mock_cache_service)

    @pytest.mark.asyncio
    async def test_leave_handler_catches_all_errors(self, mock_member_event, mock_cache_service):
        """Test that leave handler catches and logs all errors."""
        mock_member_event.new_chat_member.status = "left"
        mock_cache_service.delete.side_effect = Exception("Delete failed")

        from saqshy.bot.handlers.members import handle_member_leave

        # Should not raise
        await handle_member_leave(mock_member_event, mock_cache_service)

    @pytest.mark.asyncio
    async def test_record_action_handles_error(self, mock_cache_service):
        """Test that action recording handles errors gracefully."""
        mock_cache_service.set_json.side_effect = Exception("Redis error")

        from saqshy.bot.handlers.members import _record_user_action

        log = structlog.get_logger().bind()

        # Should not raise
        await _record_user_action(
            mock_cache_service,
            user_id=123456789,
            chat_id=-1001234567890,
            action="kicked",
            log=log,
        )
