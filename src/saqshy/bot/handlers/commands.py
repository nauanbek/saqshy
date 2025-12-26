"""
SAQSHY Command Handlers

Handles bot commands including:
- /start - Welcome message with Mini App link
- /help - List available commands
- /settings - Admin-only, link to Mini App settings
- /stats - Admin-only, show group spam statistics
- /whitelist - Admin-only, add user to whitelist
- /blacklist - Admin-only, add user to blacklist
- /status - Show bot status and protection status

All admin commands check user permissions via the AdminFilter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from saqshy.bot.filters.admin import AdminFilter

if TYPE_CHECKING:
    from saqshy.services.cache import CacheService

logger = structlog.get_logger(__name__)

router = Router(name="commands")


# =============================================================================
# /start Command
# =============================================================================


@router.message(Command("start"))
async def cmd_start(
    message: Message,
    command: CommandObject,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle /start command.

    Shows welcome message with Mini App button and usage instructions.
    If deep link parameter is provided, handles specific actions.
    """
    # Check if this is a deep link with parameters
    args = command.args
    if args:
        await _handle_start_deeplink(message, args, cache_service)
        return

    # Check if in group or private chat
    if message.chat.type in ("group", "supergroup"):
        await _handle_start_group(message, cache_service)
    else:
        await _handle_start_private(message, cache_service)


async def _handle_start_private(
    message: Message,
    cache_service: CacheService | None,
) -> None:
    """Handle /start in private chat."""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Add to Group",
                    url="https://t.me/saqshy_bot?startgroup=true",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Open Settings",
                    web_app=WebAppInfo(url="https://app.saqshy.bot"),  # Mini App URL
                ),
            ],
            [
                InlineKeyboardButton(
                    text="View Documentation",
                    url="https://docs.saqshy.bot",
                ),
            ],
        ]
    )

    await message.answer(
        "<b>Welcome to SAQSHY Anti-Spam Bot</b>\n\n"
        "AI-powered protection for your Telegram groups.\n\n"
        "<b>Features:</b>\n"
        "- Cumulative risk scoring (multiple signals combined)\n"
        "- Spam pattern detection with ML embeddings\n"
        "- Channel subscription trust bonuses\n"
        "- New user sandbox mode\n"
        "- Cross-group spam detection\n\n"
        "<b>Philosophy:</b>\n"
        "No single signal blocks a user. Better to let 2-3% spam through "
        "than block a legitimate user.\n\n"
        "Add me to your group to get started!",
        reply_markup=keyboard,
    )


async def _handle_start_group(
    message: Message,
    cache_service: CacheService | None,
) -> None:
    """Handle /start in group chat."""
    await message.answer(
        "<b>SAQSHY Anti-Spam Bot Active</b>\n\n"
        "This group is now protected.\n\n"
        "Use /help to see available commands.\n"
        "Use /settings to configure protection settings.\n"
        "Use /stats to view spam statistics.",
    )


async def _handle_start_deeplink(
    message: Message,
    args: str,
    cache_service: CacheService | None,
) -> None:
    """Handle /start with deep link parameters."""
    # Parse deep link parameters
    # e.g., /start group_123 - for specific group setup

    if args.startswith("group_"):
        # User was redirected from a group
        try:
            group_id = int(args.replace("group_", ""))
            await message.answer(
                f"Configure settings for group {group_id} in the Mini App.",
            )
        except ValueError:
            await _handle_start_private(message, cache_service)
    else:
        await _handle_start_private(message, cache_service)


# =============================================================================
# /help Command
# =============================================================================


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """
    Handle /help command.

    Shows list of available commands based on user permissions.
    """
    # General commands available to all users
    help_text = (
        "<b>SAQSHY Bot Commands</b>\n\n"
        "<b>General Commands:</b>\n"
        "/start - Start the bot and show welcome message\n"
        "/help - Show this help message\n"
        "/status - Show bot protection status\n\n"
    )

    # Check if user is admin for admin commands
    is_group = message.chat.type in ("group", "supergroup")

    if is_group:
        help_text += (
            "<b>Admin Commands:</b>\n"
            "/settings - Open settings Mini App\n"
            "/stats - View spam detection statistics\n"
            "/whitelist @username - Add user to trusted list\n"
            "/blacklist @username - Add user to blacklist\n"
            "/unwhitelist @username - Remove from trusted list\n"
            "/unblacklist @username - Remove from blacklist\n"
            "/check @username - Check user's trust score\n\n"
            "<b>Configuration:</b>\n"
            "/settype [general|tech|deals|crypto] - Set group type\n"
            "/setchannel @channel - Link channel for subscription trust\n"
            "/sensitivity [1-10] - Set detection sensitivity\n"
        )

    await message.answer(help_text)


