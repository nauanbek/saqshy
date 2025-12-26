"""
SAQSHY Telegram Utilities

Telegram-specific helper functions.
"""

import re


def format_user_mention(
    user_id: int,
    name: str | None = None,
    link: bool = True,
) -> str:
    """
    Format a user mention for Telegram HTML.

    Args:
        user_id: Telegram user ID.
        name: Display name (defaults to user_id).
        link: Whether to create a clickable link.

    Returns:
        HTML-formatted user mention.
    """
    display = name or str(user_id)

    if link:
        return f'<a href="tg://user?id={user_id}">{escape_html(display)}</a>'
    else:
        return escape_html(display)


def escape_html(text: str) -> str:
    """
    Escape HTML special characters.

    Args:
        text: Text to escape.

    Returns:
        HTML-escaped text.
    """
    if not text:
        return ""

    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def parse_command_args(text: str) -> tuple[str, list[str]]:
    """
    Parse command and arguments from message text.

    Args:
        text: Message text starting with /command.

    Returns:
        Tuple of (command, args).
    """
    if not text or not text.startswith("/"):
        return "", []

    parts = text.split()
    command = parts[0].lstrip("/")

    # Remove @botname if present
    if "@" in command:
        command = command.split("@")[0]

    args = parts[1:] if len(parts) > 1 else []

    return command, args


def parse_user_mention(text: str) -> int | None:
    """
    Parse user ID from @username or user link.

    Args:
        text: Text containing mention.

    Returns:
        User ID or None.
    """
    # Try to extract from tg://user link
    match = re.search(r"tg://user\?id=(\d+)", text)
    if match:
        return int(match.group(1))

    # Try to extract numeric ID
    match = re.search(r"\b(\d{5,15})\b", text)
    if match:
        return int(match.group(1))

    return None


def format_duration(seconds: int) -> str:
    """
    Format duration in human-readable format.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like "1h 30m" or "2d 5h".
    """
    if seconds < 60:
        return f"{seconds}s"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    if hours < 24:
        remaining_minutes = minutes % 60
        if remaining_minutes:
            return f"{hours}h {remaining_minutes}m"
        return f"{hours}h"

    days = hours // 24
    remaining_hours = hours % 24
    if remaining_hours:
        return f"{days}d {remaining_hours}h"
    return f"{days}d"


def format_number(n: int) -> str:
    """
    Format number with K/M suffix for large numbers.

    Args:
        n: Number to format.

    Returns:
        Formatted string like "1.5K" or "2.3M".
    """
    if n < 1000:
        return str(n)
    elif n < 1_000_000:
        return f"{n / 1000:.1f}K".rstrip("0").rstrip(".")
    else:
        return f"{n / 1_000_000:.1f}M".rstrip("0").rstrip(".")


def get_chat_link(chat_id: int, username: str | None = None) -> str:
    """
    Get a link to a Telegram chat.

    Args:
        chat_id: Telegram chat ID.
        username: Optional chat username.

    Returns:
        Link to the chat.
    """
    if username:
        return f"https://t.me/{username}"

    # For private chats, use deep link
    return f"tg://openmessage?chat_id={abs(chat_id)}"


def is_group_chat(chat_type: str) -> bool:
    """
    Check if chat type is a group.

    Args:
        chat_type: Telegram chat type string.

    Returns:
        True if group or supergroup.
    """
    return chat_type in ("group", "supergroup")


def get_message_link(
    chat_id: int,
    message_id: int,
    username: str | None = None,
) -> str:
    """
    Get a link to a specific message.

    Args:
        chat_id: Telegram chat ID.
        message_id: Message ID.
        username: Optional chat username.

    Returns:
        Link to the message.
    """
    if username:
        return f"https://t.me/{username}/{message_id}"

    # For private supergroups
    # Convert chat_id to supergroup format
    chat_id_str = str(abs(chat_id))
    if chat_id_str.startswith("100"):
        chat_id_str = chat_id_str[3:]

    return f"https://t.me/c/{chat_id_str}/{message_id}"
