# SAQSHY

AI-powered Telegram anti-spam bot using Cumulative Risk Score architecture.

**Philosophy:** Make spam attacks economically unfeasible. No single signal is decisive. Better to let 2-3% spam through than block a legitimate user.

## Features

- **Cumulative Risk Scoring**: Multiple signals combined for accurate spam detection
- **Group-Type Awareness**: Optimized thresholds for general, tech, deals, and crypto groups
- **Channel Subscription Trust**: Conditional trust signal with duration bonuses and new account caps
- **Sandbox Mode**: Protected onboarding for new users with race-condition-safe state management
- **LLM Gray Zone**: AI-powered decisions for wide score range (35-85) with first-message pre-filtering
- **Cross-Group Detection**: Tiered duplicate detection across groups (+20/+35/+50 points)
- **Real-time Spam Database**: Vector similarity matching against known spam patterns
- **Admin Feedback Loop**: Confirm/False Positive buttons for continuous model improvement
- **Mini App**: Admin dashboard for settings and analytics

## Quick Start

### Prerequisites

- Python 3.12+
- Docker and Docker Compose
- Telegram Bot Token
- Anthropic API Key (for Claude)
- Cohere API Key (for embeddings)

### Development Setup

1. **Clone and configure:**

```bash
cd saqshy
cp .env.example .env
# Edit .env with your configuration
```

2. **Start services:**

```bash
make docker-up
```

3. **Initialize database:**

```bash
make init-db
```

4. **Run the bot:**

```bash
make dev
```

### Using uv (recommended)

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Run linting
uv run ruff check .

# Start the bot
uv run python -m saqshy
```

## Project Structure

```
saqshy/
├── src/saqshy/
│   ├── bot/          # Telegram bot handlers, middlewares, filters
│   ├── core/         # Domain logic (ZERO external dependencies)
│   ├── analyzers/    # Signal extractors (profile, content, behavior)
│   ├── services/     # External API clients (LLM, embeddings, cache)
│   ├── db/           # Database models and repositories
│   ├── mini_app/     # Telegram Mini App API
│   └── utils/        # Helper functions
├── tests/            # Test suite
├── scripts/          # Utility scripts
├── docker/           # Docker configuration
├── pyproject.toml    # Project configuration
└── CLAUDE.md         # AI assistant instructions
```

## Architecture

### Message Processing Pipeline

```
Webhook → Preprocessor → [Profile + Content + Behavior + SpamDB] (parallel)
       → RiskCalculator → Verdict → ActionEngine
       → LLM (gray zone 35-85, or first messages from unestablished users)
```

### Verdicts

| Verdict | Score Range | Action |
|---------|-------------|--------|
| ALLOW   | 0-30        | Message passes |
| WATCH   | 30-50       | Log but allow |
| LIMIT   | 50-75       | Restrict user |
| REVIEW  | 75-92       | Admin review queue |
| BLOCK   | 92+         | Delete and restrict |

### Group Types

| Type | Description | Adjustments |
|------|-------------|-------------|
| `general` | Standard groups | Default thresholds |
| `tech` | Developer groups | Links/GitHub normal |
| `deals` | Shopping groups | Promo links normal |
| `crypto` | Crypto groups | Strict scam detection |

## Key Signals

**Trust Signals (reduce risk):**
- Channel subscriber: **-15 to -25 points** (conditional on account age and duration)
  - Base: -15, +7 days: -20, +30 days: -25
  - New accounts (<7 days) capped at -10 max
- Group membership: -5 (7d) / -10 (30d) / -15 (90d)
- Previous approved messages: -5 to -15 points
- Account age (3+ years): -15 points
- Premium user: -10 points

**Risk Signals (increase risk):**
- Spam DB similarity 0.95+: +50 points
- Crypto scam phrases: +35 points
- Duplicate across groups: +20 (2 groups) / +35 (3 groups) / +50 (5+ groups)
- New account (<7 days): +15 points

## Commands

```bash
# Development
make dev              # Start development environment
make test             # Run all tests
make lint             # Run linting checks
make format           # Format code

# Database
make migrate          # Run migrations
make init-db          # Initialize database
make seed             # Seed spam database

