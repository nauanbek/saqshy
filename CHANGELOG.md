# Changelog

All notable changes to SAQSHY will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2024-12-26

Initial production release of SAQSHY - AI-powered Telegram anti-spam bot.

### Added

#### Core Architecture
- Cumulative Risk Score system with configurable thresholds
- 4 group type profiles: `general`, `tech`, `deals`, `crypto`
- 5-tier verdict system: ALLOW, WATCH, LIMIT, REVIEW, BLOCK
- Parallel signal processing pipeline with timeout handling

#### Analyzers
- **Profile Analyzer**: Account age scoring, username pattern detection, bio scanning, premium status
- **Content Analyzer**: URL parsing and domain extraction, crypto scam phrase detection, 50+ retailer whitelist for deals groups, shortener URL handling
- **Behavior Analyzer**: Time-to-first-message (TTFM) tracking, channel subscription verification, reply chain analysis, duplicate message detection across groups
- **Spam Database**: Vector similarity matching using Qdrant and Cohere embeddings

#### Trust System
- Channel subscription as strongest trust signal (-25 points)
- Progressive trust through message history
- Smart Sandbox mode for new user onboarding
- Soft Watch mode for deals groups

#### AI Integration
- Claude Sonnet 4 for gray zone decisions (score 60-80)
- Prompt injection defense with input sanitization
- Structured JSON response parsing with fallback handling

#### Telegram Bot
- aiogram 3.x webhook-based architecture
- Middleware pipeline: rate limiting, authentication, logging
- Admin commands for group configuration
- Real-time message processing

#### Mini App
- React 18 + TypeScript + Vite frontend
- Admin dashboard for group settings
- Analytics and statistics views
- JWT-based authentication with Telegram WebApp validation

#### Infrastructure
- Docker Compose production setup (PostgreSQL, Redis, Qdrant, Nginx)
- Alembic database migrations
- Health check endpoints
- Comprehensive logging with structured output

#### Testing
- Unit tests for all core modules
- Integration tests for analyzers and services
- Security tests for rate limiting and input validation
- 6,656 lines of test coverage

### Security

- Constant-time HMAC verification for webhook signatures
- Rate limiting at multiple levels (webhook, API, per-user)
- Input sanitization for LLM prompts to prevent injection
- JWT token validation for Mini App API
- SQL injection prevention via parameterized queries
- XSS protection in Mini App frontend

### Documentation

- Comprehensive technical specification (`tech.md`)
- Product philosophy and signal weights (`idea.md`)
- Development phase guide (`START_PROMPT.md`)
- 22 specialized agent prompts for development workflow
- Production deployment runbook (`docker/RELEASE.md`)

---

## [Unreleased]

### Planned
- Group analytics dashboard improvements
- Bulk moderation actions
- Custom signal weight configuration per group
- Webhook retry with exponential backoff
- Prometheus metrics endpoint
