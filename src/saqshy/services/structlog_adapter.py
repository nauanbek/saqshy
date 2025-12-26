"""
SAQSHY Structlog Adapter

Implements LoggerProtocol using structlog.
Used in production - registered at application startup.

This adapter wraps structlog to implement the LoggerProtocol,
allowing core/ to use structured logging without directly
depending on the structlog library.

Example:
    >>> from saqshy.core.log_facade import set_logger_factory
    >>> from saqshy.services.structlog_adapter import StructlogAdapter
    >>> set_logger_factory(StructlogAdapter)
"""

from __future__ import annotations

from typing import Any

import structlog

from saqshy.core.protocols import LoggerProtocol


class StructlogAdapter(LoggerProtocol):
    """
    Wraps structlog to implement LoggerProtocol.

    This adapter provides the bridge between the abstract LoggerProtocol
    in core/ and the concrete structlog implementation used in production.

    Thread Safety:
        This class is thread-safe (structlog is thread-safe).

    Example:
        >>> adapter = StructlogAdapter("my.module")
        >>> adapter.info("user_action", user_id=123)
        2024-01-01 12:00:00 [info] user_action user_id=123

        >>> bound = adapter.bind(chat_id=-456)
        >>> bound.warning("suspicious_pattern")
        2024-01-01 12:00:01 [warning] suspicious_pattern chat_id=-456
    """

    def __init__(self, name: str) -> None:
        """
        Initialize the adapter.

        Args:
            name: Logger name (typically __name__).
        """
        self._logger = structlog.get_logger(name)

    def info(self, event: str, **kwargs: Any) -> None:
        """Log an info-level event."""
        self._logger.info(event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        """Log a warning-level event."""
        self._logger.warning(event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        """Log an error-level event."""
        self._logger.error(event, **kwargs)

    def debug(self, event: str, **kwargs: Any) -> None:
        """Log a debug-level event."""
        self._logger.debug(event, **kwargs)

    def bind(self, **kwargs: Any) -> "StructlogAdapter":
        """
        Create a new logger with additional context bound.

        Args:
            **kwargs: Context to bind to all future log calls.

        Returns:
            New StructlogAdapter instance with bound context.
        """
        # Create a new adapter instance
        adapter = StructlogAdapter.__new__(StructlogAdapter)
        # Bind the context to the underlying structlog logger
        adapter._logger = self._logger.bind(**kwargs)
        return adapter


__all__ = [
    "StructlogAdapter",
]
