"""
SAQSHY Load Tests

Performance and stress tests for spam attack resilience.

These tests verify the system can handle:
- High message throughput (100+ messages/second)
- Circuit breaker behavior under load
- Graceful degradation when services fail
- Database write performance under load
- Concurrent access patterns

Run with:
    pytest -m load tests/load/
    pytest -m "load and slow" --timeout=60  # Extended timeout for load tests
"""
