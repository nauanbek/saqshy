"""
SAQSHY Core Domain Module

This module contains the core domain logic with ZERO external dependencies.
It should not import from any other saqshy modules except within core/.

Components:
- types: Shared types (Signals, RiskResult, Verdict)
- constants: Weights, thresholds, and configuration values
- risk_calculator: Risk score calculation
- sandbox: Sandbox and Soft Watch mode logic
- protocols: Abstract interfaces for dependency injection
- log_facade: Lightweight logging facade (stdlib-only)
- logging: Structured logging with correlation IDs (uses structlog for config)
- metrics: Metrics collection for observability
- audit: Decision audit trail

Architecture Note:
    core/ now has ZERO external dependencies beyond stdlib.
    All Telegram operations are abstracted via ChatRestrictionsProtocol.
    All logging in core modules uses LoggerProtocol via log_facade.

Note: ActionEngine and TelegramRestrictionsAdapter are in bot/ module.
"""

from saqshy.core.audit import (
    AdminOverrideEvent,
    AuditTrail,
    ModerationDecisionEvent,
    create_audit_trail,
)
from saqshy.core.constants import (
    BEHAVIOR_WEIGHTS,
    CONTENT_WEIGHTS,
    DEALS_WEIGHT_OVERRIDES,
    NETWORK_WEIGHTS,
    PROFILE_WEIGHTS,
    THRESHOLDS,
)
from saqshy.core.log_facade import (
    StdlibLogger,
    set_logger_factory,
)
from saqshy.core.log_facade import (
    get_logger as get_facade_logger,
)
from saqshy.core.logging import (
    LogContext,
    configure_logging,
    get_correlation_id,
    get_logger,
    log_decision,
    log_error,
    set_correlation_id,
)
from saqshy.core.metrics import (
    AccuracyMetrics,
    LatencyMetrics,
    MetricsCollector,
    VerdictMetrics,
    check_alerts,
)
from saqshy.core.protocols import (
    CacheProtocol,
    ChannelSubscriptionProtocol,
    ChatRestrictionsProtocol,
    LoggerProtocol,
    TelegramOperationError,
)
from saqshy.core.sandbox import (
    DEFAULT_APPROVED_MESSAGES_TO_RELEASE,
    DEFAULT_SANDBOX_DURATION_HOURS,
    DEFAULT_SOFT_WATCH_DURATION_HOURS,
    SOFT_WATCH_THRESHOLDS,
    TRUST_SCORE_ADJUSTMENTS,
    ReleaseReason,
    SandboxConfig,
    SandboxManager,
    SandboxState,
    SandboxStatus,
    SoftWatchMode,
    SoftWatchState,
    SoftWatchVerdict,
    TrustLevel,
    TrustManager,
)
from saqshy.core.types import (
    GroupType,
    MessageContext,
    RiskResult,
    Signals,
    ThreatType,
    Verdict,
)

__all__ = [
    # Types
    "GroupType",
    "Verdict",
    "ThreatType",
    "Signals",
    "RiskResult",
    "MessageContext",
    # Constants
    "THRESHOLDS",
    "PROFILE_WEIGHTS",
    "CONTENT_WEIGHTS",
    "BEHAVIOR_WEIGHTS",
    "NETWORK_WEIGHTS",
    "DEALS_WEIGHT_OVERRIDES",
    # Protocols
    "LoggerProtocol",
    "CacheProtocol",
    "ChannelSubscriptionProtocol",
    "ChatRestrictionsProtocol",
    "TelegramOperationError",
    # Log Facade
    "StdlibLogger",
    "get_facade_logger",
    "set_logger_factory",
    # Sandbox
    "SandboxStatus",
    "TrustLevel",
    "ReleaseReason",
    "SandboxState",
    "SandboxConfig",
    "SoftWatchVerdict",
    "SoftWatchState",
    "SandboxManager",
    "SoftWatchMode",
    "TrustManager",
    "DEFAULT_SANDBOX_DURATION_HOURS",
    "DEFAULT_SOFT_WATCH_DURATION_HOURS",
    "DEFAULT_APPROVED_MESSAGES_TO_RELEASE",
    "TRUST_SCORE_ADJUSTMENTS",
    "SOFT_WATCH_THRESHOLDS",
    # Logging
    "configure_logging",
    "get_logger",
    "get_correlation_id",
    "set_correlation_id",
    "LogContext",
    "log_decision",
    "log_error",
    # Metrics
    "MetricsCollector",
    "VerdictMetrics",
    "LatencyMetrics",
    "AccuracyMetrics",
    "check_alerts",
    # Audit
    "AuditTrail",
    "ModerationDecisionEvent",
    "AdminOverrideEvent",
    "create_audit_trail",
]
