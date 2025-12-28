"""
Integration Tests for Mini App API Endpoints

Tests the full Mini App API including:
- WebApp authentication
- Admin permission checks
- Group settings CRUD
- Group stats
- Review queue

These tests use aiohttp test client with real database connections.
Run with: pytest tests/integration/test_mini_app/test_api_endpoints.py -v
"""

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from saqshy.core.types import GroupType, Verdict
from saqshy.db import Base
from saqshy.db.models import Decision, Group, GroupMember, TrustLevel, User
from saqshy.mini_app.auth import (
    create_auth_middleware,
    create_cors_middleware,
    create_rate_limit_middleware,
)
from saqshy.mini_app.routes import create_mini_app_routes, setup_routes

# Import test fixtures
from tests.fixtures.miniapp_auth import (
    TEST_BOT_TOKEN,
    create_mock_webapp_auth,
    generate_test_init_data,
)


# =============================================================================
# Test Application Factory
# =============================================================================


async def create_test_app(
    session_factory: async_sessionmaker[AsyncSession],
    admin_checker=None,
) -> web.Application:
    """
    Create a test aiohttp application with Mini App routes.

    Args:
        session_factory: SQLAlchemy async session factory
        admin_checker: Optional admin checker callback

    Returns:
        Configured aiohttp Application
    """
    app = web.Application()

    # Add middlewares
    app.middlewares.append(create_cors_middleware(["*"]))
    app.middlewares.append(
        create_auth_middleware(
            TEST_BOT_TOKEN,
            excluded_paths={"/api/health"},
            admin_checker=admin_checker,
        )
    )

    # Store session factory in app for request lifecycle
    app["session_factory"] = session_factory

    # Database session middleware
    @web.middleware
    async def db_session_middleware(request, handler):
        async with session_factory() as session:
            request["db_session"] = session
            try:
                response = await handler(request)
                return response
            except Exception:
                await session.rollback()
                raise

    app.middlewares.append(db_session_middleware)

    # Setup routes
    setup_routes(app)

    return app


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
async def test_engine():
    """Create test database engine."""
    import os

    db_url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://saqshy_test:test_password@localhost:5434/saqshy_test",
    )
    engine = create_async_engine(db_url, echo=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def session_factory(test_engine):
    """Create session factory."""
    return async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture
async def test_session(session_factory):
    """Get a test session."""
    async with session_factory() as session:
        yield session


@pytest.fixture
async def seed_test_data(test_session):
    """Seed test data into database."""
    # Create test group
    group = Group(
        id=-1001234567890,
        title="Test Group",
        username="testgroup",
        group_type=GroupType.GENERAL,
        sensitivity=5,
        sandbox_enabled=True,
        sandbox_duration_hours=24,
        is_active=True,
    )
    test_session.add(group)

    # Create test user
    user = User(
        id=123456789,
        username="testuser",
        first_name="Test",
        last_name="User",
        is_premium=False,
        has_photo=True,
    )
    test_session.add(user)

    # Create group membership (admin)
    admin_member = GroupMember(
        group_id=-1001234567890,
        user_id=123456789,
        trust_level=TrustLevel.ADMIN,
        trust_score=100,
        message_count=50,
    )
    test_session.add(admin_member)

    # Create another user (non-admin)
    user2 = User(
        id=987654321,
        username="otheruser",
        first_name="Other",
        last_name="User",
    )
    test_session.add(user2)

    # Create non-admin member
    regular_member = GroupMember(
        group_id=-1001234567890,
        user_id=987654321,
        trust_level=TrustLevel.TRUSTED,
        trust_score=75,
        message_count=20,
    )
    test_session.add(regular_member)

    # Create some decisions for stats
    for i in range(5):
        decision = Decision(
            id=uuid4(),
            group_id=-1001234567890,
            user_id=987654321,
            message_id=1000 + i,
            risk_score=30 + i * 10,
            verdict=Verdict.ALLOW if i < 3 else Verdict.WATCH,
            threat_type="spam" if i >= 3 else None,
            processing_time_ms=50 + i * 10,
        )
        test_session.add(decision)

    await test_session.commit()

    return {
        "group": group,
        "admin_user": user,
        "regular_user": user2,
        "admin_member": admin_member,
        "regular_member": regular_member,
    }


@pytest.fixture
async def test_app(session_factory, seed_test_data):
    """Create test application with seeded data."""

    # Create admin checker that checks test data
    async def admin_checker(user_id: int, chat_id: int) -> bool:
        # Admin user ID is 123456789, admin for group -1001234567890
        return user_id == 123456789 and chat_id == -1001234567890

    app = await create_test_app(session_factory, admin_checker)
    return app


@pytest.fixture
async def client(test_app):
    """Create test client."""
    async with TestClient(TestServer(test_app)) as client:
        yield client


# =============================================================================
# Authentication Tests
# =============================================================================


class TestAuthentication:
    """Test WebApp authentication."""

    @pytest.mark.asyncio
    async def test_unauthenticated_request_rejected(self, client):
        """Test that requests without auth are rejected."""
        resp = await client.get("/api/groups/-1001234567890/settings")
        assert resp.status == 401

        data = await resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "UNAUTHORIZED"

    @pytest.mark.asyncio
    async def test_invalid_init_data_rejected(self, client):
        """Test that invalid init data is rejected."""
        headers = {"X-Telegram-Init-Data": "invalid_data"}
        resp = await client.get("/api/groups/-1001234567890/settings", headers=headers)
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_expired_init_data_rejected(self, client):
        """Test that expired init data is rejected."""
        # Create init data from 2 days ago
        old_time = int(time.time()) - (2 * 24 * 60 * 60)
        init_data = generate_test_init_data(auth_date=old_time)

        headers = {"X-Telegram-Init-Data": init_data}
        resp = await client.get("/api/groups/-1001234567890/settings", headers=headers)
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_valid_auth_accepted(self, client):
        """Test that valid auth is accepted."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get("/api/groups/-1001234567890/settings", headers=headers)
        # Should get 200 OK (admin user accessing their group)
        assert resp.status == 200


# =============================================================================
# Admin Permission Tests
# =============================================================================


class TestAdminPermissions:
    """Test admin permission checks."""

    @pytest.mark.asyncio
    async def test_admin_can_access_settings(self, client):
        """Test that admins can access group settings."""
        # User 123456789 is admin of group -1001234567890
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get("/api/groups/-1001234567890/settings", headers=headers)
        assert resp.status == 200

        data = await resp.json()
        assert data["success"] is True
        assert data["data"]["group_id"] == -1001234567890

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, client):
        """Test that non-admins are forbidden from admin endpoints."""
        # User 987654321 is NOT admin
        init_data = generate_test_init_data(user_id=987654321)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get("/api/groups/-1001234567890/settings", headers=headers)
        assert resp.status == 403

        data = await resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_admin_of_other_group_forbidden(self, client):
        """Test that admin of one group can't access another."""
        # User 123456789 is admin of -1001234567890, not -1009999999999
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get("/api/groups/-1009999999999/settings", headers=headers)
        # Should be 404 (group not found) or 403 (forbidden)
        assert resp.status in (403, 404)


# =============================================================================
# Group Settings Tests
# =============================================================================


class TestGroupSettings:
    """Test group settings endpoints."""

    @pytest.mark.asyncio
    async def test_get_group_settings(self, client):
        """Test getting group settings."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get("/api/groups/-1001234567890/settings", headers=headers)
        assert resp.status == 200

        data = await resp.json()
        assert data["success"] is True
        settings = data["data"]
        assert settings["group_id"] == -1001234567890
        assert settings["title"] == "Test Group"
        assert settings["group_type"] == "general"
        assert settings["sensitivity"] == 5
        assert settings["sandbox_enabled"] is True

    @pytest.mark.asyncio
    async def test_update_group_settings(self, client):
        """Test updating group settings."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        # Update settings
        update_data = {
            "group_type": "tech",
            "sensitivity": 7,
            "sandbox_enabled": False,
        }

        resp = await client.put(
            "/api/groups/-1001234567890/settings",
            json=update_data,
            headers=headers,
        )
        assert resp.status == 200

        data = await resp.json()
        assert data["success"] is True
        settings = data["data"]
        assert settings["group_type"] == "tech"
        assert settings["sensitivity"] == 7
        assert settings["sandbox_enabled"] is False

    @pytest.mark.asyncio
    async def test_update_settings_validation(self, client):
        """Test settings validation."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        # Invalid group_type
        update_data = {"group_type": "invalid_type"}

        resp = await client.put(
            "/api/groups/-1001234567890/settings",
            json=update_data,
            headers=headers,
        )
        # Should fail validation
        assert resp.status in (400, 422, 500)

    @pytest.mark.asyncio
    async def test_get_nonexistent_group(self, client):
        """Test getting settings for nonexistent group."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get("/api/groups/-1009999999999/settings", headers=headers)
        # Either forbidden (user is not admin) or not found
        assert resp.status in (403, 404)

    @pytest.mark.asyncio
    async def test_invalid_group_id_format(self, client):
        """Test with invalid group ID format."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get("/api/groups/not_a_number/settings", headers=headers)
        assert resp.status == 422 or resp.status == 400


# =============================================================================
# Group Stats Tests
# =============================================================================


class TestGroupStats:
    """Test group statistics endpoint."""

    @pytest.mark.asyncio
    async def test_get_group_stats(self, client):
        """Test getting group statistics."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get("/api/groups/-1001234567890/stats", headers=headers)
        assert resp.status == 200

        data = await resp.json()
        assert data["success"] is True
        stats = data["data"]
        assert stats["group_id"] == -1001234567890
        assert stats["period_days"] == 7
        assert "total_messages" in stats
        assert "allowed" in stats
        assert "blocked" in stats
        assert "fp_rate" in stats

    @pytest.mark.asyncio
    async def test_get_stats_with_period(self, client):
        """Test getting stats with custom period."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get(
            "/api/groups/-1001234567890/stats?period_days=30",
            headers=headers,
        )
        assert resp.status == 200

        data = await resp.json()
        assert data["data"]["period_days"] == 30

    @pytest.mark.asyncio
    async def test_stats_period_clamped(self, client):
        """Test that period is clamped to valid range."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        # Request 365 days, should be clamped to 90
        resp = await client.get(
            "/api/groups/-1001234567890/stats?period_days=365",
            headers=headers,
        )
        assert resp.status == 200

        data = await resp.json()
        assert data["data"]["period_days"] == 90


# =============================================================================
# Review Queue Tests
# =============================================================================


class TestReviewQueue:
    """Test review queue endpoints."""

    @pytest.mark.asyncio
    async def test_get_review_queue(self, client):
        """Test getting the review queue."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get("/api/groups/-1001234567890/reviews", headers=headers)
        assert resp.status == 200

        data = await resp.json()
        assert data["success"] is True
        assert "items" in data["data"]
        assert "total" in data["data"]

    @pytest.mark.asyncio
    async def test_review_queue_pagination(self, client):
        """Test review queue pagination."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get(
            "/api/groups/-1001234567890/reviews?limit=10&offset=0",
            headers=headers,
        )
        assert resp.status == 200

        data = await resp.json()
        assert data["data"]["limit"] == 10
        assert data["data"]["offset"] == 0


