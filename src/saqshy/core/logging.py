"""
SAQSHY Structured Logging

Production-grade logging configuration with:
- JSON output for production (structured logs for aggregation)
- Console output for development (human-readable)
- Correlation ID propagation across requests
- Sensitive data filtering
- Request/response logging utilities

This module should be configured at application startup.

Example:
    >>> from saqshy.core.logging import configure_logging, get_logger
    >>> configure_logging(environment="production")
    >>> logger = get_logger(__name__)
    >>> logger.info("message_processed", user_id=123, verdict="allow")
"""

from __future__ import annotations

import logging
import re
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

# =============================================================================
# Correlation ID Management
# =============================================================================

# Context variable for correlation ID - thread-safe and async-safe
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_request_context: ContextVar[dict[str, Any]] = ContextVar("request_context", default={})


def get_correlation_id() -> str:
    """
    Get current correlation ID from context.

    Returns existing ID or generates a new one if not set.

    Returns:
        Correlation ID string (8 characters for brevity).
    """
    cid = _correlation_id.get()
    if cid is None:
        cid = generate_correlation_id()
        _correlation_id.set(cid)
    return cid


def set_correlation_id(correlation_id: str) -> None:
    """
    Set correlation ID in context.

    Args:
        correlation_id: The correlation ID to set.
    """
    _correlation_id.set(correlation_id)


def generate_correlation_id() -> str:
    """
    Generate a new correlation ID.

    Returns:
        8-character UUID substring for brevity in logs.
    """
    return str(uuid.uuid4())[:8]


def clear_correlation_id() -> None:
    """Clear correlation ID from context."""
    _correlation_id.set(None)


def get_request_context() -> dict[str, Any]:
    """
    Get current request context.

    Returns:
        Dictionary with request context data.
    """
    return _request_context.get()


def set_request_context(context: dict[str, Any]) -> None:
    """
    Set request context.

    Args:
        context: Dictionary with context data (chat_id, user_id, etc.)
    """
    _request_context.set(context)


def clear_request_context() -> None:
    """Clear request context."""
    _request_context.set({})


# =============================================================================
# User ID Anonymization
# =============================================================================


def anonymize_user_id(user_id: int) -> str:
    """
    Anonymize user ID for logging.

    Creates a consistent hash that allows correlation within logs
    but does not reveal the actual Telegram user ID.

    Args:
        user_id: Telegram user ID.

    Returns:
        Anonymized user ID string (8 chars).

    Example:
        >>> anonymize_user_id(123456789)
        'usr_a1b2c3d4'
    """
    import hashlib

    # Use SHA-256 with a salt to prevent rainbow table attacks
    # The salt is application-specific but consistent
    salt = "saqshy_user_salt_v1"
    hash_input = f"{salt}:{user_id}".encode()
    hash_digest = hashlib.sha256(hash_input).hexdigest()[:8]
    return f"usr_{hash_digest}"


# =============================================================================
# Sensitive Data Filtering
# =============================================================================

# Patterns for sensitive data that should be redacted
SENSITIVE_PATTERNS = [
    (re.compile(r"(api[_-]?key|apikey)[\"']?\s*[:=]\s*[\"']?[\w-]+", re.I), "[REDACTED_API_KEY]"),
    (re.compile(r"(token|bearer)[\"']?\s*[:=]\s*[\"']?[\w.-]+", re.I), "[REDACTED_TOKEN]"),
    (
        re.compile(r"(password|passwd|pwd)[\"']?\s*[:=]\s*[\"']?[^\s,}\"']+", re.I),
        "[REDACTED_PASSWORD]",
    ),
    (re.compile(r"(secret)[\"']?\s*[:=]\s*[\"']?[\w.-]+", re.I), "[REDACTED_SECRET]"),
    # Bot tokens: 123456789:ABCdefGHI...
    (re.compile(r"\d{9,10}:[A-Za-z0-9_-]{35,}"), "[REDACTED_BOT_TOKEN]"),
    # Credit card numbers
    (re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"), "[REDACTED_CC]"),
    # Email addresses (optional - comment out if emails should be logged)
    # (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[REDACTED_EMAIL]"),
]

# Keys that should have their values redacted
SENSITIVE_KEYS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "bearer",
    "credential",
    "credentials",
    "bot_token",
    "webhook_secret",
    "jwt_secret",
    "anthropic_api_key",
    "cohere_api_key",
    "database_url",
    "redis_url",
}


