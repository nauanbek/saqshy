"""
SAQSHY - AI-powered Telegram Anti-Spam Bot

Uses Cumulative Risk Score architecture to detect and block spam
while minimizing false positives.

Philosophy: Make spam attacks economically unfeasible. No single signal
is decisive. Better to let 2-3% spam through than block a legitimate user.
"""

__version__ = "2.0.0"
__author__ = "SAQSHY Team"

from saqshy.core.types import GroupType, RiskResult, Signals, Verdict

__all__ = [
    "__version__",
    "GroupType",
    "Verdict",
    "Signals",
    "RiskResult",
]