# =============================================================================
# Decisions Tests
# =============================================================================


class TestDecisions:
    """Test decision endpoints."""

    @pytest.mark.asyncio
    async def test_get_decisions(self, client):
        """Test getting decisions list."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get("/api/groups/-1001234567890/decisions", headers=headers)
        assert resp.status == 200

        data = await resp.json()
        assert data["success"] is True
        assert "decisions" in data["data"]

    @pytest.mark.asyncio
    async def test_get_decisions_with_verdict_filter(self, client):
        """Test filtering decisions by verdict."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get(
            "/api/groups/-1001234567890/decisions?verdict=allow",
            headers=headers,
        )
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_get_decisions_invalid_verdict(self, client):
        """Test with invalid verdict filter."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get(
            "/api/groups/-1001234567890/decisions?verdict=invalid",
            headers=headers,
        )
        # Should fail with validation error
        assert resp.status in (400, 422)


# =============================================================================
# User Management Tests
# =============================================================================


class TestUserManagement:
    """Test user management endpoints."""

    @pytest.mark.asyncio
    async def test_get_user_profile(self, client):
        """Test getting user profile in group."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        # Get profile for user 987654321 in the group
        resp = await client.get(
            "/api/groups/-1001234567890/users/987654321",
            headers=headers,
        )
        assert resp.status == 200

        data = await resp.json()
        assert data["success"] is True
        profile = data["data"]
        assert profile["user_id"] == 987654321
        assert "trust_level" in profile
        assert "trust_score" in profile

    @pytest.mark.asyncio
    async def test_get_nonexistent_user(self, client):
        """Test getting profile for nonexistent user."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.get(
            "/api/groups/-1001234567890/users/999999999",
            headers=headers,
        )
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_whitelist_user(self, client):
        """Test whitelisting a user."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.post(
            "/api/groups/-1001234567890/users/987654321/whitelist",
            json={"reason": "Verified user"},
            headers=headers,
        )
        assert resp.status == 200

        data = await resp.json()
        assert data["success"] is True
        assert data["data"]["action"] == "whitelisted"

    @pytest.mark.asyncio
    async def test_blacklist_user(self, client):
        """Test blacklisting a user."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        resp = await client.post(
            "/api/groups/-1001234567890/users/987654321/blacklist",
            json={"reason": "Spam"},
            headers=headers,
        )
        assert resp.status == 200

        data = await resp.json()
        assert data["success"] is True
        assert data["data"]["action"] == "blacklisted"


# =============================================================================
# Health Check (no auth required)
# =============================================================================


class TestHealthCheck:
    """Test health check endpoint (excluded from auth)."""

    @pytest.mark.asyncio
    async def test_health_check_excluded_from_auth(self, client):
        """Test that health check doesn't require auth."""
        # Note: This test assumes /api/health endpoint exists
        # If it doesn't, this test documents expected behavior
        resp = await client.get("/api/health")
        # Should not be 401 (might be 404 if endpoint not implemented)
        assert resp.status != 401


