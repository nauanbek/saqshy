"""
SAQSHY Telegram Restrictions Adapter

Implements ChatRestrictionsProtocol from core.protocols.
Wraps aiogram Bot to apply/remove chat member restrictions.

This adapter isolates all aiogram-specific exception handling,
keeping the core/ module free of external dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import ChatPermissions

from saqshy.core.protocols import ChatRestrictionsProtocol, TelegramOperationError

if TYPE_CHECKING:
    from aiogram import Bot

logger = structlog.get_logger(__name__)


class TelegramRestrictionsAdapter(ChatRestrictionsProtocol):
    """
    Implements restriction management via aiogram Bot.

    This adapter:
    - Applies sandbox restrictions (limited permissions)
    - Removes restrictions when user is released
    - Translates aiogram exceptions to TelegramOperationError
    - Logs all operations with context

    Thread Safety:
        This class is thread-safe when used with asyncio.

    Example:
        >>> from aiogram import Bot
        >>> bot = Bot(token="...")
        >>> adapter = TelegramRestrictionsAdapter(bot)
        >>> await adapter.apply_sandbox_restrictions(user_id=123, chat_id=-456)
    """

    # Sandbox permissions: text only, no media/links/forwards
    SANDBOX_PERMISSIONS = ChatPermissions(
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
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )

    # Full permissions: restore all messaging capabilities
    FULL_PERMISSIONS = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,  # Admin-only
        can_invite_users=True,
        can_pin_messages=False,  # Admin-only
        can_manage_topics=False,  # Admin-only
    )

    def __init__(self, bot: Bot) -> None:
        """
        Initialize the adapter.

        Args:
            bot: aiogram Bot instance for Telegram API calls.
        """
        self._bot = bot

    async def apply_sandbox_restrictions(
        self,
        user_id: int,
        chat_id: int,
    ) -> bool:
        """
        Apply sandbox restrictions to a user.

        Restricts user to text-only messages:
        - No media (photos, videos, documents)
        - No links/web previews
        - No forwards
        - No stickers/GIFs

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            True if restrictions applied successfully.

        Raises:
            TelegramOperationError: On Telegram API failure.
        """
        log = logger.bind(user_id=user_id, chat_id=chat_id)

        try:
            await self._bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=self.SANDBOX_PERMISSIONS,
            )

            log.info("sandbox_restrictions_applied")
            return True

        except TelegramRetryAfter as e:
            log.warning(
                "apply_restrictions_rate_limited",
                retry_after=e.retry_after,
            )
            raise TelegramOperationError(
                message=str(e),
                error_type="rate_limit",
                retry_after=e.retry_after,
            ) from e

        except TelegramForbiddenError as e:
            log.warning(
                "apply_restrictions_no_permission",
                error=str(e),
            )
            raise TelegramOperationError(
                message=str(e),
                error_type="forbidden",
            ) from e

        except TelegramBadRequest as e:
            log.error(
                "apply_restrictions_bad_request",
                error=str(e),
            )
            raise TelegramOperationError(
                message=str(e),
                error_type="bad_request",
            ) from e

        except TelegramNetworkError as e:
            log.error(
                "apply_restrictions_network_error",
                error=str(e),
            )
            raise TelegramOperationError(
                message=str(e),
                error_type="network",
            ) from e

        except TelegramAPIError as e:
            log.error(
                "apply_restrictions_api_error",
                error=str(e),
            )
            raise TelegramOperationError(
                message=str(e),
                error_type="api",
            ) from e

    async def remove_sandbox_restrictions(
        self,
        user_id: int,
        chat_id: int,
    ) -> bool:
        """
        Remove restrictions when user is released from sandbox.

        Restores full messaging permissions:
        - Can send all media types
        - Can add links/web previews
        - Can forward messages
        - Can use stickers/GIFs

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            True if restrictions removed successfully.

        Raises:
            TelegramOperationError: On Telegram API failure.
        """
        log = logger.bind(user_id=user_id, chat_id=chat_id)

        try:
            await self._bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=self.FULL_PERMISSIONS,
            )

            log.info("sandbox_restrictions_removed")
            return True

        except TelegramRetryAfter as e:
            log.warning(
                "remove_restrictions_rate_limited",
                retry_after=e.retry_after,
            )
            raise TelegramOperationError(
                message=str(e),
                error_type="rate_limit",
                retry_after=e.retry_after,
            ) from e

        except TelegramForbiddenError as e:
            log.warning(
                "remove_restrictions_no_permission",
                error=str(e),
            )
            raise TelegramOperationError(
                message=str(e),
                error_type="forbidden",
            ) from e

        except TelegramBadRequest as e:
            log.error(
                "remove_restrictions_bad_request",
                error=str(e),
            )
            raise TelegramOperationError(
                message=str(e),
                error_type="bad_request",
            ) from e

        except TelegramNetworkError as e:
            log.error(
                "remove_restrictions_network_error",
                error=str(e),
            )
            raise TelegramOperationError(
                message=str(e),
                error_type="network",
            ) from e

        except TelegramAPIError as e:
            log.error(
                "remove_restrictions_api_error",
                error=str(e),
            )
            raise TelegramOperationError(
                message=str(e),
                error_type="api",
            ) from e


# For graceful degradation - returns False instead of raising
class SafeTelegramRestrictionsAdapter(TelegramRestrictionsAdapter):
    """
    Safe version that catches exceptions and returns False.

    Use this when you want fail-open behavior (e.g., in sandbox manager
    where failing to apply restrictions shouldn't block the message).
    """

    async def apply_sandbox_restrictions(
        self,
        user_id: int,
        chat_id: int,
    ) -> bool:
        """Apply restrictions, return False on any error."""
        try:
            return await super().apply_sandbox_restrictions(user_id, chat_id)
        except TelegramOperationError:
            return False

    async def remove_sandbox_restrictions(
        self,
        user_id: int,
        chat_id: int,
    ) -> bool:
        """Remove restrictions, return False on any error."""
        try:
            return await super().remove_sandbox_restrictions(user_id, chat_id)
        except TelegramOperationError:
            return False


__all__ = [
    "TelegramRestrictionsAdapter",
    "SafeTelegramRestrictionsAdapter",
]
