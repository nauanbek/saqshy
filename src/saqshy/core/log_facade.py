"""
SAQSHY Core Log Facade

Lightweight logging facade for the core module.
Has ZERO external dependencies - uses only stdlib logging.

This module provides:
- StdlibLogger: Default logger using Python's logging module
- A global logger factory that can be replaced at runtime
- get_logger() function matching the structlog API

In production, the logger factory is replaced with StructlogAdapter
at application startup. This allows core/ to log without importing
structlog directly.

Example:
    >>> from saqshy.core.log_facade import get_logger
    >>> logger = get_logger(__name__)
    >>> logger.info("user_sandboxed", user_id=123, chat_id=-456)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from saqshy.core.protocols import LoggerProtocol

# =============================================================================
# Stdlib Logger Implementation
# =============================================================================


class StdlibLogger(LoggerProtocol):
    """
    Default logger implementation using Python's stdlib logging.

    This is the fallback logger used when no external logging library
    is configured. It provides a structlog-compatible API on top of
    the standard logging module.

    Thread Safety:
        This class is thread-safe (delegates to stdlib logging).

    Example:
        >>> logger = StdlibLogger("my.module")
        >>> logger.info("something_happened", key="value")
        INFO:my.module:something_happened key=value

        >>> bound = logger.bind(user_id=123)
        >>> bound.info("user_action")
        INFO:my.module:user_action user_id=123
    """

    def __init__(self, name: str) -> None:
        """
        Initialize the logger.

        Args:
            name: Logger name (typically __name__).
        """
        self._logger = logging.getLogger(name)
        self._context: dict[str, Any] = {}

    def info(self, event: str, **kwargs: Any) -> None:
        """Log an info-level event."""
        self._log(logging.INFO, event, kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        """Log a warning-level event."""
        self._log(logging.WARNING, event, kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        """Log an error-level event."""
        self._log(logging.ERROR, event, kwargs)

    def debug(self, event: str, **kwargs: Any) -> None:
        """Log a debug-level event."""
        self._log(logging.DEBUG, event, kwargs)

    def bind(self, **kwargs: Any) -> StdlibLogger:
        """
        Create a new logger with additional context bound.

        Args:
            **kwargs: Context to bind to all future log calls.

        Returns:
            New StdlibLogger instance with combined context.
        """
        new_logger = StdlibLogger(self._logger.name)
        new_logger._context = {**self._context, **kwargs}
        return new_logger

    def _log(
        self,
        level: int,
        event: str,
        kwargs: dict[str, Any],
    ) -> None:
        """
        Internal log method.

        Combines bound context with call-time kwargs and formats
        as key=value pairs after the event name.

        Args:
            level: Logging level (INFO, WARNING, etc.).
            event: Event name (e.g., "user_sandboxed").
            kwargs: Additional context for this log call.
        """
        combined = {**self._context, **kwargs}
        if combined:
            extra_str = " ".join(f"{k}={v}" for k, v in combined.items())
            message = f"{event} {extra_str}"
        else:
            message = event
        self._logger.log(level, message)


# =============================================================================
# Global Logger Factory
# =============================================================================

# The factory function that creates loggers
# Default is StdlibLogger, but can be replaced at runtime
_logger_factory: Callable[[str], LoggerProtocol] = StdlibLogger


def set_logger_factory(factory: Callable[[str], LoggerProtocol]) -> None:
    """
    Replace the global logger factory.

    Call this at application startup to use a different logging
    implementation (e.g., StructlogAdapter).

    Args:
        factory: Callable that takes a name and returns LoggerProtocol.

    Example:
        >>> from saqshy.services.structlog_adapter import StructlogAdapter
        >>> set_logger_factory(StructlogAdapter)
    """
    global _logger_factory
    _logger_factory = factory


def get_logger(name: str) -> LoggerProtocol:
    """
    Get a logger instance.

    Uses the currently configured logger factory.

    Args:
        name: Logger name (typically __name__).

    Returns:
        Logger implementing LoggerProtocol.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("starting_process", step=1)
    """
    return _logger_factory(name)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "StdlibLogger",
    "set_logger_factory",
    "get_logger",
]
