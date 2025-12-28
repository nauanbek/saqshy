"""
SAQSHY Message Handlers

Handles incoming messages and processes them through the spam detection pipeline.

Pipeline Flow:
1. PARSE: Extract MessageContext from aiogram Message
2. ANALYZE: Run analyzers in parallel (Profile, Content, Behavior, SpamDB)
3. DECIDE: Calculate risk score and determine verdict
4. ACT: Execute action based on verdict (delete, restrict, review, etc.)
5. LOG: Record decision for analytics and feedback

Performance Target: <200ms for non-LLM path

Error Handling:
- All exceptions are caught and logged
- Never crash on message processing
- Fail-open on service errors (allow message through)
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import Message

from saqshy.bot.action_engine import ActionEngine
from saqshy.bot.pipeline import MessagePipeline, create_pipeline
from saqshy.core.types import (
    GroupType,
    MessageContext,
    RiskResult,
    Verdict,
)

if TYPE_CHECKING:
    from saqshy.core.audit import AuditTrail
    from saqshy.core.metrics import MetricsCollector
    from saqshy.services.cache import CacheService
    from saqshy.services.channel_subscription import ChannelSubscriptionService
    from saqshy.services.llm import LLMService
    from saqshy.services.spam_db import SpamDB

logger = structlog.get_logger(__name__)

router = Router(name="messages")

# Timeout for the entire pipeline (excluding LLM)
PIPELINE_TIMEOUT_SECONDS = 5.0

# Timeout for Telegram API operations
TELEGRAM_API_TIMEOUT_SECONDS = 30.0


# =============================================================================
# Main Message Handler
# =============================================================================


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(
    message: Message,
    bot: Bot,
    cache_service: CacheService | None = None,
    spam_db: SpamDB | None = None,
    channel_subscription_service: ChannelSubscriptionService | None = None,
    llm_service: LLMService | None = None,
    metrics_collector: MetricsCollector | None = None,
    audit_trail: AuditTrail | None = None,
    correlation_id: str | None = None,
    user_is_admin: bool = False,
    user_is_whitelisted: bool = False,
    message_pipeline: MessagePipeline | None = None,
) -> None:
    """
    Handle incoming group messages through the spam detection pipeline.

    This is the main entry point for spam detection. Processes messages
    through the full MessagePipeline which includes:
    - Parallel analyzer execution with circuit breakers
    - Decision caching for repeated messages
    - LLM gray zone handling (60-80 score range)
    - Comprehensive metrics and audit trail
    - Backpressure handling via pipeline-level circuit breaker

    Args:
        message: Incoming Telegram message.
        bot: Bot instance for API calls.
        cache_service: Redis cache service (injected by middleware).
        spam_db: SpamDB service (injected via workflow_data).
        channel_subscription_service: Channel subscription checker.
        llm_service: LLM service for gray zone decisions.
        metrics_collector: Metrics collector for observability.
        audit_trail: Audit trail for decision logging.
        correlation_id: Request correlation ID for tracing.
        user_is_admin: Whether user is a group admin (from AuthMiddleware).
        user_is_whitelisted: Whether user is whitelisted (from AuthMiddleware).
        message_pipeline: Optional shared pipeline instance for backpressure handling.
            If provided, uses the shared pipeline's circuit breaker and semaphore.
            If not provided, creates a new pipeline per message (no shared backpressure).
    """
    start_time = time.perf_counter()

    # PARSE: Validate and extract context
    if not _should_process_message(message, user_is_admin, user_is_whitelisted):
        return

    log = logger.bind(
        message_id=message.message_id,
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else None,
        correlation_id=correlation_id,
    )

    # Check pipeline backpressure if shared pipeline is provided
    if message_pipeline is not None and not message_pipeline.circuit_breaker.allow_request():
        log.warning(
            "backpressure_skip",
            circuit_state=message_pipeline.circuit_breaker.state,
            active_requests=message_pipeline.active_requests,
        )
        # Fail-open: allow message through but don't process
        return

    try:
        # Build message context
        context = await build_message_context(message, cache_service)

        # Record message timestamp for TTFM calculation
        if cache_service and message.from_user:
            await _record_message_timestamp(
                cache_service,
                message.from_user.id,
                message.chat.id,
                context.timestamp,
            )

        # Get linked channel ID and admin IDs for pipeline
        linked_channel_id: int | None = None
        admin_ids: set[int] | None = None
        if cache_service:
            # Get linked channel ID
            channel_setting = await cache_service.get(f"linked_channel:{context.chat_id}")
            if channel_setting:
                try:
                    linked_channel_id = int(channel_setting)
                except ValueError:
                    pass

            # Get admin IDs
            cached_admins = await cache_service.get(f"group_admins:{context.chat_id}")
            if cached_admins:
                try:
                    admin_ids = set(int(x) for x in cached_admins.split(",") if x)
                except ValueError:
                    pass

        # Use shared pipeline if provided (for backpressure), otherwise create new one
        # Shared pipeline provides:
        # - Pipeline-level circuit breaker for backpressure
        # - Semaphore for concurrent request limiting
        # - Queue depth monitoring
        # Per-message pipeline provides:
        # - Circuit breakers for fault tolerance
        # - Decision caching to avoid redundant computation
        # - LLM integration for gray zone (60-80 score)
        # - Metrics collection and audit trail
        pipeline = message_pipeline or create_pipeline(
            group_type=context.group_type.value,
            cache_service=cache_service,
            spam_db=spam_db,
            channel_subscription_service=channel_subscription_service,
            llm_service=llm_service,
            metrics_collector=metrics_collector,
            audit_trail=audit_trail,
        )

        # ANALYZE + DECIDE: Process through full pipeline
        result = await pipeline.process(
            context=context,
            linked_channel_id=linked_channel_id,
            admin_ids=admin_ids,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        log.info(
            "pipeline_completed",
            score=result.score,
            verdict=result.verdict.value,
            threat_type=result.threat_type.value,
            profile_score=result.profile_score,
            content_score=result.content_score,
            behavior_score=result.behavior_score,
            network_score=result.network_score,
            needs_llm=result.needs_llm,
            elapsed_ms=round(elapsed_ms, 2),
        )

        # ACT: Execute action based on verdict
        if result.verdict != Verdict.ALLOW:
            await _execute_action(
                message=message,
                bot=bot,
                result=result,
                context=context,
                cache_service=cache_service,
                log=log,
            )

        # Record decision in cache for user stats
        if cache_service and message.from_user:
            await cache_service.record_decision(
                user_id=message.from_user.id,
                chat_id=message.chat.id,
                verdict=result.verdict.value,
            )

    except TimeoutError:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        log.warning(
            "pipeline_timeout",
            elapsed_ms=round(elapsed_ms, 2),
            timeout=PIPELINE_TIMEOUT_SECONDS,
        )
        # Fail-open: allow message through on timeout

    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        log.error(
            "pipeline_error",
            error=str(e),
            error_type=type(e).__name__,
            elapsed_ms=round(elapsed_ms, 2),
        )
        # Fail-open: allow message through on error


def _should_process_message(
    message: Message,
    user_is_admin: bool,
    user_is_whitelisted: bool,
) -> bool:
    """
    Check if message should be processed through spam detection.

    Returns:
        True if message should be processed.
    """
    # Skip if no user (system messages)
    if not message.from_user:
        return False

    # Skip messages from bots
    if message.from_user.is_bot:
        return False

    # Skip messages from admins (they are trusted)
    if user_is_admin:
        return False

    # Skip messages from whitelisted users
    if user_is_whitelisted:
        return False

    # Skip empty messages (no text or caption)
    if not message.text and not message.caption:
        return False

    return True


async def build_message_context(
    message: Message,
    cache_service: CacheService | None = None,
) -> MessageContext:
    """
    Build MessageContext from Telegram message.

    Extracts all relevant information from the message for analysis.

    Args:
        message: Telegram message object.
        cache_service: Optional cache service for group settings lookup.

    Returns:
        MessageContext with all relevant information.
    """
    user = message.from_user
    chat = message.chat

    # Determine group type from cache or default to GENERAL
    group_type = GroupType.GENERAL
    if cache_service:
        group_settings = await cache_service.get_json(f"group_settings:{chat.id}")
        if group_settings and "group_type" in group_settings:
            try:
                group_type = GroupType(group_settings["group_type"])
            except ValueError:
                pass

    # Extract media type
    media_type = None
    has_media = False
    if message.photo:
        has_media = True
        media_type = "photo"
    elif message.video:
        has_media = True
        media_type = "video"
    elif message.document:
        has_media = True
        media_type = "document"
    elif message.audio:
        has_media = True
        media_type = "audio"
    elif message.voice:
        has_media = True
        media_type = "voice"
    elif message.sticker:
        has_media = True
        media_type = "sticker"

    # Build raw dicts for detailed analysis
    raw_user: dict[str, Any] = {}
    if user:
        raw_user = {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_bot": user.is_bot,
            "is_premium": user.is_premium,
            "language_code": user.language_code,
        }

    raw_message: dict[str, Any] = {
        "message_id": message.message_id,
        "date": message.date.isoformat() if message.date else None,
    }

    # Add reply info if present
    if message.reply_to_message:
        raw_message["reply_to_message"] = {
            "message_id": message.reply_to_message.message_id,
            "from": {
                "id": message.reply_to_message.from_user.id,
                "username": message.reply_to_message.from_user.username,
            }
            if message.reply_to_message.from_user
            else {},
        }

    # Add forward info if present
    if message.forward_from_chat:
        raw_message["forward_from_chat"] = {
            "id": message.forward_from_chat.id,
            "type": message.forward_from_chat.type,
            "title": message.forward_from_chat.title,
        }

    return MessageContext(
        message_id=message.message_id,
        chat_id=chat.id,
        user_id=user.id if user else 0,
        text=message.text or message.caption,
        timestamp=message.date.replace(tzinfo=UTC) if message.date else datetime.now(UTC),
        username=user.username if user else None,
        first_name=user.first_name if user else None,
        last_name=user.last_name if user else None,
        is_bot=user.is_bot if user else False,
        is_premium=user.is_premium if user else False,
        chat_type=chat.type,
        chat_title=chat.title,
        group_type=group_type,
        has_media=has_media,
        media_type=media_type,
        is_forward=bool(message.forward_date),
        forward_from_chat_id=message.forward_from_chat.id if message.forward_from_chat else None,
        reply_to_message_id=message.reply_to_message.message_id
        if message.reply_to_message
        else None,
        raw_message=raw_message,
        raw_user=raw_user,
        raw_chat={"id": chat.id, "type": chat.type, "title": chat.title},
    )


async def _record_message_timestamp(
    cache_service: CacheService,
    user_id: int,
    chat_id: int,
    timestamp: datetime,
) -> None:
    """Record message timestamp for behavior analysis."""
    try:
        await cache_service.record_message(user_id, chat_id, timestamp)
    except TimeoutError:
        logger.warning(
            "record_message_timeout",
            user_id=user_id,
            chat_id=chat_id,
        )
    except ConnectionError as e:
        logger.warning(
            "record_message_connection_error",
            user_id=user_id,
            chat_id=chat_id,
            error=str(e),
        )
    except Exception as e:
        logger.warning(
            "record_message_unexpected_error",
            user_id=user_id,
            chat_id=chat_id,
            error=str(e),
            error_type=type(e).__name__,
        )


# =============================================================================
# Action Execution
# =============================================================================


async def _execute_action(
    message: Message,
    bot: Bot,
    result: RiskResult,
    context: MessageContext,
    cache_service: CacheService | None,
    log: Any,
) -> None:
    """
    Execute action based on risk verdict.

    Uses ActionEngine for consistent action execution with:
    - Timeout handling and proper error recovery
    - Idempotency to prevent duplicate actions
    - Logging of all decisions and outcomes

    Args:
        message: Original Telegram message.
        bot: Bot instance for API calls.
        result: Risk calculation result.
        context: Message context.
        cache_service: Redis cache service.
        log: Bound logger with context.
    """
    action_engine = ActionEngine(
        bot=bot,
        cache_service=cache_service,
        group_type=context.group_type,
    )

    try:
        # Execute actions through ActionEngine
        execution_result = await action_engine.execute(
            risk_result=result,
            message=message,
        )

        # Count failed actions
        failed_count = sum(
            1 for a in execution_result.actions_attempted if not a.success
        )

        log.info(
            "action_executed",
            message_deleted=execution_result.message_deleted,
            user_restricted=execution_result.user_restricted,
            user_banned=execution_result.user_banned,
            admins_notified=execution_result.admins_notified,
            failed_actions=failed_count,
        )

        # Send to review queue if needed (REVIEW verdict gets special handling)
        if result.verdict == Verdict.REVIEW:
            await _send_to_review_queue(
                bot=bot,
                message=message,
                result=result,
                context=context,
                cache_service=cache_service,
                log=log,
            )

    except asyncio.CancelledError:
        log.warning("action_execution_cancelled")
        raise
    except TelegramAPIError as e:
        log.error(
            "action_execution_telegram_error",
            error=str(e),
            error_type=type(e).__name__,
        )
    except Exception as e:
        log.error(
            "action_execution_unexpected_error",
            error=str(e),
            error_type=type(e).__name__,
        )


async def _safe_delete_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    log: Any,
) -> bool:
    """
    Safely delete a message with timeout and error handling.

    Returns:
        True if message was deleted.
    """
    try:
        await asyncio.wait_for(
            bot.delete_message(chat_id=chat_id, message_id=message_id),
            timeout=TELEGRAM_API_TIMEOUT_SECONDS,
        )
        return True

    except TimeoutError:
        log.warning("delete_message_timeout", message_id=message_id)
        return False

    except TelegramRetryAfter as e:
        log.warning("delete_message_rate_limited", retry_after=e.retry_after)
        # Don't retry here - let it go
        return False

    except TelegramBadRequest as e:
        # Message already deleted or not found
        if "message to delete not found" in str(e).lower():
            return True
        log.warning("delete_message_bad_request", error=str(e))
        return False

    except TelegramForbiddenError as e:
        log.warning(
            "delete_message_forbidden",
            message_id=message_id,
            error=str(e),
        )
        return False

    except TelegramNetworkError as e:
        log.warning(
            "delete_message_network_error",
            message_id=message_id,
            error=str(e),
        )
        return False

    except Exception as e:
        log.error(
            "delete_message_unexpected_error",
            message_id=message_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


async def _safe_restrict_user(
    bot: Bot,
    chat_id: int,
    user_id: int,
    duration_seconds: int | None,
    log: Any,
) -> bool:
    """
    Safely restrict a user with timeout and error handling.

    Returns:
        True if user was restricted.
    """
    from aiogram.types import ChatPermissions

    try:
        # Calculate until_date
        until_date = None
        if duration_seconds:
            until_date = datetime.now(UTC).timestamp() + duration_seconds

        await asyncio.wait_for(
            bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                ),
                until_date=int(until_date) if until_date else None,
            ),
            timeout=TELEGRAM_API_TIMEOUT_SECONDS,
        )

        log.info(
            "user_restricted",
            user_id=user_id,
            duration_seconds=duration_seconds,
        )
        return True

    except TimeoutError:
        log.warning("restrict_user_timeout", user_id=user_id)
        return False

    except TelegramRetryAfter as e:
        log.warning("restrict_user_rate_limited", retry_after=e.retry_after)
        return False

    except TelegramBadRequest as e:
        log.warning("restrict_user_bad_request", user_id=user_id, error=str(e))
        return False

    except TelegramForbiddenError as e:
        log.warning(
            "restrict_user_forbidden",
            user_id=user_id,
            error=str(e),
        )
        return False

    except TelegramNetworkError as e:
        log.warning(
            "restrict_user_network_error",
            user_id=user_id,
            error=str(e),
        )
        return False

    except Exception as e:
        log.error(
            "restrict_user_unexpected_error",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


async def _send_to_review_queue(
    bot: Bot,
    message: Message,
    result: RiskResult,
    context: MessageContext,
    cache_service: CacheService | None,
    log: Any,
) -> None:
    """
    Send message to admin review queue.

    Notifies admins about the suspicious message for manual review.
    """
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    # Get admin chat ID for notifications (could be a separate review channel)
    review_chat_id = None
    if cache_service:
        review_chat = await cache_service.get(f"review_chat:{context.chat_id}")
        if review_chat:
            try:
                review_chat_id = int(review_chat)
            except ValueError:
                pass

    if not review_chat_id:
        # Fall back to notifying in the same group (less ideal)
        log.debug("no_review_chat_configured")
        return

    try:
        # Build review message
        user_mention = f"@{context.username}" if context.username else f"User {context.user_id}"
        review_text = (
            f"<b>Review Required</b>\n\n"
            f"<b>User:</b> {user_mention}\n"
            f"<b>Score:</b> {result.score}/100\n"
            f"<b>Verdict:</b> {result.verdict.value.upper()}\n"
            f"<b>Threat:</b> {result.threat_type.value}\n\n"
            f"<b>Factors:</b>\n"
        )

        for factor in result.contributing_factors[:5]:
            review_text += f"- {factor}\n"

        if result.mitigating_factors:
            review_text += "\n<b>Mitigating:</b>\n"
            for factor in result.mitigating_factors[:3]:
                review_text += f"+ {factor}\n"

        review_text += f"\n<b>Message:</b>\n{context.text[:500] if context.text else '(no text)'}"

        # Build inline keyboard for actions
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Approve",
                        callback_data=f"review:approve:{message.message_id}:{context.user_id}",
                    ),
                    InlineKeyboardButton(
                        text="Reject",
                        callback_data=f"review:reject:{message.message_id}:{context.user_id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Ban User",
                        callback_data=f"review:ban:{context.user_id}:{context.chat_id}",
                    ),
                ],
            ]
        )

        await asyncio.wait_for(
            bot.send_message(
                chat_id=review_chat_id,
                text=review_text,
                reply_markup=keyboard,
            ),
            timeout=TELEGRAM_API_TIMEOUT_SECONDS,
        )

        log.info("sent_to_review_queue", review_chat_id=review_chat_id)

    except TimeoutError:
        log.warning(
            "send_to_review_timeout",
            review_chat_id=review_chat_id,
        )

    except TelegramBadRequest as e:
        log.warning(
            "send_to_review_bad_request",
            review_chat_id=review_chat_id,
            error=str(e),
        )

    except TelegramForbiddenError as e:
        log.warning(
            "send_to_review_forbidden",
            review_chat_id=review_chat_id,
            error=str(e),
        )

    except TelegramRetryAfter as e:
        log.warning(
            "send_to_review_rate_limited",
            review_chat_id=review_chat_id,
            retry_after=e.retry_after,
        )

    except TelegramNetworkError as e:
        log.warning(
            "send_to_review_network_error",
            review_chat_id=review_chat_id,
            error=str(e),
        )

    except Exception as e:
        log.error(
            "send_to_review_unexpected_error",
            review_chat_id=review_chat_id,
            error=str(e),
            error_type=type(e).__name__,
        )


# =============================================================================
# Private Message Handler
# =============================================================================


@router.message(F.chat.type == "private")
async def handle_private_message(message: Message) -> None:
    """
    Handle private messages to the bot.

    Shows help/status and links to the Mini App.

    Args:
        message: Incoming private message.
    """
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Add to Group",
                    url="https://t.me/saqshy_bot?startgroup=true",
                ),
            ],
        ]
    )

    await message.answer(
        "<b>SAQSHY Anti-Spam Bot</b>\n\n"
        "AI-powered spam protection for Telegram groups.\n\n"
        "Add me to your group as an admin to start protecting it from spam.\n\n"
        "Use /help to see available commands.",
        reply_markup=keyboard,
    )


# =============================================================================
# Utility Functions
# =============================================================================


def compute_message_hash(text: str) -> str:
    """
    Compute a hash of the message text for caching decisions.

    Args:
        text: Message text.

    Returns:
        SHA256 hash truncated to 16 characters.
    """
    return hashlib.sha256(text.encode()).hexdigest()[:16]
