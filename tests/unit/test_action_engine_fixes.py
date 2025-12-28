"""
SAQSHY ActionEngine Fixes Tests

Tests for the race condition fix and retry logic in ActionEngine:
- Atomic admin notification rate limiting (TOCTOU fix)
- Exponential backoff retry on transient Telegram API errors
- Immediate failure on non-retryable errors
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import Chat, Message, User

from saqshy.bot.action_engine import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BASE_DELAY,
    ActionEngine,
)
from saqshy.core.types import (
    GroupType,
    RiskResult,
    Signals,
    ThreatType,
    Verdict,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_bot():
    """Create a mock bot instance."""
    bot = AsyncMock()
    bot.delete_message = AsyncMock(return_value=True)
    bot.restrict_chat_member = AsyncMock(return_value=True)
    bot.ban_chat_member = AsyncMock(return_value=True)
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.get_chat_administrators = AsyncMock(return_value=[])
    return bot


@pytest.fixture
def mock_cache():
    """Create a mock cache service with set_nx support."""
    cache = AsyncMock()
    cache.exists = AsyncMock(return_value=False)
    cache.set = AsyncMock(return_value=True)
    cache.set_nx = AsyncMock(return_value=True)
    cache.set_json = AsyncMock(return_value=True)
    cache.get = AsyncMock(return_value=None)
    return cache


@pytest.fixture
def mock_message():
    """Create a mock Telegram message."""
    user = MagicMock(spec=User)
    user.id = 123456789
    user.username = "testuser"
    user.first_name = "Test"
    user.is_bot = False

    chat = MagicMock(spec=Chat)
    chat.id = -1001234567890
    chat.type = "supergroup"
    chat.title = "Test Group"

    message = MagicMock(spec=Message)
    message.message_id = 12345
    message.from_user = user
    message.chat = chat
    message.text = "Test spam message"
    message.caption = None

    return message


@pytest.fixture
def block_result():
    """Create BLOCK RiskResult."""
    return RiskResult(
        score=95,
        verdict=Verdict.BLOCK,
        threat_type=ThreatType.CRYPTO_SCAM,
        signals=Signals(),
        contributing_factors=["Crypto scam phrases"],
    )


@pytest.fixture
def action_engine(mock_bot, mock_cache):
    """Create ActionEngine with mocks."""
    return ActionEngine(
        bot=mock_bot,
        cache_service=mock_cache,
        group_type=GroupType.GENERAL,
    )


# =============================================================================
# Atomic Admin Notify Rate Limiting Tests
# =============================================================================


class TestAtomicAdminNotifyRateLimiting:
    """Test atomic rate limiting for admin notifications (TOCTOU fix)."""

    @pytest.mark.asyncio
    async def test_acquire_lock_success(self, action_engine, mock_cache):
        """Test successful lock acquisition when not rate limited."""
        mock_cache.set_nx.return_value = True

        result = await action_engine._acquire_admin_notify_lock(-1001234567890)

        assert result is True
        mock_cache.set_nx.assert_called_once()
        # Verify the key format and TTL
        call_args = mock_cache.set_nx.call_args
        assert "admin_notify_lock" in call_args.kwargs.get("key", call_args.args[0])
        assert call_args.kwargs.get("ttl") == action_engine.config.admin_notify_rate_limit

    @pytest.mark.asyncio
    async def test_acquire_lock_rate_limited(self, action_engine, mock_cache):
        """Test lock acquisition fails when rate limited."""
        mock_cache.set_nx.return_value = False

        result = await action_engine._acquire_admin_notify_lock(-1001234567890)

        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_lock_no_cache(self, mock_bot):
        """Test lock acquisition returns True when no cache available."""
        engine = ActionEngine(bot=mock_bot, cache_service=None)

        result = await engine._acquire_admin_notify_lock(-1001234567890)

        assert result is True

    @pytest.mark.asyncio
    async def test_atomic_prevents_concurrent_notifications(
        self, action_engine, mock_cache, block_result, mock_message
    ):
        """Test that atomic lock prevents concurrent notifications."""
        # First call acquires lock
        mock_cache.set_nx.return_value = True
        admin = MagicMock()
        admin.user.id = 111222333
        admin.user.is_bot = False
        action_engine.bot.get_chat_administrators.return_value = [admin]

        result1 = await action_engine.notify_admins(
            chat_id=-1001234567890,
            risk_result=block_result,
            message=mock_message,
        )

        # Second call should be rate limited
        mock_cache.set_nx.return_value = False

        result2 = await action_engine.notify_admins(
            chat_id=-1001234567890,
            risk_result=block_result,
            message=mock_message,
        )

        assert result1.success is True
        assert result2.success is True  # Rate limiting is not an error
        assert result2.details.get("skipped") is True
        assert result2.details.get("reason") == "rate_limited"

    @pytest.mark.asyncio
    async def test_fallback_when_set_nx_not_available(self, mock_bot):
        """Test fallback to exists+set when set_nx is not available."""
        cache = AsyncMock()
        cache.exists = AsyncMock(return_value=False)
        cache.set = AsyncMock(return_value=True)
        # Remove set_nx to simulate old cache without this method
        del cache.set_nx

        engine = ActionEngine(bot=mock_bot, cache_service=cache)

        # This should use the fallback mechanism
        result = await engine._acquire_admin_notify_lock(-1001234567890)

        assert result is True
        cache.exists.assert_called_once()
        cache.set.assert_called_once()


# =============================================================================
# Retry Logic Tests
# =============================================================================


class TestRetryOnTransientError:
    """Test retry behavior on transient Telegram API errors."""

    @pytest.mark.asyncio
    async def test_retry_on_network_error_then_success(self, action_engine, mock_bot):
        """Test retry succeeds after transient network error."""
        # First call fails, second succeeds
        mock_bot.delete_message.side_effect = [
            TelegramNetworkError(method="deleteMessage", message="Connection reset"),
            True,
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await action_engine.delete_message(
                chat_id=-1001234567890,
                message_id=12345,
            )

        assert result.success is True
        assert mock_bot.delete_message.call_count == 2
        mock_sleep.assert_called_once()  # One retry delay

    @pytest.mark.asyncio
    async def test_retry_on_timeout_then_success(self, action_engine, mock_bot):
        """Test retry succeeds after timeout."""
        # First call times out, second succeeds
        mock_bot.delete_message.side_effect = [
            TimeoutError(),
            True,
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await action_engine.delete_message(
                chat_id=-1001234567890,
                message_id=12345,
            )

        assert result.success is True
        assert mock_bot.delete_message.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit_respects_retry_after(self, action_engine, mock_bot):
        """Test retry respects Telegram's retry_after on rate limit."""
        retry_after_seconds = 5
        mock_bot.delete_message.side_effect = [
            TelegramRetryAfter(
                method="deleteMessage",
                message="Flood control",
                retry_after=retry_after_seconds,
            ),
            True,
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await action_engine.delete_message(
                chat_id=-1001234567890,
                message_id=12345,
            )

        assert result.success is True
        # Should sleep for the retry_after duration
        mock_sleep.assert_called_with(retry_after_seconds)

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self, action_engine, mock_bot):
        """Test that retry uses exponential backoff delays."""
        # Fail twice with network error, then succeed
        mock_bot.delete_message.side_effect = [
            TelegramNetworkError(method="deleteMessage", message="Error 1"),
            TelegramNetworkError(method="deleteMessage", message="Error 2"),
            True,
        ]

        delays = []

        async def capture_delay(delay):
            delays.append(delay)
            # Don't actually sleep in tests

        with patch("asyncio.sleep", side_effect=capture_delay):
            result = await action_engine.delete_message(
                chat_id=-1001234567890,
                message_id=12345,
            )

        assert result.success is True
        # Verify exponential backoff: base_delay * 2^attempt
        assert len(delays) == 2
        assert delays[0] == DEFAULT_RETRY_BASE_DELAY * (2**0)  # 1.0
        assert delays[1] == DEFAULT_RETRY_BASE_DELAY * (2**1)  # 2.0


