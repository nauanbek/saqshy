"""
SAQSHY Mini App Request Handlers

Business logic for Mini App API endpoints.
Handlers are responsible for:
- Extracting and validating request parameters
- Checking authorization (admin status)
- Calling repository methods
- Formatting responses

All handlers return APIResponse-compatible dictionaries.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from aiohttp import web
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from saqshy.core.types import GroupType, Verdict  # Import from canonical source
from saqshy.db.models import Decision, Group, GroupMember, TrustLevel, User
from saqshy.db.repositories import (
    DecisionRepository,
    GroupMemberRepository,
    GroupRepository,
    UserRepository,
)
from saqshy.mini_app.auth import WebAppAuth
from saqshy.mini_app.schemas import (
    APIResponse,
    DecisionDetail,
    DecisionListResponse,
    DecisionOverrideRequest,
    DecisionOverrideResponse,
    GroupSettingsRequest,
    GroupSettingsResponse,
    GroupStatsResponse,
    ReviewItem,
    ReviewQueueResponse,
    ThreatTypeCount,
    UserProfileResponse,
    UserStatsResponse,
)

logger = structlog.get_logger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def _format_datetime(dt: datetime | None) -> str | None:
    """Format datetime to ISO 8601 string."""
    if dt is None:
        return None
    return dt.isoformat()


def _decision_to_review_item(decision: Decision, user: User | None = None) -> ReviewItem:
    """Convert Decision model to ReviewItem schema."""
    # Get message preview from content signals if available
    message_preview = None
    if decision.content_signals:
        text = decision.content_signals.get("original_text", "")
        if text:
            message_preview = text[:100] + ("..." if len(text) > 100 else "")

    return ReviewItem(
        decision_id=str(decision.id),
        user_id=decision.user_id,
        username=user.username if user else None,
        first_name=user.first_name if user else None,
        message_id=decision.message_id,
        message_preview=message_preview,
        risk_score=decision.risk_score,
        verdict=decision.verdict.value,
        threat_type=decision.threat_type,
        created_at=_format_datetime(decision.created_at) or "",
        is_overridden=decision.overridden_at is not None,
    )


def _group_to_settings_response(group: Group) -> GroupSettingsResponse:
    """Convert Group model to GroupSettingsResponse schema."""
    return GroupSettingsResponse(
        group_id=group.id,
        title=group.title,
        username=group.username,
        group_type=group.group_type.value,
        sensitivity=group.sensitivity,
        sandbox_enabled=group.sandbox_enabled,
        sandbox_duration_hours=group.sandbox_duration_hours,
        linked_channel_id=group.linked_channel_id,
        link_whitelist=group.link_whitelist or [],
        language=group.language,
        members_count=group.members_count,
        blocked_count=group.blocked_count,
        is_active=group.is_active,
        created_at=_format_datetime(group.created_at) or "",
        updated_at=_format_datetime(group.updated_at) or "",
    )


def _member_to_profile_response(
    member: GroupMember,
    user: User | None = None,
) -> UserProfileResponse:
    """Convert GroupMember model to UserProfileResponse schema."""
    # Build display name
    if user:
        display_name = user.display_name
    else:
        display_name = str(member.user_id)

    return UserProfileResponse(
        user_id=member.user_id,
        username=user.username if user else None,
        first_name=user.first_name if user else None,
        last_name=user.last_name if user else None,
        display_name=display_name,
        trust_level=member.trust_level.value,
        trust_score=member.trust_score,
        message_count=member.message_count,
        last_message_at=_format_datetime(member.last_message_at),
        joined_at=_format_datetime(member.joined_at),
        first_message_at=_format_datetime(member.first_message_at),
        is_in_sandbox=member.is_in_sandbox,
        sandbox_expires_at=_format_datetime(member.sandbox_expires_at),
        messages_in_sandbox=member.messages_in_sandbox,
        has_photo=user.has_photo if user else None,
        is_premium=user.is_premium if user else None,
        bio=user.bio if user else None,
        account_age_days=user.account_age_days if user else None,
    )


async def _check_admin(
    request: web.Request,
    group_id: int,
    session: AsyncSession,
) -> tuple[bool, int | None]:
    """
    Check if the authenticated user is admin of the group.

    Returns:
        Tuple of (is_admin, user_id)
    """
    auth: WebAppAuth | None = request.get("webapp_auth")
    if auth is None:
        return False, None

    user_id = auth.user_id
    if user_id is None:
        return False, None

    # Check via admin_checker callback if available
    if await auth.is_admin(group_id):
        return True, user_id

    # Fallback: check in database
    try:
        member_repo = GroupMemberRepository(session)
        member = await member_repo.get_member(group_id, user_id)
        if member and member.trust_level == TrustLevel.ADMIN:
            return True, user_id
    except Exception as e:
        logger.error(
            "admin_check_db_error",
            group_id=group_id,
            user_id=user_id,
            error=str(e),
        )
        # Deny access on DB error to be safe
        return False, user_id

    return False, user_id


# =============================================================================
# Group Settings Handlers
# =============================================================================


async def get_group_settings(
    request: web.Request,
    session: AsyncSession,
    group_id: int,
) -> dict[str, Any]:
    """
    Get group settings.

    Requires admin authentication.

    Returns:
        APIResponse with GroupSettingsResponse data.
    """
    # Check admin permission
    is_admin, user_id = await _check_admin(request, group_id, session)
    if not is_admin:
        logger.warning(
            "get_group_settings_forbidden",
            group_id=group_id,
            user_id=user_id,
        )
        return APIResponse.fail(
            "FORBIDDEN",
            "Admin access required",
        ).model_dump()

    # Fetch group
    group_repo = GroupRepository(session)
    group = await group_repo.get_by_id(group_id)

    if group is None:
        return APIResponse.fail(
            "NOT_FOUND",
            f"Group {group_id} not found",
        ).model_dump()

    settings = _group_to_settings_response(group)
    return APIResponse.ok(settings.model_dump()).model_dump()


async def update_group_settings(
    request: web.Request,
    session: AsyncSession,
    group_id: int,
    body: dict[str, Any],
) -> dict[str, Any]:
    """
    Update group settings.

    Requires admin authentication.

    Args:
        request: aiohttp request
        session: Database session
        group_id: Telegram chat_id
        body: Request body with settings to update

    Returns:
        APIResponse with updated GroupSettingsResponse.
    """
    # Check admin permission
    is_admin, user_id = await _check_admin(request, group_id, session)
    if not is_admin:
        logger.warning(
            "update_group_settings_forbidden",
            group_id=group_id,
            user_id=user_id,
        )
        return APIResponse.fail(
            "FORBIDDEN",
            "Admin access required",
        ).model_dump()

    # Validate request body
    try:
        settings_request = GroupSettingsRequest(**body)
    except ValidationError as e:
        return APIResponse.fail(
            "VALIDATION_ERROR",
            str(e.errors()),
        ).model_dump()

    # Fetch group
    group_repo = GroupRepository(session)
    group = await group_repo.get_by_id(group_id)

    if group is None:
        return APIResponse.fail(
            "NOT_FOUND",
            f"Group {group_id} not found",
        ).model_dump()

    # Validate linked_channel_id if provided
    if settings_request.linked_channel_id is not None:
        # NOTE: Channel validation is deferred to runtime for architectural reasons:
        # 1. The mini_app module runs in a separate aiohttp context without bot access
        # 2. Bot instance (aiogram Bot) is only available in the bot/ module
        # 3. Validation requires calling Telegram's getChatMember API via the bot
        # 4. Invalid channel IDs will fail gracefully at subscription check time
        #
        # Alternative approaches considered but not implemented:
        # - Pass bot instance via app context: Couples mini_app to bot module
        # - Separate validation endpoint: Extra round-trip, still needs bot
        # - Store bot token for direct API calls: Security concern, duplicates logic
        #
        # Current behavior: Accept any channel ID, ChannelSubscriptionService
        # handles validation when checking user subscriptions (behavior_analyzer.py)
        pass

    # Update settings
    update_kwargs = {}
    if settings_request.group_type is not None:
        update_kwargs["group_type"] = GroupType(settings_request.group_type)
    if settings_request.sensitivity is not None:
        update_kwargs["sensitivity"] = settings_request.sensitivity
    if settings_request.sandbox_enabled is not None:
        update_kwargs["sandbox_enabled"] = settings_request.sandbox_enabled
    if settings_request.sandbox_duration_hours is not None:
        update_kwargs["sandbox_duration_hours"] = settings_request.sandbox_duration_hours
    if settings_request.linked_channel_id is not None:
        update_kwargs["linked_channel_id"] = settings_request.linked_channel_id
    if settings_request.link_whitelist is not None:
        update_kwargs["link_whitelist"] = settings_request.link_whitelist
    if settings_request.language is not None:
        update_kwargs["language"] = settings_request.language

    if update_kwargs:
        try:
            group = await group_repo.update_settings(group_id, **update_kwargs)
        except ValueError as e:
            return APIResponse.fail(
                "VALIDATION_ERROR",
                str(e),
            ).model_dump()

    if group is None:
        return APIResponse.fail(
            "NOT_FOUND",
            f"Group {group_id} not found",
        ).model_dump()

    logger.info(
        "group_settings_updated",
        group_id=group_id,
        admin_id=user_id,
        updates=update_kwargs,
    )

    settings = _group_to_settings_response(group)
    return APIResponse.ok(settings.model_dump()).model_dump()


# =============================================================================
# Group Statistics Handlers
# =============================================================================


async def get_group_stats(
    request: web.Request,
    session: AsyncSession,
    group_id: int,
    period_days: int = 7,
) -> dict[str, Any]:
    """
    Get group spam statistics.

    Requires admin authentication.

    Args:
        request: aiohttp request
        session: Database session
        group_id: Telegram chat_id
        period_days: Statistics period in days (default 7)

    Returns:
        APIResponse with GroupStatsResponse data.
    """
    # Check admin permission
    is_admin, user_id = await _check_admin(request, group_id, session)
    if not is_admin:
        return APIResponse.fail(
            "FORBIDDEN",
            "Admin access required",
        ).model_dump()

    # Fetch group
    group_repo = GroupRepository(session)
    group = await group_repo.get_by_id(group_id)

    if group is None:
        return APIResponse.fail(
            "NOT_FOUND",
            f"Group {group_id} not found",
        ).model_dump()

    # Get decision stats
    decision_repo = DecisionRepository(session)
    stats = await decision_repo.get_stats(group_id, days=period_days)

    # Get threat type distribution
    threat_distribution = await decision_repo.get_threat_type_distribution(
        group_id, days=period_days
    )
    top_threats = sorted(threat_distribution.items(), key=lambda x: x[1], reverse=True)[:5]

    # Get false positives (overridden decisions)
    false_positives = await decision_repo.get_false_positives(group_id, days=period_days)
    fp_count = len(false_positives)

    # Calculate FP rate
    blocked_count = stats.by_verdict.get("block", 0)
    fp_rate = (fp_count / blocked_count * 100) if blocked_count > 0 else 0.0

    # Get sandbox member count
    member_repo = GroupMemberRepository(session)
    sandbox_members = await member_repo.get_sandbox_members(group_id)
    member_stats = await member_repo.get_member_stats(group_id)

    response = GroupStatsResponse(
        group_id=group_id,
        group_type=group.group_type.value,
        period_days=period_days,
        total_messages=stats.total,
        allowed=stats.by_verdict.get("allow", 0),
        watched=stats.by_verdict.get("watch", 0),
        limited=stats.by_verdict.get("limit", 0),
        reviewed=stats.by_verdict.get("review", 0),
        blocked=blocked_count,
        fp_count=fp_count,
        tp_count=stats.blocked_messages - fp_count,
        fp_rate=round(fp_rate, 2),
        avg_processing_time_ms=stats.avg_processing_time_ms,
        llm_usage_percent=round(stats.llm_usage_percent, 2),
        top_threat_types=[ThreatTypeCount(type=t, count=c) for t, c in top_threats],
        users_in_sandbox=len(sandbox_members),
        active_users_24h=member_stats.get("active_last_24h", 0),
    )

    return APIResponse.ok(response.model_dump()).model_dump()


# =============================================================================
# Review Queue Handlers
# =============================================================================


async def get_review_queue(
    request: web.Request,
    session: AsyncSession,
    group_id: int,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Get messages pending admin review.

    Requires admin authentication.

    Returns:
        APIResponse with ReviewQueueResponse data.
    """
    # Check admin permission
    is_admin, user_id = await _check_admin(request, group_id, session)
    if not is_admin:
        return APIResponse.fail(
            "FORBIDDEN",
            "Admin access required",
        ).model_dump()

    # Fetch pending reviews
    decision_repo = DecisionRepository(session)
    pending = await decision_repo.get_pending_reviews(group_id)

    # Get user info for the decisions
    user_repo = UserRepository(session)
    user_ids = [d.user_id for d in pending]
    users = await user_repo.bulk_get_by_ids(user_ids)

    # Convert to review items
    items = [_decision_to_review_item(d, users.get(d.user_id)) for d in pending]

    # Apply pagination
    total = len(items)
    items = items[offset : offset + limit]

    response = ReviewQueueResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )

    return APIResponse.ok(response.model_dump()).model_dump()


