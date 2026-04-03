"""Configuration management via environment variables and .env files."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

# Find .env from project root regardless of CWD
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = {
        "env_file": str(_ENV_FILE) if _ENV_FILE.exists() else ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",  # ignore env vars we don't map
    }

    # --- API keys -----------------------------------------------------------
    anthropic_api_key: str = Field(description="Anthropic API key for Claude")
    elevenlabs_api_key: str = Field(default="", description="ElevenLabs API key for TTS")

    # --- Claude --------------------------------------------------------------
    claude_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model identifier",
    )
    claude_max_tokens: int = Field(
        default=1024,
        description="Default max tokens for Claude responses (keeps comms tactical)",
    )
    claude_max_tokens_briefing: int = Field(
        default=2048,
        description="Max tokens for briefings, checklists, and flight plans",
    )
    claude_max_history: int = Field(
        default=20,
        description="Max message pairs to retain in conversation history",
    )
    claude_temperature: float = Field(
        default=0.3,
        description="Default temperature for Claude responses (overridden by dynamic phase logic)",
    )

    # --- Claude model routing ---
    claude_model_fast: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Fast/cheap model for short acknowledgments and simple queries",
    )
    claude_temp_critical: float = Field(
        default=0.1,
        description="Temperature for critical flight phases (takeoff, approach, landing)",
    )
    claude_temp_normal: float = Field(
        default=0.3,
        description="Temperature for normal flight phases (climb, descent, taxi)",
    )
    claude_temp_relaxed: float = Field(
        default=0.5,
        description="Temperature for relaxed phases (preflight, cruise, landed)",
    )

    # --- Conversation summary ---
    claude_summary_interval: int = Field(
        default=10,
        description="Summarize conversation history every N turns",
    )
    claude_summary_max_tokens: int = Field(
        default=256,
        description="Max tokens for conversation summary generation",
    )

    # --- Telemetry service ---------------------------------------------------
    telemetry_service_host: str = Field(
        default="localhost",
        description="Telemetry service host",
    )
    telemetry_service_port: int = Field(
        default=8080,
        description="Telemetry service consumer WebSocket port",
    )
    telemetry_service_url: str = Field(
        default="",
        description="Full telemetry service WebSocket URL (constructed if empty)",
    )

    # --- STT (Speech-to-Text) ------------------------------------------------
    stt_backend: str = Field(
        default="deepgram",
        description="STT backend: 'deepgram' (cloud streaming) or 'whisper' (local batch)",
    )

    # Deepgram STT
    deepgram_api_key: str = Field(
        default="",
        description="Deepgram API key for streaming STT",
    )
    deepgram_model: str = Field(
        default="nova-3",
        description="Deepgram model (nova-3 recommended for aviation)",
    )
    deepgram_endpointing_ms: int = Field(
        default=300,
        description="Deepgram endpointing silence threshold in ms",
    )

    # Whisper STT (legacy/fallback)
    whisper_model: str = Field(
        default="large-v3-turbo",
        description="Whisper model size (legacy fallback, used by Docker service)",
    )
    whisper_url: str = Field(
        default="http://localhost:9090",
        description="URL of the local Whisper ASR HTTP service (legacy fallback)",
    )

    # --- TTS (Text-to-Speech) ------------------------------------------------
    tts_backend: str = Field(
        default="cartesia",
        description="TTS backend: 'cartesia' (low-latency), 'elevenlabs' (cloud), 'local' (Kokoro)",
    )

    # Cartesia TTS
    cartesia_api_key: str = Field(
        default="",
        description="Cartesia API key for ultra-low-latency TTS",
    )
    cartesia_voice_id: str = Field(
        default="",
        description="Cartesia voice ID",
    )
    cartesia_model_id: str = Field(
        default="sonic-2",
        description="Cartesia model ID",
    )

    # ElevenLabs TTS (fallback)
    elevenlabs_model_id: str = Field(
        default="eleven_multilingual_v2",
        description="ElevenLabs model ID for TTS synthesis",
    )
    elevenlabs_voice_id: str = Field(
        default="",
        description="ElevenLabs voice ID for TTS output",
    )
    tts_local_url: str = Field(
        default="http://localhost:8880",
        description="URL of the local Kokoro TTS server",
    )
    tts_voice_id_local: str = Field(
        default="af_heart",
        description="Voice ID for local Kokoro TTS",
    )
    tts_stability: float = Field(
        default=0.75,
        description="ElevenLabs voice stability (0.0-1.0)",
    )
    tts_similarity_boost: float = Field(
        default=0.80,
        description="ElevenLabs similarity boost (0.0-1.0)",
    )
    tts_style: float = Field(
        default=0.15,
        description="ElevenLabs style (0.0-1.0, V2+ models only)",
    )

    # --- Screen capture ------------------------------------------------------
    screen_capture_enabled: bool = Field(
        default=False,
        description="Enable screen capture for vision-based analysis",
    )
    screen_capture_fps: int = Field(
        default=1,
        description="Frames per second for screen capture",
    )

    # --- ChromaDB (context store) --------------------------------------------
    chromadb_url: str = Field(
        default="http://localhost:8000",
        description="URL of the ChromaDB HTTP server (Docker)",
    )

    # --- Logging -------------------------------------------------------------
    log_level: str = Field(
        default="INFO",
        description="Log level: DEBUG, INFO, WARNING, ERROR",
    )

    @model_validator(mode="after")
    def _build_derived(self) -> Settings:
        # Build telemetry service URL from components if not explicitly set
        if not self.telemetry_service_url:
            self.telemetry_service_url = (
                f"ws://{self.telemetry_service_host}:{self.telemetry_service_port}/ws/telemetry"
            )
        return self

    @property
    def tts_configured(self) -> bool:
        """Whether TTS is configured for the selected backend."""
        if self.tts_backend == "local":
            return bool(self.tts_local_url)
        return bool(self.elevenlabs_api_key and self.elevenlabs_voice_id)

    @property
    def voice_id(self) -> str:
        """Return the voice ID appropriate for the selected TTS backend."""
        if self.tts_backend == "local":
            return self.tts_voice_id_local
        return self.elevenlabs_voice_id


def load_settings() -> Settings:
    return Settings()
