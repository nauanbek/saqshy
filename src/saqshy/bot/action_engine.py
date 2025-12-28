"""
SAQSHY Action Engine

Maps verdicts to concrete actions and executes them safely.

The ActionEngine translates risk verdicts into executable actions
while respecting group settings, handling Telegram API errors gracefully,
and maintaining idempotency for safe retries.

Key Design Principles:
- All Telegram API calls are wrapped with timeouts and error handling
- Errors are logged with context but never crash the processing loop
- Idempotency protection prevents duplicate actions on retry
- Safe fallbacks ensure we always log decisions even when actions fail
- Admin notifications are rate-limited to prevent spam
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, TypeVar

import structlog
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from aiogram.types import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Message

from saqshy.core.types import GroupType, RiskResult, ThreatType, Verdict

# TypeVar for generic retry function return type
T = TypeVar("T")

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from saqshy.services.cache import CacheService


logger = structlog.get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Telegram API timeout (seconds)
TELEGRAM_API_TIMEOUT = 30.0

# Idempotency key TTL (seconds) - prevent duplicate actions for 5 minutes
IDEMPOTENCY_TTL = 300

# Admin notification rate limit (seconds) - max 1 notification per group per 5 minutes
ADMIN_NOTIFY_RATE_LIMIT = 300

# Maximum message preview length in admin notifications
MAX_MESSAGE_PREVIEW = 100

# Retry configuration for Telegram API calls
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY = 1.0  # seconds

# Non-retryable error types (permission/client errors that won't be fixed by retrying)
NON_RETRYABLE_ERRORS = (TelegramForbiddenError, TelegramBadRequest, TelegramNotFound)


# =============================================================================
# Action Types and Results
# =============================================================================


class ActionType(str, Enum):
    """Types of actions that can be taken."""

    NONE = "none"
    LOG = "log"
    DELETE = "delete"
    RESTRICT = "restrict"
    BAN = "ban"
    NOTIFY_ADMINS = "notify_admins"
    QUEUE_REVIEW = "queue_review"
    HOLD = "hold"


@dataclass
class ActionResult:
    """
    Result of executing a single action.

    Attributes:
        action: The type of action attempted.
        success: Whether the action completed successfully.
        error: Error message if action failed.
        details: Additional context about the action.
        duration_ms: Time taken to execute the action.
    """

    action: str
    success: bool
    error: str | None = None
    details: dict[str, Any] | None = None
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "action": self.action,
            "success": self.success,
            "error": self.error,
            "details": self.details,
            "duration_ms": self.duration_ms,
        }


@dataclass
class ExecutionResult:
    """
    Result of executing all actions for a verdict.

    Attributes:
        verdict: The verdict that triggered these actions.
        actions_attempted: List of action results.
        message_deleted: Whether the message was deleted.
        user_banned: Whether the user was banned.
        user_restricted: Whether the user was restricted.
        admins_notified: Whether admins were notified.
        logged: Whether the decision was logged to database.
        total_duration_ms: Total execution time.
    """

    verdict: Verdict
    actions_attempted: list[ActionResult] = field(default_factory=list)
    message_deleted: bool = False
    user_banned: bool = False
    user_restricted: bool = False
    admins_notified: bool = False
    logged: bool = False
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "verdict": self.verdict.value,
            "actions_attempted": [a.to_dict() for a in self.actions_attempted],
            "message_deleted": self.message_deleted,
            "user_banned": self.user_banned,
            "user_restricted": self.user_restricted,
            "admins_notified": self.admins_notified,
            "logged": self.logged,
            "total_duration_ms": self.total_duration_ms,
        }


# =============================================================================
# Verdict to Action Mapping
# =============================================================================


VERDICT_ACTIONS: dict[Verdict, list[str]] = {
    Verdict.ALLOW: [],  # No action needed
    Verdict.WATCH: ["log"],  # Log only
    Verdict.LIMIT: ["delete", "restrict", "log", "notify_admins"],  # Delete + temp restriction
    Verdict.REVIEW: ["hold", "log", "queue_review", "notify_admins"],  # Hold for admin review
    Verdict.BLOCK: ["delete", "ban", "log", "notify_admins"],  # Full block
}


# =============================================================================
# Permission Presets
# =============================================================================


RESTRICT_PERMISSIONS: dict[str, ChatPermissions] = {
    # Soft: Can send text, but no media/links
    "soft": ChatPermissions(
        can_send_messages=True,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_invite_users=True,
    ),
    # Medium: No messages at all
    "medium": ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_invite_users=True,
    ),
    # Hard: Complete lockdown
    "hard": ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    ),
}


# =============================================================================
# Action Configuration
# =============================================================================


@dataclass
class ActionConfig:
    """Configuration for action execution."""

    # Restriction durations (seconds)
    restrict_duration_short: int = 3600  # 1 hour
    restrict_duration_medium: int = 86400  # 24 hours
    restrict_duration_long: int = 604800  # 7 days

    # Ban durations
    ban_duration_temp: int = 86400 * 30  # 30 days
    ban_duration_permanent: int | None = None  # None = forever

    # Permission preset for restrictions
    restriction_preset: str = "medium"

    # Notification settings
    notify_admins_on_block: bool = True
    notify_admins_on_review: bool = True
    admin_notify_rate_limit: int = ADMIN_NOTIFY_RATE_LIMIT

    # Logging
    log_all_decisions: bool = True


# =============================================================================
# ActionEngine
# =============================================================================


class ActionEngine:
    """
    Executes moderation actions based on risk verdicts.

    This engine:
    - Maps verdicts to concrete actions (delete, restrict, ban, etc.)
    - Executes actions safely with timeout and error handling
    - Provides idempotency to prevent duplicate actions
    - Logs all decisions and action outcomes
    - Rate-limits admin notifications

    Thread Safety:
        This class is thread-safe when used with asyncio.
        All state is passed explicitly or stored in external services.

    Error Handling:
        All Telegram API calls are wrapped in try/except.
        Errors are logged but never crash the caller.
        Partial failures are recorded and logged.

    Example:
        >>> engine = ActionEngine(bot, cache_service, db_session)
        >>> results = await engine.execute(risk_result, message)
        >>> print(f"Deleted: {results.message_deleted}")
    """

    def __init__(
        self,
        bot: Bot,
        cache_service: CacheService | None = None,
        db_session: AsyncSession | None = None,
        group_type: GroupType = GroupType.GENERAL,
        config: ActionConfig | None = None,
    ) -> None:
        """
        Initialize the action engine.

        Args:
            bot: Telegram Bot instance for API calls.
            cache_service: Redis cache for idempotency and rate limiting.
            db_session: SQLAlchemy session for logging decisions.
            group_type: Type of group for action calibration.
            config: Action configuration settings.
        """
        self.bot = bot
        self.cache = cache_service
        self.db_session = db_session
        self.group_type = group_type
        self.config = config or ActionConfig()

    # =========================================================================
    # Main Execution Entry Point
    # =========================================================================

    async def execute(
        self,
        risk_result: RiskResult,
        message: Message,
    ) -> ExecutionResult:
        """
        Execute all actions for a verdict.

        This is the main entry point. It determines the appropriate actions
        based on the verdict and executes them in order with proper error
        handling and fallbacks.

        Args:
            risk_result: The risk calculation result.
            message: The Telegram message object.

        Returns:
            ExecutionResult with details of all actions taken.
        """
        start_time = time.perf_counter()
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        message_id = message.message_id

        log = logger.bind(
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            verdict=risk_result.verdict.value,
            score=risk_result.score,
        )

        result = ExecutionResult(verdict=risk_result.verdict)

        # Check idempotency - skip if already processed
        idempotency_key = self._compute_idempotency_key(chat_id, message_id)
        if await self._check_already_processed(idempotency_key):
            log.info("action_skipped_idempotency", reason="already_processed")
            result.total_duration_ms = (time.perf_counter() - start_time) * 1000
            return result

        # Get actions for this verdict
        actions = VERDICT_ACTIONS.get(risk_result.verdict, [])

        if not actions:
            log.debug("no_actions_for_verdict")
            result.total_duration_ms = (time.perf_counter() - start_time) * 1000
            return result

        # Execute each action with safe fallbacks
        for action_name in actions:
            action_result = await self._execute_single_action(
                action_name=action_name,
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id,
                risk_result=risk_result,
                message=message,
                log=log,
            )

            result.actions_attempted.append(action_result)

            # Update result flags based on action outcomes
            if action_result.success:
                if action_name == "delete":
                    result.message_deleted = True
                elif action_name == "ban":
                    result.user_banned = True
                elif action_name == "restrict":
                    result.user_restricted = True
                elif action_name == "notify_admins":
                    result.admins_notified = True
                elif action_name == "log":
                    result.logged = True

        # Mark as processed for idempotency
        await self._mark_as_processed(idempotency_key)

        result.total_duration_ms = (time.perf_counter() - start_time) * 1000

        log.info(
            "actions_executed",
            message_deleted=result.message_deleted,
            user_banned=result.user_banned,
            user_restricted=result.user_restricted,
            admins_notified=result.admins_notified,
            logged=result.logged,
            total_duration_ms=round(result.total_duration_ms, 2),
        )

        return result

    async def _execute_single_action(
        self,
        action_name: str,
        chat_id: int,
        user_id: int,
        message_id: int,
        risk_result: RiskResult,
        message: Message,
        log: Any,
    ) -> ActionResult:
        """
        Execute a single action with error handling.

        Dispatches to the appropriate action method based on action_name.
        """
        start_time = time.perf_counter()

        try:
            match action_name:
                case "delete":
                    action_result = await self.delete_message(chat_id, message_id)
                case "ban":
                    duration = self._calculate_ban_duration(risk_result)
                    action_result = await self.ban_user(chat_id, user_id, duration)
                case "restrict":
                    duration = self._calculate_restrict_duration(risk_result)
                    action_result = await self.restrict_user(chat_id, user_id, duration)
                case "notify_admins":
                    action_result = await self.notify_admins(chat_id, risk_result, message)
                case "queue_review":
                    action_result = await self.queue_for_review(risk_result, message)
                case "hold":
                    # Hold action is implemented via restriction with shorter duration
                    action_result = await self.restrict_user(chat_id, user_id, 3600, preset="soft")
                case "log":
                    # Note: Actions list is empty here as we're logging during execution
                    # The final log in execute_with_fallback captures all successful actions
                    await self.log_decision(
                        risk_result,
                        message,
                        [],  # Actions recorded separately
                    )
                    action_result = ActionResult(
                        action="log",
                        success=True,
                        details={"verdict": risk_result.verdict.value},
                    )
                case _:
                    action_result = ActionResult(
                        action=action_name,
                        success=False,
                        error=f"Unknown action: {action_name}",
                    )

        except Exception as e:
            log.error(
                "action_execution_error",
                action=action_name,
                error=str(e),
                error_type=type(e).__name__,
            )
            action_result = ActionResult(
                action=action_name,
                success=False,
                error=str(e),
            )

        action_result.duration_ms = (time.perf_counter() - start_time) * 1000
        return action_result

    # =========================================================================
    # Individual Action Methods
    # =========================================================================

    async def delete_message(
        self,
        chat_id: int,
        message_id: int,
    ) -> ActionResult:
        """
        Delete a spam message with automatic retry on transient errors.

        Handles all Telegram API errors gracefully and returns
        success=True if the message is gone (including if already deleted).
        Retries on network errors and rate limits with exponential backoff.

        Args:
            chat_id: Telegram chat ID.
            message_id: Telegram message ID.

        Returns:
            ActionResult indicating success/failure.
        """
        try:
            await self._telegram_api_with_retry(
                operation=lambda: asyncio.wait_for(
                    self.bot.delete_message(chat_id=chat_id, message_id=message_id),
                    timeout=TELEGRAM_API_TIMEOUT,
                ),
                operation_name="delete_message",
            )
            return ActionResult(
                action="delete",
                success=True,
                details={"chat_id": chat_id, "message_id": message_id},
            )

        except TimeoutError:
            logger.warning(
                "delete_message_timeout",
                chat_id=chat_id,
                message_id=message_id,
            )
            return ActionResult(
                action="delete",
                success=False,
                error="Telegram API timeout after retries",
            )

        except TelegramRetryAfter as e:
            logger.warning(
                "delete_message_rate_limited",
                chat_id=chat_id,
                message_id=message_id,
                retry_after=e.retry_after,
            )
            return ActionResult(
                action="delete",
                success=False,
                error=f"Rate limited, retry after {e.retry_after}s",
                details={"retry_after": e.retry_after},
            )

        except TelegramBadRequest as e:
            error_msg = str(e).lower()
            # Message already deleted or not found - consider it a success
            if "message to delete not found" in error_msg:
                return ActionResult(
                    action="delete",
                    success=True,
                    details={"already_deleted": True},
                )
            if "message can't be deleted" in error_msg:
                logger.warning(
                    "delete_message_not_allowed",
                    chat_id=chat_id,
                    message_id=message_id,
                    error=str(e),
                )
                return ActionResult(
                    action="delete",
                    success=False,
                    error="Message cannot be deleted (permissions or age)",
                )
            return ActionResult(
                action="delete",
                success=False,
                error=str(e),
            )

        except TelegramForbiddenError as e:
            logger.warning(
                "delete_message_forbidden",
                chat_id=chat_id,
                message_id=message_id,
                error=str(e),
            )
            return ActionResult(
                action="delete",
                success=False,
                error="Bot lacks delete permission",
            )

        except TelegramNotFound:
            # Chat or message not found - could be deleted or bot removed
            return ActionResult(
                action="delete",
                success=True,  # Goal achieved - message is gone
                details={"not_found": True},
            )

        except TelegramAPIError as e:
            logger.error(
                "delete_message_api_error",
                chat_id=chat_id,
                message_id=message_id,
                error=str(e),
            )
            return ActionResult(
                action="delete",
                success=False,
                error=str(e),
            )

    async def restrict_user(
        self,
        chat_id: int,
        user_id: int,
        duration: int = 3600,
        permissions: ChatPermissions | None = None,
        preset: str | None = None,
    ) -> ActionResult:
        """
        Restrict user permissions temporarily with automatic retry.

        Retries on network errors and rate limits with exponential backoff.

        Args:
            chat_id: Telegram chat ID.
            user_id: Telegram user ID.
            duration: Duration in seconds (default 1 hour).
            permissions: Specific permissions to apply.
            preset: Use a preset ("soft", "medium", "hard").

        Returns:
            ActionResult indicating success/failure.
        """
        # Determine permissions
        if permissions is None:
            preset = preset or self.config.restriction_preset
            permissions = RESTRICT_PERMISSIONS.get(preset, RESTRICT_PERMISSIONS["medium"])

        # Calculate until_date
        until_date = int(datetime.now(UTC).timestamp() + duration)

        try:
            await self._telegram_api_with_retry(
                operation=lambda: asyncio.wait_for(
                    self.bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=user_id,
                        permissions=permissions,
                        until_date=until_date,
                    ),
                    timeout=TELEGRAM_API_TIMEOUT,
                ),
                operation_name="restrict_user",
            )
            return ActionResult(
                action="restrict",
                success=True,
                details={
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "duration": duration,
                    "until_date": until_date,
                },
            )

        except TimeoutError:
            logger.warning(
                "restrict_user_timeout",
                chat_id=chat_id,
                user_id=user_id,
            )
            return ActionResult(
                action="restrict",
                success=False,
                error="Telegram API timeout after retries",
            )

        except TelegramRetryAfter as e:
            logger.warning(
                "restrict_user_rate_limited",
                chat_id=chat_id,
                user_id=user_id,
                retry_after=e.retry_after,
            )
            return ActionResult(
                action="restrict",
                success=False,
                error=f"Rate limited, retry after {e.retry_after}s",
            )

        except TelegramBadRequest as e:
            error_msg = str(e).lower()
            if "user is an administrator" in error_msg:
                logger.info(
                    "restrict_user_is_admin",
                    chat_id=chat_id,
                    user_id=user_id,
                )
                return ActionResult(
                    action="restrict",
                    success=False,
                    error="Cannot restrict administrator",
                )
            if "user not found" in error_msg:
                return ActionResult(
                    action="restrict",
                    success=False,
                    error="User not found in chat",
                )
            logger.warning(
                "restrict_user_bad_request",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
            )
            return ActionResult(
                action="restrict",
                success=False,
                error=str(e),
            )

        except TelegramForbiddenError as e:
            logger.warning(
                "restrict_user_forbidden",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
            )
            return ActionResult(
                action="restrict",
                success=False,
                error="Bot lacks restrict permission",
            )

        except TelegramNotFound:
            return ActionResult(
                action="restrict",
                success=False,
                error="Chat not found",
            )

        except TelegramAPIError as e:
            logger.error(
                "restrict_user_api_error",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
            )
            return ActionResult(
                action="restrict",
                success=False,
                error=str(e),
            )

    async def ban_user(
        self,
        chat_id: int,
        user_id: int,
        duration: int | None = None,
        revoke_messages: bool = False,
    ) -> ActionResult:
        """
        Ban a user from the group with automatic retry on transient errors.

        Retries on network errors and rate limits with exponential backoff.

        Args:
            chat_id: Telegram chat ID.
            user_id: Telegram user ID.
            duration: Ban duration in seconds (None = permanent).
            revoke_messages: Whether to delete user's recent messages.

        Returns:
            ActionResult indicating success/failure.
        """
        # Calculate until_date
        until_date = None
        if duration is not None:
            until_date = int(datetime.now(UTC).timestamp() + duration)

        try:
            await self._telegram_api_with_retry(
                operation=lambda: asyncio.wait_for(
                    self.bot.ban_chat_member(
                        chat_id=chat_id,
                        user_id=user_id,
                        until_date=until_date,
                        revoke_messages=revoke_messages,
                    ),
                    timeout=TELEGRAM_API_TIMEOUT,
                ),
                operation_name="ban_user",
            )
            return ActionResult(
                action="ban",
                success=True,
                details={
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "duration": duration,
                    "permanent": duration is None,
                    "revoke_messages": revoke_messages,
                },
            )

        except TimeoutError:
            logger.warning(
                "ban_user_timeout",
                chat_id=chat_id,
                user_id=user_id,
            )
            return ActionResult(
                action="ban",
                success=False,
                error="Telegram API timeout after retries",
            )

        except TelegramRetryAfter as e:
            logger.warning(
                "ban_user_rate_limited",
                chat_id=chat_id,
                user_id=user_id,
                retry_after=e.retry_after,
            )
            return ActionResult(
                action="ban",
                success=False,
                error=f"Rate limited, retry after {e.retry_after}s",
            )

        except TelegramBadRequest as e:
            error_msg = str(e).lower()
            if "user is an administrator" in error_msg:
                logger.info(
                    "ban_user_is_admin",
                    chat_id=chat_id,
                    user_id=user_id,
                )
                return ActionResult(
                    action="ban",
                    success=False,
                    error="Cannot ban administrator",
                )
            if "user not found" in error_msg:
                return ActionResult(
                    action="ban",
                    success=False,
                    error="User not found in chat",
                )
            logger.warning(
                "ban_user_bad_request",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
            )
            return ActionResult(
                action="ban",
                success=False,
                error=str(e),
            )

        except TelegramForbiddenError as e:
            logger.warning(
                "ban_user_forbidden",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
            )
            return ActionResult(
                action="ban",
                success=False,
                error="Bot lacks ban permission",
            )

        except TelegramNotFound:
            return ActionResult(
                action="ban",
                success=False,
                error="Chat not found",
            )

        except TelegramAPIError as e:
            logger.error(
                "ban_user_api_error",
                chat_id=chat_id,
                user_id=user_id,
                error=str(e),
            )
            return ActionResult(
                action="ban",
                success=False,
                error=str(e),
            )

    async def notify_admins(
        self,
        chat_id: int,
        risk_result: RiskResult,
        message: Message,
    ) -> ActionResult:
        """
        Send alert to group admins with inline action buttons.

        Rate-limited to prevent notification spam. Uses atomic lock acquisition
        to prevent race conditions where multiple requests could bypass rate limiting.

        Args:
            chat_id: Telegram chat ID.
            risk_result: The risk calculation result.
            message: Original message object.

        Returns:
            ActionResult indicating success/failure.
        """
        # Atomically acquire rate limit lock - prevents TOCTOU race condition
        if not await self._acquire_admin_notify_lock(chat_id):
            logger.debug(
                "admin_notify_rate_limited",
                chat_id=chat_id,
            )
            return ActionResult(
                action="notify_admins",
                success=True,  # Not an error - intentionally skipped
                details={"skipped": True, "reason": "rate_limited"},
            )

        try:
            # Build notification message
            user = message.from_user
            username_display = (
                f"@{user.username}"
                if user and user.username
                else f"ID: {user.id}"
                if user
                else "Unknown"
            )
            user_id = user.id if user else 0

            # Truncate message preview
            text_preview = message.text or message.caption or "(no text)"
            if len(text_preview) > MAX_MESSAGE_PREVIEW:
                text_preview = text_preview[:MAX_MESSAGE_PREVIEW] + "..."

            # Generate message hash for feedback tracking
            message_hash = hashlib.md5(
                f"{chat_id}:{message.message_id}:{text_preview[:50]}".encode()
            ).hexdigest()[:12]

            # Format contributing factors
            factors_text = ""
            for factor in risk_result.contributing_factors[:5]:
                factors_text += f"  - {factor}\n"

            # Build alert text (using plain formatting to avoid escaping issues)
            alert_text = (
                f"Spam Detected\n\n"
                f"User: {username_display} (ID: {user_id})\n"
                f"Score: {risk_result.score}/100 [{risk_result.verdict.value.upper()}]\n"
                f"Threat: {risk_result.threat_type.value}\n\n"
                f'Message preview:\n"{text_preview}"\n\n'
                f"Contributing factors:\n{factors_text}"
            )

            # Build inline keyboard with feedback buttons for spam detection improvement
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Confirm Spam",
                            callback_data=f"feedback:confirm:{message_hash}:{chat_id}",
                        ),
                        InlineKeyboardButton(
                            text="❌ False Positive",
                            callback_data=f"feedback:fp:{message_hash}:{chat_id}:{user_id}",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="🔨 Ban User",
                            callback_data=f"review:ban:{user_id}:{chat_id}",
                        ),
                        InlineKeyboardButton(
                            text="🔓 Restore",
                            callback_data=f"confirm:unban:{user_id}:{chat_id}",
                        ),
                    ],
                ]
            )

            # Get admin list and notify
            admins = await asyncio.wait_for(
                self.bot.get_chat_administrators(chat_id),
                timeout=TELEGRAM_API_TIMEOUT,
            )

            notified_count = 0
            for admin in admins:
                if admin.user.is_bot:
                    continue

                try:
                    await asyncio.wait_for(
                        self.bot.send_message(
                            chat_id=admin.user.id,
                            text=alert_text,
                            reply_markup=keyboard,
                        ),
                        timeout=TELEGRAM_API_TIMEOUT,
                    )
                    notified_count += 1
                    # Stop after first successful notification
                    break
                except TelegramForbiddenError:
                    # Admin hasn't started conversation with bot
                    continue
                except TelegramAPIError:
                    continue

            # Note: Rate limit lock was already acquired atomically at the start
            # No need to mark as sent - the lock acquisition handles this

            return ActionResult(
                action="notify_admins",
                success=notified_count > 0,
                details={"admins_notified": notified_count},
            )

        except TimeoutError:
            logger.warning(
                "notify_admins_timeout",
                chat_id=chat_id,
            )
            return ActionResult(
                action="notify_admins",
                success=False,
                error="Telegram API timeout",
            )

        except TelegramForbiddenError as e:
            # Bot was removed from the chat
            logger.warning(
                "notify_admins_forbidden",
                chat_id=chat_id,
                error=str(e),
            )
            return ActionResult(
                action="notify_admins",
                success=False,
                error="Bot removed from chat",
            )

        except TelegramAPIError as e:
            logger.error(
                "notify_admins_api_error",
                chat_id=chat_id,
                error=str(e),
            )
            return ActionResult(
                action="notify_admins",
                success=False,
                error=str(e),
            )

    async def queue_for_review(
        self,
        risk_result: RiskResult,
        message: Message,
    ) -> ActionResult:
        """
        Add message to admin review queue.

        Stores the message details for later review via Mini App or
        callback queries.

        Args:
            risk_result: The risk calculation result.
            message: Original message object.

        Returns:
            ActionResult indicating success/failure.
        """
        if not self.cache:
            return ActionResult(
                action="queue_review",
                success=False,
                error="Cache service not available",
            )

        try:
            chat_id = message.chat.id
            user_id = message.from_user.id if message.from_user else 0
            message_id = message.message_id

            # Build review item
            review_item = {
                "chat_id": chat_id,
                "user_id": user_id,
                "message_id": message_id,
                "score": risk_result.score,
                "verdict": risk_result.verdict.value,
                "threat_type": risk_result.threat_type.value,
                "contributing_factors": risk_result.contributing_factors[:5],
                "text": (message.text or message.caption or "")[:500],
                "created_at": datetime.now(UTC).isoformat(),
            }

            # Store in Redis list for the group
            review_key = f"saqshy:review_queue:{chat_id}"
            await self.cache.set_json(
                f"saqshy:review:{chat_id}:{message_id}",
                review_item,
                ttl=86400 * 7,  # Keep for 7 days
            )

            return ActionResult(
                action="queue_review",
                success=True,
                details={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "queue_key": review_key,
                },
            )

        except Exception as e:
            logger.error(
                "queue_for_review_error",
                error=str(e),
            )
            return ActionResult(
                action="queue_review",
                success=False,
                error=str(e),
            )

    async def log_decision(
        self,
        risk_result: RiskResult,
        message: Message,
        actions_taken: list[str],
    ) -> None:
        """
        Log decision to database.

        Records the complete decision including risk result,
        signals, and action outcomes for analytics and audit.

        Args:
            risk_result: The risk calculation result.
            message: Original message object.
            actions_taken: List of actions that were executed.
        """
        if not self.db_session:
            logger.debug("log_decision_no_db_session")
            return

        try:
            from saqshy.db.repositories.decisions import DecisionRepository

            repo = DecisionRepository(self.db_session)

            chat_id = message.chat.id
            user_id = message.from_user.id if message.from_user else 0
            message_id = message.message_id

            # Verdict enum is the same in core/types (canonical source)
            # and db/models (re-exports), so use directly
            await repo.create_decision(
                group_id=chat_id,
                user_id=user_id,
                message_id=message_id,
                risk_score=risk_result.score,
                verdict=risk_result.verdict,
                threat_type=risk_result.threat_type.value
                if risk_result.threat_type != ThreatType.NONE
                else None,
                profile_signals=risk_result.signals.profile.__dict__
                if hasattr(risk_result.signals, "profile")
                else {},
                content_signals=risk_result.signals.content.__dict__
                if hasattr(risk_result.signals, "content")
                else {},
                behavior_signals=risk_result.signals.behavior.__dict__
                if hasattr(risk_result.signals, "behavior")
                else {},
                llm_used=risk_result.needs_llm,
                llm_response={"explanation": risk_result.llm_explanation}
                if risk_result.llm_explanation
                else None,
                action_taken=",".join(actions_taken),
                message_deleted="delete" in actions_taken,
                user_banned="ban" in actions_taken,
                user_restricted="restrict" in actions_taken or "hold" in actions_taken,
            )

            await self.db_session.commit()

        except Exception as e:
            logger.error(
                "log_decision_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            # Don't raise - logging should not break the flow

    # =========================================================================
    # Helper Methods for Verdict-Based Decision Making
    # =========================================================================

    def should_delete_message(self, verdict: Verdict) -> bool:
        """Check if message should be deleted for this verdict."""
        return "delete" in VERDICT_ACTIONS.get(verdict, [])

    def should_restrict_user(self, verdict: Verdict) -> bool:
        """Check if user should be restricted for this verdict."""
        actions = VERDICT_ACTIONS.get(verdict, [])
        return "restrict" in actions or "hold" in actions

    def should_ban_user(self, verdict: Verdict) -> bool:
        """Check if user should be banned for this verdict."""
        return "ban" in VERDICT_ACTIONS.get(verdict, [])

    def should_notify_admins(self, verdict: Verdict) -> bool:
        """Check if admins should be notified for this verdict."""
        return "notify_admins" in VERDICT_ACTIONS.get(verdict, [])

    # =========================================================================
    # Duration Calculators
    # =========================================================================

    def _calculate_restrict_duration(self, result: RiskResult) -> int:
        """Calculate restriction duration based on risk severity."""
        if result.score >= 80:
            return self.config.restrict_duration_long
        elif result.score >= 60:
            return self.config.restrict_duration_medium
        else:
            return self.config.restrict_duration_short

    def _calculate_ban_duration(self, result: RiskResult) -> int | None:
        """Calculate ban duration based on risk severity."""
        # Very high confidence spam - permanent ban
        if result.score >= 95:
            return self.config.ban_duration_permanent

        # High confidence - temporary but long ban
        if result.score >= 85:
            return self.config.ban_duration_temp

        # Lower scores get shorter temp bans
        return 86400 * 7  # 7 days

    # =========================================================================
    # Retry Logic
    # =========================================================================

    async def _telegram_api_with_retry(
        self,
        operation: Callable[[], Awaitable[T]],
        operation_name: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    ) -> T:
        """
        Execute Telegram API call with exponential backoff retry.

        Retries on transient errors (network errors, timeouts, rate limits)
        but fails immediately on non-retryable errors (forbidden, bad request).

        Args:
            operation: Async callable to execute.
            operation_name: Name for logging purposes.
            max_retries: Maximum number of retry attempts.
            base_delay: Base delay in seconds for exponential backoff.

        Returns:
            Result of the operation.

        Raises:
            The last error encountered after all retries are exhausted,
            or immediately for non-retryable errors.
        """
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                return await operation()

            except NON_RETRYABLE_ERRORS as e:
                # Don't retry permission/client errors - they won't change
                logger.debug(
                    "telegram_api_non_retryable_error",
                    operation=operation_name,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                raise

            except TelegramRetryAfter as e:
                # Respect Telegram's rate limit
                if attempt < max_retries - 1:
                    wait_time = e.retry_after
                    logger.warning(
                        "telegram_api_rate_limited",
                        operation=operation_name,
                        attempt=attempt + 1,
                        retry_after=wait_time,
                    )
                    await asyncio.sleep(wait_time)
                    last_error = e
                else:
                    raise

            except (TelegramNetworkError, TelegramAPIError, TimeoutError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        "telegram_api_retry",
                        operation=operation_name,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay=delay,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "telegram_api_retries_exhausted",
                        operation=operation_name,
                        max_retries=max_retries,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    raise

        # Should not reach here, but if we do, raise the last error
        if last_error:
            raise last_error
        raise RuntimeError(f"Unexpected state in retry loop for {operation_name}")

    # =========================================================================
    # Idempotency
    # =========================================================================

    def _compute_idempotency_key(self, chat_id: int, message_id: int) -> str:
        """Compute idempotency key for a message action."""
        data = f"{chat_id}:{message_id}"
        return f"saqshy:action:{hashlib.md5(data.encode()).hexdigest()}"

    async def _check_already_processed(self, key: str) -> bool:
        """Check if this message was already processed."""
        if not self.cache:
            return False
        return await self.cache.exists(key)

    async def _mark_as_processed(self, key: str) -> None:
        """Mark a message as processed for idempotency."""
        if not self.cache:
            return
        await self.cache.set(key, "1", ttl=IDEMPOTENCY_TTL)

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    async def _acquire_admin_notify_lock(self, chat_id: int) -> bool:
        """
        Atomically acquire admin notification lock.

        Uses SET NX (set if not exists) with TTL to prevent race conditions.
        This is an atomic check-and-set operation that prevents the TOCTOU
        vulnerability in the previous check-then-mark approach.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            True if lock was acquired (notification allowed).
            False if lock already exists (rate limited).
        """
        if not self.cache:
            # No cache means no rate limiting - allow notification
            return True

        lock_key = f"saqshy:admin_notify_lock:{chat_id}"

        # Atomic SET NX with TTL - only succeeds if key doesn't exist
        # This prevents race condition where multiple requests could
        # pass the check before any marks the notification as sent
        try:
            acquired = await self.cache.set_nx(
                lock_key,
                "1",
                ttl=self.config.admin_notify_rate_limit,
            )
            return acquired
        except AttributeError:
            # Fallback if cache doesn't support set_nx - use regular set
            # This is less safe but maintains backward compatibility
            logger.warning(
                "cache_set_nx_not_available",
                fallback="using_exists_then_set",
            )
            return await self._check_admin_notify_allowed_fallback(chat_id)

    async def _check_admin_notify_allowed_fallback(self, chat_id: int) -> bool:
        """
        Fallback rate limit check for caches without atomic SET NX.

        WARNING: TOCTOU Race Condition
        This method has a small race window between exists() and set().
        Multiple concurrent calls may both pass the exists() check before
        either sets the key. This is acceptable for rate limiting admin
        notifications where occasional duplicate sends are tolerable.

        For production, prefer _acquire_admin_notify_lock() which uses
        atomic SET NX.
        """
        if not self.cache:
            return True

        key = f"saqshy:admin_notify_lock:{chat_id}"
        exists = await self.cache.exists(key)
        if exists:
            return False

        # Mark as sent - there's a small TOCTOU race window here
        # This is logged at debug level since the race is expected and tolerable
        logger.debug(
            "admin_notify_fallback_race_window",
            chat_id=chat_id,
            info="Using non-atomic fallback, small race window possible",
        )
        await self.cache.set(key, "1", ttl=self.config.admin_notify_rate_limit)
        return True


# =============================================================================
# Safe Fallback Executor
# =============================================================================


async def execute_with_fallback(
    engine: ActionEngine,
    risk_result: RiskResult,
    message: Message,
) -> ExecutionResult:
    """
    Execute actions with safe fallback chain.

    If primary actions fail, falls back to simpler actions:
    - If delete fails -> try restrict
    - If restrict fails -> notify admins only
    - If notify fails -> log to database
    - Always try to log decision

    Args:
        engine: ActionEngine instance.
        risk_result: The risk calculation result.
        message: Original message object.

    Returns:
        ExecutionResult with all action outcomes.
    """
    result = await engine.execute(risk_result, message)

    # Check if primary action failed and apply fallbacks
    if risk_result.verdict == Verdict.BLOCK:
        if not result.message_deleted:
            # Fallback: try to restrict user instead
            chat_id = message.chat.id
            user_id = message.from_user.id if message.from_user else 0

            restrict_result = await engine.restrict_user(
                chat_id,
                user_id,
                duration=86400 * 7,  # 7 days
                preset="hard",
            )
            result.actions_attempted.append(restrict_result)

            if restrict_result.success:
                result.user_restricted = True

        if not result.message_deleted and not result.user_banned and not result.user_restricted and not result.admins_notified:
            # Ultimate fallback: if we couldn't delete, ban, or restrict, at least notify admins
            # This ensures admins are aware of BLOCK-level messages that we failed to handle
            chat_id = message.chat.id
            notify_result = await engine.notify_admins(
                chat_id,
                risk_result,
                message,
            )
            result.actions_attempted.append(notify_result)
            result.admins_notified = notify_result.success

    # Always try to log if not already logged
    if not result.logged:
        await engine.log_decision(
            risk_result,
            message,
            [a.action for a in result.actions_attempted if a.success],
        )
        result.logged = True

    return result
