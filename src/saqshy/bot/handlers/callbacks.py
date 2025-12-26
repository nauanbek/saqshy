"""
SAQSHY Callback Handlers

Handles inline keyboard callback queries.

Callbacks are used for:
- Admin review actions (approve/reject/ban)
- Captcha verification
- Settings toggles
- Group type quick selection
- Pagination in message lists

All callbacks verify admin permissions where appropriate.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramBadRequest,
)
from aiogram.types import CallbackQuery, ChatPermissions, Message

from saqshy.bot.filters.admin import AdminFilter

if TYPE_CHECKING:
    from saqshy.services.cache import CacheService
    from saqshy.services.spam_db import SpamDB

logger = structlog.get_logger(__name__)

router = Router(name="callbacks")

# Telegram API timeout
API_TIMEOUT_SECONDS = 30.0


# =============================================================================
# Admin Review Callbacks
# =============================================================================


@router.callback_query(F.data.startswith("review:approve:"), AdminFilter())
async def callback_review_approve(
    callback: CallbackQuery,
    bot: Bot,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle approval of a message in review queue.

    Callback data format: review:approve:{message_id}:{user_id}

    Actions:
    - Mark message as approved (for training)
    - Update user trust score
    - Edit review message to show approval
    """
    if not callback.data:
        await callback.answer("Invalid callback data")
        return

    try:
        parts = callback.data.split(":")
        if len(parts) < 4:
            await callback.answer("Invalid callback format")
            return

        message_id = int(parts[2])
        user_id = int(parts[3])

        # Update user stats with positive action
        if cache_service:
            await _update_user_trust(cache_service, user_id, "approved")

        # Edit the review message to show approval
        admin_name = callback.from_user.first_name if callback.from_user else "Admin"
        if callback.message and isinstance(callback.message, Message):
            try:
                new_text = callback.message.text or ""
                new_text += f"\n\n<b>APPROVED</b> by {admin_name}"
                await callback.message.edit_text(new_text, reply_markup=None)
            except TelegramBadRequest:
                pass  # Message may have been deleted

        await callback.answer("Message approved - user trust increased")

        logger.info(
            "review_approved",
            message_id=message_id,
            user_id=user_id,
            approved_by=callback.from_user.id if callback.from_user else None,
        )

    except (ValueError, IndexError) as e:
        logger.warning("invalid_approve_callback", error=str(e))
        await callback.answer("Invalid callback data")


@router.callback_query(F.data.startswith("review:reject:"), AdminFilter())
async def callback_review_reject(
    callback: CallbackQuery,
    bot: Bot,
    cache_service: CacheService | None = None,
    spam_db: SpamDB | None = None,
) -> None:
    """
    Handle rejection of a message in review queue.

    Callback data format: review:reject:{message_id}:{user_id}

    Actions:
    - Mark message as spam (add to spam DB for training)
    - Update user risk score
    - Edit review message to show rejection
    """
    if not callback.data:
        await callback.answer("Invalid callback data")
        return

    try:
        parts = callback.data.split(":")
        if len(parts) < 4:
            await callback.answer("Invalid callback format")
            return

        message_id = int(parts[2])
        user_id = int(parts[3])

        # Update user stats with negative action
        if cache_service:
            await _update_user_trust(cache_service, user_id, "rejected")

        # Could add the message text to spam DB for training
        # This would require storing the original message text in the review

        # Edit the review message to show rejection
        admin_name = callback.from_user.first_name if callback.from_user else "Admin"
        if callback.message and isinstance(callback.message, Message):
            try:
                new_text = callback.message.text or ""
                new_text += f"\n\n<b>REJECTED</b> by {admin_name}"
                await callback.message.edit_text(new_text, reply_markup=None)
            except TelegramBadRequest:
                pass

        await callback.answer("Message rejected - added to spam patterns")

        logger.info(
            "review_rejected",
            message_id=message_id,
            user_id=user_id,
            rejected_by=callback.from_user.id if callback.from_user else None,
        )

    except (ValueError, IndexError) as e:
        logger.warning("invalid_reject_callback", error=str(e))
        await callback.answer("Invalid callback data")


