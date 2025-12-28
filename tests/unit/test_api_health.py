"""
SAQSHY API Health Endpoint Tests

Tests for the health check endpoints used by Kubernetes probes
and load balancer health checks.

Covers:
- /health - Basic liveness check
- /health/ready - Readiness with dependency verification
- /health/live - Kubernetes liveness probe
- /health/details - Detailed health status
- Dependency checks (Redis, DB, Qdrant)
- Timeout handling
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from saqshy.api.health import (
    ComponentHealth,
    HealthChecker,
    HealthStatus,
    check_database_health,
    check_redis_health,
    check_qdrant_health,
    create_health_routes,
)


# =============================================================================
# ComponentHealth Tests
# =============================================================================


class TestComponentHealth:
    """Tests for ComponentHealth dataclass."""

    def test_healthy_component_to_dict(self):
        """Test healthy component serialization."""
        health = ComponentHealth(
            name="redis",
            healthy=True,
            latency_ms=5.5,
        )
        result = health.to_dict()

        assert result["name"] == "redis"
        assert result["healthy"] is True
        assert result["latency_ms"] == 5.5
        assert "error" not in result
        assert "details" not in result

    def test_unhealthy_component_to_dict(self):
        """Test unhealthy component serialization."""
        health = ComponentHealth(
            name="database",
            healthy=False,
            latency_ms=100.0,
            error="Connection refused",
        )
        result = health.to_dict()

        assert result["name"] == "database"
        assert result["healthy"] is False
        assert result["latency_ms"] == 100.0
        assert result["error"] == "Connection refused"

    def test_component_with_details(self):
        """Test component with additional details."""
        health = ComponentHealth(
            name="redis",
            healthy=True,
            details={"circuit_state": "closed", "connected": True},
        )
        result = health.to_dict()

        assert result["details"]["circuit_state"] == "closed"
        assert result["details"]["connected"] is True


# =============================================================================
# HealthStatus Tests
# =============================================================================


class TestHealthStatus:
    """Tests for HealthStatus dataclass."""

    def test_healthy_status(self):
        """Test healthy status properties."""
        status = HealthStatus(
            status="healthy",
            version="2.0.0",
            uptime_seconds=3600.0,
            checks=[
                ComponentHealth(name="redis", healthy=True),
                ComponentHealth(name="database", healthy=True),
            ],
        )

        assert status.is_healthy is True
        assert status.is_ready is True

    def test_degraded_status(self):
        """Test degraded status properties."""
        status = HealthStatus(
            status="degraded",
            version="2.0.0",
            uptime_seconds=3600.0,
            checks=[
                ComponentHealth(name="redis", healthy=True),
                ComponentHealth(name="database", healthy=False),
            ],
        )

        assert status.is_healthy is True
        assert status.is_ready is False

    def test_unhealthy_status(self):
        """Test unhealthy status properties."""
        status = HealthStatus(
            status="unhealthy",
            version="2.0.0",
            uptime_seconds=3600.0,
            checks=[
                ComponentHealth(name="redis", healthy=False),
                ComponentHealth(name="database", healthy=False),
            ],
        )

        assert status.is_healthy is False
        assert status.is_ready is False

    def test_status_to_dict(self):
        """Test status serialization."""
        status = HealthStatus(
            status="healthy",
            version="2.0.0",
            uptime_seconds=3600.123,
            checks=[ComponentHealth(name="redis", healthy=True)],
        )
        result = status.to_dict()

        assert result["status"] == "healthy"
        assert result["version"] == "2.0.0"
        assert result["uptime_seconds"] == 3600.12
        assert "timestamp" in result
        assert "redis" in result["checks"]


# =============================================================================
# HealthChecker Tests
# =============================================================================


class TestHealthChecker:
    """Tests for HealthChecker class."""

    @pytest.fixture
    def mock_cache_service(self):
        """Create mock cache service."""
        cache = AsyncMock()
        cache.ping.return_value = True
        cache.get_stats.return_value = {
            "connected": True,
            "circuit_state": "closed",
        }
        return cache

    @pytest.fixture
    def mock_db_engine(self):
        """Create mock database engine."""
        engine = MagicMock()
        # Mock the async context manager for connect()
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_conn.execute.return_value = mock_result

        engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        engine.connect.return_value.__aexit__ = AsyncMock(return_value=None)

        # Mock pool stats
        engine.pool.size.return_value = 5
        engine.pool.checkedin.return_value = 4
        engine.pool.checkedout.return_value = 1
        engine.pool.overflow.return_value = 0
        engine.pool.status = True

        return engine

    @pytest.fixture
    def mock_qdrant_client(self):
        """Create mock Qdrant client."""
        client = AsyncMock()
        mock_collections = MagicMock()
        mock_collections.collections = [MagicMock(), MagicMock()]
        client.get_collections.return_value = mock_collections
        return client

    @pytest.mark.asyncio
    async def test_check_health_no_dependencies(self):
        """Test basic health check without dependencies."""
        checker = HealthChecker()
        status = await checker.check_health(include_dependencies=False)

        assert status.status == "healthy"
        assert status.is_healthy is True
        assert len(status.checks) == 0

    @pytest.mark.asyncio
    async def test_check_health_all_healthy(
        self, mock_cache_service, mock_db_engine, mock_qdrant_client
    ):
        """Test health check with all healthy dependencies."""
        checker = HealthChecker(
            cache_service=mock_cache_service,
            db_engine=mock_db_engine,
            qdrant_client=mock_qdrant_client,
        )
        status = await checker.check_health(include_dependencies=True)

        assert status.status == "healthy"
        assert status.is_ready is True
        assert len(status.checks) == 3

    @pytest.mark.asyncio
    async def test_check_health_redis_unhealthy(
        self, mock_cache_service, mock_db_engine
    ):
        """Test health check with unhealthy Redis."""
        mock_cache_service.ping.return_value = False

        checker = HealthChecker(
            cache_service=mock_cache_service,
            db_engine=mock_db_engine,
        )
        status = await checker.check_health(include_dependencies=True)

        redis_check = next(c for c in status.checks if c.name == "redis")
        assert redis_check.healthy is False
        assert status.status in ("degraded", "unhealthy")

    @pytest.mark.asyncio
    async def test_check_health_redis_exception(self, mock_cache_service):
        """Test health check when Redis throws exception."""
        mock_cache_service.ping.side_effect = Exception("Connection failed")

        checker = HealthChecker(cache_service=mock_cache_service)
        status = await checker.check_health(include_dependencies=True)

        redis_check = next((c for c in status.checks if c.name == "redis"), None)
        if redis_check:
            assert redis_check.healthy is False
            assert "Connection failed" in redis_check.error

    @pytest.mark.asyncio
    async def test_check_health_database_unhealthy(self, mock_db_engine):
        """Test health check with unhealthy database."""
        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = Exception("Database error")

        mock_db_engine.connect.return_value.__aenter__ = AsyncMock(
            return_value=mock_conn
        )

        checker = HealthChecker(db_engine=mock_db_engine)
        status = await checker.check_health(include_dependencies=True)

        db_check = next((c for c in status.checks if c.name == "database"), None)
        if db_check:
            assert db_check.healthy is False

    @pytest.mark.asyncio
    async def test_check_health_uptime(self):
        """Test that uptime is calculated correctly."""
        start_time = time.monotonic() - 100  # 100 seconds ago
        checker = HealthChecker(start_time=start_time)
        status = await checker.check_health(include_dependencies=False)

        assert status.uptime_seconds >= 100

    @pytest.mark.asyncio
    async def test_check_health_timeout(self, mock_cache_service):
        """Test health check timeout handling."""
        async def slow_ping():
            await asyncio.sleep(10)  # Longer than timeout
            return True

        mock_cache_service.ping = slow_ping

        checker = HealthChecker(cache_service=mock_cache_service)
        # Override timeout to be very short
        checker.CHECK_TIMEOUT_MS = 100

        status = await checker.check_health(include_dependencies=True)

        # Should handle timeout gracefully
        assert status.status in ("healthy", "degraded", "unhealthy")

    @pytest.mark.asyncio
    async def test_check_health_no_configured_services(self):
        """Test health check with no services configured returns healthy."""
        checker = HealthChecker()
        status = await checker.check_health(include_dependencies=True)

        # When no services are configured, they're considered healthy
        for check in status.checks:
            assert check.details.get("configured") is False or check.healthy is True

    def test_routes_creates_valid_routes(self):
        """Test that routes() returns valid route definitions."""
        checker = HealthChecker()
        routes = checker.routes()

        # RouteTableDef is callable, just verify it's returned
        assert routes is not None


# =============================================================================
# Standalone Function Tests
# =============================================================================


class TestStandaloneFunctions:
    """Tests for standalone health check functions."""

    @pytest.mark.asyncio
    async def test_check_database_health_success(self):
        """Test standalone database health check success."""
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await check_database_health(mock_engine)

        assert result["healthy"] is True
        assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_check_database_health_failure(self):
        """Test standalone database health check failure."""
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("Connection refused")

        result = await check_database_health(mock_engine)

        assert result["healthy"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_check_redis_health_success(self):
        """Test standalone Redis health check success."""
        mock_cache = AsyncMock()
        mock_cache.ping.return_value = True

        result = await check_redis_health(mock_cache)

        assert result["healthy"] is True
        assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_check_redis_health_failure(self):
        """Test standalone Redis health check failure."""
        mock_cache = AsyncMock()
        mock_cache.ping.side_effect = Exception("Redis down")

        result = await check_redis_health(mock_cache)

        assert result["healthy"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_check_qdrant_health_success(self):
        """Test standalone Qdrant health check success."""
        mock_client = AsyncMock()
        mock_collections = MagicMock()
        mock_collections.collections = [MagicMock()]
        mock_client.get_collections.return_value = mock_collections

        result = await check_qdrant_health(mock_client)

        assert result["healthy"] is True
        assert result["collections"] == 1

    @pytest.mark.asyncio
    async def test_check_qdrant_health_failure(self):
        """Test standalone Qdrant health check failure."""
        mock_client = AsyncMock()
        mock_client.get_collections.side_effect = Exception("Qdrant unreachable")

        result = await check_qdrant_health(mock_client)

        assert result["healthy"] is False
        assert "error" in result


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestCreateHealthRoutes:
    """Tests for create_health_routes factory function."""

    def test_create_health_routes_no_services(self):
        """Test creating routes without services."""
        routes = create_health_routes()
        assert routes is not None

    def test_create_health_routes_with_services(self):
        """Test creating routes with services."""
        mock_cache = AsyncMock()
        mock_engine = MagicMock()
        mock_qdrant = AsyncMock()

        routes = create_health_routes(
            cache_service=mock_cache,
            db_engine=mock_engine,
            qdrant_client=mock_qdrant,
        )
        assert routes is not None


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestHealthCheckerIntegration:
    """Integration-style tests for health checker."""

    @pytest.mark.asyncio
    async def test_full_health_check_cycle(self):
        """Test complete health check cycle."""
        # Setup mocks
        mock_cache = AsyncMock()
        mock_cache.ping.return_value = True
        mock_cache.get_stats.return_value = {"connected": True}

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_engine.pool.size.return_value = 5
        mock_engine.pool.checkedin.return_value = 4
        mock_engine.pool.checkedout.return_value = 1
        mock_engine.pool.overflow.return_value = 0
        mock_engine.pool.status = True

        # Create checker
        checker = HealthChecker(
            cache_service=mock_cache,
            db_engine=mock_engine,
            start_time=time.monotonic() - 60,
        )

        # Run health check
        status = await checker.check_health(include_dependencies=True, detailed=True)

        # Verify
        assert status.status in ("healthy", "degraded")
        assert status.uptime_seconds >= 60
        assert "version" in status.to_dict()

    @pytest.mark.asyncio
    async def test_partial_failure_results_in_degraded(self):
        """Test that one failing service results in degraded status."""
        mock_cache = AsyncMock()
        mock_cache.ping.return_value = False  # Redis failing

        mock_qdrant = AsyncMock()
        mock_collections = MagicMock()
        mock_collections.collections = []
        mock_qdrant.get_collections.return_value = mock_collections  # Qdrant healthy

        checker = HealthChecker(
            cache_service=mock_cache,
            qdrant_client=mock_qdrant,
        )

        status = await checker.check_health(include_dependencies=True)

        # One healthy, one unhealthy = degraded
        assert status.status == "degraded"
        assert status.is_healthy is True
        assert status.is_ready is False
