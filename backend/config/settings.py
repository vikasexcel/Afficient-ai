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