# =============================================================================
# CORS Tests
# =============================================================================


class TestCORS:
    """Test CORS headers."""

    @pytest.mark.asyncio
    async def test_preflight_request(self, client):
        """Test CORS preflight OPTIONS request."""
        resp = await client.options(
            "/api/groups/-1001234567890/settings",
            headers={
                "Origin": "https://web.telegram.org",
                "Access-Control-Request-Method": "GET",
            },
        )
        # OPTIONS should return 204 or 200
        assert resp.status in (200, 204)

    @pytest.mark.asyncio
    async def test_cors_headers_on_response(self, client):
        """Test CORS headers are added to responses."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {
            "X-Telegram-Init-Data": init_data,
            "Origin": "https://web.telegram.org",
        }

        resp = await client.get("/api/groups/-1001234567890/settings", headers=headers)

        # Note: With wildcard CORS, origin might be "*"
        assert (
            "Access-Control-Allow-Origin" in resp.headers
            or resp.headers.get("Access-Control-Allow-Origin") == "*"
        )


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_negative_group_id_handling(self, client):
        """Test that negative group IDs (Telegram groups) work correctly."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        # Telegram groups have negative IDs
        resp = await client.get("/api/groups/-1001234567890/settings", headers=headers)
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_malformed_json_body(self, client):
        """Test handling of malformed JSON in request body."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {
            "X-Telegram-Init-Data": init_data,
            "Content-Type": "application/json",
        }

        resp = await client.put(
            "/api/groups/-1001234567890/settings",
            data="not valid json",
            headers=headers,
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_empty_request_body(self, client):
        """Test handling of empty request body where expected."""
        init_data = generate_test_init_data(user_id=123456789)
        headers = {"X-Telegram-Init-Data": init_data}

        # PUT with empty body should work (no changes)
        resp = await client.put(
            "/api/groups/-1001234567890/settings",
            json={},
            headers=headers,
        )
        assert resp.status == 200
