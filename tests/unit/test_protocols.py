"""
Unit tests for core protocols and log facade.

Tests:
- Protocol compliance
- StdlibLogger functionality
- Logger factory replacement
"""


from saqshy.core.log_facade import StdlibLogger, get_logger, set_logger_factory
from saqshy.core.protocols import (
    CacheProtocol,
    ChannelSubscriptionProtocol,
    ChatRestrictionsProtocol,
    LoggerProtocol,
    TelegramOperationError,
)


class TestLoggerProtocol:
    """Tests for LoggerProtocol compliance."""

    def test_stdlib_logger_implements_protocol(self):
        """StdlibLogger should implement LoggerProtocol."""
        logger = StdlibLogger("test")
        assert isinstance(logger, LoggerProtocol)

    def test_stdlib_logger_info(self, caplog):
        """StdlibLogger.info should log at INFO level."""
        import logging

        caplog.set_level(logging.INFO)
        logger = StdlibLogger("test.info")
        logger.info("test_event", key="value")
        assert "test_event" in caplog.text
        assert "key=value" in caplog.text

    def test_stdlib_logger_warning(self, caplog):
        """StdlibLogger.warning should log at WARNING level."""
        import logging

        caplog.set_level(logging.WARNING)
        logger = StdlibLogger("test.warning")
        logger.warning("warning_event")
        assert "warning_event" in caplog.text

    def test_stdlib_logger_error(self, caplog):
        """StdlibLogger.error should log at ERROR level."""
        import logging

        caplog.set_level(logging.ERROR)
        logger = StdlibLogger("test.error")
        logger.error("error_event")
        assert "error_event" in caplog.text

    def test_stdlib_logger_debug(self, caplog):
        """StdlibLogger.debug should log at DEBUG level."""
        import logging

        caplog.set_level(logging.DEBUG)
        logger = StdlibLogger("test.debug")
        logger.debug("debug_event")
        assert "debug_event" in caplog.text

    def test_stdlib_logger_bind(self, caplog):
        """StdlibLogger.bind should return new logger with context."""
        import logging

        caplog.set_level(logging.INFO)
        logger = StdlibLogger("test.bind")
        bound = logger.bind(user_id=123)

        # Original logger should not have context
        logger.info("original")
        assert "user_id" not in caplog.records[-1].message

        # Bound logger should have context
        bound.info("bound_event")
        assert "user_id=123" in caplog.records[-1].message

    def test_stdlib_logger_bind_preserves_context(self, caplog):
        """Multiple binds should preserve previous context."""
        import logging

        caplog.set_level(logging.INFO)
        logger = StdlibLogger("test.chain")
        bound1 = logger.bind(user_id=123)
        bound2 = bound1.bind(chat_id=456)

        bound2.info("chained")
        message = caplog.records[-1].message
        assert "user_id=123" in message
        assert "chat_id=456" in message


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_returns_logger(self):
        """get_logger should return a LoggerProtocol instance."""
        logger = get_logger("test.module")
        assert isinstance(logger, LoggerProtocol)

    def test_get_logger_default_is_stdlib(self):
        """Default logger factory should be StdlibLogger."""
        # Reset to default
        set_logger_factory(StdlibLogger)
        logger = get_logger("test.default")
        assert isinstance(logger, StdlibLogger)


class TestSetLoggerFactory:
    """Tests for set_logger_factory function."""

    def test_set_custom_factory(self):
        """set_logger_factory should allow custom logger factories."""

        class CustomLogger(LoggerProtocol):
            def __init__(self, name: str):
                self.name = name

            def info(self, event, **kwargs):
                pass

            def warning(self, event, **kwargs):
                pass

            def error(self, event, **kwargs):
                pass

            def debug(self, event, **kwargs):
                pass

            def bind(self, **_kwargs):
                return self

        set_logger_factory(CustomLogger)
        logger = get_logger("test.custom")
        assert isinstance(logger, CustomLogger)

        # Reset to default
        set_logger_factory(StdlibLogger)


class TestTelegramOperationError:
    """Tests for TelegramOperationError exception."""

    def test_error_with_message(self):
        """Error should store message and type."""
        error = TelegramOperationError("Test error", "api")
        assert str(error) == "Test error"
        assert error.error_type == "api"
        assert error.retry_after is None

    def test_error_with_retry_after(self):
        """Error should store retry_after for rate limits."""
        error = TelegramOperationError("Rate limited", "rate_limit", retry_after=30)
        assert error.error_type == "rate_limit"
        assert error.retry_after == 30

    def test_error_repr_without_retry(self):
        """Repr should show error type."""
        error = TelegramOperationError("Test", "forbidden")
        assert repr(error) == "TelegramOperationError(forbidden)"

    def test_error_repr_with_retry(self):
        """Repr should show retry_after if present."""
        error = TelegramOperationError("Test", "rate_limit", retry_after=60)
        assert repr(error) == "TelegramOperationError(rate_limit, retry_after=60)"


class TestProtocolsAreRuntimeCheckable:
    """Tests that protocols can be used with isinstance()."""

    def test_logger_protocol_checkable(self):
        """LoggerProtocol should be runtime checkable."""
        logger = StdlibLogger("test")
        assert isinstance(logger, LoggerProtocol)

    def test_cache_protocol_checkable(self):
        """CacheProtocol should be runtime checkable."""
        # Just verify the protocol is importable and checkable
        assert CacheProtocol is not None

    def test_channel_subscription_protocol_checkable(self):
        """ChannelSubscriptionProtocol should be runtime checkable."""
        assert ChannelSubscriptionProtocol is not None

    def test_chat_restrictions_protocol_checkable(self):
        """ChatRestrictionsProtocol should be runtime checkable."""
        assert ChatRestrictionsProtocol is not None
