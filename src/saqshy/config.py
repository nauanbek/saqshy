"""
SAQSHY Configuration

Centralized configuration management using Pydantic Settings.
All settings are loaded from environment variables with sensible defaults.

Note: GroupType is imported from core/types.py - the canonical source of truth
for domain types. THRESHOLDS are imported from core/constants.py.
"""

from enum import Enum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Import THRESHOLDS from canonical location for get_thresholds function
from saqshy.core.constants import THRESHOLDS

# Import GroupType from canonical location (core/types.py has ZERO external deps)
from saqshy.core.types import GroupType


class Environment(str, Enum):
    """Application environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class TelegramSettings(BaseSettings):
    """Telegram Bot configuration."""

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_", env_file=".env", extra="ignore")

    bot_token: SecretStr = Field(..., description="Telegram Bot API token")
    webhook_secret: SecretStr = Field(
        default=SecretStr(""), description="Webhook verification secret"
    )


class WebhookSettings(BaseSettings):
    """Webhook configuration."""

    model_config = SettingsConfigDict(env_prefix="WEBHOOK_", env_file=".env", extra="ignore")

    base_url: str = Field(..., description="Base URL for webhook")
    path: str = Field(default="/webhook", description="Webhook path")
    secret: SecretStr = Field(default=SecretStr(""), description="Webhook secret")


class DatabaseSettings(BaseSettings):
    """PostgreSQL database configuration."""

    model_config = SettingsConfigDict(env_prefix="DATABASE_", env_file=".env", extra="ignore")

    url: SecretStr = Field(
        default=SecretStr("postgresql+asyncpg://saqshy:password@localhost:5432/saqshy"),
        description="Database connection URL",
    )
    pool_size: int = Field(default=10, ge=1, le=100, description="Connection pool size")
    max_overflow: int = Field(default=20, ge=0, le=100, description="Max overflow connections")
    pool_timeout: int = Field(default=30, ge=1, description="Pool timeout in seconds")
    echo: bool = Field(default=False, description="Echo SQL queries (for debugging)")


class RedisSettings(BaseSettings):
    """Redis cache configuration."""

    model_config = SettingsConfigDict(env_prefix="REDIS_", env_file=".env", extra="ignore")

    url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")
    max_connections: int = Field(default=10, ge=1, description="Max Redis connections")
    decode_responses: bool = Field(default=True, description="Decode responses as strings")


class QdrantSettings(BaseSettings):
    """Qdrant vector database configuration."""

    model_config = SettingsConfigDict(env_prefix="QDRANT_", env_file=".env", extra="ignore")

    url: str = Field(default="http://localhost:6333", description="Qdrant server URL")
    collection: str = Field(default="spam_embeddings", description="Collection name")
    api_key: SecretStr | None = Field(default=None, description="Qdrant API key")


class ClaudeSettings(BaseSettings):
    """Anthropic Claude API configuration."""

    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    anthropic_api_key: SecretStr = Field(..., description="Anthropic API key")
    claude_model: str = Field(default="claude-sonnet-4-20250514", description="Claude model to use")
    max_tokens: int = Field(default=1024, ge=1, description="Max tokens for response")
    temperature: float = Field(default=0.0, ge=0.0, le=1.0, description="Temperature")
    timeout: int = Field(default=30, ge=1, description="API timeout in seconds")


class CohereSettings(BaseSettings):
    """Cohere embeddings configuration."""

    model_config = SettingsConfigDict(env_prefix="COHERE_", env_file=".env", extra="ignore")

    api_key: SecretStr = Field(..., description="Cohere API key")
    model: str = Field(default="embed-multilingual-v3.0", description="Embedding model")
    input_type: str = Field(default="search_document", description="Input type for embeddings")


class MiniAppSettings(BaseSettings):
    """Telegram Mini App configuration."""

    model_config = SettingsConfigDict(env_prefix="MINI_APP_", env_file=".env", extra="ignore")

    url: str = Field(default="", description="Mini App URL")


class JWTSettings(BaseSettings):
    """JWT authentication settings for Mini App."""

    model_config = SettingsConfigDict(env_prefix="JWT_", env_file=".env", extra="ignore")

    secret: SecretStr = Field(..., description="JWT signing secret")
    algorithm: str = Field(default="HS256", description="JWT algorithm")
    expire_minutes: int = Field(default=60, ge=1, description="Token expiration in minutes")


class Settings(BaseSettings):
    """
    Main application settings.

    Combines all subsettings and provides application-wide configuration.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    environment: Environment = Field(default=Environment.DEVELOPMENT)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # Sub-configurations
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    webhook: WebhookSettings = Field(default_factory=WebhookSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    claude: ClaudeSettings = Field(default_factory=ClaudeSettings)
    cohere: CohereSettings = Field(default_factory=CohereSettings)
    mini_app: MiniAppSettings = Field(default_factory=MiniAppSettings)
    jwt: JWTSettings = Field(default_factory=JWTSettings)

    # Default group settings
    default_group_type: GroupType = Field(default=GroupType.GENERAL)
    default_sensitivity: int = Field(default=5, ge=1, le=10)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v.upper()


# Note: THRESHOLDS is imported from core/constants.py (canonical source)
# See core/constants.py for the full threshold configuration by group type


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once.

    Returns:
        Settings instance with all configuration.
    """
    return Settings()


def get_thresholds(group_type: GroupType) -> tuple[int, int, int, int]:
    """
    Get risk score thresholds for a group type.

    Args:
        group_type: The type of group.

    Returns:
        Tuple of (WATCH, LIMIT, REVIEW, BLOCK) thresholds.
    """
    return THRESHOLDS.get(group_type, THRESHOLDS[GroupType.GENERAL])
