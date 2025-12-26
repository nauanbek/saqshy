"""
SAQSHY Services Module

External service integrations.

Services handle communication with external APIs and databases:
- LLMService: Claude API for gray zone decisions
- EmbeddingsService: Cohere embeddings for spam database
- SpamDBService: Qdrant vector database for spam patterns
- CacheService: Redis caching
- NetworkAnalyzer: Cross-group behavior tracking
- ChannelSubscriptionService: Telegram channel subscription checks
"""

from saqshy.services.cache import CacheService
from saqshy.services.channel_subscription import (
    ChannelSubscriptionService,
    SubscriptionStatus,
)
from saqshy.services.embeddings import EmbeddingsService
from saqshy.services.llm import LLMResult, LLMService
from saqshy.services.network import NetworkAnalyzer
from saqshy.services.spam_db import SpamDBService

__all__ = [
    "CacheService",
    "ChannelSubscriptionService",
    "EmbeddingsService",
    "LLMResult",
    "LLMService",
    "NetworkAnalyzer",
    "SpamDBService",
    "SubscriptionStatus",
]
