"""
SAQSHY Mini App API Routes

REST API endpoints for the Telegram Mini App.
All routes require Telegram WebApp authentication via X-Telegram-Init-Data header.
Admin-only routes additionally verify the user is an admin of the target group.

Response Format:
{
    "success": true/false,
    "data": {...} or null,
    "error": {"code": "...", "message": "..."} or null
}
"""

import json

import structlog
from aiohttp import web
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from saqshy.mini_app.handlers import (
    blacklist_user,
    get_decision_detail,
    get_decisions,
    get_group_settings,
    get_group_stats,
    get_review_queue,
    get_user_profile,
    get_user_stats,
    override_decision,
    update_group_settings,
    whitelist_user,
)
from saqshy.mini_app.schemas import APIResponse

logger = structlog.get_logger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def _get_session(request: web.Request) -> AsyncSession:
    """Get database session from request.

    The session should be injected by middleware or request lifecycle.
    """
    session = request.get("db_session")
    if session is None:
        raise web.HTTPServiceUnavailable(
            text="Database session not available",
        )
    return session


def _error_response(code: str, message: str, status: int = 400) -> web.Response:
    """Create a JSON error response."""
    return web.json_response(
        APIResponse.fail(code, message).model_dump(),
        status=status,
    )


def _parse_int(value: str | None, default: int) -> int:
    """Parse integer from string, returning default if invalid."""
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


# =============================================================================
# Route Definitions
# =============================================================================


