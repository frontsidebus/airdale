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
)
from orchestrator.claude_client import ClaudeClient  # noqa: E402
from orchestrator.config import load_settings  # noqa: E402
from orchestrator.context_store import ContextStore  # noqa: E402
from orchestrator.flight_phase import FlightPhaseDetector  # noqa: E402
from orchestrator.sim_client import SimState, TelemetryClient  # noqa: E402
from orchestrator.stt.deepgram import DeepgramSTTClient  # noqa: E402
from orchestrator.tts.cartesia import CartesiaClient  # noqa: E402
from orchestrator.tts_preprocessor import preprocess_for_tts  # noqa: E402
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

# Brief pause (seconds) after MERLIN finishes speaking before accepting input
_POST_SPEECH_PAUSE_SECS = 0.3

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
    tts_cache: dict[str, bytes] = field(default_factory=dict)
    sim_connected: bool = False
    bridge_last_seen: float = 0.0
    bridge_connected: bool = False


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
                        "stability": 0.75,
                        "similarity_boost": 0.80,
                        "style": 0.15,
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

    # Telemetry client
    state.sim_client = TelemetryClient(url=settings.telemetry_service_url)
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

    # Claude client
    state.claude_client = ClaudeClient(
        api_key=settings.anthropic_api_key,
        model=settings.claude_model,
        sim_client=state.sim_client,
        context_store=state.context_store,
        max_tokens=settings.claude_max_tokens,
        max_tokens_briefing=settings.claude_max_tokens_briefing,
        max_history=settings.claude_max_history,
        temperature=settings.claude_temperature,
    )

    # TTS client — route to configured backend
    tts_backend = getattr(settings, "tts_backend", "elevenlabs")
    if tts_backend == "cartesia" and getattr(settings, "cartesia_api_key", ""):
        state.cartesia_client = CartesiaClient(
            api_key=settings.cartesia_api_key,
            voice_id=getattr(settings, "cartesia_voice_id", ""),
            model_id=getattr(settings, "cartesia_model_id", "sonic-2"),
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

    stt_backend = getattr(state.settings, "stt_backend", "whisper")
    tts_backend = getattr(state.settings, "tts_backend", "elevenlabs")

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
            state.settings.elevenlabs_api_key
            and getattr(state.settings, "elevenlabs_voice_id", "")
        ),
        "claude_model": state.settings.claude_model,
        "telemetry_service_url": state.settings.telemetry_service_url,
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
# ElevenLabs WebSocket streaming TTS
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
    tts_enabled = bool(state.settings.elevenlabs_api_key and state.settings.voice_id)
    sentence_buffer = ""
    full_response = ""

    # TTS queue ensures audio chunks are sent in order
    tts_queue: asyncio.Queue[str | None] = asyncio.Queue()

    # Pre-warm ElevenLabs TLS connection in the background
    if tts_enabled:

        async def _warmup_tts() -> None:
            try:
                if state.tts_client is not None:
                    await state.tts_client.head("https://api.elevenlabs.io/v1/voices")
            except Exception:
                pass

        asyncio.create_task(_warmup_tts())

    # Use WebSocket streaming TTS sender
    if tts_enabled:
        tts_task: asyncio.Task[None] | None = asyncio.create_task(
            _tts_websocket_stream(ws, tts_queue, interrupt, state)
        )
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

        async for chunk in state.claude_client.chat(user_text, sim_state=current_sim_state):
            if interrupt.is_set():
                logger.info("Response interrupted mid-stream")
                break

            full_response += chunk
            await ws.send_json({"type": "text", "content": chunk})

            if tts_enabled:
                sentence_buffer += chunk
                sent, remaining = _split_at_sentence(sentence_buffer)
                if sent:
                    sentence_buffer = remaining
                    await tts_queue.put(sent)

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


async def _transcribe_audio_bytes_with_confidence(
    audio_bytes: bytes,
    mime_type: str,
    state: AppState,
) -> tuple[str, float]:
    """Transcribe browser audio. Routes to Deepgram (v2) or Whisper (legacy)."""
    # --- Deepgram path (v2 default) ---
    if state.deepgram_client is not None:
        try:
            # Convert webm/ogg to wav for Deepgram
            if "webm" in mime_type or "ogg" in mime_type:
                audio_bytes = await convert_webm_to_wav_normalized(audio_bytes)
            result = await state.deepgram_client.transcribe(audio_bytes)
            return result.text, result.confidence
        except Exception as exc:
            logger.error("Deepgram transcription failed: %s", exc)
            return "", 0.0

    # --- Whisper fallback path ---
    if "webm" in mime_type or "ogg" in mime_type:
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
