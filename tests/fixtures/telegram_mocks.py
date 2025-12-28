"""
SAQSHY Test Fixtures - Telegram Mocks

Provides mock fixtures for aiogram bot testing:
- Mock Telegram users with realistic attributes
- Mock Telegram chats (groups/supergroups)
- Mock Telegram messages with all required fields
- Mock Bot with all API methods mocked

These fixtures are designed for deterministic unit testing
without requiring a real Telegram connection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Chat, Message, Update, User


# =============================================================================
# User Fixtures
# =============================================================================


@pytest.fixture
def mock_telegram_user() -> User:
    """
    Create a realistic mock Telegram user.

    This represents a typical legitimate user with complete profile.
    """
    from aiogram.types import User

    return User(
        id=123456789,
        is_bot=False,
        first_name="Test",
        last_name="User",
        username="testuser",
        language_code="en",
        is_premium=False,
        added_to_attachment_menu=False,
        can_join_groups=True,
        can_read_all_group_messages=False,
        supports_inline_queries=False,
    )


@pytest.fixture
def mock_spam_user() -> User:
    """
    Create a spam-like mock Telegram user.

    Profile characteristics match common spammer patterns:
    - Random-looking username with numbers
    - Emoji in name (scam cluster pattern)
    - No last name
    """
    from aiogram.types import User

    return User(
        id=987654321,
        is_bot=False,
        first_name="Crypto",
        last_name=None,
        username="user12345678",
        language_code="en",
        is_premium=False,
        added_to_attachment_menu=False,
        can_join_groups=True,
        can_read_all_group_messages=False,
        supports_inline_queries=False,
    )


@pytest.fixture
def mock_premium_user() -> User:
    """
    Create a mock premium Telegram user.

    Premium users are slightly more trusted as bots rarely have premium.
    """
    from aiogram.types import User

    return User(
        id=111222333,
        is_bot=False,
        first_name="Premium",
        last_name="Member",
        username="premiumuser",
        language_code="en",
        is_premium=True,
        added_to_attachment_menu=False,
        can_join_groups=True,
        can_read_all_group_messages=False,
        supports_inline_queries=False,
    )


@pytest.fixture
def mock_bot_user() -> User:
    """
    Create a mock bot user (non-human).

    Used to test bot detection signals.
    """
    from aiogram.types import User

    return User(
        id=8506740275,
        is_bot=True,
        first_name="Test Bot",
        last_name=None,
        username="test_bot",
        language_code=None,
        is_premium=False,
        added_to_attachment_menu=False,
        can_join_groups=True,
        can_read_all_group_messages=True,
        supports_inline_queries=True,
    )


# =============================================================================
# Chat Fixtures
# =============================================================================


@pytest.fixture
def mock_telegram_chat() -> Chat:
    """
    Create a mock Telegram supergroup chat.

    This is the most common group type for anti-spam protection.
    """
    from aiogram.types import Chat

    return Chat(
        id=-1001234567890,
        type="supergroup",
        title="Test Group",
        username="testgroup",
        is_forum=False,
    )


@pytest.fixture
def mock_private_chat(mock_telegram_user: User) -> Chat:
    """
    Create a mock private chat with a user.

    Private chats typically bypass spam checking.
    """
    from aiogram.types import Chat

    return Chat(
        id=mock_telegram_user.id,
        type="private",
        username=mock_telegram_user.username,
        first_name=mock_telegram_user.first_name,
        last_name=mock_telegram_user.last_name,
    )


@pytest.fixture
def mock_channel() -> Chat:
    """
    Create a mock Telegram channel.

    Used for testing channel subscription verification.
    """
    from aiogram.types import Chat

    return Chat(
        id=-1009876543210,
        type="channel",
        title="Test Channel",
        username="testchannel",
    )


# =============================================================================
# Message Fixtures
# =============================================================================


def _create_mock_message(
    message_id: int,
    text: str | None,
    user: User,
    chat: Chat,
    is_forward: bool = False,
    reply_to_message: Message | None = None,
    entities: list | None = None,
) -> Message:
    """
    Internal helper to create a realistic mock Message.

    All required aiogram Message fields are included with sensible defaults.
    """
    from aiogram.types import Message

    return Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=chat,
        from_user=user,
        text=text,
        reply_to_message=reply_to_message,
        forward_date=datetime.now(UTC) if is_forward else None,
        forward_from=user if is_forward else None,
        entities=entities,
        # Media fields (all None for text message)
        photo=None,
        video=None,
        audio=None,
        document=None,
        sticker=None,
        voice=None,
        video_note=None,
        animation=None,
        # Other optional fields with defaults
        edit_date=None,
        author_signature=None,
        caption=None,
        caption_entities=None,
        contact=None,
        location=None,
        venue=None,
        poll=None,
        dice=None,
        new_chat_members=None,
        left_chat_member=None,
        new_chat_title=None,
        new_chat_photo=None,
        delete_chat_photo=None,
        group_chat_created=None,
        supergroup_chat_created=None,
        channel_chat_created=None,
        message_auto_delete_timer_changed=None,
        migrate_to_chat_id=None,
        migrate_from_chat_id=None,
        pinned_message=None,
        invoice=None,
        successful_payment=None,
        connected_website=None,
        passport_data=None,
        reply_markup=None,
    )


@pytest.fixture
def mock_telegram_message(
    mock_telegram_user: User,
    mock_telegram_chat: Chat,
) -> Message:
    """
    Create a realistic mock Telegram message.

    Standard text message from a regular user in a supergroup.
    """
    return _create_mock_message(
        message_id=12345,
        text="Hello, this is a test message!",
        user=mock_telegram_user,
        chat=mock_telegram_chat,
    )


@pytest.fixture
def mock_spam_message(
    mock_spam_user: User,
    mock_telegram_chat: Chat,
) -> Message:
    """
    Create a spam-like mock message.

    Contains crypto scam phrases and urgency patterns.
    """
    return _create_mock_message(
        message_id=12346,
        text="URGENT! Double your Bitcoin NOW! DM me for guaranteed profits!",
        user=mock_spam_user,
        chat=mock_telegram_chat,
        is_forward=True,
    )


@pytest.fixture
def mock_link_message(
    mock_telegram_user: User,
    mock_telegram_chat: Chat,
) -> Message:
    """
    Create a message with URLs.

    Used to test URL analysis and shortener detection.
    """
    from aiogram.types import MessageEntity

    text = "Check out this link: https://example.com/page"
    entities = [
        MessageEntity(
            type="url",
            offset=22,
            length=26,
        )
    ]

    return _create_mock_message(
        message_id=12347,
        text=text,
        user=mock_telegram_user,
        chat=mock_telegram_chat,
        entities=entities,
    )


@pytest.fixture
def mock_reply_message(
    mock_telegram_user: User,
    mock_telegram_chat: Chat,
    mock_telegram_message: Message,
) -> Message:
    """
    Create a reply message.

    Replies are a trust signal (engaged in conversation).
    """
    return _create_mock_message(
        message_id=12348,
        text="Thanks for your message!",
        user=mock_telegram_user,
        chat=mock_telegram_chat,
        reply_to_message=mock_telegram_message,
    )


# =============================================================================
# Bot Fixtures
# =============================================================================


@pytest.fixture
def mock_telegram_bot(mock_telegram_chat: Chat) -> Bot:
    """
    Create a mock Bot with all API methods mocked.

    All async methods are AsyncMock with sensible return values.
    This allows testing handlers without actual Telegram API calls.
    """
    from aiogram import Bot
    from aiogram.types import ChatMember, ChatMemberOwner, User

    bot = MagicMock(spec=Bot)

    # Bot identity
    type(bot).id = PropertyMock(return_value=8506740275)
    bot.username = "saqshy_robot"

    # Mock token (never use real token in tests!)
    bot.token = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"

    # Message operations
    bot.delete_message = AsyncMock(return_value=True)
    bot.send_message = AsyncMock(return_value=MagicMock())
    bot.edit_message_text = AsyncMock(return_value=MagicMock())
    bot.forward_message = AsyncMock(return_value=MagicMock())
    bot.copy_message = AsyncMock(return_value=MagicMock())

    # User operations
    bot.ban_chat_member = AsyncMock(return_value=True)
    bot.unban_chat_member = AsyncMock(return_value=True)
    bot.restrict_chat_member = AsyncMock(return_value=True)
    bot.promote_chat_member = AsyncMock(return_value=True)
    bot.set_chat_administrator_custom_title = AsyncMock(return_value=True)

    # Chat operations
    bot.get_chat = AsyncMock(return_value=mock_telegram_chat)
    bot.get_chat_administrators = AsyncMock(return_value=[])
    bot.get_chat_member_count = AsyncMock(return_value=100)
    bot.leave_chat = AsyncMock(return_value=True)

    # Chat member operations (critical for channel subscription checks)
    def _mock_get_chat_member(chat_id: int, user_id: int) -> ChatMember:
        """Return a mock chat member with 'member' status by default."""
        mock_user = User(
            id=user_id,
            is_bot=False,
            first_name="Member",
        )
        return ChatMemberOwner(
            user=mock_user,
            status="creator",
            is_anonymous=False,
        )

    bot.get_chat_member = AsyncMock(side_effect=_mock_get_chat_member)

    # Webhook operations
    bot.set_webhook = AsyncMock(return_value=True)
    bot.delete_webhook = AsyncMock(return_value=True)
    bot.get_webhook_info = AsyncMock(return_value=MagicMock())

    # Other operations
    bot.get_me = AsyncMock(
        return_value=User(
            id=8506740275,
            is_bot=True,
            first_name="SAQSHY",
            username="saqshy_robot",
        )
    )
    bot.answer_callback_query = AsyncMock(return_value=True)
    bot.answer_inline_query = AsyncMock(return_value=True)

    # Session management
    bot.session = MagicMock()
    bot.session.close = AsyncMock()

    return bot


@pytest.fixture
def mock_telegram_bot_with_admin(
    mock_telegram_bot: Bot,
    mock_telegram_user: User,
) -> Bot:
    """
    Create a mock Bot where the test user is an admin.

    Useful for testing admin command handlers.
    """
    from aiogram.types import ChatMemberAdministrator

    admin_member = ChatMemberAdministrator(
        user=mock_telegram_user,
        status="administrator",
        can_be_edited=False,
        is_anonymous=False,
        can_manage_chat=True,
        can_delete_messages=True,
        can_manage_video_chats=True,
        can_restrict_members=True,
        can_promote_members=False,
        can_change_info=True,
        can_invite_users=True,
        can_post_stories=False,
        can_edit_stories=False,
        can_delete_stories=False,
    )

    mock_telegram_bot.get_chat_administrators = AsyncMock(return_value=[admin_member])
    mock_telegram_bot.get_chat_member = AsyncMock(return_value=admin_member)

    return mock_telegram_bot


# =============================================================================
# Update Fixtures
# =============================================================================


@pytest.fixture
def mock_telegram_update(mock_telegram_message: Message) -> Update:
    """
    Create a mock Telegram Update containing a message.

    Updates are the top-level object received from Telegram webhooks.
    """
    from aiogram.types import Update

    return Update(
        update_id=1,
        message=mock_telegram_message,
    )


@pytest.fixture
def mock_callback_update(
    mock_telegram_user: User,
    mock_telegram_message: Message,
) -> Update:
    """
    Create a mock Update with a callback query.

    Used for testing inline keyboard button handlers.
    """
    from aiogram.types import CallbackQuery, Update

    callback = CallbackQuery(
        id="callback_123",
        from_user=mock_telegram_user,
        chat_instance="chat_instance_456",
        message=mock_telegram_message,
        data="action:approve:12345",
    )

    return Update(
        update_id=2,
        callback_query=callback,
    )


# =============================================================================
# Helper Functions
# =============================================================================


def create_mock_user(
    user_id: int = 123456789,
    first_name: str = "Test",
    last_name: str | None = "User",
    username: str | None = "testuser",
    is_bot: bool = False,
    is_premium: bool = False,
    language_code: str = "en",
) -> User:
    """
    Create a customizable mock Telegram user.

    Args:
        user_id: Telegram user ID
        first_name: User's first name (required by Telegram)
        last_name: User's last name (optional)
        username: User's @username (optional)
        is_bot: Whether this is a bot account
        is_premium: Whether user has Telegram Premium
        language_code: User's language preference

    Returns:
        A configured User object
    """
    from aiogram.types import User

    return User(
        id=user_id,
        is_bot=is_bot,
        first_name=first_name,
        last_name=last_name,
        username=username,
        language_code=language_code,
        is_premium=is_premium,
        added_to_attachment_menu=False,
        can_join_groups=True,
        can_read_all_group_messages=False,
        supports_inline_queries=False,
    )


def create_mock_chat(
    chat_id: int = -1001234567890,
    chat_type: str = "supergroup",
    title: str = "Test Group",
    username: str | None = "testgroup",
) -> Chat:
    """
    Create a customizable mock Telegram chat.

    Args:
        chat_id: Telegram chat ID (negative for groups)
        chat_type: One of "private", "group", "supergroup", "channel"
        title: Chat title (for groups/channels)
        username: Chat @username (optional)

    Returns:
        A configured Chat object
    """
    from aiogram.types import Chat

    return Chat(
        id=chat_id,
        type=chat_type,
        title=title if chat_type != "private" else None,
        username=username,
        is_forum=False,
    )


def create_mock_message(
    text: str,
    user: User | None = None,
    chat: Chat | None = None,
    message_id: int = 1,
    is_forward: bool = False,
    reply_to: Message | None = None,
) -> Message:
    """
    Create a customizable mock Telegram message.

    Args:
        text: Message text content
        user: Sender (defaults to test user)
        chat: Chat where message was sent (defaults to test group)
        message_id: Telegram message ID
        is_forward: Whether this is a forwarded message
        reply_to: Message being replied to (optional)

    Returns:
        A configured Message object
    """
    if user is None:
        user = create_mock_user()
    if chat is None:
        chat = create_mock_chat()

    return _create_mock_message(
        message_id=message_id,
        text=text,
        user=user,
        chat=chat,
        is_forward=is_forward,
        reply_to_message=reply_to,
    )


# =============================================================================
# Export all fixtures and helpers
# =============================================================================

__all__ = [
    # User fixtures
    "mock_telegram_user",
    "mock_spam_user",
    "mock_premium_user",
    "mock_bot_user",
    # Chat fixtures
    "mock_telegram_chat",
    "mock_private_chat",
    "mock_channel",
    # Message fixtures
    "mock_telegram_message",
    "mock_spam_message",
    "mock_link_message",
    "mock_reply_message",
    # Bot fixtures
    "mock_telegram_bot",
    "mock_telegram_bot_with_admin",
    # Update fixtures
    "mock_telegram_update",
    "mock_callback_update",
    # Helper functions
    "create_mock_user",
    "create_mock_chat",
    "create_mock_message",
]
