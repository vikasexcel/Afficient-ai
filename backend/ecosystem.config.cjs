/**
 * PM2 process definitions for production (bare-metal / EC2).
 *
 * Start everything:
 *   cd backend && pm2 start ecosystem.config.cjs
 *
 * Start only the campaign scheduler (worker + beat):
 *   pm2 start ecosystem.config.cjs --only aifficient-celery-worker,aifficient-celery-beat
 *
 * Persist across reboots:
 *   pm2 save && pm2 startup
 */
module.exports = {
  apps: [
    {
      name: "aifficient-backend",
      cwd: __dirname,
      script: "/usr/bin/bash",
      args: "-lc 'source venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8000'",
      interpreter: "none",
      max_restarts: 10,
      autorestart: true,
      restart_delay: 5000,
    },
    {
      name: "aifficient-celery-worker",
      cwd: __dirname,
      script: "/usr/bin/bash",
      args:
        "-lc 'source venv/bin/activate && celery -A modules.campaign.celery_app:celery_app worker -l info -Q celery --concurrency=2'",
      interpreter: "none",
      max_restarts: 10,
      autorestart: true,
      restart_delay: 5000,
    },
    {
      name: "aifficient-celery-beat",
      cwd: __dirname,
      script: "/usr/bin/bash",
      args:
        "-lc 'source venv/bin/activate && celery -A modules.campaign.celery_app:celery_app beat -l info'",
      interpreter: "none",
      max_restarts: 10,
      autorestart: true,
      restart_delay: 5000,
    },
  ],
};
