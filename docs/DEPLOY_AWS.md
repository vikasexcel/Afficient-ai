# Complete AWS Deployment Guide — Aifficient

Follow these phases in order. Roughly 2–3 hours start to finish.

---

## What needs to be hosted

| Piece | Tech | AWS service |
|-------|------|-------------|
| Frontend | Vite + React (`frontend/`) | S3 + CloudFront |
| Backend API | FastAPI / uvicorn (`backend/`, has `Dockerfile`) | App Runner |
| Container image | Docker | ECR |
| PostgreSQL | Postgres 16 | RDS |
| Redis | Redis 7 | ElastiCache |
| LiveKit | WebRTC | **LiveKit Cloud** (recommended; not App Runner) |
| Secrets | JWT, SMTP, ElevenLabs, etc. | Secrets Manager |
| DNS / TLS | Custom domain | Route 53 + ACM |

**Important:** Self-hosting LiveKit on AWS requires EC2 with UDP open. Use **LiveKit Cloud** unless you have a specific reason not to.

---

## Phase 0 — Prerequisites & cleanup

### 0.1 Tools to install locally

- AWS CLI v2 → `aws --version`
- Docker Desktop (with `buildx`) → `docker buildx version`
- Node 20+ and Python 3.12
- `jq` (optional, for parsing AWS output)

### 0.2 AWS account setup

