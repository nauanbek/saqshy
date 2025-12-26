"""
SAQSHY Bot Adapters

Adapter implementations for core protocols.
These adapters wrap aiogram-specific functionality.
"""

from saqshy.bot.adapters.telegram_restrictions import TelegramRestrictionsAdapter

__all__ = [
    "TelegramRestrictionsAdapter",
]
