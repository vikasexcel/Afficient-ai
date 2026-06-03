# AI Phone Calling — Multi-Turn Conversation Fix

This document covers the investigation, root-cause analysis, the changes
that make outbound/inbound calls hold a natural multi-turn conversation,
and how to test it end-to-end.

---

## 1. Root Cause Analysis

The conversation engine (`ConversationOrchestrator`), `AIService`
(GPT-4o + Redis memory + transcript/summary persistence), Deepgram STT,
ElevenLabs TTS, and the per-call `CallAgentRunner` were **already fully
multi-turn capable**. The break was in the *integration* between the
telephony layer and the live loop. Three concrete defects compounded
into "AI speaks the opening line, then the conversation stops".

### RC-1 — Opening line played to an empty room (timing)
`TelephonyService.initiate_outbound` registers the `CallAgentRunner`
(which connects the agents to LiveKit and immediately speaks the opening
line) **before** Twilio dials and ~10–30s before the lead answers. The
orchestrator spoke the ElevenLabs opener into a room that contained only
agents. The lead never heard the real pipeline opener.

### RC-2 — STT transcribed the agent's own voice (self-echo feedback loop)
The orchestrator opened the STT session with `target_participant=None`.
`AudioTransport.iter_audio(None)` fans out audio from **every** remote
participant — including the TTS agent (`ai-agent`) publishing the
agent's own voice. Deepgram therefore transcribed the agent's own
speech, which:
- triggered self **barge-in** (the agent cut itself off mid-utterance), and
- fed the agent's own words back into `respond_turn`.

The genuine human turns were never cleanly processed, so the back-and-forth
collapsed and the call eventually hit the idle timeout.

### RC-3 — Duplicate opener via Twilio `<Say>` (masking)
`build_voice_twiml` emitted `<Say>{opening_line}</Say>` before
`<Dial><Sip>`. The lead heard Twilio's built-in TTS opener (a different
voice), which masked the fact that the LiveKit pipeline opener never
reached anyone.

### Investigation answers
| Question | Finding |
|---|---|
| Is `ConversationOrchestrator` started? | **Yes**, via `CallAgentRunner` in `initiate_outbound` — but too early (before the human joins). |
| Is Deepgram receiving caller audio? | **Partially** — it received *all* room audio, including the agent's own TTS, not the isolated caller. |
| Is GPT receiving transcripts? | **Yes**, but contaminated with the agent's own speech. |
| Is ElevenLabs generating after the opener? | It tried, but self-barge-in interrupted it and the opener had played to an empty room. |
| Where does it stop? | Immediately after the opener — the human↔AI loop never cleanly started (RC-1 + RC-2). |

---

## 2. The Fix

### Isolate the caller's audio (RC-2)
`AudioTransport` now accepts `ignore_identities`. Tracks published by
those identities (our TTS/STT agents) are **never** pumped into the
inbound queues, so Deepgram only ever hears the human. The orchestrator
computes the ignore set from the STT/TTS streamers' `agent_identity` and
passes it into the STT session.

### Gate the opening line on the human joining (RC-1)
`AudioTransport` exposes `find_human_identity()` (prefers a
`PARTICIPANT_KIND_SIP` participant, falls back to any non-agent remote)
and `wait_for_remote()`. `TTSSession.wait_for_human()` surfaces this. The
orchestrator (`_await_human_then_open`) waits up to
`wait_for_human_seconds` for the caller, logs `CALL_ANSWERED`, locks STT
onto that participant, and only **then** speaks the ElevenLabs opener.
The wait degrades gracefully (speaks anyway on timeout) so there's never
dead air on a stuck call.

### Stop the duplicate opener (RC-3)
`TelephonyService.handle_inbound_voice` now returns no `opening_say`, so
the TwiML contains only `<Dial><Sip>`. The AI agent is the single source
of the opener (ElevenLabs). `build_voice_twiml` is unchanged and still
supports `opening_say` for explicit callers.

### Multi-turn, memory, transcripts, summary
These already worked and are unchanged in behaviour:
- `AIService.respond_turn` loads the full Redis history every turn
  (`snapshot.history` → `build_messages`).
- Each turn persists user + assistant rows to `ai_transcript_entries`.
- `finalize_call` generates the GPT summary and writes
  `ai_call_summaries` with token/turn totals + qualification.