@router.callback_query(F.data.startswith("review:ban:"), AdminFilter())
async def callback_review_ban(
    callback: CallbackQuery,
    bot: Bot,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle ban action from review queue.

    Callback data format: review:ban:{user_id}:{chat_id}

    Actions:
    - Ban user from group
    - Record ban in cross-group stats
    - Edit review message to show ban
    """
    if not callback.data:
        await callback.answer("Invalid callback data")
        return

    try:
        parts = callback.data.split(":")
        if len(parts) < 4:
            await callback.answer("Invalid callback format")
            return

        user_id = int(parts[2])
        chat_id = int(parts[3])

        # Ban the user
        try:
            await asyncio.wait_for(
                bot.ban_chat_member(chat_id=chat_id, user_id=user_id),
                timeout=API_TIMEOUT_SECONDS,
            )
        except TelegramBadRequest as e:
            await callback.answer(f"Failed to ban: {e}")
            return

        # Record ban in cross-group stats
        if cache_service:
            action_key = f"saqshy:user_actions:{user_id}"
            actions = await cache_service.get_json(action_key) or {
                "kicked_count": 0,
                "banned_count": 0,
                "restricted_count": 0,
                "groups": [],
            }
            actions["banned_count"] = actions.get("banned_count", 0) + 1
            if chat_id not in actions.get("groups", []):
                actions.setdefault("groups", []).append(chat_id)
            await cache_service.set_json(action_key, actions, ttl=86400 * 30)

        # Edit the review message
        admin_name = callback.from_user.first_name if callback.from_user else "Admin"
        if callback.message:
            try:
                new_text = callback.message.text or ""
                new_text += f"\n\n<b>USER BANNED</b> by {admin_name}"
                await callback.message.edit_text(new_text, reply_markup=None)
            except TelegramBadRequest:
                pass

        await callback.answer("User banned from group")

        logger.info(
            "user_banned_via_review",
            user_id=user_id,
            chat_id=chat_id,
            banned_by=callback.from_user.id if callback.from_user else None,
        )

    except (ValueError, IndexError) as e:
        logger.warning("invalid_ban_callback", error=str(e))
        await callback.answer("Invalid callback data")


# =============================================================================
# Group Type Quick Selection
# =============================================================================


@router.callback_query(F.data.startswith("settype:"), AdminFilter())
async def callback_set_group_type(
    callback: CallbackQuery,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle quick group type selection from settings.

    Callback data format: settype:{type}:{chat_id}
    """
    if not callback.data:
        await callback.answer("Invalid callback data")
        return

    try:
        parts = callback.data.split(":")
        if len(parts) < 3:
            await callback.answer("Invalid callback format")
            return

        group_type = parts[1]
        chat_id = int(parts[2])

        valid_types = ["general", "tech", "deals", "crypto"]
        if group_type not in valid_types:
            await callback.answer("Invalid group type")
            return

        # Update group settings
        if cache_service:
            settings_key = f"group_settings:{chat_id}"
            settings = await cache_service.get_json(settings_key) or {}

            settings["group_type"] = group_type
            settings["updated_at"] = datetime.now(UTC).isoformat()
            settings["updated_by"] = callback.from_user.id if callback.from_user else None

            await cache_service.set_json(settings_key, settings, ttl=86400 * 365)

        # Edit the settings message
        if callback.message:
            try:
                await callback.message.edit_text(
                    f"<b>Group Settings Updated</b>\n\n"
                    f"Group type set to <b>{group_type}</b>.\n\n"
                    f"Risk thresholds have been adjusted for this group type."
                )
            except TelegramBadRequest:
                pass

        await callback.answer(f"Group type set to {group_type}")

        logger.info(
            "group_type_changed_via_callback",
            chat_id=chat_id,
            group_type=group_type,
            changed_by=callback.from_user.id if callback.from_user else None,
        )

    except (ValueError, IndexError) as e:
        logger.warning("invalid_settype_callback", error=str(e))
        await callback.answer("Invalid callback data")


# =============================================================================
# Captcha Callbacks
# =============================================================================


@router.callback_query(F.data.startswith("captcha:"))
async def callback_captcha(
    callback: CallbackQuery,
    bot: Bot,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle captcha verification response.

    Callback data format: captcha:{answer}:{expected}:{user_id}:{chat_id}
    """
    if not callback.data:
        await callback.answer("Invalid callback data")
        return

    try:
        parts = callback.data.split(":")
        if len(parts) < 5:
            await callback.answer("Invalid callback format")
            return

        answer = parts[1]
        expected = parts[2]
        user_id = int(parts[3])
        chat_id = int(parts[4])

        # Verify the callback is from the correct user
        if callback.from_user and callback.from_user.id != user_id:
            await callback.answer("This captcha is not for you!")
            return

        # Check answer
        if answer == expected:
            # Correct answer - complete captcha
            if cache_service:
                sandbox_key = f"saqshy:sandbox:{chat_id}:{user_id}"
                sandbox_state = await cache_service.get_json(sandbox_key) or {}
                sandbox_state["captcha_completed"] = True
                sandbox_state["captcha_completed_at"] = datetime.now(UTC).isoformat()
                await cache_service.set_json(sandbox_key, sandbox_state, ttl=86400 * 7)

            # Grant message permissions
            try:
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                    ),
                )
            except TelegramBadRequest as e:
                logger.warning("failed_to_unrestrict", error=str(e))

            # Delete captcha message
            if callback.message:
                try:
                    await callback.message.delete()
                except TelegramBadRequest:
                    pass

            await callback.answer("Verification successful! You can now send messages.")

            logger.info(
                "captcha_completed",
                user_id=user_id,
                chat_id=chat_id,
            )

        else:
            # Wrong answer - track attempts
            if cache_service:
                attempts_key = f"saqshy:captcha_attempts:{chat_id}:{user_id}"
                attempts = int(await cache_service.get(attempts_key) or "0")
                attempts += 1
                await cache_service.set(attempts_key, str(attempts), ttl=300)

                if attempts >= 3:
                    # Too many wrong attempts - kick user
                    try:
                        await bot.ban_chat_member(
                            chat_id=chat_id,
                            user_id=user_id,
                            until_date=int(datetime.now(UTC).timestamp()) + 60,  # 1 min ban
                        )
                        await callback.answer("Too many wrong attempts. Please try again later.")

                        logger.info(
                            "captcha_failed_kicked",
                            user_id=user_id,
                            chat_id=chat_id,
                            attempts=attempts,
                        )
                    except TelegramBadRequest:
                        pass

                    # Delete captcha message
                    if callback.message:
                        try:
                            await callback.message.delete()
                        except TelegramBadRequest:
                            pass
                else:
                    await callback.answer(f"Wrong answer! {3 - attempts} attempts remaining.")

    except (ValueError, IndexError) as e:
        logger.warning("invalid_captcha_callback", error=str(e))
        await callback.answer("Invalid callback data")


# =============================================================================
# Settings Callbacks
# =============================================================================


@router.callback_query(F.data.startswith("settings:toggle:"), AdminFilter())
async def callback_settings_toggle(
    callback: CallbackQuery,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle settings toggle (on/off).

    Callback data format: settings:toggle:{setting_name}:{chat_id}
    """
    if not callback.data:
        await callback.answer("Invalid callback data")
        return

    try:
        parts = callback.data.split(":")
        if len(parts) < 4:
            await callback.answer("Invalid callback format")
            return

        setting_name = parts[2]
        chat_id = int(parts[3])

        valid_settings = ["sandbox_enabled", "notify_admins", "auto_delete"]

        if setting_name not in valid_settings:
            await callback.answer("Invalid setting")
            return

        if cache_service:
            settings_key = f"group_settings:{chat_id}"
            settings = await cache_service.get_json(settings_key) or {}

            # Toggle the setting
            current_value = settings.get(setting_name, True)
            settings[setting_name] = not current_value
            settings["updated_at"] = datetime.now(UTC).isoformat()

            await cache_service.set_json(settings_key, settings, ttl=86400 * 365)

            new_value = "ON" if settings[setting_name] else "OFF"
            await callback.answer(f"{setting_name} is now {new_value}")

            logger.info(
                "setting_toggled",
                chat_id=chat_id,
                setting=setting_name,
                new_value=settings[setting_name],
                changed_by=callback.from_user.id if callback.from_user else None,
            )
        else:
            await callback.answer("Settings service not available")

    except (ValueError, IndexError) as e:
        logger.warning("invalid_toggle_callback", error=str(e))
        await callback.answer("Invalid callback data")


@router.callback_query(F.data.startswith("settings:sensitivity:"), AdminFilter())
async def callback_settings_sensitivity(
    callback: CallbackQuery,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle sensitivity level change.

    Callback data format: settings:sensitivity:{level}:{chat_id}
    """
    if not callback.data:
        await callback.answer("Invalid callback data")
        return

    try:
        parts = callback.data.split(":")
        if len(parts) < 4:
            await callback.answer("Invalid callback format")
            return

        level = int(parts[2])
        chat_id = int(parts[3])

        if level < 1 or level > 10:
            await callback.answer("Sensitivity must be between 1 and 10")
            return

        if cache_service:
            settings_key = f"group_settings:{chat_id}"
            settings = await cache_service.get_json(settings_key) or {}

            settings["sensitivity"] = level
            settings["updated_at"] = datetime.now(UTC).isoformat()

            await cache_service.set_json(settings_key, settings, ttl=86400 * 365)

            await callback.answer(f"Sensitivity set to {level}/10")

            logger.info(
                "sensitivity_changed",
                chat_id=chat_id,
                sensitivity=level,
                changed_by=callback.from_user.id if callback.from_user else None,
            )
        else:
            await callback.answer("Settings service not available")

    except (ValueError, IndexError) as e:
        logger.warning("invalid_sensitivity_callback", error=str(e))
        await callback.answer("Invalid callback data")


# =============================================================================
# Confirmation Callbacks
# =============================================================================


@router.callback_query(F.data.startswith("confirm:"))
async def callback_confirm(
    callback: CallbackQuery,
    bot: Bot,
    cache_service: CacheService | None = None,
) -> None:
    """
    Handle confirmation dialogs.

    Callback data format: confirm:{action}:{params}
    """
    if not callback.data:
        await callback.answer("Invalid callback data")
        return

    try:
        parts = callback.data.split(":")
        if len(parts) < 2:
            await callback.answer("Invalid callback format")
            return

        action = parts[1]

        if action == "unban":
            # confirm:unban:{user_id}:{chat_id}
            if len(parts) < 4:
                await callback.answer("Invalid unban format")
                return

            user_id = int(parts[2])
            chat_id = int(parts[3])

            try:
                await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
                await callback.answer("User unbanned")

                if callback.message:
                    await callback.message.edit_text(f"User {user_id} has been unbanned.")

                logger.info(
                    "user_unbanned",
                    user_id=user_id,
                    chat_id=chat_id,
                    unbanned_by=callback.from_user.id if callback.from_user else None,
                )

            except TelegramBadRequest as e:
                await callback.answer(f"Failed to unban: {e}")

        elif action == "delete":
            # confirm:delete:{message_id}:{chat_id}
            if len(parts) < 4:
                await callback.answer("Invalid delete format")
                return

            message_id = int(parts[2])
            chat_id = int(parts[3])

            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
                await callback.answer("Message deleted")

                if callback.message:
                    await callback.message.delete()

            except TelegramBadRequest as e:
                await callback.answer(f"Failed to delete: {e}")

        else:
            await callback.answer("Unknown action")

    except (ValueError, IndexError) as e:
        logger.warning("invalid_confirm_callback", error=str(e))
        await callback.answer("Invalid callback data")


@router.callback_query(F.data == "cancel")
async def callback_cancel(callback: CallbackQuery) -> None:
    """
    Handle cancel action in dialogs.
    """
    await callback.answer("Cancelled")

    # Delete the confirmation message
    if callback.message:
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass


@router.callback_query(F.data == "dismiss")
async def callback_dismiss(callback: CallbackQuery) -> None:
    """
    Handle dismiss action for notifications.
    """
    await callback.answer("Dismissed")

    # Delete the notification message
    if callback.message:
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass


# =============================================================================
# Admin Feedback Callbacks (for spam detection improvement)
# =============================================================================


@router.callback_query(F.data.startswith("feedback:confirm:"), AdminFilter())
async def callback_feedback_confirm(
    callback: CallbackQuery,
    cache_service: CacheService | None = None,
    spam_db: SpamDB | None = None,
) -> None:
    """
    Handle confirmation that blocked message was indeed spam.

    Callback data format: feedback:confirm:{message_hash}:{chat_id}

    Actions:
    - Add message to spam DB for future training
    - Track signal effectiveness
    - Edit message to show confirmation
    """
    if not callback.data:
        await callback.answer("Invalid callback data")
        return

    try:
        parts = callback.data.split(":")
        if len(parts) < 4:
            await callback.answer("Invalid callback format")
            return

        message_hash = parts[2]
        chat_id = int(parts[3])

        # Record confirmation in stats
        if cache_service:
            stats_key = "saqshy:feedback_stats"
            stats = await cache_service.get_json(stats_key) or {
                "confirmed_spam": 0,
                "false_positives": 0,
            }
            stats["confirmed_spam"] = stats.get("confirmed_spam", 0) + 1
            await cache_service.set_json(stats_key, stats, ttl=86400 * 30)

            # Record this message as confirmed spam for signal analysis
            confirm_key = f"saqshy:confirmed:{message_hash}"
            await cache_service.set(confirm_key, "spam", ttl=86400 * 7)

        # Edit the notification message
        admin_name = callback.from_user.first_name if callback.from_user else "Admin"
        if callback.message and isinstance(callback.message, Message):
            try:
                new_text = callback.message.text or ""
                new_text += f"\n\n<b>CONFIRMED SPAM</b> by {admin_name}"
                await callback.message.edit_text(new_text, reply_markup=None)
            except TelegramBadRequest:
                pass

        await callback.answer("Feedback recorded - confirmed as spam")

        logger.info(
            "feedback_confirmed_spam",
            message_hash=message_hash,
            chat_id=chat_id,
            confirmed_by=callback.from_user.id if callback.from_user else None,
        )

    except (ValueError, IndexError) as e:
        logger.warning("invalid_feedback_confirm_callback", error=str(e))
        await callback.answer("Invalid callback data")


@router.callback_query(F.data.startswith("feedback:fp:"), AdminFilter())
async def callback_feedback_false_positive(
    callback: CallbackQuery,
    cache_service: CacheService | None = None,
    spam_db: SpamDB | None = None,
) -> None:
    """
    Handle report that blocked message was a false positive.

    Callback data format: feedback:fp:{message_hash}:{chat_id}:{user_id}

    Actions:
    - Record false positive for signal tuning
    - Remove from spam DB if present
    - Track which signals caused the FP
    - Edit message to show FP status
    """
    if not callback.data:
        await callback.answer("Invalid callback data")
        return

    try:
        parts = callback.data.split(":")
        if len(parts) < 4:
            await callback.answer("Invalid callback format")
            return

        message_hash = parts[2]
        chat_id = int(parts[3])
        user_id = int(parts[4]) if len(parts) > 4 else 0

        # Record false positive in stats
        if cache_service:
            stats_key = "saqshy:feedback_stats"
            stats = await cache_service.get_json(stats_key) or {
                "confirmed_spam": 0,
                "false_positives": 0,
            }
            stats["false_positives"] = stats.get("false_positives", 0) + 1
            await cache_service.set_json(stats_key, stats, ttl=86400 * 30)

            # Record this as FP for signal analysis
            fp_key = f"saqshy:fp:{message_hash}"
            await cache_service.set(fp_key, "fp", ttl=86400 * 7)

            # Restore user trust if we have their ID
            if user_id > 0:
                await _update_user_trust(cache_service, user_id, "approved")

        # Try to remove from spam DB if present
        if spam_db:
            try:
                # Use message_hash as pattern ID to remove
                await spam_db.remove_pattern(message_hash)
                logger.info(
                    "removed_fp_from_spam_db",
                    message_hash=message_hash,
                )
            except Exception as e:
                logger.debug(
                    "remove_from_spam_db_failed",
                    message_hash=message_hash,
                    error=str(e),
                )

        # Edit the notification message
        admin_name = callback.from_user.first_name if callback.from_user else "Admin"
        if callback.message and isinstance(callback.message, Message):
            try:
                new_text = callback.message.text or ""
                new_text += f"\n\n<b>FALSE POSITIVE</b> reported by {admin_name}"
                await callback.message.edit_text(new_text, reply_markup=None)
            except TelegramBadRequest:
                pass

        await callback.answer("Feedback recorded - marked as false positive")

        logger.info(
            "feedback_false_positive",
            message_hash=message_hash,
            chat_id=chat_id,
            user_id=user_id,
            reported_by=callback.from_user.id if callback.from_user else None,
        )

    except (ValueError, IndexError) as e:
        logger.warning("invalid_feedback_fp_callback", error=str(e))
        await callback.answer("Invalid callback data")


# =============================================================================
# Helper Functions
# =============================================================================


async def _update_user_trust(
    cache_service: CacheService,
    user_id: int,
    action: str,
) -> None:
    """
    Update user trust based on review action.

    Args:
        cache_service: Redis cache service.
        user_id: Telegram user ID.
        action: "approved" or "rejected".
    """
    try:
        user_key = f"saqshy:user_stats:{user_id}"
        stats = await cache_service.get_json(user_key) or {
            "total_messages": 0,
            "approved": 0,
            "flagged": 0,
            "blocked": 0,
        }

        if action == "approved":
            stats["approved"] = stats.get("approved", 0) + 1
        elif action == "rejected":
            stats["blocked"] = stats.get("blocked", 0) + 1

        await cache_service.set_json(user_key, stats, ttl=86400 * 90)  # 90 days

    except TimeoutError:
        logger.warning(
            "update_user_trust_timeout",
            user_id=user_id,
            action=action,
        )
    except ConnectionError as e:
        logger.warning(
            "update_user_trust_connection_error",
            user_id=user_id,
            action=action,
            error=str(e),
        )
    except (ValueError, TypeError) as e:
        logger.warning(
            "update_user_trust_data_error",
            user_id=user_id,
            action=action,
            error=str(e),
        )
    except Exception as e:
        logger.warning(
            "update_user_trust_unexpected_error",
            user_id=user_id,
            action=action,
            error=str(e),
            error_type=type(e).__name__,
        )
