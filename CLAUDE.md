# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SAQSHY is an AI-powered Telegram anti-spam bot using Cumulative Risk Score architecture.

**Philosophy:** Make spam attacks economically unfeasible. No single signal is decisive. Better to let 2-3% spam through than block a legitimate user.

## Technology Stack

- Python 3.12+, aiogram 3.x, aiohttp
- PostgreSQL 16 (SQLAlchemy 2.0 + asyncpg), Redis 7.x, Qdrant 1.x
- Claude API (claude-sonnet-4-20250514), Cohere embed-multilingual-v3.0
- React 18, Vite, TypeScript (Mini App)
- Docker 24.x, Coolify/Traefik (production)

## Commands

```bash
# Development (using uv - recommended)
uv sync                              # Install dependencies
uv run python -m saqshy              # Start the bot
uv run pytest                        # Run all tests
uv run pytest -k "test_risk"         # Run specific test pattern
uv run pytest tests/unit/test_risk_calculator.py  # Run single file
uv run ruff check . && uv run ruff format .       # Lint and format
uv run mypy src/                     # Type checking

# Docker
docker compose -f docker/docker-compose.yml up     # Start all services
docker compose -f docker/docker-compose.dev.yml up # Dev with hot reload

# Database
alembic upgrade head                 # Run migrations
alembic revision --autogenerate -m "description"  # Create migration

# Scripts
python scripts/seed_spam_db.py       # Seed spam embeddings
python scripts/init_db.py            # Initialize database
python scripts/health_check.py       # Check service health
```

## Architecture

```
src/saqshy/
├── bot/          → aiogram handlers, middlewares, filters, pipeline, action_engine
├── core/         → RiskCalculator, Sandbox, types, constants (ZERO external deps)
├── analyzers/    → ProfileAnalyzer, ContentAnalyzer, BehaviorAnalyzer, signals
├── services/     → LLM, Embeddings, Cache, ChannelSubscription, SpamDB, Network
├── db/           → SQLAlchemy models, repositories (groups, users, decisions)
├── mini_app/     → aiohttp routes, auth, handlers for Telegram Mini App
├── api/          → Health check endpoints
└── utils/        → Text, URL, Telegram helpers
```

**Key Rules:**
- `core/` has ZERO dependencies on other modules (only stdlib + own types)
- `db/` accessed only via repository pattern (`db/repositories/`)
- `bot/` handles transport only, delegates business logic to `core/`
- All weights and thresholds defined in `core/constants.py`
- All types/dataclasses defined in `core/types.py`

## Message Processing Pipeline

```
Webhook → bot/handlers/messages.py → bot/pipeline.py
       → [ProfileAnalyzer + ContentAnalyzer + BehaviorAnalyzer + SpamDB] (parallel)
       → core/risk_calculator.py → Verdict
       → services/llm.py (only for gray zone 60-80)
       → bot/action_engine.py → Execute action
```

### Verdicts and Actions

| Verdict | Score | Actions |
|---------|-------|---------|
| ALLOW | 0-30 | — |
| WATCH | 30-50 | log |
| LIMIT | 50-75 | **delete**, restrict, log, notify_admins |
| REVIEW | 75-92 | hold, log, queue_review, notify_admins |
| BLOCK | 92+ | delete, ban, log, notify_admins |

## Group Types (Critical)

Thresholds in `core/constants.py:THRESHOLDS`:

| Type | Thresholds (WATCH/LIMIT/REVIEW/BLOCK) | Behavior |
|------|---------------------------------------|----------|
| `general` | 30/50/75/92 | Standard weights |
| `tech` | 30/50/75/92 | GitHub/docs links tolerated (`TECH_WEIGHT_OVERRIDES`) |
| `deals` | 40/60/80/95 | Links/promo = NORMAL (`DEALS_WEIGHT_OVERRIDES`), Soft Watch |
| `crypto` | 25/45/70/90 | Crypto terms OK (`CRYPTO_WEIGHT_OVERRIDES`), strict scam |

**Deals groups:** `WHITELIST_DOMAINS_DEALS`, `ALLOWED_SHORTENERS` (clck.ru, fas.st, bit.ly), FP target <5%.

## Crypto Scam Detection (core/constants.py)

`CRYPTO_SCAM_PHRASES` triggers +35 score. Key patterns:
- Airdrop: `"airdrop"`, `"free tokens"`, `"claim reward"`, `"free crypto"`
- Channel spam: `"join channel"`, `"join t.me"`, `"join now"`
- Urgency: `"limited time"`, `"hurry up"`, `"act now"`, `"don't miss"`
- Investment: `"guaranteed profit"`, `"double your"`, `"passive income"`
- Russian: `"бесплатный аирдроп"`, `"вступай в канал"`

