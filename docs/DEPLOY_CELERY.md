# Campaign Scheduler (Celery Worker + Beat)

Campaign activation only **enqueues** executions (`status=queued`). Outbound calls are placed by the **Celery scheduler**, which runs `campaign.scheduler_tick` every 60 seconds (configurable via `CAMPAIGN_SCHEDULER_INTERVAL_SECONDS`).

If Celery Worker and/or Beat are not running, campaigns stay `active` but **no telephony calls are created**.

## Architecture

```
Celery Beat  ──every 60s──►  campaign.scheduler_tick  ──►  CampaignScheduler.tick()
                                                                    │
                                                                    ▼
                                                          run_execution() → Twilio dial
```

| Component | Role |
|-----------|------|
| **Redis** | Celery broker + result backend (`REDIS_URL`) |
| **Celery Beat** | Fires `campaign.scheduler_tick` and `campaign.beat_heartbeat` on schedule |
| **Celery Worker** | Executes ticks; dispatches queued executions and places calls |
| **FastAPI** | `POST /campaigns/activate` enqueues only; does not dial |

## Health check

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  https://api.example.com/api/v1/campaigns/scheduler-status | jq
```

Expected when healthy:

```json
{
  "worker_running": true,
  "beat_running": true,
  "redis_connected": true,
  "scheduler_online": true,
  "queued_executions": 0,
  "active_executions": 0,
  "last_scheduler_tick": "2026-06-05T06:45:00+00:00"
}
```

The UI shows an amber banner when `scheduler_online` is `false`.

---

## Docker Compose (development / single host)

From `backend/`:

```bash
docker compose up -d postgres redis
docker compose up -d celery-worker celery-beat
```

Or start everything:

```bash
docker compose up -d
```

Verify:

```bash
docker compose logs -f celery-worker celery-beat
docker compose exec celery-worker celery -A modules.campaign.celery_app:celery_app inspect ping
```

---

## PM2 (production on EC2 / bare metal)

From `backend/` with venv and `.env` in place:

```bash
cd /home/ubuntu/Afficient-ai/backend
source venv/bin/activate
pip install -r requirements.txt

# Start only the scheduler (if API/frontend already run under PM2):
bash scripts/ensure-scheduler.sh

# Or start all backend processes from the ecosystem file:
pm2 start ecosystem.config.cjs
pm2 status
pm2 logs aifficient-celery-worker
pm2 save
pm2 startup   # follow printed command for boot persistence
```

**Important:** `aifficient-backend` and `aifficient-frontend` are not enough. Campaign
activation only enqueues executions; **`aifficient-celery-worker`** and
**`aifficient-celery-beat`** must also be online or calls never dial.

Processes:

| PM2 name | Command |
|----------|---------|
| `aifficient-api` | `uvicorn main:app --host 0.0.0.0 --port 8000` |
| `aifficient-celery-worker` | `celery … worker` |
| `aifficient-celery-beat` | `celery … beat` |

---

## systemd (production)

Copy unit files and enable:

```bash
sudo cp backend/deploy/aifficient-celery-worker.service /etc/systemd/system/
sudo cp backend/deploy/aifficient-celery-beat.service /etc/systemd/system/
# Edit User=, WorkingDirectory=, EnvironmentFile= if paths differ

sudo systemctl daemon-reload
sudo systemctl enable --now aifficient-celery-worker
sudo systemctl enable --now aifficient-celery-beat
sudo systemctl status aifficient-celery-worker aifficient-celery-beat
```

---

## AWS App Runner / container platforms

App Runner runs **one** web process. Run Celery as **separate** services:

1. **ECS Fargate** — two task definitions (worker + beat) using the same `backend/Dockerfile` with different `command`:
   - Worker: `celery -A modules.campaign.celery_app:celery_app worker -l info -Q celery`
   - Beat: `celery -A modules.campaign.celery_app:celery_app beat -l info`
2. Share `DATABASE_URL`, `REDIS_URL`, and telephony env vars via Secrets Manager.
3. Point ElastiCache Redis at `REDIS_URL` / `CELERY_BROKER_URL`.

**Do not** run Beat on more than one instance (duplicate ticks). Scale **workers** horizontally; keep **one** Beat.

---

## Manual one-shot dispatch (debug)

```bash
cd backend && source venv/bin/activate
python -c "
from database.session import SessionLocal
from modules.campaign.scheduler import CampaignScheduler
db = SessionLocal()
print(CampaignScheduler.tick(db))
db.close()
"
```

This does not replace a running Beat/worker in production.

---

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| `queued_executions > 0`, `worker_running: false` | Celery worker not started |
| `beat_running: false` | Celery Beat not started |
| `redis_connected: false` | Redis down or wrong `REDIS_URL` |
| `last_scheduler_tick` stale | Worker crashed mid-tick; check worker logs |
| Activate returns `already_active`, no calls | Scheduler never dispatched; start worker + beat |

Worker logs:

```bash
# PM2
pm2 logs aifficient-celery-worker

# Docker
docker compose logs -f celery-worker

# systemd
journalctl -u aifficient-celery-worker -f
```
