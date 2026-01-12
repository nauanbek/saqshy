# syntax=docker/dockerfile:1
# SAQSHY Anti-Spam Bot - Multi-stage Dockerfile
# Build: DOCKER_BUILDKIT=1 docker build -t saqshy-bot --target production -f docker/Dockerfile .
#
# BuildKit secrets usage (secrets won't be in final image):
#   docker build --secret id=pip_token,src=.pip_token -t saqshy-bot .
#   Then in RUN: --mount=type=secret,id=pip_token cat /run/secrets/pip_token

# ============================================
# Frontend build stage - Build Mini App
# ============================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app

# Copy Mini App source
COPY mini_app_frontend/package*.json ./

# Install dependencies
RUN npm ci --ignore-scripts

# Copy source and build
COPY mini_app_frontend/ ./
RUN npm run build

# ============================================
# Build stage - Install Python dependencies
# ============================================
FROM python:3.14-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml ./
COPY README.md ./

# Create wheels for all dependencies
# Use BuildKit secret for private pip index (optional):
#   --mount=type=secret,id=pip_token PIP_INDEX_URL=$(cat /run/secrets/pip_token)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir build wheel && \
    pip wheel --no-cache-dir --wheel-dir /wheels .

# ============================================
# Development stage - For local development
# ============================================
FROM python:3.14-slim AS development

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install wheels
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir /wheels/*.whl && \
    rm -rf /wheels

# Copy source code (will be mounted in development)
COPY . .

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose webhook port
EXPOSE 8080

CMD ["python", "-m", "saqshy"]

# ============================================
# Production stage - Optimized for deployment
# ============================================
FROM python:3.14-slim AS production

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd -r saqshy && useradd -r -g saqshy saqshy

# Copy and install wheels
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir /wheels/*.whl && \
    rm -rf /wheels

# Copy only necessary files
# Note: Alembic migrations are in src/saqshy/db/migrations/
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY alembic.ini ./

# Copy Mini App frontend build from node stage
# Bot serves static files from src/saqshy/static/mini_app/
COPY --from=frontend-builder /app/dist/ ./src/saqshy/static/mini_app/

# Set ownership
RUN chown -R saqshy:saqshy /app

# Switch to non-root user
USER saqshy

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose webhook port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["python", "-m", "saqshy"]
