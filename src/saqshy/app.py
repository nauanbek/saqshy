"""
SAQSHY Application Factory

Creates and configures the aiohttp web application with all components:
- Telegram bot webhook handler
- Mini App API endpoints
- Health check endpoints
- Database connections
- Redis cache
- Qdrant vector database
"""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from aiogram.types import Update
from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from saqshy.api.health import HealthChecker
from saqshy.bot.bot import (
    create_bot,
    create_dispatcher,
    setup_webhook,
    verify_webhook_secret,
)
from saqshy.config import get_settings
from saqshy.core.logging import configure_logging
from saqshy.mini_app import (
    create_auth_middleware,
    create_cors_middleware,
)
from saqshy.mini_app import (
    setup_routes as setup_mini_app_routes,
)
from saqshy.services.cache import CacheService
from saqshy.services.channel_subscription import ChannelSubscriptionService
from saqshy.services.spam_db import SpamDB

logger = structlog.get_logger(__name__)


# =============================================================================
# Database Session Middleware
# =============================================================================


def create_db_session_middleware(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable:
    """
    Create middleware that injects database session into requests.

    The session is created at the start of each request and committed/rolled
    back at the end based on whether the request succeeded.

    Args:
        session_factory: SQLAlchemy async session factory.

    Returns:
        Middleware function.
    """

    @web.middleware
    async def db_session_middleware(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.Response]],
    ) -> web.Response:
        """Inject database session into request and handle transaction."""
        # Skip for non-API routes and health checks
        if not request.path.startswith("/api/"):
            return await handler(request)

        async with session_factory() as session:
            request["db_session"] = session
            try:
                response = await handler(request)
                # Commit on success
                await session.commit()
                return response
            except web.HTTPException:
                # Don't rollback for HTTP exceptions (they're expected)
                await session.commit()
                raise
            except Exception:
                # Rollback on unexpected errors
                await session.rollback()
                raise

    return db_session_middleware


# =============================================================================
# Admin Checker
# =============================================================================


async def create_admin_checker(app: web.Application) -> Callable[[int, int], Awaitable[bool]]:
    """
    Create an admin checker function that uses the Telegram bot.

    This function checks if a user is an admin in a group by:
    1. Checking the cache first
    2. Querying the Telegram API if not cached
    3. Caching the result

    Args:
        app: The aiohttp Application with bot instance.

    Returns:
        Async function (user_id, chat_id) -> bool
    """

    async def check_admin(user_id: int, chat_id: int) -> bool:
        """Check if user is admin in chat via database trust level."""

        session_factory = app.get("session_factory")
        if session_factory is None:
            return False

        try:
            from saqshy.db.models import TrustLevel
            from saqshy.db.repositories import GroupMemberRepository

            async with session_factory() as session:
                repo = GroupMemberRepository(session)
                member = await repo.get_member(chat_id, user_id)
                if member and member.trust_level == TrustLevel.ADMIN:
                    return True
        except Exception as e:
            logger.error("admin_check_error", error=str(e), user_id=user_id, chat_id=chat_id)

        return False

    return check_admin


# =============================================================================
# Lifespan Management
# =============================================================================


