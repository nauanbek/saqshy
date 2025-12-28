"""
SAQSHY Callback Handlers Tests

Tests for inline keyboard callback query handlers.

Covers:
- Review approve/reject/ban callbacks
- Group type selection callbacks
- Captcha verification callbacks
- Invalid callback data handling
- Permission checks via AdminFilter
"""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import CallbackQuery, User, Message, Chat


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_user():
    """Create mock Telegram user."""
    user = MagicMock(spec=User)
    user.id = 123456789
    user.first_name = "Test"
    user.last_name = "Admin"
    user.username = "testadmin"
    user.is_premium = False
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
def mock_message(mock_chat):
    """Create mock Telegram message."""
    message = MagicMock(spec=Message)
    message.chat = mock_chat
    message.text = "Original review message"
    message.edit_text = AsyncMock()
    return message


@pytest.fixture
def mock_callback(mock_user, mock_message):
    """Create mock callback query."""
    callback = MagicMock(spec=CallbackQuery)
    callback.id = "callback123"
    callback.from_user = mock_user
    callback.message = mock_message
    callback.data = ""
    callback.answer = AsyncMock()
    return callback


@pytest.fixture
def mock_bot():
    """Create mock bot."""
    bot = AsyncMock()
    bot.ban_chat_member = AsyncMock()
    bot.restrict_chat_member = AsyncMock()
    return bot


@pytest.fixture
def mock_cache_service():
    """Create mock cache service."""
    cache = AsyncMock()
    cache.get_json = AsyncMock(return_value=None)
    cache.set_json = AsyncMock(return_value=True)
    return cache


# =============================================================================
# Review Approve Callback Tests
# =============================================================================


class TestReviewApproveCallback:
    """Tests for review approval callback handler."""

    @pytest.mark.asyncio
    async def test_approve_updates_user_trust(self, mock_callback, mock_bot, mock_cache_service):
        """Test that approval updates user trust score."""
        mock_callback.data = "review:approve:12345:987654321"

        from saqshy.bot.handlers.callbacks import callback_review_approve

        with patch("saqshy.bot.handlers.callbacks._update_user_trust", new_callable=AsyncMock) as mock_update:
            await callback_review_approve(mock_callback, mock_bot, mock_cache_service)

            mock_update.assert_called_once_with(mock_cache_service, 987654321, "approved")

    @pytest.mark.asyncio
    async def test_approve_edits_message(self, mock_callback, mock_bot, mock_cache_service):
        """Test that approval edits the review message."""
        mock_callback.data = "review:approve:12345:987654321"

        from saqshy.bot.handlers.callbacks import callback_review_approve

        with patch("saqshy.bot.handlers.callbacks._update_user_trust", new_callable=AsyncMock):
            await callback_review_approve(mock_callback, mock_bot, mock_cache_service)

            mock_callback.message.edit_text.assert_called()
            mock_callback.answer.assert_called_with("Message approved - user trust increased")

    @pytest.mark.asyncio
    async def test_approve_invalid_format(self, mock_callback, mock_bot):
        """Test approval with invalid callback data format."""
        mock_callback.data = "review:approve"  # Missing parts

        from saqshy.bot.handlers.callbacks import callback_review_approve

        await callback_review_approve(mock_callback, mock_bot)

        mock_callback.answer.assert_called_with("Invalid callback format")

    @pytest.mark.asyncio
    async def test_approve_no_data(self, mock_callback, mock_bot):
        """Test approval with no callback data."""
        mock_callback.data = None

        from saqshy.bot.handlers.callbacks import callback_review_approve

        await callback_review_approve(mock_callback, mock_bot)

        mock_callback.answer.assert_called_with("Invalid callback data")


# =============================================================================
# Review Reject Callback Tests
# =============================================================================


