"""
SAQSHY Bot Module

Telegram bot layer using aiogram 3.x.

This module handles:
- Bot initialization and configuration
- Message handlers for spam detection
- Callback handlers for admin actions
- Command handlers for bot commands
- Middlewares for authentication, logging, and rate limiting
- Custom filters for message routing
- Message processing pipeline orchestration

Usage:
    from saqshy.bot import create_bot, create_dispatcher, setup_webhook, MessagePipeline

    bot = create_bot(token="BOT_TOKEN")
    dp = create_dispatcher(cache_service=cache)
    await setup_webhook(bot, "https://example.com/webhook", "secret")

    # Use the message pipeline
    pipeline = MessagePipeline(
        risk_calculator=risk_calc,
        content_analyzer=content_analyzer,
        profile_analyzer=profile_analyzer,
        behavior_analyzer=behavior_analyzer,
        spam_db=spam_db_service,
        llm_service=llm_service,
        cache_service=cache_service,
    )
    result = await pipeline.process(context)
"""

from saqshy.bot.action_engine import ActionEngine
from saqshy.bot.bot import (
    create_bot,
    create_dispatcher,
    remove_webhook,
    setup_webhook,
    verify_webhook_secret,
)
from saqshy.bot.handlers import router
from saqshy.bot.pipeline import (
    ANALYZER_TIMEOUT,
    CHANNEL_SUB_TIMEOUT,
    LLM_TIMEOUT,
    SPAM_DB_TIMEOUT,
    TOTAL_PIPELINE_TIMEOUT,
    CircuitBreakerState,
    MessagePipeline,
    PipelineMetrics,
)

__all__ = [
    # Bot factory functions
    "create_bot",
    "create_dispatcher",
    "setup_webhook",
    "remove_webhook",
    "verify_webhook_secret",
    # Action engine
    "ActionEngine",
    # Main router
    "router",
    # Pipeline
    "MessagePipeline",
    "PipelineMetrics",
    "CircuitBreakerState",
    # Pipeline configuration
    "ANALYZER_TIMEOUT",
    "SPAM_DB_TIMEOUT",
    "CHANNEL_SUB_TIMEOUT",
    "LLM_TIMEOUT",
    "TOTAL_PIPELINE_TIMEOUT",
]
