#!/usr/bin/env bash
# Ensure Celery worker + Beat are running under PM2 (campaign call scheduler).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v pm2 >/dev/null 2>&1; then
  echo "pm2 not found; install Node.js + pm2 or use systemd units in deploy/" >&2
  exit 1
fi

start_or_restart() {
  local name="$1"
  if pm2 describe "$name" >/dev/null 2>&1; then
    pm2 restart "$name"
  else
    pm2 start ecosystem.config.cjs --only "$name"
  fi
}

start_or_restart aifficient-celery-worker
start_or_restart aifficient-celery-beat
pm2 save

echo "Scheduler processes:"
pm2 status aifficient-celery-worker aifficient-celery-beat
