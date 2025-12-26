"""
SAQSHY Security Tests - Webhook and Authentication

Tests for:
- Webhook secret verification
- Mini App init data validation
- HMAC signature verification
- Timing attack prevention
"""

import hashlib
import hmac
import json
import time
import urllib.parse

import pytest

from saqshy.bot.bot import verify_webhook_secret
from saqshy.core.security import (
    constant_time_compare,
    generate_nonce,
    generate_token,
    sign_request,
    verify_request_signature,
)

# =============================================================================
# Webhook Secret Verification Tests
# =============================================================================


class TestWebhookSecretVerification:
    """Test Telegram webhook secret verification."""

    def test_valid_secret_matches(self) -> None:
        """Test that valid secrets pass verification."""
        secret = "my-webhook-secret-token"
        assert verify_webhook_secret(secret, secret) is True

    def test_invalid_secret_rejected(self) -> None:
        """Test that invalid secrets are rejected."""
        assert verify_webhook_secret("wrong", "expected") is False

    def test_none_secret_rejected(self) -> None:
        """Test that None secret is rejected when expected is set."""
        assert verify_webhook_secret(None, "expected") is False

    def test_empty_received_rejected(self) -> None:
        """Test that empty received secret is rejected."""
        assert verify_webhook_secret("", "expected") is False

    def test_empty_expected_allows_all(self) -> None:
        """Test that empty expected secret allows any request (not recommended)."""
        # This is the current behavior - document it
        assert verify_webhook_secret("anything", "") is True
        assert verify_webhook_secret(None, "") is True

    def test_case_sensitive(self) -> None:
        """Test that secret comparison is case-sensitive."""
        assert verify_webhook_secret("Secret", "secret") is False
        assert verify_webhook_secret("SECRET", "secret") is False

    def test_timing_attack_resistance(self) -> None:
        """
        Test that comparison uses constant-time algorithm.

        This is a sanity check - the actual timing attack prevention
        is provided by hmac.compare_digest.
        """
        # These should all take approximately the same time
        # regardless of where the mismatch occurs
        secret = "a" * 64

        # Mismatch at beginning
        result1 = verify_webhook_secret("b" + "a" * 63, secret)

        # Mismatch at end
        result2 = verify_webhook_secret("a" * 63 + "b", secret)

        # Exact match
        result3 = verify_webhook_secret(secret, secret)

        assert result1 is False
        assert result2 is False
        assert result3 is True


# =============================================================================
# Mini App Init Data Validation Tests
# =============================================================================