class TestReviewRejectCallback:
    """Tests for review rejection callback handler."""

    @pytest.mark.asyncio
    async def test_reject_updates_user_trust(self, mock_callback, mock_bot, mock_cache_service):
        """Test that rejection updates user trust negatively."""
        mock_callback.data = "review:reject:12345:987654321"

        from saqshy.bot.handlers.callbacks import callback_review_reject

        with patch("saqshy.bot.handlers.callbacks._update_user_trust", new_callable=AsyncMock) as mock_update:
            await callback_review_reject(mock_callback, mock_bot, mock_cache_service)

            mock_update.assert_called_once_with(mock_cache_service, 987654321, "rejected")

    @pytest.mark.asyncio
    async def test_reject_edits_message(self, mock_callback, mock_bot, mock_cache_service):
        """Test that rejection edits the review message."""
        mock_callback.data = "review:reject:12345:987654321"

        from saqshy.bot.handlers.callbacks import callback_review_reject

        with patch("saqshy.bot.handlers.callbacks._update_user_trust", new_callable=AsyncMock):
            await callback_review_reject(mock_callback, mock_bot, mock_cache_service)

            mock_callback.message.edit_text.assert_called()
            mock_callback.answer.assert_called_with("Message rejected - added to spam patterns")


# =============================================================================
# Review Ban Callback Tests
# =============================================================================


class TestReviewBanCallback:
    """Tests for review ban callback handler."""

    @pytest.mark.asyncio
    async def test_ban_calls_telegram_api(self, mock_callback, mock_bot, mock_cache_service):
        """Test that ban calls Telegram ban_chat_member API."""
        mock_callback.data = "review:ban:987654321:-1001234567890"

        from saqshy.bot.handlers.callbacks import callback_review_ban

        await callback_review_ban(mock_callback, mock_bot, mock_cache_service)

        mock_bot.ban_chat_member.assert_called_once_with(
            chat_id=-1001234567890, user_id=987654321
        )

    @pytest.mark.asyncio
    async def test_ban_records_in_cache(self, mock_callback, mock_bot, mock_cache_service):
        """Test that ban records action in cache for cross-group analysis."""
        mock_callback.data = "review:ban:987654321:-1001234567890"
        mock_cache_service.get_json.return_value = {
            "kicked_count": 0,
            "banned_count": 1,
            "restricted_count": 0,
            "groups": [],
        }

        from saqshy.bot.handlers.callbacks import callback_review_ban

        await callback_review_ban(mock_callback, mock_bot, mock_cache_service)

        mock_cache_service.set_json.assert_called()

    @pytest.mark.asyncio
    async def test_ban_handles_telegram_error(self, mock_callback, mock_bot, mock_cache_service):
        """Test that ban handles Telegram API errors gracefully."""
        from aiogram.exceptions import TelegramBadRequest

        mock_callback.data = "review:ban:987654321:-1001234567890"
        mock_bot.ban_chat_member.side_effect = TelegramBadRequest(
            method="banChatMember", message="Not enough rights"
        )

        from saqshy.bot.handlers.callbacks import callback_review_ban

        await callback_review_ban(mock_callback, mock_bot, mock_cache_service)

        mock_callback.answer.assert_called()
        assert "Failed to ban" in str(mock_callback.answer.call_args)


# =============================================================================
# Group Type Selection Callback Tests
# =============================================================================