# Docker
make docker-up        # Start Docker services
make docker-down      # Stop Docker services

# Utilities
make health           # Run health check
make clean            # Clean cache files
```

## Configuration

See `.env.example` for all configuration options:

- `TELEGRAM_BOT_TOKEN`: Bot API token
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `QDRANT_URL`: Qdrant vector database URL
- `ANTHROPIC_API_KEY`: Claude API key
- `COHERE_API_KEY`: Cohere embeddings API key

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/saqshy --cov-report=html

# Run specific test file
pytest tests/unit/test_risk_calculator.py

# Run specific test
pytest -k "test_channel_subscriber"
```

## Documentation

- `CLAUDE.md` - AI assistant instructions
- `SECURITY.md` - Security audit and guidelines
- `CHANGELOG.md` - Version history
- `CONTRIBUTING.md` - Contribution guidelines

## Technology Stack

- **Python 3.12+** with type hints
- **aiogram 3.x** - Telegram bot framework
- **aiohttp** - HTTP server for webhooks and Mini App API
- **SQLAlchemy 2.0** + asyncpg - Database ORM
- **Redis** - Caching and rate limiting
- **Qdrant** - Vector database for spam patterns
- **Claude (Anthropic)** - LLM for gray zone decisions
- **Cohere** - Text embeddings

## Production Deployment

### Coolify (Recommended)

SAQSHY is designed for Coolify v4 deployment with automatic SSL via Traefik.

1. **Create new service in Coolify:**
   - Type: Docker Compose
   - Source: GitHub repository or upload `docker/docker-compose.prod.yml`

2. **Configure environment variables in Coolify dashboard:**

| Variable | Description | How to Get |
|----------|-------------|------------|
| `TELEGRAM_BOT_TOKEN` | Bot API token | [@BotFather](https://t.me/BotFather) |
| `WEBHOOK_BASE_URL` | Your domain (e.g., `https://saqshy.example.com`) | Coolify domain settings |
| `WEBHOOK_SECRET` | Webhook verification secret | `openssl rand -hex 32` |
| `ANTHROPIC_API_KEY` | Claude API key | [Anthropic Console](https://console.anthropic.com/) |
| `COHERE_API_KEY` | Embeddings API key | [Cohere Dashboard](https://dashboard.cohere.com/) |
| `POSTGRES_PASSWORD` | Database password | `openssl rand -hex 16` |
| `JWT_SECRET` | Mini App JWT secret | `openssl rand -hex 32` |

3. **Deploy and run migrations:**

```bash
# After deployment succeeds, run migrations
docker exec saqshy-bot alembic upgrade head

# Seed spam database (optional)
docker exec saqshy-bot python scripts/seed_spam_db.py
```

4. **Configure domain in Coolify:**
   - Set domain to your WEBHOOK_BASE_URL
   - SSL is handled automatically by Traefik/Let's Encrypt

### Manual VPS Deployment

For non-Coolify deployments, see [`docker/RELEASE.md`](docker/RELEASE.md).

### Health Check Verification

After deployment, verify all services are healthy:

```bash
# Check bot health endpoint
curl https://your-domain.com/health

# Expected response:
# {"status": "healthy", "version": "2.2.0", "services": {...}}

# Check webhook status
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

### Troubleshooting

**Bot not responding to messages:**
1. Verify webhook is set: `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo`
2. Check bot logs in Coolify dashboard or `docker logs saqshy-bot`
3. Verify `WEBHOOK_BASE_URL` matches your domain

**"Port already allocated" error:**
- Use `expose:` instead of `ports:` in docker-compose (Traefik handles routing)

**Database connection errors:**
1. Check PostgreSQL is running in Coolify
2. Verify `DATABASE_URL` matches `POSTGRES_*` variables
3. Check PostgreSQL logs

**Mini App not loading:**
1. Verify `WEBHOOK_BASE_URL` is set correctly with HTTPS
2. Check that `/app/` route is accessible
3. Ensure frontend assets are built in container

For detailed deployment procedures, see [`docker/RELEASE.md`](docker/RELEASE.md).

## License

MIT
