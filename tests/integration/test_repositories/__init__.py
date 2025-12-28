"""Integration tests for database repositories.

These tests run against a real PostgreSQL instance and verify
the repository layer works correctly with actual database operations.

Requirements:
    - PostgreSQL running on localhost:5433 (or TEST_DATABASE_URL env var set)
    - Database 'saqshy_test' created with appropriate permissions

Run with:
    pytest tests/integration/test_repositories/ -v
"""
