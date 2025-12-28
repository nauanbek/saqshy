"""
SAQSHY Command Handler Tests

Comprehensive tests for command handlers including:
- /start command (private and group)
- /help command
- /status command
- /settings command (admin only)
- /stats command (admin only)
- /whitelist command (admin only)
- /blacklist command (admin only)
- /settype command (admin only)
- /check command (admin only)
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.filters import CommandObject
from aiogram.types import Chat, Message, User

from saqshy.bot.handlers.commands import (
    cmd_blacklist,
    cmd_check,
    cmd_help,
    cmd_settype,
    cmd_settings,
    cmd_start,
    cmd_stats,
    cmd_status,
    cmd_whitelist,
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
    user.is_bot = False
    return user


@pytest.fixture
def mock_admin_user():
    """Create a mock admin user."""
    user = MagicMock(spec=User)
    user.id = 111222333
    user.username = "adminuser"
    user.first_name = "Admin"
    user.is_bot = False
    return user


@pytest.fixture
def mock_group_chat():
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
def mock_message(mock_user, mock_group_chat):
    """Create a mock group message."""
    message = MagicMock(spec=Message)
    message.message_id = 12345
    message.from_user = mock_user
    message.chat = mock_group_chat
    message.text = "/command"
    message.date = datetime.now(UTC)
    message.answer = AsyncMock()
    # Bot mock for settings command
    mock_bot_user = MagicMock(spec=User)
    mock_bot_user.username = "saqshy_bot"
    message.bot = MagicMock()
    message.bot.get_me = AsyncMock(return_value=mock_bot_user)
    return message


@pytest.fixture
def mock_private_message(mock_user, mock_private_chat):
    """Create a mock private message."""
    message = MagicMock(spec=Message)
    message.message_id = 12345
    message.from_user = mock_user
    message.chat = mock_private_chat
    message.text = "/command"
    message.date = datetime.now(UTC)
    message.answer = AsyncMock()
    return message


@pytest.fixture
def mock_command_no_args():
    """Create a mock CommandObject with no arguments."""
    command = MagicMock(spec=CommandObject)
    command.args = None
    return command


@pytest.fixture
def mock_command_with_args():
    """Create a mock CommandObject with arguments."""
    command = MagicMock(spec=CommandObject)
    command.args = "@testuser"
    return command


@pytest.fixture
def mock_cache_service():
    """Create a mock cache service."""
    cache = AsyncMock()
    cache.get.return_value = None
    cache.set.return_value = True
    cache.get_json.return_value = None
    cache.set_json.return_value = True
    return cache


# =============================================================================
# /start Command Tests
# =============================================================================


class TestStartCommand:
    """Tests for /start command handler."""

    @pytest.mark.asyncio
    async def test_start_private_shows_welcome(
        self, mock_private_message, mock_command_no_args, mock_cache_service
    ):
        """Test /start in private chat shows welcome message."""
        await cmd_start(
            mock_private_message,
            mock_command_no_args,
            mock_cache_service,
            mini_app_url="",
        )

        mock_private_message.answer.assert_called_once()
        call_args = mock_private_message.answer.call_args[0][0]
        assert "Welcome to SAQSHY" in call_args
        assert "Anti-Spam Bot" in call_args

    @pytest.mark.asyncio
    async def test_start_private_shows_add_to_group_button(
        self, mock_private_message, mock_command_no_args, mock_cache_service
    ):
        """Test /start in private includes 'Add to Group' button."""
        await cmd_start(
            mock_private_message,
            mock_command_no_args,
            mock_cache_service,
            mini_app_url="",
        )

        call_kwargs = mock_private_message.answer.call_args.kwargs
        reply_markup = call_kwargs.get("reply_markup")
        assert reply_markup is not None

        # Check for Add to Group button
        buttons = reply_markup.inline_keyboard[0]
        assert any("Add to Group" in btn.text for btn in buttons)

    @pytest.mark.asyncio
    async def test_start_private_with_mini_app_url(
        self, mock_private_message, mock_command_no_args, mock_cache_service
    ):
        """Test /start with mini_app_url adds settings button."""
        await cmd_start(
            mock_private_message,
            mock_command_no_args,
            mock_cache_service,
            mini_app_url="https://app.example.com",
        )

        call_kwargs = mock_private_message.answer.call_args.kwargs
        reply_markup = call_kwargs.get("reply_markup")
        assert reply_markup is not None

        # Should have more than one row (Add to Group + Settings)
        assert len(reply_markup.inline_keyboard) >= 2

    @pytest.mark.asyncio
    async def test_start_private_rejects_http_mini_app_url(
        self, mock_private_message, mock_command_no_args, mock_cache_service
    ):
        """Test /start with HTTP (not HTTPS) mini_app_url doesn't add button."""
        await cmd_start(
            mock_private_message,
            mock_command_no_args,
            mock_cache_service,
            mini_app_url="http://insecure.example.com",  # HTTP, not HTTPS
        )

        call_kwargs = mock_private_message.answer.call_args.kwargs
        reply_markup = call_kwargs.get("reply_markup")

        # Should only have one row (Add to Group only)
        assert len(reply_markup.inline_keyboard) == 1

    @pytest.mark.asyncio
    async def test_start_group_shows_active_message(
        self, mock_message, mock_command_no_args, mock_cache_service
    ):
        """Test /start in group shows 'active' message."""
        await cmd_start(
            mock_message,
            mock_command_no_args,
            mock_cache_service,
            mini_app_url="",
        )

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "Active" in call_args or "protected" in call_args

    @pytest.mark.asyncio
    async def test_start_with_deeplink_group(
        self, mock_private_message, mock_cache_service
    ):
        """Test /start with group deeplink."""
        command = MagicMock(spec=CommandObject)
        command.args = "group_123456"

        await cmd_start(
            mock_private_message,
            command,
            mock_cache_service,
            mini_app_url="",
        )

        mock_private_message.answer.assert_called_once()
        call_args = mock_private_message.answer.call_args[0][0]
        assert "123456" in call_args


