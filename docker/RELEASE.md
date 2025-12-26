# SAQSHY Release and Deployment Guide

This document provides step-by-step instructions for deploying SAQSHY to production.

## Prerequisites

- Docker 24.x and Docker Compose v2
- SSL certificate and key for your domain
- Access to production server (VPS)
- Telegram Bot Token configured
- API keys for Anthropic and Cohere

## Directory Structure

```
/opt/saqshy/                 # Production deployment root
├── docker/
│   ├── docker-compose.prod.yml
│   ├── Dockerfile
│   └── nginx/
│       ├── nginx.conf
│       └── ssl/
│           ├── cert.pem
│           └── key.pem
├── src/
├── scripts/
├── alembic/
├── mini_app_frontend/
│   └── dist/               # Built frontend assets
└── .env.prod
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
- [ ] `.env.prod` created from `.env.example`
- [ ] All API keys configured
- [ ] `POSTGRES_PASSWORD` is strong and unique
- [ ] `JWT_SECRET` is randomly generated (32+ chars)
- [ ] `WEBHOOK_SECRET` is set

### Infrastructure
- [ ] SSL certificates placed in `docker/nginx/ssl/`
- [ ] DNS configured to point to server IP
- [ ] Firewall allows ports 80 and 443
- [ ] Server has sufficient resources (2GB+ RAM recommended)

---

## Release Procedure

### Step 1: Prepare the Server

```bash
# SSH into production server
ssh user@your-server

# Create deployment directory
sudo mkdir -p /opt/saqshy
sudo chown $USER:$USER /opt/saqshy
cd /opt/saqshy

# Clone or update repository
git clone https://github.com/nauanbek/saqshy.git .
# OR if updating:
git pull origin main
```

### Step 2: Configure Environment

```bash
# Copy environment template
cp .env.example .env.prod

# Edit with production values
nano .env.prod

# Required changes:
# - TELEGRAM_BOT_TOKEN=<real token>
# - ANTHROPIC_API_KEY=<real key>
# - COHERE_API_KEY=<real key>
# - POSTGRES_PASSWORD=<strong password>
# - JWT_SECRET=<random 32+ char string>
# - WEBHOOK_BASE_URL=https://your-domain.com
# - ENVIRONMENT=production
# - DEBUG=false
```

### Step 3: Setup SSL Certificates

```bash
# Option A: Using Let's Encrypt (recommended)
sudo apt install certbot
sudo certbot certonly --standalone -d your-domain.com

# Copy certificates
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem docker/nginx/ssl/cert.pem
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem docker/nginx/ssl/key.pem
sudo chown $USER:$USER docker/nginx/ssl/*.pem

# Option B: Self-signed (for testing only)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout docker/nginx/ssl/key.pem \
  -out docker/nginx/ssl/cert.pem \
  -subj "/CN=your-domain.com"
```

### Step 4: Build Frontend

```bash
cd mini_app_frontend
npm install
npm run build
cd ..
```

### Step 5: Build and Start Services

```bash
# Build the bot image
docker compose -f docker/docker-compose.prod.yml build

# Start all services
docker compose -f docker/docker-compose.prod.yml up -d

# Verify services are running
docker compose -f docker/docker-compose.prod.yml ps
```

### Step 6: Run Database Migrations

```bash
# Wait for database to be ready (healthcheck should pass)
sleep 10

# Run migrations
docker compose -f docker/docker-compose.prod.yml exec bot alembic upgrade head
```

### Step 7: Seed Spam Database (First Deploy Only)

```bash
docker compose -f docker/docker-compose.prod.yml exec bot python scripts/seed_spam_db.py
```

### Step 8: Configure Telegram Webhook

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

### Step 9: Verify Deployment

```bash
# Check health endpoint
curl -k https://your-domain.com/health

# Check logs for errors
docker compose -f docker/docker-compose.prod.yml logs -f bot

# Test Mini App access
curl -I https://your-domain.com/app/
```

---

## Rollback Procedure

If something goes wrong, follow these steps to rollback:

### Quick Rollback (Same Version)

```bash
# Restart services
docker compose -f docker/docker-compose.prod.yml restart

# If that doesn't work, recreate containers
docker compose -f docker/docker-compose.prod.yml down
docker compose -f docker/docker-compose.prod.yml up -d
```

### Rollback to Previous Version

```bash
# 1. Stop current deployment
docker compose -f docker/docker-compose.prod.yml down

# 2. Checkout previous version
git log --oneline -10  # Find the previous good commit
git checkout <previous-commit-hash>

# 3. Rebuild and restart
docker compose -f docker/docker-compose.prod.yml build
docker compose -f docker/docker-compose.prod.yml up -d
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

```bash
# All services
docker compose -f docker/docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker/docker-compose.prod.yml logs -f bot
docker compose -f docker/docker-compose.prod.yml logs -f nginx
docker compose -f docker/docker-compose.prod.yml logs -f postgres
```

### Health Checks

```bash
# Bot health
curl https://your-domain.com/health

# PostgreSQL
docker compose -f docker/docker-compose.prod.yml exec postgres pg_isready -U saqshy

# Redis
docker compose -f docker/docker-compose.prod.yml exec redis redis-cli ping

# Qdrant
curl http://localhost:6333/readyz  # Internal only
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

## SSL Certificate Renewal

### Automated (Recommended)

```bash
# Add to crontab
0 0 1 * * certbot renew --quiet && \
  cp /etc/letsencrypt/live/your-domain.com/fullchain.pem /opt/saqshy/docker/nginx/ssl/cert.pem && \
  cp /etc/letsencrypt/live/your-domain.com/privkey.pem /opt/saqshy/docker/nginx/ssl/key.pem && \
  docker compose -f /opt/saqshy/docker/docker-compose.prod.yml exec nginx nginx -s reload
```

### Manual

```bash
sudo certbot renew
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem docker/nginx/ssl/cert.pem
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem docker/nginx/ssl/key.pem
docker compose -f docker/docker-compose.prod.yml exec nginx nginx -s reload
```

---

## Troubleshooting

### Bot Not Responding

1. Check webhook status: `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo`
2. Check bot logs: `docker compose logs bot`
3. Verify health: `curl https://your-domain.com/health`
4. Check Nginx logs: `docker compose logs nginx`

### Database Connection Issues

1. Check PostgreSQL: `docker compose exec postgres pg_isready`
2. Verify connection string in `.env.prod`
3. Check PostgreSQL logs: `docker compose logs postgres`

### High Memory Usage

1. Check stats: `docker stats`
2. Restart specific service: `docker compose restart bot`
3. Consider increasing server resources

### SSL Certificate Errors

1. Verify certificate paths in nginx.conf
2. Check certificate validity: `openssl x509 -in docker/nginx/ssl/cert.pem -noout -dates`
3. Renew if expired

---

## Contact

For critical issues, contact the development team immediately.
