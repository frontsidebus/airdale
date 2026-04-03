"""Kokoro TTS HTTP server for MERLIN local inference.

Exposes a simple FastAPI service that wraps the Kokoro TTS engine,
producing WAV audio from text input.

Endpoints:
    POST /tts          -- Synthesize text to streaming WAV audio
    POST /tts/cache    -- Pre-generate audio for multiple phrases
    GET  /voices       -- List available Kokoro voice packs
    GET  /health       -- Health check
"""

from __future__ import annotations

import io
import json
import logging
import os
import struct
import time
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from fastapi import FastAPI
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger("merlin.tts")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MODEL_DIR = os.environ.get("TTS_MODEL_DIR", "/models")
_DEFAULT_VOICE = os.environ.get("TTS_DEFAULT_VOICE", "af_heart")
_PORT = int(os.environ.get("TTS_PORT", "9091"))
_SAMPLE_RATE = 24000

# ---------------------------------------------------------------------------
# Global model state
# ---------------------------------------------------------------------------

_pipeline: Any = None
_model_loaded = False


def _load_model() -> None:
    """Load the Kokoro TTS pipeline at startup."""
    global _pipeline, _model_loaded
    try:
        from kokoro import KPipeline

        _pipeline = KPipeline(lang_code="a")
        _model_loaded = True
        logger.info("Kokoro TTS model loaded successfully")
    except Exception:
        logger.exception("Failed to load Kokoro TTS model")
        _model_loaded = False


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------


def _pcm_to_wav(samples: np.ndarray, sample_rate: int = _SAMPLE_RATE) -> bytes:
    """Convert float32 PCM samples to a complete WAV byte string."""
    # Clip and convert to int16
    clipped = np.clip(samples, -1.0, 1.0)
    pcm_int16 = (clipped * 32767).astype(np.int16)
    raw_pcm = pcm_int16.tobytes()

    # Build WAV header (44 bytes)
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(raw_pcm)

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,  # fmt chunk size
        1,  # PCM format
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + raw_pcm


def _generate_audio(text: str, voice_id: str) -> np.ndarray:
    """Generate audio samples from text using the Kokoro pipeline.

    Returns a float32 numpy array of audio samples.
    """
    assert _pipeline is not None, "Model not loaded"

    all_samples: list[np.ndarray] = []
    for _, _, audio in _pipeline(text, voice=voice_id):
        if audio is not None:
            all_samples.append(audio)

    if not all_samples:
        return np.array([], dtype=np.float32)

    return np.concatenate(all_samples)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class TTSRequest(BaseModel):
    text: str
    voice_id: str | None = None


class CacheRequest(BaseModel):
    phrases: list[str]
    voice_id: str | None = None


class VoiceInfo(BaseModel):
    id: str
    name: str
    language: str
    description: str


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_model()
    yield


app = FastAPI(
    title="MERLIN Kokoro TTS",
    description="Local TTS server for MERLIN AI co-pilot",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {
        "status": "ok" if _model_loaded else "degraded",
        "model_loaded": _model_loaded,
        "default_voice": _DEFAULT_VOICE,
    }


@app.post("/tts")
async def synthesize(request: TTSRequest):
    """Synthesize text to WAV audio.

    Returns a streaming WAV response for low time-to-first-byte.
    """
    if not _model_loaded or _pipeline is None:
        return Response(
            content=json.dumps({"error": "TTS model not loaded"}),
            status_code=503,
            media_type="application/json",
        )

    voice = request.voice_id or _DEFAULT_VOICE
    start = time.monotonic()

    try:
        samples = _generate_audio(request.text, voice)
        if samples.size == 0:
            return Response(
                content=json.dumps({"error": "No audio generated"}),
                status_code=500,
                media_type="application/json",
            )

        wav_bytes = _pcm_to_wav(samples)
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "Synthesized %d bytes in %.0fms for: %s",
            len(wav_bytes),
            elapsed_ms,
            request.text[:60],
        )

        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as exc:
        logger.exception("Synthesis failed")
        return Response(
            content=json.dumps({"error": str(exc)}),
            status_code=500,
            media_type="application/json",
        )


@app.post("/tts/cache")
async def cache_phrases(request: CacheRequest):
    """Pre-generate WAV audio for a list of phrases.

    Returns a JSON object mapping each phrase to base64-encoded WAV bytes.
    """
    import base64

    if not _model_loaded or _pipeline is None:
        return Response(
            content=json.dumps({"error": "TTS model not loaded"}),
            status_code=503,
            media_type="application/json",
        )

    voice = request.voice_id or _DEFAULT_VOICE
    results: dict[str, str] = {}

    for phrase in request.phrases:
        try:
            samples = _generate_audio(phrase, voice)
            if samples.size > 0:
                wav_bytes = _pcm_to_wav(samples)
                results[phrase] = base64.b64encode(wav_bytes).decode()
        except Exception as exc:
            logger.warning("Cache generation failed for '%s': %s", phrase, exc)

    return results


@app.get("/voices")
async def list_voices():
    """List available Kokoro voice packs.

    Returns built-in Kokoro v1.0 voices that are available for use.
    """
    # Kokoro built-in voices (English)
    voices = [
        VoiceInfo(
            id="af_heart",
            name="Heart",
            language="en-us",
            description="Warm, expressive American female voice",
        ),
        VoiceInfo(
            id="af_alloy",
            name="Alloy",
            language="en-us",
            description="Clear, professional American female voice",
        ),
        VoiceInfo(
            id="am_adam",
            name="Adam",
            language="en-us",
            description="Authoritative American male voice",
        ),
        VoiceInfo(
            id="am_michael",
            name="Michael",
            language="en-us",
            description="Calm, measured American male voice",
        ),
        VoiceInfo(
            id="bf_emma",
            name="Emma",
            language="en-gb",
            description="Clear British female voice",
        ),
        VoiceInfo(
            id="bm_george",
            name="George",
            language="en-gb",
            description="Deep British male voice",
        ),
    ]
    return [v.model_dump() for v in voices]


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )
    uvicorn.run(app, host="0.0.0.0", port=_PORT)
