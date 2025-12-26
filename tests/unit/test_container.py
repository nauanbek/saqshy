"""
Unit tests for ServiceContainer and DI wiring.

Tests:
- Service registration and retrieval
- Factory lazy initialization
- Global container management
- Logger factory integration
"""

import pytest

from saqshy.core.log_facade import StdlibLogger, get_logger, set_logger_factory
from saqshy.core.protocols import CacheProtocol, LoggerProtocol
from saqshy.services.container import (
    ServiceContainer,
    configure_container,
    get_container,
    reset_container,
)


class TestServiceContainerBasics:
    """Tests for basic ServiceContainer functionality."""

    def test_empty_container(self):
        """Empty container should have None for all protocols."""
        container = ServiceContainer()
        assert container.cache is None
        assert container.logger_factory is None
        assert container.channel_subscription is None
        assert container.chat_restrictions is None

    def test_container_with_services(self):
        """Container should store provided services."""

        class MockCache(CacheProtocol):
            async def get_json(self, _key):
                return None

            async def set_json(self, _key, _value, _ttl):
                return True

            async def get(self, _key):
                return None

            async def set(self, _key, _value, _ttl):
                return True

        cache = MockCache()
        container = ServiceContainer(cache=cache)
        assert container.cache is cache


class TestServiceRegistration:
    """Tests for service registration."""

    def test_register_factory(self):
        """Registered factory should be callable via get()."""
        container = ServiceContainer()

        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return "test_service"

        container.register("test", factory)

        # Factory not called yet
        assert call_count == 0

        # First get calls factory
        result = container.get("test")
        assert result == "test_service"
        assert call_count == 1

        # Second get returns cached instance
        result2 = container.get("test")
        assert result2 == "test_service"
        assert call_count == 1  # Not called again

    def test_register_instance(self):
        """Registered instance should be returned directly."""
        container = ServiceContainer()

        instance = {"key": "value"}
        container.register_instance("config", instance)

        result = container.get("config")
        assert result is instance

    def test_get_unregistered_raises(self):
        """Getting unregistered service should raise KeyError."""
        container = ServiceContainer()

        with pytest.raises(KeyError, match="Service 'unknown' not registered"):
            container.get("unknown")

    def test_has_registered(self):
        """has() should return True for registered services."""
        container = ServiceContainer()
        container.register("test", lambda: "value")

        assert container.has("test") is True
        assert container.has("unknown") is False

    def test_get_optional_returns_none(self):
        """get_optional() should return None for unregistered services."""
        container = ServiceContainer()

        result = container.get_optional("unknown")
        assert result is None

    def test_get_optional_returns_service(self):
        """get_optional() should return service if registered."""
        container = ServiceContainer()
        container.register_instance("test", "value")

        result = container.get_optional("test")
        assert result == "value"


class TestGlobalContainerManagement:
    """Tests for global container functions."""

    def setup_method(self):
        """Reset container before each test."""
        reset_container()

    def teardown_method(self):
        """Reset container after each test."""
        reset_container()
        # Reset logger factory to default
        set_logger_factory(StdlibLogger)

    def test_get_container_before_configure_raises(self):
        """get_container() before configure should raise RuntimeError."""
        with pytest.raises(RuntimeError, match="Service container not configured"):
            get_container()

    def test_configure_and_get_container(self):
        """configure_container() should set global container."""
        container = ServiceContainer()
        configure_container(container)

        result = get_container()
        assert result is container

    def test_reset_container(self):
        """reset_container() should clear global container."""
        container = ServiceContainer()
        configure_container(container)

        reset_container()

        with pytest.raises(RuntimeError):
            get_container()

    def test_configure_sets_logger_factory(self):
        """configure_container should set logger factory if provided."""

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

        container = ServiceContainer(logger_factory=CustomLogger)
        configure_container(container)

        # get_logger should now return CustomLogger
        logger = get_logger("test")
        assert isinstance(logger, CustomLogger)


class TestContainerWithProtocols:
    """Tests for container with protocol implementations."""

    def test_cache_protocol_storage(self):
        """Container should accept CacheProtocol implementations."""

        class InMemoryCache(CacheProtocol):
            def __init__(self):
                self._data = {}

            async def get_json(self, key):
                return self._data.get(key)

            async def set_json(self, key, value, _ttl):
                self._data[key] = value
                return True

            async def get(self, key):
                return self._data.get(key)

            async def set(self, key, value, _ttl):
                self._data[key] = value
                return True

        cache = InMemoryCache()
        container = ServiceContainer(cache=cache)

        assert isinstance(container.cache, CacheProtocol)

    def test_logger_factory_callable(self):
        """logger_factory should be callable returning LoggerProtocol."""
        container = ServiceContainer(logger_factory=StdlibLogger)

        assert container.logger_factory is not None
        logger = container.logger_factory("test.module")
        assert isinstance(logger, LoggerProtocol)


class TestContainerServiceChaining:
    """Tests for services that depend on other services."""

    def test_factory_can_access_container(self):
        """Factory can create service that uses other services."""
        container = ServiceContainer()

        # Register a config service
        container.register_instance("config", {"api_key": "secret"})

        # Register a service that depends on config
        def create_api_client():
            config = container.get("config")
            return f"Client with key: {config['api_key']}"

        container.register("api_client", create_api_client)

        result = container.get("api_client")
        assert result == "Client with key: secret"

    def test_multiple_services(self):
        """Container should handle multiple services."""
        container = ServiceContainer()

        container.register_instance("db", "postgres://...")
        container.register_instance("redis", "redis://...")
        container.register("computed", lambda: "computed_value")

        assert container.get("db") == "postgres://..."
        assert container.get("redis") == "redis://..."
        assert container.get("computed") == "computed_value"


class TestContainerEdgeCases:
    """Tests for edge cases."""

    def test_register_overwrites(self):
        """Registering same name should overwrite."""
        container = ServiceContainer()

        container.register_instance("test", "first")
        assert container.get("test") == "first"

        container.register_instance("test", "second")
        assert container.get("test") == "second"

    def test_factory_error_propagates(self):
        """Factory errors should propagate."""
        container = ServiceContainer()

        def failing_factory():
            raise ValueError("Factory failed")

        container.register("failing", failing_factory)

        with pytest.raises(ValueError, match="Factory failed"):
            container.get("failing")

    def test_none_instance_allowed(self):
        """None should be a valid instance."""
        container = ServiceContainer()
        container.register_instance("nullable", None)

        assert container.has("nullable") is True
        assert container.get("nullable") is None

    def test_get_optional_with_none_instance(self):
        """get_optional should return None instance, not skip it."""
        container = ServiceContainer()
        container.register_instance("nullable", None)

        # Should return None (the registered value), not None (not found)
        result = container.get_optional("nullable")
        assert result is None
        assert container.has("nullable") is True
