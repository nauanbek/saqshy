"""
SAQSHY Decision Audit Trail

Comprehensive audit logging for all moderation decisions.

The audit trail captures:
- Every moderation decision with full context
- All signal scores and contributing factors
- Processing times and LLM usage
- Admin overrides and confirmations
- User actions (whitelist, blacklist)

This data is stored in PostgreSQL for:
- Mini App decision review
- FP/TP analysis
- Model improvement
- Compliance and accountability

Example:
    >>> audit = AuditTrail(session_factory, metrics_collector)
    >>> await audit.log_decision(
    ...     correlation_id="abc12345",
    ...     context=message_context,
    ...     result=risk_result,
    ...     metrics=pipeline_metrics,
    ... )
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from saqshy.core.logging import get_logger, log_decision
from saqshy.core.types import MessageContext, RiskResult

logger = get_logger(__name__)


# =============================================================================
# Audit Event Types
# =============================================================================


@dataclass
class AuditEvent:
    """Base class for audit events."""

    correlation_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_type: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
        }


@dataclass
class ModerationDecisionEvent(AuditEvent):
    """Audit event for a moderation decision."""

    event_type: str = "moderation_decision"

    # Identifiers
    group_id: int = 0
    user_id: int = 0
    message_id: int | None = None

    # Group context
    group_type: str = "general"

    # Decision outcome
    verdict: str = "allow"
    risk_score: int = 0
    threat_type: str = "none"

    # Score breakdown
    profile_score: int = 0
    content_score: int = 0
    behavior_score: int = 0
    network_score: int = 0

    # Signals (for debugging and analysis)
    profile_signals: dict[str, Any] = field(default_factory=dict)
    content_signals: dict[str, Any] = field(default_factory=dict)
    behavior_signals: dict[str, Any] = field(default_factory=dict)
    network_signals: dict[str, Any] = field(default_factory=dict)

    # Contributing factors (explainability)
    contributing_factors: list[str] = field(default_factory=list)
    mitigating_factors: list[str] = field(default_factory=list)

    # LLM usage
    llm_called: bool = False
    llm_verdict: str | None = None
    llm_explanation: str | None = None
    llm_latency_ms: float | None = None

    # Spam DB match
    spam_db_match: bool = False
    spam_db_similarity: float = 0.0
    spam_db_matched_pattern: str | None = None

    # Timing
    total_latency_ms: float = 0.0
    profile_latency_ms: float = 0.0
    content_latency_ms: float = 0.0
    behavior_latency_ms: float = 0.0
    spam_db_latency_ms: float = 0.0

    # Action taken
    action_taken: str | None = None
    message_deleted: bool = False
    user_banned: bool = False
    user_restricted: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        base = super().to_dict()
        base.update(
            {
                "group_id": self.group_id,
                "user_id": self.user_id,
                "message_id": self.message_id,
                "group_type": self.group_type,
                "verdict": self.verdict,
                "risk_score": self.risk_score,
                "threat_type": self.threat_type,
                "profile_score": self.profile_score,
                "content_score": self.content_score,
                "behavior_score": self.behavior_score,
                "network_score": self.network_score,
                "profile_signals": self.profile_signals,
                "content_signals": self.content_signals,
                "behavior_signals": self.behavior_signals,
                "network_signals": self.network_signals,
                "contributing_factors": self.contributing_factors,
                "mitigating_factors": self.mitigating_factors,
                "llm_called": self.llm_called,
                "llm_verdict": self.llm_verdict,
                "llm_explanation": self.llm_explanation,
                "llm_latency_ms": self.llm_latency_ms,
                "spam_db_match": self.spam_db_match,
                "spam_db_similarity": self.spam_db_similarity,
                "total_latency_ms": self.total_latency_ms,
                "action_taken": self.action_taken,
                "message_deleted": self.message_deleted,
                "user_banned": self.user_banned,
                "user_restricted": self.user_restricted,
            }
        )
        return base


@dataclass
class AdminOverrideEvent(AuditEvent):
    """Audit event for an admin override."""

    event_type: str = "admin_override"

    decision_id: UUID | None = None
    group_id: int = 0
    admin_id: int = 0
    target_user_id: int = 0

    original_verdict: str = ""
    new_action: str = ""
    reason: str = ""

    # Was this a false positive?
    is_false_positive: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        base = super().to_dict()
        base.update(
            {
                "decision_id": str(self.decision_id) if self.decision_id else None,
                "group_id": self.group_id,
                "admin_id": self.admin_id,
                "target_user_id": self.target_user_id,
                "original_verdict": self.original_verdict,
                "new_action": self.new_action,
                "reason": self.reason,
                "is_false_positive": self.is_false_positive,
            }
        )
        return base


@dataclass
class AdminActionEvent(AuditEvent):
    """Audit event for other admin actions."""

    event_type: str = "admin_action"

    group_id: int = 0
    admin_id: int = 0
    target_user_id: int | None = None

    action_type: str = ""  # whitelist, blacklist, ban, unban, settings_change
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        base = super().to_dict()
        base.update(
            {
                "group_id": self.group_id,
                "admin_id": self.admin_id,
                "target_user_id": self.target_user_id,
                "action_type": self.action_type,
                "details": self.details,
            }
        )
        return base


# =============================================================================
# Audit Trail Service
# =============================================================================


class AuditTrail:
    """
    Audit trail service for logging all moderation decisions.

    Provides:
    - Structured logging of every decision
    - Database persistence for Mini App review
    - Metrics integration for FP/TP tracking
    - Error handling with graceful degradation

    Example:
        >>> audit = AuditTrail(session_factory, metrics)
        >>> decision_id = await audit.log_decision(
        ...     correlation_id="abc123",
        ...     context=context,
        ...     result=result,
        ...     metrics=pipeline_metrics,
        ... )
    """

    def __init__(
        self,
        session_factory: Any | None = None,
        metrics_collector: Any | None = None,
    ) -> None:
        """
        Initialize audit trail.

        Args:
            session_factory: SQLAlchemy async session factory.
            metrics_collector: MetricsCollector for updating metrics.
        """
        self.session_factory = session_factory
        self.metrics = metrics_collector
        self._logger = get_logger(__name__)

    async def log_decision(
        self,
        correlation_id: str,
        context: MessageContext,
        result: RiskResult,
        *,
        pipeline_metrics: dict[str, Any] | None = None,
        action_taken: str | None = None,
        message_deleted: bool = False,
        user_banned: bool = False,
        user_restricted: bool = False,
    ) -> UUID | None:
        """
        Log a moderation decision.

        This is the primary method for recording spam detection outcomes.
        Writes to both structured logs and database.

        Args:
            correlation_id: Request correlation ID.
            context: MessageContext with message data.
            result: RiskResult from the pipeline.
            pipeline_metrics: Optional timing metrics from pipeline.
            action_taken: Description of action taken.
            message_deleted: Whether message was deleted.
            user_banned: Whether user was banned.
            user_restricted: Whether user was restricted.

        Returns:
            Decision UUID if saved to database, None otherwise.
        """
        metrics = pipeline_metrics or {}

        # Build audit event
        event = ModerationDecisionEvent(
            correlation_id=correlation_id,
            group_id=context.chat_id,
            user_id=context.user_id,
            message_id=context.message_id,
            group_type=context.group_type.value,
            verdict=result.verdict.value,
            risk_score=result.score,
            threat_type=result.threat_type.value if result.threat_type else "none",
            profile_score=result.profile_score,
            content_score=result.content_score,
            behavior_score=result.behavior_score,
            network_score=result.network_score,
            profile_signals=asdict(result.signals.profile) if result.signals else {},
            content_signals=asdict(result.signals.content) if result.signals else {},
            behavior_signals=asdict(result.signals.behavior) if result.signals else {},
            network_signals=asdict(result.signals.network) if result.signals else {},
            contributing_factors=result.contributing_factors,
            mitigating_factors=result.mitigating_factors,
            llm_called=result.needs_llm and result.llm_verdict is not None,
            llm_verdict=result.llm_verdict.value if result.llm_verdict else None,
            llm_explanation=result.llm_explanation,
            llm_latency_ms=metrics.get("llm_ms"),
            spam_db_match=result.signals.network.spam_db_similarity > 0.7
            if result.signals
            else False,
            spam_db_similarity=result.signals.network.spam_db_similarity if result.signals else 0.0,
            spam_db_matched_pattern=result.signals.network.spam_db_matched_pattern
            if result.signals
            else None,
            total_latency_ms=metrics.get("total_ms", 0),
            profile_latency_ms=metrics.get("profile_ms", 0),
            content_latency_ms=metrics.get("content_ms", 0),
            behavior_latency_ms=metrics.get("behavior_ms", 0),
            spam_db_latency_ms=metrics.get("spam_db_ms", 0),
            action_taken=action_taken,
            message_deleted=message_deleted,
            user_banned=user_banned,
            user_restricted=user_restricted,
        )

        # Log to structured logs
        self._log_to_structlog(event)

        # Record metrics
        await self._record_metrics(event)

        # Persist to database
        decision_id = await self._persist_to_database(event)

        return decision_id

    async def log_override(
        self,
        correlation_id: str,
        decision_id: UUID,
        group_id: int,
        admin_id: int,
        target_user_id: int,
        original_verdict: str,
        new_action: str,
        reason: str,
    ) -> None:
        """
        Log an admin override of a decision.

        Called when an admin approves a blocked message or takes
        different action than the automated decision.

        Args:
            correlation_id: Request correlation ID.
            decision_id: UUID of the original decision.
            group_id: Group ID.
            admin_id: Admin user ID.
            target_user_id: Affected user ID.
            original_verdict: Original automated verdict.
            new_action: Action taken by admin.
            reason: Reason for override.
        """
        # Determine if this is a false positive
        is_fp = original_verdict.lower() in ("block", "review") and new_action.lower() in (
            "approve",
            "allow",
            "unban",
        )

        event = AdminOverrideEvent(
            correlation_id=correlation_id,
            decision_id=decision_id,
            group_id=group_id,
            admin_id=admin_id,
            target_user_id=target_user_id,
            original_verdict=original_verdict,
            new_action=new_action,
            reason=reason,
            is_false_positive=is_fp,
        )

        # Log to structured logs
        self._logger.info(
            "admin_override",
            correlation_id=correlation_id,
            decision_id=str(decision_id),
            group_id=group_id,
            admin_id=admin_id,
            target_user_id=target_user_id,
            original_verdict=original_verdict,
            new_action=new_action,
            is_false_positive=is_fp,
        )

        # Update metrics for FP tracking
        if self.metrics and is_fp:
            # Fetch decision from database to get actual group_type and threat_type
            decision_data = await self._get_decision_details(decision_id)
            group_type = decision_data.get("group_type", "general") if decision_data else "general"
            threat_type = (
                decision_data.get("threat_type", "unknown") if decision_data else "unknown"
            )

            await self.metrics.record_fp_override(
                group_type=group_type,
                threat_type=threat_type or "unknown",
                decision_id=str(decision_id),
            )

        # Persist override to database
        await self._persist_override(event)

    async def log_admin_action(
        self,
        correlation_id: str,
        group_id: int,
        admin_id: int,
        action_type: str,
        target_user_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Log an admin action (whitelist, blacklist, settings change).

        Args:
            correlation_id: Request correlation ID.
            group_id: Group ID.
            admin_id: Admin user ID.
            action_type: Type of action.
            target_user_id: Optional target user.
            details: Additional action details.
        """
        event = AdminActionEvent(
            correlation_id=correlation_id,
            group_id=group_id,
            admin_id=admin_id,
            target_user_id=target_user_id,
            action_type=action_type,
            details=details or {},
        )

        self._logger.info(
            "admin_action",
            correlation_id=correlation_id,
            group_id=group_id,
            admin_id=admin_id,
            action_type=action_type,
            target_user_id=target_user_id,
        )

        await self._persist_admin_action(event)

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _log_to_structlog(self, event: ModerationDecisionEvent) -> None:
        """Log decision to structured logs."""
        log_decision(
            self._logger,
            correlation_id=event.correlation_id,
            user_id=event.user_id,
            chat_id=event.group_id,
            message_id=event.message_id,
            group_type=event.group_type,
            verdict=event.verdict,
            risk_score=event.risk_score,
            threat_type=event.threat_type,
            total_latency_ms=event.total_latency_ms,
            profile_score=event.profile_score,
            content_score=event.content_score,
            behavior_score=event.behavior_score,
            network_score=event.network_score,
            llm_called=event.llm_called,
            llm_latency_ms=event.llm_latency_ms,
            spam_db_match=event.spam_db_match,
            spam_db_score=event.spam_db_similarity,
            contributing_factors=event.contributing_factors,
            mitigating_factors=event.mitigating_factors,
        )

    async def _record_metrics(self, event: ModerationDecisionEvent) -> None:
        """Record metrics for the decision."""
        if not self.metrics:
            return

        try:
            await self.metrics.record_verdict(
                group_type=event.group_type,
                verdict=event.verdict,
                risk_score=event.risk_score,
                threat_type=event.threat_type,
                latency_ms=event.total_latency_ms,
                llm_called=event.llm_called,
                llm_latency_ms=event.llm_latency_ms,
            )
        except Exception as e:
            self._logger.warning(
                "metrics_recording_failed",
                error=str(e),
            )

    async def _persist_to_database(
        self,
        event: ModerationDecisionEvent,
    ) -> UUID | None:
        """Persist decision to database."""
        if not self.session_factory:
            return None

        try:
            from saqshy.core.types import Verdict
            from saqshy.db.repositories.decisions import DecisionRepository

            async with self.session_factory() as session:
                repo = DecisionRepository(session)

                decision = await repo.create_decision(
                    group_id=event.group_id,
                    user_id=event.user_id,
                    message_id=event.message_id,
                    risk_score=event.risk_score,
                    verdict=Verdict(event.verdict),
                    threat_type=event.threat_type,
                    profile_signals=event.profile_signals,
                    content_signals=event.content_signals,
                    behavior_signals=event.behavior_signals,
                    llm_used=event.llm_called,
                    llm_response={
                        "verdict": event.llm_verdict,
                        "explanation": event.llm_explanation,
                    }
                    if event.llm_called
                    else None,
                    llm_latency_ms=int(event.llm_latency_ms) if event.llm_latency_ms else None,
                    action_taken=event.action_taken,
                    message_deleted=event.message_deleted,
                    user_banned=event.user_banned,
                    user_restricted=event.user_restricted,
                    processing_time_ms=int(event.total_latency_ms),
                )

                await session.commit()
                return decision.id

        except Exception as e:
            self._logger.warning(
                "decision_persistence_failed",
                error=str(e),
                correlation_id=event.correlation_id,
            )
            return None

    async def _persist_override(self, event: AdminOverrideEvent) -> None:
        """Persist admin override to database."""
        if not self.session_factory or not event.decision_id:
            return

        try:
            from saqshy.db.repositories.decisions import DecisionRepository

            async with self.session_factory() as session:
                repo = DecisionRepository(session)

                await repo.record_override(
                    decision_id=event.decision_id,
                    admin_id=event.admin_id,
                    reason=event.reason,
                    new_action=event.new_action,
                )

                await session.commit()

        except Exception as e:
            self._logger.warning(
                "override_persistence_failed",
                error=str(e),
                correlation_id=event.correlation_id,
            )

    async def _persist_admin_action(self, event: AdminActionEvent) -> None:
        """Persist admin action to database."""
        if not self.session_factory:
            return

        try:
            from saqshy.db.models import AdminAction

            async with self.session_factory() as session:
                action = AdminAction(
                    group_id=event.group_id,
                    admin_id=event.admin_id,
                    action_type=event.action_type,
                    target_user_id=event.target_user_id,
                    details=event.details,
                )
                session.add(action)
                await session.commit()

        except Exception as e:
            self._logger.warning(
                "admin_action_persistence_failed",
                error=str(e),
                correlation_id=event.correlation_id,
            )

    async def _get_decision_details(self, decision_id: UUID) -> dict[str, Any] | None:
        """Fetch decision details from database.

        Args:
            decision_id: UUID of the decision to fetch.

        Returns:
            Dictionary with group_type and threat_type, or None if not found.
        """
        if not self.session_factory:
            return None

        try:
            from saqshy.db.repositories.decisions import DecisionRepository

            async with self.session_factory() as session:
                repo = DecisionRepository(session)
                decision = await repo.get_by_id_with_group(decision_id)

                if decision is None:
                    return None

                return {
                    "group_type": decision.group.group_type.value if decision.group else "general",
                    "threat_type": decision.threat_type,
                }

        except Exception as e:
            self._logger.warning(
                "decision_fetch_failed",
                error=str(e),
                decision_id=str(decision_id),
            )
            return None


# =============================================================================
# Utility Functions
# =============================================================================


def create_audit_trail(
    session_factory: Any | None = None,
    metrics_collector: Any | None = None,
) -> AuditTrail:
    """
    Create an AuditTrail instance.

    Factory function for creating audit trail with dependencies.

    Args:
        session_factory: SQLAlchemy async session factory.
        metrics_collector: MetricsCollector instance.

    Returns:
        Configured AuditTrail instance.
    """
    return AuditTrail(
        session_factory=session_factory,
        metrics_collector=metrics_collector,
    )