class TestSetGroupTypeCallback:
    """Tests for group type selection callback handler."""

    @pytest.mark.asyncio
    async def test_set_valid_group_type(self, mock_callback, mock_cache_service):
        """Test setting a valid group type."""
        mock_callback.data = "settype:tech:-1001234567890"

        from saqshy.bot.handlers.callbacks import callback_set_group_type

        await callback_set_group_type(mock_callback, mock_cache_service)

        mock_callback.answer.assert_called_with("Group type set to tech")

    @pytest.mark.asyncio
    async def test_set_invalid_group_type(self, mock_callback, mock_cache_service):
        """Test rejecting invalid group type."""
        mock_callback.data = "settype:invalid:-1001234567890"

        from saqshy.bot.handlers.callbacks import callback_set_group_type

        await callback_set_group_type(mock_callback, mock_cache_service)

        mock_callback.answer.assert_called_with("Invalid group type")

    @pytest.mark.asyncio
    async def test_set_group_type_updates_cache(self, mock_callback, mock_cache_service):
        """Test that setting group type updates cache."""
        mock_callback.data = "settype:deals:-1001234567890"

        from saqshy.bot.handlers.callbacks import callback_set_group_type

        await callback_set_group_type(mock_callback, mock_cache_service)

        mock_cache_service.set_json.assert_called()
        call_args = mock_cache_service.set_json.call_args
        assert "group_type" in str(call_args)

    @pytest.mark.asyncio
    async def test_set_group_type_edits_message(self, mock_callback, mock_cache_service):
        """Test that setting group type edits the settings message."""
        mock_callback.data = "settype:crypto:-1001234567890"

        from saqshy.bot.handlers.callbacks import callback_set_group_type

        await callback_set_group_type(mock_callback, mock_cache_service)

        mock_callback.message.edit_text.assert_called()

    @pytest.mark.asyncio
    async def test_set_all_valid_group_types(self, mock_callback, mock_cache_service):
        """Test that all valid group types are accepted."""
        valid_types = ["general", "tech", "deals", "crypto"]

        from saqshy.bot.handlers.callbacks import callback_set_group_type

        for group_type in valid_types:
            mock_callback.data = f"settype:{group_type}:-1001234567890"
            mock_callback.answer.reset_mock()

            await callback_set_group_type(mock_callback, mock_cache_service)

            mock_callback.answer.assert_called_with(f"Group type set to {group_type}")


# =============================================================================
# Callback Data Validation Tests
# =============================================================================


class TestCallbackDataValidation:
    """Tests for callback data validation."""

    @pytest.mark.asyncio
    async def test_missing_callback_data(self, mock_callback, mock_bot):
        """Test handling of missing callback data."""
        mock_callback.data = None

        from saqshy.bot.handlers.callbacks import callback_review_approve

        await callback_review_approve(mock_callback, mock_bot)

        mock_callback.answer.assert_called_with("Invalid callback data")

    @pytest.mark.asyncio
    async def test_malformed_callback_data(self, mock_callback, mock_bot):
        """Test handling of malformed callback data."""
        mock_callback.data = "review:approve:not_a_number:also_not"

        from saqshy.bot.handlers.callbacks import callback_review_approve

        await callback_review_approve(mock_callback, mock_bot)

        mock_callback.answer.assert_called_with("Invalid callback data")

    @pytest.mark.asyncio
    async def test_empty_callback_data(self, mock_callback, mock_bot):
        """Test handling of empty callback data."""
        mock_callback.data = ""

        from saqshy.bot.handlers.callbacks import callback_review_approve

        await callback_review_approve(mock_callback, mock_bot)

        mock_callback.answer.assert_called_with("Invalid callback data")


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestCallbackErrorHandling:
    """Tests for error handling in callbacks."""

    @pytest.mark.asyncio
    async def test_cache_error_doesnt_crash(self, mock_callback, mock_bot, mock_cache_service):
        """Test that cache errors don't crash the callback."""
        mock_callback.data = "review:approve:12345:987654321"
        mock_cache_service.get_json.side_effect = Exception("Redis down")

        from saqshy.bot.handlers.callbacks import callback_review_approve

        # Should not raise
        with patch("saqshy.bot.handlers.callbacks._update_user_trust", new_callable=AsyncMock) as mock_update:
            mock_update.side_effect = Exception("Cache error")
            await callback_review_approve(mock_callback, mock_bot, mock_cache_service)

        # Should still answer the callback
        mock_callback.answer.assert_called()

    @pytest.mark.asyncio
    async def test_message_edit_error_handled(self, mock_callback, mock_bot, mock_cache_service):
        """Test that message edit errors are handled gracefully."""
        from aiogram.exceptions import TelegramBadRequest

        mock_callback.data = "review:approve:12345:987654321"
        mock_callback.message.edit_text.side_effect = TelegramBadRequest(
            method="editMessageText", message="Message not modified"
        )

        from saqshy.bot.handlers.callbacks import callback_review_approve

        with patch("saqshy.bot.handlers.callbacks._update_user_trust", new_callable=AsyncMock):
            await callback_review_approve(mock_callback, mock_bot, mock_cache_service)

        # Should still complete without raising
        mock_callback.answer.assert_called()