class TestMiniAppInitDataValidation:
    """Test Telegram Mini App init data validation."""

    @pytest.fixture
    def bot_token(self) -> str:
        """Sample bot token for testing."""
        return "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"

    def _create_init_data(
        self,
        bot_token: str,
        user_id: int = 123456789,
        auth_date: int | None = None,
        tamper_hash: bool = False,
        tamper_auth_date: bool = False,
    ) -> str:
        """
        Create valid init data for testing.

        Args:
            bot_token: Bot token for signing.
            user_id: User ID to include.
            auth_date: Auth date timestamp (defaults to now).
            tamper_hash: If True, use invalid hash.
            tamper_auth_date: If True, make auth_date very old.
        """
        if auth_date is None:
            auth_date = int(time.time())

        if tamper_auth_date:
            auth_date = int(time.time()) - 86400 * 2  # 2 days ago

        user_data = {
            "id": user_id,
            "first_name": "Test",
            "last_name": "User",
            "username": "testuser",
            "language_code": "en",
        }

        params = {
            "auth_date": str(auth_date),
            "user": json.dumps(user_data),
            "query_id": "AAHdF6IQAAAAAA",
        }

        # Build data-check-string
        check_params = []
        for key in sorted(params.keys()):
            check_params.append(f"{key}={params[key]}")
        data_check_string = "\n".join(check_params)

        # Calculate hash
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256,
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        if tamper_hash:
            calculated_hash = "invalid" + calculated_hash[7:]

        params["hash"] = calculated_hash

        # Build query string
        return urllib.parse.urlencode(params)

    def test_valid_init_data(self, bot_token: str) -> None:
        """Test that valid init data is accepted."""
        from saqshy.mini_app.auth import validate_init_data

        init_data = self._create_init_data(bot_token)
        result = validate_init_data(init_data, bot_token)

        assert result is not None
        assert result.user.id == 123456789
        assert result.user.username == "testuser"

    def test_tampered_hash_rejected(self, bot_token: str) -> None:
        """Test that tampered hash is rejected."""
        from saqshy.mini_app.auth import validate_init_data

        init_data = self._create_init_data(bot_token, tamper_hash=True)
        result = validate_init_data(init_data, bot_token)

        assert result is None

    def test_expired_auth_date_rejected(self, bot_token: str) -> None:
        """Test that expired auth_date is rejected."""
        from saqshy.mini_app.auth import validate_init_data

        init_data = self._create_init_data(bot_token, tamper_auth_date=True)
        result = validate_init_data(init_data, bot_token, max_age_seconds=3600)

        assert result is None

    def test_missing_hash_rejected(self, bot_token: str) -> None:
        """Test that missing hash is rejected."""
        from saqshy.mini_app.auth import validate_init_data

        # Create init data without hash
        params = {
            "auth_date": str(int(time.time())),
            "user": json.dumps({"id": 123, "first_name": "Test"}),
        }
        init_data = urllib.parse.urlencode(params)

        result = validate_init_data(init_data, bot_token)
        assert result is None

    def test_missing_user_rejected(self, bot_token: str) -> None:
        """Test that missing user data is rejected."""
        from saqshy.mini_app.auth import validate_init_data

        # Create init data without user
        auth_date = str(int(time.time()))
        params = {
            "auth_date": auth_date,
        }

        # Calculate hash without user
        data_check_string = f"auth_date={auth_date}"
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256,
        ).digest()
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        params["hash"] = calculated_hash
        init_data = urllib.parse.urlencode(params)

        result = validate_init_data(init_data, bot_token)
        assert result is None

    def test_empty_init_data_rejected(self, bot_token: str) -> None:
        """Test that empty init data is rejected."""
        from saqshy.mini_app.auth import validate_init_data

        assert validate_init_data("", bot_token) is None
        assert validate_init_data(None, bot_token) is None  # type: ignore

    def test_malformed_json_user_rejected(self, bot_token: str) -> None:
        """Test that malformed JSON in user field is rejected."""
        from saqshy.mini_app.auth import validate_init_data

        auth_date = str(int(time.time()))
        params = {
            "auth_date": auth_date,
            "user": "not valid json{",
        }

        # Calculate hash
        check_params = [f"auth_date={auth_date}", f"user={params['user']}"]
        data_check_string = "\n".join(sorted(check_params))
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256,
        ).digest()
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        params["hash"] = calculated_hash
        init_data = urllib.parse.urlencode(params)

        result = validate_init_data(init_data, bot_token)
        assert result is None

    def test_wrong_bot_token_rejected(self, bot_token: str) -> None:
        """Test that init data signed with different token is rejected."""
        from saqshy.mini_app.auth import validate_init_data

        # Create init data with one token
        init_data = self._create_init_data(bot_token)

        # Validate with different token
        wrong_token = "999999999:WrongTokenABCDEF"
        result = validate_init_data(init_data, wrong_token)

        assert result is None


# =============================================================================
# Request Signing Tests
# =============================================================================


