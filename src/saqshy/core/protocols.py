"""
SAQSHY Core Protocols

Abstract interfaces for dependency injection.
These protocols have ZERO external dependencies - only stdlib typing.

This module defines contracts that allow core/ to depend on abstractions
rather than concrete implementations, enabling:
- Testability (easy mocking)
- Flexibility (swap implementations)
- Architectural purity (core/ stays framework-agnostic)
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass


# =============================================================================
# Logging Protocol
# =============================================================================


@runtime_checkable
class LoggerProtocol(Protocol):
    """
    Abstract logger interface for core module.

    This allows core/ to log without depending on structlog or any
    specific logging library. The concrete implementation is injected
    at application startup.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("user_entered_sandbox", user_id=123)
    """

    @abstractmethod
    def info(self, event: str, **kwargs: Any) -> None:
        """Log an info-level event."""
        ...

    @abstractmethod
    def warning(self, event: str, **kwargs: Any) -> None:
        """Log a warning-level event."""
        ...

    @abstractmethod
    def error(self, event: str, **kwargs: Any) -> None:
        """Log an error-level event."""
        ...

    @abstractmethod
    def debug(self, event: str, **kwargs: Any) -> None:
        """Log a debug-level event."""
        ...

    @abstractmethod
    def bind(self, **kwargs: Any) -> LoggerProtocol:
        """
        Create a new logger with additional context bound.

        Args:
            **kwargs: Context to bind to all future log calls.

        Returns:
            New logger instance with bound context.
        """
        ...


# =============================================================================
# Cache Protocol
# =============================================================================


@runtime_checkable
class CacheProtocol(Protocol):
    """
    Abstract cache interface for state persistence.

    Provides async methods for JSON and string storage with TTL support.
    Used by SandboxManager, TrustManager, etc. for Redis operations.
    """

    @abstractmethod
    async def get_json(self, key: str) -> dict[str, Any] | None:
        """
        Get JSON value from cache.

        Args:
            key: Cache key.

        Returns:
            Parsed JSON as dict, or None if not found.
        """
        ...

    @abstractmethod
    async def set_json(
        self,
        key: str,
        value: dict[str, Any],
        ttl: int,
    ) -> bool:
        """
        Set JSON value in cache with TTL.

        Args:
            key: Cache key.
            value: Dict to serialize and store.
            ttl: Time-to-live in seconds.

        Returns:
            True if set successfully.
        """
        ...

    @abstractmethod
    async def get(self, key: str) -> str | None:
        """
        Get string value from cache.

        Args:
            key: Cache key.

        Returns:
            String value, or None if not found.
        """
        ...

    @abstractmethod
    async def set(
        self,
        key: str,
        value: str,
        ttl: int,
    ) -> bool:
        """
        Set string value in cache with TTL.

        Args:
            key: Cache key.
            value: String to store.
            ttl: Time-to-live in seconds.

        Returns:
            True if set successfully.
        """
        ...


# =============================================================================
# Channel Subscription Protocol
# =============================================================================


@runtime_checkable
class ChannelSubscriptionProtocol(Protocol):
    """
    Abstract interface for channel subscription checks.

    Channel subscription is the STRONGEST trust signal in SAQSHY.
    Users subscribed to a group's linked channel bypass sandbox.
    """

    @abstractmethod
    async def is_subscribed(
        self,
        user_id: int,
        channel_id: int,
    ) -> bool:
        """
        Check if user is subscribed to a channel.

        Args:
            user_id: Telegram user ID.
            channel_id: Telegram channel ID.

        Returns:
            True if user is a member of the channel.
        """
        ...


# =============================================================================
# Chat Restrictions Protocol
# =============================================================================


@runtime_checkable
class ChatRestrictionsProtocol(Protocol):
    """
    Abstract interface for applying Telegram chat restrictions.

    This allows SandboxManager to apply/remove restrictions without
    directly depending on aiogram Bot or Telegram API specifics.
    """

    @abstractmethod
    async def apply_sandbox_restrictions(
        self,
        user_id: int,
        chat_id: int,
    ) -> bool:
        """
        Apply sandbox restrictions to a user.

        Sandbox restrictions typically include:
        - Cannot send media
        - Cannot send links
        - Cannot forward messages
        - Cannot add web page previews

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            True if restrictions applied successfully.
        """
        ...

    @abstractmethod
    async def remove_sandbox_restrictions(
        self,
        user_id: int,
        chat_id: int,
    ) -> bool:
        """
        Remove restrictions when user is released from sandbox.

        Restores full messaging permissions to the user.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.

        Returns:
            True if restrictions removed successfully.
        """
        ...


# =============================================================================
# Exception Types
# =============================================================================


class TelegramOperationError(Exception):
    """
    Abstract error for Telegram operations.

    This replaces direct aiogram exception dependencies in core/.
    The adapter layer translates aiogram exceptions to this type.

    Attributes:
        message: Error description.
        error_type: Category of error (rate_limit, forbidden, bad_request, network, api).
        retry_after: Seconds to wait before retry (for rate limits).
    """

    def __init__(
        self,
        message: str,
        error_type: str,
        retry_after: int | None = None,
    ) -> None:
        """
        Initialize the error.

        Args:
            message: Error description.
            error_type: One of: rate_limit, forbidden, bad_request, network, api.
            retry_after: Seconds to wait (for rate_limit type).
        """
        super().__init__(message)
        self.error_type = error_type
        self.retry_after = retry_after

    def __repr__(self) -> str:
        """String representation."""
        if self.retry_after:
            return f"TelegramOperationError({self.error_type}, retry_after={self.retry_after})"
        return f"TelegramOperationError({self.error_type})"


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Protocols
    "LoggerProtocol",
    "CacheProtocol",
    "ChannelSubscriptionProtocol",
    "ChatRestrictionsProtocol",
    # Exceptions
    "TelegramOperationError",
]
