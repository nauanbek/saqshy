"""
SAQSHY Message Handler Tests

Comprehensive tests for message handler including:
- Message filtering (_should_process_message)
- Context building (build_message_context)
- Pipeline integration
- Action execution on verdicts
- Error handling and fail-open behavior
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Chat, Message, PhotoSize, User

from saqshy.bot.handlers.messages import (
    _should_process_message,
    build_message_context,
    compute_message_hash,
    handle_group_message,
    handle_private_message,
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
def mock_user():
    """Create a mock Telegram user."""
    user = MagicMock(spec=User)
    user.id = 123456789
    user.username = "testuser"
    user.first_name = "Test"
    user.last_name = "User"
    user.is_bot = False
    user.is_premium = False
    user.language_code = "en"
    return user


@pytest.fixture
def mock_bot_user():
    """Create a mock bot user."""
    user = MagicMock(spec=User)
    user.id = 999888777
    user.username = "some_bot"
    user.first_name = "Some"
    user.last_name = "Bot"
    user.is_bot = True
    user.is_premium = False
    user.language_code = None
    return user


@pytest.fixture
def mock_chat():
    """Create a mock supergroup chat."""
    chat = MagicMock(spec=Chat)
    chat.id = -1001234567890
    chat.type = "supergroup"
    chat.title = "Test Group"
    return chat


@pytest.fixture
def mock_private_chat():
    """Create a mock private chat."""
    chat = MagicMock(spec=Chat)
    chat.id = 123456789
    chat.type = "private"
    chat.title = None
    return chat


@pytest.fixture
def mock_message(mock_user, mock_chat):
    """Create a mock Telegram message."""
    message = MagicMock(spec=Message)
    message.message_id = 12345
    message.from_user = mock_user
    message.chat = mock_chat
    message.text = "Hello, this is a test message!"
    message.caption = None
    message.date = datetime.now(UTC)
    message.photo = None
    message.video = None
    message.document = None
    message.audio = None
    message.voice = None
    message.sticker = None
    message.forward_date = None
    message.forward_from_chat = None
    message.reply_to_message = None
    message.answer = AsyncMock()
    return message


@pytest.fixture
def mock_message_with_photo(mock_message):
    """Create a mock message with photo."""
    photo = MagicMock(spec=PhotoSize)
    photo.file_id = "photo123"
    mock_message.photo = [photo]
    mock_message.caption = "Check out this photo!"
    mock_message.text = None
    return mock_message


@pytest.fixture
def mock_forwarded_message(mock_message):
    """Create a mock forwarded message."""
    forward_chat = MagicMock()
    forward_chat.id = -1009876543210
    forward_chat.type = "channel"
    forward_chat.title = "Source Channel"
    mock_message.forward_date = datetime.now(UTC)
    mock_message.forward_from_chat = forward_chat
    return mock_message


@pytest.fixture
def mock_reply_message(mock_message):
    """Create a mock message that is a reply."""
    reply_msg = MagicMock(spec=Message)
    reply_msg.message_id = 12340
    reply_user = MagicMock(spec=User)
    reply_user.id = 111222333
    reply_user.username = "originaluser"
    reply_msg.from_user = reply_user
    mock_message.reply_to_message = reply_msg
    return mock_message


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
def mock_cache_service():
    """Create a mock cache service."""
    cache = AsyncMock()
    cache.get.return_value = None
    cache.set.return_value = True
    cache.get_json.return_value = None
    cache.set_json.return_value = True
    cache.record_message.return_value = None
    cache.record_decision.return_value = None
    cache.exists.return_value = False
    return cache


@pytest.fixture
def mock_pipeline():
    """Create a mock MessagePipeline."""
    pipeline = MagicMock()
    pipeline.process = AsyncMock(
        return_value=RiskResult(
            score=20,
            verdict=Verdict.ALLOW,
            threat_type=ThreatType.NONE,
            signals=Signals(),
            contributing_factors=[],
            mitigating_factors=[],
        )
    )
    return pipeline


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


# =============================================================================
# _should_process_message Tests
# =============================================================================


class TestShouldProcessMessage:
    """Tests for _should_process_message helper function."""

    def test_returns_false_for_no_user(self, mock_message):
        """Test that messages with no user are skipped."""
        mock_message.from_user = None
        assert _should_process_message(mock_message, False, False) is False

    def test_returns_false_for_bot_users(self, mock_message, mock_bot_user):
        """Test that messages from bots are skipped."""
        mock_message.from_user = mock_bot_user
        assert _should_process_message(mock_message, False, False) is False

    def test_returns_false_for_admin_users(self, mock_message):
        """Test that messages from admins are skipped."""
        assert _should_process_message(mock_message, True, False) is False

    def test_returns_false_for_whitelisted_users(self, mock_message):
        """Test that messages from whitelisted users are skipped."""
        assert _should_process_message(mock_message, False, True) is False

    def test_returns_false_for_empty_messages(self, mock_message):
        """Test that empty messages (no text or caption) are skipped."""
        mock_message.text = None
        mock_message.caption = None
        assert _should_process_message(mock_message, False, False) is False

    def test_returns_true_for_text_message(self, mock_message):
        """Test that normal text messages are processed."""
        assert _should_process_message(mock_message, False, False) is True

    def test_returns_true_for_caption_only_message(self, mock_message):
        """Test that messages with only caption are processed."""
        mock_message.text = None
        mock_message.caption = "Photo caption here"
        assert _should_process_message(mock_message, False, False) is True

    def test_admin_and_whitelisted_both_skip(self, mock_message):
        """Test that admin + whitelisted still skips (admin check first)."""
        assert _should_process_message(mock_message, True, True) is False


# =============================================================================
# build_message_context Tests
# =============================================================================


class TestBuildMessageContext:
    """Tests for build_message_context function."""

    @pytest.mark.asyncio
    async def test_extracts_all_user_fields(self, mock_message, mock_cache_service):
        """Test that all user fields are correctly extracted."""
        context = await build_message_context(mock_message, mock_cache_service)

        assert context.user_id == 123456789
        assert context.username == "testuser"
        assert context.first_name == "Test"
        assert context.last_name == "User"
        assert context.is_bot is False
        assert context.is_premium is False

    @pytest.mark.asyncio
    async def test_extracts_chat_fields(self, mock_message, mock_cache_service):
        """Test that chat fields are correctly extracted."""
        context = await build_message_context(mock_message, mock_cache_service)

        assert context.chat_id == -1001234567890
        assert context.chat_type == "supergroup"
        assert context.chat_title == "Test Group"

    @pytest.mark.asyncio
    async def test_extracts_message_fields(self, mock_message, mock_cache_service):
        """Test that message fields are correctly extracted."""
        context = await build_message_context(mock_message, mock_cache_service)

        assert context.message_id == 12345
        assert context.text == "Hello, this is a test message!"

    @pytest.mark.asyncio
    async def test_handles_missing_optional_fields(self, mock_message, mock_cache_service):
        """Test handling of missing optional user fields."""
        mock_message.from_user.username = None
        mock_message.from_user.last_name = None

        context = await build_message_context(mock_message, mock_cache_service)

        assert context.username is None
        assert context.last_name is None
        assert context.first_name == "Test"  # Still present

    @pytest.mark.asyncio
    async def test_handles_forwarded_messages(self, mock_forwarded_message, mock_cache_service):
        """Test that forwarded message info is extracted."""
        context = await build_message_context(mock_forwarded_message, mock_cache_service)

        assert context.is_forward is True
        assert context.forward_from_chat_id == -1009876543210

    @pytest.mark.asyncio
    async def test_handles_reply_messages(self, mock_reply_message, mock_cache_service):
        """Test that reply message info is extracted."""
        context = await build_message_context(mock_reply_message, mock_cache_service)

        assert context.reply_to_message_id == 12340

    @pytest.mark.asyncio
    async def test_handles_photo_messages(self, mock_message_with_photo, mock_cache_service):
        """Test that photo messages are properly detected."""
        context = await build_message_context(mock_message_with_photo, mock_cache_service)

        assert context.has_media is True
        assert context.media_type == "photo"
        assert context.text == "Check out this photo!"  # Uses caption

    @pytest.mark.asyncio
    async def test_defaults_to_general_group_type(self, mock_message, mock_cache_service):
        """Test that GENERAL is used when no cache entry exists."""
        mock_cache_service.get_json.return_value = None

        context = await build_message_context(mock_message, mock_cache_service)

        assert context.group_type == GroupType.GENERAL

    @pytest.mark.asyncio
    async def test_uses_cached_group_type(self, mock_message, mock_cache_service):
        """Test that group type is retrieved from cache."""
        mock_cache_service.get_json.return_value = {"group_type": "tech"}

        context = await build_message_context(mock_message, mock_cache_service)

        assert context.group_type == GroupType.TECH

    @pytest.mark.asyncio
    async def test_handles_invalid_cached_group_type(self, mock_message, mock_cache_service):
        """Test that invalid cached group type falls back to GENERAL."""
        mock_cache_service.get_json.return_value = {"group_type": "invalid_type"}

        context = await build_message_context(mock_message, mock_cache_service)

        assert context.group_type == GroupType.GENERAL

    @pytest.mark.asyncio
    async def test_works_without_cache_service(self, mock_message):
        """Test that context can be built without cache service."""
        context = await build_message_context(mock_message, None)

        assert context.group_type == GroupType.GENERAL
        assert context.user_id == 123456789

    @pytest.mark.asyncio
    async def test_raw_user_dict_populated(self, mock_message, mock_cache_service):
        """Test that raw_user dict is populated correctly."""
        context = await build_message_context(mock_message, mock_cache_service)

        assert context.raw_user["id"] == 123456789
        assert context.raw_user["username"] == "testuser"
        assert context.raw_user["first_name"] == "Test"
        assert context.raw_user["is_bot"] is False

    @pytest.mark.asyncio
    async def test_raw_message_dict_populated(self, mock_message, mock_cache_service):
        """Test that raw_message dict is populated correctly."""
        context = await build_message_context(mock_message, mock_cache_service)

        assert context.raw_message["message_id"] == 12345
        assert "date" in context.raw_message


# =============================================================================
# handle_group_message Tests
# =============================================================================


class TestHandleGroupMessage:
    """Tests for handle_group_message function."""

    @pytest.mark.asyncio
    async def test_skips_bot_messages(self, mock_message, mock_bot, mock_bot_user):
        """Test that messages from bots are skipped."""
        mock_message.from_user = mock_bot_user

        # Should return without calling any services
        await handle_group_message(mock_message, mock_bot)
        # No assertions needed - just verify no exceptions

    @pytest.mark.asyncio
    async def test_skips_admin_messages(self, mock_message, mock_bot):
        """Test that messages from admins are skipped."""
        await handle_group_message(
            mock_message,
            mock_bot,
            user_is_admin=True,
        )
        # No assertions needed - just verify no exceptions and no processing

    @pytest.mark.asyncio
    async def test_skips_whitelisted_users(self, mock_message, mock_bot, mock_cache_service):
        """Test that whitelisted users are skipped."""
        await handle_group_message(
            mock_message,
            mock_bot,
            cache_service=mock_cache_service,
            user_is_whitelisted=True,
        )
        # Pipeline should not be called

    @pytest.mark.asyncio
    async def test_skips_empty_messages(self, mock_message, mock_bot, mock_cache_service):
        """Test that empty messages are skipped."""
        mock_message.text = None
        mock_message.caption = None

        await handle_group_message(
            mock_message,
            mock_bot,
            cache_service=mock_cache_service,
        )
        # Should return without processing

    @pytest.mark.asyncio
    async def test_processes_normal_message(self, mock_message, mock_bot, mock_cache_service):
        """Test that normal messages are processed through pipeline."""
        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(
                return_value=RiskResult(
                    score=20,
                    verdict=Verdict.ALLOW,
                    threat_type=ThreatType.NONE,
                    signals=Signals(),
                    contributing_factors=[],
                )
            )
            mock_create_pipeline.return_value = mock_pipeline

            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )

            mock_create_pipeline.assert_called_once()
            mock_pipeline.process.assert_called_once()

    @pytest.mark.asyncio
    async def test_records_message_timestamp(self, mock_message, mock_bot, mock_cache_service):
        """Test that message timestamp is recorded for behavior analysis."""
        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(
                return_value=RiskResult(
                    score=20,
                    verdict=Verdict.ALLOW,
                    threat_type=ThreatType.NONE,
                    signals=Signals(),
                    contributing_factors=[],
                )
            )
            mock_create_pipeline.return_value = mock_pipeline

            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )

            mock_cache_service.record_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_pipeline_timeout(self, mock_message, mock_bot, mock_cache_service):
        """Test graceful handling of pipeline timeout."""
        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(side_effect=TimeoutError())
            mock_create_pipeline.return_value = mock_pipeline

            # Should not raise - fail open
            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )

    @pytest.mark.asyncio
    async def test_handles_pipeline_exception(self, mock_message, mock_bot, mock_cache_service):
        """Test graceful handling of pipeline exceptions."""
        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(
                side_effect=Exception("Unexpected error")
            )
            mock_create_pipeline.return_value = mock_pipeline

            # Should not raise - fail open
            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )

    @pytest.mark.asyncio
    async def test_executes_action_on_non_allow_verdict(
        self, mock_message, mock_bot, mock_cache_service
    ):
        """Test that action is executed when verdict is not ALLOW."""
        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline, patch(
            "saqshy.bot.handlers.messages.ActionEngine"
        ) as mock_action_engine_class:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(
                return_value=RiskResult(
                    score=60,
                    verdict=Verdict.LIMIT,
                    threat_type=ThreatType.SPAM,
                    signals=Signals(),
                    contributing_factors=["Spam detected"],
                )
            )
            mock_create_pipeline.return_value = mock_pipeline

            mock_action_engine = MagicMock()
            mock_action_engine.execute = AsyncMock(
                return_value=MagicMock(
                    message_deleted=True,
                    user_restricted=True,
                    user_banned=False,
                    admins_notified=True,
                    actions_attempted=[],
                )
            )
            mock_action_engine_class.return_value = mock_action_engine

            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )

            mock_action_engine.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_action_on_allow_verdict(
        self, mock_message, mock_bot, mock_cache_service
    ):
        """Test that no action is executed when verdict is ALLOW."""
        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline, patch(
            "saqshy.bot.handlers.messages.ActionEngine"
        ) as mock_action_engine_class:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(
                return_value=RiskResult(
                    score=15,
                    verdict=Verdict.ALLOW,
                    threat_type=ThreatType.NONE,
                    signals=Signals(),
                    contributing_factors=[],
                )
            )
            mock_create_pipeline.return_value = mock_pipeline

            mock_action_engine = MagicMock()
            mock_action_engine.execute = AsyncMock()
            mock_action_engine_class.return_value = mock_action_engine

            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )

            # ActionEngine.execute should NOT be called for ALLOW
            mock_action_engine.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_records_decision_in_cache(self, mock_message, mock_bot, mock_cache_service):
        """Test that decision is recorded in cache for user stats."""
        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(
                return_value=RiskResult(
                    score=20,
                    verdict=Verdict.ALLOW,
                    threat_type=ThreatType.NONE,
                    signals=Signals(),
                    contributing_factors=[],
                )
            )
            mock_create_pipeline.return_value = mock_pipeline

            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )

            mock_cache_service.record_decision.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_linked_channel_from_cache(
        self, mock_message, mock_bot, mock_cache_service
    ):
        """Test that linked channel ID is retrieved from cache."""
        mock_cache_service.get.side_effect = lambda key: (
            "999888777" if "linked_channel" in key else None
        )

        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(
                return_value=RiskResult(
                    score=20,
                    verdict=Verdict.ALLOW,
                    threat_type=ThreatType.NONE,
                    signals=Signals(),
                    contributing_factors=[],
                )
            )
            mock_create_pipeline.return_value = mock_pipeline

            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )

            # Verify pipeline.process was called with linked_channel_id
            call_kwargs = mock_pipeline.process.call_args.kwargs
            assert call_kwargs.get("linked_channel_id") == 999888777


# =============================================================================
# handle_private_message Tests
# =============================================================================


class TestHandlePrivateMessage:
    """Tests for handle_private_message function."""

    @pytest.mark.asyncio
    async def test_sends_welcome_message(self, mock_message, mock_private_chat):
        """Test that private messages receive a welcome response."""
        mock_message.chat = mock_private_chat

        await handle_private_message(mock_message)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args
        assert "SAQSHY Anti-Spam Bot" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_includes_add_to_group_button(self, mock_message, mock_private_chat):
        """Test that response includes 'Add to Group' button."""
        mock_message.chat = mock_private_chat

        await handle_private_message(mock_message)

        call_kwargs = mock_message.answer.call_args.kwargs
        reply_markup = call_kwargs.get("reply_markup")
        assert reply_markup is not None
        # Check that there's a button with URL containing startgroup
        buttons = reply_markup.inline_keyboard[0]
        assert any("startgroup" in btn.url for btn in buttons)


# =============================================================================
# compute_message_hash Tests
# =============================================================================


class TestComputeMessageHash:
    """Tests for compute_message_hash utility function."""

    def test_returns_16_char_hash(self):
        """Test that hash is 16 characters."""
        result = compute_message_hash("test message")
        assert len(result) == 16

    def test_same_input_same_hash(self):
        """Test deterministic hashing."""
        hash1 = compute_message_hash("same message")
        hash2 = compute_message_hash("same message")
        assert hash1 == hash2

    def test_different_input_different_hash(self):
        """Test different inputs produce different hashes."""
        hash1 = compute_message_hash("message one")
        hash2 = compute_message_hash("message two")
        assert hash1 != hash2

    def test_handles_unicode(self):
        """Test handling of unicode characters."""
        result = compute_message_hash("Test with emoji and Cyrillic text")
        assert len(result) == 16

    def test_handles_empty_string(self):
        """Test handling of empty string."""
        result = compute_message_hash("")
        assert len(result) == 16


# =============================================================================
# Integration-like Tests
# =============================================================================


class TestMessageProcessingFlow:
    """Tests for complete message processing flow."""

    @pytest.mark.asyncio
    async def test_spam_message_triggers_action(
        self, mock_message, mock_bot, mock_cache_service
    ):
        """Test that a spam message triggers appropriate actions."""
        mock_message.text = "URGENT! Double your Bitcoin NOW! DM me for guaranteed profits!"

        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline, patch(
            "saqshy.bot.handlers.messages.ActionEngine"
        ) as mock_action_engine_class:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(
                return_value=RiskResult(
                    score=95,
                    verdict=Verdict.BLOCK,
                    threat_type=ThreatType.CRYPTO_SCAM,
                    signals=Signals(),
                    contributing_factors=["Crypto scam phrases"],
                )
            )
            mock_create_pipeline.return_value = mock_pipeline

            mock_action_engine = MagicMock()
            mock_action_engine.execute = AsyncMock(
                return_value=MagicMock(
                    message_deleted=True,
                    user_banned=True,
                    user_restricted=False,
                    admins_notified=True,
                    actions_attempted=[],
                )
            )
            mock_action_engine_class.return_value = mock_action_engine

            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )

            # Verify actions were executed
            mock_action_engine.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_trusted_user_message_allowed(
        self, mock_message, mock_bot, mock_cache_service
    ):
        """Test that a message from a trusted user is allowed."""
        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline, patch(
            "saqshy.bot.handlers.messages.ActionEngine"
        ) as mock_action_engine_class:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(
                return_value=RiskResult(
                    score=5,
                    verdict=Verdict.ALLOW,
                    threat_type=ThreatType.NONE,
                    signals=Signals(),
                    contributing_factors=[],
                    mitigating_factors=["Long-term member", "Channel subscriber"],
                )
            )
            mock_create_pipeline.return_value = mock_pipeline

            mock_action_engine = MagicMock()
            mock_action_engine_class.return_value = mock_action_engine

            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )

            # No action should be executed for ALLOW
            mock_action_engine.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_watch_verdict_logs_only(
        self, mock_message, mock_bot, mock_cache_service
    ):
        """Test that WATCH verdict only logs without taking action."""
        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline, patch(
            "saqshy.bot.handlers.messages.ActionEngine"
        ) as mock_action_engine_class:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(
                return_value=RiskResult(
                    score=40,
                    verdict=Verdict.WATCH,
                    threat_type=ThreatType.NONE,
                    signals=Signals(),
                    contributing_factors=["Slightly suspicious"],
                )
            )
            mock_create_pipeline.return_value = mock_pipeline

            mock_action_engine = MagicMock()
            mock_action_engine.execute = AsyncMock(
                return_value=MagicMock(
                    message_deleted=False,
                    user_banned=False,
                    user_restricted=False,
                    admins_notified=False,
                    logged=True,
                    actions_attempted=[],
                )
            )
            mock_action_engine_class.return_value = mock_action_engine

            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )

            # WATCH is not ALLOW, so action engine is called
            mock_action_engine.execute.assert_called_once()


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in message processing."""

    @pytest.mark.asyncio
    async def test_record_message_timeout_doesnt_crash(
        self, mock_message, mock_bot, mock_cache_service
    ):
        """Test that record_message timeout doesn't crash processing."""
        mock_cache_service.record_message.side_effect = TimeoutError()

        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(
                return_value=RiskResult(
                    score=20,
                    verdict=Verdict.ALLOW,
                    threat_type=ThreatType.NONE,
                    signals=Signals(),
                    contributing_factors=[],
                )
            )
            mock_create_pipeline.return_value = mock_pipeline

            # Should not raise
            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )

    @pytest.mark.asyncio
    async def test_record_message_connection_error_doesnt_crash(
        self, mock_message, mock_bot, mock_cache_service
    ):
        """Test that record_message connection error doesn't crash."""
        mock_cache_service.record_message.side_effect = ConnectionError("Redis down")

        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(
                return_value=RiskResult(
                    score=20,
                    verdict=Verdict.ALLOW,
                    threat_type=ThreatType.NONE,
                    signals=Signals(),
                    contributing_factors=[],
                )
            )
            mock_create_pipeline.return_value = mock_pipeline

            # Should not raise
            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )

    @pytest.mark.asyncio
    async def test_cache_get_json_error_uses_default(
        self, mock_message, mock_bot, mock_cache_service
    ):
        """Test that cache.get_json error results in default group type."""
        mock_cache_service.get_json.side_effect = Exception("Cache error")

        with patch(
            "saqshy.bot.handlers.messages.create_pipeline"
        ) as mock_create_pipeline:
            mock_pipeline = MagicMock()
            mock_pipeline.process = AsyncMock(
                return_value=RiskResult(
                    score=20,
                    verdict=Verdict.ALLOW,
                    threat_type=ThreatType.NONE,
                    signals=Signals(),
                    contributing_factors=[],
                )
            )
            mock_create_pipeline.return_value = mock_pipeline

            # Should not raise - uses default group type
            await handle_group_message(
                mock_message,
                mock_bot,
                cache_service=mock_cache_service,
            )
