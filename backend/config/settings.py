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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