def create_mini_app_routes() -> web.RouteTableDef:
    """
    Create route table for Mini App API.

    Returns:
        RouteTableDef with all Mini App routes.
    """
    routes = web.RouteTableDef()

    # =========================================================================
    # Group Settings Endpoints
    # =========================================================================

    @routes.get("/api/groups/{group_id}")
    async def api_get_group(request: web.Request) -> web.Response:
        """
        Get group settings and info.

        GET /api/groups/{group_id}

        Requires:
        - WebApp authentication
        - Admin status in the group

        Returns:
        - GroupSettingsResponse on success
        - Error on failure
        """
        try:
            group_id = int(request.match_info["group_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id")

        session = _get_session(request)
        result = await get_group_settings(request, session, group_id)

        status = 200 if result.get("success") else _get_error_status(result)
        return web.json_response(result, status=status)

    @routes.get("/api/groups/{group_id}/settings")
    async def api_get_group_settings(request: web.Request) -> web.Response:
        """
        Get group settings (alias for /api/groups/{group_id}).

        GET /api/groups/{group_id}/settings
        """
        try:
            group_id = int(request.match_info["group_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id")

        session = _get_session(request)
        result = await get_group_settings(request, session, group_id)

        status = 200 if result.get("success") else _get_error_status(result)
        return web.json_response(result, status=status)

    @routes.put("/api/groups/{group_id}/settings")
    @routes.post("/api/groups/{group_id}/settings")
    async def api_update_group_settings(request: web.Request) -> web.Response:
        """
        Update group settings.

        PUT/POST /api/groups/{group_id}/settings

        Body (all fields optional):
        {
            "group_type": "general" | "tech" | "deals" | "crypto",
            "sensitivity": 1-10,
            "sandbox_enabled": true/false,
            "sandbox_duration_hours": 1-168,
            "linked_channel_id": number,
            "link_whitelist": ["domain1.com", "domain2.com"],
            "language": "ru" | "en" | etc.
        }

        Requires:
        - WebApp authentication
        - Admin status in the group
        """
        try:
            group_id = int(request.match_info["group_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id")

        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            logger.warning("invalid_json_body", error=str(e), endpoint="update_group_settings")
            return _error_response("VALIDATION_ERROR", "Invalid JSON body", status=400)
        except Exception as e:
            logger.error("json_parse_unexpected", error_type=type(e).__name__, error=str(e))
            return _error_response("ERROR", "Internal server error", status=500)

        session = _get_session(request)
        try:
            result = await update_group_settings(request, session, group_id, body)
            if result.get("success"):
                await session.commit()
            status = 200 if result.get("success") else _get_error_status(result)
            return web.json_response(result, status=status)
        except ValidationError as e:
            await session.rollback()
            return _error_response("VALIDATION_ERROR", str(e), status=422)
        except Exception as e:
            await session.rollback()
            logger.error("update_group_settings_failed", group_id=group_id, error=str(e))
            return _error_response("ERROR", "Update failed", status=500)

    # =========================================================================
    # Group Statistics Endpoints
    # =========================================================================

    @routes.get("/api/groups/{group_id}/stats")
    async def api_get_group_stats(request: web.Request) -> web.Response:
        """
        Get group spam statistics.

        GET /api/groups/{group_id}/stats?period_days=7

        Query params:
        - period_days: Statistics period (default: 7, max: 90)

        Requires:
        - WebApp authentication
        - Admin status in the group
        """
        try:
            group_id = int(request.match_info["group_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id")

        period_days = _parse_int(request.query.get("period_days"), 7)
        period_days = max(1, min(90, period_days))

        session = _get_session(request)
        result = await get_group_stats(request, session, group_id, period_days)

        status = 200 if result.get("success") else _get_error_status(result)
        return web.json_response(result, status=status)

    # =========================================================================
    # Review Queue Endpoints
    # =========================================================================

    @routes.get("/api/groups/{group_id}/review")
    async def api_get_review_queue(request: web.Request) -> web.Response:
        """
        Get messages pending admin review.

        GET /api/groups/{group_id}/review?limit=50&offset=0

        Query params:
        - limit: Max results (default: 50, max: 100)
        - offset: Pagination offset (default: 0)

        Requires:
        - WebApp authentication
        - Admin status in the group
        """
        try:
            group_id = int(request.match_info["group_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id")

        limit = _parse_int(request.query.get("limit"), 50)
        limit = max(1, min(100, limit))
        offset = _parse_int(request.query.get("offset"), 0)
        offset = max(0, offset)

        session = _get_session(request)
        result = await get_review_queue(request, session, group_id, limit, offset)

        status = 200 if result.get("success") else _get_error_status(result)
        return web.json_response(result, status=status)

    # =========================================================================
    # Decision Endpoints
    # =========================================================================

    @routes.get("/api/groups/{group_id}/decisions")
    async def api_get_decisions(request: web.Request) -> web.Response:
        """
        Get recent spam decisions for a group.

        GET /api/groups/{group_id}/decisions?limit=50&offset=0&verdict=block

        Query params:
        - limit: Max results (default: 50, max: 100)
        - offset: Pagination offset (default: 0)
        - verdict: Filter by verdict (allow/watch/limit/review/block)

        Requires:
        - WebApp authentication
        - Admin status in the group
        """
        try:
            group_id = int(request.match_info["group_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id")

        limit = _parse_int(request.query.get("limit"), 50)
        limit = max(1, min(100, limit))
        offset = _parse_int(request.query.get("offset"), 0)
        offset = max(0, offset)
        verdict = request.query.get("verdict")

        session = _get_session(request)
        result = await get_decisions(request, session, group_id, limit, offset, verdict)

        status = 200 if result.get("success") else _get_error_status(result)
        return web.json_response(result, status=status)

    @routes.get("/api/groups/{group_id}/decisions/{decision_id}")
    async def api_get_decision_detail(request: web.Request) -> web.Response:
        """
        Get detailed information about a specific decision.

        GET /api/groups/{group_id}/decisions/{decision_id}

        Requires:
        - WebApp authentication
        - Admin status in the group
        """
        try:
            group_id = int(request.match_info["group_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id")

        decision_id = request.match_info["decision_id"]

        session = _get_session(request)
        result = await get_decision_detail(request, session, group_id, decision_id)

        status = 200 if result.get("success") else _get_error_status(result)
        return web.json_response(result, status=status)

    @routes.post("/api/groups/{group_id}/decisions/{decision_id}/override")
    async def api_override_decision(request: web.Request) -> web.Response:
        """
        Override a spam decision.

        POST /api/groups/{group_id}/decisions/{decision_id}/override

        Body:
        {
            "action": "approve" | "confirm_block",
            "reason": "optional reason"
        }

        Requires:
        - WebApp authentication
        - Admin status in the group
        """
        try:
            group_id = int(request.match_info["group_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id")

        decision_id = request.match_info["decision_id"]

        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            logger.warning("invalid_json_body", error=str(e), endpoint="override_decision")
            return _error_response("VALIDATION_ERROR", "Invalid JSON body", status=400)
        except Exception as e:
            logger.error("json_parse_unexpected", error_type=type(e).__name__, error=str(e))
            return _error_response("ERROR", "Internal server error", status=500)

        session = _get_session(request)
        try:
            result = await override_decision(request, session, group_id, decision_id, body)
            if result.get("success"):
                await session.commit()
            status = 200 if result.get("success") else _get_error_status(result)
            return web.json_response(result, status=status)
        except ValidationError as e:
            await session.rollback()
            return _error_response("VALIDATION_ERROR", str(e), status=422)
        except Exception as e:
            await session.rollback()
            logger.error(
                "override_decision_failed", group_id=group_id, decision_id=decision_id, error=str(e)
            )
            return _error_response("ERROR", "Override failed", status=500)

    # Legacy endpoint path support
    @routes.post("/api/decisions/{decision_id}/override")
    async def api_override_decision_legacy(request: web.Request) -> web.Response:
        """
        Override a spam decision (legacy endpoint).

        POST /api/decisions/{decision_id}/override

        Body:
        {
            "action": "approve" | "confirm_block",
            "reason": "optional reason",
            "group_id": number  (required for this endpoint)
        }
        """
        decision_id = request.match_info["decision_id"]

        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            logger.warning("invalid_json_body", error=str(e), endpoint="override_decision_legacy")
            return _error_response("VALIDATION_ERROR", "Invalid JSON body", status=400)
        except Exception as e:
            logger.error("json_parse_unexpected", error_type=type(e).__name__, error=str(e))
            return _error_response("ERROR", "Internal server error", status=500)

        group_id = body.get("group_id")
        if group_id is None:
            return _error_response("VALIDATION_ERROR", "group_id is required")

        try:
            group_id = int(group_id)
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id")

        session = _get_session(request)
        try:
            result = await override_decision(request, session, group_id, decision_id, body)
            if result.get("success"):
                await session.commit()
            status = 200 if result.get("success") else _get_error_status(result)
            return web.json_response(result, status=status)
        except ValidationError as e:
            await session.rollback()
            return _error_response("VALIDATION_ERROR", str(e), status=422)
        except Exception as e:
            await session.rollback()
            logger.error(
                "override_decision_legacy_failed",
                group_id=group_id,
                decision_id=decision_id,
                error=str(e),
            )
            return _error_response("ERROR", "Override failed", status=500)

    # =========================================================================
    # User Management Endpoints
    # =========================================================================

    @routes.get("/api/groups/{group_id}/users/{user_id}")
    async def api_get_user_profile(request: web.Request) -> web.Response:
        """
        Get user's profile and risk assessment in a group.

        GET /api/groups/{group_id}/users/{user_id}

        Requires:
        - WebApp authentication
        - Admin status in the group
        """
        try:
            group_id = int(request.match_info["group_id"])
            user_id = int(request.match_info["user_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id or user_id")

        session = _get_session(request)
        result = await get_user_profile(request, session, group_id, user_id)

        status = 200 if result.get("success") else _get_error_status(result)
        return web.json_response(result, status=status)

    @routes.get("/api/users/{user_id}/stats")
    @routes.get("/api/users/{user_id}/profile")
    async def api_get_user_stats(request: web.Request) -> web.Response:
        """
        Get user's spam history across groups.

        GET /api/users/{user_id}/stats
        GET /api/users/{user_id}/profile (alias)

        Requires:
        - WebApp authentication
        """
        try:
            user_id = int(request.match_info["user_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid user_id")

        session = _get_session(request)
        result = await get_user_stats(request, session, user_id)

        status = 200 if result.get("success") else _get_error_status(result)
        return web.json_response(result, status=status)

    @routes.post("/api/groups/{group_id}/users/{user_id}/whitelist")
    async def api_whitelist_user(request: web.Request) -> web.Response:
        """
        Add user to group whitelist (promote to trusted).

        POST /api/groups/{group_id}/users/{user_id}/whitelist

        Body:
        {
            "reason": "optional reason"
        }

        Requires:
        - WebApp authentication
        - Admin status in the group
        """
        try:
            group_id = int(request.match_info["group_id"])
            user_id = int(request.match_info["user_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id or user_id")

        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            logger.debug("whitelist_user_no_body", error=str(e))
            body = {}
        except Exception as e:
            logger.error("json_parse_unexpected", error_type=type(e).__name__, error=str(e))
            body = {}

        session = _get_session(request)
        try:
            result = await whitelist_user(request, session, group_id, user_id, body)
            if result.get("success"):
                await session.commit()
            status = 200 if result.get("success") else _get_error_status(result)
            return web.json_response(result, status=status)
        except Exception as e:
            await session.rollback()
            logger.error("whitelist_user_failed", group_id=group_id, user_id=user_id, error=str(e))
            return _error_response("ERROR", "Whitelist operation failed", status=500)

    @routes.post("/api/groups/{group_id}/users/{user_id}/blacklist")
    async def api_blacklist_user(request: web.Request) -> web.Response:
        """
        Add user to group blacklist and ban.

        POST /api/groups/{group_id}/users/{user_id}/blacklist

        Body:
        {
            "reason": "optional reason",
            "duration_hours": null  (null = permanent)
        }

        Requires:
        - WebApp authentication
        - Admin status in the group
        """
        try:
            group_id = int(request.match_info["group_id"])
            user_id = int(request.match_info["user_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id or user_id")

        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            logger.debug("blacklist_user_no_body", error=str(e))
            body = {}
        except Exception as e:
            logger.error("json_parse_unexpected", error_type=type(e).__name__, error=str(e))
            body = {}

        session = _get_session(request)
        try:
            result = await blacklist_user(request, session, group_id, user_id, body)
            if result.get("success"):
                await session.commit()
            status = 200 if result.get("success") else _get_error_status(result)
            return web.json_response(result, status=status)
        except Exception as e:
            await session.rollback()
            logger.error("blacklist_user_failed", group_id=group_id, user_id=user_id, error=str(e))
            return _error_response("ERROR", "Blacklist operation failed", status=500)

    # =========================================================================
    # Legacy User Endpoints (group_id in body)
    # =========================================================================

    @routes.post("/api/users/{user_id}/whitelist")
    async def api_whitelist_user_legacy(request: web.Request) -> web.Response:
        """
        Add user to whitelist (legacy endpoint).

        POST /api/users/{user_id}/whitelist

        Body:
        {
            "group_id": number (required),
            "reason": "optional reason"
        }
        """
        try:
            user_id = int(request.match_info["user_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid user_id")

        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            logger.warning("invalid_json_body", error=str(e), endpoint="whitelist_user_legacy")
            return _error_response("VALIDATION_ERROR", "Invalid JSON body", status=400)
        except Exception as e:
            logger.error("json_parse_unexpected", error_type=type(e).__name__, error=str(e))
            return _error_response("ERROR", "Internal server error", status=500)

        group_id = body.get("group_id")
        if group_id is None:
            return _error_response("VALIDATION_ERROR", "group_id is required")

        try:
            group_id = int(group_id)
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id")

        session = _get_session(request)
        try:
            result = await whitelist_user(request, session, group_id, user_id, body)
            if result.get("success"):
                await session.commit()
            status = 200 if result.get("success") else _get_error_status(result)
            return web.json_response(result, status=status)
        except Exception as e:
            await session.rollback()
            logger.error(
                "whitelist_user_legacy_failed", group_id=group_id, user_id=user_id, error=str(e)
            )
            return _error_response("ERROR", "Whitelist operation failed", status=500)

    @routes.post("/api/users/{user_id}/blacklist")
    async def api_blacklist_user_legacy(request: web.Request) -> web.Response:
        """
        Add user to blacklist (legacy endpoint).

        POST /api/users/{user_id}/blacklist

        Body:
        {
            "group_id": number (required),
            "reason": "optional reason",
            "duration_hours": null (null = permanent)
        }
        """
        try:
            user_id = int(request.match_info["user_id"])
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid user_id")

        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            logger.warning("invalid_json_body", error=str(e), endpoint="blacklist_user_legacy")
            return _error_response("VALIDATION_ERROR", "Invalid JSON body", status=400)
        except Exception as e:
            logger.error("json_parse_unexpected", error_type=type(e).__name__, error=str(e))
            return _error_response("ERROR", "Internal server error", status=500)

        group_id = body.get("group_id")
        if group_id is None:
            return _error_response("VALIDATION_ERROR", "group_id is required")

        try:
            group_id = int(group_id)
        except ValueError:
            return _error_response("VALIDATION_ERROR", "Invalid group_id")

        session = _get_session(request)
        try:
            result = await blacklist_user(request, session, group_id, user_id, body)
            if result.get("success"):
                await session.commit()
            status = 200 if result.get("success") else _get_error_status(result)
            return web.json_response(result, status=status)
        except Exception as e:
            await session.rollback()
            logger.error(
                "blacklist_user_legacy_failed", group_id=group_id, user_id=user_id, error=str(e)
            )
            return _error_response("ERROR", "Blacklist operation failed", status=500)

    return routes


def _get_error_status(result: dict) -> int:
    """Get HTTP status code from error response."""
    error = result.get("error", {})
    code = error.get("code", "")

    status_map = {
        "UNAUTHORIZED": 401,
        "FORBIDDEN": 403,
        "NOT_FOUND": 404,
        "VALIDATION_ERROR": 422,
        "ERROR": 500,
    }

    return status_map.get(code, 400)


def setup_routes(app: web.Application) -> None:
    """
    Add Mini App routes to the application.

    This function should be called during app setup.

    Args:
        app: The aiohttp Application instance.
    """
    routes = create_mini_app_routes()
    app.router.add_routes(routes)
    logger.info("mini_app_routes_configured", route_count=len(routes))
