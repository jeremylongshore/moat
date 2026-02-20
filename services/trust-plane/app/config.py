"""
app.config
~~~~~~~~~~
Settings for the Moat Trust Plane service.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Identity
    SERVICE_NAME: str = "moat-trust-plane"

    # Data stores
    DATABASE_URL: str = "sqlite+aiosqlite:///./trust_plane_dev.db"
    REDIS_URL: str = "redis://localhost:6379/2"

    # Observability
    LOG_LEVEL: str = "INFO"

    # Trust scoring thresholds
    MIN_SUCCESS_RATE_7D: float = 0.80  # Below this = should_hide
    MAX_P95_LATENCY_MS: float = 10_000.0  # Above this = should_throttle

    # Authentication
    MOAT_JWT_SECRET: str = ""  # Required when auth is enabled
    MOAT_AUTH_DISABLED: bool = False  # Set True only for local dev

    # Environment
    MOAT_ENV: str = "local"

    # CORS
    ALLOWED_ORIGINS: str = "*"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8003


settings = Settings()
