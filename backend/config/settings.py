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

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
