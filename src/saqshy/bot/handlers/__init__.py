"""
SAQSHY Bot Handlers

Message and event handlers for the Telegram bot.

Handlers are organized by purpose:
- messages: Handle incoming messages for spam detection
- members: Handle join/leave events
- commands: Handle admin and user commands
- callbacks: Handle inline keyboard callbacks

Router Registration Order:
1. commands_router - Command handlers (highest priority)
2. callbacks_router - Callback query handlers
3. members_router - ChatMemberUpdated handlers
4. messages_router - Message handlers (lowest priority, catch-all)

This order ensures commands are matched before the general message handler.
"""

from aiogram import Router

from saqshy.bot.handlers.callbacks import router as callbacks_router
from saqshy.bot.handlers.commands import router as commands_router
from saqshy.bot.handlers.members import router as members_router
from saqshy.bot.handlers.messages import router as messages_router

# Create main router that includes all sub-routers
router = Router(name="main")

# Include sub-routers in priority order
# Commands first - they should match before generic message handlers
router.include_router(commands_router)

# Callbacks for inline keyboard interactions
router.include_router(callbacks_router)

# Member updates (joins, leaves, etc.)
router.include_router(members_router)

# Messages last - general message handler is catch-all
router.include_router(messages_router)

__all__ = [
    "router",
    "commands_router",
    "callbacks_router",
    "members_router",
    "messages_router",
]