@asynccontextmanager
async def lifespan(app: web.Application) -> AsyncIterator[None]:
    """
    Application lifespan context manager.

    Initializes all resources on startup and cleans up on shutdown.

    Service Initialization Order (dependencies matter):
    1. Database (PostgreSQL) - required for persistence
    2. Redis (CacheService) - required for caching and rate limiting
    3. SpamDB (Qdrant + Cohere) - requires Qdrant URL and Cohere API key
    4. Telegram Bot - requires bot token
    5. ChannelSubscriptionService - requires Bot + CacheService
    6. Dispatcher - requires all services above

    Cleanup Order (reverse of initialization):
    1. Dispatcher (stop processing updates)
    2. Bot session
    3. ChannelSubscriptionService (nothing to close)
    4. SpamDB (Qdrant client)
    5. CacheService (Redis connections)
    6. Database engine
    """
    settings = get_settings()

    # Record start time for uptime calculation
    app["start_time"] = time.monotonic()

    # Configure structured logging based on environment
    configure_logging(
        environment=settings.environment.value,
        log_level=settings.log_level,
    )

    # Startup
    logger.info("initializing_application", environment=settings.environment)

    # =========================================================================
    # 1. Initialize database connection pool
    # =========================================================================
    try:
        engine = create_async_engine(
            settings.database.url.get_secret_value(),
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
            pool_timeout=settings.database.pool_timeout,
            echo=settings.database.echo,
        )
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        app["engine"] = engine
        app["session_factory"] = session_factory
        logger.info("database_connected")
    except Exception as e:
        logger.error("database_connection_failed", error=str(e))
        # Continue without database for health checks

    # =========================================================================
    # 2. Initialize Redis via CacheService
    # =========================================================================
    cache_service: CacheService | None = None
    try:
        cache_service = CacheService(
            redis_url=settings.redis.url,
            default_ttl=300,
            pool_size=settings.redis.max_connections,
        )
        await cache_service.connect()

        app["cache_service"] = cache_service
        logger.info(
            "redis_connected",
            url=cache_service._sanitize_url(settings.redis.url),
        )
    except Exception as e:
        logger.error("redis_connection_failed", error=str(e))
        # Continue without Redis - graceful degradation
        # Rate limiting and caching will be disabled

    # =========================================================================
    # 3. Initialize SpamDB (Qdrant + Cohere embeddings)
    # =========================================================================
    spam_db: SpamDB | None = None
    try:
        # Get Qdrant API key if configured
        qdrant_api_key = None
        if settings.qdrant.api_key:
            qdrant_api_key = settings.qdrant.api_key.get_secret_value()

        spam_db = SpamDB(
            qdrant_url=settings.qdrant.url,
            cohere_api_key=settings.cohere.api_key.get_secret_value(),
            collection_name=settings.qdrant.collection,
            qdrant_api_key=qdrant_api_key,
            cache_ttl_seconds=300,
        )
        await spam_db.initialize()

        app["spam_db"] = spam_db
        app["qdrant"] = spam_db._qdrant_client  # For health checks
        logger.info(
            "spam_db_initialized",
            qdrant_url=settings.qdrant.url,
            collection=settings.qdrant.collection,
        )
    except Exception as e:
        logger.error("spam_db_initialization_failed", error=str(e))
        # Continue without SpamDB - spam pattern matching will be disabled

    # =========================================================================
    # 4. Initialize Telegram Bot
    # =========================================================================
    bot = None
    try:
        bot = create_bot(settings)
        app["bot"] = bot

        # Verify bot token by fetching bot info
        bot_info = await bot.get_me()
        logger.info(
            "telegram_bot_initialized",
            bot_id=bot_info.id,
            bot_username=bot_info.username,
        )
    except Exception as e:
        logger.error("telegram_bot_initialization_failed", error=str(e))
        # Bot is critical - continue but webhook handler will return 200 without processing

    # =========================================================================
    # 5. Initialize ChannelSubscriptionService (requires Bot + Cache)
    # =========================================================================
    channel_subscription_service = None
    if bot is not None:
        try:
            channel_subscription_service = ChannelSubscriptionService(
                bot=bot,
                cache=cache_service,  # Can be None for graceful degradation
                cache_ttl=3600,  # 1 hour cache for subscription status
                max_concurrent_requests=10,
            )
            app["channel_subscription_service"] = channel_subscription_service
            logger.info("channel_subscription_service_initialized")
        except Exception as e:
            logger.error("channel_subscription_service_initialization_failed", error=str(e))
            # Continue without channel subscription checks

    # =========================================================================
    # 6. Initialize Dispatcher with all services
    # =========================================================================
    if bot is not None:
        try:
            # Build mini app URL from webhook base URL if not explicitly set
            mini_app_url = settings.mini_app.url
            if not mini_app_url and settings.webhook.base_url:
                mini_app_url = f"{settings.webhook.base_url}/app"

            dispatcher = create_dispatcher(
                cache_service=cache_service,
                spam_db=spam_db,
                channel_subscription_service=channel_subscription_service,
                mini_app_url=mini_app_url,
            )
            app["dispatcher"] = dispatcher
            logger.info(
                "dispatcher_initialized",
                has_cache=cache_service is not None,
                has_spam_db=spam_db is not None,
                has_channel_sub=channel_subscription_service is not None,
            )
        except Exception as e:
            logger.error("dispatcher_initialization_failed", error=str(e))

    # =========================================================================
    # 7. Setup webhook (optional, only in production)
    # =========================================================================
    if bot is not None and settings.webhook.base_url:
        try:
            webhook_url = f"{settings.webhook.base_url}{settings.webhook.path}"
            webhook_secret = settings.webhook.secret.get_secret_value()

            success = await setup_webhook(
                bot=bot,
                webhook_url=webhook_url,
                secret=webhook_secret,
                drop_pending=True,
            )
            if success:
                logger.info("webhook_configured", url=webhook_url)
            else:
                logger.warning("webhook_setup_failed")
        except Exception as e:
            logger.error("webhook_setup_error", error=str(e))

    logger.info("application_ready")

    yield

    # =========================================================================
    # Shutdown - reverse order of initialization
    # =========================================================================
    logger.info("shutting_down_application")

    # 1. Close bot session
    if "bot" in app and app["bot"] is not None:
        try:
            await app["bot"].session.close()
            logger.info("telegram_bot_session_closed")
        except Exception as e:
            logger.warning("telegram_bot_session_close_failed", error=str(e))

    # 2. Close SpamDB (Qdrant client and Cohere)
    if "spam_db" in app and app["spam_db"] is not None:
        try:
            await app["spam_db"].close()
            logger.info("spam_db_closed")
        except Exception as e:
            logger.warning("spam_db_close_failed", error=str(e))

    # 3. Close CacheService (Redis connections)
    if "cache_service" in app and app["cache_service"] is not None:
        try:
            await app["cache_service"].close()
            logger.info("cache_service_closed")
        except Exception as e:
            logger.warning("cache_service_close_failed", error=str(e))

    # 4. Close database connections
    if "engine" in app:
        try:
            await app["engine"].dispose()
            logger.info("database_disconnected")
        except Exception as e:
            logger.warning("database_close_failed", error=str(e))

    logger.info("application_shutdown_complete")


