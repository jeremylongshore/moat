"""
app.config
~~~~~~~~~~
Settings for the Moat Gateway service.
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
    SERVICE_NAME: str = "moat-gateway"

    # Upstream services
    CONTROL_PLANE_URL: str = "http://localhost:8001"
    TRUST_PLANE_URL: str = "http://localhost:8003"

    # Data stores
    REDIS_URL: str = "redis://localhost:6379/1"
    DATABASE_URL: str = "sqlite+aiosqlite:///./gateway_dev.db"

    # Observability
    LOG_LEVEL: str = "INFO"

    # HTTP client timeouts (seconds)
    HTTP_TIMEOUT: float = 30.0

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8002


settings = Settings()
