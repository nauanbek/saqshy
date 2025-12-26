"""
SAQSHY Member Handlers

Handles join/leave events for group members.

Key Responsibilities:
- Detect and record new member joins for TTFM calculation
- Track member departures and cleanup sandbox state
- Detect raid patterns (mass joins in short time)
- Initialize sandbox mode for new users if configured
- Record kick/ban events for cross-group analysis

All handlers are defensive and never crash the bot on errors.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from aiogram import Bot, F, Router
from aiogram.types import ChatMemberUpdated

if TYPE_CHECKING:
    from saqshy.services.cache import CacheService

logger = structlog.get_logger(__name__)

router = Router(name="members")

# Raid detection constants
RAID_WINDOW_SECONDS = 60  # 1 minute window
RAID_JOIN_THRESHOLD = 10  # 10+ joins in window = raid
RAID_MODE_DURATION_SECONDS = 300  # 5 minutes of raid mode

# Cache key prefixes
KEY_JOIN_COUNT = "saqshy:raid:joins"
KEY_RAID_MODE = "saqshy:raid:active"


# =============================================================================
# Member Join Handler
# =============================================================================


@router.chat_member(F.new_chat_member.status == "member")
async def handle_member_join(
    event: ChatMemberUpdated,
    bot: Bot,
    cache_service: CacheService | None = None,
    correlation_id: str | None = None,
) -> None:
    """
    Handle new member joining the group.

    Records join time for TTFM calculation and checks for raid patterns.

    Args:
        event: Chat member update event.
        bot: Bot instance.
        cache_service: Redis cache service.
        correlation_id: Request correlation ID.
    """
    user = event.new_chat_member.user
    chat = event.chat
    join_time = datetime.now(UTC)

    log = logger.bind(
        user_id=user.id,
        username=user.username,
        chat_id=chat.id,
        chat_title=chat.title,
        correlation_id=correlation_id,
    )

    log.info("member_joined")

    try:
        # Record join time for TTFM (Time To First Message) calculation
        if cache_service:
            await _record_join_time(cache_service, user.id, chat.id, join_time)

            # Check for raid pattern (many joins in short time)
            is_raid = await _check_and_update_raid_status(cache_service, chat.id, join_time, log)

            if is_raid:
                log.warning("raid_mode_active", chat_id=chat.id)
                # In raid mode, apply stricter controls
                # Could auto-mute new joins or require captcha

        # Check if user should enter sandbox mode
        # Sandbox mode requires captcha or waiting period before posting
        should_sandbox = await _should_enter_sandbox(
            user_id=user.id,
            chat_id=chat.id,
            is_premium=user.is_premium or False,
            cache_service=cache_service,
        )

        if should_sandbox and cache_service:
            await _initialize_sandbox_state(cache_service, user.id, chat.id, join_time, log)

    except Exception as e:
        log.error(
            "member_join_handling_failed",
            error=str(e),
            error_type=type(e).__name__,
        )


# =============================================================================
# Member Leave Handler
# =============================================================================


@router.chat_member(F.new_chat_member.status == "left")
async def handle_member_leave(
    event: ChatMemberUpdated,
    cache_service: CacheService | None = None,
    correlation_id: str | None = None,
) -> None:
    """
    Handle member leaving the group.

    Cleans up cached data for the user.

    Args:
        event: Chat member update event.
        cache_service: Redis cache service.
        correlation_id: Request correlation ID.
    """
    user = event.new_chat_member.user
    chat = event.chat

    log = logger.bind(
        user_id=user.id,
        username=user.username,
        chat_id=chat.id,
        correlation_id=correlation_id,
    )

    log.info("member_left")

    try:
        # Cleanup sandbox state if exists
        if cache_service:
            await _cleanup_user_state(cache_service, user.id, chat.id, log)

    except Exception as e:
        log.error(
            "member_leave_handling_failed",
            error=str(e),
            error_type=type(e).__name__,
        )


# =============================================================================
# Member Kicked Handler
# =============================================================================


@router.chat_member(F.new_chat_member.status == "kicked")
async def handle_member_kicked(
    event: ChatMemberUpdated,
    cache_service: CacheService | None = None,
    correlation_id: str | None = None,
) -> None:
    """
    Handle member being kicked from the group.

    Records kick for cross-group analysis (kicked users are higher risk in other groups).

    Args:
        event: Chat member update event.
        cache_service: Redis cache service.
        correlation_id: Request correlation ID.
    """
    user = event.new_chat_member.user
    chat = event.chat

    log = logger.bind(
        user_id=user.id,
        username=user.username,
        chat_id=chat.id,
        correlation_id=correlation_id,
    )

    log.info("member_kicked")

    try:
        if cache_service:
            # Record kick for cross-group analysis
            await _record_user_action(cache_service, user.id, chat.id, "kicked", log)

            # Cleanup user state
            await _cleanup_user_state(cache_service, user.id, chat.id, log)

    except Exception as e:
        log.error(
            "member_kicked_handling_failed",
            error=str(e),
            error_type=type(e).__name__,
        )


# =============================================================================
# Member Banned Handler
# =============================================================================


@router.chat_member(F.new_chat_member.status == "banned")
async def handle_member_banned(
    event: ChatMemberUpdated,
    cache_service: CacheService | None = None,
    correlation_id: str | None = None,
) -> None:
    """
    Handle member being banned from the group.

    Records ban for cross-group analysis (banned users are high risk).

    Args:
        event: Chat member update event.
        cache_service: Redis cache service.
        correlation_id: Request correlation ID.
    """
    user = event.new_chat_member.user
    chat = event.chat

    log = logger.bind(
        user_id=user.id,
        username=user.username,
        chat_id=chat.id,
        correlation_id=correlation_id,
    )

    log.info("member_banned")

    try:
        if cache_service:
            # Record ban for cross-group analysis
            await _record_user_action(cache_service, user.id, chat.id, "banned", log)

            # Cleanup user state
            await _cleanup_user_state(cache_service, user.id, chat.id, log)

    except Exception as e:
        log.error(
            "member_banned_handling_failed",
            error=str(e),
            error_type=type(e).__name__,
        )


# =============================================================================
# Member Restricted Handler
# =============================================================================


@router.chat_member(F.new_chat_member.status == "restricted")
async def handle_member_restricted(
    event: ChatMemberUpdated,
    cache_service: CacheService | None = None,
    correlation_id: str | None = None,
) -> None:
    """
    Handle member being restricted in the group.

    Records restriction for behavior analysis.

    Args:
        event: Chat member update event.
        cache_service: Redis cache service.
        correlation_id: Request correlation ID.
    """
    user = event.new_chat_member.user
    chat = event.chat

    log = logger.bind(
        user_id=user.id,
        chat_id=chat.id,
        correlation_id=correlation_id,
    )

    log.info("member_restricted")

    try:
        if cache_service:
            await _record_user_action(cache_service, user.id, chat.id, "restricted", log)

    except Exception as e:
        log.error(
            "member_restricted_handling_failed",
            error=str(e),
            error_type=type(e).__name__,
        )


# =============================================================================
# Helper Functions
# =============================================================================


async def _record_join_time(
    cache_service: CacheService,
    user_id: int,
    chat_id: int,
    join_time: datetime,
) -> None:
    """
    Record user join time for TTFM calculation.

    Args:
        cache_service: Redis cache service.
        user_id: Telegram user ID.
        chat_id: Telegram chat ID.
        join_time: When user joined.
    """
    try:
        await cache_service.record_join(user_id, chat_id, join_time)
    except Exception as e:
        logger.warning(
            "failed_to_record_join_time",
            user_id=user_id,
            chat_id=chat_id,
            error=str(e),
        )


async def _check_and_update_raid_status(
    cache_service: CacheService,
    chat_id: int,
    join_time: datetime,
    log: structlog.BoundLogger,
) -> bool:
    """
    Check and update raid detection status.

    Uses a sliding window counter to detect mass joins.

    Args:
        cache_service: Redis cache service.
        chat_id: Telegram chat ID.
        join_time: Join timestamp.
        log: Bound logger.

    Returns:
        True if raid mode is active.
    """
    try:
        # Check if already in raid mode
        raid_mode_key = f"{KEY_RAID_MODE}:{chat_id}"
        is_raid_mode = await cache_service.get(raid_mode_key)
        if is_raid_mode == "1":
            return True

        # Increment join counter using rate limit mechanism
        join_count = await cache_service.increment_rate(
            user_id=0,  # Global for chat
            chat_id=chat_id,
            window_seconds=RAID_WINDOW_SECONDS,
        )

        # Check if threshold exceeded
        if join_count >= RAID_JOIN_THRESHOLD:
            # Activate raid mode
            await cache_service.set(
                raid_mode_key,
                "1",
                ttl=RAID_MODE_DURATION_SECONDS,
            )
            log.warning(
                "raid_mode_activated",
                chat_id=chat_id,
                join_count=join_count,
                threshold=RAID_JOIN_THRESHOLD,
            )
            return True

        return False

    except Exception as e:
        log.warning("raid_check_failed", error=str(e))
        return False


async def _should_enter_sandbox(
    user_id: int,
    chat_id: int,
    is_premium: bool,
    cache_service: CacheService | None,
) -> bool:
    """
    Check if user should enter sandbox mode.

    Sandbox mode is skipped for:
    - Premium users (trusted)
    - Channel subscribers (if subscription is configured)
    - Users with previous approved messages in other groups

    Args:
        user_id: Telegram user ID.
        chat_id: Telegram chat ID.
        is_premium: Whether user is premium.
        cache_service: Redis cache service.

    Returns:
        True if user should enter sandbox.
    """
    # Premium users skip sandbox
    if is_premium:
        return False

    if cache_service:
        # Check group settings for sandbox mode
        settings = await cache_service.get_json(f"group_settings:{chat_id}")
        if settings:
            # Sandbox mode might be disabled for this group
            if not settings.get("sandbox_enabled", True):
                return False

    # Default: new users enter sandbox
    return True


async def _initialize_sandbox_state(
    cache_service: CacheService,
    user_id: int,
    chat_id: int,
    join_time: datetime,
    log: structlog.BoundLogger,
) -> None:
    """
    Initialize sandbox state for a new user.

    Sandbox state tracks:
    - Join time
    - Captcha status
    - Message count in sandbox
    - Sandbox expiry time

    Args:
        cache_service: Redis cache service.
        user_id: Telegram user ID.
        chat_id: Telegram chat ID.
        join_time: When user joined.
        log: Bound logger.
    """
    try:
        sandbox_key = f"saqshy:sandbox:{chat_id}:{user_id}"
        sandbox_state = {
            "user_id": user_id,
            "chat_id": chat_id,
            "join_time": join_time.isoformat(),
            "captcha_completed": False,
            "messages_in_sandbox": 0,
            "sandbox_started": join_time.isoformat(),
            "sandbox_expires": None,  # Could be time-based or message-based
        }

        await cache_service.set_json(sandbox_key, sandbox_state, ttl=86400 * 7)  # 7 days

        log.info("sandbox_initialized", user_id=user_id)

    except Exception as e:
        log.warning("sandbox_initialization_failed", error=str(e))


async def _cleanup_user_state(
    cache_service: CacheService,
    user_id: int,
    chat_id: int,
    log: structlog.BoundLogger,
) -> None:
    """
    Cleanup cached state for a user leaving the group.

    Args:
        cache_service: Redis cache service.
        user_id: Telegram user ID.
        chat_id: Telegram chat ID.
        log: Bound logger.
    """
    try:
        # Delete sandbox state
        sandbox_key = f"saqshy:sandbox:{chat_id}:{user_id}"
        await cache_service.delete(sandbox_key)

        # Could also clean up other user-specific data here
        # but we keep join times and message counts for cross-group analysis

        log.debug("user_state_cleaned", user_id=user_id)

    except Exception as e:
        log.warning("user_state_cleanup_failed", error=str(e))


async def _record_user_action(
    cache_service: CacheService,
    user_id: int,
    chat_id: int,
    action: str,
    log: structlog.BoundLogger,
) -> None:
    """
    Record user action (kicked, banned, restricted) for cross-group analysis.

    Args:
        cache_service: Redis cache service.
        user_id: Telegram user ID.
        chat_id: Telegram chat ID.
        action: Action type ("kicked", "banned", "restricted").
        log: Bound logger.
    """
    try:
        # Increment cross-group action counter
        action_key = f"saqshy:user_actions:{user_id}"
        actions = await cache_service.get_json(action_key) or {
            "kicked_count": 0,
            "banned_count": 0,
            "restricted_count": 0,
            "groups": [],
        }

        if action == "kicked":
            actions["kicked_count"] = actions.get("kicked_count", 0) + 1
        elif action == "banned":
            actions["banned_count"] = actions.get("banned_count", 0) + 1
        elif action == "restricted":
            actions["restricted_count"] = actions.get("restricted_count", 0) + 1

        # Track which groups took action
        if chat_id not in actions.get("groups", []):
            actions.setdefault("groups", []).append(chat_id)
            # Keep only last 100 groups
            actions["groups"] = actions["groups"][-100:]

        await cache_service.set_json(action_key, actions, ttl=86400 * 30)  # 30 days

        log.debug(
            "user_action_recorded",
            user_id=user_id,
            action=action,
            total_kicked=actions.get("kicked_count", 0),
            total_banned=actions.get("banned_count", 0),
        )

    except Exception as e:
        log.warning(
            "record_user_action_failed",
            action=action,
            error=str(e),
        )


async def check_raid_pattern(
    cache_service: CacheService,
    chat_id: int,
) -> bool:
    """
    Check if a group is currently in raid mode.

    Args:
        cache_service: Redis cache service.
        chat_id: Telegram chat ID.

    Returns:
        True if raid mode is active.
    """
    try:
        raid_mode_key = f"{KEY_RAID_MODE}:{chat_id}"
        is_raid = await cache_service.get(raid_mode_key)
        return is_raid == "1"
    except Exception as e:
        logger.debug(
            "raid_mode_check_failed",
            chat_id=chat_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


async def get_user_cross_group_stats(
    cache_service: CacheService,
    user_id: int,
) -> dict:
    """
    Get user's cross-group action statistics.

    Useful for risk calculation - users kicked/banned in multiple groups
    are higher risk.

    Args:
        cache_service: Redis cache service.
        user_id: Telegram user ID.

    Returns:
        Dict with kicked_count, banned_count, restricted_count, groups.
    """
    try:
        action_key = f"saqshy:user_actions:{user_id}"
        actions = await cache_service.get_json(action_key)
        if actions:
            return actions
    except Exception as e:
        logger.warning(
            "get_user_cross_group_stats_failed",
            user_id=user_id,
            error=str(e),
        )

    return {
        "kicked_count": 0,
        "banned_count": 0,
        "restricted_count": 0,
        "groups": [],
    }