async def override_decision(
    request: web.Request,
    session: AsyncSession,
    group_id: int,
    decision_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """
    Override a spam decision.

    Requires admin authentication.

    Args:
        request: aiohttp request
        session: Database session
        group_id: Telegram chat_id
        decision_id: UUID of the decision
        body: Request body with override action

    Returns:
        APIResponse with DecisionOverrideResponse data.
    """
    # Check admin permission
    is_admin, admin_id = await _check_admin(request, group_id, session)
    if not is_admin:
        return APIResponse.fail(
            "FORBIDDEN",
            "Admin access required",
        ).model_dump()

    # Validate request body
    try:
        override_request = DecisionOverrideRequest(**body)
    except ValidationError as e:
        return APIResponse.fail(
            "VALIDATION_ERROR",
            str(e.errors()),
        ).model_dump()

    # Parse decision UUID
    try:
        decision_uuid = UUID(decision_id)
    except ValueError:
        return APIResponse.fail(
            "VALIDATION_ERROR",
            "Invalid decision ID format",
        ).model_dump()

    # Fetch decision
    decision_repo = DecisionRepository(session)
    decision = await decision_repo.get_by_id(decision_uuid)

    if decision is None:
        return APIResponse.fail(
            "NOT_FOUND",
            f"Decision {decision_id} not found",
        ).model_dump()

    # Verify decision belongs to this group
    if decision.group_id != group_id:
        return APIResponse.fail(
            "FORBIDDEN",
            "Decision does not belong to this group",
        ).model_dump()

    # Determine new action based on override type
    new_action = "approved" if override_request.action == "approve" else "confirmed_block"

    # Record override
    previous_verdict = decision.verdict.value
    decision = await decision_repo.record_override(
        decision_id=decision_uuid,
        admin_id=admin_id,
        reason=override_request.reason or "",
        new_action=new_action,
    )

    if decision is None:
        return APIResponse.fail(
            "ERROR",
            "Failed to record override",
        ).model_dump()

    # If approving a blocked/banned user, restore their group membership
    # This handles false positive cases where user was wrongly removed
    user_restored = False
    if override_request.action == "approve" and decision.user_banned:
        member_repo = GroupMemberRepository(session)
        existing_member = await member_repo.get_member(group_id, decision.user_id)
        if existing_member is None:
            # Re-add user to group with LIMITED trust level (not NEW/SANDBOX)
            # This acknowledges they were a legitimate user
            member, created = await member_repo.create_or_update_member(
                group_id=group_id,
                user_id=decision.user_id,
                trust_level=TrustLevel.LIMITED,
                trust_score=60,  # Slightly above default to reflect admin approval
            )
            user_restored = created
            logger.info(
                "user_restored_after_override",
                group_id=group_id,
                user_id=decision.user_id,
                admin_id=admin_id,
            )

    # NOTE: Telegram unban API call is not performed here for same reasons as
    # blacklist_user (see note there). The admin should:
    # 1. Use Telegram's native unban, OR
    # 2. The user will need to rejoin the group manually
    # Database membership is restored so the bot won't re-block them

    logger.info(
        "decision_overridden",
        group_id=group_id,
        decision_id=decision_id,
        admin_id=admin_id,
        action=override_request.action,
        previous_verdict=previous_verdict,
        user_restored=user_restored,
    )

    response = DecisionOverrideResponse(
        decision_id=str(decision.id),
        previous_verdict=previous_verdict,
        new_action=new_action,
        overridden_by=admin_id,
        overridden_at=_format_datetime(decision.overridden_at) or "",
    )

    return APIResponse.ok(response.model_dump()).model_dump()


async def get_decisions(
    request: web.Request,
    session: AsyncSession,
    group_id: int,
    limit: int = 50,
    offset: int = 0,
    verdict: str | None = None,
) -> dict[str, Any]:
    """
    Get recent spam decisions for a group.

    Requires admin authentication.

    Returns:
        APIResponse with DecisionListResponse data.
    """
    # Check admin permission
    is_admin, user_id = await _check_admin(request, group_id, session)
    if not is_admin:
        return APIResponse.fail(
            "FORBIDDEN",
            "Admin access required",
        ).model_dump()

    # Parse verdict filter
    verdict_enum = None
    if verdict:
        try:
            verdict_enum = Verdict(verdict)
        except ValueError:
            return APIResponse.fail(
                "VALIDATION_ERROR",
                f"Invalid verdict: {verdict}",
            ).model_dump()

    # Fetch decisions
    decision_repo = DecisionRepository(session)
    decisions = await decision_repo.get_by_group(
        group_id,
        limit=limit,
        offset=offset,
        verdict=verdict_enum,
    )

    # Get user info
    user_repo = UserRepository(session)
    user_ids = [d.user_id for d in decisions]
    users = await user_repo.bulk_get_by_ids(user_ids)

    # Convert to review items
    items = [_decision_to_review_item(d, users.get(d.user_id)) for d in decisions]

    response = DecisionListResponse(
        decisions=items,
        total=len(items),
        limit=limit,
        offset=offset,
    )

    return APIResponse.ok(response.model_dump()).model_dump()


async def get_decision_detail(
    request: web.Request,
    session: AsyncSession,
    group_id: int,
    decision_id: str,
) -> dict[str, Any]:
    """
    Get detailed information about a specific decision.

    Requires admin authentication.

    Returns:
        APIResponse with DecisionDetail data.
    """
    # Check admin permission
    is_admin, user_id = await _check_admin(request, group_id, session)
    if not is_admin:
        return APIResponse.fail(
            "FORBIDDEN",
            "Admin access required",
        ).model_dump()

    # Parse decision UUID
    try:
        decision_uuid = UUID(decision_id)
    except ValueError:
        return APIResponse.fail(
            "VALIDATION_ERROR",
            "Invalid decision ID format",
        ).model_dump()

    # Fetch decision
    decision_repo = DecisionRepository(session)
    decision = await decision_repo.get_by_id(decision_uuid)

    if decision is None:
        return APIResponse.fail(
            "NOT_FOUND",
            f"Decision {decision_id} not found",
        ).model_dump()

    # Verify decision belongs to this group
    if decision.group_id != group_id:
        return APIResponse.fail(
            "FORBIDDEN",
            "Decision does not belong to this group",
        ).model_dump()

    # Get user info
    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(decision.user_id)

    detail = DecisionDetail(
        id=str(decision.id),
        group_id=decision.group_id,
        user_id=decision.user_id,
        username=user.username if user else None,
        first_name=user.first_name if user else None,
        message_id=decision.message_id,
        risk_score=decision.risk_score,
        verdict=decision.verdict.value,
        threat_type=decision.threat_type,
        profile_signals=decision.profile_signals or {},
        content_signals=decision.content_signals or {},
        behavior_signals=decision.behavior_signals or {},
        llm_used=decision.llm_used,
        llm_response=decision.llm_response,
        llm_latency_ms=decision.llm_latency_ms,
        action_taken=decision.action_taken,
        message_deleted=decision.message_deleted,
        user_banned=decision.user_banned,
        user_restricted=decision.user_restricted,
        overridden_by=decision.overridden_by,
        overridden_at=_format_datetime(decision.overridden_at),
        override_reason=decision.override_reason,
        created_at=_format_datetime(decision.created_at) or "",
        processing_time_ms=decision.processing_time_ms,
    )

    return APIResponse.ok(detail.model_dump()).model_dump()


# =============================================================================
# User Management Handlers
# =============================================================================


async def get_user_profile(
    request: web.Request,
    session: AsyncSession,
    group_id: int,
    target_user_id: int,
) -> dict[str, Any]:
    """
    Get user's profile and risk assessment in a group.

    Requires admin authentication.

    Returns:
        APIResponse with UserProfileResponse data.
    """
    # Check admin permission
    is_admin, user_id = await _check_admin(request, group_id, session)
    if not is_admin:
        return APIResponse.fail(
            "FORBIDDEN",
            "Admin access required",
        ).model_dump()

    # Fetch member
    member_repo = GroupMemberRepository(session)
    member = await member_repo.get_member_with_user(group_id, target_user_id)

    if member is None:
        return APIResponse.fail(
            "NOT_FOUND",
            f"User {target_user_id} not found in group {group_id}",
        ).model_dump()

    # Get user profile data
    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(target_user_id)

    profile = _member_to_profile_response(member, user)
    return APIResponse.ok(profile.model_dump()).model_dump()


async def get_user_stats(
    request: web.Request,
    session: AsyncSession,
    target_user_id: int,
) -> dict[str, Any]:
    """
    Get user's spam history across all groups.

    Requires authentication (any authenticated user can view this).

    Returns:
        APIResponse with UserStatsResponse data.
    """
    # Get authenticated user
    auth: WebAppAuth | None = request.get("webapp_auth")
    if auth is None or auth.user_id is None:
        return APIResponse.fail(
            "UNAUTHORIZED",
            "Authentication required",
        ).model_dump()

    # Fetch user profile
    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(target_user_id)

    if user is None:
        return APIResponse.fail(
            "NOT_FOUND",
            f"User {target_user_id} not found",
        ).model_dump()

    # Get decision history
    decision_repo = DecisionRepository(session)
    decisions = await decision_repo.get_by_user(target_user_id, limit=20)

    # Count blocks and reviews
    total_blocks = sum(1 for d in decisions if d.verdict == Verdict.BLOCK)
    total_reviews = sum(1 for d in decisions if d.verdict == Verdict.REVIEW)

    # Get group membership count and total messages
    member_repo = GroupMemberRepository(session)
    total_groups = await member_repo.count_user_groups(target_user_id)
    total_messages = await member_repo.sum_user_messages(target_user_id)

    response = UserStatsResponse(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        total_groups=total_groups,
        total_messages=total_messages,
        total_blocks=total_blocks,
        total_reviews=total_reviews,
        recent_decisions=[_decision_to_review_item(d, user) for d in decisions[:10]],
    )

    return APIResponse.ok(response.model_dump()).model_dump()


async def whitelist_user(
    request: web.Request,
    session: AsyncSession,
    group_id: int,
    target_user_id: int,
    body: dict[str, Any],
) -> dict[str, Any]:
    """
    Add user to group whitelist (trusted status).

    Requires admin authentication.

    Returns:
        APIResponse with success status.
    """
    # Check admin permission
    is_admin, admin_id = await _check_admin(request, group_id, session)
    if not is_admin:
        return APIResponse.fail(
            "FORBIDDEN",
            "Admin access required",
        ).model_dump()

    reason = body.get("reason", "")

    # Promote user to trusted
    member_repo = GroupMemberRepository(session)
    member = await member_repo.promote_to_trusted(group_id, target_user_id)

    if member is None:
        return APIResponse.fail(
            "NOT_FOUND",
            f"User {target_user_id} not found in group {group_id}",
        ).model_dump()

    logger.info(
        "user_whitelisted",
        group_id=group_id,
        user_id=target_user_id,
        admin_id=admin_id,
        reason=reason,
    )

    return APIResponse.ok(
        {
            "user_id": target_user_id,
            "action": "whitelisted",
            "trust_level": member.trust_level.value,
        }
    ).model_dump()


async def blacklist_user(
    request: web.Request,
    session: AsyncSession,
    group_id: int,
    target_user_id: int,
    body: dict[str, Any],
) -> dict[str, Any]:
    """
    Add user to group blacklist and ban.

    Requires admin authentication.

    Returns:
        APIResponse with success status.
    """
    # Check admin permission
    is_admin, admin_id = await _check_admin(request, group_id, session)
    if not is_admin:
        return APIResponse.fail(
            "FORBIDDEN",
            "Admin access required",
        ).model_dump()

    reason = body.get("reason", "")

    # Remove member from group (this doesn't actually ban via Telegram API)
    # The actual ban would need to be done via the bot
    member_repo = GroupMemberRepository(session)
    removed = await member_repo.remove_member(group_id, target_user_id)

    if not removed:
        return APIResponse.fail(
            "NOT_FOUND",
            f"User {target_user_id} not found in group {group_id}",
        ).model_dump()

    logger.info(
        "user_blacklisted",
        group_id=group_id,
        user_id=target_user_id,
        admin_id=admin_id,
        reason=reason,
    )

    # NOTE: Telegram ban API call is deferred for architectural separation:
    # 1. The mini_app module is a pure aiohttp REST API without bot dependencies
    # 2. Bot instance (aiogram Bot) lives in the bot/ module only
    # 3. This maintains clean separation: mini_app handles data, bot handles Telegram
    #
    # Current behavior:
    # - User is removed from group_members table immediately
    # - User will be blocked on next message (ActionEngine checks membership)
    # - For immediate ban, admin should use Telegram's native ban or /ban command
    #
    # Future enhancement options:
    # - Add Redis pub/sub for mini_app -> bot communication
    # - Create a background task queue for deferred bot actions
    # - Expose internal RPC endpoint for bot module to poll

    return APIResponse.ok(
        {
            "user_id": target_user_id,
            "action": "blacklisted",
        }
    ).model_dump()
