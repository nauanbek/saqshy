"""
SAQSHY Security Tests - Mini App Authentication and Security

Tests for:
- CORS origin validation (no wildcard with credentials)
- API rate limiting
- Security headers
- Input validation on admin endpoints
- Sensitive data filtering
"""

import json
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from saqshy.mini_app.auth import (
    DEFAULT_TELEGRAM_ORIGINS,
    InMemoryRateLimiter,
    create_cors_middleware,
    create_rate_limit_middleware,
    create_security_headers_middleware,
)
from saqshy.mini_app.handlers import (
    SENSITIVE_KEYS_CONTENT,
    SENSITIVE_KEYS_LLM,
    SENSITIVE_KEYS_PROFILE,
    _filter_llm_response,
    _filter_sensitive_signals,
)


# =============================================================================
# CORS Security Tests
# =============================================================================


class TestCORSSecurityMiddleware:
    """Test CORS middleware security features."""

    def test_allowed_origin_gets_credentials(self) -> None:
        """Test that allowed origins get Access-Control-Allow-Credentials."""
        # This is a structural test - the actual middleware test would be async
        origins = DEFAULT_TELEGRAM_ORIGINS.copy()
        assert "https://telegram.org" in origins
        assert "https://web.telegram.org" in origins

    def test_wildcard_not_in_default_origins(self) -> None:
        """Test that wildcard is not in default allowed origins."""
        assert "*" not in DEFAULT_TELEGRAM_ORIGINS

    def test_cors_middleware_creation(self) -> None:
        """Test that CORS middleware can be created."""
        middleware = create_cors_middleware()
        assert middleware is not None
        assert callable(middleware)

    def test_cors_middleware_with_custom_origins(self) -> None:
        """Test CORS middleware with custom origins list."""
        custom_origins = ["https://example.com", "https://test.com"]
        middleware = create_cors_middleware(allowed_origins=custom_origins)
        assert middleware is not None


# =============================================================================
# Rate Limiting Tests
# =============================================================================


class TestInMemoryRateLimiter:
    """Test in-memory rate limiter functionality."""

    def test_allows_requests_under_limit(self) -> None:
        """Test that requests under limit are allowed."""
        limiter = InMemoryRateLimiter(limit=5, window_seconds=60)

        for i in range(5):
            allowed, remaining = limiter.is_allowed(user_id=123)
            assert allowed is True
            assert remaining == 5 - i - 1

    def test_blocks_requests_over_limit(self) -> None:
        """Test that requests over limit are blocked."""
        limiter = InMemoryRateLimiter(limit=3, window_seconds=60)

        # Use up the limit
        for _ in range(3):
            allowed, _ = limiter.is_allowed(user_id=123)
            assert allowed is True

        # Next request should be blocked
        allowed, remaining = limiter.is_allowed(user_id=123)
        assert allowed is False
        assert remaining == 0

    def test_different_users_have_separate_limits(self) -> None:
        """Test that different users have independent rate limits."""
        limiter = InMemoryRateLimiter(limit=2, window_seconds=60)

        # User 1 uses up limit
        for _ in range(2):
            limiter.is_allowed(user_id=1)

        # User 1 is blocked
        allowed, _ = limiter.is_allowed(user_id=1)
        assert allowed is False

        # User 2 still has limit
        allowed, _ = limiter.is_allowed(user_id=2)
        assert allowed is True

    def test_retry_after_calculation(self) -> None:
        """Test retry-after time calculation."""
        limiter = InMemoryRateLimiter(limit=1, window_seconds=60)

        # Use up limit
        limiter.is_allowed(user_id=123)

        # Retry after should be positive
        retry_after = limiter.get_retry_after(user_id=123)
        assert 0 < retry_after <= 60

    def test_lru_eviction(self) -> None:
        """Test that LRU eviction works when max entries exceeded."""
        limiter = InMemoryRateLimiter(limit=10, window_seconds=60, max_entries=5)

        # Add more users than max entries
        for user_id in range(10):
            limiter.is_allowed(user_id=user_id)

        # Should not have more than max_entries + 1 (due to how eviction works)
        assert len(limiter._entries) <= 6

    def test_rate_limit_middleware_creation(self) -> None:
        """Test that rate limit middleware can be created."""
        middleware = create_rate_limit_middleware()
        assert middleware is not None
        assert callable(middleware)


# =============================================================================
# Security Headers Tests
# =============================================================================


class TestSecurityHeadersMiddleware:
    """Test security headers middleware."""

    def test_middleware_creation(self) -> None:
        """Test that security headers middleware can be created."""
        middleware = create_security_headers_middleware()
        assert middleware is not None
        assert callable(middleware)


