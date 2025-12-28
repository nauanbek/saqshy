#!/usr/bin/env python3
"""
SAQSHY Mini App Local Development Server

Runs the Mini App API locally for development and testing.
Includes mock data seeding and mock Telegram authentication bypass.

Usage:
    # Start with dev services (PostgreSQL, Redis on dev ports)
    python scripts/run_miniapp_local.py

    # Start with test services (different ports)
    python scripts/run_miniapp_local.py --test

    # Skip auth (all requests are authorized)
    python scripts/run_miniapp_local.py --no-auth

    # Seed mock data
    python scripts/run_miniapp_local.py --seed

    # Custom port
    python scripts/run_miniapp_local.py --port 8081

Environment Variables:
    DATABASE_URL - PostgreSQL connection URL
    REDIS_URL - Redis connection URL
    BOT_TOKEN - Telegram bot token (for auth validation)
"""

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aiohttp import web


async def create_mock_admin_checker():
    """Create a mock admin checker that allows everything."""
    async def check_admin(user_id: int, chat_id: int) -> bool:
        print(f"[MOCK] Admin check: user={user_id}, chat={chat_id} -> True")
        return True
    return check_admin


async def seed_mock_data(session):
    """Seed the database with mock data for testing."""
    from saqshy.core.types import GroupType, Verdict
    from saqshy.db.models import Decision, Group, GroupMember, TrustLevel, User

    print("Seeding mock data...")

    # Create test group
    group = Group(
        id=-1001234567890,
        title="Test Development Group",
        username="testdevgroup",
        group_type=GroupType.GENERAL,
        sensitivity=5,
        sandbox_enabled=True,
        sandbox_duration_hours=24,
        is_active=True,
    )
    session.add(group)

    # Create test admin user
    admin = User(
        id=123456789,
        username="testadmin",
        first_name="Test",
        last_name="Admin",
        is_bot=False,
        is_premium=True,
        has_photo=True,
    )
    session.add(admin)

    # Create admin membership
    admin_member = GroupMember(
        group_id=-1001234567890,
        user_id=123456789,
        trust_level=TrustLevel.ADMIN,
        trust_score=100,
        message_count=100,
    )
    session.add(admin_member)

    # Create some test users
    for i in range(5):
        user = User(
            id=200000000 + i,
            username=f"testuser{i}",
            first_name=f"User{i}",
            is_bot=False,
        )
        session.add(user)

        member = GroupMember(
            group_id=-1001234567890,
            user_id=200000000 + i,
            trust_level=TrustLevel.NEW if i < 2 else TrustLevel.ESTABLISHED,
            trust_score=50 + i * 10,
            message_count=i * 5,
        )
        session.add(member)

    # Create some decisions
    verdicts = [Verdict.ALLOW, Verdict.ALLOW, Verdict.WATCH, Verdict.LIMIT, Verdict.BLOCK]
    for i, verdict in enumerate(verdicts):
        decision = Decision(
            id=uuid4(),
            group_id=-1001234567890,
            user_id=200000000 + (i % 5),
            message_id=10000 + i,
            risk_score=10 + i * 20,
            verdict=verdict,
            threat_type="spam" if verdict in (Verdict.LIMIT, Verdict.BLOCK) else None,
            processing_time_ms=50 + i * 10,
        )
        session.add(decision)

    await session.commit()
    print("Mock data seeded successfully!")


