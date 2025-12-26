"""
SAQSHY Config Middleware

Injects configuration values into handler data for access in handlers.
This ensures config values like mini_app_url are available to all handlers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class ConfigMiddleware(BaseMiddleware):
    """
    Configuration injection middleware.

    Injects configuration values into handler data dict so they're
    accessible as handler parameters.

    Example:
        >>> dp.message.middleware(ConfigMiddleware(mini_app_url="https://..."))
        >>> # In handler:
        >>> async def handler(message: Message, mini_app_url: str = ""):
        >>>     # mini_app_url is now available
    """

    def __init__(self, **config: Any) -> None:
        """
        Initialize with configuration values.

        Args:
            **config: Key-value pairs to inject into handler data.
        """
        self.config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Inject config values and process event.

        Args:
            handler: Next handler in chain.
            event: Incoming Telegram event.
            data: Handler context data.

        Returns:
            Handler result.
        """
        # Inject all config values into handler data
        for key, value in self.config.items():
            data[key] = value

        return await handler(event, data)
