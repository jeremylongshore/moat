"""
app.config
~~~~~~~~~~
Settings for the Moat MCP Server.
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
    SERVICE_NAME: str = "moat-mcp-server"

    # Upstream services
    CONTROL_PLANE_URL: str = "http://localhost:8001"
    GATEWAY_URL: str = "http://localhost:8002"
    TRUST_PLANE_URL: str = "http://localhost:8003"

    # HTTP client config
    HTTP_TIMEOUT: float = 30.0

    # Observability
    LOG_LEVEL: str = "INFO"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8004


settings = Settings()
