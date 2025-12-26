.PHONY: help dev test lint format migrate seed clean install docker-up docker-down health

# Default target
help:
	@echo "SAQSHY Bot - Available Commands"
	@echo "================================"
	@echo ""
	@echo "Development:"
	@echo "  make install     - Install dependencies with uv"
	@echo "  make dev         - Start development environment"
	@echo "  make docker-up   - Start Docker services"
	@echo "  make docker-down - Stop Docker services"
	@echo ""
	@echo "Testing:"
	@echo "  make test        - Run all tests"
	@echo "  make test-cov    - Run tests with coverage"
	@echo "  make lint        - Run linting checks"
	@echo "  make format      - Format code with ruff"
	@echo "  make typecheck   - Run mypy type checking"
	@echo ""
	@echo "Database:"
	@echo "  make migrate     - Run database migrations"
	@echo "  make seed        - Seed spam database"
	@echo "  make init-db     - Initialize database"
	@echo ""
	@echo "Utilities:"
	@echo "  make health      - Run health check"
	@echo "  make clean       - Clean cache files"

# Install dependencies
install:
	uv sync

# Development
dev: docker-up
	uv run python -m saqshy

docker-up:
	docker-compose -f docker/docker-compose.yml up -d

docker-down:
	docker-compose -f docker/docker-compose.yml down

# Testing
test:
	uv run pytest -v

test-cov:
	uv run pytest --cov=src/saqshy --cov-report=html --cov-report=term

test-unit:
	uv run pytest tests/unit -v

test-integration:
	uv run pytest tests/integration -v

# Code Quality
lint:
	uv run ruff check .
	uv run mypy src/

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy src/

# Database
migrate:
	uv run alembic upgrade head

migrate-down:
	uv run alembic downgrade -1

migrate-new:
	@read -p "Migration message: " msg; \
	uv run alembic revision --autogenerate -m "$$msg"

init-db:
	uv run python scripts/init_db.py

seed:
	uv run python scripts/seed_spam_db.py

# Utilities
health:
	uv run python scripts/health_check.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
