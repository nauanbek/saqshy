# SAQSHY Observability Runbooks

This document contains runbooks for common operational scenarios related to observability, incident response, and monitoring.

## Table of Contents

1. [Log Queries](#log-queries)
2. [False Positive Investigation](#false-positive-investigation)
3. [Spam Wave Detection](#spam-wave-detection)
4. [High Latency Investigation](#high-latency-investigation)
5. [LLM Error Investigation](#llm-error-investigation)
6. [Health Check Troubleshooting](#health-check-troubleshooting)

---

## Log Queries

### Find all decisions for a user

```bash
# In production logs (JSON format)
cat /var/log/saqshy/app.log | jq 'select(.user_id == 123456789)'

# With structlog JSON output
grep '"user_id": 123456789' /var/log/saqshy/app.log | jq .
```

### Find all BLOCK verdicts in the last hour

```bash
cat /var/log/saqshy/app.log | jq 'select(.verdict == "block" and .timestamp > "2024-01-01T00:00:00")'
```

### Find decisions by correlation ID

```bash
# Trace a single request through all services
grep '"correlation_id": "abc12345"' /var/log/saqshy/*.log | jq .
```

### Find high latency decisions (>2s)

```bash
cat /var/log/saqshy/app.log | jq 'select(.total_latency_ms > 2000)'
```

### Find LLM calls

```bash
cat /var/log/saqshy/app.log | jq 'select(.llm_called == true)'
```

---

## False Positive Investigation

### When to Use

- FP rate alert triggered (>10% for deals groups)
- Admin reports legitimate messages being blocked
- User complaints about wrongful bans

### Steps

1. **Query recent FP overrides**

```sql
-- Get FP overrides in last 24 hours
SELECT
    d.id,
    d.group_id,
    g.group_type,
    d.user_id,
    d.risk_score,
    d.verdict,
    d.threat_type,
    d.profile_signals,
    d.content_signals,
    d.behavior_signals,
    d.overridden_by,
    d.override_reason,
    d.created_at
FROM decisions d
JOIN groups g ON d.group_id = g.id
WHERE d.overridden_at IS NOT NULL
  AND d.created_at > NOW() - INTERVAL '24 hours'
ORDER BY d.created_at DESC;
```

2. **Identify common patterns in FP cases**

```sql
-- Group by threat_type to find which detection is causing FPs
SELECT
    threat_type,
    COUNT(*) as fp_count,
    AVG(risk_score) as avg_score
FROM decisions
WHERE overridden_at IS NOT NULL
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY threat_type
ORDER BY fp_count DESC;
```

3. **Check if it's a specific group type issue**

```sql
-- FP rate by group_type
SELECT
    g.group_type,
    COUNT(CASE WHEN d.overridden_at IS NOT NULL THEN 1 END) as overrides,
    COUNT(CASE WHEN d.verdict = 'block' THEN 1 END) as blocks,
    ROUND(
        COUNT(CASE WHEN d.overridden_at IS NOT NULL THEN 1 END)::numeric /
        NULLIF(COUNT(CASE WHEN d.verdict = 'block' THEN 1 END), 0) * 100,
        2
    ) as fp_rate_percent
FROM decisions d
JOIN groups g ON d.group_id = g.id
WHERE d.created_at > NOW() - INTERVAL '24 hours'
GROUP BY g.group_type;
```

4. **Analyze common signals in FP decisions**

```python
# Python script to analyze FP signals
from saqshy.db.repositories.decisions import DecisionRepository

async def analyze_fp_signals(session, group_type: str, days: int = 7):
    repo = DecisionRepository(session)
    fps = await repo.get_false_positives(group_id=None, days=days)  # All groups

    signal_counts = defaultdict(int)
    for fp in fps:
        for signal, value in fp.content_signals.items():
            if value > 0:
                signal_counts[f"content:{signal}"] += 1
        for signal, value in fp.profile_signals.items():
            if value > 0:
                signal_counts[f"profile:{signal}"] += 1

    # Print top signals causing FPs
    for signal, count in sorted(signal_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"{signal}: {count}")
```

5. **Resolution actions**

- **If URL-related FPs in deals groups**: Check `WHITELIST_DOMAINS_DEALS` for missing retailers
- **If profile-related FPs**: Check `PROFILE_WEIGHTS` - may need to reduce weight
- **If content-related FPs**: Review `CRYPTO_SCAM_PHRASES` for over-aggressive patterns
- **If threshold issue**: Adjust group_type thresholds in `THRESHOLDS`

---

## Spam Wave Detection

### When to Use

- `spam_wave_detected` log appears
- Sudden spike in BLOCK verdicts
- Multiple users reporting spam simultaneously

### Steps

1. **Confirm spam wave**

```bash
# Check BLOCK count in last 5 minutes
redis-cli ZCOUNT "saqshy:metrics:spam_wave:general" $(date -d '5 minutes ago' +%s) $(date +%s)
```

2. **Identify attack pattern**

```sql
-- Find messages with highest similarity in spam wave period
SELECT
    d.user_id,
    d.content_signals->>'spam_db_similarity' as similarity,
    d.created_at
FROM decisions d
WHERE d.verdict = 'block'
  AND d.created_at > NOW() - INTERVAL '10 minutes'
ORDER BY d.created_at DESC
LIMIT 100;
```

3. **Check if coordinated attack (same user/IP pattern)**

```sql
-- Users with multiple blocks
SELECT
    user_id,
    COUNT(*) as block_count
FROM decisions
WHERE verdict = 'block'
  AND created_at > NOW() - INTERVAL '10 minutes'
GROUP BY user_id
HAVING COUNT(*) > 3
ORDER BY block_count DESC;
```

4. **Response actions**

- **If real spam wave**: Monitor, the system should handle it automatically
- **If coordinated attack**: Consider adding patterns to spam DB
- **If false wave (scoring regression)**:
  - Check recent code changes
  - Review threshold configuration
  - Consider rollback if needed

5. **Add to spam DB if new pattern**

```python
from saqshy.services.spam_db import SpamDBService

async def add_spam_pattern(text: str, threat_type: str = "spam"):
    spam_db = SpamDBService(...)
    await spam_db.add_pattern(text, threat_type=threat_type, confidence=0.95)
```

---

## High Latency Investigation

### When to Use

- `high_latency_p95` alert triggered (>2s)
- Users reporting slow bot responses
- Pipeline timeout errors increasing

### Steps

1. **Check current latency metrics**

```python
from saqshy.core.metrics import MetricsCollector

async def check_latency(metrics: MetricsCollector, group_type: str):
    stats = await metrics.get_latency_stats(group_type, window_hours=1)
    print(f"p50: {stats['p50_ms']}ms")
    print(f"p95: {stats['p95_ms']}ms")
    print(f"p99: {stats['p99_ms']}ms")
```

2. **Identify slow component**

```bash
# Find decisions with breakdown of component times
cat /var/log/saqshy/app.log | jq 'select(.total_latency_ms > 2000) | {
    correlation_id,
    total: .total_latency_ms,
    profile: .profile_latency_ms,
    content: .content_latency_ms,
    behavior: .behavior_latency_ms,
    spam_db: .spam_db_latency_ms,
    llm: .llm_latency_ms
}'
```

3. **Check LLM if high LLM latency**

```bash
# LLM call stats
cat /var/log/saqshy/app.log | jq 'select(.llm_called == true) | .llm_latency_ms' | sort -n | tail -20
```

4. **Check external service health**

```bash
# Redis latency
redis-cli --latency-history -i 1

# PostgreSQL connection pool
psql -c "SELECT * FROM pg_stat_activity WHERE datname = 'saqshy';"

# Qdrant health
curl http://localhost:6333/health
```

5. **Resolution actions**

- **High LLM latency**:
  - Check Anthropic API status
  - Review LLM call rate - may need to raise gray zone threshold
  - Consider increasing LLM timeout

- **High DB latency**:
  - Check connection pool stats
  - Look for slow queries
  - Consider adding indexes

- **High Redis latency**:
  - Check memory usage
  - Look for large keys
  - Consider connection pool size

---

## LLM Error Investigation

### When to Use

- `llm_error_rate` alert triggered (>5%)
- `llm_call_failed` logs appearing
- Gray zone decisions defaulting to conservative verdicts

### Steps

1. **Check LLM error rate**

```python
from saqshy.core.metrics import MetricsCollector

async def check_llm_errors(metrics: MetricsCollector, group_type: str):
    stats = await metrics.get_llm_stats(group_type, window_hours=1)
    local = metrics._local.get_group_metrics(group_type)

    error_count = local.errors.get("llm_error", 0)
    total_calls = local.llm_calls

    if total_calls > 0:
        error_rate = error_count / total_calls
        print(f"LLM error rate: {error_rate * 100:.2f}%")
```

2. **Find LLM errors in logs**

```bash
cat /var/log/saqshy/app.log | jq 'select(.event == "llm_call_failed")'
```

3. **Check Anthropic API status**

```bash
curl -I https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2024-01-01"
```

4. **Resolution actions**

- **Rate limiting**: Reduce LLM call rate by increasing gray zone thresholds
- **API errors**: Check Anthropic status page, consider backup provider
- **Timeout errors**: Increase LLM timeout, check network connectivity

---

## Health Check Troubleshooting

### Endpoints

- `/health` - Basic liveness (always 200 if service running)
- `/health/ready` - Readiness with dependency checks
- `/health/live` - Kubernetes liveness probe
- `/health/details` - Detailed status for debugging

### Common Issues

1. **Readiness failing - Redis unhealthy**

```bash
# Check Redis connection
redis-cli ping

# Check circuit breaker state
curl http://localhost:8080/health/details | jq '.checks.redis'
```

Resolution:
- Check Redis container/service status
- Verify Redis URL in config
- Check network connectivity

2. **Readiness failing - Database unhealthy**

```bash
# Check PostgreSQL connection
psql -h localhost -U saqshy -c "SELECT 1"

# Check pool status
curl http://localhost:8080/health/details | jq '.checks.database'
```

Resolution:
- Check PostgreSQL container/service status
- Verify database URL in config
- Check connection pool limits

3. **Readiness failing - Qdrant unhealthy**

```bash
# Check Qdrant connection
curl http://localhost:6333/health

# Check collections
curl http://localhost:6333/collections
```

Resolution:
- Check Qdrant container/service status
- Verify Qdrant URL in config
- Check if collections exist

---

## Quick Reference

### Key Log Events

| Event | Level | Description |
|-------|-------|-------------|
| `moderation_decision` | INFO | Every spam decision with full context |
| `event_received` | DEBUG | Incoming Telegram event |
| `event_processed` | DEBUG | Successfully processed event |
| `event_error` | ERROR | Handler exception |
| `pipeline_completed` | INFO | Pipeline finished |
| `pipeline_timeout` | ERROR | Pipeline exceeded timeout |
| `pipeline_error` | ERROR | Unexpected pipeline error |
| `llm_call_failed` | WARNING | LLM API error |
| `spam_wave_detected` | WARNING | Spam wave threshold exceeded |
| `fp_override_recorded` | INFO | Admin approved blocked message |
| `circuit_breaker_opened` | WARNING | Service circuit opened |

### Key Metrics

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| FP rate (deals) | Overrides / Blocks | >10% |
| FP rate (other) | Overrides / Blocks | >20% |
| p95 latency | Processing time | >2000ms |
| LLM error rate | Errors / Calls | >5% |
| Spam wave | Blocks in 5min | >10 |

### Contact Escalation

1. **L1**: Check runbooks, restart services if needed
2. **L2**: Investigate logs, adjust thresholds
3. **L3**: Code changes, infrastructure issues
