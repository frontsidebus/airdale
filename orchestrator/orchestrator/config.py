"""Configuration management via environment variables and .env files."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings

from .authority import SUPPORTED_AUTHORITY_LEVELS, parse_authority_level

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
    # --- Turn detection (end-of-utterance)
    turn_detector: str = Field(
        default="smart",
        description=(
            "End-of-turn detector: 'smart' (semantic, Smart Turn v3 ONNX) or "
            "'silence' (fixed silence threshold). 'smart' falls back to 'silence' "
            "automatically if onnxruntime or the model file is unavailable."
        ),
    )
    turn_threshold: float = Field(
        default=0.5,
        gt=0.0,
        lt=1.0,
        description=(
            "Probability above which the semantic detector calls the turn complete. "
            "Raise it to make MERLIN more willing to wait through a pause."
        ),
    )
    turn_probe_silence_ms: int = Field(
        default=150,
        gt=0,
        description=(
            "Silence observed before consulting the semantic detector. Lower than "
            "vad_silence_ms because the model decides on content, not duration."
        ),
    )
    vad_silence_ms: int = Field(
        default=400,
        gt=0,
        description="Silence threshold for the fixed-silence detector and the RMS fallback.",
    )

    whisper_model: str = Field(
        default="large-v3-turbo",
        description="Whisper model size (legacy fallback, used by Docker service)",
    )
    whisper_url: str = Field(
        default="http://localhost:9090",
        description="URL of the local Whisper ASR HTTP service (legacy fallback)",
    )

    # --- Authority & safety --------------------------------------------------
    authority_level: str = Field(
        default="full",
        description=(
            "How far MERLIN may go with the aircraft. 'advisory' never commands and "
            "reports what it would have done; 'assisted' executes but withholds "
            "anything command_safety flags as 'warning'; 'full' executes unless "
            "command_safety blocks it outright. Defaults to 'full' because that is "
            "exactly today's behaviour -- restriction is opt-in, so upgrading changes "
            "nothing. Caveat: 'assisted' keys off 'warning' severity, and only 7 safety "
            "rules exist, covering gear, flaps, autopilot and throttle -- so for the "
            "other 16 of the 20 commandable systems 'assisted' behaves identically to "
            f"'full'. One of {SUPPORTED_AUTHORITY_LEVELS}; an unknown value fails at "
            "startup rather than degrading silently."
        ),
    )
    authority_override_grace_s: float = Field(
        default=30.0,
        gt=0.0,
        description=(
            "Seconds after MERLIN issues a command during which a change to that "
            "command's own telemetry fields is attributed to MERLIN. Without the grace "
            "window MERLIN's own command reads back as a pilot override and it drops "
            "its own authority."
        ),
    )
    authority_override_settle_s: float = Field(
        default=2.0,
        gt=0.0,
        description=(
            "Seconds to wait before re-scrutinising the fields of a command that has no "
            "verification rule. Surfaces, autopilot and radios broadcast at 1 Hz, so a "
            "shorter settle reads the pre-command value and calls MERLIN's own change a "
            "pilot override."
        ),
    )
    authority_override_cooldown_s: float = Field(
        default=120.0,
        gt=0.0,
        description=(
            "Seconds MERLIN stays advisory after a pilot override. Rolling -- each new "
            "override pushes the expiry out, so a pilot who keeps flying keeps MERLIN "
            "deferring. Authority restores automatically when the cooldown lapses."
        ),
    )
    authority_watchdog_max_timeouts: int = Field(
        default=3,
        ge=1,
        description=(
            "Consecutive command-path timeouts before MERLIN latches to advisory. Three "
            "tolerates a transient hiccup while still catching a dead adapter. The latch "
            "is cleared on reconnect, never by a later success -- a latch that stops "
            "command issuance cannot produce the ack that would clear it."
        ),
    )
    authority_command_timeout_s: float = Field(
        default=5.0,
        gt=0.0,
        description=(
            "Seconds to wait for a command acknowledgment from the sim adapter. Promotes "
            "the value previously hardcoded in TelemetryClient.send_command so the "
            "watchdog and the tool deadline can be reasoned about together."
        ),
    )
    authority_verify_timeout_s: float = Field(
        default=3.0,
        gt=0.0,
        description=(
            "Seconds CommandVerifier polls telemetry for post-execution confirmation. "
            "Promotes the value previously hardcoded in CommandVerifier."
        ),
    )
    authority_tool_timeout_s: float = Field(
        default=12.0,
        gt=0.0,
        description=(
            "Outer deadline on the set_aircraft_control tool call. Must exceed "
            "authority_command_timeout_s + authority_verify_timeout_s: the outer "
            "deadline starts first, so an equal budget pre-empts the genuine ack "
            "timeout and the watchdog never observes it. Enforced at startup."
        ),
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

    @field_validator("authority_level")
    @classmethod
    def _normalise_authority_level(cls, value: str) -> str:
        """Reject an unknown authority level at startup, listing what is supported.

        There is no fallback branch on purpose. A typo that silently resolved to a
        default would be a typo that granted MERLIN authority nobody asked for.
        """
        try:
            return parse_authority_level(value).value
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def _build_derived(self) -> Settings:
        # Build telemetry service URL from components if not explicitly set
        if not self.telemetry_service_url:
            self.telemetry_service_url = (
                f"ws://{self.telemetry_service_host}:{self.telemetry_service_port}/ws/telemetry"
            )
        return self

    @model_validator(mode="after")
    def _check_authority_timeout_budget(self) -> Settings:
        """The tool deadline must outlast the ack wait plus the verification poll.

        ``set_aircraft_control``'s outer ``asyncio.wait_for`` starts first, so if its
        budget is not strictly larger than what it contains, it fires before the ack
        timeout does -- the command path looks like a slow tool rather than a dead
        adapter, and the watchdog never sees the timeout it exists to count.
        """
        inner = self.authority_command_timeout_s + self.authority_verify_timeout_s
        if self.authority_tool_timeout_s <= inner:
            raise ValueError(
                f"authority_tool_timeout_s ({self.authority_tool_timeout_s}) must be greater "
                f"than authority_command_timeout_s ({self.authority_command_timeout_s}) + "
                f"authority_verify_timeout_s ({self.authority_verify_timeout_s}) = {inner}; "
                "otherwise the tool deadline pre-empts the ack timeout and the command-path "
                "watchdog can never observe a genuine timeout."
            )
        return self

    @property
    def tts_configured(self) -> bool:
        """Whether TTS is configured for the *selected* backend.

        Each backend is checked against its own credentials -- never another
        backend's. Adding a backend to ``tts/__init__.py`` requires a branch
        here too, or the new backend silently reports itself unconfigured.
        """
        backend = self.tts_backend.lower().strip()
        if backend == "local":
            return bool(self.tts_local_url)
        if backend == "cartesia":
            return bool(self.cartesia_api_key and self.cartesia_voice_id)
        if backend == "elevenlabs":
            return bool(self.elevenlabs_api_key and self.elevenlabs_voice_id)
        return False

    @property
    def voice_id(self) -> str:
        """Return the voice ID appropriate for the selected TTS backend."""
        backend = self.tts_backend.lower().strip()
        if backend == "local":
            return self.tts_voice_id_local
        if backend == "cartesia":
            return self.cartesia_voice_id
        return self.elevenlabs_voice_id

    @property
    def stt_configured(self) -> bool:
        """Whether STT is configured for the *selected* backend."""
        backend = self.stt_backend.lower().strip()
        if backend == "whisper":
            return bool(self.whisper_url)
        if backend == "deepgram":
            return bool(self.deepgram_api_key)
        return False


def load_settings() -> Settings:
    return Settings()
