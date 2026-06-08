# Aifficient — Troubleshooting Guide

**Version:** Phase 5C | **Audience:** Engineers, DevOps

---

## Quick Diagnostics

```bash
# 1. Is the API alive?
curl http://localhost:8000/api/v1/health

# 2. Are all services ready?
curl http://localhost:8000/api/v1/health/ready | jq .

# 3. Are workers running?
celery -A modules.campaign.scheduler inspect ping

# 4. What's in the Redis queue?
redis-cli -u $REDIS_URL LLEN celery

# 5. Any recent errors?
pm2 logs aifficient-backend --lines 50 | grep '"level":"error"'
# or Docker:
docker compose logs --tail=100 backend | grep '"level":"error"'
```

---

## 1. Backend Won't Start

### Symptom: `alembic upgrade head` fails

**Cause:** Database not running, wrong `DATABASE_URL`, or migration conflict.

```bash
# Check DB is running
pg_isready -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER

# Check the URL
echo $DATABASE_URL

# View migration history
alembic history --verbose

# Check current head
alembic current
```

**Fix:** Apply migrations sequentially: `alembic upgrade +1` to identify the failing revision.

---

### Symptom: `ImportError` or `ModuleNotFoundError` on startup

**Cause:** Missing dependency or wrong Python environment.

```bash
which python3  # should point to .venv
pip list | grep fastapi
pip install -r requirements.txt
```

---

### Symptom: `JWT_SECRET is missing or shorter than 32 chars` in logs

**Cause:** `.env` not loaded or `JWT_SECRET` not set.

```bash
cat backend/.env | grep JWT_SECRET
# Must be ≥ 32 characters
```

---

### Symptom: `CORS error` in browser console

**Cause:** `ENV` is not `production` and `allow_origin_regex` is too permissive, OR in production the frontend domain is not in `allow_origins`.

**Fix:** Ensure `ENV=production` in the backend `.env`. Add your frontend domain to `allow_origins` in `main.py`.

---

## 2. Database Issues

### Symptom: `sqlalchemy.exc.OperationalError: could not connect to server`

**Check:**
```bash
# Is Postgres running?
docker compose ps postgres
# or
systemctl status postgresql

# Can the app user connect?
psql -U $POSTGRES_USER -h $POSTGRES_HOST -d $POSTGRES_DB -c "SELECT 1"
```

**Fix:** Start PostgreSQL, verify credentials in `.env`, check firewall rules.

---

### Symptom: Slow API responses on campaign/execution endpoints

**Cause:** Missing indexes on `executions` table (Phase 5B fix).

```bash
# Verify indexes exist
psql $DATABASE_URL -c "\di executions*"
# Should include ix_executions_workflow_id, ix_executions_status, etc.

# If missing, apply the Phase 5B migration
alembic upgrade s5t6u7v8w9x0
```

---

### Symptom: `could not serialize access due to concurrent update`

**Cause:** High concurrency on the same execution rows during bulk campaign dispatch.

**Fix:** Celery worker concurrency is set to 2 (PM2 default) or 4 (Docker Compose). Reduce `--concurrency` if contention is high.

---

## 3. Redis Issues

### Symptom: `redis.exceptions.ConnectionError`

```bash
redis-cli -u $REDIS_URL ping  # should return PONG
```

**Fix:** Start Redis (`docker compose up redis -d`) and verify `REDIS_URL` in `.env`.

---

### Symptom: Rate limiter always blocking (429 on all requests)

**Cause:** Redis rate-limit keys stuck after non-atomic INCR+EXPIRE (pre-Phase 5B). Now using Lua script — but old keys may linger.

```bash
# Flush all rl:* keys (resets all rate limit buckets)
redis-cli -u $REDIS_URL --scan --pattern "rl:*" | xargs redis-cli -u $REDIS_URL DEL
```

---

### Symptom: `maxmemory` limit hit — Redis evicting keys

**Check:**
```bash
redis-cli -u $REDIS_URL INFO memory | grep used_memory_human
```

**Fix:** Increase `maxmemory` in redis.conf or Redis container env. The `allkeys-lru` policy evicts least-recently-used keys when full — rate-limit and session keys may be evicted under pressure.

---

## 4. Celery Issues

### Symptom: Campaigns are scheduled but leads are never dialled

**Check:**
```bash
# Is beat running?
pm2 show aifficient-celery-beat

# Is worker running?
celery -A modules.campaign.scheduler inspect ping

# Any tasks in queue?
redis-cli -u $REDIS_URL LLEN celery
```

**Fix:** Start both `celery-worker` and `celery-beat`. Only ONE beat instance should run at a time.

---

### Symptom: `[ERROR/MainProcess] Received unregistered task`

**Cause:** Celery worker started from the wrong directory or with the wrong app module.

```bash
cd backend
source venv/bin/activate
celery -A modules.campaign.scheduler worker -l info
```

---

### Symptom: Beat is running but scheduler-status shows `scheduler_online: false`

**Check:** The scheduler stores its last tick in Redis. If the Redis key expired or Beat is lagging:

```bash
redis-cli -u $REDIS_URL GET "campaign:scheduler:last_tick"
```

**Fix:** Restart `celery-beat`. If the issue persists, check Beat's logs for errors.

---

### Symptom: `Event loop is closed` errors in Celery worker logs