class TestRequestSigning:
    """Test request signing and verification."""

    def test_sign_and_verify(self) -> None:
        """Test that signed requests verify correctly."""
        payload = '{"action": "test"}'
        secret = "signing-secret"
        timestamp = int(time.time())

        signature = sign_request(payload, secret, timestamp)
        is_valid, error = verify_request_signature(
            payload, secret, timestamp, signature, current_time=timestamp
        )

        assert is_valid is True
        assert error == ""

    def test_tampered_payload_rejected(self) -> None:
        """Test that tampered payload is rejected."""
        payload = '{"action": "test"}'
        secret = "signing-secret"
        timestamp = int(time.time())

        signature = sign_request(payload, secret, timestamp)

        # Tamper with payload
        tampered = '{"action": "hacked"}'
        is_valid, error = verify_request_signature(
            tampered, secret, timestamp, signature, current_time=timestamp
        )

        assert is_valid is False
        assert "invalid" in error.lower()

    def test_expired_timestamp_rejected(self) -> None:
        """Test that expired timestamp is rejected."""
        payload = '{"action": "test"}'
        secret = "signing-secret"
        old_timestamp = int(time.time()) - 600  # 10 minutes ago

        signature = sign_request(payload, secret, old_timestamp)

        is_valid, error = verify_request_signature(
            payload, secret, old_timestamp, signature, max_age_seconds=300
        )

        assert is_valid is False
        assert "old" in error.lower()

    def test_future_timestamp_rejected(self) -> None:
        """Test that future timestamp is rejected."""
        payload = '{"action": "test"}'
        secret = "signing-secret"
        future_timestamp = int(time.time()) + 3600  # 1 hour in future

        signature = sign_request(payload, secret, future_timestamp)

        is_valid, error = verify_request_signature(payload, secret, future_timestamp, signature)

        assert is_valid is False
        assert "future" in error.lower()

    def test_wrong_secret_rejected(self) -> None:
        """Test that wrong secret is rejected."""
        payload = '{"action": "test"}'
        timestamp = int(time.time())

        signature = sign_request(payload, "correct-secret", timestamp)

        is_valid, error = verify_request_signature(
            payload, "wrong-secret", timestamp, signature, current_time=timestamp
        )

        assert is_valid is False


# =============================================================================
# Token Generation Tests
# =============================================================================


class TestTokenGeneration:
    """Test cryptographic token generation."""

    def test_nonce_uniqueness(self) -> None:
        """Test that generated nonces are unique."""
        nonces = [generate_nonce() for _ in range(100)]
        assert len(set(nonces)) == 100

    def test_nonce_length(self) -> None:
        """Test that nonces have correct length."""
        nonce = generate_nonce(16)
        assert len(nonce) == 32  # 16 bytes = 32 hex chars

        nonce = generate_nonce(32)
        assert len(nonce) == 64  # 32 bytes = 64 hex chars

    def test_token_uniqueness(self) -> None:
        """Test that generated tokens are unique."""
        tokens = [generate_token() for _ in range(100)]
        assert len(set(tokens)) == 100

    def test_token_url_safe(self) -> None:
        """Test that tokens are URL-safe."""
        for _ in range(10):
            token = generate_token()
            # Should not need URL encoding (base64 URL-safe)
            assert urllib.parse.quote(token, safe="") == urllib.parse.quote(token, safe="-_")


# =============================================================================
# Constant-Time Comparison Tests
# =============================================================================


class TestConstantTimeComparison:
    """Test constant-time string comparison."""

    def test_equal_strings(self) -> None:
        """Test that equal strings compare as equal."""
        assert constant_time_compare("secret", "secret") is True
        assert constant_time_compare(b"secret", b"secret") is True

    def test_unequal_strings(self) -> None:
        """Test that unequal strings compare as unequal."""
        assert constant_time_compare("secret", "different") is False
        assert constant_time_compare("secret", "secre") is False
        assert constant_time_compare("secret", "secrets") is False

    def test_mixed_types(self) -> None:
        """Test comparison of mixed string/bytes types."""
        assert constant_time_compare("secret", b"secret") is True
        assert constant_time_compare(b"secret", "secret") is True

    def test_empty_strings(self) -> None:
        """Test comparison of empty strings."""
        assert constant_time_compare("", "") is True
        assert constant_time_compare("", "x") is False

    def test_unicode_strings(self) -> None:
        """Test comparison of unicode strings."""
        assert constant_time_compare("secret", "secret") is True
        # Test with actual different unicode characters (Latin vs Cyrillic 'e')
        assert constant_time_compare("secret", "sеcret") is False  # Second 'e' is Cyrillic
