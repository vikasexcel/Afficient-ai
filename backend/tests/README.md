# Aifficient Test Suite

End-to-end test + benchmark harness for the implemented surfaces of the
Aifficient backend (auth, leads, playbook, AI, LiveKit, STT, TTS,
telephony, campaign, members, health).

```
tests/
├── _support/                # benchmark recorder, reporter, in-process fakes
├── unit/                    # pure-Python tests (no DB, Redis, network)
├── integration/             # DB + Redis + cross-service flows
├── api/                     # FastAPI TestClient HTTP coverage
├── performance/             # throughput / concurrency benchmarks
├── latency/                 # per-call latency benchmarks + p50/p95/p99
└── reports/                 # latency_report.json + performance_report.html
```

The original behaviour-driven cases (`test_auth.py`, `test_ai_playbook.py`,
`test_campaign.py`, `test_security_and_misc.py`) live at the package
root unchanged.

---

## Prerequisites

1. Postgres + Redis running on the host:port from `backend/.env`
   (`docker-compose up -d` inside `backend/` handles both).
2. `pip install -r requirements.txt` (already includes `pytest` and
   `pytest-asyncio`; nothing new is required by this suite).
3. Optional: set provider API keys when you want to record real-provider
   latency (OpenAI, Deepgram, ElevenLabs, LiveKit, Twilio).

---

## Quick start

```bash
cd backend
source venv/bin/activate

# Default suite: unit + integration + api.
pytest

# Run by directory.
pytest tests/unit
pytest tests/integration
pytest tests/api
pytest tests/performance
pytest tests/latency

# Run by marker (markers are registered in pytest.ini).
pytest -m unit
pytest -m "integration and not external"
pytest -m "performance or latency"

# Performance + latency benchmark in one shot (recommended).
./scripts/run_benchmarks.sh
```

Reports are written to:

- `backend/tests/reports/latency_report.json`
- `backend/tests/reports/performance_report.html`

The console summary at the end of every benchmark run prints the same
data.

---

## What gets measured

Every latency / performance benchmark records its samples into a
shared `BenchmarkRecorder` so the session-end hook can roll them up
into:

- count / successes / failures
- avg / min / max / p50 / p95 / p99
- success rate / failure rate

The categories that the JSON / HTML reports group by are:

| Category | What's measured |
|---|---|
| `api` | FastAPI endpoints via `TestClient` |
| `db` | SQLAlchemy session + common queries |
| `redis` | sync + async PING, SET/GET, ConversationMemory, rate limiter |
| `auth` | bcrypt + full register → login → me round-trip |
| `jwt` | JWT signing + decoding |
| `livekit` | token mint (hermetic) + room CRUD (live) |
| `openai_gpt` | OpenAIClient.complete + stream_collected |
| `deepgram_stt` | event iteration + speech-started → partial |
| `elevenlabs_tts` | stream_pcm full + TTFB |
| `twilio` | TwiML build + create_call (fake + live) |
| `voice_pipeline` | STT → AI → TTS end-to-end (fake) |
| `barge_in` | cooldown gate, interrupt(), InterruptionLog write |
| `perf` | concurrent throughput tests |

SLO thresholds are declared in `tests/_support/reporter.py`. P95/P99
cells exceeding the SLO are highlighted in red on the HTML report.

---

## Live-provider benchmarks (opt-in)

Provider calls are skipped by default so the suite stays hermetic and
deterministic. Flip them on individually with environment variables:

```bash
# Master switch — turns on every provider benchmark.
RUN_EXTERNAL_BENCH=1 pytest -m latency

# Or per-provider.
RUN_OPENAI_BENCH=1     pytest tests/latency/test_latency_openai.py
RUN_DEEPGRAM_BENCH=1   pytest tests/latency/test_latency_deepgram.py
RUN_ELEVENLABS_BENCH=1 pytest tests/latency/test_latency_elevenlabs.py
RUN_LIVEKIT_BENCH=1    pytest tests/latency/test_latency_livekit.py
RUN_TWILIO_BENCH=1     pytest tests/latency/test_latency_twilio.py
```

⚠ The Twilio live benchmark **places real PSTN calls** (immediately
hung up). Only enable when you've set `BENCH_TWILIO_TO_NUMBER` to a
number you control and you accept the per-call charge.

---

## Tuning iteration counts

Every latency / perf module reads an environment variable for its
iteration count so you can scale runs up/down without editing source:

| Variable | Default | What it controls |
|---|---|---|
| `BENCH_API_ITERATIONS` | 30 | API endpoint latency loops |
| `BENCH_DB_ITERATIONS` | 30 | DB query latency loops |
| `BENCH_REDIS_ITERATIONS` | 50 | Redis op latency loops |
| `BENCH_JWT_ITERATIONS` | 200 | JWT create/decode loops |
| `BENCH_BCRYPT_ITERATIONS` | 5 | bcrypt hash/verify loops |
| `BENCH_AUTH_ITERATIONS` | 10 | register/login/me round-trips |
| `BENCH_LIVEKIT_TOKEN_ITERATIONS` | 100 | token minting |
| `BENCH_LIVEKIT_ROOM_ITERATIONS` | 5 | live room CRUD |
| `BENCH_OPENAI_FAKE_ITERATIONS` | 20 | fake-mode GPT |
| `BENCH_OPENAI_LIVE_ITERATIONS` | 3 | live-mode GPT |
| `BENCH_DEEPGRAM_FAKE_ITERATIONS` | 20 | fake STT |
| `BENCH_ELEVENLABS_FAKE_ITERATIONS` | 20 | fake TTS |
| `BENCH_ELEVENLABS_LIVE_ITERATIONS` | 3 | live TTS |
| `BENCH_TWILIO_FAKE_ITERATIONS` | 30 | fake Twilio |
| `BENCH_TWILIO_LIVE_ITERATIONS` | 2 | live Twilio |
| `BENCH_VOICE_PIPELINE_ITERATIONS` | 10 | end-to-end voice loop |
| `BENCH_BARGE_IN_ITERATIONS` | 30 | barge-in path |
| `PERF_API_CONCURRENCY` / `PERF_API_REQUESTS` | 8 / 80 | API burst |
| `PERF_DB_CONCURRENCY` / `PERF_DB_REQUESTS` | 8 / 80 | DB burst |
| `PERF_REDIS_CONCURRENCY` / `PERF_REDIS_REQUESTS` | 16 / 300 | Redis burst |
| `PERF_JWT_CONCURRENCY` / `PERF_JWT_REQUESTS` | 16 / 400 | JWT burst |
| `PERF_CSV_ROWS` | 1000 | CSV parser load |

---

## CI notes

The benchmark suite is safe to run in CI — no external network is
required by default. If your CI image has Postgres + Redis side-cars
(see `backend/docker-compose.yml`) the full unit + integration + api +
performance + latency run should finish in under a minute.

To gate a PR on a P99 regression, parse `tests/reports/latency_report.json`
and assert against the `slo_breach` flags.