## Key Signals (from core/constants.py)

Trust signals (negative = lower risk):
- `is_channel_subscriber`: **-25** (strongest in `BEHAVIOR_WEIGHTS`)
- `previous_messages_approved_10_plus`: -15
- `account_age_3_years`: -15
- `is_in_global_whitelist`: -30

Risk signals (positive = higher risk):
- `spam_db_similarity_0.95_plus`: +50 (in `NETWORK_WEIGHTS`)
- `is_in_global_blocklist`: +50
- `crypto_scam_phrase`: +35 (in `CONTENT_WEIGHTS`)
- `duplicate_across_groups`: +35

## Bot Commands

Admin commands (in groups):
- `/settings` — Open Mini App settings (requires admin)
- `/status` — Show protection status
- `/stats` — View spam statistics
- `/settype [general|tech|deals|crypto]` — Set group type
- `/whitelist @user` — Add to trusted list
- `/blacklist @user` — Add to blocklist
- `/check @user` — Check user trust score

## Middlewares (bot/middlewares/)

Execution order:
1. `ErrorMiddleware` (outer) — Catches all errors
2. `ConfigMiddleware` — Injects config values (mini_app_url)
3. `LoggingMiddleware` — Correlation IDs, request logging
4. `AuthMiddleware` — Permission checks, admin detection
5. `RateLimitMiddleware` — Abuse prevention

## Core Types (from core/types.py)

- `GroupType`: Enum (GENERAL, TECH, DEALS, CRYPTO)
- `Verdict`: Enum (ALLOW, WATCH, LIMIT, REVIEW, BLOCK)
- `ThreatType`: Enum (NONE, SPAM, SCAM, CRYPTO_SCAM, PHISHING, FLOOD, RAID, BOT)
- `Signals`: Dataclass combining ProfileSignals, ContentSignals, BehaviorSignals, NetworkSignals
- `RiskResult`: Final calculation result with score, verdict, contributing/mitigating factors
- `MessageContext`: All context needed to analyze a message
- `Action`: What to do based on verdict (delete, restrict, ban, warn)

## Testing

```bash
# Test markers defined in pyproject.toml
pytest -m unit           # Unit tests only (no external deps)
pytest -m integration    # Integration tests (needs DB/Redis)
pytest -m security       # Security-focused tests
pytest --cov=src/saqshy --cov-report=html  # Coverage report
```

## Specialized Agents

22 agents in `.claude/agents/`. Key ones:

| Agent | Use For |
|-------|---------|
| `risk-decision-engineer` | Scoring logic, weights, group_type thresholds |
| `content-analyzer-engineer` | URL parsing, whitelists, CRYPTO_SCAM_PHRASES |
| `behavior-analyzer-engineer` | TTFM, channel subscription, reply chains |
| `message-pipeline-orchestrator` | Pipeline timeouts, circuit breakers, degradation |
| `channel-subscription-engineer` | Telegram getChatMember, caching, rate limits |
| `telegram-bot-engineer` | aiogram handlers, webhooks, middlewares |
| `sandbox-trust-engineer` | Sandbox + Soft Watch modes |
| `db-data-engineer` | Schema, migrations, repositories |
| `miniapp-backend-engineer` | aiohttp API, Telegram WebApp auth |
| `miniapp-frontend-engineer` | React UI in mini_app_frontend/ |

## Development Workflow

**Phase order:** Infrastructure → Core Domain → External Services → Telegram Bot → Mini App → Quality/Security → Production Deploy

## Deployment (Coolify)

Production uses Coolify v4 with Traefik reverse proxy:
- Use `docker/docker-compose.prod.yml`
- Use `expose:` not `ports:` (Traefik handles routing)
- Environment variables injected via Coolify dashboard
- SSL/TLS handled automatically by Let's Encrypt

Key environment variables:
- `TELEGRAM_BOT_TOKEN`, `WEBHOOK_BASE_URL`, `WEBHOOK_SECRET`
- `ANTHROPIC_API_KEY`, `COHERE_API_KEY`
- `POSTGRES_PASSWORD`, `JWT_SECRET`

## Documentation

- `docker/RELEASE.md` - Coolify deployment procedures
- `SECURITY.md` - Security audit and guidelines
- `CHANGELOG.md` - Version history
- `CONTRIBUTING.md` - Contribution guidelines