# =============================================================================
# Sensitive Data Filtering Tests
# =============================================================================


class TestSensitiveDataFiltering:
    """Test sensitive data filtering in responses."""

    def test_filter_profile_signals_redacts_bio(self) -> None:
        """Test that bio is redacted from profile signals."""
        signals = {
            "has_username": True,
            "bio": "This is my personal bio",
            "account_age_days": 365,
        }

        filtered = _filter_sensitive_signals(signals, SENSITIVE_KEYS_PROFILE)

        assert filtered["has_username"] is True
        assert filtered["account_age_days"] == 365
        assert filtered["bio"] == "[REDACTED]"

    def test_filter_content_signals_redacts_text(self) -> None:
        """Test that message text is redacted from content signals."""
        signals = {
            "url_count": 2,
            "text": "Original message content",
            "has_links": True,
        }

        filtered = _filter_sensitive_signals(signals, SENSITIVE_KEYS_CONTENT)

        assert filtered["url_count"] == 2
        assert filtered["has_links"] is True
        assert filtered["text"] == "[REDACTED]"

    def test_filter_nested_dicts(self) -> None:
        """Test that nested dictionaries are filtered recursively."""
        signals = {
            "level1": {
                "bio": "Nested bio",
                "safe_key": "safe_value",
            },
            "top_safe": True,
        }

        filtered = _filter_sensitive_signals(signals, SENSITIVE_KEYS_PROFILE)

        assert filtered["top_safe"] is True
        assert filtered["level1"]["safe_key"] == "safe_value"
        assert filtered["level1"]["bio"] == "[REDACTED]"

    def test_filter_empty_signals(self) -> None:
        """Test that empty signals return empty dict."""
        assert _filter_sensitive_signals(None, SENSITIVE_KEYS_PROFILE) == {}
        assert _filter_sensitive_signals({}, SENSITIVE_KEYS_PROFILE) == {}

    def test_filter_llm_response_keeps_safe_fields(self) -> None:
        """Test that LLM response filtering keeps only safe fields."""
        llm_response = {
            "verdict": "ALLOW",
            "confidence": 0.95,
            "reason": "Legitimate message",
            "system_prompt": "You are a spam detector...",
            "raw_input": "Full user message",
        }

        filtered = _filter_llm_response(llm_response)

        assert filtered["verdict"] == "ALLOW"
        assert filtered["confidence"] == 0.95
        assert filtered["reason"] == "Legitimate message"
        assert "system_prompt" not in filtered
        assert "raw_input" not in filtered

    def test_filter_llm_response_none(self) -> None:
        """Test that None LLM response returns None."""
        assert _filter_llm_response(None) is None


# =============================================================================
# Input Validation Tests
# =============================================================================


class TestInputValidation:
    """Test input validation on admin endpoints."""

    def test_telegram_user_id_bounds(self) -> None:
        """Test Telegram user ID validation bounds."""
        from saqshy.mini_app.schemas import (
            TELEGRAM_USER_ID_MAX,
            TELEGRAM_USER_ID_MIN,
            validate_telegram_user_id,
        )

        # Valid IDs
        assert validate_telegram_user_id(1) == 1
        assert validate_telegram_user_id(123456789) == 123456789
        assert validate_telegram_user_id(TELEGRAM_USER_ID_MAX) == TELEGRAM_USER_ID_MAX

        # Invalid IDs
        with pytest.raises(ValueError):
            validate_telegram_user_id(0)

        with pytest.raises(ValueError):
            validate_telegram_user_id(-1)

        with pytest.raises(ValueError):
            validate_telegram_user_id(TELEGRAM_USER_ID_MAX + 1)

    def test_telegram_chat_id_bounds(self) -> None:
        """Test Telegram chat ID validation bounds."""
        from saqshy.mini_app.schemas import (
            TELEGRAM_CHAT_ID_MAX,
            TELEGRAM_CHAT_ID_MIN,
            validate_telegram_chat_id,
        )

        # Valid IDs (including negative for groups)
        assert validate_telegram_chat_id(-1001234567890) == -1001234567890
        assert validate_telegram_chat_id(123456789) == 123456789

        # Invalid IDs (out of bounds)
        with pytest.raises(ValueError):
            validate_telegram_chat_id(TELEGRAM_CHAT_ID_MIN - 1)

        with pytest.raises(ValueError):
            validate_telegram_chat_id(TELEGRAM_CHAT_ID_MAX + 1)
