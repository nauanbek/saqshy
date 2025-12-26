"""
SAQSHY Service Container

Simple dependency injection container for service wiring.

This module provides explicit dependency management without magic auto-wiring.
Services are registered at application startup and retrieved by name.

Philosophy:
- Explicit over implicit
- No decorators or magic
- Easy to test (just create container with mocks)
- Type-safe when used correctly

Example:
    >>> from saqshy.services.container import ServiceContainer, configure_container
    >>> from saqshy.services.cache import CacheService
    >>> from saqshy.services.structlog_adapter import StructlogAdapter
    >>> from saqshy.bot.adapters import TelegramRestrictionsAdapter
    >>>
    >>> # At application startup:
    >>> container = ServiceContainer(
    ...     cache=CacheService(redis_url="redis://localhost:6379"),
    ...     logger_factory=StructlogAdapter,
    ... )
    >>> configure_container(container)
    >>>
    >>> # Later, anywhere in the application:
    >>> from saqshy.services.container import get_container
    >>> cache = get_container().cache
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from saqshy.core.protocols import (
    CacheProtocol,
    ChannelSubscriptionProtocol,
    ChatRestrictionsProtocol,
    LoggerProtocol,
)

T = TypeVar("T")


@dataclass
class ServiceContainer:
    """
    Container for service dependencies.

    Provides lazy initialization and explicit wiring.
    All services are optional with None defaults, allowing
    partial initialization for testing.

    Attributes:
        cache: Cache service for Redis operations.
        logger_factory: Factory function to create loggers.
        channel_subscription: Service for channel subscription checks.
        chat_restrictions: Adapter for Telegram restrictions.

    Thread Safety:
        This class is NOT thread-safe for registration.
        Register all services at startup before concurrent access.
        Reading services after registration is thread-safe.

    Example:
        >>> container = ServiceContainer(cache=mock_cache)
        >>> container.register("spam_db", lambda: SpamDBService(...))
        >>> spam_db = container.get("spam_db")
    """

    # Core protocols
    cache: CacheProtocol | None = None
    logger_factory: Callable[[str], LoggerProtocol] | None = None

    # Optional services
    channel_subscription: ChannelSubscriptionProtocol | None = None
    chat_restrictions: ChatRestrictionsProtocol | None = None

    # Additional named services (lazy initialized)
    _services: dict[str, tuple[str, Any]] = field(default_factory=dict)

    def register(
        self,
        name: str,
        factory: Callable[[], T],
    ) -> None:
        """
        Register a service factory.

        The factory will be called lazily on first get().

        Args:
            name: Unique service name.
            factory: Callable that returns the service instance.

        Example:
            >>> container.register("llm", lambda: LLMService(api_key=...))
        """
        self._services[name] = ("factory", factory)

    def register_instance(
        self,
        name: str,
        instance: Any,
    ) -> None:
        """
        Register a pre-built service instance.

        Args:
            name: Unique service name.
            instance: The service instance.

        Example:
            >>> container.register_instance("bot", bot)
        """
        self._services[name] = ("instance", instance)

    def get(self, name: str) -> Any:
        """
        Get or create a service instance.

        For factories, the instance is created and cached on first call.

        Args:
            name: Service name.

        Returns:
            The service instance.

        Raises:
            KeyError: If service is not registered.

        Example:
            >>> llm = container.get("llm")
        """
        if name not in self._services:
            raise KeyError(f"Service '{name}' not registered")

        kind, value = self._services[name]
        if kind == "instance":
            return value

        # Factory - create and cache
        instance = value()
        self._services[name] = ("instance", instance)
        return instance

    def has(self, name: str) -> bool:
        """
        Check if a service is registered.

        Args:
            name: Service name.

        Returns:
            True if service is registered.
        """
        return name in self._services

    def get_optional(self, name: str) -> Any | None:
        """
        Get a service if registered, otherwise None.

        Args:
            name: Service name.

        Returns:
            Service instance or None if not registered.
        """
        if not self.has(name):
            return None
        return self.get(name)


# =============================================================================
# Global Container Management
# =============================================================================

_container: ServiceContainer | None = None


def get_container() -> ServiceContainer:
    """
    Get the global service container.

    Returns:
        The configured ServiceContainer.

    Raises:
        RuntimeError: If container has not been configured.

    Example:
        >>> container = get_container()
        >>> cache = container.cache
    """
    global _container
    if _container is None:
        raise RuntimeError(
            "Service container not configured. Call configure_container() at startup."
        )
    return _container


def configure_container(container: ServiceContainer) -> None:
    """
    Set the global service container.

    Should be called once at application startup.

    Args:
        container: Configured ServiceContainer.

    Example:
        >>> container = ServiceContainer(cache=cache_service)
        >>> configure_container(container)
    """
    global _container
    _container = container

    # Also configure the logger factory if provided
    if container.logger_factory is not None:
        from saqshy.core.log_facade import set_logger_factory

        set_logger_factory(container.logger_factory)


def reset_container() -> None:
    """
    Reset the global container (for testing).

    Clears the global container so tests can configure their own.
    """
    global _container
    _container = None


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "ServiceContainer",
    "get_container",
    "configure_container",
    "reset_container",
]
