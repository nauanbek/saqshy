"""
SAQSHY ActionEngine Tests

Comprehensive tests for the ActionEngine including:
- Verdict to action mapping
- Telegram API error handling
- Idempotency protection
- Rate limiting
- Fallback chains
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from aiogram.types import Chat, Message, User

from saqshy.bot.action_engine import (
    RESTRICT_PERMISSIONS,
    VERDICT_ACTIONS,
    ActionConfig,
    ActionEngine,
    ActionResult,
    ExecutionResult,
    execute_with_fallback,
)
from saqshy.core.types import (
    GroupType,
    RiskResult,
    Signals,
    ThreatType,
    Verdict,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_bot():
    """Create a mock bot instance."""
    bot = AsyncMock()
    bot.delete_message = AsyncMock(return_value=True)
    bot.restrict_chat_member = AsyncMock(return_value=True)
    bot.ban_chat_member = AsyncMock(return_value=True)
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.get_chat_administrators = AsyncMock(return_value=[])
    return bot


@pytest.fixture
def mock_cache():
    """Create a mock cache service with set_nx support."""
    cache = AsyncMock()
    cache.exists = AsyncMock(return_value=False)
    cache.set = AsyncMock(return_value=True)
    cache.set_nx = AsyncMock(return_value=True)  # For atomic rate limiting
    cache.set_json = AsyncMock(return_value=True)
    cache.get = AsyncMock(return_value=None)
    return cache


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_message():
    """Create a mock Telegram message."""
    user = MagicMock(spec=User)
    user.id = 123456789
    user.username = "testuser"
    user.first_name = "Test"
    user.is_bot = False

    chat = MagicMock(spec=Chat)
    chat.id = -1001234567890
    chat.type = "supergroup"
    chat.title = "Test Group"

    message = MagicMock(spec=Message)
    message.message_id = 12345
    message.from_user = user
    message.chat = chat
    message.text = "Test spam message"
    message.caption = None
    message.date = datetime.now(UTC)

    return message


@pytest.fixture
def allow_result():
    """Create ALLOW RiskResult."""
    return RiskResult(
        score=15,
        verdict=Verdict.ALLOW,
        threat_type=ThreatType.NONE,
        signals=Signals(),
        contributing_factors=[],
    )


@pytest.fixture
def watch_result():
    """Create WATCH RiskResult."""
    return RiskResult(
        score=35,
        verdict=Verdict.WATCH,
        threat_type=ThreatType.NONE,
        signals=Signals(),
        contributing_factors=["Slightly elevated risk"],
    )


@pytest.fixture
def limit_result():
    """Create LIMIT RiskResult."""
    return RiskResult(
        score=60,
        verdict=Verdict.LIMIT,
        threat_type=ThreatType.SPAM,
        signals=Signals(),
        contributing_factors=["New account", "First message"],
    )


@pytest.fixture
def review_result():
    """Create REVIEW RiskResult."""
    return RiskResult(
        score=80,
        verdict=Verdict.REVIEW,
        threat_type=ThreatType.SCAM,
        signals=Signals(),
        contributing_factors=["Suspicious links", "Urgency patterns"],
    )


@pytest.fixture
def block_result():
    """Create BLOCK RiskResult."""
    return RiskResult(
        score=95,
        verdict=Verdict.BLOCK,
        threat_type=ThreatType.CRYPTO_SCAM,
        signals=Signals(),
        contributing_factors=[
            "Crypto scam phrases",
            "No profile photo",
            "First message with link",
        ],
    )


@pytest.fixture
def action_engine(mock_bot, mock_cache, mock_db_session):
    """Create ActionEngine with mocks."""
    return ActionEngine(
        bot=mock_bot,
        cache_service=mock_cache,
        db_session=mock_db_session,
        group_type=GroupType.GENERAL,
    )


# =============================================================================
# Verdict Action Mapping Tests
# =============================================================================


class TestVerdictActionMapping:
    """Test verdict to action mapping."""

    def test_allow_has_no_actions(self):
        """ALLOW verdict should have no actions."""
        assert VERDICT_ACTIONS[Verdict.ALLOW] == []

    def test_watch_only_logs(self):
        """WATCH verdict should only log."""
        assert VERDICT_ACTIONS[Verdict.WATCH] == ["log"]

    def test_limit_restricts_and_notifies(self):
        """LIMIT verdict should restrict, log, and notify admins."""
        actions = VERDICT_ACTIONS[Verdict.LIMIT]
        assert "restrict" in actions
        assert "log" in actions
        assert "notify_admins" in actions

    def test_review_holds_and_queues(self):
        """REVIEW verdict should hold, log, queue, and notify."""
        actions = VERDICT_ACTIONS[Verdict.REVIEW]
        assert "hold" in actions
        assert "log" in actions
        assert "queue_review" in actions
        assert "notify_admins" in actions

    def test_block_deletes_and_bans(self):
        """BLOCK verdict should delete, ban, log, and notify."""
        actions = VERDICT_ACTIONS[Verdict.BLOCK]
        assert "delete" in actions
        assert "ban" in actions
        assert "log" in actions
        assert "notify_admins" in actions


# =============================================================================
# Permission Preset Tests
# =============================================================================


class TestPermissionPresets:
    """Test permission presets are correctly defined."""

    def test_soft_preset_allows_messages(self):
        """Soft preset should allow text messages."""
        preset = RESTRICT_PERMISSIONS["soft"]
        assert preset.can_send_messages is True

    def test_soft_preset_blocks_media(self):
        """Soft preset should block media."""
        preset = RESTRICT_PERMISSIONS["soft"]
        assert preset.can_send_photos is False
        assert preset.can_send_videos is False
        assert preset.can_add_web_page_previews is False

    def test_medium_preset_blocks_all_messages(self):
        """Medium preset should block all messages."""
        preset = RESTRICT_PERMISSIONS["medium"]
        assert preset.can_send_messages is False

    def test_hard_preset_full_lockdown(self):
        """Hard preset should be complete lockdown."""
        preset = RESTRICT_PERMISSIONS["hard"]
        assert preset.can_send_messages is False
        assert preset.can_invite_users is False
        assert preset.can_pin_messages is False


# =============================================================================
# ActionResult Tests
# =============================================================================


class TestActionResult:
    """Test ActionResult dataclass."""

    def test_action_result_creation(self):
        """Test creating ActionResult."""
        result = ActionResult(
            action="delete",
            success=True,
            details={"chat_id": 123},
        )
        assert result.action == "delete"
        assert result.success is True
        assert result.error is None
        assert result.details == {"chat_id": 123}

    def test_action_result_with_error(self):
        """Test ActionResult with error."""
        result = ActionResult(
            action="ban",
            success=False,
            error="User is admin",
        )
        assert result.success is False
        assert result.error == "User is admin"

    def test_action_result_to_dict(self):
        """Test ActionResult.to_dict()."""
        result = ActionResult(
            action="restrict",
            success=True,
            details={"duration": 3600},
            duration_ms=50.5,
        )
        d = result.to_dict()
        assert d["action"] == "restrict"
        assert d["success"] is True
        assert d["duration_ms"] == 50.5


# =============================================================================
# Delete Message Tests
# =============================================================================


class TestDeleteMessage:
    """Test delete_message method."""

    @pytest.mark.asyncio
    async def test_delete_message_success(self, action_engine, mock_bot):
        """Test successful message deletion."""
        result = await action_engine.delete_message(
            chat_id=-1001234567890,
            message_id=12345,
        )

        assert result.success is True
        assert result.action == "delete"
        mock_bot.delete_message.assert_called_once_with(
            chat_id=-1001234567890,
            message_id=12345,
        )

    @pytest.mark.asyncio
    async def test_delete_message_already_deleted(self, action_engine, mock_bot):
        """Test deleting an already-deleted message returns success."""
        mock_bot.delete_message.side_effect = TelegramBadRequest(
            method="deleteMessage",
            message="Bad Request: message to delete not found",
        )

        result = await action_engine.delete_message(
            chat_id=-1001234567890,
            message_id=12345,
        )

        assert result.success is True
        assert result.details.get("already_deleted") is True

    @pytest.mark.asyncio
    async def test_delete_message_timeout(self, action_engine, mock_bot):
        """Test delete message timeout handling."""
        mock_bot.delete_message.side_effect = TimeoutError()

        result = await action_engine.delete_message(
            chat_id=-1001234567890,
            message_id=12345,
        )

        assert result.success is False
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_delete_message_rate_limited(self, action_engine, mock_bot):
        """Test delete message rate limit handling."""
        mock_bot.delete_message.side_effect = TelegramRetryAfter(
            method="deleteMessage",
            message="Flood control exceeded",
            retry_after=30,
        )

        result = await action_engine.delete_message(
            chat_id=-1001234567890,
            message_id=12345,
        )

        assert result.success is False
        assert result.details.get("retry_after") == 30

    @pytest.mark.asyncio
    async def test_delete_message_forbidden(self, action_engine, mock_bot):
        """Test delete message forbidden handling."""
        mock_bot.delete_message.side_effect = TelegramForbiddenError(
            method="deleteMessage",
            message="Forbidden: bot can't delete messages",
        )

        result = await action_engine.delete_message(
            chat_id=-1001234567890,
            message_id=12345,
        )

        assert result.success is False
        assert "permission" in result.error.lower()

    @pytest.mark.asyncio
    async def test_delete_message_not_found(self, action_engine, mock_bot):
        """Test delete message when chat not found."""
        mock_bot.delete_message.side_effect = TelegramNotFound(
            method="deleteMessage",
            message="Not Found: chat not found",
        )

        result = await action_engine.delete_message(
            chat_id=-1001234567890,
            message_id=12345,
        )

        # Message is gone, so this is considered success
        assert result.success is True
        assert result.details.get("not_found") is True


# =============================================================================
# Restrict User Tests
# =============================================================================


class TestRestrictUser:
    """Test restrict_user method."""

    @pytest.mark.asyncio
    async def test_restrict_user_success(self, action_engine, mock_bot):
        """Test successful user restriction."""
        result = await action_engine.restrict_user(
            chat_id=-1001234567890,
            user_id=123456789,
            duration=3600,
        )

        assert result.success is True
        assert result.action == "restrict"
        assert result.details["duration"] == 3600
        mock_bot.restrict_chat_member.assert_called_once()

    @pytest.mark.asyncio
    async def test_restrict_user_with_preset(self, action_engine, mock_bot):
        """Test restricting user with preset."""
        result = await action_engine.restrict_user(
            chat_id=-1001234567890,
            user_id=123456789,
            duration=3600,
            preset="soft",
        )

        assert result.success is True
        call_kwargs = mock_bot.restrict_chat_member.call_args.kwargs
        permissions = call_kwargs["permissions"]
        assert permissions.can_send_messages is True

    @pytest.mark.asyncio
    async def test_restrict_admin_fails(self, action_engine, mock_bot):
        """Test restricting an admin fails gracefully."""
        mock_bot.restrict_chat_member.side_effect = TelegramBadRequest(
            method="restrictChatMember",
            message="Bad Request: user is an administrator of the chat",
        )

        result = await action_engine.restrict_user(
            chat_id=-1001234567890,
            user_id=123456789,
        )

        assert result.success is False
        assert "administrator" in result.error.lower()

    @pytest.mark.asyncio
    async def test_restrict_user_timeout(self, action_engine, mock_bot):
        """Test restrict user timeout handling."""
        mock_bot.restrict_chat_member.side_effect = TimeoutError()

        result = await action_engine.restrict_user(
            chat_id=-1001234567890,
            user_id=123456789,
        )

        assert result.success is False
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_restrict_user_forbidden(self, action_engine, mock_bot):
        """Test restrict user forbidden handling."""
        mock_bot.restrict_chat_member.side_effect = TelegramForbiddenError(
            method="restrictChatMember",
            message="Forbidden: bot is not admin",
        )

        result = await action_engine.restrict_user(
            chat_id=-1001234567890,
            user_id=123456789,
        )

        assert result.success is False
        assert "permission" in result.error.lower()


# =============================================================================
# Ban User Tests
# =============================================================================


class TestBanUser:
    """Test ban_user method."""

    @pytest.mark.asyncio
    async def test_ban_user_permanent(self, action_engine, mock_bot):
        """Test permanent user ban."""
        result = await action_engine.ban_user(
            chat_id=-1001234567890,
            user_id=123456789,
            duration=None,
        )

        assert result.success is True
        assert result.action == "ban"
        assert result.details["permanent"] is True
        mock_bot.ban_chat_member.assert_called_once()

    @pytest.mark.asyncio
    async def test_ban_user_temporary(self, action_engine, mock_bot):
        """Test temporary user ban."""
        result = await action_engine.ban_user(
            chat_id=-1001234567890,
            user_id=123456789,
            duration=86400 * 7,  # 7 days
        )

        assert result.success is True
        assert result.details["duration"] == 86400 * 7
        assert result.details["permanent"] is False

    @pytest.mark.asyncio
    async def test_ban_admin_fails(self, action_engine, mock_bot):
        """Test banning an admin fails gracefully."""
        mock_bot.ban_chat_member.side_effect = TelegramBadRequest(
            method="banChatMember",
            message="Bad Request: user is an administrator of the chat",
        )

        result = await action_engine.ban_user(
            chat_id=-1001234567890,
            user_id=123456789,
        )

        assert result.success is False
        assert "administrator" in result.error.lower()

    @pytest.mark.asyncio
    async def test_ban_user_rate_limited(self, action_engine, mock_bot):
        """Test ban user rate limit handling."""
        mock_bot.ban_chat_member.side_effect = TelegramRetryAfter(
            method="banChatMember",
            message="Flood control exceeded",
            retry_after=60,
        )

        result = await action_engine.ban_user(
            chat_id=-1001234567890,
            user_id=123456789,
        )

        assert result.success is False
        assert "rate limit" in result.error.lower()


# =============================================================================
# Notify Admins Tests
# =============================================================================


class TestNotifyAdmins:
    """Test notify_admins method."""

    @pytest.mark.asyncio
    async def test_notify_admins_success(
        self, action_engine, mock_bot, mock_cache, block_result, mock_message
    ):
        """Test successful admin notification."""
        # Set up mock admin
        admin = MagicMock()
        admin.user.id = 111222333
        admin.user.is_bot = False
        mock_bot.get_chat_administrators.return_value = [admin]

        result = await action_engine.notify_admins(
            chat_id=-1001234567890,
            risk_result=block_result,
            message=mock_message,
        )

        assert result.success is True
        assert result.details["admins_notified"] >= 1
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_admins_rate_limited(
        self, action_engine, mock_cache, block_result, mock_message
    ):
        """Test admin notification rate limiting using atomic set_nx."""
        # Simulate rate limit hit - set_nx returns False when lock already exists
        mock_cache.set_nx.return_value = False

        result = await action_engine.notify_admins(
            chat_id=-1001234567890,
            risk_result=block_result,
            message=mock_message,
        )

        assert result.success is True
        assert result.details.get("skipped") is True
        assert result.details.get("reason") == "rate_limited"

    @pytest.mark.asyncio
    async def test_notify_admins_no_admins(
        self, action_engine, mock_bot, block_result, mock_message
    ):
        """Test notification when no admins available."""
        mock_bot.get_chat_administrators.return_value = []

        result = await action_engine.notify_admins(
            chat_id=-1001234567890,
            risk_result=block_result,
            message=mock_message,
        )

        # No admins to notify is not a failure
        assert result.success is False
        assert result.details["admins_notified"] == 0

    @pytest.mark.asyncio
    async def test_notify_skips_bot_admins(
        self, action_engine, mock_bot, block_result, mock_message
    ):
        """Test that bot admins are skipped."""
        bot_admin = MagicMock()
        bot_admin.user.id = 999888777
        bot_admin.user.is_bot = True

        human_admin = MagicMock()
        human_admin.user.id = 111222333
        human_admin.user.is_bot = False

        mock_bot.get_chat_administrators.return_value = [bot_admin, human_admin]

        result = await action_engine.notify_admins(
            chat_id=-1001234567890,
            risk_result=block_result,
            message=mock_message,
        )

        # Should only attempt to notify human admin
        assert result.success is True
        mock_bot.send_message.assert_called_once()
        assert mock_bot.send_message.call_args.kwargs["chat_id"] == 111222333


# =============================================================================
# Queue For Review Tests
# =============================================================================


class TestQueueForReview:
    """Test queue_for_review method."""

    @pytest.mark.asyncio
    async def test_queue_for_review_success(
        self, action_engine, mock_cache, review_result, mock_message
    ):
        """Test successful queue for review."""
        result = await action_engine.queue_for_review(
            risk_result=review_result,
            message=mock_message,
        )

        assert result.success is True
        mock_cache.set_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_queue_for_review_no_cache(self, mock_bot, review_result, mock_message):
        """Test queue for review fails without cache."""
        engine = ActionEngine(bot=mock_bot, cache_service=None)

        result = await engine.queue_for_review(
            risk_result=review_result,
            message=mock_message,
        )

        assert result.success is False
        assert "cache" in result.error.lower()


# =============================================================================
# Execute Method Tests
# =============================================================================


class TestExecute:
    """Test the main execute method."""

    @pytest.mark.asyncio
    async def test_execute_allow_no_actions(self, action_engine, allow_result, mock_message):
        """Test ALLOW verdict executes no actions."""
        result = await action_engine.execute(
            risk_result=allow_result,
            message=mock_message,
        )

        assert result.verdict == Verdict.ALLOW
        assert len(result.actions_attempted) == 0
        assert result.message_deleted is False
        assert result.user_banned is False

    @pytest.mark.asyncio
    async def test_execute_watch_only_logs(self, action_engine, watch_result, mock_message):
        """Test WATCH verdict only logs."""
        result = await action_engine.execute(
            risk_result=watch_result,
            message=mock_message,
        )

        assert result.verdict == Verdict.WATCH
        assert any(a.action == "log" for a in result.actions_attempted)
        assert result.message_deleted is False

    @pytest.mark.asyncio
    async def test_execute_block_full_actions(
        self, action_engine, mock_bot, block_result, mock_message
    ):
        """Test BLOCK verdict executes all actions."""
        # Set up mock admin for notifications
        admin = MagicMock()
        admin.user.id = 111222333
        admin.user.is_bot = False
        mock_bot.get_chat_administrators.return_value = [admin]

        result = await action_engine.execute(
            risk_result=block_result,
            message=mock_message,
        )

        assert result.verdict == Verdict.BLOCK
        assert result.message_deleted is True
        assert result.user_banned is True
        mock_bot.delete_message.assert_called_once()
        mock_bot.ban_chat_member.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_idempotency(self, action_engine, mock_cache, block_result, mock_message):
        """Test idempotency prevents duplicate execution."""
        # First call should execute
        mock_cache.exists.return_value = False
        result1 = await action_engine.execute(
            risk_result=block_result,
            message=mock_message,
        )

        # Second call should be skipped due to idempotency
        mock_cache.exists.return_value = True
        result2 = await action_engine.execute(
            risk_result=block_result,
            message=mock_message,
        )

        # Second result should have no actions
        assert len(result2.actions_attempted) == 0


# =============================================================================
# Helper Method Tests
# =============================================================================


class TestHelperMethods:
    """Test helper methods."""

    def test_should_delete_message(self, action_engine):
        """Test should_delete_message helper."""
        assert action_engine.should_delete_message(Verdict.BLOCK) is True
        assert action_engine.should_delete_message(Verdict.ALLOW) is False
        assert action_engine.should_delete_message(Verdict.WATCH) is False

    def test_should_restrict_user(self, action_engine):
        """Test should_restrict_user helper."""
        assert action_engine.should_restrict_user(Verdict.LIMIT) is True
        assert action_engine.should_restrict_user(Verdict.REVIEW) is True
        assert action_engine.should_restrict_user(Verdict.ALLOW) is False

    def test_should_ban_user(self, action_engine):
        """Test should_ban_user helper."""
        assert action_engine.should_ban_user(Verdict.BLOCK) is True
        assert action_engine.should_ban_user(Verdict.REVIEW) is False
        assert action_engine.should_ban_user(Verdict.LIMIT) is False

    def test_should_notify_admins(self, action_engine):
        """Test should_notify_admins helper."""
        assert action_engine.should_notify_admins(Verdict.BLOCK) is True
        assert action_engine.should_notify_admins(Verdict.REVIEW) is True
        assert action_engine.should_notify_admins(Verdict.LIMIT) is True
        assert action_engine.should_notify_admins(Verdict.ALLOW) is False


# =============================================================================
# Duration Calculation Tests
# =============================================================================


class TestDurationCalculation:
    """Test duration calculation methods."""

    def test_restrict_duration_high_score(self, action_engine):
        """Test restriction duration for high risk score."""
        result = RiskResult(score=85, verdict=Verdict.LIMIT, signals=Signals())
        duration = action_engine._calculate_restrict_duration(result)
        assert duration == action_engine.config.restrict_duration_long

    def test_restrict_duration_medium_score(self, action_engine):
        """Test restriction duration for medium risk score."""
        result = RiskResult(score=65, verdict=Verdict.LIMIT, signals=Signals())
        duration = action_engine._calculate_restrict_duration(result)
        assert duration == action_engine.config.restrict_duration_medium

    def test_restrict_duration_low_score(self, action_engine):
        """Test restriction duration for lower risk score."""
        result = RiskResult(score=55, verdict=Verdict.LIMIT, signals=Signals())
        duration = action_engine._calculate_restrict_duration(result)
        assert duration == action_engine.config.restrict_duration_short

    def test_ban_duration_very_high_score(self, action_engine):
        """Test permanent ban for very high score."""
        result = RiskResult(score=97, verdict=Verdict.BLOCK, signals=Signals())
        duration = action_engine._calculate_ban_duration(result)
        assert duration is None  # Permanent

    def test_ban_duration_high_score(self, action_engine):
        """Test temp ban for high score."""
        result = RiskResult(score=90, verdict=Verdict.BLOCK, signals=Signals())
        duration = action_engine._calculate_ban_duration(result)
        assert duration == action_engine.config.ban_duration_temp


# =============================================================================
# Fallback Chain Tests
# =============================================================================


class TestFallbackChain:
    """Test execute_with_fallback function."""

    @pytest.mark.asyncio
    async def test_fallback_restrict_on_delete_failure(
        self, action_engine, mock_bot, block_result, mock_message
    ):
        """Test fallback to restrict when delete fails."""
        # Make delete fail
        mock_bot.delete_message.side_effect = TelegramForbiddenError(
            method="deleteMessage",
            message="Forbidden: bot can't delete messages",
        )

        result = await execute_with_fallback(
            engine=action_engine,
            risk_result=block_result,
            message=mock_message,
        )

        # Should have attempted restrict as fallback
        restrict_actions = [a for a in result.actions_attempted if a.action == "restrict"]
        assert len(restrict_actions) >= 1

    @pytest.mark.asyncio
    async def test_fallback_notify_on_all_failures(
        self, action_engine, mock_bot, block_result, mock_message
    ):
        """Test fallback to notify when all actions fail."""
        # Make everything fail
        mock_bot.delete_message.side_effect = TelegramForbiddenError(
            method="deleteMessage",
            message="Forbidden",
        )
        mock_bot.ban_chat_member.side_effect = TelegramForbiddenError(
            method="banChatMember",
            message="Forbidden",
        )
        mock_bot.restrict_chat_member.side_effect = TelegramForbiddenError(
            method="restrictChatMember",
            message="Forbidden",
        )

        result = await execute_with_fallback(
            engine=action_engine,
            risk_result=block_result,
            message=mock_message,
        )

        # Should still try to notify admins
        notify_actions = [a for a in result.actions_attempted if a.action == "notify_admins"]
        assert len(notify_actions) >= 1

    @pytest.mark.asyncio
    async def test_fallback_always_logs(self, action_engine, mock_bot, block_result, mock_message):
        """Test that logging always happens even on failures."""
        # Make everything fail
        mock_bot.delete_message.side_effect = TelegramForbiddenError(
            method="deleteMessage",
            message="Forbidden",
        )
        mock_bot.ban_chat_member.side_effect = TelegramForbiddenError(
            method="banChatMember",
            message="Forbidden",
        )
        mock_bot.restrict_chat_member.side_effect = TelegramForbiddenError(
            method="restrictChatMember",
            message="Forbidden",
        )

        result = await execute_with_fallback(
            engine=action_engine,
            risk_result=block_result,
            message=mock_message,
        )

        assert result.logged is True


# =============================================================================
# ActionConfig Tests
# =============================================================================


class TestActionConfig:
    """Test ActionConfig defaults and customization."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ActionConfig()
        assert config.restrict_duration_short == 3600
        assert config.restrict_duration_medium == 86400
        assert config.restrict_duration_long == 604800
        assert config.ban_duration_temp == 86400 * 30
        assert config.ban_duration_permanent is None

    def test_custom_config(self):
        """Test custom configuration."""
        config = ActionConfig(
            restrict_duration_short=1800,
            restriction_preset="hard",
            admin_notify_rate_limit=600,
        )
        assert config.restrict_duration_short == 1800
        assert config.restriction_preset == "hard"
        assert config.admin_notify_rate_limit == 600

    def test_engine_uses_config(self, mock_bot):
        """Test engine uses provided config."""
        config = ActionConfig(restriction_preset="soft")
        engine = ActionEngine(bot=mock_bot, config=config)
        assert engine.config.restriction_preset == "soft"


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_execute_with_no_from_user(self, action_engine, block_result):
        """Test execution when message has no from_user."""
        message = MagicMock(spec=Message)
        message.message_id = 12345
        message.from_user = None
        message.chat = MagicMock()
        message.chat.id = -1001234567890

        # Should not crash
        result = await action_engine.execute(
            risk_result=block_result,
            message=message,
        )

        assert result.verdict == Verdict.BLOCK

    @pytest.mark.asyncio
    async def test_execute_without_cache(self, mock_bot, block_result, mock_message):
        """Test execution without cache service."""
        engine = ActionEngine(bot=mock_bot, cache_service=None)

        # Should not crash, just skip idempotency
        result = await engine.execute(
            risk_result=block_result,
            message=mock_message,
        )

        assert result.verdict == Verdict.BLOCK

    @pytest.mark.asyncio
    async def test_execute_without_db_session(
        self, mock_bot, mock_cache, block_result, mock_message
    ):
        """Test execution without database session."""
        engine = ActionEngine(bot=mock_bot, cache_service=mock_cache, db_session=None)

        # Should not crash, just skip logging
        result = await engine.execute(
            risk_result=block_result,
            message=mock_message,
        )

        assert result.verdict == Verdict.BLOCK

    @pytest.mark.asyncio
    async def test_message_with_caption_not_text(self, action_engine, block_result):
        """Test handling message with caption instead of text."""
        message = MagicMock(spec=Message)
        message.message_id = 12345
        message.from_user = MagicMock()
        message.from_user.id = 123456789
        message.from_user.username = "spammer"
        message.chat = MagicMock()
        message.chat.id = -1001234567890
        message.text = None
        message.caption = "Spam caption here"

        result = await action_engine.execute(
            risk_result=block_result,
            message=message,
        )

        assert result.verdict == Verdict.BLOCK


# =============================================================================
# ExecutionResult Tests
# =============================================================================


class TestExecutionResult:
    """Test ExecutionResult dataclass."""

    def test_execution_result_creation(self):
        """Test creating ExecutionResult."""
        result = ExecutionResult(verdict=Verdict.BLOCK)
        assert result.verdict == Verdict.BLOCK
        assert result.message_deleted is False
        assert len(result.actions_attempted) == 0

    def test_execution_result_to_dict(self):
        """Test ExecutionResult.to_dict()."""
        result = ExecutionResult(
            verdict=Verdict.BLOCK,
            message_deleted=True,
            user_banned=True,
            total_duration_ms=150.5,
        )
        result.actions_attempted.append(ActionResult(action="delete", success=True))

        d = result.to_dict()
        assert d["verdict"] == "block"
        assert d["message_deleted"] is True
        assert d["user_banned"] is True
        assert d["total_duration_ms"] == 150.5
        assert len(d["actions_attempted"]) == 1
