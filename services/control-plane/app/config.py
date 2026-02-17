"""
app.config
~~~~~~~~~~
Settings for the Moat Control Plane service.

All values can be supplied via environment variables (case-insensitive).
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
    SERVICE_NAME: str = "moat-control-plane"

    # Data stores (used by production wiring; in-memory for MVP)
    DATABASE_URL: str = "sqlite+aiosqlite:///./control_plane_dev.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Secret Manager (optional – only needed in production)
    SECRET_MANAGER_PROJECT: str | None = None

    # Observability
    LOG_LEVEL: str = "INFO"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8001


settings = Settings()