class TestRetryExhausted:
    """Test behavior when all retries are exhausted."""

    @pytest.mark.asyncio
    async def test_delete_message_fails_after_max_retries(self, action_engine, mock_bot):
        """Test delete_message returns failure after max retries exhausted."""
        mock_bot.delete_message.side_effect = TelegramNetworkError(
            method="deleteMessage",
            message="Persistent network error",
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await action_engine.delete_message(
                chat_id=-1001234567890,
                message_id=12345,
            )

        assert result.success is False
        assert mock_bot.delete_message.call_count == DEFAULT_MAX_RETRIES

    @pytest.mark.asyncio
    async def test_ban_user_fails_after_max_retries(self, action_engine, mock_bot):
        """Test ban_user returns failure after max retries exhausted."""
        mock_bot.ban_chat_member.side_effect = TelegramNetworkError(
            method="banChatMember",
            message="Persistent network error",
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await action_engine.ban_user(
                chat_id=-1001234567890,
                user_id=123456789,
            )

        assert result.success is False
        assert mock_bot.ban_chat_member.call_count == DEFAULT_MAX_RETRIES

    @pytest.mark.asyncio
    async def test_restrict_user_fails_after_max_retries(self, action_engine, mock_bot):
        """Test restrict_user returns failure after max retries exhausted."""
        mock_bot.restrict_chat_member.side_effect = TelegramNetworkError(
            method="restrictChatMember",
            message="Persistent network error",
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await action_engine.restrict_user(
                chat_id=-1001234567890,
                user_id=123456789,
            )

        assert result.success is False
        assert mock_bot.restrict_chat_member.call_count == DEFAULT_MAX_RETRIES


class TestNoRetryOnNonRetryableErrors:
    """Test immediate failure on non-retryable errors."""

    @pytest.mark.asyncio
    async def test_no_retry_on_forbidden_error(self, action_engine, mock_bot):
        """Test no retry on TelegramForbiddenError."""
        mock_bot.delete_message.side_effect = TelegramForbiddenError(
            method="deleteMessage",
            message="Forbidden: bot can't delete messages",
        )

        result = await action_engine.delete_message(
            chat_id=-1001234567890,
            message_id=12345,
        )

        assert result.success is False
        assert "permission" in result.error.lower()
        # Should fail immediately without retries
        mock_bot.delete_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_retry_on_bad_request(self, action_engine, mock_bot):
        """Test no retry on TelegramBadRequest."""
        mock_bot.ban_chat_member.side_effect = TelegramBadRequest(
            method="banChatMember",
            message="Bad Request: user is an administrator of the chat",
        )

        result = await action_engine.ban_user(
            chat_id=-1001234567890,
            user_id=123456789,
        )

        assert result.success is False
        assert "administrator" in result.error.lower()
        # Should fail immediately without retries
        mock_bot.ban_chat_member.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_retry_on_not_found(self, action_engine, mock_bot):
        """Test no retry on TelegramNotFound."""
        from aiogram.exceptions import TelegramNotFound

        mock_bot.restrict_chat_member.side_effect = TelegramNotFound(
            method="restrictChatMember",
            message="Not Found: chat not found",
        )

        result = await action_engine.restrict_user(
            chat_id=-1001234567890,
            user_id=123456789,
        )

        assert result.success is False
        assert "not found" in result.error.lower()
        # Should fail immediately without retries
        mock_bot.restrict_chat_member.assert_called_once()


class TestRetryHelperMethod:
    """Test the _telegram_api_with_retry helper method directly."""

    @pytest.mark.asyncio
    async def test_successful_operation_no_retry(self, action_engine):
        """Test successful operation doesn't trigger retries."""
        call_count = 0

        async def success_operation():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await action_engine._telegram_api_with_retry(
            operation=success_operation,
            operation_name="test_op",
        )

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_raises_last_error_after_retries(self, action_engine):
        """Test that the last error is raised after retries exhausted."""
        call_count = 0

        async def failing_operation():
            nonlocal call_count
            call_count += 1
            raise TelegramNetworkError(
                method="test",
                message=f"Error {call_count}",
            )

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(TelegramNetworkError) as exc_info,
        ):
            await action_engine._telegram_api_with_retry(
                operation=failing_operation,
                operation_name="test_op",
            )

        assert call_count == DEFAULT_MAX_RETRIES
        assert f"Error {DEFAULT_MAX_RETRIES}" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_forbidden_error_raises_immediately(self, action_engine):
        """Test TelegramForbiddenError raises immediately without retry."""
        call_count = 0

        async def forbidden_operation():
            nonlocal call_count
            call_count += 1
            raise TelegramForbiddenError(
                method="test",
                message="Forbidden",
            )

        with pytest.raises(TelegramForbiddenError):
            await action_engine._telegram_api_with_retry(
                operation=forbidden_operation,
                operation_name="test_op",
            )

        assert call_count == 1  # No retries

    @pytest.mark.asyncio
    async def test_custom_max_retries(self, action_engine):
        """Test custom max_retries parameter."""
        call_count = 0
        custom_retries = 5

        async def failing_operation():
            nonlocal call_count
            call_count += 1
            raise TelegramNetworkError(method="test", message="Error")

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(TelegramNetworkError),
        ):
            await action_engine._telegram_api_with_retry(
                operation=failing_operation,
                operation_name="test_op",
                max_retries=custom_retries,
            )

        assert call_count == custom_retries

    @pytest.mark.asyncio
    async def test_custom_base_delay(self, action_engine):
        """Test custom base_delay parameter."""
        custom_base_delay = 0.5
        delays = []

        async def capture_delay(delay):
            delays.append(delay)

        async def failing_operation():
            raise TelegramNetworkError(method="test", message="Error")

        with (
            patch("asyncio.sleep", side_effect=capture_delay),
            pytest.raises(TelegramNetworkError),
        ):
            await action_engine._telegram_api_with_retry(
                operation=failing_operation,
                operation_name="test_op",
                max_retries=3,
                base_delay=custom_base_delay,
            )

        # Check first delay uses custom base
        assert delays[0] == custom_base_delay * (2**0)
        assert delays[1] == custom_base_delay * (2**1)


# =============================================================================
# Integration Tests
# =============================================================================


class TestRetryIntegration:
    """Integration tests for retry logic with action methods."""

    @pytest.mark.asyncio
    async def test_delete_then_ban_both_retry(self, action_engine, mock_bot):
        """Test that both delete and ban retry independently."""
        # Delete fails once, succeeds
        mock_bot.delete_message.side_effect = [
            TelegramNetworkError(method="deleteMessage", message="Error"),
            True,
        ]
        # Ban fails once, succeeds
        mock_bot.ban_chat_member.side_effect = [
            TelegramNetworkError(method="banChatMember", message="Error"),
            True,
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            delete_result = await action_engine.delete_message(
                chat_id=-1001234567890,
                message_id=12345,
            )
            ban_result = await action_engine.ban_user(
                chat_id=-1001234567890,
                user_id=123456789,
            )

        assert delete_result.success is True
        assert ban_result.success is True
        assert mock_bot.delete_message.call_count == 2
        assert mock_bot.ban_chat_member.call_count == 2