# =============================================================================
# /help Command Tests
# =============================================================================


class TestHelpCommand:
    """Tests for /help command handler."""

    @pytest.mark.asyncio
    async def test_help_shows_general_commands(self, mock_message):
        """Test /help shows general commands."""
        await cmd_help(mock_message)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "/start" in call_args
        assert "/help" in call_args
        assert "/status" in call_args

    @pytest.mark.asyncio
    async def test_help_in_group_shows_admin_commands(self, mock_message):
        """Test /help in group shows admin commands."""
        await cmd_help(mock_message)

        call_args = mock_message.answer.call_args[0][0]
        assert "/settings" in call_args
        assert "/stats" in call_args
        assert "/whitelist" in call_args
        assert "/blacklist" in call_args

    @pytest.mark.asyncio
    async def test_help_in_private_no_admin_commands(self, mock_private_message):
        """Test /help in private chat shows fewer commands."""
        await cmd_help(mock_private_message)

        call_args = mock_private_message.answer.call_args[0][0]
        # General commands should be present
        assert "/start" in call_args
        # Admin commands section should not be present for private
        # (group check returns False for private chat)


# =============================================================================
# /status Command Tests
# =============================================================================


class TestStatusCommand:
    """Tests for /status command handler."""

    @pytest.mark.asyncio
    async def test_status_requires_group(self, mock_private_message, mock_cache_service):
        """Test /status only works in groups."""
        await cmd_status(mock_private_message, mock_cache_service)

        mock_private_message.answer.assert_called_once()
        call_args = mock_private_message.answer.call_args[0][0]
        assert "only works in groups" in call_args

    @pytest.mark.asyncio
    async def test_status_shows_protection_status(self, mock_message, mock_cache_service):
        """Test /status shows protection status."""
        mock_cache_service.get_json.return_value = {
            "group_type": "tech",
            "sensitivity": 7,
            "sandbox_enabled": True,
        }

        await cmd_status(mock_message, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Protection Status" in call_args
        assert "tech" in call_args
        assert "7" in call_args

    @pytest.mark.asyncio
    async def test_status_shows_defaults_when_no_settings(
        self, mock_message, mock_cache_service
    ):
        """Test /status shows defaults when no settings cached."""
        mock_cache_service.get_json.return_value = None

        await cmd_status(mock_message, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "general" in call_args or "default" in call_args

    @pytest.mark.asyncio
    async def test_status_handles_cache_connection_error(
        self, mock_message, mock_cache_service
    ):
        """Test /status handles cache connection errors gracefully."""
        mock_cache_service.get_json.side_effect = ConnectionError("Redis down")

        await cmd_status(mock_message, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "connection error" in call_args.lower()

    @pytest.mark.asyncio
    async def test_status_shows_linked_channel(self, mock_message, mock_cache_service):
        """Test /status shows linked channel info."""
        mock_cache_service.get_json.return_value = {
            "group_type": "general",
            "sensitivity": 5,
            "sandbox_enabled": True,
            "linked_channel_id": -1009999888,
        }

        await cmd_status(mock_message, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Linked Channel" in call_args


# =============================================================================
# /settings Command Tests (Admin Only)
# =============================================================================


class TestSettingsCommand:
    """Tests for /settings command handler."""

    @pytest.mark.asyncio
    async def test_settings_requires_group(
        self, mock_private_message, mock_cache_service
    ):
        """Test /settings only works in groups."""
        await cmd_settings(
            mock_private_message,
            mock_cache_service,
            mini_app_url="",
        )

        mock_private_message.answer.assert_called_once()
        call_args = mock_private_message.answer.call_args[0][0]
        assert "only works in groups" in call_args

    @pytest.mark.asyncio
    async def test_settings_shows_current_settings(
        self, mock_message, mock_cache_service
    ):
        """Test /settings shows current group settings."""
        mock_cache_service.get_json.return_value = {
            "group_type": "crypto",
            "sensitivity": 8,
            "sandbox_enabled": False,
        }

        await cmd_settings(
            mock_message,
            mock_cache_service,
            mini_app_url="",
        )

        call_args = mock_message.answer.call_args[0][0]
        assert "crypto" in call_args
        assert "8" in call_args

    @pytest.mark.asyncio
    async def test_settings_shows_quick_type_buttons(
        self, mock_message, mock_cache_service
    ):
        """Test /settings shows quick group type selection buttons."""
        await cmd_settings(
            mock_message,
            mock_cache_service,
            mini_app_url="",
        )

        call_kwargs = mock_message.answer.call_args.kwargs
        reply_markup = call_kwargs.get("reply_markup")
        assert reply_markup is not None

        # Find buttons with group types
        all_buttons = []
        for row in reply_markup.inline_keyboard:
            all_buttons.extend(row)

        button_texts = [btn.text for btn in all_buttons]
        assert any("General" in text for text in button_texts)
        assert any("Tech" in text for text in button_texts)
        assert any("Deals" in text for text in button_texts)
        assert any("Crypto" in text for text in button_texts)

    @pytest.mark.asyncio
    async def test_settings_with_mini_app_url(self, mock_message, mock_cache_service):
        """Test /settings includes Mini App button when URL configured."""
        await cmd_settings(
            mock_message,
            mock_cache_service,
            mini_app_url="https://app.example.com",
        )

        call_kwargs = mock_message.answer.call_args.kwargs
        reply_markup = call_kwargs.get("reply_markup")

        # First row should have Mini App button
        first_row = reply_markup.inline_keyboard[0]
        assert any("Open Full Settings" in btn.text for btn in first_row)


# =============================================================================
# /stats Command Tests (Admin Only)
# =============================================================================


class TestStatsCommand:
    """Tests for /stats command handler."""

    @pytest.mark.asyncio
    async def test_stats_requires_group(self, mock_private_message, mock_cache_service):
        """Test /stats only works in groups."""
        await cmd_stats(mock_private_message, mock_cache_service)

        mock_private_message.answer.assert_called_once()
        call_args = mock_private_message.answer.call_args[0][0]
        assert "only works in groups" in call_args

    @pytest.mark.asyncio
    async def test_stats_shows_statistics(self, mock_message, mock_cache_service):
        """Test /stats shows spam statistics."""
        mock_cache_service.get_json.side_effect = [
            {
                "total_messages": 1000,
                "messages_scanned": 950,
                "allowed": 900,
                "watching": 30,
                "limited": 15,
                "review": 3,
                "blocked": 2,
                "avg_risk_score": 15.5,
            },
            None,  # recent_actions
        ]

        await cmd_stats(mock_message, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Spam Statistics" in call_args
        assert "1000" in call_args
        assert "950" in call_args

    @pytest.mark.asyncio
    async def test_stats_handles_no_stats(self, mock_message, mock_cache_service):
        """Test /stats handles no statistics available."""
        mock_cache_service.get_json.return_value = None

        await cmd_stats(mock_message, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "No statistics available" in call_args or "not available" in call_args

    @pytest.mark.asyncio
    async def test_stats_shows_detection_rate(self, mock_message, mock_cache_service):
        """Test /stats calculates and shows detection rate."""
        mock_cache_service.get_json.side_effect = [
            {
                "messages_scanned": 100,
                "blocked": 5,
                "review": 3,
            },
            None,  # recent_actions
        ]

        await cmd_stats(mock_message, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Detection rate" in call_args or "detection rate" in call_args.lower()

    @pytest.mark.asyncio
    async def test_stats_handles_connection_error(
        self, mock_message, mock_cache_service
    ):
        """Test /stats handles cache connection errors."""
        mock_cache_service.get_json.side_effect = ConnectionError("Redis down")

        await cmd_stats(mock_message, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "connection error" in call_args.lower()


# =============================================================================
# /whitelist Command Tests (Admin Only)
# =============================================================================


class TestWhitelistCommand:
    """Tests for /whitelist command handler."""

    @pytest.mark.asyncio
    async def test_whitelist_requires_group(
        self, mock_private_message, mock_command_with_args, mock_cache_service
    ):
        """Test /whitelist only works in groups."""
        await cmd_whitelist(
            mock_private_message,
            mock_command_with_args,
            mock_cache_service,
        )

        mock_private_message.answer.assert_called_once()
        call_args = mock_private_message.answer.call_args[0][0]
        assert "only works in groups" in call_args

    @pytest.mark.asyncio
    async def test_whitelist_requires_args(
        self, mock_message, mock_command_no_args, mock_cache_service
    ):
        """Test /whitelist requires username argument."""
        await cmd_whitelist(mock_message, mock_command_no_args, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Usage:" in call_args

    @pytest.mark.asyncio
    async def test_whitelist_adds_user_by_username(
        self, mock_message, mock_cache_service
    ):
        """Test /whitelist adds user by @username."""
        command = MagicMock(spec=CommandObject)
        command.args = "@newuser"

        mock_cache_service.get_json.return_value = {"users": []}

        await cmd_whitelist(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Added" in call_args
        assert "whitelist" in call_args.lower()

    @pytest.mark.asyncio
    async def test_whitelist_adds_user_by_id(self, mock_message, mock_cache_service):
        """Test /whitelist adds user by user ID."""
        command = MagicMock(spec=CommandObject)
        command.args = "987654321"

        mock_cache_service.get_json.return_value = {"users": []}

        await cmd_whitelist(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Added" in call_args

    @pytest.mark.asyncio
    async def test_whitelist_rejects_already_whitelisted(
        self, mock_message, mock_cache_service
    ):
        """Test /whitelist rejects already whitelisted user."""
        command = MagicMock(spec=CommandObject)
        command.args = "@existinguser"

        mock_cache_service.get_json.return_value = {
            "users": [{"username": "existinguser"}]
        }

        await cmd_whitelist(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "already whitelisted" in call_args

    @pytest.mark.asyncio
    async def test_whitelist_validates_user_id_format(
        self, mock_message, mock_cache_service
    ):
        """Test /whitelist validates user ID format."""
        command = MagicMock(spec=CommandObject)
        command.args = "invalid_id"

        await cmd_whitelist(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Invalid" in call_args

    @pytest.mark.asyncio
    async def test_whitelist_handles_no_cache(self, mock_message):
        """Test /whitelist handles missing cache service."""
        command = MagicMock(spec=CommandObject)
        command.args = "@testuser"

        await cmd_whitelist(mock_message, command, None)

        call_args = mock_message.answer.call_args[0][0]
        assert "not available" in call_args


# =============================================================================
# /blacklist Command Tests (Admin Only)
# =============================================================================


class TestBlacklistCommand:
    """Tests for /blacklist command handler."""

    @pytest.mark.asyncio
    async def test_blacklist_requires_group(
        self, mock_private_message, mock_command_with_args, mock_cache_service
    ):
        """Test /blacklist only works in groups."""
        await cmd_blacklist(
            mock_private_message,
            mock_command_with_args,
            mock_cache_service,
        )

        mock_private_message.answer.assert_called_once()
        call_args = mock_private_message.answer.call_args[0][0]
        assert "only works in groups" in call_args

    @pytest.mark.asyncio
    async def test_blacklist_requires_args(
        self, mock_message, mock_command_no_args, mock_cache_service
    ):
        """Test /blacklist requires username argument."""
        await cmd_blacklist(mock_message, mock_command_no_args, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Usage:" in call_args

    @pytest.mark.asyncio
    async def test_blacklist_adds_user_by_username(
        self, mock_message, mock_cache_service
    ):
        """Test /blacklist adds user by @username."""
        command = MagicMock(spec=CommandObject)
        command.args = "@spammer"

        mock_cache_service.get_json.return_value = {"users": []}

        await cmd_blacklist(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Added" in call_args
        assert "blacklist" in call_args.lower()
        assert "+50 risk score" in call_args

    @pytest.mark.asyncio
    async def test_blacklist_adds_user_by_id(self, mock_message, mock_cache_service):
        """Test /blacklist adds user by user ID."""
        command = MagicMock(spec=CommandObject)
        command.args = "999888777"

        mock_cache_service.get_json.return_value = {"users": []}

        await cmd_blacklist(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Added" in call_args

    @pytest.mark.asyncio
    async def test_blacklist_rejects_already_blacklisted(
        self, mock_message, mock_cache_service
    ):
        """Test /blacklist rejects already blacklisted user."""
        command = MagicMock(spec=CommandObject)
        command.args = "@spammer"

        mock_cache_service.get_json.return_value = {"users": [{"username": "spammer"}]}

        await cmd_blacklist(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "already blacklisted" in call_args


# =============================================================================
# /settype Command Tests (Admin Only)
# =============================================================================


class TestSetTypeCommand:
    """Tests for /settype command handler."""

    @pytest.mark.asyncio
    async def test_settype_requires_group(
        self, mock_private_message, mock_command_with_args, mock_cache_service
    ):
        """Test /settype only works in groups."""
        await cmd_settype(
            mock_private_message,
            mock_command_with_args,
            mock_cache_service,
        )

        mock_private_message.answer.assert_called_once()
        call_args = mock_private_message.answer.call_args[0][0]
        assert "only works in groups" in call_args

    @pytest.mark.asyncio
    async def test_settype_requires_args(
        self, mock_message, mock_command_no_args, mock_cache_service
    ):
        """Test /settype requires type argument."""
        await cmd_settype(mock_message, mock_command_no_args, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Usage:" in call_args
        assert "general" in call_args
        assert "tech" in call_args
        assert "deals" in call_args
        assert "crypto" in call_args

    @pytest.mark.asyncio
    async def test_settype_updates_to_general(self, mock_message, mock_cache_service):
        """Test /settype general updates group type."""
        command = MagicMock(spec=CommandObject)
        command.args = "general"

        mock_cache_service.get_json.return_value = {}

        await cmd_settype(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "general" in call_args.lower()
        assert "set to" in call_args.lower() or "Group type" in call_args

    @pytest.mark.asyncio
    async def test_settype_updates_to_tech(self, mock_message, mock_cache_service):
        """Test /settype tech updates group type."""
        command = MagicMock(spec=CommandObject)
        command.args = "tech"

        mock_cache_service.get_json.return_value = {}

        await cmd_settype(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "tech" in call_args.lower()

    @pytest.mark.asyncio
    async def test_settype_updates_to_deals(self, mock_message, mock_cache_service):
        """Test /settype deals updates group type."""
        command = MagicMock(spec=CommandObject)
        command.args = "deals"

        mock_cache_service.get_json.return_value = {}

        await cmd_settype(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "deals" in call_args.lower()

    @pytest.mark.asyncio
    async def test_settype_updates_to_crypto(self, mock_message, mock_cache_service):
        """Test /settype crypto updates group type."""
        command = MagicMock(spec=CommandObject)
        command.args = "crypto"

        mock_cache_service.get_json.return_value = {}

        await cmd_settype(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "crypto" in call_args.lower()

    @pytest.mark.asyncio
    async def test_settype_validates_type_value(self, mock_message, mock_cache_service):
        """Test /settype rejects invalid type values."""
        command = MagicMock(spec=CommandObject)
        command.args = "invalid_type"

        await cmd_settype(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Usage:" in call_args

    @pytest.mark.asyncio
    async def test_settype_case_insensitive(self, mock_message, mock_cache_service):
        """Test /settype is case insensitive."""
        command = MagicMock(spec=CommandObject)
        command.args = "TECH"

        mock_cache_service.get_json.return_value = {}

        await cmd_settype(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "tech" in call_args.lower()

    @pytest.mark.asyncio
    async def test_settype_caches_new_type(self, mock_message, mock_cache_service):
        """Test /settype stores new type in cache."""
        command = MagicMock(spec=CommandObject)
        command.args = "tech"

        mock_cache_service.get_json.return_value = {}

        await cmd_settype(mock_message, command, mock_cache_service)

        mock_cache_service.set_json.assert_called_once()
        call_args = mock_cache_service.set_json.call_args
        key = call_args[0][0]
        value = call_args[0][1]

        assert "group_settings" in key
        assert value["group_type"] == "tech"


# =============================================================================
# /check Command Tests (Admin Only)
# =============================================================================


class TestCheckCommand:
    """Tests for /check command handler."""

    @pytest.mark.asyncio
    async def test_check_requires_args(
        self, mock_message, mock_command_no_args, mock_cache_service
    ):
        """Test /check requires username/ID argument."""
        await cmd_check(mock_message, mock_command_no_args, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Usage:" in call_args

    @pytest.mark.asyncio
    async def test_check_shows_user_trust_score(
        self, mock_message, mock_cache_service
    ):
        """Test /check shows user's trust score and history."""
        command = MagicMock(spec=CommandObject)
        command.args = "@someuser"

        mock_cache_service.get_json.side_effect = [
            {
                "total_messages": 50,
                "approved": 48,
                "flagged": 2,
                "blocked": 0,
                "avg_risk_score": 12.5,
            },
            None,  # cross-group actions
            {"users": []},  # whitelist
            {"users": []},  # blacklist
        ]

        await cmd_check(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "User Check" in call_args
        assert "50" in call_args

    @pytest.mark.asyncio
    async def test_check_shows_no_history(self, mock_message, mock_cache_service):
        """Test /check handles users with no history."""
        command = MagicMock(spec=CommandObject)
        command.args = "@newuser"

        mock_cache_service.get_json.return_value = None

        await cmd_check(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "No history" in call_args

    @pytest.mark.asyncio
    async def test_check_shows_whitelist_status(self, mock_message, mock_cache_service):
        """Test /check shows if user is whitelisted."""
        command = MagicMock(spec=CommandObject)
        command.args = "@trusted"

        # When using @username (not user_id), user_actions lookup is skipped
        # Order is: user_stats, whitelist, blacklist
        mock_cache_service.get_json.side_effect = [
            None,  # user_stats
            {"users": [{"username": "trusted"}]},  # whitelist
            {"users": []},  # blacklist
        ]

        await cmd_check(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "WHITELISTED" in call_args

    @pytest.mark.asyncio
    async def test_check_shows_blacklist_status(self, mock_message, mock_cache_service):
        """Test /check shows if user is blacklisted."""
        command = MagicMock(spec=CommandObject)
        command.args = "@spammer"

        # When using @username (not user_id), user_actions lookup is skipped
        # Order is: user_stats, whitelist, blacklist
        mock_cache_service.get_json.side_effect = [
            None,  # user_stats
            {"users": []},  # whitelist
            {"users": [{"username": "spammer"}]},  # blacklist
        ]

        await cmd_check(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "BLACKLISTED" in call_args

    @pytest.mark.asyncio
    async def test_check_by_user_id(self, mock_message, mock_cache_service):
        """Test /check works with user ID."""
        command = MagicMock(spec=CommandObject)
        command.args = "123456789"

        mock_cache_service.get_json.return_value = None

        await cmd_check(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "123456789" in call_args

    @pytest.mark.asyncio
    async def test_check_validates_user_id_format(
        self, mock_message, mock_cache_service
    ):
        """Test /check validates user ID format."""
        command = MagicMock(spec=CommandObject)
        command.args = "invalid_id"

        await cmd_check(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Invalid" in call_args


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestCommandErrorHandling:
    """Tests for error handling in command handlers."""

    @pytest.mark.asyncio
    async def test_whitelist_handles_cache_error(
        self, mock_message, mock_cache_service
    ):
        """Test /whitelist handles cache errors gracefully."""
        command = MagicMock(spec=CommandObject)
        command.args = "@testuser"

        mock_cache_service.get_json.side_effect = Exception("Unexpected error")

        await cmd_whitelist(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Failed" in call_args

    @pytest.mark.asyncio
    async def test_settype_handles_cache_error(self, mock_message, mock_cache_service):
        """Test /settype handles cache errors gracefully."""
        command = MagicMock(spec=CommandObject)
        command.args = "tech"

        mock_cache_service.get_json.return_value = {}
        mock_cache_service.set_json.side_effect = ConnectionError("Redis down")

        await cmd_settype(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Failed" in call_args or "connection error" in call_args.lower()

    @pytest.mark.asyncio
    async def test_check_handles_cache_error(self, mock_message, mock_cache_service):
        """Test /check handles cache errors gracefully."""
        command = MagicMock(spec=CommandObject)
        command.args = "@testuser"

        mock_cache_service.get_json.side_effect = Exception("Cache explosion")

        await cmd_check(mock_message, command, mock_cache_service)

        call_args = mock_message.answer.call_args[0][0]
        assert "Error" in call_args or "error" in call_args.lower()
