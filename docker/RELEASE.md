# SAQSHY Release and Deployment Guide

This document provides step-by-step instructions for deploying SAQSHY to production using Coolify.

## Prerequisites

- Coolify v4 instance configured
- Access to Coolify dashboard
- Telegram Bot Token configured
- API keys for Anthropic and Cohere

## Coolify Deployment

### Step 1: Create Application in Coolify

1. Go to Coolify dashboard
2. Create new **Docker Compose** application
3. Connect your GitHub repository (`nauanbek/saqshy`)
4. Set the compose file path: `docker/docker-compose.prod.yml`

### Step 2: Configure Environment Variables

In Coolify dashboard, add these environment variables:

**Required:**
```
TELEGRAM_BOT_TOKEN=<your bot token>
ANTHROPIC_API_KEY=<your key>
COHERE_API_KEY=<your key>
POSTGRES_PASSWORD=<strong random password>
JWT_SECRET=<random 32+ char string>
WEBHOOK_BASE_URL=https://your-domain.com
WEBHOOK_SECRET=<random string>
```

**Optional (have defaults):**
```
POSTGRES_USER=saqshy
POSTGRES_DB=saqshy
QDRANT_COLLECTION=spam_embeddings
ENVIRONMENT=production
LOG_LEVEL=INFO
DEBUG=false
```

### Step 3: Configure Domain

1. In Coolify, set your domain (e.g., `bot.yourdomain.com`)
2. Enable HTTPS (Traefik handles SSL via Let's Encrypt automatically)
3. SSL certificates are managed automatically by Coolify/Traefik

### Step 4: Deploy

Click "Deploy" in Coolify dashboard. The deployment will:
1. Build the bot image from Dockerfile
2. Start PostgreSQL, Redis, Qdrant services
3. Wait for healthchecks to pass
4. Start the bot container

### Step 5: Post-Deployment Setup

After successful deployment, run these commands via Coolify terminal or SSH:

```bash
# Run database migrations
docker compose -f docker/docker-compose.prod.yml exec bot alembic upgrade head

# Seed spam database (first deploy only)
docker compose -f docker/docker-compose.prod.yml exec bot python scripts/seed_spam_db.py
```

### Step 6: Configure Telegram Webhook

```bash
# Set webhook URL
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-domain.com/webhook",
    "secret_token": "<YOUR_WEBHOOK_SECRET>"
  }'

# Verify webhook
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

### Step 7: Verify Deployment

```bash
# Check health endpoint
curl https://your-domain.com/health

# Check detailed health
curl https://your-domain.com/health/ready

# Test Mini App access
curl -I https://your-domain.com/app/
```

---

## Pre-Release Checklist

### Code Verification
- [ ] All tests pass locally: `pytest`
- [ ] Type checking passes: `mypy src/`
- [ ] Linting passes: `ruff check .`
- [ ] No hardcoded secrets in code
- [ ] Database migrations reviewed and tested

### Environment Preparation
- [ ] All environment variables configured in Coolify dashboard
- [ ] `POSTGRES_PASSWORD` is strong and unique
- [ ] `JWT_SECRET` is randomly generated (32+ chars)
- [ ] `WEBHOOK_SECRET` is set
- [ ] Domain configured in Coolify

---

## Rollback Procedure

### Quick Rollback (Same Version)

```bash
# Restart services via Coolify dashboard
# Or manually:
docker compose -f docker/docker-compose.prod.yml restart

# If that doesn't work, recreate containers
docker compose -f docker/docker-compose.prod.yml down
docker compose -f docker/docker-compose.prod.yml up -d
```

### Rollback to Previous Version

1. In Coolify, go to Deployments history
2. Click "Rollback" on the previous successful deployment
3. Alternatively, manually:

```bash
# 1. Stop current deployment
docker compose -f docker/docker-compose.prod.yml down

# 2. Checkout previous version
git log --oneline -10  # Find the previous good commit
git checkout <previous-commit-hash>

# 3. Redeploy via Coolify
```

### Database Rollback

```bash
# Check current migration
docker compose -f docker/docker-compose.prod.yml exec bot alembic current

# List all migrations
docker compose -f docker/docker-compose.prod.yml exec bot alembic history

# Rollback one migration
docker compose -f docker/docker-compose.prod.yml exec bot alembic downgrade -1

# Rollback to specific revision
docker compose -f docker/docker-compose.prod.yml exec bot alembic downgrade <revision_id>
```

### Emergency: Full Service Stop

```bash
# Stop everything
docker compose -f docker/docker-compose.prod.yml down

# Remove webhook (bot will stop receiving messages)
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/deleteWebhook"
```

---

## Monitoring and Logs

### View Logs

In Coolify dashboard, go to "Logs" tab. Or via SSH:

```bash
# All services
docker compose -f docker/docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker/docker-compose.prod.yml logs -f bot
docker compose -f docker/docker-compose.prod.yml logs -f postgres
```

### Health Checks

```bash
# Bot health (via domain)
curl https://your-domain.com/health

# Bot readiness (checks all dependencies)
curl https://your-domain.com/health/ready

# PostgreSQL
docker compose -f docker/docker-compose.prod.yml exec postgres pg_isready -U saqshy

# Redis
docker compose -f docker/docker-compose.prod.yml exec redis redis-cli ping
```

### Resource Usage

```bash
docker stats
```

---

## Backup and Restore

### Backup Database

```bash
# Create backup
docker compose -f docker/docker-compose.prod.yml exec postgres \
  pg_dump -U saqshy saqshy > backup_$(date +%Y%m%d_%H%M%S).sql

# Compress
gzip backup_*.sql
```

### Restore Database

```bash
# Stop bot first
docker compose -f docker/docker-compose.prod.yml stop bot

# Restore
gunzip backup_YYYYMMDD_HHMMSS.sql.gz
docker compose -f docker/docker-compose.prod.yml exec -T postgres \
  psql -U saqshy saqshy < backup_YYYYMMDD_HHMMSS.sql

# Restart bot
docker compose -f docker/docker-compose.prod.yml start bot
```

### Backup Qdrant

```bash
# Create snapshot
curl -X POST "http://localhost:6333/collections/spam_embeddings/snapshots"

# List snapshots
curl "http://localhost:6333/collections/spam_embeddings/snapshots"
```

---

## Troubleshooting

### Bot Not Responding

1. Check webhook status: `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo`
2. Check bot logs in Coolify dashboard
3. Verify health: `curl https://your-domain.com/health`
4. Check Traefik routing in Coolify

### Database Connection Issues

1. Check PostgreSQL: `docker compose exec postgres pg_isready`
2. Verify DATABASE_URL in Coolify environment variables
3. Check PostgreSQL logs: `docker compose logs postgres`

### High Memory Usage

1. Check stats: `docker stats`
2. Restart specific service: `docker compose restart bot`
3. Check resource limits in docker-compose.prod.yml

### Deployment Fails with "port already allocated"

This should not happen with current configuration. If it does:
1. Verify `docker-compose.prod.yml` uses `expose:` not `ports:` for bot service
2. Check no other services are binding to the same port
3. Restart Coolify/Traefik if needed

---

## Important Notes

- **SSL/TLS**: Handled automatically by Coolify/Traefik via Let's Encrypt
- **Port binding**: Do NOT use `ports:` directive in docker-compose.prod.yml - use `expose:` instead
- **Environment variables**: Injected via Coolify dashboard, not `.env.prod` file
- **Container naming**: Do NOT use `container_name:` directive - Coolify manages naming

---

## Contact

For critical issues, contact the development team immediately.