### Meeting status (PLACEHOLDER only)
New `modules/ai/meeting.py` tracks `unknown → not_booked → booked` with a
conservative, deterministic heuristic (lead confirmation **in a
scheduling context**). The orchestrator logs every transition as
`MEETING_STATUS_UPDATED` and `[MEETING_STATUS] <status>`, persists it to
Redis meta, and `finalize_call` records it on the summary row
(`extra.meeting_status`) and prepends it to the summary text. **No
scheduling, calendar, or booking workflow is implemented.**

### Structured logs (requirement 8)
The orchestrator now emits the named lifecycle tokens:
`CALL_STARTED`, `CALL_ANSWERED`, `LIVEKIT_CONNECTED`,
`ORCHESTRATOR_STARTED`, `STT_TRANSCRIPT_RECEIVED`,
`GPT_RESPONSE_GENERATED`, `TTS_AUDIO_GENERATED`, `AUDIO_PUBLISHED`,
`TRANSCRIPT_SAVED`, `MEETING_STATUS_UPDATED`, `CALL_ENDED`.

### Error handling / recovery (requirement 7)
Pre-existing and retained: GPT retries + per-turn deadline → `RECOVERY`
line; TTS failure → recovery; STT websocket auto-reconnect; LiveKit/Twilio
disconnects signal the runner to finalize (summary still written). The
new human-wait and meeting-status paths are wrapped in best-effort
guards so they can never crash a live call.

---

## 3. Architecture (end-to-end call flow)

```
User clicks "Place Call"
  → POST /api/v1/telephony/calls
  → TelephonyService.initiate_outbound
      1. insert telephony_calls row
      2. ensure LiveKit room
      3. register CallAgentRunner  ── spawns ConversationOrchestrator
         │                              • TTS agent joins room (publishes)
         │                              • STT agent joins room (subscribe,
         │                                ignores agent identities)
         │                              • start_call → Redis meta + ai_calls row
         │                              • waits for human to join
      4. Twilio.calls.create(url=/webhooks/voice, statusCallback=/webhooks/status)
  → Twilio dials the destination
  → Lead answers → Twilio fetches /webhooks/voice
      → TwiML: <Dial answerOnBridge><Sip>sip:{room}@{LIVEKIT_SIP_URI}</Sip></Dial>
  → LiveKit SIP gateway bridges the PSTN leg into the room (SIP participant)
  → Orchestrator detects the SIP participant  ── CALL_ANSWERED
      → speaks opening line (ElevenLabs)        ── TTS_AUDIO_GENERATED / AUDIO_PUBLISHED
  ── loop ────────────────────────────────────────────────────────────────
  Human speaks → Deepgram (caller audio only)   ── STT_TRANSCRIPT_RECEIVED
      → AIService.respond_turn (GPT-4o + full Redis history + playbook)
                                                 ── GPT_RESPONSE_GENERATED
      → persists transcript rows                 ── TRANSCRIPT_SAVED
      → meeting-status heuristic                 ── MEETING_STATUS_UPDATED
      → ElevenLabs TTS into room                 ── TTS_AUDIO_GENERATED / AUDIO_PUBLISHED
  barge-in: human speaks over agent → TTS interrupt (caller audio only)
  ── repeat until ────────────────────────────────────────────────────────
  caller hangs up | agent ends (disqualified / branch) | idle timeout | fatal error
  → Twilio /webhooks/status (terminal) → registry.stop(room)
  → orchestrator exits → finalize_call
      → GPT summary + ai_call_summaries (+ meeting_status)  ── CALL_ENDED
```

Component map:
- **Twilio outbound** — `modules/telephony/twilio_client.py`, `service.py`, `router.py`
- **LiveKit transport / SIP** — `modules/livekit/transport.py`, `service.py`
- **Deepgram STT** — `modules/stt/streamer.py`, `deepgram_client.py`
- **GPT-4o engine + memory + persistence** — `modules/ai/service.py`, `memory.py`, `openai_client.py`, `repository.py`
- **Orchestrator (the live loop)** — `modules/ai/orchestrator.py`
- **ElevenLabs TTS** — `modules/tts/streamer.py`, `elevenlabs_client.py`
- **Per-call runner / registry** — `modules/telephony/agent_runner.py`
- **Playbook** — `modules/playbook/*` (persona, opener, framework, branches, context)
- **Meeting status (placeholder)** — `modules/ai/meeting.py`

---

## 4. Modified / Added Files

