"""
SAQSHY Bot Filters

Custom aiogram filters for message routing.

Available filters:
- AdminFilter: Check if user is group admin (with caching)
- IsAdmin: Alias for AdminFilter (backward compatibility)
- IsGroupAdmin: Check if user is admin in a group (not private)
- IsBotAdmin: Check if bot has admin permissions
- IsCreator: Check if user is group creator
- IsWhitelisted: Check if user is whitelisted
"""

from saqshy.bot.filters.admin import (
    AdminFilter,
    IsAdmin,
    IsBotAdmin,
    IsCreator,
    IsGroupAdmin,
    IsWhitelisted,
)

__all__ = [
    "AdminFilter",
    "IsAdmin",
    "IsGroupAdmin",
    "IsBotAdmin",
    "IsCreator",
    "IsWhitelisted",
]
