"""
SAQSHY Test Fixtures - Mini App Authentication

Provides mock authentication helpers for testing Mini App API endpoints
without requiring a real Telegram WebApp session.

Usage in tests:
    from tests.fixtures.miniapp_auth import create_mock_webapp_auth, generate_test_init_data

    # Create mock auth for request
    mock_auth = create_mock_webapp_auth(user_id=123456789, is_admin_for=[group_id])

    # Or generate real-looking init data for integration tests
    init_data = generate_test_init_data(user_id=123456789, bot_token=TEST_BOT_TOKEN)
"""

import hashlib
import hmac
import json
import time
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient

from saqshy.mini_app.auth import WebAppAuth, WebAppData, WebAppUser, validate_init_data


# =============================================================================
# Test Bot Token
# =============================================================================

# Fake bot token for tests - NEVER use real tokens!
TEST_BOT_TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"


# =============================================================================
# Helper Functions
# =============================================================================


def generate_test_init_data(
    user_id: int = 123456789,
    first_name: str = "Test",
    last_name: str | None = "User",
    username: str | None = "testuser",
    is_premium: bool = False,
    bot_token: str = TEST_BOT_TOKEN,
    start_param: str | None = None,
    auth_date: int | None = None,
) -> str:
    """
    Generate valid Telegram WebApp init data for testing.

    Creates properly signed init data that will pass validation.

    Args:
        user_id: Telegram user ID
        first_name: User's first name
        last_name: User's last name (optional)
        username: User's @username (optional)
        is_premium: Whether user has premium
        bot_token: Bot token for signing
        start_param: The start parameter (e.g., "group_-1001234567890")
        auth_date: Unix timestamp (defaults to current time)

    Returns:
        URL-encoded init data string that can be validated
    """
    if auth_date is None:
        auth_date = int(time.time())

    # Build user JSON
    user_data = {
        "id": user_id,
        "first_name": first_name,
        "is_premium": is_premium,
    }
    if last_name:
        user_data["last_name"] = last_name
    if username:
        user_data["username"] = username

    # Build params
    params: dict[str, str] = {
        "user": json.dumps(user_data, separators=(",", ":")),
        "auth_date": str(auth_date),
    }
    if start_param:
        params["start_param"] = start_param

    # Build data-check-string (sorted alphabetically, newline-separated)
    check_params = []
    for key in sorted(params.keys()):
        check_params.append(f"{key}={params[key]}")
    data_check_string = "\n".join(check_params)

    # Calculate hash
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode(),
        hashlib.sha256,
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    # Add hash to params
    params["hash"] = calculated_hash

    # Return URL-encoded query string
    return urllib.parse.urlencode(params)


def create_mock_webapp_auth(
    user_id: int = 123456789,
    username: str | None = "testuser",
    first_name: str = "Test",
    last_name: str | None = "User",
    is_admin_for: list[int] | None = None,
    is_premium: bool = False,
) -> WebAppAuth:
    """
    Create a mock WebAppAuth instance for handler testing.

    Args:
        user_id: Telegram user ID
        username: User's @username
        first_name: User's first name
        last_name: User's last name
        is_admin_for: List of chat IDs where user is admin
        is_premium: Whether user has premium

    Returns:
        Pre-validated WebAppAuth mock
    """
    admin_groups = set(is_admin_for or [])

    mock_request = MagicMock(spec=web.Request)
    mock_request.get = lambda key: {"admin_groups": admin_groups}.get(key)

    auth = MagicMock(spec=WebAppAuth)
    auth.user_id = user_id

    # Create user data
    user = WebAppUser(
        id=user_id,
        first_name=first_name,
        last_name=last_name,
        username=username,
        is_premium=is_premium,
    )
    auth.user = user
    auth._data = WebAppData(
        user=user,
        auth_date=datetime.now(UTC),
    )

    # Mock is_admin to check against admin_groups
    async def mock_is_admin(chat_id: int) -> bool:
        return chat_id in admin_groups

    auth.is_admin = mock_is_admin
    auth.validate = AsyncMock(return_value=True)

    return auth


