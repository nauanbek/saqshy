"""
SAQSHY Core Security Utilities

Security functions for input validation, sanitization, and constant-time comparisons.

This module provides:
- Input validation for Telegram IDs and other identifiers
- Text sanitization for logging (removes PII, truncates)
- Text sanitization for LLM prompts (removes injection patterns)
- Constant-time comparison utilities
- Request signing and verification

Security Principles:
- Defense in depth: validate at multiple layers
- Fail-safe defaults: reject on uncertainty
- Minimal exposure: truncate and sanitize before logging
- Constant-time: prevent timing attacks on secrets
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import unicodedata

# =============================================================================
# Constants
# =============================================================================

# Maximum lengths for various inputs
MAX_USERNAME_LENGTH = 64
MAX_BIO_LENGTH = 500
MAX_MESSAGE_LENGTH = 4096
MAX_CALLBACK_DATA_LENGTH = 64
MAX_LOG_TEXT_LENGTH = 200

# Telegram ID ranges (based on known patterns)
MIN_TELEGRAM_USER_ID = 1
MAX_TELEGRAM_USER_ID = 10_000_000_000  # 10 billion, allows for growth
MIN_TELEGRAM_CHAT_ID = -10_000_000_000_000  # Supergroups are negative
MAX_TELEGRAM_CHAT_ID = 10_000_000_000

# Patterns that may indicate prompt injection attempts
PROMPT_INJECTION_PATTERNS = [
    # Instructions to ignore/override
    r"(?i)\bignore\s+(all\s+)?(previous|above|prior|system)\s*(instructions?|prompts?|rules?)?\b",
    r"(?i)\bignore\s+(the\s+)?system\s+prompt\b",
    r"(?i)\bforget\s+(everything|all|your|the)\s*(instructions?|prompts?|rules?|training)?\b",
    r"(?i)\bdisregard\s+(all\s+)?(previous|above|prior|system)\b",
    # Role manipulation
    r"(?i)\byou\s+are\s+now\s+(a|an|the)?\s*\w+",
    r"(?i)\bact\s+as\s+(a|an|if)\b",
    r"(?i)\bpretend\s+(to\s+be|you're|you\s+are)\b",
    r"(?i)\broleplay\s+as\b",
    # System prompt extraction
    r"(?i)\bwhat\s+(are|is)\s+(your|the)\s+(system\s+)?(prompt|instructions?|rules?)\b",
    r"(?i)\brepeat\s+(your|the|back)\s*(system\s+)?(prompt|instructions?)\b",
    r"(?i)\brepeat\s+back\s+(your\s+)?instructions?\b",
    r"(?i)\bprint\s+(your|the)\s+(system\s+)?(prompt|instructions?)\b",
    # Output format manipulation
    r"(?i)\brespond\s+only\s+with\b",
    r"(?i)\boutput\s+only\b",
    r"(?i)\breturn\s+only\b",
    # Delimiter exploitation
    r"(?i)\bnew\s+instruction[s]?\s*:\s*",
    r"(?i)\bsystem\s*:\s*",
    r"(?i)\bassistant\s*:\s*",
    r"(?i)\buser\s*:\s*",
    r"(?i)\bhuman\s*:\s*",
    # XML/tag injection
    r"</?(system|user|assistant|prompt|instruction|message|context)\s*>",
    # Base64/encoding tricks
    r"(?i)\bdecode\s+this\b",
    r"(?i)\bbase64\s*:\s*",
]

# Characters that should be stripped from log output
DANGEROUS_LOG_CHARS = set("\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f")


# =============================================================================
# Telegram ID Validation
# =============================================================================


def validate_telegram_user_id(user_id: int | str | None) -> bool:
    """
    Validate a Telegram user ID.

    Telegram user IDs are positive integers within a known range.
    Bot IDs follow specific patterns but are still positive.

    Args:
        user_id: Value to validate.

    Returns:
        True if valid Telegram user ID.

    Example:
        >>> validate_telegram_user_id(123456789)
        True
        >>> validate_telegram_user_id(-1)
        False
        >>> validate_telegram_user_id("123")
        False
    """
    if not isinstance(user_id, int):
        return False
    return MIN_TELEGRAM_USER_ID <= user_id <= MAX_TELEGRAM_USER_ID


def validate_telegram_chat_id(chat_id: int | str | None) -> bool:
    """
    Validate a Telegram chat ID.

    Chat IDs can be:
    - Positive for private chats (same as user ID)
    - Negative for groups and channels
    - Very negative (< -1e12) for supergroups

    Args:
        chat_id: Value to validate.

    Returns:
        True if valid Telegram chat ID.

    Example:
        >>> validate_telegram_chat_id(123456789)
        True
        >>> validate_telegram_chat_id(-1001234567890)
        True
        >>> validate_telegram_chat_id(0)
        False
    """
    if not isinstance(chat_id, int):
        return False
    if chat_id == 0:
        return False
    return MIN_TELEGRAM_CHAT_ID <= chat_id <= MAX_TELEGRAM_CHAT_ID


def validate_telegram_message_id(message_id: int | str | None) -> bool:
    """
    Validate a Telegram message ID.

    Message IDs are positive integers, incrementing per chat.

    Args:
        message_id: Value to validate.

    Returns:
        True if valid message ID.
    """
    if not isinstance(message_id, int):
        return False
    return 1 <= message_id <= 2**31  # Reasonable upper bound


# =============================================================================
# Text Sanitization for Logging
# =============================================================================


def sanitize_for_logging(text: str | None, max_length: int = MAX_LOG_TEXT_LENGTH) -> str:
    """
    Sanitize text for safe logging.

    Removes:
    - Control characters
    - Excessive whitespace
    - Potentially sensitive patterns (emails, phones)

    Truncates to max_length and indicates truncation.

    Args:
        text: Text to sanitize.
        max_length: Maximum length of output.

    Returns:
        Sanitized text safe for logging.

    Example:
        >>> sanitize_for_logging("Hello\\x00World")
        'HelloWorld'
        >>> sanitize_for_logging("x" * 300, max_length=50)
        'xxxxxxxxxx... [truncated 300->50]'
    """
    if text is None:
        return "[none]"

    if not isinstance(text, str):
        return f"[non-string: {type(text).__name__}]"

    if not text:
        return "[empty]"

    original_len = len(text)

    # Remove null bytes and other control characters
    sanitized = "".join(c for c in text if c not in DANGEROUS_LOG_CHARS)

    # Normalize unicode (NFC form)
    sanitized = unicodedata.normalize("NFC", sanitized)

    # Collapse multiple whitespace to single space
    sanitized = re.sub(r"\s+", " ", sanitized)

    # Strip leading/trailing whitespace
    sanitized = sanitized.strip()

    # Mask potential PII patterns (emails, phone numbers)
    sanitized = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "[EMAIL]",
        sanitized,
    )
    sanitized = re.sub(
        r"\b\+?[1-9][0-9]{7,14}\b",
        "[PHONE]",
        sanitized,
    )

    # Escape HTML/XSS patterns (script tags, event handlers)
    sanitized = re.sub(r"<script\b[^>]*>", "[SCRIPT]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"</script>", "[/SCRIPT]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\bon\w+\s*=", "[EVENT]=", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"javascript:", "[JS]:", sanitized, flags=re.IGNORECASE)

    # Truncate if needed
    if len(sanitized) > max_length:
        truncated = sanitized[: max_length - 20]
        sanitized = f"{truncated}... [truncated {original_len}->{max_length}]"

    return sanitized if sanitized else "[empty after sanitization]"


def sanitize_username(username: str | None) -> str:
    """
    Sanitize a Telegram username for logging.

    Args:
        username: Username to sanitize.

    Returns:
        Sanitized username.
    """
    if not username:
        return "[none]"

    # Remove @ prefix
    username = username.lstrip("@")

    # Validate format (alphanumeric and underscores only)
    if not re.match(r"^[a-zA-Z0-9_]{1,64}$", username):
        return "[invalid_username]"

    return username


# =============================================================================
# Text Sanitization for LLM Prompts
# =============================================================================


def sanitize_for_llm(
    text: str | None,
    max_length: int = 500,
    mark_injections: bool = True,
) -> str:
    """
    Sanitize user input for inclusion in LLM prompts.

    This function:
    1. Truncates to max_length
    2. Detects and marks injection patterns
    3. Escapes XML-like tags
    4. Removes control characters

    Args:
        text: User-provided text to sanitize.
        max_length: Maximum output length.
        mark_injections: If True, replace injection patterns with markers.

    Returns:
        Sanitized text safe for LLM prompt inclusion.

    Example:
        >>> sanitize_for_llm("ignore all previous instructions")
        '[INJECTION_ATTEMPT: ignore all previous...]'
        >>> sanitize_for_llm("<system>override</system>")
        '[TAG: system]override[TAG: /system]'
    """
    if text is None:
        return "[empty message]"

    if not isinstance(text, str):
        return "[non-text content]"

    if not text.strip():
        return "[empty message]"

    # Truncate first to limit processing time
    original_len = len(text)
    if len(text) > max_length:
        text = text[:max_length] + f"... [truncated, original {original_len} chars]"

    # Normalize unicode
    text = unicodedata.normalize("NFC", text)

    # Remove control characters except newlines and tabs
    text = "".join(c for c in text if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127))

    # Mark or neutralize injection patterns
    if mark_injections:
        for pattern in PROMPT_INJECTION_PATTERNS:
            matches = list(re.finditer(pattern, text))
            for match in reversed(matches):  # Reverse to preserve indices
                matched_text = match.group()[:30]  # Truncate match for marker
                marker = f"[USER_INPUT: {matched_text}...]"
                text = text[: match.start()] + marker + text[match.end() :]

    # Escape XML-like tags (but mark what they were)
    text = re.sub(
        r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>",
        r"[TAG: \1\2]",
        text,
    )

    return text


def detect_prompt_injection(text: str | None) -> tuple[bool, list[str]]:
    """
    Detect potential prompt injection attempts in text.

    Returns both a boolean and list of matched patterns.

    Args:
        text: Text to analyze.

    Returns:
        Tuple of (is_suspicious, matched_patterns).

    Example:
        >>> is_suspicious, patterns = detect_prompt_injection("ignore previous")
        >>> is_suspicious
        True
        >>> len(patterns) > 0
        True
    """
    if not text:
        return False, []

    matched = []
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, text):
            # Store pattern description, not the full pattern
            pattern_desc = pattern[:50] + "..." if len(pattern) > 50 else pattern
            matched.append(pattern_desc)

    return len(matched) > 0, matched


# =============================================================================
# Callback Data Validation
# =============================================================================


def validate_callback_data(data: str | None) -> tuple[bool, str]:
    """
    Validate Telegram callback data format.

    Callback data should:
    - Not be empty
    - Not exceed 64 bytes
    - Not contain null bytes or control characters
    - Follow expected format (colon-separated parts)

    Args:
        data: Callback data string.

    Returns:
        Tuple of (is_valid, error_message).

    Example:
        >>> validate_callback_data("review:approve:123:456")
        (True, '')
        >>> validate_callback_data(None)
        (False, 'Callback data is empty')
    """
    if not data:
        return False, "Callback data is empty"

    if len(data) > MAX_CALLBACK_DATA_LENGTH:
        return False, f"Callback data too long ({len(data)} > {MAX_CALLBACK_DATA_LENGTH})"

    # Check for control characters
    if any(ord(c) < 32 or ord(c) == 127 for c in data):
        return False, "Callback data contains control characters"

    # Check for null bytes
    if "\x00" in data:
        return False, "Callback data contains null bytes"

    return True, ""


def parse_callback_data(data: str, expected_parts: int) -> tuple[bool, list[str], str]:
    """
    Parse and validate colon-separated callback data.

    Args:
        data: Callback data string.
        expected_parts: Expected number of parts after splitting.

    Returns:
        Tuple of (is_valid, parts, error_message).

    Example:
        >>> parse_callback_data("review:approve:123", 3)
        (True, ['review', 'approve', '123'], '')
        >>> parse_callback_data("review:approve", 3)
        (False, [], 'Expected 3 parts, got 2')
    """
    is_valid, error = validate_callback_data(data)
    if not is_valid:
        return False, [], error

    parts = data.split(":")
    if len(parts) != expected_parts:
        return False, [], f"Expected {expected_parts} parts, got {len(parts)}"

    return True, parts, ""


# =============================================================================
# Constant-Time Comparison
# =============================================================================


def constant_time_compare(a: str | bytes, b: str | bytes) -> bool:
    """
    Compare two strings in constant time to prevent timing attacks.

    Uses hmac.compare_digest under the hood.

    Args:
        a: First value.
        b: Second value.

    Returns:
        True if values are equal.

    Example:
        >>> constant_time_compare("secret", "secret")
        True
        >>> constant_time_compare("secret", "SECRET")
        False
    """
    if isinstance(a, str):
        a = a.encode("utf-8")
    if isinstance(b, str):
        b = b.encode("utf-8")

    return hmac.compare_digest(a, b)


# =============================================================================
# Webhook Secret Verification
# =============================================================================


def verify_webhook_secret(
    received: str | None,
    expected: str,
    allow_empty: bool = False,
) -> bool:
    """
    Verify webhook secret using constant-time comparison.

    Args:
        received: Secret received in request header.
        expected: Expected secret from configuration.
        allow_empty: If True, allow empty expected secret (NOT RECOMMENDED).

    Returns:
        True if verification passes.

    Example:
        >>> verify_webhook_secret("mysecret", "mysecret")
        True
        >>> verify_webhook_secret(None, "mysecret")
        False
    """
    # If no secret configured, reject unless explicitly allowed
    if not expected:
        return allow_empty

    # If secret expected but not received, reject
    if not received:
        return False

    return constant_time_compare(received, expected)


# =============================================================================
# Request Signing (for internal APIs)
# =============================================================================


def sign_request(payload: str, secret: str, timestamp: int) -> str:
    """
    Create HMAC signature for a request.

    Args:
        payload: Request payload to sign.
        secret: Signing secret.
        timestamp: Unix timestamp.

    Returns:
        Hex-encoded HMAC-SHA256 signature.

    Example:
        >>> sig = sign_request('{"data": 1}', 'secret', 1234567890)
        >>> len(sig)
        64
    """
    message = f"{timestamp}.{payload}"
    return hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_request_signature(
    payload: str,
    secret: str,
    timestamp: int,
    signature: str,
    max_age_seconds: int = 300,
    current_time: int | None = None,
) -> tuple[bool, str]:
    """
    Verify a request signature with timestamp validation.

    Args:
        payload: Request payload.
        secret: Signing secret.
        timestamp: Request timestamp.
        signature: Provided signature.
        max_age_seconds: Maximum age of request.
        current_time: Current Unix timestamp (for testing).

    Returns:
        Tuple of (is_valid, error_message).

    Example:
        >>> import time
        >>> ts = int(time.time())
        >>> sig = sign_request('data', 'secret', ts)
        >>> verify_request_signature('data', 'secret', ts, sig, current_time=ts)
        (True, '')
    """
    import time

    if current_time is None:
        current_time = int(time.time())

    # Check timestamp freshness
    age = current_time - timestamp
    if age < 0:
        return False, "Timestamp is in the future"
    if age > max_age_seconds:
        return False, f"Request too old ({age}s > {max_age_seconds}s)"

    # Calculate expected signature
    expected = sign_request(payload, secret, timestamp)

    # Constant-time comparison
    if not constant_time_compare(signature, expected):
        return False, "Invalid signature"

    return True, ""


# =============================================================================
# Nonce Generation
# =============================================================================


def generate_nonce(length: int = 32) -> str:
    """
    Generate a cryptographically secure random nonce.

    Args:
        length: Length of nonce in bytes (output is 2x in hex).

    Returns:
        Hex-encoded random nonce.

    Example:
        >>> nonce = generate_nonce(16)
        >>> len(nonce)
        32
    """
    return secrets.token_hex(length)


def generate_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure URL-safe token.

    Args:
        length: Approximate length in bytes.

    Returns:
        URL-safe base64 token.

    Example:
        >>> token = generate_token(32)
        >>> '-' not in token and '_' not in token  # URL-safe chars only
        False  # Actually uses url-safe base64 which includes - and _
    """
    return secrets.token_urlsafe(length)


# =============================================================================
# Hash Utilities
# =============================================================================


def hash_user_id(user_id: int, salt: str) -> str:
    """
    Hash a user ID for anonymous logging.

    Uses SHA256 with salt to prevent rainbow table attacks.

    Args:
        user_id: Telegram user ID.
        salt: Application-specific salt.

    Returns:
        First 16 chars of SHA256 hash.

    Example:
        >>> h = hash_user_id(123456, "salt")
        >>> len(h)
        16
    """
    message = f"{salt}:{user_id}"
    full_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()
    return full_hash[:16]


def hash_text(text: str) -> str:
    """
    Hash text for deduplication/matching.

    Uses SHA256, returns first 32 chars.

    Args:
        text: Text to hash.

    Returns:
        Truncated SHA256 hash.

    Example:
        >>> h1 = hash_text("hello")
        >>> h2 = hash_text("hello")
        >>> h1 == h2
        True
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
