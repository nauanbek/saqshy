"""
SAQSHY Analyzers Module

Signal extraction from various data sources.

Analyzers extract signals that are used by the RiskCalculator:
- ProfileAnalyzer: Analyzes user profile data
- ContentAnalyzer: Analyzes message content
- BehaviorAnalyzer: Analyzes user behavior patterns
- SpamDBAnalyzer: Compares against known spam patterns

Protocol classes for dependency injection:
- MessageHistoryProvider: Interface for message history storage
- ChannelSubscriptionChecker: Interface for channel subscription checks

Helper functions:
- get_account_age_tier_signal: Get tiered account age signal and weight
"""

from saqshy.analyzers.behavior import (
    BehaviorAnalyzer,
    ChannelSubscriptionChecker,
    FloodDetector,
    MessageHistoryProvider,
)
from saqshy.analyzers.content import ContentAnalyzer
from saqshy.analyzers.profile import ProfileAnalyzer, get_account_age_tier_signal
from saqshy.analyzers.signals import SignalAggregator

__all__ = [
    # Analyzers
    "ProfileAnalyzer",
    "ContentAnalyzer",
    "BehaviorAnalyzer",
    "SignalAggregator",
    "FloodDetector",
    # Protocol classes (for dependency injection)
    "MessageHistoryProvider",
    "ChannelSubscriptionChecker",
    # Helper functions
    "get_account_age_tier_signal",
]
