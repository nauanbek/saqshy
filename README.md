# SAQSHY

AI-powered Telegram anti-spam bot using Cumulative Risk Score architecture.

**Philosophy:** Make spam attacks economically unfeasible. No single signal is decisive. Better to let 2-3% spam through than block a legitimate user.

## Features

- **Cumulative Risk Scoring**: Multiple signals combined for accurate spam detection
- **Group-Type Awareness**: Optimized thresholds for general, tech, deals, and crypto groups
- **Channel Subscription Trust**: Strongest trust signal for verified community members
- **Sandbox Mode**: Protected onboarding for new users
- **LLM Gray Zone**: AI-powered decisions for ambiguous cases (60-80 score range)
- **Real-time Spam Database**: Vector similarity matching against known spam patterns
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
       → LLM (only for gray zone 60-80)
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
- Channel subscriber: **-25 points**
- Previous approved messages: -5 to -15 points
- Account age (3+ years): -15 points
- Premium user: -10 points

**Risk Signals (increase risk):**
- Spam DB similarity 0.88+: +45 points
- Crypto scam phrases: +35 points
- Duplicate across groups: +35 points
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

### Quick Start (VPS)

1. **Prepare the server:**

```bash
# SSH into your VPS
ssh user@your-server

# Create deployment directory
sudo mkdir -p /opt/saqshy
sudo chown $USER:$USER /opt/saqshy
cd /opt/saqshy

# Clone the repository
git clone https://github.com/nauanbek/saqshy.git .
```

2. **Configure environment:**

```bash
# Copy production template
cp .env.prod.example .env.prod

# Edit with your production values
nano .env.prod
```

3. **Setup SSL and deploy:**

```bash
# Install certbot and get certificate
sudo apt install certbot
sudo certbot certonly --standalone -d your-domain.com

# Copy certificates
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem docker/nginx/ssl/cert.pem
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem docker/nginx/ssl/key.pem

# Build and start
docker compose -f docker/docker-compose.prod.yml up -d

# Run migrations
docker compose -f docker/docker-compose.prod.yml exec bot alembic upgrade head
```

4. **Set webhook:**

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-domain.com/webhook", "secret_token": "<WEBHOOK_SECRET>"}'
```

### GitHub Actions Secrets

For automated CI/CD deployment, configure these secrets in your repository:

| Secret | Description | How to Get |
|--------|-------------|------------|
| `TELEGRAM_BOT_TOKEN` | Production bot token | [@BotFather](https://t.me/BotFather) |
| `ANTHROPIC_API_KEY` | Claude API key | [Anthropic Console](https://console.anthropic.com/) |
| `COHERE_API_KEY` | Embeddings API key | [Cohere Dashboard](https://dashboard.cohere.com/) |
| `POSTGRES_PASSWORD` | Database password | `openssl rand -hex 16` |
| `WEBHOOK_SECRET` | Webhook verification | `openssl rand -hex 32` |
| `JWT_SECRET` | Mini App JWT secret | `openssl rand -hex 32` |
| `SSH_HOST` | Server IP address | Your VPS provider |
| `SSH_USER` | SSH username | Usually `root` or `deploy` |
| `SSH_PRIVATE_KEY` | SSH private key | `cat ~/.ssh/id_ed25519` |
| `GHCR_TOKEN` | GitHub packages token | [GitHub Settings](https://github.com/settings/tokens) |

### Health Check Verification

After deployment, verify all services are healthy:

```bash
# Check bot health endpoint
curl https://your-domain.com/health

# Expected response:
# {"status": "healthy", "version": "1.0.0", "services": {...}}

# Check webhook status
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"

# Check service status
docker compose -f docker/docker-compose.prod.yml ps
```

### Troubleshooting

**Bot not responding to messages:**
1. Verify webhook is set: `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo`
2. Check bot logs: `docker compose -f docker/docker-compose.prod.yml logs bot`
3. Verify SSL certificate is valid and not expired

**Database connection errors:**
1. Check PostgreSQL is running: `docker compose ps postgres`
2. Verify `DATABASE_URL` in `.env.prod` matches `POSTGRES_*` variables
3. Check PostgreSQL logs: `docker compose logs postgres`

**Mini App not loading:**
1. Verify frontend was built: `ls mini_app_frontend/dist/`
2. Check Nginx logs: `docker compose logs nginx`
3. Ensure `MINI_APP_URL` matches your domain

**High memory usage:**
1. Check resource usage: `docker stats`
2. Consider increasing server RAM (2GB+ recommended)
3. Restart services: `docker compose restart`

For detailed deployment procedures, see [`docker/RELEASE.md`](docker/RELEASE.md).

## License

MIT