# =============================================================================
# /status Command
# =============================================================================


@router.message(Command("status"))
async def cmd_status(
    message: Message,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle /status command.

    Shows current protection status for the group.
    """
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("This command only works in groups.")
        return

    chat_id = message.chat.id
    status_text = f"<b>Protection Status for {message.chat.title}</b>\n\n"

    try:
        if cache_service:
            # Get group settings
            settings = await cache_service.get_json(f"group_settings:{chat_id}")

            if settings:
                group_type = settings.get("group_type", "general")
                sensitivity = settings.get("sensitivity", 5)
                sandbox_enabled = settings.get("sandbox_enabled", True)
                linked_channel = settings.get("linked_channel_id")

                status_text += (
                    f"<b>Group Type:</b> {group_type}\n"
                    f"<b>Sensitivity:</b> {sensitivity}/10\n"
                    f"<b>Sandbox Mode:</b> {'Enabled' if sandbox_enabled else 'Disabled'}\n"
                )

                if linked_channel:
                    status_text += f"<b>Linked Channel:</b> {linked_channel}\n"
                else:
                    status_text += "<b>Linked Channel:</b> Not set\n"
            else:
                status_text += (
                    "<b>Group Type:</b> general (default)\n"
                    "<b>Sensitivity:</b> 5/10 (default)\n"
                    "<b>Sandbox Mode:</b> Enabled\n"
                    "<b>Linked Channel:</b> Not set\n"
                )

            # Get recent stats
            stats_key = f"saqshy:stats:{chat_id}"
            stats = await cache_service.get_json(stats_key)

            if stats:
                status_text += (
                    f"\n<b>Last 24h:</b>\n"
                    f"- Messages scanned: {stats.get('messages_scanned', 0)}\n"
                    f"- Spam blocked: {stats.get('spam_blocked', 0)}\n"
                    f"- Sent to review: {stats.get('sent_to_review', 0)}\n"
                )

        status_text += "\nProtection is active and running."

    except ConnectionError as e:
        logger.warning("status_command_connection_error", error=str(e))
        status_text += "\nUnable to fetch detailed status (connection error)."
    except (ValueError, TypeError) as e:
        logger.warning("status_command_data_error", error=str(e))
        status_text += "\nUnable to fetch detailed status (data error)."
    except Exception as e:
        logger.error(
            "status_command_unexpected_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        status_text += "\nUnable to fetch detailed status."

    await message.answer(status_text)


# =============================================================================
# /settings Command (Admin Only)
# =============================================================================


@router.message(Command("settings"), AdminFilter())
async def cmd_settings(
    message: Message,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle /settings command (admin only).

    Shows settings summary and link to Mini App for full configuration.
    """
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("This command only works in groups.")
        return

    chat_id = message.chat.id

    # Build settings keyboard
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Open Full Settings",
                    web_app=WebAppInfo(url=f"https://app.saqshy.bot/group/{chat_id}"),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Quick: General",
                    callback_data=f"settype:general:{chat_id}",
                ),
                InlineKeyboardButton(
                    text="Quick: Tech",
                    callback_data=f"settype:tech:{chat_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Quick: Deals",
                    callback_data=f"settype:deals:{chat_id}",
                ),
                InlineKeyboardButton(
                    text="Quick: Crypto",
                    callback_data=f"settype:crypto:{chat_id}",
                ),
            ],
        ]
    )

    settings_text = "<b>Group Settings</b>\n\n"

    if cache_service:
        settings = await cache_service.get_json(f"group_settings:{chat_id}")
        if settings:
            settings_text += (
                f"<b>Current Configuration:</b>\n"
                f"- Type: {settings.get('group_type', 'general')}\n"
                f"- Sensitivity: {settings.get('sensitivity', 5)}/10\n"
                f"- Sandbox: {'On' if settings.get('sandbox_enabled', True) else 'Off'}\n\n"
            )
        else:
            settings_text += "<b>Using default settings</b>\n\n"

    settings_text += "Use the Mini App for full configuration, or quick-select a group type below:"

    await message.answer(settings_text, reply_markup=keyboard)


# =============================================================================
# /stats Command (Admin Only)
# =============================================================================


