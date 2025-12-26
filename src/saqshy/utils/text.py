"""
SAQSHY Text Processing Utilities

Text manipulation and normalization functions.
"""

import re
import unicodedata
from re import Pattern

# Compiled regex patterns for efficiency
WHITESPACE_PATTERN: Pattern[str] = re.compile(r"\s+")
ZERO_WIDTH_PATTERN: Pattern[str] = re.compile(r"[\u200b\u200c\u200d\ufeff\u2060]")
FORMATTING_PATTERN: Pattern[str] = re.compile(r"[\*_~`\[\]()>]")


def normalize_text(text: str) -> str:
    """
    Normalize text for comparison and analysis.

    Operations:
    - Removes zero-width characters
    - Normalizes whitespace
    - Applies Unicode NFC normalization
    - Strips leading/trailing whitespace

    Args:
        text: Input text to normalize.

    Returns:
        Normalized text.
    """
    if not text:
        return ""

    # Remove zero-width characters (often used to bypass filters)
    text = ZERO_WIDTH_PATTERN.sub("", text)

    # Normalize Unicode (NFC form)
    text = unicodedata.normalize("NFC", text)

    # Normalize whitespace
    text = WHITESPACE_PATTERN.sub(" ", text)

    # Strip leading/trailing
    text = text.strip()

    return text


def truncate_text(
    text: str,
    max_length: int = 100,
    suffix: str = "...",
) -> str:
    """
    Truncate text to maximum length with suffix.

    Args:
        text: Text to truncate.
        max_length: Maximum length including suffix.
        suffix: Suffix to add if truncated.

    Returns:
        Truncated text.
    """
    if not text:
        return ""

    if len(text) <= max_length:
        return text

    # Calculate truncation point
    truncate_at = max_length - len(suffix)
    if truncate_at <= 0:
        return suffix[:max_length]

    return text[:truncate_at] + suffix


def strip_formatting(text: str) -> str:
    """
    Remove Markdown/HTML formatting from text.

    Removes:
    - Markdown bold/italic (*_~`)
    - Markdown links [text](url)
    - HTML tags

    Args:
        text: Text with formatting.

    Returns:
        Plain text without formatting.
    """
    if not text:
        return ""

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Remove Markdown links but keep text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Remove Markdown formatting characters
    text = FORMATTING_PATTERN.sub("", text)

    return text


def extract_text_features(text: str) -> dict[str, float | int | bool]:
    """
    Extract statistical features from text.

    Args:
        text: Input text.

    Returns:
        Dict with text features.
    """
    if not text:
        return {
            "length": 0,
            "word_count": 0,
            "avg_word_length": 0.0,
            "caps_ratio": 0.0,
            "digit_ratio": 0.0,
            "special_ratio": 0.0,
            "has_url": False,
        }

    words = text.split()
    letters = [c for c in text if c.isalpha()]
    digits = [c for c in text if c.isdigit()]
    alphanumeric = letters + digits

    return {
        "length": len(text),
        "word_count": len(words),
        "avg_word_length": (sum(len(w) for w in words) / len(words) if words else 0.0),
        "caps_ratio": (sum(1 for c in letters if c.isupper()) / len(letters) if letters else 0.0),
        "digit_ratio": (len(digits) / len(alphanumeric) if alphanumeric else 0.0),
        "special_ratio": (
            sum(1 for c in text if not c.isalnum() and not c.isspace()) / len(text) if text else 0.0
        ),
        "has_url": bool(re.search(r"https?://|www\.|\.com|\.ru|\.org", text, re.IGNORECASE)),
    }


def detect_language_simple(text: str) -> str:
    """
    Simple language detection based on character sets.

    Args:
        text: Input text.

    Returns:
        Language code: "ru", "en", "mixed", or "unknown".
    """
    if not text:
        return "unknown"

    cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())

    total = cyrillic + latin
    if total == 0:
        return "unknown"

    if cyrillic / total > 0.7:
        return "ru"
    elif latin / total > 0.7:
        return "en"
    elif cyrillic > 0 and latin > 0:
        return "mixed"

    return "unknown"


def hash_text(text: str) -> str:
    """
    Generate SHA-256 hash of text for deduplication.

    Args:
        text: Text to hash.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    import hashlib

    normalized = normalize_text(text.lower())
    return hashlib.sha256(normalized.encode()).hexdigest()