def filter_sensitive_data(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Processor that filters sensitive data from log entries.

    Redacts values for sensitive keys and patterns in string values.

    Args:
        logger: The wrapped logger instance.
        method_name: The log method name (info, warning, etc.).
        event_dict: The event dictionary to filter.

    Returns:
        Filtered event dictionary.
    """

    def redact_value(key: str, value: Any) -> Any:
        """Redact a single value if necessary."""
        # Check if key is sensitive
        key_lower = key.lower()
        if key_lower in SENSITIVE_KEYS:
            return "[REDACTED]"

        # Check string values for sensitive patterns
        if isinstance(value, str):
            for pattern, replacement in SENSITIVE_PATTERNS:
                value = pattern.sub(replacement, value)

        # Recursively handle nested dicts
        elif isinstance(value, dict):
            value = {k: redact_value(k, v) for k, v in value.items()}

        # Handle lists
        elif isinstance(value, list):
            value = [redact_value(key, item) for item in value]

        return value

    # Filter all keys in the event dict
    filtered = {}
    for key, value in event_dict.items():
        filtered[key] = redact_value(key, value)

    return filtered


# =============================================================================
# Custom Processors
# =============================================================================


def add_correlation_id(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Processor that adds correlation ID to every log entry.

    Args:
        logger: The wrapped logger instance.
        method_name: The log method name.
        event_dict: The event dictionary.

    Returns:
        Event dictionary with correlation_id added.
    """
    cid = _correlation_id.get()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


def add_request_context(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Processor that adds request context to log entries.

    Adds chat_id, user_id, group_type if available in context.

    Args:
        logger: The wrapped logger instance.
        method_name: The log method name.
        event_dict: The event dictionary.

    Returns:
        Event dictionary with request context added.
    """
    ctx = _request_context.get()
    if ctx:
        # Only add specific fields, not everything
        for key in ("chat_id", "user_id", "group_type", "message_id"):
            if key in ctx and key not in event_dict:
                event_dict[key] = ctx[key]
    return event_dict


def add_service_info(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Processor that adds service identification info.

    Args:
        logger: The wrapped logger instance.
        method_name: The log method name.
        event_dict: The event dictionary.

    Returns:
        Event dictionary with service info added.
    """
    event_dict["service"] = "saqshy"
    return event_dict


def format_exception_info(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Processor that formats exception info for production logs.

    Converts exception to a structured format suitable for JSON logging.

    Args:
        logger: The wrapped logger instance.
        method_name: The log method name.
        event_dict: The event dictionary.

    Returns:
        Event dictionary with formatted exception info.
    """
    if "exc_info" in event_dict:
        exc_info = event_dict.pop("exc_info")
        if exc_info:
            if isinstance(exc_info, tuple):
                exc_type, exc_value, exc_tb = exc_info
                if exc_type is not None:
                    event_dict["exception_type"] = exc_type.__name__
                    event_dict["exception_message"] = str(exc_value)
            elif isinstance(exc_info, BaseException):
                event_dict["exception_type"] = type(exc_info).__name__
                event_dict["exception_message"] = str(exc_info)

    return event_dict


# =============================================================================
# Logging Configuration
# =============================================================================


def configure_logging(
    environment: str = "development",
    log_level: str = "INFO",
    json_logs: bool | None = None,
) -> None:
    """
    Configure structlog for the application.

    Call this once at application startup, before any logging is performed.

    Args:
        environment: Environment name ("development", "staging", "production").
        log_level: Minimum log level ("DEBUG", "INFO", "WARNING", "ERROR").
        json_logs: Force JSON output. If None, auto-detect based on environment.

    Example:
        >>> configure_logging(environment="production", log_level="INFO")
    """
    # Determine if we should use JSON logs
    if json_logs is None:
        # Use JSON in production, console in development
        use_json = environment in ("production", "staging") or not sys.stdout.isatty()
    else:
        use_json = json_logs

    # Build processor chain
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        add_correlation_id,
        add_request_context,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        filter_sensitive_data,
    ]

    if use_json:
        # Production: JSON output with full structure
        processors: list[Processor] = [
            *shared_processors,
            add_service_info,
            format_exception_info,
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Development: Human-readable console output
        processors = [
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            ),
        ]

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure standard library logging for compatibility
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    # Suppress noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a configured logger instance.

    Args:
        name: Logger name (typically __name__).

    Returns:
        Bound structlog logger.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("user_joined", user_id=123, chat_id=-456)
    """
    return structlog.get_logger(name)


# =============================================================================
# Logging Utilities
# =============================================================================


class LogContext:
    """
    Context manager for scoped logging context.

    Automatically sets correlation ID and request context on entry,
    and clears them on exit.

    Example:
        >>> async with LogContext(correlation_id="abc123", chat_id=-123):
        ...     logger.info("processing_message")  # Automatically includes correlation_id
    """

    def __init__(
        self,
        correlation_id: str | None = None,
        **context: Any,
    ) -> None:
        """
        Initialize logging context.

        Args:
            correlation_id: Optional correlation ID (generated if not provided).
            **context: Additional context fields (chat_id, user_id, etc.)
        """
        self.correlation_id = correlation_id or generate_correlation_id()
        self.context = context
        self._prev_cid: str | None = None
        self._prev_ctx: dict[str, Any] = {}

    def __enter__(self) -> LogContext:
        """Enter context, setting correlation ID and context."""
        self._prev_cid = _correlation_id.get()
        self._prev_ctx = _request_context.get()
        set_correlation_id(self.correlation_id)
        set_request_context(self.context)
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit context, restoring previous values."""
        if self._prev_cid is not None:
            set_correlation_id(self._prev_cid)
        else:
            clear_correlation_id()
        if self._prev_ctx:
            set_request_context(self._prev_ctx)
        else:
            clear_request_context()

    async def __aenter__(self) -> LogContext:
        """Async enter context."""
        return self.__enter__()

    async def __aexit__(self, *args: Any) -> None:
        """Async exit context."""
        return self.__exit__(*args)


def log_decision(
    logger: structlog.stdlib.BoundLogger,
    *,
    correlation_id: str,
    user_id: int,
    chat_id: int,
    message_id: int | None,
    group_type: str,
    verdict: str,
    risk_score: int,
    threat_type: str,
    total_latency_ms: float,
    profile_score: int = 0,
    content_score: int = 0,
    behavior_score: int = 0,
    network_score: int = 0,
    llm_called: bool = False,
    llm_latency_ms: float | None = None,
    spam_db_match: bool = False,
    spam_db_score: float = 0.0,
    contributing_factors: list[str] | None = None,
    mitigating_factors: list[str] | None = None,
    anonymize: bool = True,
) -> None:
    """
    Log a moderation decision with full context.

    This is the primary logging function for spam detection decisions.
    Provides consistent structured logging for all verdicts.

    IMPORTANT: By default, user_id is anonymized to comply with privacy
    requirements. Set anonymize=False only for debugging in development.

    Args:
        logger: The bound logger instance.
        correlation_id: Request correlation ID.
        user_id: Telegram user ID.
        chat_id: Telegram chat ID (also logged as group_id for clarity).
        message_id: Telegram message ID (optional).
        group_type: Group type (general/tech/deals/crypto).
        verdict: Decision verdict (ALLOW/WATCH/LIMIT/REVIEW/BLOCK).
        risk_score: Cumulative risk score (0-100).
        threat_type: Detected threat type.
        total_latency_ms: Total processing time in milliseconds.
        profile_score: Score from profile analysis.
        content_score: Score from content analysis.
        behavior_score: Score from behavior analysis.
        network_score: Score from network/spam DB analysis.
        llm_called: Whether LLM was invoked.
        llm_latency_ms: LLM response time (if called).
        spam_db_match: Whether spam DB had a match.
        spam_db_score: Spam DB similarity score.
        contributing_factors: Top factors that increased score.
        mitigating_factors: Top factors that decreased score.
        anonymize: Whether to anonymize user_id (default True).
    """
    # Build top signals for debugging
    top_signals = []
    if contributing_factors:
        for factor in contributing_factors[:3]:
            top_signals.append({"type": "risk", "signal": factor})
    if mitigating_factors:
        for factor in mitigating_factors[:2]:
            top_signals.append({"type": "trust", "signal": factor})

    # Anonymize user_id for privacy in production logs
    logged_user_id: str | int = anonymize_user_id(user_id) if anonymize else user_id

    logger.info(
        "moderation_decision",
        correlation_id=correlation_id,
        user_id=logged_user_id,
        group_id=chat_id,  # Alias for clarity in metrics/dashboards
        message_id=message_id,
        group_type=group_type,
        verdict=verdict,
        risk_score=risk_score,
        threat_type=threat_type,
        processing_time_ms=round(total_latency_ms, 2),  # Standard field name
        profile_score=profile_score,
        content_score=content_score,
        behavior_score=behavior_score,
        network_score=network_score,
        llm_called=llm_called,
        llm_latency_ms=round(llm_latency_ms, 2) if llm_latency_ms else None,
        spam_db_match=spam_db_match,
        spam_db_score=round(spam_db_score, 3) if spam_db_score else 0.0,
        top_signals=top_signals,
    )


def log_error(
    logger: structlog.stdlib.BoundLogger,
    event: str,
    error: Exception,
    *,
    correlation_id: str | None = None,
    **context: Any,
) -> None:
    """
    Log an error with full context and exception details.

    Args:
        logger: The bound logger instance.
        event: Error event name.
        error: The exception that occurred.
        correlation_id: Optional correlation ID.
        **context: Additional context fields.
    """
    logger.error(
        event,
        correlation_id=correlation_id or get_correlation_id(),
        error=str(error),
        error_type=type(error).__name__,
        exc_info=error,
        **context,
    )


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Correlation ID management
    "get_correlation_id",
    "set_correlation_id",
    "generate_correlation_id",
    "clear_correlation_id",
    # Request context management
    "get_request_context",
    "set_request_context",
    "clear_request_context",
    # Privacy utilities
    "anonymize_user_id",
    # Configuration
    "configure_logging",
    "get_logger",
    # Context manager
    "LogContext",
    # Logging utilities
    "log_decision",
    "log_error",
]