@router.message(Command("stats"), AdminFilter())
async def cmd_stats(
    message: Message,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle /stats command (admin only).

    Shows spam detection statistics for the group.
    """
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("This command only works in groups.")
        return

    chat_id = message.chat.id
    stats_text = f"<b>Spam Statistics for {message.chat.title}</b>\n\n"

    try:
        if cache_service:
            # Get stats from cache
            stats_key = f"saqshy:stats:{chat_id}"
            stats = await cache_service.get_json(stats_key)

            if stats:
                stats_text += (
                    "<b>Last 24 Hours:</b>\n"
                    f"- Total messages: {stats.get('total_messages', 0)}\n"
                    f"- Messages scanned: {stats.get('messages_scanned', 0)}\n"
                    f"- Allowed: {stats.get('allowed', 0)}\n"
                    f"- Watching: {stats.get('watching', 0)}\n"
                    f"- Limited: {stats.get('limited', 0)}\n"
                    f"- Sent to review: {stats.get('review', 0)}\n"
                    f"- Blocked: {stats.get('blocked', 0)}\n\n"
                )

                # Calculate detection rate
                total_scanned = stats.get("messages_scanned", 0)
                blocked = stats.get("blocked", 0) + stats.get("review", 0)

                if total_scanned > 0:
                    detection_rate = (blocked / total_scanned) * 100
                    stats_text += f"<b>Detection rate:</b> {detection_rate:.1f}%\n"

                # Average risk score
                avg_score = stats.get("avg_risk_score", 0)
                if avg_score > 0:
                    stats_text += f"<b>Average risk score:</b> {avg_score:.1f}\n"

            else:
                stats_text += "No statistics available yet.\n"

            # Get recent actions
            recent_key = f"saqshy:recent_actions:{chat_id}"
            recent_actions = await cache_service.get_json(recent_key)

            if recent_actions and len(recent_actions) > 0:
                stats_text += "\n<b>Recent Actions:</b>\n"
                for action in recent_actions[-5:]:  # Last 5 actions
                    action_type = action.get("action", "unknown")
                    user_id = action.get("user_id", "unknown")
                    stats_text += f"- {action_type}: User {user_id}\n"

        else:
            stats_text += "Statistics service not available."

    except ConnectionError as e:
        logger.warning("stats_command_connection_error", error=str(e))
        stats_text += "Error fetching statistics (connection error)."
    except (ValueError, TypeError) as e:
        logger.warning("stats_command_data_error", error=str(e))
        stats_text += "Error fetching statistics (data error)."
    except Exception as e:
        logger.error(
            "stats_command_unexpected_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        stats_text += "Error fetching statistics."

    await message.answer(stats_text)


# =============================================================================
# /whitelist Command (Admin Only)
# =============================================================================


@router.message(Command("whitelist"), AdminFilter())
async def cmd_whitelist(
    message: Message,
    command: CommandObject,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle /whitelist command (admin only).

    Adds a user to the trusted whitelist for this group.
    Usage: /whitelist @username or /whitelist user_id
    """
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("This command only works in groups.")
        return

    if not command.args:
        await message.answer(
            "Usage: /whitelist @username or /whitelist user_id\n"
            "Whitelisted users bypass spam detection."
        )
        return

    chat_id = message.chat.id
    target = command.args.strip()

    # Parse target (username or user_id)
    user_id = None
    username = None

    if target.startswith("@"):
        username = target[1:]
    else:
        try:
            user_id = int(target)
        except ValueError:
            await message.answer("Invalid user ID or username format.")
            return

    try:
        if cache_service:
            # Get current whitelist
            whitelist_key = f"saqshy:whitelist:{chat_id}"
            whitelist = await cache_service.get_json(whitelist_key) or {"users": []}

            # Add user to whitelist
            entry = {
                "user_id": user_id,
                "username": username,
                "added_by": message.from_user.id if message.from_user else None,
                "added_at": datetime.now(UTC).isoformat(),
            }

            # Check if already whitelisted
            existing = next(
                (
                    u
                    for u in whitelist["users"]
                    if (user_id and u.get("user_id") == user_id)
                    or (username and u.get("username") == username)
                ),
                None,
            )

            if existing:
                await message.answer(f"User {target} is already whitelisted.")
                return

            whitelist["users"].append(entry)
            await cache_service.set_json(whitelist_key, whitelist, ttl=86400 * 365)

            await message.answer(
                f"Added {target} to whitelist.\nThis user will bypass spam detection."
            )

            logger.info(
                "user_whitelisted",
                chat_id=chat_id,
                target=target,
                by_user=message.from_user.id if message.from_user else None,
            )

        else:
            await message.answer("Whitelist service not available.")

    except ConnectionError as e:
        logger.warning(
            "whitelist_command_connection_error",
            chat_id=chat_id,
            target=target,
            error=str(e),
        )
        await message.answer("Failed to add user to whitelist (connection error).")
    except (ValueError, TypeError) as e:
        logger.warning(
            "whitelist_command_data_error",
            chat_id=chat_id,
            target=target,
            error=str(e),
        )
        await message.answer("Failed to add user to whitelist (data error).")
    except Exception as e:
        logger.error(
            "whitelist_command_unexpected_error",
            chat_id=chat_id,
            target=target,
            error=str(e),
            error_type=type(e).__name__,
        )
        await message.answer("Failed to add user to whitelist.")


# =============================================================================
# /blacklist Command (Admin Only)
# =============================================================================


@router.message(Command("blacklist"), AdminFilter())
async def cmd_blacklist(
    message: Message,
    command: CommandObject,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle /blacklist command (admin only).

    Adds a user to the blacklist for this group.
    Usage: /blacklist @username or /blacklist user_id
    """
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("This command only works in groups.")
        return

    if not command.args:
        await message.answer(
            "Usage: /blacklist @username or /blacklist user_id\n"
            "Blacklisted users get +50 risk score on all messages."
        )
        return

    chat_id = message.chat.id
    target = command.args.strip()

    # Parse target (username or user_id)
    user_id = None
    username = None

    if target.startswith("@"):
        username = target[1:]
    else:
        try:
            user_id = int(target)
        except ValueError:
            await message.answer("Invalid user ID or username format.")
            return

    try:
        if cache_service:
            # Get current blacklist
            blacklist_key = f"saqshy:blacklist:{chat_id}"
            blacklist = await cache_service.get_json(blacklist_key) or {"users": []}

            # Add user to blacklist
            entry = {
                "user_id": user_id,
                "username": username,
                "added_by": message.from_user.id if message.from_user else None,
                "added_at": datetime.now(UTC).isoformat(),
                "reason": None,
            }

            # Check if already blacklisted
            existing = next(
                (
                    u
                    for u in blacklist["users"]
                    if (user_id and u.get("user_id") == user_id)
                    or (username and u.get("username") == username)
                ),
                None,
            )

            if existing:
                await message.answer(f"User {target} is already blacklisted.")
                return

            blacklist["users"].append(entry)
            await cache_service.set_json(blacklist_key, blacklist, ttl=86400 * 365)

            await message.answer(
                f"Added {target} to blacklist.\n"
                "This user will receive +50 risk score on all messages."
            )

            logger.info(
                "user_blacklisted",
                chat_id=chat_id,
                target=target,
                by_user=message.from_user.id if message.from_user else None,
            )

        else:
            await message.answer("Blacklist service not available.")

    except ConnectionError as e:
        logger.warning(
            "blacklist_command_connection_error",
            chat_id=chat_id,
            target=target,
            error=str(e),
        )
        await message.answer("Failed to add user to blacklist (connection error).")
    except (ValueError, TypeError) as e:
        logger.warning(
            "blacklist_command_data_error",
            chat_id=chat_id,
            target=target,
            error=str(e),
        )
        await message.answer("Failed to add user to blacklist (data error).")
    except Exception as e:
        logger.error(
            "blacklist_command_unexpected_error",
            chat_id=chat_id,
            target=target,
            error=str(e),
            error_type=type(e).__name__,
        )
        await message.answer("Failed to add user to blacklist.")


# =============================================================================
# /settype Command (Admin Only)
# =============================================================================


@router.message(Command("settype"), AdminFilter())
async def cmd_settype(
    message: Message,
    command: CommandObject,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle /settype command (admin only).

    Sets the group type for threshold calibration.
    Usage: /settype [general|tech|deals|crypto]
    """
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("This command only works in groups.")
        return

    valid_types = ["general", "tech", "deals", "crypto"]

    if not command.args or command.args.lower() not in valid_types:
        await message.answer(
            "Usage: /settype [general|tech|deals|crypto]\n\n"
            "<b>Group Types:</b>\n"
            "- <b>general</b>: Standard community groups\n"
            "- <b>tech</b>: Developer groups (GitHub links normal)\n"
            "- <b>deals</b>: Shopping groups (promo links normal)\n"
            "- <b>crypto</b>: Crypto groups (strict scam detection)"
        )
        return

    chat_id = message.chat.id
    group_type = command.args.lower()

    try:
        if cache_service:
            # Update group settings
            settings_key = f"group_settings:{chat_id}"
            settings = await cache_service.get_json(settings_key) or {}

            settings["group_type"] = group_type
            settings["updated_at"] = datetime.now(UTC).isoformat()
            settings["updated_by"] = message.from_user.id if message.from_user else None

            await cache_service.set_json(settings_key, settings, ttl=86400 * 365)

            await message.answer(
                f"Group type set to <b>{group_type}</b>.\n"
                "Risk thresholds have been adjusted accordingly."
            )

            logger.info(
                "group_type_changed",
                chat_id=chat_id,
                group_type=group_type,
                by_user=message.from_user.id if message.from_user else None,
            )

        else:
            await message.answer("Settings service not available.")

    except ConnectionError as e:
        logger.warning(
            "settype_command_connection_error",
            chat_id=chat_id,
            group_type=group_type,
            error=str(e),
        )
        await message.answer("Failed to update group type (connection error).")
    except (ValueError, TypeError) as e:
        logger.warning(
            "settype_command_data_error",
            chat_id=chat_id,
            group_type=group_type,
            error=str(e),
        )
        await message.answer("Failed to update group type (data error).")
    except Exception as e:
        logger.error(
            "settype_command_unexpected_error",
            chat_id=chat_id,
            group_type=group_type,
            error=str(e),
            error_type=type(e).__name__,
        )
        await message.answer("Failed to update group type.")


# =============================================================================
# /check Command (Admin Only)
# =============================================================================


@router.message(Command("check"), AdminFilter())
async def cmd_check(
    message: Message,
    command: CommandObject,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle /check command (admin only).

    Checks a user's trust score and history.
    Usage: /check @username or /check user_id
    """
    if not command.args:
        await message.answer(
            "Usage: /check @username or /check user_id\nShows user's trust score and history."
        )
        return

    target = command.args.strip()

    # Parse target
    user_id = None
    username = None

    if target.startswith("@"):
        username = target[1:]
    else:
        try:
            user_id = int(target)
        except ValueError:
            await message.answer("Invalid user ID or username format.")
            return

    check_text = f"<b>User Check: {target}</b>\n\n"

    try:
        if cache_service:
            # Get user stats
            user_key = f"saqshy:user_stats:{user_id or username}"
            user_stats = await cache_service.get_json(user_key)

            if user_stats:
                check_text += (
                    f"<b>Message History:</b>\n"
                    f"- Total messages: {user_stats.get('total_messages', 0)}\n"
                    f"- Approved: {user_stats.get('approved', 0)}\n"
                    f"- Flagged: {user_stats.get('flagged', 0)}\n"
                    f"- Blocked: {user_stats.get('blocked', 0)}\n\n"
                )

                avg_score = user_stats.get("avg_risk_score", 0)
                check_text += f"<b>Average Risk Score:</b> {avg_score:.1f}\n"
            else:
                check_text += "No history for this user.\n"

            # Check cross-group stats
            if user_id:
                action_key = f"saqshy:user_actions:{user_id}"
                actions = await cache_service.get_json(action_key)

                if actions:
                    check_text += (
                        f"\n<b>Cross-Group History:</b>\n"
                        f"- Kicked: {actions.get('kicked_count', 0)} times\n"
                        f"- Banned: {actions.get('banned_count', 0)} times\n"
                        f"- Groups with actions: {len(actions.get('groups', []))}\n"
                    )

            # Check whitelist/blacklist status
            chat_id = message.chat.id
            whitelist_key = f"saqshy:whitelist:{chat_id}"
            whitelist = await cache_service.get_json(whitelist_key) or {"users": []}

            is_whitelisted = any(
                (user_id and u.get("user_id") == user_id)
                or (username and u.get("username") == username)
                for u in whitelist.get("users", [])
            )

            blacklist_key = f"saqshy:blacklist:{chat_id}"
            blacklist = await cache_service.get_json(blacklist_key) or {"users": []}

            is_blacklisted = any(
                (user_id and u.get("user_id") == user_id)
                or (username and u.get("username") == username)
                for u in blacklist.get("users", [])
            )

            check_text += "\n<b>Status:</b> "
            if is_whitelisted:
                check_text += "WHITELISTED (trusted)"
            elif is_blacklisted:
                check_text += "BLACKLISTED (+50 risk)"
            else:
                check_text += "Normal"

        else:
            check_text += "Check service not available."

    except ConnectionError as e:
        logger.warning(
            "check_command_connection_error",
            target=target,
            error=str(e),
        )
        check_text += "Error checking user (connection error)."
    except (ValueError, TypeError) as e:
        logger.warning(
            "check_command_data_error",
            target=target,
            error=str(e),
        )
        check_text += "Error checking user (data error)."
    except Exception as e:
        logger.error(
            "check_command_unexpected_error",
            target=target,
            error=str(e),
            error_type=type(e).__name__,
        )
        check_text += "Error checking user."

    await message.answer(check_text)
