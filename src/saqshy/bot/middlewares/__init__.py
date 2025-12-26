"""
SAQSHY Bot Middlewares

Middlewares process messages before they reach handlers.

Middleware Registration Order (in Dispatcher):
1. ErrorMiddleware (outer) - Catches all errors, prevents propagation
2. LoggingMiddleware - Adds correlation ID, logs events
3. AuthMiddleware - Checks user permissions (admin, whitelist, blacklist)
4. RateLimitMiddleware - Prevents abuse

Available middlewares:
- AuthMiddleware: Validates user permissions
- RateLimitMiddleware: Prevents abuse
- LoggingMiddleware: Logs all messages with correlation IDs
- MetricsMiddleware: Collects processing metrics
- ErrorMiddleware: Handles errors gracefully

Utilities:
- CircuitBreaker: Resilience pattern for external services
- ServiceDegradation: Tracks degraded service state
- configure_structlog: Configures structured logging
- check_user_is_admin: Standalone admin check function
- refresh_admin_cache: Refreshes admin cache for a chat
"""

from saqshy.bot.middlewares.auth import (
    AuthMiddleware,
    check_user_is_admin,
    refresh_admin_cache,
)
from saqshy.bot.middlewares.config import ConfigMiddleware
from saqshy.bot.middlewares.error import (
    CircuitBreaker,
    CircuitBreakerOpen,
    ErrorMiddleware,
    ServiceDegradation,
    get_degradation_manager,
    handle_error,
)
from saqshy.bot.middlewares.logging import (
    LoggingMiddleware,
    MetricsMiddleware,
    configure_structlog,
)
from saqshy.bot.middlewares.rate_limit import (
    AdaptiveRateLimiter,
    RateLimitMiddleware,
)

__all__ = [
    # Core middlewares
    "AuthMiddleware",
    "RateLimitMiddleware",
    "LoggingMiddleware",
    "MetricsMiddleware",
    "ErrorMiddleware",
    "ConfigMiddleware",
    # Error handling utilities
    "CircuitBreaker",
    "CircuitBreakerOpen",
    "ServiceDegradation",
    "get_degradation_manager",
    "handle_error",
    # Auth utilities
    "check_user_is_admin",
    "refresh_admin_cache",
    # Rate limiting utilities
    "AdaptiveRateLimiter",
    # Logging utilities
    "configure_structlog",
]
