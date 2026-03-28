"""Telemetry service configuration."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class TelemetryServiceSettings(BaseSettings):
    model_config = {
        "env_prefix": "TELEMETRY_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    host: str = Field(default="0.0.0.0", description="Bind address")
    consumer_port: int = Field(default=8080, description="Port for consumer WebSocket connections")
    ingest_port: int = Field(default=8081, description="Port for adapter ingest connections")
    stale_adapter_timeout: float = Field(
        default=15.0,
        description="Seconds before an adapter is considered stale",
    )
    log_level: str = Field(default="INFO", description="Log level")


def load_settings() -> TelemetryServiceSettings:
    return TelemetryServiceSettings()
