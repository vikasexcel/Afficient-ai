from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "AIFFICIENT"
    ENV: str = "development"

    POSTGRES_DB: str = "aifficient"
    POSTGRES_USER: str = "admin"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 20190

    DATABASE_URL: str
    REDIS_URL: str

    API_PREFIX: str = "/api/v1"
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "Aifficient"
    APP_LOGIN_URL: str = "http://localhost:5173/login"

    # LiveKit
    LIVEKIT_URL: str = "ws://localhost:7880"
    LIVEKIT_API_KEY: str = ""
    LIVEKIT_API_SECRET: str = ""
    LIVEKIT_TOKEN_TTL_MINUTES: int = 60
    LIVEKIT_DEFAULT_EMPTY_TIMEOUT: int = 300
    LIVEKIT_DEFAULT_MAX_PARTICIPANTS: int = 20

    # ElevenLabs TTS
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""
    ELEVENLABS_MODEL_ID: str = "eleven_turbo_v2_5"
    ELEVENLABS_SAMPLE_RATE: int = 24000
    ELEVENLABS_AGENT_IDENTITY: str = "ai-agent"
    ELEVENLABS_AGENT_NAME: str = "AI Agent"
    # Output format used for in-browser voice previews (an mp3 profile the
    # ElevenLabs SDK can emit and an <audio> element can play directly).
    ELEVENLABS_PREVIEW_FORMAT: str = "mp3_44100_128"
    # Optional JSON array overriding/extending the curated voice registry.
    # See modules.tts.voice_registry. Empty string = use built-in defaults.
    TTS_VOICE_REGISTRY_JSON: str = ""

    # Deepgram STT
    DEEPGRAM_API_KEY: str = ""
    DEEPGRAM_MODEL: str = "nova-3"
    DEEPGRAM_LANGUAGE: str = "en"
    DEEPGRAM_INTERIM_RESULTS: bool = True
    DEEPGRAM_VAD_EVENTS: bool = True
    DEEPGRAM_ENDPOINTING_MS: int = 300
    DEEPGRAM_UTTERANCE_END_MS: int = 1000
    DEEPGRAM_SMART_FORMAT: bool = True
    DEEPGRAM_PUNCTUATE: bool = True
    DEEPGRAM_STT_AGENT_IDENTITY: str = "ai-stt-agent"
    DEEPGRAM_STT_AGENT_NAME: str = "AI STT Agent"

    # OpenAI / GPT-4o conversation engine
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str | None = None
    OPENAI_ORG_ID: str | None = None
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_TEMPERATURE: float = 0.4
    OPENAI_MAX_TOKENS: int = 320
    OPENAI_TIMEOUT_SECONDS: float = 30.0
    OPENAI_MAX_RETRIES: int = 2
    AI_MEMORY_TTL_SECONDS: int = 60 * 60 * 6  # 6h
    AI_MEMORY_MAX_TURNS: int = 24  # rolling window (user+assistant pairs)
    AI_QUALIFICATION_FRAMEWORK: str = "BANT"  # or MEDDICC
    AI_DEFAULT_PERSONA: str = "outbound_sdr"

    # ------------------------------------------------------------------
    # Interruption / recovery (barge-in pipeline)
    # ------------------------------------------------------------------

    # Use a Deepgram PARTIAL transcript with non-empty text as a *second*
    # barge-in trigger (in addition to SPEECH_STARTED). Improves
    # detection latency on carriers where VAD events are slow.
    BARGE_IN_ON_PARTIAL: bool = True
    # Minimum characters in a PARTIAL to count as user speech (filters
    # noise-driven false positives). Effective only when BARGE_IN_ON_PARTIAL.
    BARGE_IN_PARTIAL_MIN_CHARS: int = 2
    # Barge-in on PSTN/phone-dialer calls. Disabled by default because PSTN
    # echo / line noise can trigger false SPEECH_STARTED / PARTIAL events that
    # cut the agent off mid-utterance. Browser test rooms are unaffected by
    # this flag (they always allow barge-in).
    PHONE_CALL_BARGE_IN_ENABLED: bool = False
    # Throttle: don't fire two barge-ins within this window (ms).
    BARGE_IN_COOLDOWN_MS: int = 250
    # Number of interruption events to keep per call in Redis (FIFO).
    BARGE_IN_MAX_EVENTS_PER_CALL: int = 200
    # Text the agent speaks after entering RECOVERY because the LLM
    # failed irrecoverably for one turn.
    AI_RECOVERY_LLM_FALLBACK_TEXT: str = (
        "Sorry, I had a brief issue on my end. Could you say that again?"
    )
    # Text the agent speaks after a STT/TTS recovery so the lead doesn't
    # think the line dropped silently.
    AI_RECOVERY_PIPELINE_FALLBACK_TEXT: str = (
        "Apologies — I lost you for a moment. I'm back now, please go ahead."
    )

    # Per-turn retry policy for the LLM (independent of OpenAI SDK retries
    # which only cover transport errors; this layer adds backoff between
    # full HTTP attempts on rate limit / timeout / 5xx).
    AI_TURN_MAX_ATTEMPTS: int = 3
    AI_TURN_RETRY_BACKOFF_SECONDS: float = 0.4
    AI_TURN_TIMEOUT_SECONDS: float = 12.0

    # Deepgram socket reconnect.
    STT_MAX_RECONNECT_ATTEMPTS: int = 3
    STT_RECONNECT_BACKOFF_SECONDS: float = 0.5

    # ElevenLabs retry per utterance.
    TTS_MAX_ATTEMPTS: int = 2
    TTS_RETRY_BACKOFF_SECONDS: float = 0.3

    # LiveKit reconnect (we only attempt this once: a second failure
    # almost always means the room was destroyed).
    LIVEKIT_RECONNECT_ATTEMPTS: int = 1
    LIVEKIT_RECONNECT_BACKOFF_SECONDS: float = 1.0

    # Twilio PSTN
    # Account SID (AC...) — always required. Find it on the Twilio
    # console homepage; it is not a secret.
    TWILIO_ACCOUNT_SID: str = ""
    # Auth Token — only needed for X-Twilio-Signature validation. When
    # blank we force-disable signature validation.
    TWILIO_AUTH_TOKEN: str = ""
    # Optional API Key auth (preferred for production: scoped keys can
    # be rotated/revoked without touching the master auth token).
    # When both are set the SDK is initialised with API Key auth.
    TWILIO_API_KEY_SID: str = ""
    TWILIO_API_KEY_SECRET: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    # Public base URL Twilio will hit for webhooks (must be HTTPS in prod).
    TWILIO_PUBLIC_BASE_URL: str = "http://localhost:8000"
    # If set, /telephony/webhooks/voice returns TwiML that dials the LiveKit
    # SIP gateway, bridging the PSTN leg into the AI agent's room.
    # Example: "sip.livekit.cloud" or "<region>.sip.livekit.cloud".
    LIVEKIT_SIP_URI: str = ""
    # LiveKit-originated outbound calling (preferred path). When set, the
    # backend dials the lead via LiveKit ``CreateSIPParticipant`` into the
    # agent's room instead of Twilio TwiML <Dial><Sip>. Provisioned by
    # ``scripts/setup_sip_trunk.py``.
    LIVEKIT_SIP_OUTBOUND_TRUNK_ID: str = ""
    # Ring timeout (seconds) for LiveKit-originated SIP calls.
    LIVEKIT_SIP_RING_TIMEOUT_SECONDS: float = 30.0
    # When False (dev), webhook signature validation is skipped.
    TWILIO_VALIDATE_SIGNATURE: bool = True
    # Default per-call timeouts.
    TWILIO_DIAL_TIMEOUT_SECONDS: int = 30
    TWILIO_CALL_RECORD: bool = False
    TWILIO_MAX_RETRIES: int = 2
    TWILIO_RETRY_BACKOFF_SECONDS: float = 5.0
    # Outbound caller-ID name shown on supported carriers.
    TWILIO_CALLER_ID_NAME: str = "Aifficient"

    # ------------------------------------------------------------------
    # Answering Machine Detection (AMD) + Voicemail Drop
    # ------------------------------------------------------------------
    # Master switch — when False the telephony layer never asks Twilio to
    # run AMD even if a campaign requests voicemail handling.
    TWILIO_AMD_ENABLED: bool = True
    # Twilio ``machine_detection`` mode: "Enable" (detect human vs machine)
    # or "DetectMessageEnd" (also wait for the greeting/beep to finish, which
    # is what you want before dropping a voicemail).
    TWILIO_AMD_MODE: str = "DetectMessageEnd"
    # Max seconds Twilio waits to classify the answer (3..59).
    TWILIO_AMD_TIMEOUT_SECONDS: int = 30
    # Asynchronous AMD. When True, Twilio fetches the voice TwiML (the
    # ``<Dial><Sip>`` bridge) IMMEDIATELY on answer and posts the AMD verdict
    # separately to ``async_amd_status_callback`` — so the human is bridged to
    # the AI agent within ~1s instead of waiting ~5s for synchronous AMD to
    # finish. Voicemail drop is then decided on the async callback, which
    # redirects the live call to the recording. Set False to restore the legacy
    # synchronous AMD path (voice TwiML gated on AMD completion).
    TWILIO_AMD_ASYNC: bool = True
    # Voicemail recording upload + validation.
    # Directory uploaded voicemail audio is written to (local FS until the
    # S3 integration lands — see deliverable notes).
    VOICEMAIL_UPLOAD_DIR: str = "uploads/voicemail"
    # Max upload size in bytes (default 5 MB).
    VOICEMAIL_MAX_BYTES: int = 5 * 1024 * 1024
    # Allowed audio content-types / extensions for uploads + configured URLs.
    VOICEMAIL_ALLOWED_FORMATS: str = "mp3,wav,x-wav,wave,ogg,mpeg,aac"
    # When True, configuring a voicemail by URL performs a best-effort network
    # HEAD request to confirm the URL is reachable + audio. Off by default so
    # CI / offline environments don't depend on the network.
    VOICEMAIL_URL_NETWORK_CHECK: bool = False
    # When True, reject voicemail URLs that Twilio cannot fetch over the public
    # internet (file://, localhost, loopback / private / link-local IPs,
    # ``*.local``). Twilio ``<Play>`` runs from Twilio's cloud, so a recording
    # behind a private address will silently fail to play. Disable only in
    # isolated dev where Twilio is mocked.
    VOICEMAIL_REQUIRE_PUBLIC_URL: bool = True
    # Public HTTP route uploaded recordings are served from (mounted onto
    # ``VOICEMAIL_UPLOAD_DIR``). The Twilio-reachable URL is
    # ``{TWILIO_PUBLIC_BASE_URL}{VOICEMAIL_PUBLIC_ROUTE}/{filename}``.
    VOICEMAIL_PUBLIC_ROUTE: str = "/media/voicemail"

    # When True, the campaign execution worker places a real outbound
    # telephony call (Twilio + AMD + voicemail drop) per lead instead of the
    # legacy LLM-plan stub. The terminal call outcome is reconciled back onto
    # the execution via the Twilio status webhook. Off by default so existing
    # deployments/tests keep the in-process plan behaviour until telephony is
    # provisioned.
    CAMPAIGN_TELEPHONY_DIALING_ENABLED: bool = False

    # ------------------------------------------------------------------
    # Campaign dispatch transport (Celery -> FastAPI)
    # ------------------------------------------------------------------
    # The realtime AI agent (LiveKit room, STT/LLM/TTS sessions, SIP bridge)
    # MUST run inside the long-lived FastAPI/uvicorn event loop. The Celery
    # scheduler runs each tick in a short-lived ``asyncio.run`` loop that is
    # torn down the moment the coroutine returns — spawning the agent there
    # orphaned its background task and killed the shared async LiveKit/Redis
    # clients ("Event loop is closed" / "Future attached to a different loop").
    #
    # When True (default) the scheduler does NOT originate calls itself: it
    # builds the dial payload and sends an authenticated internal HTTP request
    # to ``POST {INTERNAL_API_BASE_URL}{API_PREFIX}/telephony/calls`` so the
    # FastAPI process owns room creation + agent lifecycle. Set False only to
    # restore the legacy in-process ``asyncio.run`` dial path (tests / debug).
    CAMPAIGN_DISPATCH_VIA_HTTP: bool = True
    # Base URL of the FastAPI process the scheduler dispatches calls to. In a
    # single-host bare-metal/PM2 deploy this is the local uvicorn bind.
    INTERNAL_API_BASE_URL: str = "http://localhost:8000"
    # Shared secret authenticating service-to-service calls (sent as the
    # ``X-Internal-Token`` header). Falls back to ``JWT_SECRET`` when unset so
    # the feature works out of the box on a single-tenant host; set an explicit
    # value in multi-host deployments.
    INTERNAL_SERVICE_TOKEN: str = ""
    # HTTP timeout (seconds) for the scheduler -> FastAPI dispatch request.
    CAMPAIGN_DISPATCH_HTTP_TIMEOUT_SECONDS: float = 30.0

    @property
    def internal_service_token(self) -> str:
        """Effective shared secret for internal service-to-service auth."""

        return self.INTERNAL_SERVICE_TOKEN or self.JWT_SECRET

    # ------------------------------------------------------------------
    # Campaign call-scheduling engine (Celery Beat + pacing)
    # ------------------------------------------------------------------
    # Broker / result backend for Celery. Both fall back to ``REDIS_URL``
    # when unset so a single Redis instance powers memory, rate limiting
    # and the task queue in development.
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None
    # How often Celery Beat fires the campaign scheduler tick (seconds).
    CAMPAIGN_SCHEDULER_INTERVAL_SECONDS: float = 60.0
    # Default pacing applied when a campaign doesn't set its own. ``0`` on
    # either field means "unlimited" for that constraint.
    CAMPAIGN_DEFAULT_CALLS_PER_HOUR: int = 60
    CAMPAIGN_DEFAULT_MAX_CONCURRENT_CALLS: int = 5

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False

    # ------------------------------------------------------------------
    # Rate limiting (Redis-backed sliding-window per identity)
    # ------------------------------------------------------------------
    # Default budget per identity. Tightened for unauthenticated auth
    # endpoints (see RATE_LIMIT_AUTH_*).
    RATE_LIMIT_REQUESTS: int = 300
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    # Stricter bucket applied to the login/register/refresh endpoints so
    # an attacker can't brute force from one IP.
    RATE_LIMIT_AUTH_REQUESTS: int = 10
    RATE_LIMIT_AUTH_WINDOW_SECONDS: int = 60
    # Dedicated budget for expensive AI inference calls (POST /ai/generate,
    # POST /ai/converse). Lower than the general API budget to prevent
    # runaway cost amplification.
    RATE_LIMIT_AI_REQUESTS: int = 30
    RATE_LIMIT_AI_WINDOW_SECONDS: int = 60
    # Dedicated budget for outbound telephony calls (POST /telephony/calls).
    # Prevents a single AGENT from initiating hundreds of real Twilio calls/min.
    RATE_LIMIT_TELEPHONY_REQUESTS: int = 60
    RATE_LIMIT_TELEPHONY_WINDOW_SECONDS: int = 60
    # Dedicated budget for campaign activation (POST /campaigns/activate).
    # Prevents mass re-activation in tight loops.
    RATE_LIMIT_CAMPAIGN_ACTIVATE_REQUESTS: int = 20
    RATE_LIMIT_CAMPAIGN_ACTIVATE_WINDOW_SECONDS: int = 60
    # Set to False in tests / load-gen environments to disable the
    # middleware entirely.
    RATE_LIMIT_ENABLED: bool = True
    # Comma-separated path prefixes that bypass the limiter (CORS
    # preflights are handled separately by checking the request method).
    RATE_LIMIT_EXEMPT_PATHS: str = (
        "/api/v1/health,/health,/,"
        "/api/v1/telephony/webhooks,/docs,/openapi.json,/redoc,/favicon.ico"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
