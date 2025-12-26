"""
SAQSHY Health Check Endpoints

Production-grade health check endpoints for:
- Kubernetes liveness/readiness probes
- Load balancer health checks
- Dependency status monitoring

Endpoints:
- /health - Basic liveness check (always responds if service is running)
- /health/ready - Readiness check with dependency verification
- /health/live - Kubernetes liveness probe (lightweight)

Example:
    >>> app = web.Application()
    >>> health = HealthChecker(...)
    >>> app.router.add_routes(health.routes())
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aiohttp import web

from saqshy import __version__
from saqshy.core.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Health Status Types
# =============================================================================


@dataclass
class ComponentHealth:
    """Health status of a single component."""

    name: str
    healthy: bool
    latency_ms: float | None = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "name": self.name,
            "healthy": self.healthy,
        }
        if self.latency_ms is not None:
            result["latency_ms"] = round(self.latency_ms, 2)
        if self.error:
            result["error"] = self.error
        if self.details:
            result["details"] = self.details
        return result


@dataclass
class HealthStatus:
    """Overall health status."""

    status: str  # "healthy", "degraded", "unhealthy"
    version: str
    uptime_seconds: float
    checks: list[ComponentHealth] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def is_healthy(self) -> bool:
        """Check if all critical components are healthy."""
        return self.status in ("healthy", "degraded")

    @property
    def is_ready(self) -> bool:
        """Check if service is ready to accept traffic."""
        return self.status == "healthy"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "status": self.status,
            "version": self.version,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "timestamp": self.timestamp,
            "checks": {c.name: c.to_dict() for c in self.checks},
        }


# =============================================================================
# Health Checker
# =============================================================================


class HealthChecker:
    """
    Health check manager for SAQSHY services.

    Provides endpoints for Kubernetes probes and load balancer health checks.
    Checks are designed to be:
    - Fast (no heavy operations on hot path)
    - Non-blocking (async with timeouts)
    - Informative (detailed status for debugging)

    Example:
        >>> from saqshy.api.health import HealthChecker
        >>> health = HealthChecker(
        ...     cache_service=cache,
        ...     db_engine=engine,
        ...     qdrant_client=qdrant,
        ... )
        >>> app.router.add_routes(health.routes())
    """

    # Timeout for individual health checks (milliseconds)
    # Keep low (2s) to avoid blocking readiness probes
    CHECK_TIMEOUT_MS = 2000

    def __init__(
        self,
        cache_service: Any | None = None,
        db_engine: Any | None = None,
        qdrant_client: Any | None = None,
        start_time: float | None = None,
    ) -> None:
        """
        Initialize health checker.

        Args:
            cache_service: CacheService instance for Redis checks.
            db_engine: SQLAlchemy AsyncEngine for database checks.
            qdrant_client: Qdrant client for vector DB checks.
            start_time: Service start time for uptime calculation.
        """
        self.cache_service = cache_service
        self.db_engine = db_engine
        self.qdrant_client = qdrant_client
        self._start_time = start_time or time.monotonic()

    def routes(self) -> web.RouteTableDef:
        """
        Create route table for health endpoints.

        Returns:
            RouteTableDef with health check routes.
        """
        routes = web.RouteTableDef()

        @routes.get("/health")
        async def health_check(request: web.Request) -> web.Response:
            """
            Basic health check endpoint.

            Returns 200 if the service is running, regardless of dependencies.
            Used by load balancers for basic availability checks.
            """
            status = await self.check_health(include_dependencies=False)
            return web.json_response(
                status.to_dict(),
                status=200 if status.is_healthy else 503,
            )

        @routes.get("/health/ready")
        async def readiness_check(request: web.Request) -> web.Response:
            """
            Readiness check with dependency verification.

            Returns 200 only if all critical dependencies are healthy.
            Used by Kubernetes readiness probes to control traffic routing.
            """
            status = await self.check_health(include_dependencies=True)
            return web.json_response(
                status.to_dict(),
                status=200 if status.is_ready else 503,
            )

        @routes.get("/health/live")
        async def liveness_check(request: web.Request) -> web.Response:
            """
            Kubernetes liveness probe.

            Returns 200 if the service process is alive.
            Very lightweight - no dependency checks.
            """
            return web.json_response(
                {
                    "status": "alive",
                    "version": __version__,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

        @routes.get("/health/details")
        async def detailed_health(request: web.Request) -> web.Response:
            """
            Detailed health status with all component information.

            For debugging and monitoring dashboards.
            """
            status = await self.check_health(include_dependencies=True, detailed=True)
            return web.json_response(
                status.to_dict(),
                status=200 if status.is_healthy else 503,
            )

        return routes

    async def check_health(
        self,
        include_dependencies: bool = True,
        detailed: bool = False,
    ) -> HealthStatus:
        """
        Perform health check.

        Args:
            include_dependencies: Whether to check dependencies.
            detailed: Whether to include detailed information.

        Returns:
            HealthStatus with check results.
        """
        uptime = time.monotonic() - self._start_time
        checks: list[ComponentHealth] = []

        if include_dependencies:
            # Run all checks in parallel with timeout
            check_tasks = [
                self._check_redis(),
                self._check_database(),
                self._check_qdrant(),
            ]

            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*check_tasks, return_exceptions=True),
                    timeout=self.CHECK_TIMEOUT_MS / 1000,
                )

                for result in results:
                    if isinstance(result, ComponentHealth):
                        checks.append(result)
                    elif isinstance(result, Exception):
                        logger.warning(
                            "health_check_exception",
                            error=str(result),
                        )

            except TimeoutError:
                logger.warning("health_checks_timeout")
                checks.append(
                    ComponentHealth(
                        name="overall",
                        healthy=False,
                        error="Health check timeout",
                    )
                )

        # Determine overall status
        if not checks or all(c.healthy for c in checks):
            status = "healthy"
        elif any(c.healthy for c in checks):
            status = "degraded"
        else:
            status = "unhealthy"

        return HealthStatus(
            status=status,
            version=__version__,
            uptime_seconds=uptime,
            checks=checks,
        )

    async def _check_redis(self) -> ComponentHealth:
        """Check Redis connectivity."""
        if self.cache_service is None:
            return ComponentHealth(
                name="redis",
                healthy=True,
                details={"configured": False},
            )

        start = time.monotonic()
        try:
            is_healthy = await self.cache_service.ping()
            latency = (time.monotonic() - start) * 1000

            stats = await self.cache_service.get_stats()

            return ComponentHealth(
                name="redis",
                healthy=is_healthy,
                latency_ms=latency,
                details={
                    "connected": stats.get("connected", False),
                    "circuit_state": stats.get("circuit_state", "unknown"),
                },
            )

        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return ComponentHealth(
                name="redis",
                healthy=False,
                latency_ms=latency,
                error=str(e),
            )

    async def _check_database(self) -> ComponentHealth:
        """Check PostgreSQL connectivity."""
        if self.db_engine is None:
            return ComponentHealth(
                name="database",
                healthy=True,
                details={"configured": False},
            )

        start = time.monotonic()
        try:
            from sqlalchemy import text

            async with self.db_engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                result.close()

            latency = (time.monotonic() - start) * 1000

            # Get pool stats if available
            pool_status = {}
            if hasattr(self.db_engine.pool, "status"):
                pool_status = {
                    "pool_size": self.db_engine.pool.size(),
                    "checked_in": self.db_engine.pool.checkedin(),
                    "checked_out": self.db_engine.pool.checkedout(),
                    "overflow": self.db_engine.pool.overflow(),
                }

            return ComponentHealth(
                name="database",
                healthy=True,
                latency_ms=latency,
                details=pool_status,
            )

        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return ComponentHealth(
                name="database",
                healthy=False,
                latency_ms=latency,
                error=str(e),
            )

    async def _check_qdrant(self) -> ComponentHealth:
        """Check Qdrant vector database connectivity."""
        if self.qdrant_client is None:
            return ComponentHealth(
                name="qdrant",
                healthy=True,
                details={"configured": False},
            )

        start = time.monotonic()
        try:
            # Get collection info

            collections = await self.qdrant_client.get_collections()
            latency = (time.monotonic() - start) * 1000

            return ComponentHealth(
                name="qdrant",
                healthy=True,
                latency_ms=latency,
                details={
                    "collections": len(collections.collections),
                },
            )

        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            return ComponentHealth(
                name="qdrant",
                healthy=False,
                latency_ms=latency,
                error=str(e),
            )


# =============================================================================
# Standalone Functions
# =============================================================================


async def check_database_health(engine: Any) -> dict[str, Any]:
    """
    Check database health as a standalone function.

    Args:
        engine: SQLAlchemy AsyncEngine.

    Returns:
        Health status dictionary.
    """
    start = time.monotonic()
    try:
        from sqlalchemy import text

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

        return {
            "healthy": True,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
        }

    except Exception as e:
        return {
            "healthy": False,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
            "error": str(e),
        }


async def check_redis_health(cache_service: Any) -> dict[str, Any]:
    """
    Check Redis health as a standalone function.

    Args:
        cache_service: CacheService instance.

    Returns:
        Health status dictionary.
    """
    start = time.monotonic()
    try:
        is_healthy = await cache_service.ping()
        return {
            "healthy": is_healthy,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
        }

    except Exception as e:
        return {
            "healthy": False,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
            "error": str(e),
        }


async def check_qdrant_health(qdrant_client: Any) -> dict[str, Any]:
    """
    Check Qdrant health as a standalone function.

    Args:
        qdrant_client: Qdrant AsyncClient.

    Returns:
        Health status dictionary.
    """
    start = time.monotonic()
    try:
        collections = await qdrant_client.get_collections()
        return {
            "healthy": True,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
            "collections": len(collections.collections),
        }

    except Exception as e:
        return {
            "healthy": False,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
            "error": str(e),
        }


# =============================================================================
# Factory Function
# =============================================================================


def create_health_routes(
    cache_service: Any | None = None,
    db_engine: Any | None = None,
    qdrant_client: Any | None = None,
) -> web.RouteTableDef:
    """
    Create health check routes with dependencies.

    Convenience function for adding health checks to an aiohttp application.

    Args:
        cache_service: CacheService for Redis checks.
        db_engine: SQLAlchemy engine for database checks.
        qdrant_client: Qdrant client for vector DB checks.

    Returns:
        RouteTableDef to add to application.

    Example:
        >>> from saqshy.api.health import create_health_routes
        >>> app.router.add_routes(create_health_routes(
        ...     cache_service=cache,
        ...     db_engine=engine,
        ... ))
    """
    checker = HealthChecker(
        cache_service=cache_service,
        db_engine=db_engine,
        qdrant_client=qdrant_client,
    )
    return checker.routes()