async def run_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    db_url: str | None = None,
    redis_url: str | None = None,
    no_auth: bool = False,
    seed: bool = False,
):
    """Run the Mini App API server."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from saqshy.db import Base
    from saqshy.mini_app.auth import (
        create_auth_middleware,
        create_cors_middleware,
        create_rate_limit_middleware,
    )
    from saqshy.mini_app.routes import setup_routes

    # Default URLs for dev environment
    db_url = db_url or os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://saqshy:password@localhost:5433/saqshy"
    )

    print(f"Connecting to database: {db_url.split('@')[1] if '@' in db_url else db_url}")

    # Create engine
    engine = create_async_engine(db_url, echo=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables created/verified")

    # Create session factory
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Seed data if requested
    if seed:
        async with session_factory() as session:
            await seed_mock_data(session)

    # Create app
    app = web.Application()

    # Add CORS middleware (allow all for local dev)
    app.middlewares.append(create_cors_middleware(["*"]))

    # Add auth middleware (or skip for no-auth mode)
    bot_token = os.getenv("BOT_TOKEN", "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz")

    if no_auth:
        print("WARNING: Running in NO-AUTH mode - all requests are authorized!")

        @web.middleware
        async def mock_auth_middleware(request, handler):
            """Mock auth that always succeeds."""
            from saqshy.mini_app.auth import WebAppAuth, WebAppData, WebAppUser

            # Create mock auth for every request
            mock_user = WebAppUser(
                id=123456789,
                first_name="Test",
                last_name="Admin",
                username="testadmin",
            )
            mock_data = WebAppData(
                user=mock_user,
                auth_date=datetime.now(UTC),
            )

            # Create mock auth object
            class MockAuth:
                user_id = 123456789
                user = mock_user
                _data = mock_data

                async def is_admin(self, chat_id: int) -> bool:
                    return True

                async def validate(self) -> bool:
                    return True

            request["webapp_auth"] = MockAuth()
            request["user_id"] = 123456789
            request["user"] = mock_user

            return await handler(request)

        app.middlewares.append(mock_auth_middleware)
    else:
        admin_checker = await create_mock_admin_checker()
        app.middlewares.append(
            create_auth_middleware(
                bot_token,
                excluded_paths={"/api/health"},
                admin_checker=admin_checker,
            )
        )

    # Add rate limiting (relaxed for dev)
    app.middlewares.append(create_rate_limit_middleware(limit=1000, window_seconds=60))

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

    # Add health endpoint
    async def health_handler(request):
        return web.json_response({"status": "ok", "mode": "development"})

    app.router.add_get("/api/health", health_handler)

    # Setup Mini App routes
    setup_routes(app)

    # Print info
    print(f"\n{'=' * 50}")
    print(f"Mini App API running at http://{host}:{port}")
    print(f"{'=' * 50}")
    print("\nAvailable endpoints:")
    print("  GET  /api/health")
    print("  GET  /api/groups/{group_id}/settings")
    print("  PUT  /api/groups/{group_id}/settings")
    print("  GET  /api/groups/{group_id}/stats")
    print("  GET  /api/groups/{group_id}/reviews")
    print("  GET  /api/groups/{group_id}/decisions")
    print("  GET  /api/groups/{group_id}/users/{user_id}")
    print("  POST /api/groups/{group_id}/users/{user_id}/whitelist")
    print("  POST /api/groups/{group_id}/users/{user_id}/blacklist")
    print("  GET  /api/channels/validate?channel=@name")
    print("\nTest with:")
    print(f"  curl http://localhost:{port}/api/health")
    if no_auth:
        print(f"  curl http://localhost:{port}/api/groups/-1001234567890/settings")
    else:
        print("  (Authentication required - use generate_test_init_data() from tests/fixtures/miniapp_auth.py)")
    print(f"{'=' * 50}\n")

    # Run server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    print(f"Server started on http://{host}:{port}")
    print("Press Ctrl+C to stop...")

    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="Run Mini App API locally",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to listen on (default: 8080)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Use test database (port 5434 instead of 5433)",
    )
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Disable authentication (all requests authorized)",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Seed database with mock data",
    )
    parser.add_argument(
        "--db-url",
        help="Override database URL",
    )

    args = parser.parse_args()

    # Determine database URL
    if args.db_url:
        db_url = args.db_url
    elif args.test:
        db_url = "postgresql+asyncpg://saqshy_test:test_password@localhost:5434/saqshy_test"
    else:
        db_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://saqshy:password@localhost:5433/saqshy"
        )

    try:
        asyncio.run(run_server(
            host=args.host,
            port=args.port,
            db_url=db_url,
            no_auth=args.no_auth,
            seed=args.seed,
        ))
    except KeyboardInterrupt:
        print("\nServer stopped")


if __name__ == "__main__":
    main()
