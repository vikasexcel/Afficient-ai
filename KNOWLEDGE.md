# Aifficient — Project Knowledge Base

> Source of truth for how this codebase is organized, what each piece does, and how it fits together. Update this file whenever significant changes are made (see [Maintenance Instructions](#-maintenance-instructions) at the bottom).

---

## 1. Project Overview

**Aifficient** is a multi-tenant SaaS for **AI-powered outbound voice campaigns**. An organization invites members, configures campaigns/workflows, runs executions, and engages with leads through **real-time audio calls** powered by **LiveKit** with **ElevenLabs** as the TTS voice for the AI agent.

Current state of features (as observed in code):

- Auth, multi-tenant orgs, role-based members — **implemented end-to-end** (incl. proper 401/409 semantics, password strength validation, audit log scoped to org + paginated).
- LiveKit room/token/session management — **implemented end-to-end**.
- **ElevenLabs TTS** streaming into LiveKit rooms — **implemented end-to-end** (backend + smoke tested).
- **Deepgram STT** subscribing to a LiveKit room and emitting transcript events — **implemented end-to-end** (backend + smoke endpoint + frontend debug UI).
- **OpenAI GPT-4o conversation engine** — **implemented end-to-end** with Redis-backed conversation memory, BANT/MEDDICC qualification, Postgres-persisted transcripts and call summaries. Wired into the frontend Calls page (assistant panel) and Transcripts page (real DB data). `/ai/calls` listing uses a bulk-fetch path (no N+1).
- **ConversationOrchestrator** wiring STT → GPT-4o → TTS with barge-in — implemented (backend) and exercisable via `scripts/run_ai_agent.py`.
- **Playbooks** — full CRUD, publish/archive/duplicate, versioned snapshots, dry-run `/test`, declarative branch rules with strict `when`-key allowlist. Drives prompts + qualification on AI calls.
- Campaigns / workflows / executions — **wired end-to-end** including a real **dialing pipeline**: activation enqueues per-lead executions, the `CampaignScheduler` (Celery Beat) paces dispatch within business hours, and the worker places real outbound calls via `TelephonyService` (gated by `CAMPAIGN_TELEPHONY_DIALING_ENABLED`). Retry engine, AMD/voicemail-drop, and pacing are implemented. Dial failures fail the execution (no silent LLM fallback). Auth + tenant-scoping enforced on `/campaigns/*`.
- **Telephony (Twilio + LiveKit SIP)** — outbound originate + status/voice webhooks + `<Dial><Sip>` bridge, Answering Machine Detection + voicemail drop, and reconciliation of terminal call outcomes back onto campaign executions. Mock-origination path explicitly **refuses to run when `ENV=production`**.
- Frontend **Calls** and **Transcripts** pages — **wired to the live backend** (GPT-4o chat, Deepgram transcribe smoke, real transcripts + summaries). **Analytics** page remains UI-only with mock data.
- **Leads** — full Phase 1 Lead Management implemented end-to-end: backend module (`modules/leads/`), migration, and frontend wired to real APIs. See §4 for module details.
- **Test suite** — 29 pytest cases under `backend/tests/` cover auth, audit scoping, password rules, campaign worker, playbook branches, tenant isolation, rate limit, Twilio prod guard. Run with `pytest tests/`.

---

## 2. Tech Stack

### Backend (`backend/`)

- **Python 3.12**
- **FastAPI** `0.136` — HTTP framework
- **uvicorn** — ASGI server
- **SQLAlchemy 2.0** + **Alembic** — ORM and migrations
- **PostgreSQL 16** — primary datastore
- **Redis 7** — rate limiting (and infrastructure for future caching/queues)
- **python-jose** — JWT signing
- **passlib + bcrypt** — password hashing
- **pydantic v2 / pydantic-settings** — request/response models and config
- **structlog** — structured logging
- **livekit / livekit-api** — LiveKit server SDK
- **elevenlabs** — TTS SDK
- **openai** (`>=1.51,<2`) — official OpenAI Python SDK (GPT-4o)
- **deepgram-sdk** (`7.2.0`) — Deepgram Speech-to-Text SDK (nova-3)
- **celery / kombu** — listed in `requirements.txt` (no worker code found yet; likely planned)
- **prometheus-fastapi-instrumentator / prometheus_client** — present in requirements (not wired into `main.py`)
- **smtplib** (stdlib) — SMTP email delivery
- **pytest + pytest-asyncio** — backend test runner (added; not in `requirements.txt` yet — install separately in dev/CI)
- **twilio** (`>=9.3,<10`) — Twilio REST + signature validator

### Frontend (`frontend/`)

- **React 19** + **TypeScript** + **Vite 8**
- **React Router 7** (`react-router-dom`)
- **Tailwind CSS 4** (`@tailwindcss/vite`)
- **shadcn/ui** components built on **radix-ui**
- **Zustand 5** — state management
- **axios** — HTTP client with request/response interceptors
- **react-hook-form** + **zod** + `@hookform/resolvers` — forms and validation
- **livekit-client** — browser WebRTC client
- **next-themes** — light/dark theme controller
- **sonner** — toast notifications
- **lucide-react** — icon set
- **class-variance-authority**, **clsx**, **tailwind-merge** — class composition helpers
- **@fontsource-variable/geist** — primary UI font

### Infrastructure (dev)

- **Docker Compose** (`backend/docker-compose.yml`) — runs Postgres, Redis, LiveKit (dev mode), and the backend image
- **Dockerfile** (`backend/Dockerfile`) — production-friendly backend image (Python 3.12, libsoxr/opus/ffmpeg for LiveKit RTC)

> A `backend/next-app/` folder also exists but only contains config (no source files). It appears to be a placeholder/experiment and is **not part of the active app**.

---

## 3. Folder Structure

```
afficient-ai/
├── KNOWLEDGE.md                    ← this file
├── docs/
│   └── DEPLOY_AWS.md               step-by-step AWS deployment guide
│
├── backend/
│   ├── main.py                     FastAPI app entrypoint, router wiring, middleware
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── docker-compose.yml          local dev stack (Postgres, Redis, LiveKit, backend)
│   ├── .env                        local env (gitignored)
│   ├── alembic.ini
│   ├── next-app/                   placeholder; not currently in use
│   │
│   ├── config/
│   │   └── settings.py             pydantic-settings BaseSettings (all env vars)
│   │
│   ├── database/
│   │   ├── base.py                 BaseModel (uuid id + timestamps)
│   │   ├── session.py              SQLAlchemy engine + SessionLocal
│   │   ├── dependencies.py         get_db() FastAPI dep
│   │   └── models.py               (aggregator)
│   │
│   ├── migrations/                 Alembic
│   │   └── versions/               20+ revisions: init -> users/orgs -> sessions ->
│   │                               memberships -> audit_logs -> role enum -> campaigns ->
│   │                               workflows -> executions -> exec output -> membership
│   │                               status -> livekit_sessions -> ai_tables ->
│   │                               telephony -> playbook chain -> leads -> lead_activities ->
│   │                               extend_campaigns -> retry -> amd_voicemail ->
│   │                               rebuild_leads (Phase 1)
│   │                               (ai_calls, ai_transcript_entries, ai_call_summaries)
│   │
│   ├── common/
│   │   ├── security/
│   │   │   ├── jwt.py              create/decode access + refresh tokens (HS256)
│   │   │   ├── password.py         bcrypt hash/verify
│   │   │   ├── dependencies.py     get_current_user (HTTPBearer + JWT decode)
│   │   │   ├── authorization.py    require_role / requires(*Role) dependency factories
│   │   │   ├── roles.py            Role enum (owner, admin, agent, member)
│   │   │   ├── status.py           MembershipStatus enum (active, pending)
│   │   │   ├── rate_limit.py       Redis-backed sliding-window limiter
│   │   │   └── protection.py       RateLimitMiddleware (30 req / 60s per IP)
│   │   ├── logging/                structlog setup (configure_logging, get_logger)
│   │   └── email/
│   │       ├── mailer.py           SMTP send (sync + async-via-thread)
│   │       └── templates.py        member invitation, removal, password reset
│   │
│   ├── modules/                    feature-grouped vertical slices
│   │   ├── health/router.py        GET /health
│   │   ├── auth/                   register, login, /me, refresh, logout, audit
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   ├── repository.py
│   │   │   ├── schema.py
│   │   │   ├── dependencies.py     get_current_org (stub)
│   │   │   ├── tenant.py           get_current_tenant (selects best membership)
│   │   │   ├── model.py            User
│   │   │   ├── organization_model.py    Organization
│   │   │   ├── membership_model.py      Membership (User <-> Org + role + status)
│   │   │   ├── session_model.py         Session (refresh tokens)
│   │   │   └── audit_model.py           AuditLog
│   │   ├── organization/           org CRUD, rename, transfer ownership, delete
│   │   ├── members/                list/create/update-role/reset-password/remove
│   │   ├── campaign/               campaigns, workflows, executions, dialing, scheduler
│   │   │   ├── router.py / service.py / repository.py / schema.py
│   │   │   ├── model.py            Campaign (status, playbook_id, lead_list_id,
│   │   │   │                       schedule, business_hours, retry/voicemail cfg, pacing)
│   │   │   ├── workflow_model.py   Workflow
│   │   │   ├── execution_model.py  Execution (status, outcome, retry bookkeeping)
│   │   │   ├── worker.py           run_execution: places a REAL outbound call via
│   │   │   │                       TelephonyService when dialing is enabled (no silent
│   │   │   │                       LLM fallback on dial failure); else LLM-plan stub
│   │   │   ├── scheduler.py        CampaignScheduler tick (auto-activate, paced
│   │   │   │                       dispatch, completion, metrics, retry requeue)
│   │   │   ├── scheduling.py       business-hours + pacing math
│   │   │   ├── retry.py            retry engine (process_outcome, backoff, outcomes)
│   │   │   ├── voicemail.py        AMD / voicemail-drop config + recording upload
│   │   │   ├── celery_app.py       Celery app + Beat schedule (per-minute tick)
│   │   │   └── tasks.py            scheduler_tick Celery task
│   │   ├── telephony/              Twilio + LiveKit SIP outbound/inbound calling
│   │   │   ├── router.py           originate, status/voice webhooks, list/cancel/retry
│   │   │   ├── service.py          TelephonyService: initiate_outbound, AMD/voicemail,
│   │   │   │                       webhook reconcile → campaign execution outcome
│   │   │   ├── twilio_client.py    Twilio REST + TwiML + signature validation
│   │   │   ├── amd.py              answer-type detection (human / voicemail / unknown)
│   │   │   ├── agent_runner.py     in-room AI agent registry/runner
│   │   │   └── model.py / repository.py / schema.py / dependencies.py / exceptions.py
│   │   ├── playbook/               playbook CRUD, versions, call-apply, company config
│   │   ├── ai/                     GPT-4o conversation engine
│   │   │   ├── router.py           /ai/generate, /ai/converse, /ai/calls/*, /ai/personas
│   │   │   ├── service.py          AIService: start_call, respond_turn, stream_turn,
│   │   │   │                       get_qualification, get_transcript, finalize_call
│   │   │   ├── openai_client.py    Async OpenAI SDK wrapper (complete + stream)
│   │   │   ├── memory.py           Redis-backed ConversationMemory (history+meta+qual)
│   │   │   ├── qualification.py    Rule-based BANT/MEDDICC state machine
│   │   │   ├── prompts.py          Persona system prompts (outbound_sdr, appointment_setter, support_triage)
│   │   │   ├── orchestrator.py     Live STT→GPT-4o→TTS loop with barge-in (LiveKit)
│   │   │   ├── provider.py         Backward-compatible shim → OpenAIClient
│   │   │   ├── repository.py       Sync CRUD for AICall / AITranscriptEntry / AICallSummary
│   │   │   ├── model.py            SQLAlchemy models (org-scoped)
│   │   │   ├── schema.py           pydantic request/response + CallListEntry
│   │   │   ├── dependencies.py     Singletons (openai/memory/service) + AIError→HTTPException
│   │   │   └── exceptions.py       AIError hierarchy with HTTP status codes
│   │   ├── livekit/                rooms, tokens, sessions
│   │   │   ├── router.py
│   │   │   ├── service.py          LiveKitService (async wrapper around livekit.api)
│   │   │   ├── transport.py        AudioTransport (publish PCM into a room)
│   │   │   ├── repository.py / schema.py / dependencies.py / exceptions.py
│   │   │   └── model.py            LiveKitSession
│   │   ├── tts/
│   │   │   ├── router.py           POST /tts/speak, GET /tts/voices
│   │   │   ├── streamer.py         TTSStreamer: ElevenLabs → LiveKit room
│   │   │   ├── elevenlabs_client.py
│   │   │   └── schema.py / dependencies.py / exceptions.py
│   │   └── stt/                    Deepgram speech-to-text
│   │       ├── router.py           POST /stt/transcribe (smoke/debug endpoint)
│   │       ├── streamer.py         STTSession: LiveKit audio → Deepgram → TranscriptEvent
│   │       ├── deepgram_client.py  Async websocket wrapper, normalises events
│   │       └── schema.py / dependencies.py / exceptions.py
│   │
│   └── scripts/
│       ├── e2e_livekit_test.py     LiveKit smoke
│       ├── e2e_full_validation.py  13-point LiveKit validation (rooms, tokens, WebRTC, audio, errors)
│       ├── e2e_tts_test.py         ElevenLabs → LiveKit smoke
│       ├── e2e_stt_test.py         LiveKit → Deepgram smoke
│       ├── e2e_ai_test.py          GPT-4o E2E: generate, converse, qualification, transcript, finalize
│       ├── run_ai_agent.py         Standalone runner for ConversationOrchestrator (live voice)
│       ├── demo_barge_in.py        Interactive TTS barge-in demo
│       ├── debug_stt_capture.py / debug_stt_tap.py    Deepgram debugging utilities
│       └── bench_tts_http.py / bench_tts_inproc.py    TTS latency benchmarks
│
└── frontend/
    ├── package.json
    ├── vite.config.ts              @ alias points to ./src
    ├── tsconfig*.json
    ├── eslint.config.js
    ├── index.html
    └── src/
        ├── main.tsx                bootstraps app + imports axios interceptor
        ├── App.tsx                 hydrates auth/appearance, wraps RouterProvider in ThemeProvider, mounts Toaster
        ├── index.css               Tailwind v4 setup, theme tokens (light/dark via oklch), light-mode safety net
        │
        ├── router/
        │   ├── index.tsx           createBrowserRouter — all routes listed in §5
        │   └── ProtectedRoute.tsx  redirects to /login when no token
        │
        ├── pages/
        │   ├── Home.tsx            marketing landing (fully responsive hero/nav/feature grid)
        │   ├── Login.tsx           login form (react-hook-form)
        │   ├── Signup.tsx          signup form
        │   ├── Dashboard.tsx       dashboard (mostly placeholder)
        │   ├── Campaigns.tsx       campaign list/CTA
        │   ├── Calls.tsx           LiveKit join + GPT-4o assistant panel + Deepgram live transcribe
        │   ├── Leads.tsx           **mock data**, no backend
        │   ├── Analytics.tsx       **mock data**, no backend
        │   ├── Transcripts.tsx     real data from /ai/calls + per-call transcript/summary
        │   ├── Settings.tsx        Tabs: Members / Organization / Profile / Appearance / Security
        │   └── Documentation.tsx   in-app docs hub (sticky left nav, search, 10 sections + FAQ + perms table)
        │
        ├── components/
        │   ├── layout/             AppLayout (sidebar+header shell), Sidebar (mobile drawer), Header (hamburger + dropdown nav)
        │   ├── settings/           MembersCard, OrganizationCard, ProfileCard, AppearanceCard, SecurityCard
        │   ├── members/            MembersTable, InviteMemberDialog
        │   ├── campaign/           CreateCampaignDialog
        │   ├── theme-provider.tsx  thin wrapper around next-themes
        │   └── ui/                 shadcn primitives (button, input, dialog, dropdown, etc.)
        │
        ├── services/               HTTP wrappers (all share one axios instance from auth.ts)
        │   ├── auth.ts             axios instance + login/signup/me/refresh/logout
        │   ├── members.ts
        │   ├── organization.ts
        │   ├── campaign.ts
        │   ├── livekit.ts
        │   ├── ai.ts               GPT-4o: generate, converse, listCalls, getTranscript,
        │   │                       getQualification, finalizeCall, listPersonas
        │   └── stt.ts              Deepgram: transcribe (smoke endpoint)
        │
        ├── store/                  Zustand stores
        │   ├── auth.ts             token + refreshToken (persisted in localStorage)
        │   ├── me.ts               current user profile + role/org + RBAC helpers
        │   ├── livekit.ts          Room + participants + connect/disconnect/toggleMic
        │   ├── ai.ts               conversation state (bubbles, qualification, summary, send/finalize)
        │   ├── appearance.ts       density preference (comfortable / compact)
        │   └── ui.ts               global UI state — sidebarOpen + open/close/toggle (mobile drawer)
        │
        ├── lib/
        │   ├── interceptor.ts      axios req: attach Bearer; res: 401 → refresh → retry
        │   └── utils.ts            cn() = clsx + tailwind-merge
        │
        └── types/
            └── campaign.ts
```

---

## 4. Core Features & Modules

### Backend modules

| Module | Responsibility | Key files |
|---|---|---|
| `auth` | Register, login, `/me`, refresh, logout, audit log | `modules/auth/*` |
| `organization` | Read/rename/transfer-ownership/delete current tenant | `modules/organization/router.py` |
| `members` | Org membership CRUD + temp-password reset + invitation email | `modules/members/*` |
| `leads` | Phase 1 Lead Management: org-scoped `Lead` + `LeadList` (many-to-many via `lead_list_memberships`). Full CRUD + search + pagination + duplicate detection (`phone_normalized`). Audit logs: `LEAD_CREATED`, `LEAD_UPDATED`, `LEAD_DELETED`, `LEAD_LIST_CREATED`. Lead fields: `first_name`, `last_name`, `email`, `phone`, `linkedin_url`, `company`, `job_title`, `status`, `tags`, `extra_data`. | `modules/leads/*` |
| `campaign` | Campaign → Workflow → Execution chain. Activation enqueues one queued `Execution` per lead; the `CampaignScheduler` tick (Celery Beat) paces dispatch within business hours; the worker places a **real outbound call** via `TelephonyService` (Twilio/LiveKit SIP) per lead when `CAMPAIGN_TELEPHONY_DIALING_ENABLED`. Retry engine + AMD/voicemail-drop + pacing supported. | `modules/campaign/*` |
| `telephony` | Outbound/inbound PSTN via Twilio + LiveKit SIP. `initiate_outbound` creates a `telephony_calls` row + LiveKit room + AI agent, originates the call, and reconciles the terminal status webhook back onto the linked campaign execution. | `modules/telephony/*` |
| `playbook` | Playbook CRUD, versioned snapshots, publish/archive/duplicate, call-apply (persona/framework/voice/opening line) | `modules/playbook/*` |
| `ai` | GPT-4o conversation engine: stateless `generate`, stateful `converse`, Redis memory, BANT/MEDDICC qualification, Postgres transcripts/summaries, live STT→LLM→TTS orchestrator | `modules/ai/*` |
| `livekit` | Create/list/get/delete LiveKit rooms, mint JWT tokens, store local session rows | `modules/livekit/*` |
| `tts` | List voices, speak text into a LiveKit room via ElevenLabs PCM stream | `modules/tts/*` |
| `stt` | Subscribe to a LiveKit room as an agent, pipe audio into Deepgram, return TranscriptEvents | `modules/stt/*` |
| `health` | `/health` smoke check | `modules/health/router.py` |

### Cross-cutting

- **JWT**: `common/security/jwt.py` (HS256, 60-min access by default, 30-day refresh).
- **RBAC**: `common/security/authorization.py` exposes `require_role(...)` and `requires(*Role)` FastAPI dep factory.
- **Tenant resolution**: `modules/auth/tenant.py` picks the best Membership for the JWT subject (active + highest role + most recent).
- **Rate limiting**: `common/security/protection.py` middleware uses Redis (`30 req / 60s` per source IP).
- **Structured logs**: `common/logging/logger.py` — console-renderer in dev, JSON in non-dev or when `LOG_JSON=true`.
- **Email**: `common/email/mailer.py` (SMTP via stdlib `smtplib`, sent on a background thread; gracefully no-ops if SMTP isn't configured).

### Frontend feature surface

| Page | Status | Notes |
|---|---|---|
| Home | static landing | `pages/Home.tsx` |
| Login / Signup | wired to `/auth/login` and `/auth/register` | uses react-hook-form |
| Dashboard | placeholder | `pages/Dashboard.tsx` |
| Campaigns | minimal CRUD UI, dialog for create | `pages/Campaigns.tsx`, `services/campaign.ts` |
| Calls | LiveKit join/disconnect, mic toggle, persona picker, GPT-4o assistant panel (live converse + BANT chips + Finalize summary), Deepgram "Live transcribe" smoke widget | `pages/Calls.tsx`, `store/livekit.ts`, `store/ai.ts`, `services/ai.ts`, `services/stt.ts` |
| Leads | **wired to backend** — real CRUD (add/edit/delete/search), paginated list, Lead + LeadList management | `pages/Leads.tsx`, `services/lead.ts`, `types/lead.ts`, `components/leads/` |
| Analytics | **mock data only** | `pages/Analytics.tsx` |
| Transcripts | Real calls from `GET /ai/calls`, per-call transcript from `GET /ai/calls/{id}/transcript`, summary + qualification, finalize + export JSON | `pages/Transcripts.tsx`, `services/ai.ts` |
| Settings | tabs: Members, Organization, Profile, Appearance, Security | gated by role via `store/me.ts` helpers |
| Documentation | in-app docs hub: sticky topic nav + search, 10 sections (getting started, campaigns, playbooks, leads, calls, analytics, transcripts, settings, roles & permissions, FAQ). Reached from the avatar dropdown in `Header.tsx` | `pages/Documentation.tsx` |

---

## 5. Routing / Pages

All frontend routes are declared in `frontend/src/router/index.tsx`:

| Path | Component | Protected |
|---|---|---|
| `/` | `Home` | no |
| `/login` | `Login` | no |
| `/signup` | `Signup` | no |
| `/dashboard` | `Dashboard` | yes |
| `/campaigns` | `Campaigns` | yes |
| `/calls` | `Calls` | yes |
| `/leads` | `Leads` | yes |
| `/analytics` | `Analytics` | yes |
| `/transcripts` | `Transcripts` | yes |
| `/playbooks` | `Playbooks` | yes |
| `/settings` | `Settings` (Tabs UI) | yes |
| `/documentation` | `Documentation` | yes |

`ProtectedRoute` reads the access token from `useAuth` and redirects to `/login` when missing.

Sidebar nav (`components/layout/Sidebar.tsx`) further hides entries based on role helpers from `store/me.ts`:

- **Workspace** (Dashboard, Campaigns, Leads, Calls) — visible to `owner`/`admin`/`agent`
- **Insights** (Analytics, Transcripts) — visible to `owner`/`admin`
- **Settings** — visible to everyone signed in

Backend routes are mounted under `settings.API_PREFIX` (default `/api/v1`):

| Prefix | Module | Notable endpoints |
|---|---|---|
| (no prefix) | health | `GET /health` |
| `/auth` | auth | `POST /register`, `POST /login`, `GET /me`, `POST /refresh`, `POST /logout`, `GET /audit`, `GET /tenant`, `GET /admin` |
| `/organization` | organization | `GET /`, `PATCH /`, `POST /transfer-ownership`, `DELETE /` |
| `/members` | members | `GET /`, `POST /`, `PATCH /{id}/role`, `POST /{id}/reset-password`, `DELETE /{id}` |
| `/leads` | leads | `POST /`, `GET /`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}` |
| `/lead-lists` | leads | `GET /`, `POST /`, `PATCH /{id}`, `DELETE /{id}`, `POST /{id}/leads`, `DELETE /{id}/leads` |
| `/campaigns` | campaign | `POST /`, `GET /`, `POST /activate`, `POST /execute/{workflow_id}`, `GET /executions/{id}`, `GET /executions/{id}/retry-history`, `POST /{id}/pause`, `POST /{id}/resume`, `GET /{id}/schedule-status`, `GET /{id}/metrics` (incl. `failed_executions`), `GET /{id}/retries`, `GET|POST /{id}/voicemail`, `GET|PATCH|DELETE /{id}` |
| `/livekit` | livekit | `POST /rooms`, `GET /rooms`, `GET /rooms/{name}`, `DELETE /rooms/{name}`, `POST /tokens`, `GET /sessions/{room_name}` |
| `/tts` | tts | `GET /voices`, `POST /speak` |
| `/stt` | stt | `POST /transcribe` (joins a LiveKit room as a Deepgram subscriber for N seconds, returns events) |
| `/ai` | ai | `POST /generate` (stateless), `POST /converse` (stateful turn), `GET /calls`, `GET /calls/{id}/transcript`, `GET /calls/{id}/qualification`, `POST /calls/{id}/finalize`, `GET /personas` |

---

## 6. State Management

Zustand is used throughout the frontend. There is **no Redux, Context, or React Query** in the codebase.

| Store | Purpose | Persistence |
|---|---|---|
| `useAuth` (`store/auth.ts`) | `token`, `refreshToken`, `setAuth`, `logout`, `hydrate` | `localStorage` keys `token`, `refresh_token` |
| `useMe` (`store/me.ts`) | Current user from `GET /auth/me`; exposes role helpers (`canManageMembers`, `canUseCampaigns`, `canAccessWorkspace`, `canAccessInsights`, `isOwner`) | in-memory only; refetched on token change |
| `useLiveKit` (`store/livekit.ts`) | Live `Room` instance + participants + mic state | in-memory only |
| `useAI` (`store/ai.ts`) | Active call_id, persona, framework, chat bubbles, qualification snapshot, summary. Actions: `start`, `send` (→ `/ai/converse`), `finalize`, `refreshQualification`, `loadTranscript`, `reset` | in-memory only |
| `useAppearance` (`store/appearance.ts`) | UI density (`comfortable`/`compact`); writes `data-density` attribute on `<html>` | `localStorage` key `afficient-density` |
| `useUI` (`store/ui.ts`) | Global UI toggles — currently `sidebarOpen` for the mobile drawer; actions: `openSidebar`, `closeSidebar`, `toggleSidebar`. Consumed by `Header` (hamburger) and `Sidebar` (drawer transform + backdrop + Esc/route-change auto-close) | in-memory only |

Bootstrapping (`App.tsx`):

1. On mount, `hydrate()` reads tokens from `localStorage` into `useAuth`.
2. `hydrateAppearance()` applies density to `<html>`.
3. When `token` becomes truthy, `useMe.load()` fetches the profile.
4. When `token` becomes falsy, `useMe.reset()`.

Theme state is delegated to **next-themes** (see §9).

---

## 7. API / Services Layer

### Frontend

All HTTP calls go through a single axios instance defined in `frontend/src/services/auth.ts`:

```ts
const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8001/api/v1";
export const api = axios.create({ baseURL: API_BASE, ... });
```

Other service modules (`services/members.ts`, `services/organization.ts`, `services/campaign.ts`, `services/livekit.ts`, `services/ai.ts`, `services/stt.ts`) import and reuse `api`. Each exports typed wrappers around endpoints (e.g. `listMembers()`, `createRoom()`, `issueToken()`, `converse()`, `listCalls()`, `transcribe()`).

#### Interceptor (`lib/interceptor.ts`)

- **Request:** attach `Authorization: Bearer <token>` from `localStorage`.
- **Response:** on `401` from a non-auth endpoint, attempt **one** refresh using the stored refresh token, retry the original request once, and on failure clear storage and redirect to `/login`. Concurrent 401s share a single in-flight refresh promise.

### Backend

Each module follows a **router → service → repository → model** structure:

- `router.py` — FastAPI endpoints, validation, role dependencies
- `service.py` — orchestration / business logic / commits
- `repository.py` — narrow SQL access
- `model.py` (and friends) — SQLAlchemy ORM models inheriting `database.base.BaseModel` (UUID PK, `created_at`, `updated_at`)
- `schema.py` — pydantic request/response models

The shared FastAPI dependency `database.dependencies.get_db()` yields a `SessionLocal()` per request. There is a near-identical alias `database/session.py::get_db` — both are present.

---

## 8. Authentication Flow

### Registration

1. `POST /api/v1/auth/register` with `full_name`, `email`, `password`, `organization`.
2. Backend creates an `Organization`, a `User` (bcrypt-hashed password), and a `Membership` with role `OWNER` and status `ACTIVE`. Returns `{ message: "registered" }`. **No tokens are issued on register** — the user must log in.

### Login

1. `POST /api/v1/auth/login` with `email`, `password`.
2. `AuthService.login` looks up the user, verifies the password, and on success:
   - mints an access JWT (`JWT_EXPIRE_MINUTES`, default 60 min)
   - mints a refresh JWT (30 days)
   - inserts a `sessions` row keyed by the refresh token (`expires_at = now + 30d`, `revoked = false`)
   - logs `LOGIN` to `audit_logs`
3. Returns `{ access_token, refresh_token }`.

### Storage (browser)

`localStorage`:

| Key | Value |
|---|---|
| `token` | access JWT |
| `refresh_token` | refresh JWT |

These are written by `useAuth.setAuth()` and consumed by `lib/interceptor.ts` for every API request. The Zustand store mirrors them in memory.

> No password is ever stored client-side. Bearer-token-in-localStorage is the chosen pattern; XSS-resistant httpOnly cookies are **not** used.

### Protected calls

- `Authorization: Bearer <access>` header (auto-attached by the axios interceptor)
- `HTTPBearer` dependency on the backend decodes the JWT → returns `{ "sub": <user_id>, ... }`
- `get_current_tenant` then selects the user's best `Membership` (active + highest role + most recent), exposing `{ user_id, organization_id, membership_id, role, status }` to downstream handlers
- `requires(Role.OWNER, Role.ADMIN, ...)` enforces RBAC

### Refresh

`POST /api/v1/auth/refresh` with `{ refresh_token }` returns a new `access_token` if the matching `sessions` row exists and is not revoked. The interceptor invokes this automatically on a 401.

### Logout

`POST /api/v1/auth/logout` with `{ refresh_token }` revokes the matching `sessions` row. The Settings → Security "Sign out everywhere" flow calls this and then clears `localStorage`. `SecurityCard.tsx`.

### Audit

`audit_logs` table receives entries for actions like `REGISTER`, `LOGIN`, `ORG_RENAMED`, `ORG_OWNERSHIP_TRANSFERRED`, and member-management actions (see `modules/members/service.py`).

---

## 9. Theme System

### Library

The frontend uses **`next-themes`** wrapped by a thin `components/theme-provider.tsx`. `App.tsx` mounts it with:

```ts
<ThemeProvider
  attribute="class"
  defaultTheme="dark"
  enableSystem
  storageKey="afficient-theme"
>
```

This toggles the `dark` class on `<html>` and persists the choice in `localStorage` under `afficient-theme`.

### Tokens

CSS variables in `frontend/src/index.css` define both palettes via OKLCH:

- `:root { ... }` — light mode tokens (`--background`, `--foreground`, `--muted`, `--border`, etc.)
- `.dark { ... }` — dark mode overrides

Tailwind v4 (`@theme inline`) maps each token to a Tailwind color (`--color-background`, `--color-foreground`, …) so utilities like `bg-background` and `text-foreground` follow the active theme automatically.

### Light-mode safety net

Many components were originally authored against a dark surface (e.g. `text-white`, `bg-[#07070a]`, `bg-white/[0.04]`, `border-white/[0.06]`). A centralized override block in `index.css`, scoped to `html:not(.dark)`, remaps those dark-only utilities to readable equivalents on light mode without touching every component.

### Density

`useAppearance` writes `data-density="comfortable" | "compact"` on `<html>`. CSS rules in `index.css` adjust main padding and sidebar nav height when compact is active.

### UI controls

`components/settings/AppearanceCard.tsx` provides:

- Theme picker (Dark / Light / System) → calls `setTheme()` from `next-themes`
- Density picker (Comfortable / Compact) → calls `useAppearance.setDensity()`

---

## 9.5. Responsive Design

The frontend is built mobile-first against Tailwind v4 breakpoints: `sm` 640px, `md` 768px, `lg` 1024px, `xl` 1280px. A 2026-06-02 sweep covered every page and the layout shell.

### Shell

- **Sidebar as drawer below `lg`.** `components/layout/Sidebar.tsx` is `fixed inset-y-0 left-0 z-40` with `-translate-x-full` by default, and slides in via `translate-x-0` driven by `useUI.sidebarOpen`. On `lg+` it becomes `lg:static lg:translate-x-0` (no transition). A backdrop `div` (`bg-black/50`, `lg:hidden`) closes the drawer on tap. Side-effects in `useEffect`: auto-close on route change, lock `body` scroll while open, close on `Escape`.
- **Header hamburger.** `components/layout/Header.tsx` renders a `Menu` icon button (`lg:hidden`) that calls `useUI.toggleSidebar()`. Header padding tightens on mobile (`px-3 sm:px-6`); breadcrumbs use `truncate` and the leading crumb is `hidden sm:inline`. Search button + divider are `hidden sm:flex` / `hidden sm:block` to free up space on phones.
- **Main content padding.** `AppLayout.tsx` main is `p-4 sm:p-6 lg:p-8`. Under `html[data-density="compact"]` the values step down via media queries in `index.css`.

### Global safety nets (`frontend/src/index.css`)

```css
body { overflow-x: hidden; }
html, body { max-width: 100%; }
img, svg, video, canvas { max-width: 100%; }
```

These prevent runaway horizontal scroll if any descendant overflows.

### Per-page patterns

| Page | Adaptation |
|---|---|
| `Home` | Nav and hero scale via `px-4 sm:px-6 lg:px-10`, headline `text-[34px] sm:text-[44px] md:text-[54px] lg:text-[62px]`. Stats grid `grid-cols-1 sm:grid-cols-3` with conditional `border-b`/`border-r` flips. Feature grid `grid-cols-1 md:grid-cols-3`. CTAs `flex-col sm:flex-row` with `w-full max-w-[320px]` clamp on mobile. |
| `Login` / `Signup` | Left branding panel narrows on tablets (`w-[380px] xl:w-[420px]`); right form panel `px-4 sm:px-6 py-10 sm:py-14`. |
| `Dashboard` | Metric & funnel grids `grid-cols-2 lg:grid-cols-4`. Campaigns table wrapped in `overflow-x-auto` with `min-w-[640px]` and `whitespace-nowrap` headers. |
| `Leads` | Header `flex-col sm:flex-row` with `flex-wrap` actions. Below `md`, the status filter renders as a native `<select>`; above `md`, the original button group. |
| `Calls` | Mode tabs `overflow-x-auto max-w-full` with `whitespace-nowrap shrink-0` buttons. Live room `grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px]`. AI assistant panel `h-[520px] sm:h-[600px] lg:h-[640px] lg:sticky lg:top-4`. Phone dialer `grid-cols-1 lg:grid-cols-[380px_minmax(0,1fr)]`. |
| `Analytics` | Range selector scrolls horizontally on phones; progress bars `hidden sm:block` to keep cards readable. |
| `Transcripts` | Split view collapses to a stacked layout `grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)]`; list pane capped at `max-h-[420px] lg:max-h-none` so detail is reachable on mobile. |
| `Playbooks` | Sidebar list collapses above the editor (`max-h-[260px] lg:max-h-none`); action bar `flex-col sm:flex-row`. |
| `Campaigns` | Header stacks; CTA `self-start sm:self-auto`. |
| `Settings` | `TabsList` uses `overflow-x-auto flex-nowrap` so all tabs remain reachable on narrow widths. |
| `Documentation` | Sidebar nav stacks above the article column below `lg` (`grid-cols-1 lg:grid-cols-[240px_minmax(0,1fr)]`); permissions matrix is `overflow-x-auto` with `min-w-[520px]`. |

### Reusable building blocks

- `flex-col sm:flex-row` headers — stack on mobile, side-by-side on tablet+.
- `overflow-x-auto` + `min-w-[N]` + `whitespace-nowrap` — preserves wide tables/tab strips.
- `flex-wrap` action rows — buttons drop to the next line instead of overflowing.
- `truncate` + `min-w-0` — keeps long IDs, emails, and breadcrumbs in their column.

---

## 10. Important Utilities & Helpers

### Frontend

| File | Purpose |
|---|---|
| `lib/utils.ts` | `cn(...)` = `twMerge(clsx(...))` — class composition |
| `lib/interceptor.ts` | Bearer attach + 401-refresh-retry pipeline |
| `store/me.ts` | Role helper exports: `canManageMembers`, `canUseCampaigns`, `canAccessWorkspace`, `canAccessInsights`, `isOwner` |
| `components/ui/*` | shadcn-style primitives (Button, Input, Dialog, DropdownMenu, Table, Tabs, Card, Sheet, AlertDialog, etc.) |
| `components/ui/sonner.tsx` | Theme-aware Toaster wrapper |
| `components/theme-provider.tsx` | Wraps `next-themes` |

### Backend

| File | Purpose |
|---|---|
| `database/base.py` | `BaseModel` with UUID `id`, `created_at`, `updated_at` |
| `common/security/jwt.py` | `create_token`, `create_refresh_token`, `decode_token` |
| `common/security/password.py` | bcrypt `hash_password`, `verify_password` |
| `common/security/dependencies.py` | `get_current_user` (HTTPBearer + JWT) |
| `common/security/authorization.py` | `require_role(...)`, `requires(*Role)` |
| `common/security/rate_limit.py` | Redis sliding-window limiter |
| `common/email/mailer.py` | SMTP send (background thread, fire-and-forget) |
| `common/logging/logger.py` | `configure_logging()`, `get_logger(name)` |
| `modules/auth/tenant.py` | `get_current_tenant` — picks the best Membership |

---

## 11. Environment Variables

Defined in `backend/config/settings.py` via `pydantic-settings` (loaded from `backend/.env`). **Required** values have no default in the schema.

### Core

| Var | Required | Default | Purpose |
|---|---|---|---|
| `APP_NAME` | no | `"AIFFICIENT"` | Display name |
| `ENV` | no | `"development"` | `production` switches log format to JSON |
| `API_PREFIX` | no | `"/api/v1"` | Mounted under all module routers |

### Database / cache

| Var | Required | Notes |
|---|---|---|
| `DATABASE_URL` | **yes** | SQLAlchemy URL, e.g. `postgresql+psycopg2://admin:password@localhost:20190/aifficient` |
| `REDIS_URL` | **yes** | e.g. `redis://localhost:20193/0` (use `rediss://` for TLS in cloud) |
| `POSTGRES_DB / USER / PASSWORD / HOST / PORT` | no | Used by docker-compose; not by the app at runtime |

### JWT

| Var | Required | Default | Purpose |
|---|---|---|---|
| `JWT_SECRET` | **yes** | — | HS256 signing secret |
| `JWT_ALGORITHM` | no | `HS256` | |
| `JWT_EXPIRE_MINUTES` | **yes** | — | Access-token TTL |

### Email (SMTP)

| Var | Default |
|---|---|
| `SMTP_HOST` | `""` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `""` |
| `SMTP_PASSWORD` | `""` |
| `SMTP_FROM_NAME` | `"Aifficient"` |
| `APP_LOGIN_URL` | `http://localhost:5173/login` (used inside email bodies) |

If SMTP isn't fully configured, `mailer.py` logs a warning and skips sending — the API does **not** fail.

### LiveKit

| Var | Default |
|---|---|
| `LIVEKIT_URL` | `ws://localhost:7880` (use `wss://...livekit.cloud` in prod) |
| `LIVEKIT_API_KEY` | `""` |
| `LIVEKIT_API_SECRET` | `""` |
| `LIVEKIT_TOKEN_TTL_MINUTES` | `60` |
| `LIVEKIT_DEFAULT_EMPTY_TIMEOUT` | `300` |
| `LIVEKIT_DEFAULT_MAX_PARTICIPANTS` | `20` |

### ElevenLabs TTS

| Var | Default |
|---|---|
| `ELEVENLABS_API_KEY` | `""` |
| `ELEVENLABS_VOICE_ID` | `""` |
| `ELEVENLABS_MODEL_ID` | `eleven_turbo_v2_5` |
| `ELEVENLABS_SAMPLE_RATE` | `24000` |
| `ELEVENLABS_AGENT_IDENTITY` | `ai-agent` |
| `ELEVENLABS_AGENT_NAME` | `AI Agent` |

### Deepgram STT

| Var | Default |
|---|---|
| `DEEPGRAM_API_KEY` | `""` |
| `DEEPGRAM_MODEL` | `nova-3` |
| `DEEPGRAM_LANGUAGE` | `en` |
| `DEEPGRAM_INTERIM_RESULTS` | `true` |
| `DEEPGRAM_VAD_EVENTS` | `true` |
| `DEEPGRAM_ENDPOINTING_MS` | `300` |
| `DEEPGRAM_UTTERANCE_END_MS` | `1000` |
| `DEEPGRAM_SMART_FORMAT` | `true` |
| `DEEPGRAM_PUNCTUATE` | `true` |
| `DEEPGRAM_STT_AGENT_IDENTITY` | `ai-stt-agent` |
| `DEEPGRAM_STT_AGENT_NAME` | `AI STT Agent` |

### OpenAI / GPT-4o conversation engine

| Var | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | `""` | Required for `/ai/*` endpoints to actually call OpenAI |
| `OPENAI_BASE_URL` | `None` | Optional override (Azure / proxy) |
| `OPENAI_ORG_ID` | `None` | Optional org header |
| `OPENAI_MODEL` | `gpt-4o` | Default chat model |
| `OPENAI_TEMPERATURE` | `0.4` | |
| `OPENAI_MAX_TOKENS` | `320` | Per-turn cap |
| `OPENAI_TIMEOUT_SECONDS` | `30.0` | Per-request timeout |
| `OPENAI_MAX_RETRIES` | `2` | SDK retry count |
| `AI_MEMORY_TTL_SECONDS` | `21600` (6h) | Redis TTL for conversation memory |
| `AI_MEMORY_MAX_TURNS` | `24` | Rolling history window (user+assistant pairs) |
| `AI_QUALIFICATION_FRAMEWORK` | `BANT` | `BANT` or `MEDDICC` |
| `AI_DEFAULT_PERSONA` | `outbound_sdr` | Built-ins: `outbound_sdr`, `appointment_setter`, `support_triage` |

> When `OPENAI_API_KEY` is missing, the AI singletons raise `AIConfigError` on first use and the FastAPI dependency translates it to a clean HTTP 500 with `detail = "OPENAI_API_KEY is not set"`. The app still boots; only `/ai/*` endpoints fail.

### Twilio / Telephony

| Var | Required | Default | Purpose |
|---|---|---|---|
| `TWILIO_ACCOUNT_SID` | for PSTN | `""` | Twilio account SID. Values starting with `ACdummy` trigger mock-mode in dev and **raise `TelephonyConfigError` in production**. |
| `TWILIO_AUTH_TOKEN` | for PSTN | `""` | REST + signature-validation secret. |
| `TWILIO_FROM_NUMBER` | for PSTN | `""` | Default E.164 caller-id. |
| `TWILIO_PUBLIC_BASE_URL` | **for production** | `""` | Fully-qualified URL used in `voice_url` / `status_callback` registered with Twilio. If empty, falls back to `request.url.netloc` — won't work behind a private host. |
| `TWILIO_VALIDATE_SIGNATURE` | recommend `true` in prod | `false` | When false, webhooks accept any signature. `main.py` emits `app.startup.unsafe` if `ENV=production` and this is false. |
| `TWILIO_STATUS_CALLBACK_EVENTS` | no | `initiated,ringing,answered,completed` | Subset of Twilio call lifecycle events to receive. |
| `TWILIO_AMD_ENABLED` | no | `true` | Master switch for Answering Machine Detection (required for voicemail drop). |
| `LIVEKIT_SIP_URI` | for SIP bridge | `""` | LiveKit SIP host; Twilio `<Dial><Sip>` bridges the PSTN leg into the agent room. |
| `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` | no | `""` | When set (and AMD off), origination uses LiveKit `CreateSIPParticipant` instead of Twilio. AMD calls always force the Twilio path. |

### Campaign dialing & scheduler

| Var | Required | Default | Purpose |
|---|---|---|---|
| `CAMPAIGN_TELEPHONY_DIALING_ENABLED` | no | `false` | When `true`, the worker places a **real** outbound call per campaign lead via `TelephonyService.initiate_outbound`. When `false`, executions run the legacy in-process LLM-plan stub. (Set `true` in `backend/.env` for live dialing.) |
| `CELERY_BROKER_URL` | no | falls back to `REDIS_URL` | Broker for the scheduler tick. |
| `CELERY_RESULT_BACKEND` | no | falls back to `REDIS_URL` | Result backend. |
| `CAMPAIGN_SCHEDULER_INTERVAL_SECONDS` | no | `60.0` | Celery Beat tick cadence (activate due campaigns + paced dispatch). |
| `CAMPAIGN_DEFAULT_CALLS_PER_HOUR` | no | `60` | Pacing fallback when a campaign omits its own (`0` = unlimited). |
| `CAMPAIGN_DEFAULT_MAX_CONCURRENT_CALLS` | no | `5` | Concurrency fallback (`0` = unlimited). |

### Rate limiting

| Var | Default | Purpose |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `true` | Master switch; tests / load-gen can set `false`. |
| `RATE_LIMIT_REQUESTS` | `300` | Requests allowed per window for general API routes. |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Window length. |
| `RATE_LIMIT_AUTH_REQUESTS` | `10` | Stricter bucket for `/auth/login`, `/auth/register`, `/auth/refresh`. |
| `RATE_LIMIT_AUTH_WINDOW_SECONDS` | `60` | |
| `RATE_LIMIT_EXEMPT_PATHS` | `"/health,/api/v1/telephony/webhooks/twilio/voice,/api/v1/telephony/webhooks/twilio/status,/docs,/openapi.json,/redoc,/favicon.ico"` | Comma-separated path prefixes. `/` (root) and all `OPTIONS` requests are always exempt. |

Scoping: when a valid `Authorization: Bearer …` JWT is present, the limiter buckets by `user:{sub}`; otherwise it falls back to `ip:{remote_addr}`.

### Logging

| Var | Default | Purpose |
|---|---|---|
| `LOG_LEVEL` | `INFO` | |
| `LOG_JSON` | `false` | Forces JSON renderer even in development |

### Frontend

| Var | Default | Purpose |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8001/api/v1` (in `services/auth.ts`) | Backend base URL |

> Note: the backend Dockerfile exposes port **8000**, the dev convention has shifted between **8001** and **8002** depending on which uvicorn the developer launches, and the frontend dev server typically runs on **20197** (Vite finds the next free port if it's taken). Reconcile per environment by setting `VITE_API_URL` in `frontend/.env` to match the actual backend port. The CORS allowlist in `main.py` already includes `http://localhost:20197`.

---

## 12. How to Run the Project

### A. Full stack via Docker Compose (recommended for first run)

From `backend/`:

```bash
docker compose up --build
```

This starts:

- Postgres on `127.0.0.1:20190` (vol: `aifficient_pgdata`)
- Redis on `127.0.0.1:20193`
- LiveKit dev server on `7880` (TCP) + `7881` (TCP) + `7882/udp`
- Backend on `8000`

Then run migrations once against the running DB:

```bash
cd backend
alembic upgrade head
```

### B. Backend only (host Python)

```bash
cd backend
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Provide a .env with DATABASE_URL, REDIS_URL, JWT_SECRET, JWT_EXPIRE_MINUTES, ...
alembic upgrade head
uvicorn main:app --reload --port 8000
```

Health check: `GET http://localhost:8000/api/v1/health`.

### C. Frontend

```bash
cd frontend
npm install
npm run dev          # Vite dev server, default http://localhost:5173
```

If your backend isn't on `http://localhost:8001/api/v1`, create `frontend/.env.local`:

```
VITE_API_URL=http://localhost:8000/api/v1
```

### D. Production build (frontend)

```bash
cd frontend
npm run build        # outputs ./dist
npm run preview      # serve ./dist locally for sanity check
```

### E. Smoke tests

```bash
cd backend
source venv/bin/activate

python scripts/e2e_livekit_test.py        # LiveKit rooms/tokens/WebRTC
python scripts/e2e_full_validation.py     # 13-point LiveKit validation (audio, multi-participant, errors)
python scripts/e2e_tts_test.py            # ElevenLabs → LiveKit
python scripts/e2e_stt_test.py            # LiveKit → Deepgram
python scripts/e2e_ai_test.py             # GPT-4o: generate, converse, qualification, transcript, finalize

# Live voice agent (joins a real LiveKit room and runs STT→GPT-4o→TTS with barge-in)
python scripts/run_ai_agent.py --room my-test-room
```

These exercise the full auth → LiveKit / TTS / STT / GPT-4o pipeline against a running backend. `e2e_ai_test.py` requires `OPENAI_API_KEY` in `backend/.env`. Set `E2E_BASE_URL=http://127.0.0.1:8001` (or 8002) if your backend is not on the script's default.

### F. Pytest suite (regression tests)

```bash
cd backend
source venv/bin/activate
pip install pytest pytest-asyncio    # not yet in requirements.txt
pytest tests/ -v
```

Lives under `backend/tests/`:

- `test_auth.py` (12 cases) — duplicate register → 409, weak passwords → 422, login/refresh/logout → 401 on bad creds, `/auth/audit` requires auth, org-scoping, role gating, pagination.
- `test_campaign.py` (6 cases) — `/campaigns/execute/*` auth gating, cross-org 404, worker uses `OpenAIClient`.
- `test_ai_playbook.py` (6 cases) — transcript 404 for unknown / cross-tenant call ids, archived playbook → 422, unknown `when` keys rejected, prompt grammar with missing lead name.
- `test_security_and_misc.py` (5 cases) — async rate-limit window, exempt paths, Twilio production guard, branch validators.

`conftest.py` disables the rate limiter for the suite (`RATE_LIMIT_ENABLED=false`) and provides `unique_user` / `second_user` / `auth_headers` fixtures.

### G. External-service health check

A one-shot health probe lives at `scripts/healthcheck.py` (or `/tmp/aifficient-healthcheck/healthcheck.py` in dev). It hits lightweight endpoints on OpenAI, ElevenLabs, Deepgram, Twilio, LiveKit, SMTP and the public webhook URL, masks secrets, and prints a `VALID / INVALID / MISSING / DISABLED` verdict per service. Safe to run against production credentials.

### H. Deployment

See `docs/DEPLOY_AWS.md` for a step-by-step AWS guide (S3+CloudFront, App Runner, RDS, ElastiCache, Secrets Manager, LiveKit Cloud).

### I. Twilio webhook / ngrok wiring (dev)

Twilio reaches the backend via a reserved ngrok tunnel. Three things must agree on the port:

1. **`TWILIO_PUBLIC_BASE_URL`** in `backend/.env` — currently `https://handmade-agreed-dimple.ngrok-free.dev` (reserved domain).
2. **The Twilio number's "A Call Comes In" webhook** in the Twilio Console — `<TWILIO_PUBLIC_BASE_URL>/api/v1/telephony/webhooks/voice`, method `POST`.
3. **The actual uvicorn port** that ngrok forwards to. Dev convention is **`8001`**.

Start ngrok with the reserved domain bound to whichever uvicorn port you're running:

```bash
ngrok http --url=handmade-agreed-dimple.ngrok-free.dev 8001
```

Then start uvicorn on the same port:

```bash
cd backend && source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

Verify both legs are healthy:

```bash
curl -s -o /dev/null -w "local: %{http_code}\n" http://localhost:8001/api/v1/health
curl -s -o /dev/null -w "ngrok: %{http_code}\n" https://handmade-agreed-dimple.ngrok-free.dev/api/v1/health
# Webhook (unsigned probe) should return 403 "invalid X-Twilio-Signature" — that's correct.
curl -sS -X POST -d 'CallSid=PROBE' \
  https://handmade-agreed-dimple.ngrok-free.dev/api/v1/telephony/webhooks/voice
```

**Symptom of a misconfigured tunnel:** the caller hears Twilio's built-in fallback **"We're sorry, an application error has occurred. Goodbye."** immediately on answer. Twilio plays this whenever the voice webhook is unreachable / returns 5xx / returns invalid TwiML / times out (>15s). Diagnose by running the two `curl`s above — if the ngrok one fails or returns 502, ngrok and uvicorn are pointing at different ports.

> **Do not run the pm2 process `afficient-be` (port 20158) at the same time** as uvicorn on 8001 — only one of them can own the ngrok tunnel. Pick one. The pm2 entry is preserved for production-style runs; in dev keep it `stopped`.

---

## 13. Key Architectural Decisions

1. **Vertical-slice backend.** Each domain (`auth`, `members`, `campaign`, `livekit`, `tts`, …) owns its router/service/repository/model/schema. Cross-cutting helpers live under `common/`.
2. **Single FastAPI app, single SQLAlchemy session per request.** No microservices.
3. **Bearer + refresh JWTs.** Access in headers; refresh rows persisted server-side in `sessions` so logout can revoke. Tokens stored in browser `localStorage` (not httpOnly cookies).
4. **Multi-tenant via Memberships.** A user can belong to multiple orgs; `get_current_tenant` always picks the best one. RBAC roles: `owner`, `admin`, `agent`, `member`.
5. **LiveKit as the realtime transport.** Backend mints scoped JWTs per participant; the frontend joins via `livekit-client`. Local `livekit_sessions` table mirrors LiveKit state for attribution/observability.
6. **ElevenLabs streamed into LiveKit.** Backend joins a room as a hidden agent participant and pushes PCM frames — no audio storage required (see `modules/tts/streamer.py`).
7. **Deepgram subscribed from LiveKit.** Symmetric to TTS: backend joins as a subscribe-only agent, pulls PCM from the target participant, and forwards to Deepgram's streaming WS. Normalised `TranscriptEvent` (speech_started / partial / final / utterance_end) decouples the consumer from provider specifics (see `modules/stt/streamer.py`).
8. **GPT-4o conversation engine isolated in `modules/ai/`.** Composed of a thin async OpenAI client, a Redis-backed memory layer (history + meta + qualification under one TTL), a rule-based BANT/MEDDICC tracker, a prompt/persona registry, a service that orchestrates them, a synchronous repository that persists turns and summaries to Postgres, and an orchestrator that wires the live STT→LLM→TTS loop with barge-in. All HTTP edges go through `dependencies.py` which converts `AIError` → `HTTPException` so the API surface is predictable.
9. **Zustand over Redux/Context.** Small bespoke stores per concern; localStorage only for things that must survive reload (auth tokens, theme, density).
10. **Single axios instance.** All service modules share it; the interceptor centralizes auth, refresh, and 401 handling.
11. **Theme via next-themes + Tailwind v4 tokens.** A light-mode safety net in `index.css` lets legacy dark-only utility classes degrade gracefully in light mode without rewriting every component.
12. **Alembic for migrations.** 13 numbered revisions in `backend/migrations/versions/`; the source-of-truth is the ORM models. AI tables (`ai_calls`, `ai_transcript_entries`, `ai_call_summaries`) are FK'd to organizations and (optionally) users so transcripts are tenant-scoped.
13. **structlog for logs.** Console renderer in dev, JSON renderer in prod / when `LOG_JSON=true`. AI module emits structured events (`ai.call.started`, `ai.turn.done`, `ai.complete.done`, `ai.stream_collected.done`, `ai.finalize.done`) with latency, token counts, model, qualification score and TTFT for observability. Rate-limit middleware uses `rate_limit.exceeded` only on 429 (no per-request log noise).
14. **Rate limiting at the edge.** Async Redis sliding window scoped by **JWT subject when present, client IP otherwise**. Configurable per bucket: `RATE_LIMIT_REQUESTS` (default 300/min for API) and `RATE_LIMIT_AUTH_REQUESTS` (default 10/min for `/auth/login`, `/auth/register`, `/auth/refresh`). Exempts `/health`, `/`, `/api/v1/telephony/webhooks/*`, `/docs`, `/openapi.json`, `/redoc`, `/favicon.ico`, and all `OPTIONS` preflights. Disable via `RATE_LIMIT_ENABLED=false` in tests/load-gen.
15. **Production safety guards.** `main.py` lifespan emits `app.startup.unsafe` errors when `ENV=production` and any of: `TWILIO_VALIDATE_SIGNATURE=false`, `TWILIO_ACCOUNT_SID` starts with `ACdummy`, or `JWT_SECRET` is shorter than 32 chars. `TwilioClient.create_call` raises `TelephonyConfigError` instead of mock-originating when the SID is a dummy and `ENV=production`.
16. **Tenant isolation enforced at the row level.** Cross-tenant access to AI call transcripts, playbooks, telephony calls, campaigns, workflows and executions returns `404` (never `200` with empty data, never `500`). Audit log filters via the org's `Memberships` set; lower-role users only see their own audit rows.
17. **Mobile-first responsive UI.** The shell uses an off-canvas drawer below `lg` with body-scroll-lock and Esc/route-change auto-close, plus global `overflow-x: hidden` and `max-width: 100%` safety nets. Wide content (tables, tab strips, permission matrices) uses `overflow-x-auto` + `min-w` rather than collapsing. Layout state for the drawer lives in `store/ui.ts` (Zustand) so any descendant can toggle without prop drilling. See §9.5.
18. **Campaign dialing pipeline (campaign → scheduler → worker → telephony).** Activation (`CampaignService.activate`) only **enqueues** one `queued` Execution per lead (frozen lead+playbook context). A per-minute Celery Beat tick (`CampaignScheduler.tick`) auto-activates due campaigns and **paces** dispatch within business hours, then calls the in-process worker. `run_execution` (`modules/campaign/worker.py`) places a **real outbound call** via `TelephonyService.initiate_outbound` for any lead execution when `CAMPAIGN_TELEPHONY_DIALING_ENABLED` is on — creating a `telephony_calls` row, a LiveKit room + AI agent, and a Twilio Call SID (or a LiveKit SIP leg when an outbound trunk is configured and AMD is off). The execution is left `running`; its terminal outcome is **reconciled asynchronously** by the Twilio status webhook (`TelephonyService._reconcile_campaign_execution`), which runs the retry engine so metrics/retries advance. **No silent LLM fallback:** dial failures (telephony unavailable, Twilio/LiveKit errors, undiallable lead) mark the execution `failed` via `process_outcome` (retry scheduled when configured) and log `CAMPAIGN_DIAL_FAILED` / `CAMPAIGN_DIAL_EXCEPTION`. The legacy LLM-plan path only runs for non-dial (generic) executions or when dialing is disabled.

---

## 14. Known Issues / Technical Debt (visible in code)

These are real items found while scanning the repo, not speculation.

### Backend

- **Secrets committed to `backend/.env`.** ElevenLabs API key, Gmail SMTP app password, JWT secret, LiveKit dev secret, **OpenAI API key**, and **Deepgram API key** are present in the working tree. Must be rotated before public deployment and removed from history.
- **Twilio credentials are dummies** (`ACdummy.../dummy_token`). Real PSTN origination is disabled in production by `TelephonyConfigError`; replace with real SID/token before any outbound calling.
- **`TWILIO_PUBLIC_BASE_URL` is unset.** Webhook URLs registered with Twilio fall back to `request.url.netloc`, which won't work behind a private host. Required for production.
- **`TWILIO_VALIDATE_SIGNATURE=false` by default.** Production startup logs an error; flip to `true` once a public URL exists.
- **ElevenLabs voice id mismatch.** `.env` ships a voice id (`21m00Tcm4TlvDq8ikWAM`) that's not in the configured account — runtime TTS falls back to the default voice. Update `ELEVENLABS_VOICE_ID` or remove it.
- **CORS allowlist is dev-only** (`main.py` allows `localhost:5173/5174` plus `localhost:20197`). Production frontend origins must be added.
- **Two backend launch paths can race for the ngrok tunnel.** The pm2 entry `afficient-be` binds port **20158**, but the dev convention is `uvicorn ... --port 8001`. Only one can be live at a time, and the reserved ngrok URL (`handmade-agreed-dimple.ngrok-free.dev`) must be pointed at the matching port — otherwise Twilio webhooks fail and callers hear Twilio's default error message. See §12.I for the canonical dev wiring.
- **`get_current_org` (`modules/auth/dependencies.py`) is a stub** that returns `{"organization":"current"}` regardless of the user. The AI / campaign / playbook modules sidestep this by reading `organization_id` directly from the tenant dict in their routers. Should be removed or made real.
- **`run_execution` (`modules/campaign/worker.py`) still runs in-process** (driven by the Celery Beat scheduler tick / request handler), not as a distributed task per call. Fine for current pacing, but a high-throughput campaign relies on the tick cadence + pacing budget rather than a fan-out worker pool.
- **Duplicate `get_db`** helpers in `database/session.py` and `database/dependencies.py`.
- **`prometheus-fastapi-instrumentator` is in `requirements.txt` but is not registered** in `main.py`.
- **Celery Beat tick must be running for scheduled/paced dialing.** `modules/campaign/{celery_app,tasks}.py` define the `campaign.scheduler_tick` task; if no Celery worker+beat is running, campaigns still activate (which enqueues executions) but paced auto-dispatch won't fire. See `scripts/ensure-scheduler.sh`.
- **JWT uses `datetime.utcnow()`** which is deprecated in Python 3.12; should migrate to `datetime.now(timezone.utc)`.
- **`backend/next-app/`** appears unused (no source, only config files).
- **`/ai/generate` and `/ai/converse` do not stream responses to the HTTP client** even though the underlying `OpenAIClient` supports streaming (`stream_collected`). The orchestrator uses streaming internally for TTFT, but the public REST endpoints buffer the full reply. Add SSE/chunked endpoints if the frontend wants token-by-token rendering.
- **No automated tests for `ConversationOrchestrator`.** It is exercised manually via `scripts/run_ai_agent.py`; barge-in correctness is not regression-protected.
- **`pytest` / `pytest-asyncio` not yet pinned in `requirements.txt`.** Test suite runs locally but CI will need them added.

### Frontend

- **`Login.tsx`, `Signup.tsx`, `Dashboard.tsx`, `Calls.tsx` and others contain large commented-out legacy code blocks.** Pure clutter; safe to delete.
- **`VITE_API_URL` default** in `services/auth.ts` points at `http://localhost:8001/api/v1`, but the backend may run on 8000 (Docker), 8001, or 8002 depending on dev workflow. The current Vite dev port is 20197. Always set `VITE_API_URL` in `frontend/.env` to match.
- **`Leads` and `Analytics` pages still use mock data only.** No services or stores yet. (Transcripts and Calls are now real.)
- **`useAuth` does not persist via Zustand's `persist` middleware** — it reads/writes localStorage manually. Works, but slightly inconsistent with `useAppearance` which uses the same pattern.
- **No global error boundary.** Unhandled render errors will white-screen the SPA.
- **Bundle size warning at build time** (~1.1 MB JS, ~320 KB gzipped). Consider route-level code splitting via `React.lazy` once pages have real backend wiring.
- **`AuthTokens` shape** assumes `{ access_token, refresh_token }` — backend's `/auth/refresh` returns only `{ access_token }`, which the interceptor correctly handles. Documenting here so future changes don't break refresh.
- **Node 20.18.2 in the dev environment** is below Vite 8's recommended `20.19+ / 22.12+` — Vite still runs but prints a warning at startup.

### Resolved (kept for trace, do not re-open without re-checking)

- ~~Launching a campaign placed no real calls (worker ran the LLM stub).~~ Root cause: `worker._campaign_dial_context` referenced `campaign.created_by`, a column the `Campaign` model doesn't have; the `AttributeError` was swallowed by the dial `try/except`, silently falling back to the LLM plan on every lead. Fixed (`created_by=None`); dialing now reaches `TelephonyService.initiate_outbound`. Covered by `tests/api/test_campaign_dialing_e2e.py`.
- ~~Dial failures silently completed via the LLM fallback.~~ Removed. Dial candidates never fall back to the LLM: failures mark the execution `failed` via the retry engine (retry scheduled when configured), log `CAMPAIGN_DIAL_FAILED` / `CAMPAIGN_DIAL_EXCEPTION`, and surface in metrics (`failed_calls`, new `failed_executions`). Covered by the telephony-unavailable / Twilio / LiveKit / invalid-phone cases in `tests/api/test_campaign_dialing_e2e.py`.
- ~~`AIProvider.generate` is a stub.~~ Replaced; `modules/ai/provider.py` now delegates to `OpenAIClient.agenerate`. The legacy `AIService.execute(prompt)` shim is preserved for the campaign worker.
- ~~No real LLM integration.~~ Full GPT-4o engine landed: `/ai/generate`, `/ai/converse`, BANT/MEDDICC qualification, Redis memory, Postgres transcripts and summaries, live orchestrator.
- ~~Transcripts page uses mock data only.~~ Now backed by `GET /ai/calls` + `GET /ai/calls/{id}/transcript`.
- ~~`GET /auth/audit` returns every tenant's audit log, unauthenticated, no pagination.~~ Now requires JWT, scopes by org membership (owners/admins) or self (agents/members), paginated via `AuditListResponse`.
- ~~`/campaigns/execute/{wf}` and `/campaigns/executions/{id}` accept no auth.~~ Now gated by `requires(Role.OWNER, Role.ADMIN, Role.AGENT)` and tenant-joined.
- ~~Campaign worker crashes (`AIService.execute` missing).~~ Worker rewritten against `OpenAIClient.complete`; `CampaignService.execute` deduplicated and made async.
- ~~Login with wrong credentials returns 200.~~ Returns 401; user enumeration mitigated via constant-time bcrypt verify on missing-user path.
- ~~Duplicate registration crashes with 500.~~ Returns 409 with a clean message.
- ~~No password strength validation.~~ `RegisterInput` enforces min length + character classes via `field_validator`.
- ~~`/ai/converse` returns 500 on inactive playbook.~~ Catches `PlaybookError` and surfaces 422.
- ~~Cross-tenant transcript read returns 200 with empty payload.~~ Returns 404.
- ~~`/ai/calls` does N+1 DB hits.~~ Bulk-fetch summaries and playbooks; constant queries.
- ~~Rate limit too aggressive, blocking `/health`, logging via `print()`.~~ Rewritten async, JWT-scoped, path-exempt, structlog-only.
- ~~Playbook branch matcher silently accepts unknown `when` keys.~~ Whitelisted; unknown keys → 422.
- ~~`{lead_name}` defaults to `"there"` producing broken sentences.~~ Defaults to `"the prospect"`.
- ~~Twilio mock-origination silently triggered in production.~~ Raises `TelephonyConfigError` when `ENV=production`.
- ~~Frontend `npm run build` fails on TS6 `baseUrl` deprecation + unused identifiers.~~ Removed `baseUrl`, cleaned imports/vars; `tsc -b && vite build` is clean.

---

## 🔄 Maintenance Instructions

This file is **living documentation**. Treat it the same way you treat code — when behavior changes, this file must change in the same commit.

**Update `KNOWLEDGE.md` whenever you modify any of:**

- **Folder structure** (new module, renamed folder, moved files)
- **API / services layer** (new endpoint, changed contract, new service file)
- **Routing / pages** (new route, removed route, protection changed)
- **State management** (new Zustand store, changed persistence, new selector helper)
- **Authentication / RBAC logic** (new role, new dependency, changed token lifecycle)
- **Theme system** (new theme tokens, density options, theme-related CSS rules)
- **Core features** (new module, removed module, materially changed behavior)
- **Environment variables** (new required var, default change, new optional integration)
- **Database schema / migrations** (new model, new revision)
- **External integrations** (LiveKit, ElevenLabs, SMTP, future LLM providers)

**Workflow for any change:**

1. Make the code change.
2. Update the relevant section in `KNOWLEDGE.md`.
3. If you introduced or resolved technical debt, update §14 accordingly.
4. Commit both together.

**For AI agents:** When you modify this codebase, you are responsible for keeping `KNOWLEDGE.md` accurate. If you make a change that affects any of the categories above and you do not update this file, the change is incomplete.

**Do not:**

- Speculate about unimplemented features as if they exist.
- Remove entries from §14 just because the file is getting long — close them by fixing the code instead.
- Duplicate full code listings here; reference file paths and key behavior only.

If something is genuinely unclear from reading the code, write **"Not clearly defined in code"** rather than guessing.

---

*Last full review: 2026-06-01 — covers the post-E2E security and stability pass: hardened `/auth/audit`, `/campaigns/*`, `/ai/calls/*/transcript`; proper HTTP semantics for login/register/refresh/logout; password strength rules; campaign worker rebuilt on `OpenAIClient`; async/JWT-scoped Redis rate limiter with path exemptions; playbook branch-key whitelist; Twilio production guards; N+1 fix on `/ai/calls`; frontend `tsc -b && vite build` clean; new pytest suite (`backend/tests/`, 29 cases); external-service `healthcheck.py`. Re-scan whenever you suspect drift.*

*2026-06-02 — added §12.I (Twilio webhook / ngrok wiring) and a §14 note covering the pm2-20158 vs uvicorn-8001 port mismatch that caused "We're sorry, an application error has occurred." on inbound calls. Dev convention is now: ngrok `handmade-agreed-dimple.ngrok-free.dev` → uvicorn on port `8001`; keep pm2 `afficient-be` stopped while running dev uvicorn.*

*2026-06-02 — frontend responsive overhaul: every page and the layout shell now adapts cleanly from 360px phones up through 4K desktops. New `store/ui.ts` Zustand store drives an off-canvas mobile drawer; `Sidebar` and `Header` were refactored to consume it. Added global `overflow-x: hidden` / `max-width: 100%` safety nets in `index.css`. Tables and tab strips use horizontal scroll instead of collapsing. New documentation section: `pages/Documentation.tsx` mounted at `/documentation` (protected), reachable from the avatar dropdown in `Header.tsx`. See new §9.5 (Responsive Design) and updated §3/§4/§5/§6/§13.*

*2026-06-06 — Phase 1 Lead Management implemented. Backend: `modules/leads/` rewritten with new schema (`first_name`, `last_name`, `email`, `phone`, `linkedin_url`, `company`, `job_title`, `status`, `tags`, `extra_data`); `Lead ↔ LeadList` is now many-to-many via `lead_list_memberships` join table (replacing the old direct FK); `lead_activities` removed from Phase 1; full CRUD + search + pagination + phone-dedup + audit logging (`LEAD_CREATED/UPDATED/DELETED/LEAD_LIST_CREATED`); `PATCH /lead-lists/{id}` and `DELETE /lead-lists/{id}` added; migration `o1p2q3r4s5t6_rebuild_leads` migrates the existing tables. Frontend: `types/lead.ts`, `services/lead.ts`, `pages/Leads.tsx`, `components/leads/LeadFormDialog.tsx`, `components/leads/LeadDetailsDialog.tsx` all updated for new field names. Leads page now wired to the real backend.*

*2026-06-05 — campaign dialing pipeline audit + fix. (1) Root cause of "campaign launches but no calls": `worker._campaign_dial_context` referenced a non-existent `Campaign.created_by`; the `AttributeError` was swallowed by the dial `try/except`, silently falling back to the LLM stub on every lead. Fixed to `created_by=None`, so activation → scheduler → worker now actually calls `TelephonyService.initiate_outbound` (Twilio Call SID or LiveKit SIP leg, `telephony_calls` populated, status webhooks reconcile outcomes). (2) Removed the silent LLM fallback for dial failures: lead executions now fail via the retry engine (retry scheduled when configured) and log `CAMPAIGN_DIAL_FAILED` / `CAMPAIGN_DIAL_EXCEPTION`; the LLM-plan path is reserved for non-dial/generic executions or when dialing is disabled. (3) Added `failed_executions` to campaign metrics. New env var `CAMPAIGN_TELEPHONY_DIALING_ENABLED` (default false; `true` in `backend/.env`). New tests: `tests/api/test_campaign_dialing_e2e.py` (success Twilio + LiveKit-SIP paths, telephony-unavailable, Twilio failure, LiveKit failure, invalid phone). See updated §1/§3/§4/§11/§13/§14.*
