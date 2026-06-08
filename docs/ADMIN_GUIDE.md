# Aifficient — Administrator Guide

**Version:** Phase 5C | **Audience:** System Administrators, DevOps

---

## 1. System Overview

Aifficient is a multi-tenant SaaS for AI-powered outbound voice campaigns. The platform orchestrates lead outreach via email, LinkedIn, and PSTN phone calls using a node-based workflow engine.

### Architecture at a Glance

```
Browser (React SPA)
       │
       ▼ HTTPS
  nginx / Load Balancer
       │
       ├──▶ FastAPI (uvicorn)   port 8000
       │         │
       │    PostgreSQL 16       port 5432
       │    Redis 7             port 6379
       │
       ├──▶ Celery Worker (campaign execution)
       ├──▶ Celery Beat (scheduler ticker)
       │
       ├──▶ LiveKit (voice rooms)
       ├──▶ Twilio (PSTN outbound)
       ├──▶ ElevenLabs (TTS)
       └──▶ Deepgram (STT)
```

---

## 2. Deployment

### 2a. Docker Compose (recommended for single-host)

```bash
# 1. Clone the repo
git clone https://github.com/your-org/aifficient.git
cd aifficient

# 2. Configure environment
cp backend/.env.example backend/.env
# Edit backend/.env — fill in every CHANGE_ME value
cp frontend/.env.example frontend/.env
# Set VITE_API_URL to your backend API domain

# 3. Build and launch
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

# 4. Verify health
curl https://api.your-domain.com/api/v1/health/ready
```

### 2b. Manual / PM2 (bare metal)

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Apply DB migrations
alembic upgrade head

# Start API (background)
pm2 start ecosystem.config.cjs --only aifficient-backend

# Start Celery (background)
pm2 start ecosystem.config.cjs --only aifficient-celery-worker
pm2 start ecosystem.config.cjs --only aifficient-celery-beat

# Frontend
cd ../frontend
npm ci && npm run build
# Serve dist/ with nginx, Apache, or vite preview
```

### 2c. AWS App Runner

See `docs/DEPLOY_AWS.md` for the full AWS deployment guide.

---

## 3. Environment Variables Reference

See `backend/.env.example` for a fully commented template.

### Critical Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `REDIS_URL` | ✅ | Redis connection string |
| `JWT_SECRET` | ✅ | Min 32 chars; rotate every 90 days |
| `OPENAI_API_KEY` | ✅ (AI calling) | GPT-4o API key |
| `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` | ✅ (PSTN) | Twilio credentials |
| `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` | ✅ (voice) | LiveKit credentials |
| `ENV` | ✅ | `production` in prod (tightens CORS, enables guards) |
| `INTERNAL_SERVICE_TOKEN` | ✅ | Scheduler → API auth; min 32 chars |

---

## 4. Database Management

### Apply Migrations

```bash
cd backend
source venv/bin/activate
alembic upgrade head          # apply all pending migrations
alembic current               # show current revision
alembic history --verbose     # list all migrations
```

### Create a New Migration

```bash
alembic revision --autogenerate -m "describe_your_change"
# Review the generated file in backend/migrations/versions/
# Then apply: alembic upgrade head
```

### Rollback a Migration

```bash
alembic downgrade -1          # roll back one revision
alembic downgrade base        # roll back everything (DESTRUCTIVE)
```

### Backup

```bash
# Snapshot before migrations or deployments
pg_dump -Fc -U $POSTGRES_USER -h $POSTGRES_HOST $POSTGRES_DB > backup_$(date +%Y%m%d_%H%M%S).dump

# Restore
pg_restore -d $DATABASE_URL --clean backup_YYYYMMDD_HHMMSS.dump
```

---

## 5. Service Management

### Health Checks

```bash
# Liveness (process alive?)
curl http://localhost:8000/api/v1/health

# Readiness (DB + Redis + scheduler OK?)
curl http://localhost:8000/api/v1/health/ready | jq .

# Prometheus metrics
curl http://localhost:8000/metrics
```

### Celery

```bash
# Check worker is alive
celery -A modules.campaign.scheduler inspect ping

# Check registered tasks
celery -A modules.campaign.scheduler inspect registered

