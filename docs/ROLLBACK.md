# Aifficient — Rollback Procedure

**Version:** Phase 5C  
**Owner:** DevOps / Engineering Lead

---

## When to Roll Back

Roll back when:
- HTTP 5xx error rate > 5% for more than 5 minutes
- Critical data integrity issue identified
- Core feature (campaigns, calls, lead management) is completely broken
- Security vulnerability discovered in newly deployed code

Roll back **decision deadline**: 30 minutes after go-live; after that, prefer a hotfix forward.

---

## 1. Docker Compose Rollback (single-host)

### Pre-conditions

- Previous Docker images are tagged with the git SHA or a version tag
- A DB snapshot was taken before deploying (see Step 0)

### Step 0 — Pre-deployment snapshot (do this BEFORE any deployment)

```bash
# Tag current Docker images before deploying new ones
docker tag aifficient-backend:latest aifficient-backend:$(git rev-parse --short HEAD)-prev
docker tag aifficient-frontend:latest aifficient-frontend:$(git rev-parse --short HEAD)-prev

# Snapshot the database
pg_dump -Fc \
  -U $POSTGRES_USER \
  -h $POSTGRES_HOST \
  $POSTGRES_DB \
  > /backups/pre-deploy-$(date +%Y%m%d-%H%M%S).dump
```

### Step 1 — Stop the failing deployment

```bash
docker compose -f docker-compose.prod.yml down
```

### Step 2 — Restore database (if schema changed)

```bash
# ONLY if the failing migration introduced schema changes
# Restore from pre-deployment snapshot
pg_restore \
  --clean \
  --no-acl \
  --no-owner \
  -d $DATABASE_URL \
  /backups/pre-deploy-YYYYMMDD-HHMMSS.dump
```

To roll back only Alembic migrations (without full restore):

```bash
cd backend
source venv/bin/activate
alembic downgrade -1   # roll back one migration
# Repeat if multiple migrations were applied
alembic current        # confirm target revision
```

### Step 3 — Start previous images

```bash
# Re-tag the previous images as latest
PREV_SHA=$(git rev-parse --short HEAD~1)
docker tag aifficient-backend:${PREV_SHA}-prev aifficient-backend:latest
docker tag aifficient-frontend:${PREV_SHA}-prev aifficient-frontend:latest

# Restart
docker compose -f docker-compose.prod.yml up -d
```

### Step 4 — Verify

```bash
curl https://api.your-domain.com/api/v1/health/ready | jq .
# Expected: {"status": "ok", ...}
```

---

## 2. PM2 (bare metal) Rollback

### Pre-conditions

- Previous release is checked out in a sibling directory (e.g., `/home/ubuntu/aifficient-prev`)
- PM2 is managing all processes

### Step 1 — Stop current processes

```bash
pm2 stop all
```

### Step 2 — Restore database

```bash
# If schema changed:
psql $DATABASE_URL -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
pg_restore --no-acl --no-owner -d $DATABASE_URL /backups/pre-deploy-YYYYMMDD.dump
# Or Alembic downgrade:
cd /home/ubuntu/aifficient-current/backend
alembic downgrade -1
```

### Step 3 — Switch to previous release

```bash
# Stop current symlink
cd /home/ubuntu
mv aifficient-current aifficient-failed
mv aifficient-prev aifficient-current

# Restart from previous release
cd aifficient-current/backend
pm2 start ecosystem.config.cjs
```

### Step 4 — Rebuild and restart frontend

```bash
cd /home/ubuntu/aifficient-current/frontend
npm ci && npm run build
# Restart nginx to serve the old build
sudo nginx -s reload
```

---

## 3. AWS App Runner Rollback

```bash
# List recent deployments
aws apprunner list-operations \
  --service-arn arn:aws:apprunner:REGION:ACCOUNT:service/aifficient/SERVICE_ID

# Re-deploy the previous ECR image tag
aws apprunner start-deployment \
  --service-arn arn:aws:apprunner:REGION:ACCOUNT:service/aifficient/SERVICE_ID

# Or use the App Runner console: Service → Deployments → select previous → Redeploy
```

For RDS rollback, use the AWS Console → RDS → Snapshots → Restore.

---

## 4. Database-only Rollback

If only a migration needs to be reverted (no application code change):

```bash
cd backend
source venv/bin/activate

# Show current state
alembic current

# Roll back one step
alembic downgrade -1

# Roll back to a specific revision
alembic downgrade r4s5t6u7v8w9  # the revision BEFORE the problematic one

# Verify
alembic current
```

**Caution:** Rolling back destructive migrations (DROP TABLE, DROP COLUMN) requires the pre-migration DB snapshot — Alembic's `downgrade` only reverses additive changes.

---

## 5. Post-Rollback Checklist

- [ ] `GET /api/v1/health/ready` returns `{"status": "ok"}`
- [ ] A test login and campaign create works
- [ ] Error rate returns to baseline (< 0.5%)
- [ ] Notify the team that rollback is complete
- [ ] Write an incident report within 24h (what failed, why, timeline, resolution)
- [ ] Create a hotfix branch to address the root cause before re-deploying
- [ ] Add a test to the E2E suite to prevent regression

---

## 6. Rollback Decision Matrix

| Condition | Action |
|-----------|--------|
| Error rate 1–5%, degraded but functional | Monitor for 15 min; hotfix if not recovering |
| Error rate > 5% for > 5 min | Immediate rollback |
| Core feature (campaigns/calls) broken | Immediate rollback |
| Analytics/reporting broken | Hotfix forward (non-blocking) |
| Security vulnerability | Immediate rollback + incident response |
| Performance degraded (P99 > 5s) | Monitor 15 min; rollback if no improvement |
| Single user-reported issue | Investigate; no rollback unless widespread |

---

## 7. Contacts

| Role | Action |
|------|--------|
| On-call Engineer | First responder; executes rollback if authorised |
| Engineering Lead | Authorises rollback decisions |
| Product Manager | Notified when rollback is initiated; communicates to stakeholders |