async def handle_webhook(request: web.Request) -> web.Response:
    """
    Handle incoming Telegram webhook updates.

    This is the main entry point for all Telegram messages.
    Follows Parse -> Analyze -> Decide -> Act pattern with defensive error handling.

    Security:
    - Validates webhook secret using constant-time comparison
    - Returns 200 even on errors to prevent Telegram retry storms

    Args:
        request: aiohttp Request containing Telegram Update JSON.

    Returns:
        200 OK response (always, to acknowledge receipt to Telegram).
    """
    # =========================================================================
    # PARSE: Extract and validate input
    # =========================================================================

    # Get bot and dispatcher from app context
    bot = request.app.get("bot")
    dispatcher = request.app.get("dispatcher")

    if bot is None or dispatcher is None:
        logger.error(
            "webhook_handler_not_initialized",
            bot_present=bot is not None,
            dispatcher_present=dispatcher is not None,
        )
        # Return 200 to prevent Telegram retries - we can't process without bot/dispatcher
        return web.Response(status=200)

    # =========================================================================
    # ANALYZE: Validate webhook secret
    # =========================================================================

    settings = request.app.get("settings")
    expected_secret = ""
    if settings:
        # Try webhook.secret first, fall back to telegram.webhook_secret
        try:
            expected_secret = settings.webhook.secret.get_secret_value()
        except AttributeError:
            with contextlib.suppress(AttributeError):
                expected_secret = settings.telegram.webhook_secret.get_secret_value()

    received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")

    if not verify_webhook_secret(received_secret, expected_secret):
        logger.warning(
            "webhook_secret_validation_failed",
            has_received_secret=received_secret is not None,
            has_expected_secret=bool(expected_secret),
        )
        # Return 200 to not leak information about secret validation
        # but do NOT process the update
        return web.Response(status=200)

    # =========================================================================
    # DECIDE: Parse the update JSON
    # =========================================================================

    try:
        update_data = await request.json()
    except Exception as e:
        logger.error(
            "webhook_json_parse_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        return web.Response(status=200)

    # Parse into aiogram Update object
    try:
        update = Update.model_validate(update_data)
    except Exception as e:
        logger.error(
            "webhook_update_parse_error",
            error=str(e),
            error_type=type(e).__name__,
            update_id=update_data.get("update_id"),
        )
        return web.Response(status=200)

    # Log update receipt for debugging
    logger.debug(
        "webhook_update_received",
        update_id=update.update_id,
        update_type=_get_update_type(update),
    )

    # =========================================================================
    # ACT: Feed update to dispatcher
    # =========================================================================

    try:
        await asyncio.wait_for(
            dispatcher.feed_update(bot, update),
            timeout=55.0,  # Telegram expects response within 60s, leave 5s buffer
        )
        logger.debug(
            "webhook_update_processed",
            update_id=update.update_id,
        )
    except TimeoutError:
        logger.error(
            "webhook_processing_timeout",
            update_id=update.update_id,
            timeout_seconds=55.0,
        )
    except Exception as e:
        logger.error(
            "webhook_processing_error",
            update_id=update.update_id,
            error=str(e),
            error_type=type(e).__name__,
        )

    # Always return 200 to acknowledge receipt
    # Returning non-200 causes Telegram to retry, creating potential duplicate processing
    return web.Response(status=200)


def _get_update_type(update) -> str:
    """Extract the type of update for logging purposes."""
    if update.message:
        return "message"
    elif update.callback_query:
        return "callback_query"
    elif update.chat_member:
        return "chat_member"
    elif update.my_chat_member:
        return "my_chat_member"
    elif update.edited_message:
        return "edited_message"
    elif update.channel_post:
        return "channel_post"
    elif update.inline_query:
        return "inline_query"
    else:
        return "unknown"


# =============================================================================
# Route Configuration
# =============================================================================


# Path to Mini App static files
_MINI_APP_STATIC_PATH = Path(__file__).parent / "static" / "mini_app"


async def spa_fallback_handler(request: web.Request) -> web.FileResponse:
    """
    Serve index.html for any /app/* route that doesn't match a static file.

    This enables React Router client-side routing. When a user navigates
    directly to /app/settings or refreshes on /app/reviews, we serve
    index.html and let React Router handle the route.

    Returns:
        FileResponse with index.html
    """
    index_path = _MINI_APP_STATIC_PATH / "index.html"

    if not index_path.exists():
        logger.warning(
            "mini_app_not_deployed",
            path=str(_MINI_APP_STATIC_PATH),
            message="Mini App frontend not found. Run 'npm run build' in mini_app_frontend/",
        )
        raise web.HTTPNotFound(text="Mini App not deployed")

    return web.FileResponse(
        index_path,
        headers={"Cache-Control": "no-cache"},
    )


def create_routes(app: web.Application) -> None:
    """Configure all application routes."""
    # Health endpoints using HealthChecker
    # Pass dependencies for comprehensive health checks
    health_checker = HealthChecker(
        cache_service=app.get("cache_service"),
        db_engine=app.get("engine"),
        qdrant_client=app.get("qdrant"),
        start_time=app.get("start_time"),
    )
    app.router.add_routes(health_checker.routes())

    # Telegram webhook
    app.router.add_post("/webhook", handle_webhook)

    # Mini App API routes
    setup_mini_app_routes(app)

    # Serve static files for Mini App frontend (production)
    # Route order matters for SPA support:
    # 1. /app/assets/* - Static assets (JS, CSS, images) with caching
    # 2. /app/{path} - SPA fallback serves index.html for all other routes
    if _MINI_APP_STATIC_PATH.exists():
        assets_path = _MINI_APP_STATIC_PATH / "assets"
        if assets_path.exists():
            app.router.add_static(
                "/app/assets/",
                assets_path,
                name="mini_app_assets",
                append_version=True,
            )

        # SPA fallback routes - serve index.html for all /app/* paths
        # This enables React Router client-side routing
        app.router.add_get("/app", spa_fallback_handler, name="spa_root_redirect")
        app.router.add_get("/app/", spa_fallback_handler, name="spa_root")
        app.router.add_get("/app/{path:.*}", spa_fallback_handler, name="spa_fallback")

        logger.info(
            "spa_routing_configured",
            path=str(_MINI_APP_STATIC_PATH),
            routes=["/app/", "/app/{path}"],
        )


def create_middlewares(app: web.Application) -> list:
    """Create and configure all middlewares."""
    settings = app["settings"]
    middlewares = []

    # CORS middleware (must be first to handle OPTIONS requests)
    cors_middleware = create_cors_middleware()
    middlewares.append(cors_middleware)

    # Database session middleware
    if "session_factory" in app:
        db_middleware = create_db_session_middleware(app["session_factory"])
        middlewares.append(db_middleware)

    # Telegram WebApp authentication middleware
    bot_token = settings.telegram.bot_token.get_secret_value()
    auth_middleware = create_auth_middleware(
        bot_token,
        excluded_paths={"/api/health"},
    )
    middlewares.append(auth_middleware)

    return middlewares


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> web.Application:
    """
    Application factory.

    Creates and configures the aiohttp web application.

    Returns:
        Configured aiohttp Application instance.
    """
    app = web.Application()

    # Store settings in app
    app["settings"] = get_settings()

    # Setup cleanup context (lifespan)
    app.cleanup_ctx.append(_lifespan_wrapper)

    # Note: Routes and middlewares are configured after lifespan startup
    # because they may depend on initialized resources

    logger.info("application_created")

    return app


async def _lifespan_wrapper(app: web.Application) -> AsyncIterator[None]:
    """Wrapper to use lifespan as cleanup context."""
    async with lifespan(app):
        # Configure routes after resources are initialized
        create_routes(app)

        # Configure middlewares after resources are initialized
        middlewares = create_middlewares(app)
        # Insert middlewares at the beginning
        for middleware in reversed(middlewares):
            app.middlewares.insert(0, middleware)

        yield


# =============================================================================
# Development Server
# =============================================================================


async def run_app(app: web.Application) -> None:
    """
    Run the application.

    Starts the aiohttp server with the configured settings.
    """
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=8080,
    )

    logger.info("starting_server", host="0.0.0.0", port=8080)
    await site.start()

    # Keep running until interrupted
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


def main() -> None:
    """Entry point for running the application."""
    app = create_app()
    asyncio.run(run_app(app))


if __name__ == "__main__":
    main()