1. Create / log into your AWS account.
2. **Create an IAM user** (don't use root):
   - IAM → Users → Create user → name: `deploy-aifficient`
   - Permissions → attach: `AdministratorAccess` (scope down later)
   - Create access keys → download CSV
3. Configure CLI:

   ```bash
   aws configure
   # paste access key, secret, region (e.g. ap-south-1), output: json
   ```

4. Verify:

   ```bash
   aws sts get-caller-identity
   ```

### 0.3 Pick a region

For India: `ap-south-1` (Mumbai). For US: `us-east-1`. **Use one region for everything.**

```bash
export AWS_REGION=ap-south-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

### 0.4 Critical: rotate leaked secrets

Your `backend/.env` may contain live secrets in git. **Rotate before deploying:**

| Secret | Where to rotate |
|--------|-----------------|
| `ELEVENLABS_API_KEY` | elevenlabs.io → Profile → API Keys |
| `SMTP_PASSWORD` (Gmail app password) | Google Account → Security → 2-Step → App passwords |
| `JWT_SECRET` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `LIVEKIT_API_SECRET` | LiveKit Cloud dashboard |

Also ensure `backend/.env` is in `.gitignore` and never committed with real values.

### 0.5 Sign up for LiveKit Cloud

1. https://cloud.livekit.io → create account → create a project
2. Note:
   - `LIVEKIT_URL` (e.g. `wss://yourproject-xxxx.livekit.cloud`)
   - `LIVEKIT_API_KEY`
   - `LIVEKIT_API_SECRET`

Free tier is enough for development.

---

## Phase 1 — Networking (VPC)

App Runner needs private access to RDS and ElastiCache. Use the **default VPC** for simplicity.

### 1.1 Get default VPC + subnets

```bash
export VPC_ID=$(aws ec2 describe-vpcs \
  --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)

export SUBNET_IDS=$(aws ec2 describe-subnets \
  --filters Name=vpc-id,Values=$VPC_ID \
  --query 'Subnets[].SubnetId' --output text)

echo $VPC_ID
echo $SUBNET_IDS
```

### 1.2 Create security groups

```bash
# App Runner VPC connector
APP_SG=$(aws ec2 create-security-group \
  --group-name aifficient-apprunner \
  --description "App Runner outbound" \
  --vpc-id $VPC_ID --query GroupId --output text)

# RDS
DB_SG=$(aws ec2 create-security-group \
  --group-name aifficient-rds \
  --description "RDS Postgres" \
  --vpc-id $VPC_ID --query GroupId --output text)

# ElastiCache
REDIS_SG=$(aws ec2 create-security-group \
  --group-name aifficient-redis \
  --description "ElastiCache Redis" \
  --vpc-id $VPC_ID --query GroupId --output text)

# Allow App Runner -> RDS (5432)
aws ec2 authorize-security-group-ingress \
  --group-id $DB_SG --protocol tcp --port 5432 --source-group $APP_SG

# Allow App Runner -> Redis (6379)
aws ec2 authorize-security-group-ingress \
  --group-id $REDIS_SG --protocol tcp --port 6379 --source-group $APP_SG

echo "APP_SG=$APP_SG"
echo "DB_SG=$DB_SG"
echo "REDIS_SG=$REDIS_SG"
```

Save these IDs for later steps.

---

## Phase 2 — Database (RDS PostgreSQL)

### 2.1 Create RDS instance

```bash
export DB_PASSWORD='REPLACE_WITH_STRONG_PASSWORD'

aws rds create-db-instance \
  --db-instance-identifier aifficient-db \
  --engine postgres --engine-version 16 \
  --db-instance-class db.t4g.micro \
  --allocated-storage 20 --storage-type gp3 \
  --master-username admin --master-user-password "$DB_PASSWORD" \
  --db-name aifficient \
  --vpc-security-group-ids $DB_SG \
  --backup-retention-period 7 \
  --no-publicly-accessible \
  --storage-encrypted
```

### 2.2 Wait and get endpoint

```bash
aws rds wait db-instance-available --db-instance-identifier aifficient-db

export DB_HOST=$(aws rds describe-db-instances \
  --db-instance-identifier aifficient-db \
  --query 'DBInstances[0].Endpoint.Address' --output text)

echo $DB_HOST
```

Connection string:

```
postgresql+psycopg2://admin:<DB_PASSWORD>@<DB_HOST>:5432/aifficient
```

---

## Phase 3 — Redis (ElastiCache)

```bash
aws elasticache create-cache-cluster \
  --cache-cluster-id aifficient-redis \
  --engine redis --engine-version 7.1 \
  --cache-node-type cache.t4g.micro \
  --num-cache-nodes 1 \
  --security-group-ids $REDIS_SG \
  --transit-encryption-enabled
```

Wait (~5 min):

```bash
aws elasticache wait cache-cluster-available --cache-cluster-id aifficient-redis

export REDIS_HOST=$(aws elasticache describe-cache-clusters \
  --cache-cluster-id aifficient-redis --show-cache-node-info \
  --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' --output text)

echo $REDIS_HOST
```

Connection string (TLS enabled):

```
rediss://<REDIS_HOST>:6379/0
```

---

## Phase 4 — Build & push backend image (ECR)

### 4.1 Create ECR repo

```bash
aws ecr create-repository --repository-name aifficient-backend
```

### 4.2 Log Docker into ECR

```bash
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS \
      --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```

### 4.3 Build & push

From the repo root:

```bash
cd backend

docker buildx build --platform linux/amd64 \
  -t $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/aifficient-backend:latest \
  --push .
```

`--platform linux/amd64` is required on Apple Silicon — App Runner runs x86.

---

## Phase 5 — Secrets Manager

### 5.1 Create secret JSON

Create `aifficient-env.json` locally (do not commit). Replace all placeholders:

```json
{
  "ENV": "production",
  "LOG_LEVEL": "INFO",
  "LOG_JSON": "true",

  "DATABASE_URL": "postgresql+psycopg2://admin:<DB_PASSWORD>@<DB_HOST>:5432/aifficient",
  "REDIS_URL": "rediss://<REDIS_HOST>:6379/0",

  "JWT_SECRET": "<new strong hex>",
  "JWT_ALGORITHM": "HS256",
  "JWT_EXPIRE_MINUTES": "60",

  "SMTP_HOST": "smtp.gmail.com",
  "SMTP_PORT": "587",
  "SMTP_USER": "<rotated>",
  "SMTP_PASSWORD": "<rotated>",
  "SMTP_FROM_NAME": "Aifficient",
  "APP_LOGIN_URL": "https://app.yourdomain.com/login",

  "LIVEKIT_URL": "wss://<your>.livekit.cloud",
  "LIVEKIT_API_KEY": "<new>",
  "LIVEKIT_API_SECRET": "<new>",
  "LIVEKIT_TOKEN_TTL_MINUTES": "60",
  "LIVEKIT_DEFAULT_EMPTY_TIMEOUT": "300",
  "LIVEKIT_DEFAULT_MAX_PARTICIPANTS": "20",

  "ELEVENLABS_API_KEY": "<new>",
  "ELEVENLABS_VOICE_ID": "ErXwobaYiN019PkySvjV",
  "ELEVENLABS_MODEL_ID": "eleven_turbo_v2_5",
  "ELEVENLABS_SAMPLE_RATE": "24000",
  "ELEVENLABS_AGENT_IDENTITY": "ai-agent",
  "ELEVENLABS_AGENT_NAME": "AI Agent"
}
```

### 5.2 Upload to Secrets Manager

```bash
aws secretsmanager create-secret \
  --name aifficient/backend/env \
  --secret-string file://aifficient-env.json

export SECRET_ARN=$(aws secretsmanager describe-secret \
  --secret-id aifficient/backend/env \
  --query ARN --output text)
echo $SECRET_ARN
```

Delete the local `aifficient-env.json` after upload.

---

## Phase 6 — Run database migrations

Run from your laptop **before** starting App Runner.

### Option A — Temporarily enable public RDS access

```bash
aws rds modify-db-instance \
  --db-instance-identifier aifficient-db \
  --publicly-accessible --apply-immediately
aws rds wait db-instance-available --db-instance-identifier aifficient-db

MY_IP=$(curl -s ifconfig.me)
aws ec2 authorize-security-group-ingress \
  --group-id $DB_SG --protocol tcp --port 5432 --cidr ${MY_IP}/32

cd backend
DATABASE_URL="postgresql+psycopg2://admin:$DB_PASSWORD@$DB_HOST:5432/aifficient" \
  alembic upgrade head

aws ec2 revoke-security-group-ingress \
  --group-id $DB_SG --protocol tcp --port 5432 --cidr ${MY_IP}/32
aws rds modify-db-instance \
  --db-instance-identifier aifficient-db \
  --no-publicly-accessible --apply-immediately
```

### Option B — Bastion EC2

Run a small EC2 in the same VPC, SSH in, install deps, run `alembic upgrade head`.

---

## Phase 7 — Backend service (App Runner)

### 7.1 IAM roles

**ECR access role:**

```bash
cat > apprunner-access-trust.json <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"build.apprunner.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF

aws iam create-role --role-name AppRunnerECRAccessRole \
  --assume-role-policy-document file://apprunner-access-trust.json
aws iam attach-role-policy --role-name AppRunnerECRAccessRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess

export ACCESS_ROLE_ARN=$(aws iam get-role --role-name AppRunnerECRAccessRole --query Role.Arn --output text)
```

**Instance role (reads Secrets Manager):**

```bash
cat > apprunner-instance-trust.json <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"tasks.apprunner.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF

aws iam create-role --role-name AppRunnerInstanceRole \
  --assume-role-policy-document file://apprunner-instance-trust.json

cat > apprunner-secrets-policy.json <<EOF
{"Version":"2012-10-17","Statement":[
  {"Effect":"Allow","Action":["secretsmanager:GetSecretValue"],"Resource":"$SECRET_ARN"}
]}
EOF

aws iam put-role-policy --role-name AppRunnerInstanceRole \
  --policy-name ReadAifficientSecrets \
  --policy-document file://apprunner-secrets-policy.json

export INSTANCE_ROLE_ARN=$(aws iam get-role --role-name AppRunnerInstanceRole --query Role.Arn --output text)
```

### 7.2 VPC connector

```bash
SUBNET_ARGS=$(echo $SUBNET_IDS | tr ' ' ',')

aws apprunner create-vpc-connector \
  --vpc-connector-name aifficient-vpc \
  --subnets $SUBNET_ARGS \
  --security-groups $APP_SG

export VPC_CONNECTOR_ARN=$(aws apprunner list-vpc-connectors \
  --query "VpcConnectors[?VpcConnectorName=='aifficient-vpc'].VpcConnectorArn | [0]" --output text)
```

### 7.3 Create App Runner service (Console recommended)

AWS Console → **App Runner → Create service**:

| Setting | Value |
|---------|-------|
| Source | Container registry → ECR → `aifficient-backend:latest` |
| Deployment trigger | Automatic |
| ECR access role | `AppRunnerECRAccessRole` |
| Service name | `aifficient-backend` |
| vCPU / Memory | 0.5 vCPU / 1 GB |
| Port | `8000` |
| Environment variables | Reference → Secrets Manager → `aifficient/backend/env` |
| Instance role | `AppRunnerInstanceRole` |
| Outgoing network | Custom VPC → `aifficient-vpc` connector |
| Health check | HTTP `/api/v1/health` port `8000` |

Wait for **Running**, then test:

```
https://<service-id>.<region>.awsapprunner.com/api/v1/health
```

---

## Phase 8 — Frontend (S3 + CloudFront)

### 8.1 Build with production API URL

```bash
cd frontend

export API_URL=$(aws apprunner list-services \
  --query "ServiceSummaryList[?ServiceName=='aifficient-backend'].ServiceUrl | [0]" --output text)
echo "API: https://$API_URL/api/v1"

cat > .env.production <<EOF
VITE_API_URL=https://$API_URL/api/v1
EOF

npm install
npm run build
```

### 8.2 Create S3 bucket (private)

```bash
export BUCKET=aifficient-frontend-$AWS_ACCOUNT_ID
aws s3api create-bucket --bucket $BUCKET --region $AWS_REGION \
  --create-bucket-configuration LocationConstraint=$AWS_REGION
aws s3api put-public-access-block --bucket $BUCKET \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

### 8.3 Upload build

```bash
aws s3 sync dist/ s3://$BUCKET --delete
```

### 8.4 Create CloudFront distribution

CloudFront → Create distribution:

- **Origin:** S3 bucket with **Origin Access Control (OAC)**
- **Viewer protocol:** Redirect HTTP → HTTPS
- **Default root object:** `index.html`
- **Custom error responses:**
  - 403 → `/index.html` with HTTP 200
  - 404 → `/index.html` with HTTP 200
  *(SPA routing for React Router)*
- **Price class:** PriceClass_100

Apply the OAC bucket policy CloudFront provides after creation.

### 8.5 Custom domain (optional)

- ACM cert in **us-east-1** for CloudFront (`app.yourdomain.com`)
- Route 53 A-record (alias) → CloudFront
- App Runner custom domain for API (`api.yourdomain.com`)

---

## Phase 9 — CORS

In `backend/main.py`, restrict `CORSMiddleware` to:

```
https://app.yourdomain.com
https://<cloudfront-id>.cloudfront.net
http://localhost:5173
```

Allow headers: `Authorization`, `Content-Type`.

Push change → rebuild ECR image → App Runner redeploys.

---

## Phase 10 — Smoke test

1. `GET https://<api>/api/v1/health` → 200
2. Open frontend URL
3. Sign up → log in
4. DevTools → Application → Local Storage: `token`, `refresh_token`
5. API calls include `Authorization: Bearer ...`
6. Test Members, Calls (LiveKit), Settings logout

---

## Phase 11 — CI/CD (optional)

GitHub Actions on push to `main`:

1. **Backend:** build & push to ECR → `aws apprunner start-deployment`
2. **Frontend:** `npm ci && npm run build` → `aws s3 sync` → CloudFront invalidation `/*`

Use GitHub OIDC or stored AWS secrets for auth.

---

## Phase 12 — Day-to-day operations

| Task | How |
|------|-----|
| Backend logs | App Runner → Logs or CloudWatch |
| DB metrics | RDS → Monitoring |
| Run migration | Bastion or temporary public RDS → `alembic upgrade head` |
| Rotate secret | Secrets Manager → trigger new App Runner deployment |
| Scale backend | App Runner → Configuration → vCPU/Memory |
| Restore DB | RDS automated snapshots (7-day retention) |
| Save cost | Stop App Runner; `stop-db-instance` (max 7 days) |

---

## Estimated monthly cost (ap-south-1, small workload)

| Service | $/mo |
|---------|------|
| App Runner (0.5 vCPU, 1 GB) | 12–20 |
| RDS db.t4g.micro + 20 GB | 14–18 |
| ElastiCache cache.t4g.micro | 11–14 |
| S3 + CloudFront | < 2 |
| Secrets Manager | 0.40 |
| Route 53 | 0.50 |
| LiveKit Cloud (free tier) | 0 |
| **Total** | **~$40–55** |

Cheaper: Upstash Redis instead of ElastiCache, pause App Runner when idle, AWS Free Tier for RDS (12 months).

---

## Common pitfalls

1. **Image arch mismatch** — forgot `--platform linux/amd64` on M1/M2 → `exec format error`
2. **App Runner can't reach RDS** — missing VPC connector or wrong security group
3. **CORS errors** — frontend domain not in FastAPI allowlist
4. **`VITE_API_URL` wrong** — frontend still calls `localhost:8001`; rebuild with correct `.env.production`
5. **CloudFront 403 on refresh** — missing SPA 403/404 → `/index.html` rewrite
6. **Migrations not run** — login 500s; tables don't exist
7. **LiveKit `ws://` in prod** — must use `wss://` (LiveKit Cloud)
8. **Secrets in git** — rotate everything in `backend/.env` before going live

---

## Repo-specific checklist

- [ ] Rotate all secrets in `backend/.env`
- [ ] Add `backend/.env` to `.gitignore`
- [ ] Set `VITE_API_URL` at frontend build time
- [ ] Update `APP_LOGIN_URL` to production URL
- [ ] Point LiveKit env to LiveKit Cloud (`wss://...`)
- [ ] Tighten CORS in `backend/main.py`
- [ ] Run `alembic upgrade head` on prod DB
- [ ] Set `ENV=production`, `LOG_JSON=true`

---

## Architecture diagram

```
Users
  │
  ├─► CloudFront ──► S3 (frontend static)
  │
  └─► App Runner (backend API)
         │
         ├─► RDS PostgreSQL (users, sessions, orgs)
         ├─► ElastiCache Redis
         └─► LiveKit Cloud (calls / WebRTC)

Secrets Manager ──► App Runner env at runtime
```

---

*Generated for the Aifficient project. Backend health check: `/api/v1/health`. Default backend port: `8000`.*
