# SAQSHY Local Development Guide

This guide explains how to run and test the SAQSHY Mini App locally without deploying to production.

## Quick Start

### 1. Start Development Services

```bash
# Start PostgreSQL, Redis, Qdrant for development
docker compose -f docker/docker-compose.dev.yml up -d

# Verify services are running
docker compose -f docker/docker-compose.dev.yml ps
```

### 2. Run Database Migrations

```bash
# Apply migrations to dev database
DATABASE_URL="postgresql+asyncpg://saqshy:password@localhost:5433/saqshy" \
    uv run alembic upgrade head
```

### 3. Run the Mini App API Locally

```bash
# Start the API server with mock data
uv run python scripts/run_miniapp_local.py --seed --no-auth

# The server will be available at http://localhost:8080
```

### 4. Test the API

```bash
# Check health
curl http://localhost:8080/api/health

# Get group settings (when running in --no-auth mode)
curl http://localhost:8080/api/groups/-1001234567890/settings
```

## Running Tests

### Unit Tests (No External Dependencies)

```bash
# Run unit tests only
uv run pytest -m unit tests/unit/ -v
```

### Integration Tests

```bash
# Option 1: Use the test runner script (recommended)
uv run python scripts/run_local_tests.py -v

# Option 2: Manual setup
# Start test services
docker compose -f docker/docker-compose.test.yml up -d

# Wait for services to be ready, then run tests
TEST_DATABASE_URL="postgresql+asyncpg://saqshy_test:test_password@localhost:5434/saqshy_test" \
    uv run pytest tests/integration/ -v

# Stop test services when done
docker compose -f docker/docker-compose.test.yml down
```

### Mini App Specific Tests

```bash
# Run Mini App integration tests
uv run python scripts/run_local_tests.py --mini-app -v

# Or directly
TEST_DATABASE_URL="postgresql+asyncpg://saqshy_test:test_password@localhost:5434/saqshy_test" \
    uv run pytest tests/integration/test_mini_app/ -v
```

## Development Workflow

### Testing Mini App API Changes

1. **Start dev services**:
   ```bash
   docker compose -f docker/docker-compose.dev.yml up -d
   ```

2. **Make code changes** to `src/saqshy/mini_app/`

3. **Start local server**:
   ```bash
   uv run python scripts/run_miniapp_local.py --seed --no-auth
   ```

4. **Test with curl** or the Mini App frontend:
   ```bash
   curl http://localhost:8080/api/groups/-1001234567890/settings
   ```

5. **Run integration tests**:
   ```bash
   uv run python scripts/run_local_tests.py --mini-app -v
   ```

### Testing with Real Authentication

To test with proper Telegram WebApp authentication:

```python
# Generate valid init data for testing
from tests.fixtures.miniapp_auth import generate_test_init_data, TEST_BOT_TOKEN

init_data = generate_test_init_data(
    user_id=123456789,
    username="testuser",
    start_param="group_-1001234567890",
)

# Use in curl
import subprocess
subprocess.run([
    "curl", "-H", f"X-Telegram-Init-Data: {init_data}",
    "http://localhost:8080/api/groups/-1001234567890/settings"
])
```

Or start the server WITH authentication:
```bash
# Start with real auth validation (requires valid init data)
uv run python scripts/run_miniapp_local.py --seed
```

## Service Ports

### Development Environment (docker-compose.dev.yml)

| Service    | Port  | URL                                |
|------------|-------|-----------------------------------|
| PostgreSQL | 5433  | `localhost:5433`                   |
| Redis      | 6379  | `redis://localhost:6379`           |
| Qdrant     | 6333  | `http://localhost:6333`            |

### Test Environment (docker-compose.test.yml)

| Service    | Port  | URL                                |
|------------|-------|-----------------------------------|
| PostgreSQL | 5434  | `localhost:5434`                   |
| Redis      | 6380  | `redis://localhost:6380`           |
| Qdrant     | 6335  | `http://localhost:6335`            |

## Test Fixtures

### Mock Authentication

```python
from tests.fixtures.miniapp_auth import (
    # Generate valid init data
    generate_test_init_data,

    # Create mock WebAppAuth for handler tests
    create_mock_webapp_auth,

    # Create mock request with auth context
    create_mock_webapp_request,

    # Pytest fixtures
    mock_admin_webapp_auth,  # Admin user
    mock_non_admin_webapp_auth,  # Regular user
    valid_init_data,  # Valid init data string
    expired_init_data,  # Expired init data
)

# Example: Create mock admin auth
auth = create_mock_webapp_auth(
    user_id=123456789,
    username="testadmin",
    is_admin_for=[-1001234567890],  # Admin in this group
)
```

### Database Fixtures

```python
from tests.fixtures import (
    test_db_session,  # Isolated session with rollback
    test_db_engine,   # Test database engine
    test_redis_client,  # Redis client
    test_qdrant_client,  # Qdrant client
)

@pytest.mark.asyncio
async def test_something(test_db_session):
    # Use test_db_session for database operations
    # Changes are automatically rolled back after test
    pass
```

## Common Issues

### PostgreSQL Connection Refused

```
Error: Connection refused to localhost:5433
```

**Solution**: Start dev services:
```bash
docker compose -f docker/docker-compose.dev.yml up -d
```

### Tables Don't Exist

```
Error: relation "groups" does not exist
```

**Solution**: Run migrations:
```bash
DATABASE_URL="postgresql+asyncpg://saqshy:password@localhost:5433/saqshy" \
    uv run alembic upgrade head
```

### Port Already in Use

```
Error: Address already in use :8080
```

**Solution**: Use a different port:
```bash
uv run python scripts/run_miniapp_local.py --port 8081
```

### Authentication Fails

```
Error: 401 Unauthorized
```

**Solution**: Either use `--no-auth` mode or generate valid init data:
```python
from tests.fixtures.miniapp_auth import generate_test_init_data
init_data = generate_test_init_data(user_id=123456789)
# Use this in X-Telegram-Init-Data header
```

## Frontend Development

### Running Frontend Locally

```bash
cd mini_app_frontend

# Install dependencies
npm install

# Start dev server
npm run dev

# Frontend will be at http://localhost:5173
```

### Connecting to Local Backend

Update the API base URL in `mini_app_frontend/src/config.ts` or use environment variables:

```bash
VITE_API_URL=http://localhost:8080 npm run dev
```

### End-to-End Testing

```bash
# Start backend
uv run python scripts/run_miniapp_local.py --seed --no-auth

# In another terminal, start frontend
cd mini_app_frontend && npm run dev

# In another terminal, run E2E tests (if configured)
cd mini_app_frontend && npm run test:e2e
```

## Summary

| Task | Command |
|------|---------|
| Start dev services | `docker compose -f docker/docker-compose.dev.yml up -d` |
| Run migrations | `DATABASE_URL=... uv run alembic upgrade head` |
| Start Mini App API | `uv run python scripts/run_miniapp_local.py --seed --no-auth` |
| Run unit tests | `uv run pytest -m unit tests/unit/ -v` |
| Run integration tests | `uv run python scripts/run_local_tests.py -v` |
| Run Mini App tests | `uv run python scripts/run_local_tests.py --mini-app -v` |
| Stop services | `docker compose -f docker/docker-compose.dev.yml down` |
