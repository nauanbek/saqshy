"""
SAQSHY Mini App Module

Telegram Mini App backend API using aiohttp.

Provides:
- Group settings management
- Statistics and analytics
- Admin authentication via Telegram WebApp
- Decision logs and overrides
- User management (whitelist/blacklist)

Usage:
    from saqshy.mini_app import create_mini_app_routes, setup_routes
    from saqshy.mini_app import create_auth_middleware, create_cors_middleware

    # Add middleware
    app.middlewares.append(create_cors_middleware())
    app.middlewares.append(create_auth_middleware(bot_token))

    # Add routes
    setup_routes(app)
"""

# Authentication
from saqshy.mini_app.auth import (
    InMemoryRateLimiter,
    TelegramAuthMiddleware,
    WebAppAuth,
    WebAppData,
    WebAppUser,
    create_auth_middleware,
    create_cors_middleware,
    create_rate_limit_middleware,
    create_security_headers_middleware,
    validate_init_data,
)

# Routes
from saqshy.mini_app.routes import (
    create_mini_app_routes,
    setup_routes,
)

# Schemas - Response types
from saqshy.mini_app.schemas import (
    APIResponse,
    ChannelValidateResponse,
    DecisionDetail,
    DecisionListResponse,
    DecisionOverrideRequest,
    DecisionOverrideResponse,
    ErrorDetail,
    GroupInfoResponse,
    GroupSettingsRequest,
    GroupSettingsResponse,
    GroupStatsResponse,
    ReviewItem,
    ReviewQueueResponse,
    ThreatTypeCount,
    UserListRequest,
    UserListResponse,
    UserProfileResponse,
    UserStatsResponse,
)

__all__ = [
    # Authentication
    "InMemoryRateLimiter",
    "TelegramAuthMiddleware",
    "WebAppAuth",
    "WebAppData",
    "WebAppUser",
    "create_auth_middleware",
    "create_cors_middleware",
    "create_rate_limit_middleware",
    "create_security_headers_middleware",
    "validate_init_data",
    # Routes
    "create_mini_app_routes",
    "setup_routes",
    # Schemas
    "APIResponse",
    "ChannelValidateResponse",
    "DecisionDetail",
    "DecisionListResponse",
    "DecisionOverrideRequest",
    "DecisionOverrideResponse",
    "ErrorDetail",
    "GroupInfoResponse",
    "GroupSettingsRequest",
    "GroupSettingsResponse",
    "GroupStatsResponse",
    "ReviewItem",
    "ReviewQueueResponse",
    "ThreatTypeCount",
    "UserListRequest",
    "UserListResponse",
    "UserProfileResponse",
    "UserStatsResponse",
]
