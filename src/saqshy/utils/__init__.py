"""
SAQSHY Utils Module

Utility functions and helpers.

Modules:
- text: Text processing utilities
- url: URL extraction and validation
- telegram: Telegram-specific helpers
"""

from saqshy.utils.telegram import (
    format_user_mention,
    parse_command_args,
)
from saqshy.utils.text import (
    normalize_text,
    strip_formatting,
    truncate_text,
)
from saqshy.utils.url import (
    extract_domains,
    extract_urls,
    is_shortened_url,
)

__all__ = [
    # Text
    "normalize_text",
    "truncate_text",
    "strip_formatting",
    # URL
    "extract_urls",
    "extract_domains",
    "is_shortened_url",
    # Telegram
    "format_user_mention",
    "parse_command_args",
]
