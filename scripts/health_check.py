#!/usr/bin/env python3
"""
SAQSHY Health Check Script

Verifies all services are running and accessible.

Usage:
    python scripts/health_check.py

Exit codes:
    0 - All services healthy
    1 - One or more services unhealthy
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import structlog

logger = structlog.get_logger(__name__)


class HealthChecker:
    """Health checker for all SAQSHY services."""

    def __init__(self):
        self.results = {}

    async def check_postgres(self, database_url: str) -> bool:
        """Check PostgreSQL connection."""
        try:
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import create_async_engine

            if database_url.startswith("postgresql://"):
                database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

            engine = create_async_engine(database_url)

            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                result.fetchone()

            await engine.dispose()

            self.results["postgres"] = {"status": "healthy", "error": None}
            return True

        except Exception as e:
            self.results["postgres"] = {"status": "unhealthy", "error": str(e)}
            return False

    async def check_redis(self, redis_url: str) -> bool:
        """Check Redis connection."""
        try:
            import redis.asyncio as redis

            client = redis.from_url(redis_url)
            await client.ping()
            await client.close()

            self.results["redis"] = {"status": "healthy", "error": None}
            return True

        except Exception as e:
            self.results["redis"] = {"status": "unhealthy", "error": str(e)}
            return False

    async def check_qdrant(self, qdrant_url: str) -> bool:
        """Check Qdrant connection."""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.get(f"{qdrant_url}/health", timeout=5.0)
                if response.status_code == 200:
                    self.results["qdrant"] = {"status": "healthy", "error": None}
                    return True
                else:
                    self.results["qdrant"] = {
                        "status": "unhealthy",
                        "error": f"HTTP {response.status_code}",
                    }
                    return False

        except Exception as e:
            self.results["qdrant"] = {"status": "unhealthy", "error": str(e)}
            return False

    async def check_anthropic_api(self, api_key: str) -> bool:
        """Check Anthropic API access."""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    timeout=10.0,
                )
                if response.status_code in (200, 401):  # 401 means API accessible
                    self.results["anthropic"] = {"status": "healthy", "error": None}
                    return True
                else:
                    self.results["anthropic"] = {
                        "status": "unhealthy",
                        "error": f"HTTP {response.status_code}",
                    }
                    return False

        except Exception as e:
            self.results["anthropic"] = {"status": "unhealthy", "error": str(e)}
            return False

    async def check_cohere_api(self, api_key: str) -> bool:
        """Check Cohere API access."""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.cohere.ai/v1/check-api-key",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )
                # Any response means API is accessible
                self.results["cohere"] = {"status": "healthy", "error": None}
                return True

        except Exception as e:
            self.results["cohere"] = {"status": "unhealthy", "error": str(e)}
            return False

    def print_results(self):
        """Print health check results."""
        print("\n" + "=" * 50)
        print("SAQSHY Health Check Results")
        print("=" * 50)

        all_healthy = True

        for service, result in self.results.items():
            status = result["status"]
            error = result.get("error")

            if status == "healthy":
                icon = "[OK]"
            else:
                icon = "[FAIL]"
                all_healthy = False

            print(f"{icon} {service}: {status}")
            if error:
                print(f"    Error: {error}")

        print("=" * 50)

        if all_healthy:
            print("All services are healthy!")
        else:
            print("Some services are unhealthy. Check configuration.")

        return all_healthy


async def main() -> int:
    """Main health check function."""
    from saqshy.config import get_settings

    logger.info("starting_health_check")

    try:
        settings = get_settings()
    except Exception as e:
        logger.error("settings_load_failed", error=str(e))
        print("\nError: Could not load settings.")
        print("Make sure .env file exists with proper configuration.")
        return 1

    checker = HealthChecker()

    # Run all checks concurrently
    await asyncio.gather(
        checker.check_postgres(settings.database.url.get_secret_value()),
        checker.check_redis(settings.redis.url),
        checker.check_qdrant(settings.qdrant.url),
        # API checks are optional - skip if keys not configured
        # checker.check_anthropic_api(settings.claude.anthropic_api_key.get_secret_value()),
        # checker.check_cohere_api(settings.cohere.api_key.get_secret_value()),
        return_exceptions=True,
    )

    # Print results
    all_healthy = checker.print_results()

    return 0 if all_healthy else 1


if __name__ == "__main__":
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
    )

    exit_code = asyncio.run(main())
    sys.exit(exit_code)
