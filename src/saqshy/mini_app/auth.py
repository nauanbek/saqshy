"""
SAQSHY Mini App Authentication

Validates Telegram WebApp init data for secure authentication.
Implements the validation algorithm described in:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import os
import time
import urllib.parse
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from aiohttp import web

logger = structlog.get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Default allowed CORS origins for Telegram WebApp
# Can be overridden via ALLOWED_CORS_ORIGINS environment variable (comma-separated)
DEFAULT_TELEGRAM_ORIGINS = [
    "https://telegram.org",
    "https://web.telegram.org",
    "https://webk.telegram.org",
    "https://webz.telegram.org",
    "https://telegram.web.app",  # Newer Telegram domain
]


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class WebAppUser:
    """Telegram WebApp user data extracted from init data."""

    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    is_premium: bool = False
    photo_url: str | None = None


@dataclass
class WebAppData:
    """Validated Telegram WebApp init data."""

    user: WebAppUser
    chat_instance: str | None = None
    chat_type: str | None = None
    start_param: str | None = None
    auth_date: datetime | None = None
    hash: str = ""
    query_id: str | None = None


# =============================================================================
# Validation Functions
# =============================================================================


def validate_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = 86400,
) -> WebAppData | None:
    """
    Validate Telegram WebApp init data.

    Implements the validation algorithm described in:
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Args:
        init_data: The init data string from Telegram WebApp (query string format).
        bot_token: Bot token for HMAC validation.
        max_age_seconds: Max age of auth_date (default 24 hours).

    Returns:
        WebAppData if validation succeeds, None otherwise.

    Example:
        >>> data = validate_init_data(init_data, "123456:ABC-DEF...")
        >>> if data:
        ...     print(f"User ID: {data.user.id}")
    """
    if not init_data:
        return None

    try:
        # Parse the init data as query string
        params = urllib.parse.parse_qs(init_data)

        # Extract hash
        received_hash = params.get("hash", [""])[0]
        if not received_hash:
            logger.warning("webapp_auth_missing_hash")
            return None

        # Build data-check-string
        # Sort parameters alphabetically and join with newlines
        # Exclude 'hash' from the check string
        check_params = []
        for key in sorted(params.keys()):
            if key != "hash":
                value = params[key][0]
                check_params.append(f"{key}={value}")

        data_check_string = "\n".join(check_params)

        # Calculate secret key using HMAC-SHA256
        # secret_key = HMAC_SHA256(bot_token, "WebAppData")
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256,
        ).digest()

        # Calculate expected hash
        # hash = HMAC_SHA256(secret_key, data_check_string)
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        # Compare hashes using constant-time comparison
        if not hmac.compare_digest(calculated_hash, received_hash):
            logger.warning("webapp_auth_invalid_hash")
            return None

        # Check auth_date is not too old
        auth_date_str = params.get("auth_date", [""])[0]
        if not auth_date_str:
            logger.warning("webapp_auth_missing_auth_date")
            return None

        auth_date = datetime.fromtimestamp(int(auth_date_str), tz=UTC)
        now = datetime.now(UTC)
        if now - auth_date > timedelta(seconds=max_age_seconds):
            logger.warning(
                "webapp_auth_expired",
                auth_date=auth_date.isoformat(),
                max_age_seconds=max_age_seconds,
            )
            return None

        # Parse user data
        user_str = params.get("user", [""])[0]
        if not user_str:
            logger.warning("webapp_auth_missing_user")
            return None

        user_data = json.loads(user_str)
        user = WebAppUser(
            id=user_data["id"],
            first_name=user_data.get("first_name", ""),
            last_name=user_data.get("last_name"),
            username=user_data.get("username"),
            language_code=user_data.get("language_code"),
            is_premium=user_data.get("is_premium", False),
            photo_url=user_data.get("photo_url"),
        )

        return WebAppData(
            user=user,
            chat_instance=params.get("chat_instance", [None])[0],
            chat_type=params.get("chat_type", [None])[0],
            start_param=params.get("start_param", [None])[0],
            auth_date=auth_date,
            hash=received_hash,
            query_id=params.get("query_id", [None])[0],
        )

    except json.JSONDecodeError as e:
        logger.error("webapp_auth_json_error", error=str(e))
        return None
    except KeyError as e:
        logger.error("webapp_auth_missing_field", field=str(e))
        return None
    except (ValueError, TypeError) as e:
        logger.error("webapp_auth_parse_error", error=str(e))
        return None
    except Exception as e:
        logger.error("webapp_auth_unexpected_error", error=str(e), error_type=type(e).__name__)
        return None


# =============================================================================
# WebApp Auth Helper
# =============================================================================


class WebAppAuth:
    """
    WebApp authentication helper.

    Validates init data from request headers and provides
    admin status checking via Telegram API or cache.

    Attributes:
        HEADER_NAME: The HTTP header containing init data.

    Example:
        >>> auth = WebAppAuth(request, bot_token)
        >>> if await auth.validate():
        ...     print(f"User: {auth.user_id}")
        ...     if await auth.is_admin(group_id):
        ...         print("User is admin")
    """

    HEADER_NAME = "X-Telegram-Init-Data"

    def __init__(
        self,
        request: web.Request,
        bot_token: str,
        *,
        admin_checker: Callable[[int, int], Awaitable[bool]] | None = None,
    ):
        """
        Initialize auth helper.

        Args:
            request: aiohttp Request object.
            bot_token: Bot token for validation.
            admin_checker: Optional async function to check admin status.
                           Signature: async (user_id, chat_id) -> bool
        """
        self.request = request
        self.bot_token = bot_token
        self._admin_checker = admin_checker
        self._data: WebAppData | None = None
        self._validated = False

    async def validate(self) -> bool:
        """
        Validate the WebApp init data from request headers.

        Returns:
            True if validation succeeds, False otherwise.
        """
        if self._validated:
            return self._data is not None

        init_data = self.request.headers.get(self.HEADER_NAME, "")
        self._data = validate_init_data(init_data, self.bot_token)
        self._validated = True

        if self._data:
            logger.debug(
                "webapp_auth_success",
                user_id=self._data.user.id,
                username=self._data.user.username,
            )
        else:
            logger.warning(
                "webapp_auth_failed",
                path=self.request.path,
            )

        return self._data is not None

    @property
    def data(self) -> WebAppData | None:
        """Get validated WebApp data."""
        return self._data

    @property
    def user(self) -> WebAppUser | None:
        """Get authenticated user."""
        return self._data.user if self._data else None

    @property
    def user_id(self) -> int | None:
        """Get authenticated user ID."""
        return self._data.user.id if self._data else None

    async def is_admin(self, chat_id: int) -> bool:
        """
        Check if authenticated user is admin in a group.

        Uses the admin_checker callback if provided, otherwise
        falls back to checking via the database.

        Args:
            chat_id: Telegram chat ID to check admin status for.

        Returns:
            True if user is admin in the group, False otherwise.
        """
        if not self._data:
            return False

        user_id = self._data.user.id

        # Use custom admin checker if provided
        if self._admin_checker is not None:
            try:
                return await self._admin_checker(user_id, chat_id)
            except Exception as e:
                logger.error(
                    "admin_check_error",
                    user_id=user_id,
                    chat_id=chat_id,
                    error=str(e),
                )
                return False

        # Fall back to checking request context (set by middleware)
        admin_groups = self.request.get("admin_groups", set())
        return chat_id in admin_groups


# =============================================================================
# Middleware
# =============================================================================


class TelegramAuthMiddleware:
    """
    aiohttp middleware for Telegram WebApp authentication.

    Validates init data from X-Telegram-Init-Data header for all /api/* routes.
    On successful validation, injects user context into the request.

    Attributes:
        bot_token: Bot token used for validation.
        excluded_paths: Paths to exclude from authentication.

    Example:
        >>> middleware = TelegramAuthMiddleware(bot_token)
        >>> app.middlewares.append(middleware.middleware)
    """

    def __init__(
        self,
        bot_token: str,
        *,
        excluded_paths: set[str] | None = None,
        admin_checker: Callable[[int, int], Awaitable[bool]] | None = None,
    ):
        """
        Initialize the middleware.

        Args:
            bot_token: Bot token for init data validation.
            excluded_paths: Set of paths to skip authentication for.
            admin_checker: Optional async function to check admin status.
        """
        self.bot_token = bot_token
        self.excluded_paths = excluded_paths or set()
        self.admin_checker = admin_checker

    @web.middleware
    async def middleware(
        self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.Response]],
    ) -> web.Response:
        """
        Middleware handler that validates WebApp auth.

        Skips validation for:
        - Non-API routes (not starting with /api/)
        - Explicitly excluded paths

        On successful validation, adds to request:
        - webapp_auth: WebAppAuth instance
        - user_id: Authenticated user's Telegram ID
        - user: WebAppUser instance

        Args:
            request: The incoming request.
            handler: The next handler in the chain.

        Returns:
            Response from handler or 401 error.
        """
        # Skip non-API routes
        if not request.path.startswith("/api/"):
            return await handler(request)

        # Skip excluded paths
        if request.path in self.excluded_paths:
            return await handler(request)

        # Validate authentication
        auth = WebAppAuth(
            request,
            self.bot_token,
            admin_checker=self.admin_checker,
        )

        if not await auth.validate():
            return web.json_response(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Invalid or missing authentication",
                    },
                },
                status=401,
            )

        # Store auth context in request
        request["webapp_auth"] = auth
        request["user_id"] = auth.user_id
        request["user"] = auth.user

        return await handler(request)


def create_auth_middleware(
    bot_token: str,
    *,
    excluded_paths: set[str] | None = None,
    admin_checker: Callable[[int, int], Awaitable[bool]] | None = None,
) -> Callable:
    """
    Create an authentication middleware instance.

    Factory function for creating the middleware.

    Args:
        bot_token: Bot token for init data validation.
        excluded_paths: Set of paths to skip authentication for.
        admin_checker: Optional async function to check admin status.

    Returns:
        Configured middleware function.

    Example:
        >>> middleware = create_auth_middleware(bot_token)
        >>> app.middlewares.append(middleware)
    """
    auth_middleware = TelegramAuthMiddleware(
        bot_token,
        excluded_paths=excluded_paths,
        admin_checker=admin_checker,
    )
    return auth_middleware.middleware


# =============================================================================
# CORS Middleware
# =============================================================================


def create_cors_middleware(
    allowed_origins: list[str] | None = None,
) -> Callable:
    """
    Create CORS middleware for the Mini App API.

    Allows requests from Telegram WebApp domains.

    Args:
        allowed_origins: List of allowed origins. Defaults to Telegram domains.
            Can be overridden via ALLOWED_CORS_ORIGINS environment variable
            (comma-separated list of origins).

    Returns:
        Configured CORS middleware function.
    """
    if allowed_origins is None:
        # Check for environment variable override
        env_origins = os.getenv("ALLOWED_CORS_ORIGINS")
        if env_origins:
            allowed_origins = [o.strip() for o in env_origins.split(",")]
        else:
            allowed_origins = DEFAULT_TELEGRAM_ORIGINS.copy()

    @web.middleware
    async def cors_middleware(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.Response]],
    ) -> web.Response:
        """Add CORS headers to responses."""
        origin = request.headers.get("Origin", "")

        # Handle preflight requests
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            try:
                response = await handler(request)
            except web.HTTPException as e:
                response = e

        # Add CORS headers if origin is allowed
        # SECURITY: Do NOT allow wildcard "*" with credentials - this is a security vulnerability
        # Only explicit origin matching is allowed for credentialed requests
        if origin and origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, X-Telegram-Init-Data, Authorization"
            )
            response.headers["Access-Control-Max-Age"] = "86400"
            response.headers["Access-Control-Allow-Credentials"] = "true"
        elif "*" in allowed_origins:
            # Wildcard mode: allow any origin but WITHOUT credentials
            # This is only safe for public APIs with no authentication
            logger.warning(
                "cors_wildcard_mode",
                origin=origin,
                warning="Wildcard CORS mode enabled - credentials NOT allowed",
            )
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Max-Age"] = "86400"
            # NOTE: Access-Control-Allow-Credentials is NOT set for wildcard

        return response

    return cors_middleware


# =============================================================================
# Rate Limiting Middleware (SH2 fix)
# =============================================================================

# Default rate limits
DEFAULT_API_RATE_LIMIT = 100  # Requests per window
DEFAULT_API_RATE_WINDOW = 60  # Seconds


class InMemoryRateLimiter:
    """
    Simple in-memory rate limiter using sliding window.

    Uses OrderedDict for O(1) LRU eviction.
    Thread-safe within single asyncio event loop.
    """

    def __init__(
        self,
        limit: int = DEFAULT_API_RATE_LIMIT,
        window_seconds: int = DEFAULT_API_RATE_WINDOW,
        max_entries: int = 10000,
    ):
        """
        Initialize rate limiter.

        Args:
            limit: Maximum requests per window per user.
            window_seconds: Time window in seconds.
            max_entries: Maximum number of user entries to track.
        """
        self.limit = limit
        self.window = window_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[int, list[float]] = OrderedDict()

    def is_allowed(self, user_id: int) -> tuple[bool, int]:
        """
        Check if request is allowed for user.

        Args:
            user_id: Telegram user ID.

        Returns:
            Tuple of (allowed, requests_remaining).
        """
        now = time.monotonic()
        window_start = now - self.window

        # Get or create entry
        if user_id not in self._entries:
            self._entries[user_id] = []

        # Move to end (LRU)
        self._entries.move_to_end(user_id)

        # Clean old timestamps
        timestamps = self._entries[user_id]
        self._entries[user_id] = [ts for ts in timestamps if ts > window_start]

        # Check limit
        current_count = len(self._entries[user_id])
        if current_count >= self.limit:
            return False, 0

        # Add new timestamp
        self._entries[user_id].append(now)

        # Evict oldest entries if over capacity
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

        return True, self.limit - current_count - 1

    def get_retry_after(self, user_id: int) -> int:
        """Get seconds until next allowed request."""
        if user_id not in self._entries or not self._entries[user_id]:
            return 0

        oldest = min(self._entries[user_id])
        retry_after = int(oldest + self.window - time.monotonic())
        return max(0, retry_after)


def create_rate_limit_middleware(
    limit: int = DEFAULT_API_RATE_LIMIT,
    window_seconds: int = DEFAULT_API_RATE_WINDOW,
) -> Callable:
    """
    Create rate limiting middleware for the Mini App API.

    Args:
        limit: Maximum requests per window per user.
        window_seconds: Time window in seconds.

    Returns:
        Configured rate limiting middleware function.
    """
    # Override from environment if set
    limit = int(os.getenv("API_RATE_LIMIT", str(limit)))
    window_seconds = int(os.getenv("API_RATE_WINDOW", str(window_seconds)))

    limiter = InMemoryRateLimiter(limit=limit, window_seconds=window_seconds)

    @web.middleware
    async def rate_limit_middleware(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.Response]],
    ) -> web.Response:
        """Apply rate limiting based on authenticated user."""
        # Skip for OPTIONS (CORS preflight)
        if request.method == "OPTIONS":
            return await handler(request)

        # Get user from auth context (set by auth middleware)
        user: WebAppUser | None = request.get("user")
        if user is None:
            # No authenticated user, skip rate limiting
            return await handler(request)

        # Check rate limit
        allowed, remaining = limiter.is_allowed(user.id)

        if not allowed:
            retry_after = limiter.get_retry_after(user.id)
            logger.warning(
                "api_rate_limited",
                user_id=user.id,
                retry_after=retry_after,
                limit=limit,
                window=window_seconds,
            )
            raise web.HTTPTooManyRequests(
                text=json.dumps({
                    "success": False,
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                    },
                }),
                content_type="application/json",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + retry_after),
                },
            )

        # Process request
        response = await handler(request)

        # Add rate limit headers to response
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response

    return rate_limit_middleware


# =============================================================================
# Security Headers Middleware (BP1 fix)
# =============================================================================


def create_security_headers_middleware() -> Callable:
    """
    Create middleware that adds security headers to all responses.

    Adds:
    - Content-Security-Policy
    - Strict-Transport-Security
    - X-Content-Type-Options
    - X-Frame-Options
    - X-XSS-Protection
    - Referrer-Policy

    Returns:
        Configured security headers middleware function.
    """

    @web.middleware
    async def security_headers_middleware(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.Response]],
    ) -> web.Response:
        """Add security headers to all responses."""
        response = await handler(request)

        # Content Security Policy - strict for API
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'",
        )

        # HSTS - force HTTPS (only set if not already present)
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )

        # Prevent MIME type sniffing
        response.headers.setdefault(
            "X-Content-Type-Options",
            "nosniff",
        )

        # Prevent embedding in iframes (except for Telegram WebApp)
        # Note: frame-ancestors in CSP takes precedence
        response.headers.setdefault(
            "X-Frame-Options",
            "DENY",
        )

        # XSS Protection (legacy, but still useful for older browsers)
        response.headers.setdefault(
            "X-XSS-Protection",
            "1; mode=block",
        )

        # Referrer Policy - don't leak URLs
        response.headers.setdefault(
            "Referrer-Policy",
            "strict-origin-when-cross-origin",
        )

        # Permissions Policy - disable unnecessary features
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )

        return response

    return security_headers_middleware
