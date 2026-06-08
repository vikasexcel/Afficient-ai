# Aifficient — Production Launch Checklist

**Version:** Phase 5C  
**Date:** 2026-06-08  
**Owner:** Engineering

Mark each item ✅ before go-live. Items marked ⚠️ are BLOCKING.

---

## 1. Infrastructure ⚠️

- [ ] ⚠️ PostgreSQL 16 running, accessible, persistent storage attached
- [ ] ⚠️ Redis 7 running, `maxmemory-policy allkeys-lru` set
- [ ] ⚠️ Celery worker process running (`celery worker`)
- [ ] ⚠️ Celery beat process running (`celery beat`) — exactly ONE instance
- [ ] ⚠️ FastAPI / uvicorn running and responding on configured port
- [ ] ⚠️ Frontend built and served (nginx or CDN)
- [ ] LiveKit server/cloud configured with SIP trunk
- [ ] Twilio account configured with webhook URLs pointing to production domain

## 2. Database ⚠️

- [ ] ⚠️ `alembic upgrade head` executed with zero errors on production DB
- [ ] ⚠️ Latest migration `s5t6u7v8w9x0_phase5b_indexes_hardening` is applied
- [ ] ⚠️ Automated database backups enabled and tested (restore drill completed)
- [ ] Point-in-time recovery (PITR / WAL archival) configured
- [ ] DB connection pooling tuned (max_connections ≥ 100 for the app + Celery)

## 3. Secrets & Configuration ⚠️

- [ ] ⚠️ `backend/.env` contains NO placeholder values (CHANGE_ME not present)
- [ ] ⚠️ `JWT_SECRET` is ≥ 32 characters, randomly generated (`openssl rand -hex 32`)
- [ ] ⚠️ `INTERNAL_SERVICE_TOKEN` is ≥ 32 characters, different from `JWT_SECRET`
- [ ] ⚠️ `TWILIO_VALIDATE_SIGNATURE=true`
- [ ] ⚠️ `ENV=production` (enables strict CORS, JSON logging, production guards)
- [ ] ⚠️ `LOG_JSON=true` (structured logs for aggregator)
- [ ] API keys rotated after any accidental commit to version control
- [ ] `.env` file is NOT committed to git (confirm with `git status`)
- [ ] `.env.example` is committed with all real values redacted

## 4. Security ⚠️

- [ ] ⚠️ HTTPS enforced end-to-end (TLS termination at load balancer / nginx)
- [ ] ⚠️ HTTP → HTTPS redirect configured
- [ ] ⚠️ CORS `allow_origin_regex` disabled (`ENV=production` does this automatically)
- [ ] ⚠️ `RATE_LIMIT_ENABLED=true`
- [ ] Security headers set (X-Frame-Options, X-Content-Type-Options, CSP)
- [ ] `TWILIO_ACCOUNT_SID` is NOT a dummy placeholder
- [ ] Admin user created and OWNER role verified
- [ ] Default/test accounts removed from production DB

## 5. Health Checks ⚠️

- [ ] ⚠️ `GET /api/v1/health` returns `200 {"status":"ok"}`
- [ ] ⚠️ `GET /api/v1/health/ready` returns `200 {"status":"ok"}` with all checks green
  - [ ] `checks.postgres.status == "ok"`
  - [ ] `checks.redis.status == "ok"`
  - [ ] `checks.scheduler.status == "ok"` (or "degraded" if Celery not used)
- [ ] Load balancer / container orchestrator health-check pointed at `/api/v1/health`
- [ ] Readiness probe pointed at `/api/v1/health/ready`

## 6. Observability

- [ ] `GET /metrics` returns Prometheus text format
- [ ] Prometheus (or Datadog / CloudWatch agent) scraping `/metrics` every 15s
- [ ] Grafana dashboard imported (request rate, latency P99, error rate, queue depth)
- [ ] Log aggregator (CloudWatch Logs / Loki / Datadog) receiving structured JSON logs
- [ ] Alerts configured:
  - [ ] HTTP 5xx rate > 1% → page on-call
  - [ ] DB connection failures → page on-call
  - [ ] Redis memory > 80% → alert
  - [ ] Celery queue depth > 500 → alert
  - [ ] Scheduler last tick > 5 min ago → alert

## 7. Domain & SSL

- [ ] DNS A records pointing to production servers
- [ ] TLS certificate issued (Let's Encrypt / ACM) and auto-renewal configured
- [ ] Certificate expiry monitoring configured
- [ ] Webhook URLs in Twilio dashboard updated to production HTTPS endpoints:
  - [ ] Voice webhook: `https://api.your-domain.com/api/v1/telephony/webhooks/voice`
  - [ ] Status webhook: `https://api.your-domain.com/api/v1/telephony/webhooks/status`
  - [ ] AMD webhook: `https://api.your-domain.com/api/v1/telephony/webhooks/amd-status`

## 8. End-to-End Tests

- [ ] `pytest tests/e2e/test_campaign_lifecycle.py` passes against staging
- [ ] Scenario 1 (Full Lifecycle) — PASS
- [ ] Scenario 2 (Email → Wait → Call) — PASS
- [ ] Scenario 3 (LinkedIn → Condition) — PASS
- [ ] Scenario 4 (Retry + Failure Handling) — PASS
- [ ] Cross-tenant isolation tests — PASS
- [ ] Rate limiting tests — PASS

## 9. Performance

- [ ] Load test at 1,000 leads/campaign completed without error rate > 0.5%
- [ ] P99 API latency < 500 ms under normal load
- [ ] DB query plan reviewed for `executions` table (indexes applied via migration)
- [ ] Celery worker concurrency tuned for expected call volume

## 10. Rollback Readiness

- [ ] Previous Docker image/release tagged and available in registry
- [ ] Rollback procedure documented and tested (see `docs/ROLLBACK.md`)
- [ ] DB snapshot taken immediately before go-live
- [ ] Rollback decision criteria agreed (e.g. > 5% error rate for > 5 min)

## 11. Communications

- [ ] Internal team notified of go-live time
- [ ] Support team briefed on known issues list
- [ ] Maintenance window communicated to early-access users (if any)
- [ ] On-call rotation active for first 48 hours post-launch

---

## Signoff

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Engineering Lead | | | |
| QA Lead | | | |
| DevOps / Infra | | | |
| Product Manager | | | |