| File | Change |
|---|---|
| `backend/modules/livekit/transport.py` | `ignore_identities` (skip agent's own track in STT); `participant_connected` wiring; `find_human_identity()` (SIP-first); `wait_for_remote()`. |
| `backend/modules/stt/streamer.py` | `agent_identity` property; `open_session(ignore_identities=...)` → transport. |
| `backend/modules/tts/streamer.py` | `agent_identity` property; `TTSSession.wait_for_human()`. |
| `backend/modules/ai/orchestrator.py` | Compute agent ignore-set; pass to STT; gate opener on human-join; lock STT onto caller; all named lifecycle logs; meeting-status tracking; `wait_for_human_seconds`; pass `meeting_status` to `finalize_call`. |
| `backend/modules/ai/service.py` | `finalize_call(meeting_status=...)` → summary text prefix + `ai_call_summaries.extra`; meta fallback. |
| `backend/modules/ai/meeting.py` | **New.** Placeholder meeting-status constants + `detect_status()` heuristic. |
| `backend/modules/telephony/service.py` | `handle_inbound_voice` returns no `opening_say` (no duplicate Twilio opener). |
| `backend/modules/telephony/agent_runner.py` | `wait_for_human_seconds` field (default 45s) → orchestrator. |
| `backend/scripts/run_ai_agent.py` | `AI_AGENT_WAIT_FOR_HUMAN_SECONDS` env → orchestrator. |

No DB migration needed — `ai_call_summaries.extra` (JSON) already exists.

---

## 5. End-to-End Testing Guide

### A. Automated (no external services)
```bash
cd backend
source venv/bin/activate
python scripts/test_barge_in_unit.py          # orchestrator loop + barge-in + recovery
python -m pytest -m "unit or api" -q           # full unit + api suites
```
All pass (orchestrator 17/17; unit+api 136/136).

### B. Local browser conversation (real GPT/STT/TTS, no phone)
```bash
# 1. infra
docker compose up -d postgres redis livekit
# 2. secrets in backend/.env
#    OPENAI_API_KEY, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY, LIVEKIT_*
# 3. run the agent worker (waits for you to join)
cd backend && source venv/bin/activate
AI_AGENT_WAIT_FOR_HUMAN_SECONDS=60 python scripts/run_ai_agent.py --room demo-room
# 4. mint a token: POST /api/v1/livekit/tokens {room: "demo-room", identity: "me"}
# 5. join demo-room (meet.livekit.io/custom) and talk.
```
Expect: the opener fires **after** you join; you can interrupt (barge-in);
multi-turn continues; on exit the worker prints turn stats.

### C. Full telephony (Twilio + LiveKit SIP)
Prereqs: `TWILIO_*` real creds, `TWILIO_PUBLIC_BASE_URL` (public HTTPS, e.g.
ngrok), and `LIVEKIT_SIP_URI` wired to the LiveKit SIP gateway/trunk.
```bash
curl -X POST $BASE/api/v1/telephony/calls \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"to_number":"+1...","playbook_id":"<uuid>"}'
```
Watch backend logs for the lifecycle tokens in order:
```
CALL_STARTED → LIVEKIT_CONNECTED → CALL_ANSWERED → ORCHESTRATOR_STARTED
→ STT_TRANSCRIPT_RECEIVED → GPT_RESPONSE_GENERATED → TRANSCRIPT_SAVED
→ TTS_AUDIO_GENERATED → AUDIO_PUBLISHED → [MEETING_STATUS] ... → CALL_ENDED
```
Verify:
- Answer the call → you hear the **ElevenLabs** opener (single voice) right
  after pickup, then a natural back-and-forth.
- `GET /api/v1/telephony/calls/{id}/events` shows the lifecycle.
- `ai_transcript_entries` has a row per turn; `ai_call_summaries` has the
  summary + `extra.meeting_status` after the call ends.
- Say "yes, Tuesday at 10am works for the demo" → logs show
  `[MEETING_STATUS] booked` and it appears in the summary.

### Troubleshooting
- **Opener but silence after** → check `LIVEKIT_SIP_URI` and that the SIP
  participant actually joins (`participant_connected` log with `kind=3`).
- **Agent talks to itself** → confirm `LIVEKIT_CONNECTED` log lists the TTS
  identity under `ignored_agents`.
- **No transcripts** → check Deepgram key + that STT sample rate matches the
  inbound track; look for `stt.deepgram.session.opened`.
