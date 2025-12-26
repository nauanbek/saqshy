# Contributing to SAQSHY

Thank you for your interest in contributing to SAQSHY! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Python 3.12+
- Docker and Docker Compose
- uv (recommended) or pip

### Getting Started

1. Clone the repository:
```bash
git clone https://github.com/nauanbek/saqshy.git
cd saqshy
```

2. Install dependencies:
```bash
uv sync
```

3. Copy environment template:
```bash
cp .env.example .env
# Edit .env with your development configuration
```

4. Start development services:
```bash
make docker-up
```

5. Initialize database:
```bash
make init-db
```

## Code Style

We use strict code quality tools:

### Linting and Formatting (ruff)
```bash
uv run ruff check .        # Check for issues
uv run ruff check . --fix  # Auto-fix issues
uv run ruff format .       # Format code
```

### Type Checking (mypy)
```bash
uv run mypy src/
```

We use `strict = true` mode for mypy. All code must be fully typed.

### Pre-commit Checks

Before submitting a PR, ensure:
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest tests/unit
```

## Testing

### Running Tests

```bash
# All tests (requires running services)
uv run pytest

# Unit tests only (no external dependencies)
uv run pytest tests/unit

# Integration tests
uv run pytest tests/integration

# Security tests
uv run pytest tests/security

# With coverage
uv run pytest --cov=src/saqshy --cov-report=html
```

### Writing Tests

- Place unit tests in `tests/unit/`
- Place integration tests in `tests/integration/`
- Use fixtures from `tests/conftest.py`
- Follow existing patterns in the test suite

## Pull Request Guidelines

1. **Branch naming**: Use descriptive branch names
   - `feature/add-new-signal`
   - `fix/sandbox-timeout`
   - `docs/update-readme`

2. **Commit messages**: Write clear, descriptive commit messages
   - Use present tense ("Add feature" not "Added feature")
   - Keep first line under 72 characters
   - Reference issues when applicable

3. **PR description**: Include
   - What changes were made
   - Why they were made
   - How to test the changes

4. **CI checks**: Ensure all CI checks pass before requesting review

## Architecture Guidelines

When contributing code, follow these architectural principles:

### Module Dependencies
- `core/` has ZERO dependencies on other modules (only stdlib)
- `db/` is accessed only via repository pattern
- `bot/` handles transport only, delegates business logic to `core/`

### Key Patterns
- All weights and thresholds in `core/constants.py`
- All types/dataclasses in `core/types.py`
- Use async/await for all I/O operations
- Use structured logging with correlation IDs

## Getting Help

- Open an issue for bugs or feature requests
- Check existing issues before creating new ones
- Join discussions for general questions

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