def create_mock_webapp_request(
    path: str = "/api/groups/-1001234567890/settings",
    method: str = "GET",
    user_id: int = 123456789,
    is_admin_for: list[int] | None = None,
    body: dict[str, Any] | None = None,
    bot_token: str = TEST_BOT_TOKEN,
) -> MagicMock:
    """
    Create a complete mock aiohttp request with auth context.

    Args:
        path: Request path
        method: HTTP method
        user_id: Authenticated user ID
        is_admin_for: Chat IDs where user is admin
        body: Request body (for POST/PUT)
        bot_token: Bot token for init data

    Returns:
        Mock request ready for handler testing
    """
    auth = create_mock_webapp_auth(
        user_id=user_id,
        is_admin_for=is_admin_for or [],
    )

    request = MagicMock(spec=web.Request)
    request.path = path
    request.method = method
    request.app = {}

    # Setup request.get() for auth context
    request_context = {
        "webapp_auth": auth,
        "user_id": user_id,
        "user": auth.user,
    }
    request.get = lambda key, default=None: request_context.get(key, default)

    # Setup body parsing
    if body:
        request.json = AsyncMock(return_value=body)
    else:
        request.json = AsyncMock(return_value={})

    return request


# =============================================================================
# Pytest Fixtures
# =============================================================================


@pytest.fixture
def test_bot_token() -> str:
    """Provide test bot token."""
    return TEST_BOT_TOKEN


@pytest.fixture
def mock_webapp_user() -> WebAppUser:
    """Create a test WebApp user."""
    return WebAppUser(
        id=123456789,
        first_name="Test",
        last_name="User",
        username="testuser",
        is_premium=False,
    )


@pytest.fixture
def mock_admin_webapp_auth() -> WebAppAuth:
    """Create mock auth for an admin user."""
    return create_mock_webapp_auth(
        user_id=123456789,
        is_admin_for=[-1001234567890],
    )


@pytest.fixture
def mock_non_admin_webapp_auth() -> WebAppAuth:
    """Create mock auth for a non-admin user."""
    return create_mock_webapp_auth(
        user_id=987654321,
        is_admin_for=[],  # Not admin anywhere
    )


@pytest.fixture
def valid_init_data() -> str:
    """Generate valid init data for testing."""
    return generate_test_init_data(
        user_id=123456789,
        first_name="Test",
        last_name="User",
        username="testuser",
        start_param="group_-1001234567890",
    )


@pytest.fixture
def expired_init_data() -> str:
    """Generate expired init data for testing."""
    # Create init data from 2 days ago
    old_time = int(time.time()) - (2 * 24 * 60 * 60)
    return generate_test_init_data(
        user_id=123456789,
        auth_date=old_time,
    )


# =============================================================================
# Test Helpers for aiohttp Test Client
# =============================================================================


class MiniAppTestClient:
    """
    Test client wrapper for Mini App API testing.

    Provides helper methods to make authenticated requests.
    """

    def __init__(
        self,
        client: TestClient,
        bot_token: str = TEST_BOT_TOKEN,
    ):
        self.client = client
        self.bot_token = bot_token
        self._user_id: int = 123456789
        self._username: str = "testuser"
        self._is_premium: bool = False

    def as_user(
        self,
        user_id: int,
        username: str = "testuser",
        is_premium: bool = False,
    ) -> "MiniAppTestClient":
        """Set the user for subsequent requests."""
        self._user_id = user_id
        self._username = username
        self._is_premium = is_premium
        return self

    def _get_auth_headers(self, start_param: str | None = None) -> dict[str, str]:
        """Generate auth headers for request."""
        init_data = generate_test_init_data(
            user_id=self._user_id,
            username=self._username,
            is_premium=self._is_premium,
            bot_token=self.bot_token,
            start_param=start_param,
        )
        return {"X-Telegram-Init-Data": init_data}

    async def get(
        self,
        path: str,
        start_param: str | None = None,
        **kwargs: Any,
    ):
        """Make authenticated GET request."""
        headers = self._get_auth_headers(start_param)
        return await self.client.get(path, headers=headers, **kwargs)

    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        start_param: str | None = None,
        **kwargs: Any,
    ):
        """Make authenticated POST request."""
        headers = self._get_auth_headers(start_param)
        return await self.client.post(path, json=json, headers=headers, **kwargs)

    async def put(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        start_param: str | None = None,
        **kwargs: Any,
    ):
        """Make authenticated PUT request."""
        headers = self._get_auth_headers(start_param)
        return await self.client.put(path, json=json, headers=headers, **kwargs)

    async def delete(
        self,
        path: str,
        start_param: str | None = None,
        **kwargs: Any,
    ):
        """Make authenticated DELETE request."""
        headers = self._get_auth_headers(start_param)
        return await self.client.delete(path, headers=headers, **kwargs)


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "TEST_BOT_TOKEN",
    "generate_test_init_data",
    "create_mock_webapp_auth",
    "create_mock_webapp_request",
    "mock_webapp_user",
    "mock_admin_webapp_auth",
    "mock_non_admin_webapp_auth",
    "valid_init_data",
    "expired_init_data",
    "MiniAppTestClient",
]
