"""FastAPI backend for the MERLIN AI co-pilot web UI.

Bridges the browser frontend to the orchestrator components: SimConnect
telemetry streaming, Claude chat with the MERLIN persona, Whisper STT,
and ElevenLabs TTS.

Supports barge-in interruption: if the user sends new audio or text while
MERLIN is responding, the current Claude stream and TTS pipeline are
cancelled immediately.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import websockets as ws_lib
from fastapi import (
    Depends,
    FastAPI,
    Form,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from orchestrator.audio_processing import (
    convert_webm_to_wav_normalized,
    decode_webm_to_samples,
)
from orchestrator.authority import (  # noqa: E402
    AuthorityLevel,
    AuthorityReason,
    AuthorityState,
    parse_authority_level,
)
from orchestrator.claude_client import ClaudeClient  # noqa: E402
from orchestrator.config import load_settings  # noqa: E402
from orchestrator.context_store import ContextStore  # noqa: E402
from orchestrator.flight_phase import FlightPhaseDetector  # noqa: E402
from orchestrator.override_detector import OverrideDetector  # noqa: E402
from orchestrator.sim_client import (  # noqa: E402
    HealthMonitor,
    SimState,
    TelemetryClient,
)
from orchestrator.stt.deepgram import DeepgramSTTClient  # noqa: E402
from orchestrator.tts.cartesia import CartesiaClient  # noqa: E402
from orchestrator.tts_preprocessor import preprocess_for_tts  # noqa: E402
from orchestrator.turn import (  # noqa: E402
    SilenceTurnDetector,
    TurnDetector,
    create_turn_detector,
)
from orchestrator.whisper_client import WhisperClient  # noqa: E402
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("merlin.web")

# ---------------------------------------------------------------------------
# Shared application state (initialised in lifespan)
# ---------------------------------------------------------------------------
settings = load_settings()
logging.getLogger().setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

# Confidence threshold: transcriptions below this trigger a retry or warning
_LOW_CONFIDENCE_THRESHOLD = 0.4

# Minimum audio duration (seconds) to bother sending to STT
_MIN_AUDIO_DURATION_SECS = 0.5

# Brief pause (seconds) after MERLIN finishes speaking before accepting input
_POST_SPEECH_PAUSE_SECS = 0.3

# ---------------------------------------------------------------------------
# Turn probe limits
#
# /api/turn-probe is an unauthenticated local endpoint that spawns an ffmpeg
# process per request, and the browser calls it from a requestAnimationFrame
# loop. Both bounds below exist to keep a client bug from becoming a local fork
# bomb; the browser has matching guards, but the server does not trust them.
# ---------------------------------------------------------------------------

# Opus at ~24 kbps puts a 15 s utterance near 45 KB, so 2 MiB is several minutes
# of audio. Anything larger is a bug or abuse, and is rejected before ffmpeg runs.
_MAX_TURN_PROBE_BYTES = 2 * 1024 * 1024

# Sample rate decode_webm_to_samples emits; turn.features raises on anything else.
_TURN_PROBE_SAMPLE_RATE = 16000

# Cap on tracked probe clients so the throttle table cannot grow without bound.
_MAX_TURN_PROBE_CLIENTS = 64

# ---------------------------------------------------------------------------
# TTS phrase cache -- pre-populated at startup for common MERLIN phrases
# ---------------------------------------------------------------------------

_CACHEABLE_PHRASES = [
    "Roger.",
    "Roger, Captain.",
    "Copy that.",
    "Standby.",
    "Affirmative.",
    "Negative.",
    "Understood.",
    "Wilco.",
    "Good copy.",
    "Say again?",
    "Checking.",
]


# ---------------------------------------------------------------------------
# AppState: typed container for all mutable shared state
# ---------------------------------------------------------------------------


@dataclass
class AppState:
    """Mutable shared state for the MERLIN web server."""

    settings: Any  # Settings from orchestrator.config
    sim_client: TelemetryClient | None = None
    claude_client: ClaudeClient | None = None
    context_store: ContextStore | None = None
    phase_detector: FlightPhaseDetector | None = None
    whisper_client: WhisperClient | None = None  # Legacy STT fallback
    deepgram_client: DeepgramSTTClient | None = None  # v2 streaming STT
    cartesia_client: CartesiaClient | None = None  # v2 low-latency TTS
    tts_client: httpx.AsyncClient | None = None  # Legacy ElevenLabs HTTP
    turn_detector: TurnDetector | None = None  # End-of-turn detection for /api/turn-probe
    #: How much MERLIN may do to the aircraft, and why. The ``None`` default is a
    #: construction convenience for directly-built test states only -- ``lifespan``
    #: guarantees a non-``None`` value on every path out of startup, because a
    #: ``None`` authority reads as FULL to the gate in ``tools.py`` and makes the
    #: dispatch floor in ``sim_client.py`` inert.
    authority: AuthorityState | None = None
    health: HealthMonitor | None = None  # Subsystem health, incl. command_path (D-17)
    override_detector: OverrideDetector | None = None  # Drops authority on pilot override
    tts_cache: dict[str, bytes] = field(default_factory=dict)
    #: client host -> time.monotonic() of its last accepted turn probe
    turn_probe_seen: dict[str, float] = field(default_factory=dict)
    sim_connected: bool = False
    bridge_last_seen: float = 0.0
    bridge_connected: bool = False


def _int_setting(app_settings: Any, name: str, default: int) -> int:
    """Read an integer setting defensively.

    Mirrors the ``getattr(settings, ..., default)`` idiom used throughout this
    module, but coerces the result. Tests inject a ``MagicMock`` settings object
    where ``getattr`` invents an attribute instead of raising, which would put a
    non-serialisable value into ``/api/status`` and a non-comparable one into the
    probe throttle.
    """
    try:
        return int(getattr(app_settings, name, default))
    except (TypeError, ValueError):
        return default


def _build_health_monitor() -> HealthMonitor:
    """Register the same subsystem set the CLI registers (D-17).

    ``orchestrator/main.py`` registers these five by name. The browser and the CLI
    must not report different subsystem sets, or a pilot comparing the two would
    have to work out which absence means "not wired here" and which means "down".
    """
    health = HealthMonitor()
    health.register("simconnect_bridge")
    health.register("chromadb")
    health.register("whisper")
    health.register("claude_api")
    # Belt and braces -- TelemetryClient registers this too when it is handed a
    # monitor. Registering here keeps command_path in summary() from process start,
    # even if some future path builds the client without a monitor.
    health.register("command_path")
    return health


def _json_safe_subsystems(health: HealthMonitor | None) -> dict[str, dict[str, Any]]:
    """``HealthMonitor.summary()`` with ``age_seconds`` made JSON-legal.

    A subsystem that has never reported healthy carries ``age_seconds == inf``, and
    Starlette's ``JSONResponse`` renders with ``allow_nan=False`` -- so returning
    the summary verbatim turns ``/api/status`` into a 500 the moment any registered
    subsystem is unseen, which is all of them at startup. ``None`` is the honest
    wire value for "never seen": a sentinel number would be one the browser could
    not tell from a real age, and ``Infinity`` is not JSON the browser can parse.
    """
    if health is None:
        return {}
    summary = health.summary()
    for entry in summary.values():
        age = entry.get("age_seconds")
        if isinstance(age, float) and not math.isfinite(age):
            entry["age_seconds"] = None
    return summary


def get_app_state(request: Request) -> AppState:
    """FastAPI dependency: extract AppState from app.state (HTTP routes)."""
    return request.app.state.app_state


def get_ws_app_state(ws: WebSocket) -> AppState:
    """FastAPI dependency: extract AppState from app.state (WebSocket routes)."""
    return ws.app.state.app_state


# ---------------------------------------------------------------------------
# TTS cache prepopulation
# ---------------------------------------------------------------------------


async def _prepopulate_tts_cache(state: AppState) -> None:
    """Pre-generate TTS audio for common short phrases at startup."""
    if not state.settings.elevenlabs_api_key or not state.settings.voice_id:
        return

    if state.tts_client is None:
        return

    for phrase in _CACHEABLE_PHRASES:
        sanitized = preprocess_for_tts(phrase)
        if not sanitized or sanitized in state.tts_cache:
            continue
        try:
            resp = await state.tts_client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{state.settings.voice_id}/stream",
                headers={
                    "xi-api-key": state.settings.elevenlabs_api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": sanitized,
                    "model_id": state.settings.elevenlabs_model_id,
                    "voice_settings": {
                        "stability": state.settings.tts_stability,
                        "similarity_boost": state.settings.tts_similarity_boost,
                        "style": state.settings.tts_style,
                    },
                },
            )
            resp.raise_for_status()
            state.tts_cache[sanitized] = resp.content
            logger.info("Cached TTS phrase: '%s' (%d bytes)", sanitized, len(resp.content))
        except Exception as exc:
            logger.debug("Failed to cache TTS phrase '%s': %s", sanitized, exc)


# ---------------------------------------------------------------------------
# Lifespan -- start / stop background services
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MERLIN web server")

    state = AppState(settings=settings)

    # Context store (ChromaDB) -- degrades gracefully if unavailable
    state.context_store = ContextStore(chromadb_url=settings.chromadb_url)

    # --- Authority and subsystem health (fail SAFE, never fail silent) --------
    #
    # Deliberately carved out of the degrade-and-continue idiom used below for STT,
    # TTS and the turn detector. For those, `None` means "this feature is off". For
    # authority, `None` means *unrestricted*: the gate in tools.py reads a None
    # authority as FULL, and the floor, the ack watchdog and the override cooldown
    # in sim_client.py are all guarded on `is not None`. A swallowed exception here
    # would therefore disable the whole authority layer on the browser path
    # regardless of AUTHORITY_LEVEL, while /api/status reported it as a deliberate
    # `full` / `config` setup -- indistinguishable from an operator's own choice.
    #
    # Do NOT "make this consistent" with its neighbours. On failure we substitute a
    # degraded, advisory-only state; if even that cannot be built we let the
    # exception out and the server does not start, because a web server serving
    # with no authority object is strictly more dangerous than one that refuses to
    # serve. The CLI fails CLOSED (orchestrator/main.py lets the exception abort
    # startup); the browser fails SAFE. Different mechanism, same guarantee: a
    # construction failure can never *grant* authority. See CLAUDE.md decision 26.
    try:
        state.health = _build_health_monitor()
        state.authority = AuthorityState(
            parse_authority_level(settings.authority_level),
            override_cooldown_s=settings.authority_override_cooldown_s,
            watchdog_max_timeouts=settings.authority_watchdog_max_timeouts,
        )
    except Exception as exc:
        detail = f"authority subsystem failed to start: {exc}"
        logger.error(
            "Authority subsystem failed to start (%s); MERLIN is restricting itself "
            "to advisory for the life of this process",
            exc,
            exc_info=True,
        )
        # The fallback below is built from enum literals only -- it reads no
        # Settings and takes no collaborator -- so it is safe to call from inside
        # the handler for the failure it replaces. If it raises anyway, that
        # exception propagates and startup aborts: the fail-closed backstop under
        # the fail-safe default.
        state.authority = AuthorityState.degraded_fallback(detail)
        state.health = _build_health_monitor()
        state.health.update("command_path", False, detail)

    logger.info(
        "Authority: %s (reason: %s, configured: %s)",
        state.authority.level.value,
        state.authority.reason.value,
        state.authority.configured_level.value,
    )

    # Telemetry client. One AuthorityState per process, shared by identity: the
    # client reads it for the dispatch floor, ClaudeClient forwards it to the tool
    # gate, and the override detector mutates it. A second instance would let the
    # three disagree about the current level.
    state.sim_client = TelemetryClient(
        url=settings.telemetry_service_url,
        authority=state.authority,
        health=state.health,
        command_timeout=settings.authority_command_timeout_s,
    )
    try:
        await state.sim_client.connect()
        state.sim_connected = True
        logger.info(
            "Telemetry service connected at %s",
            settings.telemetry_service_url,
        )
    except Exception as exc:
        state.sim_connected = False
        logger.warning(
            "Telemetry service unavailable at %s (%s); telemetry will be offline",
            settings.telemetry_service_url,
            exc,
        )

    # Flight phase detector
    state.phase_detector = FlightPhaseDetector()

    # Register the phase detector as a subscriber when connected
    if state.sim_connected and state.sim_client is not None:

        async def _on_state(sim_state: SimState) -> None:
            assert state.phase_detector is not None
            detected = state.phase_detector.update(sim_state)
            sim_state.flight_phase = detected

        state.sim_client.subscribe(_on_state)

        # Pilot-override detection. This one KEEPS the degrade-and-continue
        # treatment: without it AUTH-06 never fires, so MERLIN simply never drops
        # to advisory when the pilot takes the controls -- a capability loss that
        # leaves the configured level in force. That is the line between the two
        # treatments: a component whose absence *reduces* what MERLIN may do can
        # degrade; a component whose absence *increases* it cannot. Logged at
        # ERROR rather than WARNING because a silently missing detector is a
        # safety feature that is simply not running.
        try:
            state.override_detector = OverrideDetector(
                state.authority,
                state.sim_client,
                grace_s=settings.authority_override_grace_s,
                settle_s=settings.authority_override_settle_s,
                verify_timeout_s=settings.authority_verify_timeout_s,
            )
            # Its own subscriber, not a call from inside _on_state, so a failure
            # in one cannot suppress the other (D-11).
            state.sim_client.subscribe(state.override_detector.on_telemetry_update)
        except Exception as exc:
            state.override_detector = None
            logger.error(
                "Pilot-override detection unavailable (%s); MERLIN will not drop to "
                "advisory when the pilot takes the controls",
                exc,
                exc_info=True,
            )

    # STT client — route to configured backend
    stt_backend = getattr(settings, "stt_backend", "whisper")
    if stt_backend == "deepgram" and getattr(settings, "deepgram_api_key", ""):
        state.deepgram_client = DeepgramSTTClient(
            api_key=settings.deepgram_api_key,
            model=getattr(settings, "deepgram_model", "nova-3"),
            endpointing_ms=getattr(settings, "deepgram_endpointing_ms", 300),
        )
        logger.info("STT backend: Deepgram Nova-3 (streaming)")
    else:
        state.whisper_client = WhisperClient(base_url=settings.whisper_url)
        logger.info("STT backend: Whisper (local batch)")

    # End-of-turn detector for /api/turn-probe.
    #
    # Built through the factory, not SmartTurnDetector directly: the factory
    # resolves the smart -> silence fallback here at startup and logs the
    # fetch_turn_model.py hint. Discovering a missing model mid-utterance would
    # be the worst possible time to find out.
    try:
        state.turn_detector = create_turn_detector(settings)
        logger.info(
            "Turn detector: %s (available: %s)",
            state.turn_detector.name,
            state.turn_detector.available,
        )
    except Exception as exc:
        state.turn_detector = None
        logger.warning(
            "Turn detector unavailable (%s); browser will endpoint on fixed silence", exc
        )

    # Claude client. Handed the same AuthorityState object the telemetry client
    # holds, so the tool gate and the dispatch floor read one state. The two
    # timeouts come from settings for the ordering reason RESEARCH B3 names: the
    # tool-layer deadline must exceed the ack + verify budget or a genuine ack
    # timeout is cancelled as a tool timeout and the watchdog never sees it.
    state.claude_client = ClaudeClient(
        api_key=settings.anthropic_api_key,
        model=settings.claude_model,
        sim_client=state.sim_client,
        context_store=state.context_store,
        max_tokens=settings.claude_max_tokens,
        max_tokens_briefing=settings.claude_max_tokens_briefing,
        max_history=settings.claude_max_history,
        temperature=settings.claude_temperature,
        verify_timeout=settings.authority_verify_timeout_s,
        command_tool_timeout=settings.authority_tool_timeout_s,
        authority=state.authority,
    )

    # TTS client — route to configured backend
    tts_backend = getattr(settings, "tts_backend", "elevenlabs")
    if tts_backend == "cartesia" and getattr(settings, "cartesia_api_key", ""):
        state.cartesia_client = CartesiaClient(
            api_key=settings.cartesia_api_key,
            voice_id=getattr(settings, "cartesia_voice_id", ""),
            model_id=getattr(settings, "cartesia_model_id", "sonic-2"),
            output_format="mp3",  # Browser expects MP3 for decodeAudioData
        )
        logger.info("TTS backend: Cartesia Sonic-3 (low-latency)")
    else:
        logger.info("TTS backend: ElevenLabs (cloud)")

    # Legacy TTS HTTP client (connection pooling, used by ElevenLabs path)
    state.tts_client = httpx.AsyncClient(timeout=30.0)

    # Pre-populate TTS cache in the background (non-blocking)
    _cache_task = asyncio.create_task(_prepopulate_tts_cache(state))
    _cache_task.add_done_callback(
        lambda t: (
            logger.error("TTS cache prepopulation failed: %s", t.exception())
            if t.exception()
            else None
        )
    )

    app.state.app_state = state

    logger.info("MERLIN web server ready on port 3838")
    yield

    # Shutdown
    logger.info("Shutting down MERLIN web server")
    if state.sim_connected and state.sim_client is not None:
        await state.sim_client.disconnect()

    # Close persistent HTTP clients
    if state.tts_client and not state.tts_client.is_closed:
        await state.tts_client.aclose()
    if state.whisper_client is not None:
        await state.whisper_client.aclose()
    if state.deepgram_client is not None:
        await state.deepgram_client.aclose()
    if state.cartesia_client is not None:
        await state.cartesia_client.aclose()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MERLIN AI Co-Pilot",
    description="Web backend for the MERLIN flight simulator co-pilot",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class TTSRequest(BaseModel):
    text: str


class TurnProbeResponse(BaseModel):
    """Answer to "has the speaker finished?" for one candidate endpoint.

    ``available`` is separate from ``ended`` on purpose. It tells the browser
    whether asking is worth doing at all: ``False`` means stop probing for this
    session and fall back to fixed-silence endpointing, while a transient failure
    keeps ``available`` true so one bad blob does not permanently degrade
    responsiveness.
    """

    ended: bool
    probability: float
    detector: str
    available: bool


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.get("/")
async def index():
    """Serve the frontend."""
    index_path = _STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "MERLIN web UI -- place index.html in web/static/"}


@app.get("/overlay")
async def overlay():
    """Serve the compact overlay UI for use on top of the sim."""
    overlay_path = _STATIC_DIR / "overlay.html"
    if overlay_path.exists():
        return FileResponse(str(overlay_path))
    return {"message": "Overlay UI not found"}


@app.get("/api/status")
async def get_status(state: AppState = Depends(get_app_state)):
    """Return health status of all subsystems."""
    whisper_ok = False
    try:
        if state.whisper_client is not None:
            whisper_ok = await state.whisper_client.is_available()
    except Exception:
        pass

    chromadb_ok = state.context_store.available if state.context_store else False

    # Bridge is considered connected if telemetry was received recently
    # (updated by ws_telemetry proxy), OR the startup connection succeeded.
    bridge_ok = (
        state.bridge_connected and (time.monotonic() - state.bridge_last_seen) < 10.0
    ) or state.sim_connected

    # Feed what this endpoint just measured back into the monitor, so the
    # subsystems block cannot contradict the top-level fields in the same response
    # -- a payload saying chromadb_available: true beside chromadb.healthy: false
    # is worse than no subsystems block at all. The CLI does the same thing
    # (_update_bridge_health runs before get_health_summary). Nothing here writes
    # an authority value: the level moves only from configuration at startup,
    # override detection and the watchdog (T-02-09-03). claude_api is left alone
    # because this endpoint has no signal for it, and "never observed" is the
    # honest report.
    if state.health is not None:
        state.health.update(
            "simconnect_bridge",
            bool(bridge_ok),
            "Connected" if bridge_ok else "Disconnected",
        )
        state.health.update(
            "chromadb",
            bool(chromadb_ok),
            "Connected" if chromadb_ok else "Unavailable; RAG disabled",
        )
        state.health.update(
            "whisper",
            bool(whisper_ok),
            "Responding" if whisper_ok else "Unavailable or not the active backend",
        )

    stt_backend = getattr(state.settings, "stt_backend", "whisper")
    tts_backend = getattr(state.settings, "tts_backend", "elevenlabs")

    # Semantic turn probing is only worth the round trip when the detector is a
    # real model. The silence fallback would just re-derive what the browser can
    # already time locally, so report it as unavailable and let the browser use
    # its own vad_silence_ms threshold.
    turn_probe_available = (
        state.turn_detector is not None
        and state.turn_detector.available
        and not isinstance(state.turn_detector, SilenceTurnDetector)
    )

    # Authority is read straight out of AuthorityState.summary() rather than
    # formatted from the enums here, so the CLI and the browser render from one
    # place. It also removes the branch: AuthorityLevel has three members and
    # AuthorityReason four, and CLAUDE.md records what a missing branch costs --
    # tts_configured reported a working Cartesia setup as unconfigured for months
    # because one arm was absent. There is nothing to keep in sync here.
    #
    # An absent authority state reports advisory / degraded, never full / config.
    # After lifespan this is unreachable in a running server, so this fallback is
    # for a directly-constructed AppState and for any future path that reaches the
    # route before startup finished. In both cases the honest answer is "MERLIN
    # has no working authority state"; rendering that as a deliberate `full`
    # configuration is the precise ambiguity AUTH-08 exists to remove. Omitting the
    # keys would be the same ambiguity in a different costume.
    authority_summary = state.authority.summary() if state.authority is not None else {}
    authority_level = authority_summary.get("level", AuthorityLevel.ADVISORY.value)
    authority_reason = authority_summary.get("reason", AuthorityReason.DEGRADED.value)

    return {
        "sim_connected": bridge_ok,
        "chromadb_available": chromadb_ok,
        "chromadb_documents": (state.context_store.document_count if state.context_store else 0),
        "stt_backend": stt_backend,
        "stt_available": (
            state.deepgram_client is not None if stt_backend == "deepgram" else whisper_ok
        ),
        "tts_backend": tts_backend,
        "tts_available": (
            state.cartesia_client is not None
            if tts_backend == "cartesia"
            else bool(state.settings.elevenlabs_api_key and state.settings.voice_id)
        ),
        # Legacy fields for backward compat
        "whisper_available": whisper_ok,
        "elevenlabs_configured": bool(
            state.settings.elevenlabs_api_key and getattr(state.settings, "elevenlabs_voice_id", "")
        ),
        "claude_model": state.settings.claude_model,
        "telemetry_service_url": state.settings.telemetry_service_url,
        # Endpointing: one call tells the browser whether to probe and at what
        # thresholds, so it never has to guess or hardcode them.
        "turn_probe_available": turn_probe_available,
        "turn_probe_silence_ms": _int_setting(state.settings, "turn_probe_silence_ms", 150),
        "vad_silence_ms": _int_setting(state.settings, "vad_silence_ms", 400),
        # Authority: how much MERLIN may do to the aircraft, and why (AUTH-08).
        # The reason is what keeps "deferring to the pilot", "cannot reach the sim"
        # and "the authority subsystem failed to start" from all rendering as one
        # undifferentiated advisory badge (D-10).
        "authority_level": authority_level,
        "authority_reason": authority_reason,
        "authority": authority_summary,
        # Subsystem health, including command_path -- what lets the browser render
        # "advisory (command path down)" rather than an unexplained badge (D-17).
        "subsystems": _json_safe_subsystems(state.health),
    }


@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile, state: AppState = Depends(get_app_state)):
    """Transcribe uploaded audio.

    Routes to Deepgram (v2 default, cloud streaming) or Whisper (legacy
    fallback, local batch) based on STT_BACKEND configuration.
    """
    audio_bytes = await file.read()
    content_type = file.content_type or ""
    filename = file.filename or "audio.webm"

    logger.info("Received %d bytes of audio (mime: %s)", len(audio_bytes), content_type)

    # --- Deepgram path (v2 default) ---
    if state.deepgram_client is not None:
        try:
            # Convert webm to wav for Deepgram (it prefers raw audio)
            is_webm = "webm" in content_type or filename.endswith(".webm")
            if is_webm:
                audio_bytes = await convert_webm_to_wav_normalized(audio_bytes)

            result = await state.deepgram_client.transcribe(audio_bytes)
            response: dict[str, Any] = {
                "text": result.text,
                "confidence": result.confidence,
            }
            if result.text and result.confidence < _LOW_CONFIDENCE_THRESHOLD:
                response["low_confidence"] = True
                logger.warning(
                    "Low confidence transcription (%.2f): '%s'",
                    result.confidence,
                    result.text[:80],
                )
            return response
        except Exception as exc:
            logger.error("Deepgram transcription failed: %s", exc)
            return {"text": "", "confidence": 0.0, "error": str(exc)}

    # --- Whisper fallback path (legacy) ---
    is_webm = "webm" in content_type or filename.endswith(".webm")

    if is_webm:
        text, confidence = await _transcribe_with_confidence(
            audio_bytes, filename="audio.webm", mime_type="audio/webm", state=state
        )
        if not text and confidence == 0.0:
            logger.info("Direct webm transcription failed, falling back to ffmpeg")
            audio_bytes = await convert_webm_to_wav_normalized(audio_bytes)
            text, confidence = await _transcribe_with_confidence(audio_bytes, state=state)
    else:
        text, confidence = await _transcribe_with_confidence(audio_bytes, state=state)

    result_dict: dict[str, Any] = {"text": text, "confidence": confidence}

    if text and confidence < _LOW_CONFIDENCE_THRESHOLD:
        result_dict["low_confidence"] = True
        logger.warning(
            "Low confidence transcription (%.2f): '%s'",
            confidence,
            text[:80],
        )

    return result_dict


def _turn_probe_result(detector: str, *, available: bool) -> TurnProbeResponse:
    """A "turn is still going" answer, tagged with why we could not decide."""
    return TurnProbeResponse(ended=False, probability=0.0, detector=detector, available=available)


def _accept_turn_probe(state: AppState, client_host: str, min_interval_ms: float) -> bool:
    """Record a probe from ``client_host``, or reject it as too soon.

    ``pollVAD`` runs on ``requestAnimationFrame`` at roughly 60 Hz. The browser
    spaces its own probes, but this endpoint is unauthenticated and spawns an
    ffmpeg process per call, so it does not take the browser's word for it.
    """
    now = time.monotonic()
    last = state.turn_probe_seen.get(client_host)
    if last is not None and (now - last) * 1000.0 < min_interval_ms:
        return False

    if last is None and len(state.turn_probe_seen) >= _MAX_TURN_PROBE_CLIENTS:
        # Evict the least recently seen client; the table must not grow forever.
        oldest = min(state.turn_probe_seen, key=lambda host: state.turn_probe_seen[host])
        del state.turn_probe_seen[oldest]

    state.turn_probe_seen[client_host] = now
    return True


@app.post("/api/turn-probe", response_model=TurnProbeResponse)
async def turn_probe(
    request: Request,
    file: UploadFile,
    silence_ms: int = Form(...),
    state: AppState = Depends(get_app_state),
) -> TurnProbeResponse:
    """Judge whether the speaker has finished, given the utterance so far.

    The browser keeps the cheap acoustic gate and decides *when* to ask; this
    endpoint runs the semantic detector and decides *whether* the turn is over.
    No turn model, feature extraction, or ONNX runtime lives in the browser.

    ``file`` is the whole accumulated MediaRecorder blob, not a trailing slice:
    webm chunks after the first carry no EBML header and will not decode on
    their own. Truncation to the model's 8 s window happens inside the detector.

    Never raises. Every failure path returns a not-ended answer, because the
    browser's fixed-silence fallback is what keeps voice input working and a
    5xx here would only add latency to reaching it.
    """
    detector = state.turn_detector
    if detector is None or not detector.available:
        # Permanent for this session: tell the browser to stop asking.
        return _turn_probe_result("unavailable", available=False)

    client_host = request.client.host if request.client else "unknown"
    probe_interval_ms = _int_setting(state.settings, "turn_probe_silence_ms", 150)
    if not _accept_turn_probe(state, client_host, probe_interval_ms / 2):
        return _turn_probe_result("throttled", available=True)

    declared_size = getattr(file, "size", None)
    if declared_size is not None and declared_size > _MAX_TURN_PROBE_BYTES:
        logger.warning(
            "Rejecting %d-byte turn probe from %s (limit %d)",
            declared_size,
            client_host,
            _MAX_TURN_PROBE_BYTES,
        )
        return _turn_probe_result("too_large", available=True)

    audio_bytes = await file.read()
    if len(audio_bytes) > _MAX_TURN_PROBE_BYTES:
        logger.warning(
            "Rejecting %d-byte turn probe from %s (limit %d)",
            len(audio_bytes),
            client_host,
            _MAX_TURN_PROBE_BYTES,
        )
        return _turn_probe_result("too_large", available=True)

    samples = await decode_webm_to_samples(audio_bytes)
    if samples is None:
        # Transient: one undecodable blob should not disable probing for good.
        return _turn_probe_result("decode_failed", available=True)

    try:
        # Inference is sub-20ms but synchronous; keep it off the event loop so a
        # probe cannot stutter concurrent TTS streaming.
        decision = await asyncio.to_thread(
            detector.evaluate, samples, _TURN_PROBE_SAMPLE_RATE, silence_ms
        )
    except Exception as exc:
        logger.error("Turn probe evaluation failed: %s", exc)
        return _turn_probe_result("error", available=True)

    return TurnProbeResponse(
        ended=decision.ended,
        probability=decision.probability,
        detector=decision.detector,
        available=True,
    )


@app.post("/api/tts")
async def text_to_speech(request: TTSRequest, state: AppState = Depends(get_app_state)):
    """Convert text to speech. Routes to Cartesia (v2) or ElevenLabs (fallback)."""
    clean = preprocess_for_tts(request.text)

    # Check TTS cache first (works for all backends)
    if clean in state.tts_cache:
        content_type = "audio/pcm" if state.cartesia_client else "audio/mpeg"
        return Response(content=state.tts_cache[clean], media_type=content_type)

    # --- Cartesia path (v2 default) ---
    if state.cartesia_client is not None:
        try:
            audio = await state.cartesia_client.synthesize(clean)
            if audio:
                return Response(
                    content=audio,
                    media_type=state.cartesia_client.audio_content_type,
                )
            return Response(
                content=json.dumps({"error": "Cartesia returned empty audio"}),
                status_code=502,
                media_type="application/json",
            )
        except Exception as exc:
            logger.error("Cartesia TTS failed: %s", exc)
            return Response(
                content=json.dumps({"error": f"TTS failed: {exc}"}),
                status_code=502,
                media_type="application/json",
            )

    # --- ElevenLabs fallback path ---
    if not state.settings.elevenlabs_api_key or not state.settings.voice_id:
        return Response(
            content=json.dumps({"error": "No TTS backend configured"}),
            status_code=503,
            media_type="application/json",
        )

    if state.tts_client is None:
        return Response(
            content=json.dumps({"error": "TTS client not initialized"}),
            status_code=503,
            media_type="application/json",
        )

    try:
        resp = await state.tts_client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{state.settings.voice_id}",
            headers={
                "xi-api-key": state.settings.elevenlabs_api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": clean,
                "model_id": state.settings.elevenlabs_model_id,
                "voice_settings": {
                    "stability": 0.75,
                    "similarity_boost": 0.80,
                    "style": 0.15,
                },
            },
        )
        resp.raise_for_status()
        return Response(content=resp.content, media_type="audio/mpeg")
    except httpx.HTTPError as exc:
        logger.error("ElevenLabs TTS failed: %s", exc)
        return Response(
            content=json.dumps({"error": f"TTS failed: {exc}"}),
            status_code=502,
            media_type="application/json",
        )


# ---------------------------------------------------------------------------
# WebSocket: /ws/telemetry
# ---------------------------------------------------------------------------


@app.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket, state: AppState = Depends(get_ws_app_state)):
    """Stream simulator telemetry to the browser.

    Connects (or reconnects) to the SimConnect bridge on demand and
    proxies telemetry as JSON. Falls back to polling if the bridge
    subscriber model isn't active.
    """
    await ws.accept()
    logger.info("Telemetry WebSocket client connected")

    telemetry_url = state.settings.telemetry_service_url

    try:
        while True:
            # Connect to the telemetry service consumer endpoint
            try:
                async with ws_lib.connect(telemetry_url) as bridge_ws:
                    logger.info(
                        "Telemetry proxy connected to service at %s",
                        telemetry_url,
                    )
                    # Bridge WS is open, but don't claim sim is connected
                    # until we receive data with connected=true from the bridge
                    await ws.send_json({"type": "telemetry", "connected": False, "data": None})

                    async for raw_msg in bridge_ws:
                        try:
                            data = json.loads(raw_msg)
                            # Use the bridge's SimConnect status, not WS status
                            sim_active = data.get("connected", False)
                            state.bridge_last_seen = time.monotonic()
                            state.bridge_connected = sim_active
                            # Detect flight phase
                            if state.phase_detector and "position" in data:
                                try:
                                    sim_state = SimState.model_validate(data)
                                    fp = state.phase_detector.update(sim_state)
                                    data["flight_phase"] = fp.value
                                except Exception:
                                    pass
                            await ws.send_json(
                                {
                                    "type": "telemetry",
                                    "connected": sim_active,
                                    "data": data,
                                }
                            )
                        except json.JSONDecodeError:
                            pass

            except (ConnectionRefusedError, OSError, Exception) as exc:
                logger.debug("Telemetry service not available (%s), retrying in 3s", exc)
                await ws.send_json(
                    {
                        "type": "telemetry",
                        "connected": False,
                        "flight_phase": "PREFLIGHT",
                        "data": None,
                    }
                )
                await asyncio.sleep(3.0)

    except WebSocketDisconnect:
        logger.info("Telemetry WebSocket client disconnected")
    except Exception as exc:
        logger.warning("Telemetry WebSocket error: %s", exc)


# ---------------------------------------------------------------------------
# WebSocket: /ws/chat  (with barge-in / interruption support)
# ---------------------------------------------------------------------------


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket, state: AppState = Depends(get_ws_app_state)):
    """Chat with MERLIN, with barge-in interruption support.

    Receives JSON messages or binary audio data.

    Text messages:
      {"type": "audio_start", "mime": "audio/webm"}  -- next binary = audio
      {"text": "user message"}                         -- direct text input
      {"type": "interrupt"}                            -- cancel current response

    Binary messages:
      Raw audio bytes (preceded by audio_start marker)

    Streams response as:
      {"type": "text", "content": "..."}      -- streamed text chunks
      {"type": "transcription", "text": "...", "confidence": 0.85}
      {"type": "tts_audio", "size": N}        -- followed by binary MP3
      {"type": "interrupted"}                 -- response was cancelled
      {"type": "done"}                        -- end of response
      {"type": "listening"}                   -- MERLIN is ready for input
    """
    await ws.accept()
    logger.info("Chat WebSocket client connected")

    pending_audio_mime: str | None = None

    # Active response task -- cancelled on barge-in
    active_response_task: asyncio.Task[None] | None = None
    # Event signalled when the user interrupts
    interrupt_event = asyncio.Event()

    async def _cancel_active_response() -> None:
        """Cancel any in-progress Claude stream and TTS pipeline."""
        nonlocal active_response_task
        if active_response_task and not active_response_task.done():
            interrupt_event.set()
            active_response_task.cancel()
            try:
                await active_response_task
            except (asyncio.CancelledError, Exception):
                pass
            logger.info("Active response cancelled (barge-in)")
            try:
                await ws.send_json({"type": "interrupted"})
            except Exception:
                pass
        active_response_task = None

    try:
        while True:
            message = await ws.receive()

            # Handle binary audio data from the browser's MediaRecorder
            if "bytes" in message and message["bytes"]:
                audio_bytes = message["bytes"]
                logger.info(
                    "Received %d bytes of audio (mime: %s)",
                    len(audio_bytes),
                    pending_audio_mime,
                )

                # Barge-in: cancel current response if one is active
                await _cancel_active_response()

                user_text, confidence = await _transcribe_audio_bytes_with_confidence(
                    audio_bytes,
                    pending_audio_mime or "audio/webm",
                    state,
                )
                pending_audio_mime = None

                if not user_text:
                    await ws.send_json(
                        {
                            "type": "error",
                            "content": "Could not transcribe audio",
                        }
                    )
                    continue

                await ws.send_json(
                    {
                        "type": "transcription",
                        "text": user_text,
                        "confidence": round(confidence, 2),
                    }
                )

                # If confidence is very low, retry once with the raw audio
                if confidence < _LOW_CONFIDENCE_THRESHOLD and user_text:
                    logger.warning(
                        "Low confidence (%.2f), sending anyway: '%s'",
                        confidence,
                        user_text[:60],
                    )

            elif "text" in message and message["text"]:
                raw = message["text"]
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send_json(
                        {
                            "type": "error",
                            "content": "Invalid JSON",
                        }
                    )
                    continue

                # Handle audio_start marker (next message will be binary)
                if msg.get("type") == "audio_start":
                    pending_audio_mime = msg.get("mime", "audio/webm")
                    # Barge-in: if MERLIN is speaking and user starts recording
                    await _cancel_active_response()
                    continue

                # Handle explicit interrupt request
                if msg.get("type") == "interrupt":
                    await _cancel_active_response()
                    continue

                user_text = msg.get("text", "")
                if not user_text:
                    await ws.send_json(
                        {
                            "type": "error",
                            "content": "No text provided",
                        }
                    )
                    continue

                # Barge-in: cancel if user sends text while MERLIN responding
                await _cancel_active_response()

            else:
                continue

            # Reset interrupt event for the new response
            interrupt_event.clear()

            # Launch response streaming as a cancellable task
            active_response_task = asyncio.create_task(
                _stream_response(ws, user_text, interrupt_event, state)
            )

    except WebSocketDisconnect:
        logger.info("Chat WebSocket client disconnected")
        await _cancel_active_response()
    except Exception as exc:
        logger.warning("Chat WebSocket error: %s", exc)
        await _cancel_active_response()


# ---------------------------------------------------------------------------
# Cartesia TTS streaming (v2 default)
# ---------------------------------------------------------------------------


async def _tts_cartesia_stream(
    ws: WebSocket,
    tts_queue: asyncio.Queue[str | None],
    interrupt: asyncio.Event,
    state: AppState,
) -> None:
    """Stream TTS via Cartesia REST synthesis per sentence.

    Cartesia achieves ~90ms TTFB so per-sentence REST calls are fast enough
    for real-time cockpit use. Audio is sent as PCM to the browser.
    """
    while True:
        if interrupt.is_set():
            break
        try:
            sentence = await asyncio.wait_for(tts_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            continue
        if sentence is None:
            break
        if interrupt.is_set():
            break

        clean_text = preprocess_for_tts(sentence)
        if not clean_text:
            continue

        # Check cache
        if clean_text in state.tts_cache:
            await ws.send_json({"type": "tts_audio", "size": len(state.tts_cache[clean_text])})
            await ws.send_bytes(state.tts_cache[clean_text])
            continue

        try:
            assert state.cartesia_client is not None
            audio = await state.cartesia_client.synthesize(clean_text)
            if audio and not interrupt.is_set():
                await ws.send_json({"type": "tts_audio", "size": len(audio)})
                await ws.send_bytes(audio)
        except Exception as exc:
            logger.warning("Cartesia TTS failed for chunk: %s", exc)


# ---------------------------------------------------------------------------
# ElevenLabs REST per-sentence TTS
# ---------------------------------------------------------------------------


async def _tts_elevenlabs_stream(
    ws: WebSocket,
    tts_queue: asyncio.Queue[str | None],
    interrupt: asyncio.Event,
    state: AppState,
) -> None:
    """Synthesize TTS via ElevenLabs REST, one sentence at a time.

    Produces complete audio per sentence — avoids the garbled playback
    caused by WebSocket chunk fragmentation in the browser pipeline.
    """
    voice_id = state.settings.voice_id
    model_id = state.settings.elevenlabs_model_id
    api_key = state.settings.elevenlabs_api_key

    while True:
        if interrupt.is_set():
            break
        try:
            sentence = await asyncio.wait_for(tts_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            continue
        if sentence is None:
            break
        if interrupt.is_set():
            break

        clean_text = preprocess_for_tts(sentence)
        if not clean_text:
            continue

        # Check cache
        if clean_text in state.tts_cache:
            await ws.send_json({"type": "tts_audio", "size": len(state.tts_cache[clean_text])})
            await ws.send_bytes(state.tts_cache[clean_text])
            continue

        try:
            resp = await state.tts_client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream",
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": clean_text,
                    "model_id": model_id,
                    "voice_settings": {
                        "stability": state.settings.tts_stability,
                        "similarity_boost": state.settings.tts_similarity_boost,
                        "style": state.settings.tts_style,
                    },
                },
            )
            resp.raise_for_status()
            if resp.content and not interrupt.is_set():
                await ws.send_json({"type": "tts_audio", "size": len(resp.content)})
                await ws.send_bytes(resp.content)
        except Exception as exc:
            logger.warning("ElevenLabs TTS failed for chunk: %s", exc)


# ---------------------------------------------------------------------------
# ElevenLabs WebSocket streaming TTS (legacy — not used, causes garbled audio)
# ---------------------------------------------------------------------------


async def _tts_websocket_stream(
    ws: WebSocket,
    tts_queue: asyncio.Queue[str | None],
    interrupt: asyncio.Event,
    state: AppState,
) -> None:
    """Stream TTS via ElevenLabs WebSocket API.

    Opens a single WebSocket connection per response, pipes sanitized text
    chunks through it, and forwards audio chunks to the browser as they
    arrive. Falls back to REST-based TTS if the WebSocket approach fails.
    """
    voice_id = state.settings.voice_id
    model_id = state.settings.elevenlabs_model_id
    api_key = state.settings.elevenlabs_api_key
    ws_url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        f"/stream-input?model_id={model_id}&output_format=mp3_22050_32"
    )

    try:
        async with ws_lib.connect(ws_url) as tts_ws:
            # Send initial config
            await tts_ws.send(
                json.dumps(
                    {
                        "text": " ",
                        "voice_settings": {
                            "stability": 0.75,
                            "similarity_boost": 0.80,
                            "style": 0.15,
                        },
                        "xi_api_key": api_key,
                    }
                )
            )

            # Task to receive audio chunks from ElevenLabs
            audio_done = asyncio.Event()

            async def _receive_audio() -> None:
                """Receive audio chunks from ElevenLabs and forward to browser."""
                try:
                    async for msg in tts_ws:
                        if interrupt.is_set():
                            break
                        if isinstance(msg, bytes):
                            # Binary audio chunk
                            await ws.send_json(
                                {
                                    "type": "tts_audio",
                                    "size": len(msg),
                                }
                            )
                            await ws.send_bytes(msg)
                        elif isinstance(msg, str):
                            data = json.loads(msg)
                            if data.get("isFinal"):
                                break
                            # Some responses include base64 audio
                            audio_b64 = data.get("audio")
                            if audio_b64:
                                audio_chunk = base64.b64decode(audio_b64)
                                if audio_chunk:
                                    await ws.send_json(
                                        {
                                            "type": "tts_audio",
                                            "size": len(audio_chunk),
                                        }
                                    )
                                    await ws.send_bytes(audio_chunk)
                except Exception as exc:
                    logger.debug("TTS WS receive error: %s", exc)
                finally:
                    audio_done.set()

            recv_task = asyncio.create_task(_receive_audio())

            # Feed text chunks from the queue into the WebSocket
            while True:
                if interrupt.is_set():
                    break
                try:
                    sentence = await asyncio.wait_for(tts_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                if sentence is None:
                    break  # Poison pill -- done
                if interrupt.is_set():
                    break

                clean_text = preprocess_for_tts(sentence)
                if not clean_text:
                    continue

                # Check cache before sending over WebSocket
                if clean_text in state.tts_cache:
                    await ws.send_json(
                        {
                            "type": "tts_audio",
                            "size": len(state.tts_cache[clean_text]),
                        }
                    )
                    await ws.send_bytes(state.tts_cache[clean_text])
                    continue

                await tts_ws.send(
                    json.dumps(
                        {
                            "text": clean_text + " ",
                            "try_trigger_generation": True,
                        }
                    )
                )

            # Send flush signal to indicate end of input
            try:
                await tts_ws.send(json.dumps({"text": ""}))
            except Exception:
                pass

            # Wait for remaining audio to arrive
            try:
                await asyncio.wait_for(recv_task, timeout=15.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                recv_task.cancel()

    except Exception as exc:
        logger.warning("ElevenLabs WebSocket TTS failed (%s), falling back to REST", exc)
        # Fallback: drain the queue and use REST-based TTS
        await _tts_rest_fallback(ws, tts_queue, interrupt, state)


async def _tts_rest_fallback(
    ws: WebSocket,
    tts_queue: asyncio.Queue[str | None],
    interrupt: asyncio.Event,
    state: AppState,
) -> None:
    """REST-based TTS fallback -- processes remaining items in tts_queue."""
    while True:
        if interrupt.is_set():
            break
        try:
            sentence = await asyncio.wait_for(tts_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            continue
        if sentence is None:
            break
        if interrupt.is_set():
            break
        await _send_tts_chunk_rest(ws, sentence, state)


async def _stream_response(
    ws: WebSocket,
    user_text: str,
    interrupt: asyncio.Event,
    state: AppState,
) -> None:
    """Stream Claude response with TTS. Cancellable via interrupt event.

    Uses ElevenLabs WebSocket streaming for low-latency audio, with
    REST fallback. This runs as a task so it can be cancelled when the
    user barges in.
    """
    tts_enabled = state.cartesia_client is not None or bool(
        state.settings.elevenlabs_api_key and getattr(state.settings, "elevenlabs_voice_id", "")
    )
    sentence_buffer = ""
    full_response = ""

    # TTS queue ensures audio chunks are sent in order
    tts_queue: asyncio.Queue[str | None] = asyncio.Queue()

    # Choose TTS streaming strategy based on backend
    if tts_enabled and state.cartesia_client is not None:
        # Cartesia: use REST synthesis per sentence (still fast at ~90ms TTFB)
        tts_task: asyncio.Task[None] | None = asyncio.create_task(
            _tts_cartesia_stream(ws, tts_queue, interrupt, state)
        )
    elif tts_enabled:
        # ElevenLabs: REST per-sentence (WS streaming causes garbled audio
        # from chunk fragmentation in the browser playback pipeline)
        tts_task = asyncio.create_task(_tts_elevenlabs_stream(ws, tts_queue, interrupt, state))
    else:
        tts_task = None

    try:
        assert state.claude_client is not None
        # Pass current sim state so Claude has telemetry context
        current_sim_state = None
        if state.sim_connected and state.sim_client is not None:
            current_sim_state = state.sim_client.state
            if state.phase_detector:
                detected = state.phase_detector.update(current_sim_state)
                current_sim_state.flight_phase = detected

        # Queue for command status messages from tool callbacks.
        # The callback is synchronous so it cannot await ws.send_json
        # directly; instead it queues messages we drain after each chunk.
        command_status_queue: list[dict[str, Any]] = []

        def _on_tool_result(tool_name: str, tool_input: dict[str, Any], tool_result: Any) -> None:
            """Classify a command outcome for the browser: advisory, withheld, failed, done.

            The three-way split is explicit rather than inferred from the absence of
            an ``"error"`` key, because the advisory dry run and the assisted
            withhold both carry no ``"error"`` by design (plan 02-04). The previous
            ``success = "error" not in tool_result`` therefore reported a command
            that was never transmitted as executed -- the pilot saw "GEAR DOWN" for
            a gear that never moved (RESEARCH B8, threat T-02-09-01).
            """
            if tool_name != "set_aircraft_control":
                return
            system = tool_input.get("system", "unknown")
            action = tool_input.get("action", "unknown")
            result = tool_result if isinstance(tool_result, dict) else {}
            label = f"{system.upper()} {action.upper()}"

            # authority_level / authority_reason are copied through verbatim, never
            # mapped or defaulted. AuthorityReason has four members and the browser
            # renders an unrecognised one as-is; substituting "config" for a missing
            # reason would report a crashed subsystem as a deliberate configuration.
            if result.get("advisory"):
                command_status_queue.append(
                    {
                        "type": "command_advisory",
                        "system": system,
                        "action": action,
                        "message": f"{label} -- advisory, not sent",
                        "would_execute": result.get("would_execute"),
                        "authority_level": result.get("authority_level"),
                        "authority_reason": result.get("authority_reason"),
                    }
                )
                return

            if result.get("withheld"):
                safety = result.get("safety") or {}
                command_status_queue.append(
                    {
                        "type": "command_withheld",
                        "system": system,
                        "action": action,
                        "message": f"{label} -- withheld, yours to make",
                        "authority_level": result.get("authority_level"),
                        "authority_reason": result.get("authority_reason"),
                        "safety_reason": safety.get("reason"),
                    }
                )
                return

            success = "error" not in result
            message = label if success else f"{label} failed"
            command_status_queue.append(
                {
                    "type": "command_status",
                    "system": system,
                    "action": action,
                    "success": success,
                    "message": message,
                }
            )

        async for chunk in state.claude_client.chat(
            user_text,
            sim_state=current_sim_state,
            on_tool_result=_on_tool_result,
        ):
            if interrupt.is_set():
                logger.info("Response interrupted mid-stream")
                break

            # Drain any queued command status messages before text
            while command_status_queue:
                await ws.send_json(command_status_queue.pop(0))

            full_response += chunk
            await ws.send_json({"type": "text", "content": chunk})

            if tts_enabled:
                sentence_buffer += chunk
                sent, remaining = _split_at_sentence(sentence_buffer)
                if sent:
                    sentence_buffer = remaining
                    await tts_queue.put(sent)

        # Drain any remaining command status messages after stream ends
        while command_status_queue:
            await ws.send_json(command_status_queue.pop(0))

        # Flush remaining text to TTS (if not interrupted)
        if tts_enabled and sentence_buffer.strip() and not interrupt.is_set():
            await tts_queue.put(sentence_buffer.strip())
            sentence_buffer = ""

    except asyncio.CancelledError:
        logger.info("Response task cancelled")
        raise
    except Exception as exc:
        logger.exception("Claude chat error")
        await ws.send_json(
            {
                "type": "error",
                "content": f"Chat error: {exc}",
            }
        )
    finally:
        # Flush any remaining text before sending poison pill
        if tts_task and sentence_buffer.strip() and not interrupt.is_set():
            await tts_queue.put(sentence_buffer.strip())
        # Signal TTS sender to finish
        if tts_task:
            await tts_queue.put(None)
            try:
                await asyncio.wait_for(tts_task, timeout=15.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                tts_task.cancel()

    if not interrupt.is_set():
        await ws.send_json({"type": "done"})

        # Brief pause after MERLIN finishes before signalling readiness
        await asyncio.sleep(_POST_SPEECH_PAUSE_SECS)
        await ws.send_json({"type": "listening"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# NOTE: TTS text sanitization uses orchestrator.tts_preprocessor.preprocess_for_tts
# which is imported at the top of this file. All TTS text cleaning is handled
# by that single module to avoid duplication.


def _split_at_sentence(text: str) -> tuple[str, str]:
    """Split text at a natural speech boundary. Returns (complete, remaining).

    Looks for sentence-ending punctuation first. If the buffer is getting long
    (>50 chars) without a sentence break, falls back to splitting at commas,
    semicolons, or colons to keep TTS chunks flowing.
    """
    # First try: sentence-ending punctuation (.!?) followed by space or end
    for i in range(len(text) - 1, -1, -1):
        if text[i] in ".!?" and (i + 1 >= len(text) or text[i + 1] in " \n"):
            return text[: i + 1].strip(), text[i + 1 :].lstrip()

    # Fallback for long buffers: split at clause boundaries (, ; :)
    if len(text) > 30:
        for i in range(len(text) - 1, -1, -1):
            if text[i] in ",;:" and i + 1 < len(text) and text[i + 1] == " ":
                return text[: i + 1].strip(), text[i + 1 :].lstrip()

    # Force-split very long buffers with no punctuation at all
    if len(text) > 100:
        # Split at last space
        last_space = text.rfind(" ", 0, 80)
        if last_space > 0:
            return text[:last_space].strip(), text[last_space:].lstrip()

    return "", text  # No boundary found yet -- keep buffering


async def _send_tts_chunk_rest(ws: WebSocket, text: str, state: AppState) -> None:
    """Synthesize a sentence via REST and send audio over WebSocket.

    This is the REST-based fallback used when WebSocket TTS is unavailable.
    """
    clean_text = preprocess_for_tts(text)
    if not clean_text:
        return

    # Check TTS cache first
    if clean_text in state.tts_cache:
        await ws.send_json(
            {
                "type": "tts_audio",
                "size": len(state.tts_cache[clean_text]),
            }
        )
        await ws.send_bytes(state.tts_cache[clean_text])
        return

    if state.tts_client is None:
        return

    try:
        resp = await state.tts_client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{state.settings.voice_id}/stream",
            headers={
                "xi-api-key": state.settings.elevenlabs_api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": clean_text,
                "model_id": state.settings.elevenlabs_model_id,
                "voice_settings": {
                    "stability": 0.75,
                    "similarity_boost": 0.80,
                    "style": 0.15,
                },
            },
        )
        resp.raise_for_status()
        # Send audio as binary WebSocket frame -- browser will play it
        await ws.send_json(
            {
                "type": "tts_audio",
                "size": len(resp.content),
            }
        )
        await ws.send_bytes(resp.content)
    except Exception as exc:
        logger.warning("TTS chunk failed: %s", exc)


async def _transcribe_with_confidence(
    audio_bytes: bytes,
    filename: str = "audio.wav",
    mime_type: str = "audio/wav",
    *,
    state: AppState,
) -> tuple[str, float]:
    """Transcribe audio via the unified WhisperClient and return (text, confidence)."""
    try:
        if state.whisper_client is None:
            logger.error("Whisper client not initialized")
            return "", 0.0
        result = await state.whisper_client.transcribe_with_confidence(
            audio_bytes,
            filename=filename,
            mime_type=mime_type,
        )
        logger.info("Transcribed (confidence=%.2f): %s", result.confidence, result.text[:80])
        return result.text, result.confidence
    except Exception as exc:
        logger.error("Whisper transcription failed: %s", exc)
        return "", 0.0


def _estimate_wav_duration_secs(wav_bytes: bytes) -> float:
    """Estimate the duration of a 16-kHz mono 16-bit WAV from its byte length.

    Returns 0.0 for non-WAV or unrecognisable data so callers can fall through.
    """
    header_size = 44  # standard WAV header
    if len(wav_bytes) <= header_size:
        return 0.0
    # 16-kHz, mono, 16-bit = 32 000 bytes per second of audio
    return (len(wav_bytes) - header_size) / 32_000


async def _transcribe_audio_bytes_with_confidence(
    audio_bytes: bytes,
    mime_type: str,
    state: AppState,
) -> tuple[str, float]:
    """Transcribe browser audio. Routes to Deepgram (v2) or Whisper (legacy).

    Returns ``("", -1.0)`` when the audio is too short to transcribe (so
    callers can distinguish "nothing useful" from a real STT error).
    """
    needs_conversion = "webm" in mime_type or "ogg" in mime_type

    # Convert to WAV early so we can measure duration for both paths
    if needs_conversion:
        audio_bytes = await convert_webm_to_wav_normalized(audio_bytes)

    # --- Minimum duration gate ---
    duration = _estimate_wav_duration_secs(audio_bytes)
    logger.info(
        "Audio for STT: %d bytes, estimated %.2fs (min %.2fs)",
        len(audio_bytes),
        duration,
        _MIN_AUDIO_DURATION_SECS,
    )
    if 0 < duration < _MIN_AUDIO_DURATION_SECS:
        logger.info("Audio too short (%.2fs), discarding", duration)
        return "", -1.0  # sentinel: too-short, not an error

    # --- Deepgram path (v2 default) ---
    if state.deepgram_client is not None:
        try:
            result = await state.deepgram_client.transcribe(audio_bytes)
            return result.text, result.confidence
        except Exception as exc:
            logger.error("Deepgram transcription failed: %s", exc)
            return "", 0.0

    # --- Whisper fallback path ---
    if needs_conversion:
        # Already converted above; try with webm metadata hint
        text, confidence = await _transcribe_with_confidence(
            audio_bytes,
            filename="audio.webm",
            mime_type="audio/webm",
            state=state,
        )
        if text or confidence > 0.0:
            return text, confidence

        logger.info("Direct webm transcription failed, falling back to ffmpeg")
        audio_bytes = await convert_webm_to_wav_normalized(audio_bytes)

    return await _transcribe_with_confidence(audio_bytes, state=state)