# Check active tasks
celery -A modules.campaign.scheduler inspect active

# Check queue depth
redis-cli -u $REDIS_URL LLEN celery

# Purge all tasks (DESTRUCTIVE)
celery -A modules.campaign.scheduler purge
```

### Log Inspection

```bash
# Docker
docker compose -f docker-compose.prod.yml logs --tail=100 -f backend

# PM2
pm2 logs aifficient-backend --lines 100

# JSON log search (jq)
pm2 logs aifficient-backend --raw | jq 'select(.level == "error")'
```

---

## 6. User & Organisation Management

All user management is via the API (no admin UI yet).

### Register First Admin

```bash
curl -X POST https://api.your-domain.com/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "Admin User",
    "email": "admin@your-org.com",
    "password": "StrongPassword123!",
    "organization": "Your Organisation"
  }'
```

### Invite a Team Member

Use the Members page in the UI, or via API:

```bash
curl -X POST https://api.your-domain.com/api/v1/members/invite \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "new.user@your-org.com", "role": "agent"}'
```

### Available Roles

| Role | Permissions |
|------|-------------|
| `owner` | Full access; can delete org, manage billing |
| `admin` | Full access; cannot delete org |
| `agent` | Campaign/lead management; no member management |
| `member` | Read-only access |

---

## 7. Rate Limiting

Limits are per authenticated user (JWT sub), falling back to client IP.

| Bucket | Default Limit | Env Var |
|--------|--------------|---------|
| General API | 300 req/60s | `RATE_LIMIT_REQUESTS` |
| Auth (login/register/refresh) | 10 req/60s | `RATE_LIMIT_AUTH_REQUESTS` |
| AI inference (generate/converse) | 30 req/60s | `RATE_LIMIT_AI_REQUESTS` |
| Telephony calls | 60 req/60s | `RATE_LIMIT_TELEPHONY_REQUESTS` |
| Campaign activation | 20 req/60s | `RATE_LIMIT_CAMPAIGN_ACTIVATE_REQUESTS` |

To disable entirely (for load testing): `RATE_LIMIT_ENABLED=false`.

---

## 8. Monitoring & Alerts

### Metrics (Prometheus)

Key metrics to alert on:

| Metric | Alert Condition |
|--------|----------------|
| `http_requests_total{status=~"5.."}` | Rate > 1% for 5 min |
| `http_request_duration_seconds{quantile="0.99"}` | > 2s for 5 min |
| `celery_task_failure_rate` | > 5% for 10 min |
| Redis memory usage | > 80% capacity |
| PostgreSQL connection pool | > 90% utilised |

### Structured Log Fields

All backend logs are JSON (when `LOG_JSON=true`) with:

```json
{
  "timestamp": "2026-06-08T07:30:00Z",
  "level": "info",
  "event": "app.startup",
  "request_id": "abc123",
  "method": "POST",
  "path": "/api/v1/campaigns"
}
```

Filter errors: `jq 'select(.level == "error" or .level == "critical")'`

---

## 9. Security Hardening Checklist

- [ ] `JWT_SECRET` rotated (requires users to log in again)
- [ ] DB password strong (≥ 24 chars, alphanumeric + symbols)
- [ ] Redis password set (`requirepass` in redis.conf) if exposed beyond localhost
- [ ] Firewall: only 443 (HTTPS) open to public; DB/Redis/Celery on internal network only
- [ ] Twilio webhook signature validation enabled (`TWILIO_VALIDATE_SIGNATURE=true`)
- [ ] Review CORS allowed origins — use exact list in production, not regex
- [ ] API keys stored in secrets manager, not `.env` file on disk in production

---

## 10. Scheduled Maintenance

### Weekly
- Review error logs for recurring issues
- Check Celery queue depth (should drain between campaigns)
- Verify DB backup is current

### Monthly
- Rotate `JWT_SECRET` if required by security policy
- Review and apply any dependency security updates
- Review Prometheus alerts for drift

### Quarterly
- Full DR drill: restore DB from backup to staging
- Rotate Twilio / OpenAI / ElevenLabs / Deepgram API keys
- Review rate-limit settings against actual usage patterns