**Cause:** The AI agent (LiveKit/STT/TTS) uses async clients that are bound to the event loop. When `CAMPAIGN_DISPATCH_VIA_HTTP=false`, the scheduler tries to run async code in Celery's sync context.

**Fix:** Keep `CAMPAIGN_DISPATCH_VIA_HTTP=true` (the default). This routes calls through FastAPI's event loop instead of running them inline in Celery.

---

## 5. Twilio / Telephony Issues

### Symptom: Outbound calls not initiated

**Check:**
1. `CAMPAIGN_TELEPHONY_DIALING_ENABLED=true` in `.env`
2. `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` are valid
3. `TWILIO_PHONE_NUMBER` is a real Twilio number
4. `TWILIO_PUBLIC_BASE_URL` is reachable from Twilio's cloud (must be HTTPS)

```bash
# Verify Twilio creds
curl -X POST https://api.twilio.com/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/Calls.json \
  --data-urlencode "Url=http://demo.twilio.com/docs/voice.xml" \
  --data-urlencode "To=+15005550006" \
  --data-urlencode "From=$TWILIO_PHONE_NUMBER" \
  -u "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN"
```

---

### Symptom: `403 Forbidden` on Twilio webhooks

**Cause:** Signature validation is failing. Check that:
- `TWILIO_AUTH_TOKEN` matches the token in the Twilio console
- Your reverse proxy is forwarding the original `Host` header (needed for signature validation)
- `TWILIO_PUBLIC_BASE_URL` matches the URL Twilio is calling

**Temporary bypass (dev only):** `TWILIO_VALIDATE_SIGNATURE=false` — NEVER in production.

---

### Symptom: Voicemail upload fails with "unsupported audio format"

**Fix:**
- Ensure the file is a real audio file (not renamed `.txt` or `.html`)
- Supported formats: `mp3, wav, ogg, aac` (configured in `VOICEMAIL_ALLOWED_FORMATS`)
- Maximum file size: 5 MB (`VOICEMAIL_MAX_BYTES`)

---

## 6. AI / LLM Issues

### Symptom: `openai.RateLimitError` in logs

**Cause:** OpenAI API rate limit hit. The backend has per-turn retry with backoff (`AI_TURN_MAX_ATTEMPTS=3`).

**Fix:**
- Upgrade your OpenAI tier / request quota increase
- Reduce `RATE_LIMIT_AI_REQUESTS` to limit AI calls per user

---

### Symptom: `openai.AuthenticationError`

**Fix:** Verify `OPENAI_API_KEY` is valid and not expired. Generate a new key at `https://platform.openai.com/api-keys`.

---

### Symptom: AI agent response is very slow (> 5s)

**Check:**
- `OPENAI_TIMEOUT_SECONDS` (default 30s)
- `AI_TURN_TIMEOUT_SECONDS` (default 12s per turn)
- Network latency to OpenAI API

**Fix:** Use `gpt-4o-mini` for lower latency (change `OPENAI_MODEL=gpt-4o-mini`), or deploy in a region closer to OpenAI's servers.

---

## 7. Frontend Issues

### Symptom: White screen on navigation (no error message)

**Cause (pre-Phase 5B):** A render error crashed the entire app. Now caught by `ErrorBoundary`.

**With Phase 5B:** You should see a "Something went wrong" page with a "Try again" button.

**Debug:** Open browser DevTools → Console. The `ErrorBoundary` logs the full error.

---

### Symptom: API calls return `401 Unauthorized`

**Cause:** JWT expired. The frontend should auto-refresh using the refresh token.

**Fix:** Log out and back in. If auto-refresh is failing, check `JWT_EXPIRE_MINUTES` and that `VITE_API_URL` points to the correct backend.

---

### Symptom: `CORS error` in browser console on API calls

**Fix:** Ensure `VITE_API_URL` matches the backend origin exactly (protocol + domain + port). Check the backend's allowed origins in `main.py`.

---

### Symptom: Build fails with TypeScript errors in WorkflowBuilder.tsx

**Cause:** Pre-existing TypeScript errors in `WorkflowBuilder.tsx` (tracked debt, not new). These do not affect runtime.

**Fix (temporary):** The CI pipeline has `continue-on-error: true` on the TypeScript check. The Vite build succeeds regardless.

---

## 8. Performance Issues

### Symptom: `GET /api/v1/campaigns/{id}/monitor` is slow

**Cause:** Large execution table without indexes.

**Fix:** Apply Phase 5B migration:
```bash
alembic upgrade s5t6u7v8w9x0
```
This adds `ix_executions_workflow_id` and `ix_executions_status`.

---

### Symptom: Analytics queries time out on large datasets

**Fix:** The Phase 5B migration adds composite indexes on `lead_activities` and `campaigns.created_at`. Apply the migration and run `ANALYZE` on the DB:

```sql
ANALYZE executions;
ANALYZE lead_activities;
ANALYZE campaigns;
```

---

## 9. Getting Help

1. Check this guide first
2. Search the structured logs with `jq 'select(.event == "your_error_event")'`
3. Check the `X-Request-ID` header from the failing request and grep logs for that ID
4. Review `KNOWLEDGE.md` for architecture context
5. Open a ticket with: request_id, timestamp, error message, and steps to reproduce
