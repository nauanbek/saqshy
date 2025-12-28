#!/usr/bin/env python3
"""
SAQSHY Local Test Runner

This script provides a complete local testing environment without production deploys.
It handles:
1. Starting test services (PostgreSQL, Redis, Qdrant)
2. Waiting for services to be ready
3. Running database migrations
4. Running specified tests
5. Cleaning up after tests

Usage:
    # Run all integration tests
    python scripts/run_local_tests.py

    # Run specific test file
    python scripts/run_local_tests.py tests/integration/test_mini_app/test_api_endpoints.py

    # Run with verbose output
    python scripts/run_local_tests.py -v

    # Skip docker startup (services already running)
    python scripts/run_local_tests.py --no-docker

    # Run unit tests only (no external deps)
    python scripts/run_local_tests.py --unit

    # Keep services running after tests
    python scripts/run_local_tests.py --keep-services

Environment Variables:
    TEST_DATABASE_URL - Override test database URL
    TEST_REDIS_URL - Override test Redis URL
    TEST_QDRANT_URL - Override test Qdrant URL
"""

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent


def run_command(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return result."""
    print(f"Running: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd or PROJECT_ROOT, check=check, capture_output=False)


def start_test_services():
    """Start test docker services."""
    print("\n=== Starting test services ===")
    compose_file = PROJECT_ROOT / "docker" / "docker-compose.test.yml"

    if not compose_file.exists():
        print(f"ERROR: {compose_file} not found")
        sys.exit(1)

    run_command([
        "docker", "compose",
        "-f", str(compose_file),
        "up", "-d",
    ])
    print("Test services started")


def stop_test_services():
    """Stop test docker services."""
    print("\n=== Stopping test services ===")
    compose_file = PROJECT_ROOT / "docker" / "docker-compose.test.yml"

    run_command([
        "docker", "compose",
        "-f", str(compose_file),
        "down",
    ], check=False)
    print("Test services stopped")


def wait_for_postgres(max_attempts: int = 30, delay: float = 1.0) -> bool:
    """Wait for PostgreSQL to be ready."""
    import socket

    print("Waiting for PostgreSQL...")
    host = "localhost"
    port = 5434  # Test postgres port

    for attempt in range(max_attempts):
        try:
            with socket.create_connection((host, port), timeout=1):
                print(f"PostgreSQL is ready (attempt {attempt + 1})")
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(delay)

    print("ERROR: PostgreSQL did not become ready in time")
    return False


def wait_for_redis(max_attempts: int = 30, delay: float = 1.0) -> bool:
    """Wait for Redis to be ready."""
    import socket

    print("Waiting for Redis...")
    host = "localhost"
    port = 6380  # Test redis port

    for attempt in range(max_attempts):
        try:
            with socket.create_connection((host, port), timeout=1):
                print(f"Redis is ready (attempt {attempt + 1})")
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(delay)

    print("ERROR: Redis did not become ready in time")
    return False


def wait_for_qdrant(max_attempts: int = 30, delay: float = 1.0) -> bool:
    """Wait for Qdrant to be ready."""
    import socket

    print("Waiting for Qdrant...")
    host = "localhost"
    port = 6335  # Test qdrant port

    for attempt in range(max_attempts):
        try:
            with socket.create_connection((host, port), timeout=1):
                print(f"Qdrant is ready (attempt {attempt + 1})")
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(delay)

    print("ERROR: Qdrant did not become ready in time")
    return False


def run_migrations():
    """Run Alembic migrations for test database."""
    print("\n=== Running migrations ===")

    # Set test database URL
    os.environ["DATABASE_URL"] = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://saqshy_test:test_password@localhost:5434/saqshy_test"
    )

    try:
        run_command([
            "uv", "run", "alembic", "upgrade", "head"
        ])
        print("Migrations completed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"WARNING: Migration failed (may be OK if tables exist): {e}")
        return True  # Continue anyway, tests may create tables


def run_pytest(args: list[str], verbose: bool = False) -> int:
    """Run pytest with specified arguments."""
    print("\n=== Running tests ===")

    # Set test environment variables
    os.environ["TEST_DATABASE_URL"] = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://saqshy_test:test_password@localhost:5434/saqshy_test"
    )
    os.environ["TEST_REDIS_URL"] = os.getenv(
        "TEST_REDIS_URL",
        "redis://localhost:6380"
    )
    os.environ["TEST_QDRANT_URL"] = os.getenv(
        "TEST_QDRANT_URL",
        "http://localhost:6335"
    )

    cmd = ["uv", "run", "pytest"]
    if verbose:
        cmd.append("-v")
    cmd.extend(args)

    result = run_command(cmd, check=False)
    return result.returncode


def run_unit_tests(verbose: bool = False) -> int:
    """Run unit tests only (no external dependencies)."""
    print("\n=== Running unit tests ===")

    cmd = ["uv", "run", "pytest", "-m", "unit", "tests/unit/"]
    if verbose:
        cmd.append("-v")

    result = run_command(cmd, check=False)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="SAQSHY Local Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "test_paths",
        nargs="*",
        default=["tests/integration/"],
        help="Test paths to run (default: tests/integration/)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose test output",
    )
    parser.add_argument(
        "--no-docker",
        action="store_true",
        help="Skip starting docker services (assume they're already running)",
    )
    parser.add_argument(
        "--unit",
        action="store_true",
        help="Run unit tests only (no external dependencies)",
    )
    parser.add_argument(
        "--keep-services",
        action="store_true",
        help="Keep docker services running after tests",
    )
    parser.add_argument(
        "--mini-app",
        action="store_true",
        help="Run Mini App integration tests specifically",
    )

    args = parser.parse_args()

    # Unit tests don't need docker
    if args.unit:
        exit_code = run_unit_tests(args.verbose)
        sys.exit(exit_code)

    # Start services if needed
    if not args.no_docker:
        try:
            start_test_services()
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Failed to start docker services: {e}")
            sys.exit(1)

    # Wait for services
    try:
        if not wait_for_postgres():
            sys.exit(1)
        if not wait_for_redis():
            sys.exit(1)
        if not wait_for_qdrant():
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted. Cleaning up...")
        if not args.keep_services and not args.no_docker:
            stop_test_services()
        sys.exit(1)

    # Run migrations
    run_migrations()

    # Determine test paths
    test_paths = args.test_paths
    if args.mini_app:
        test_paths = ["tests/integration/test_mini_app/"]

    # Run tests
    try:
        exit_code = run_pytest(test_paths, args.verbose)
    except KeyboardInterrupt:
        print("\nTests interrupted")
        exit_code = 1
    finally:
        # Cleanup
        if not args.keep_services and not args.no_docker:
            stop_test_services()

    # Summary
    print("\n" + "=" * 50)
    if exit_code == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"TESTS FAILED (exit code: {exit_code})")
    print("=" * 50)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
