"""REST endpoint tests for the MERLIN web server.

Covers:
- WTST-07: Status endpoint reports subsystem health
- WTST-04: Transcription endpoint returns text and confidence
- WTST-05: TTS phrase cache hits/misses and not-configured handling
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport


# ---------------------------------------------------------------------------
# WTST-07: Status endpoint
# ---------------------------------------------------------------------------


async def test_status_returns_subsystem_health(test_app, mock_app_state):
    """GET /api/status returns 200 with correct subsystem health fields."""
    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")

    assert resp.status_code == 200
    data = resp.json()
    assert "sim_connected" in data
    assert "chromadb_available" in data
    assert "whisper_available" in data
    assert "elevenlabs_configured" in data
    assert "claude_model" in data
    assert data["chromadb_available"] is True
    assert data["whisper_available"] is True
    assert data["elevenlabs_configured"] is True
    assert data["claude_model"] == "claude-sonnet-4-20250514"


async def test_status_whisper_unavailable(test_app, mock_app_state):
    """When whisper_client.is_available returns False, whisper_available is False."""
    mock_app_state.whisper_client.is_available = AsyncMock(return_value=False)

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")

    assert resp.status_code == 200
    assert resp.json()["whisper_available"] is False


# ---------------------------------------------------------------------------
# WTST-04: Transcription endpoint
# ---------------------------------------------------------------------------


@dataclass
class _FakeTranscriptionResult:
    """Minimal stand-in for orchestrator.whisper_client.TranscriptionResult."""

    text: str
    confidence: float
    language: str = "en"
    duration: float = 1.0


async def test_transcribe_returns_text_and_confidence(test_app, mock_app_state):
    """POST /api/transcribe with WAV file returns {text, confidence} from mocked whisper."""
    mock_app_state.whisper_client.transcribe_with_confidence.return_value = (
        _FakeTranscriptionResult(text="check altimeter setting", confidence=0.92)
    )

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/transcribe",
            files={"file": ("audio.wav", b"RIFF" + b"\x00" * 100, "audio/wav")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "check altimeter setting"
    assert data["confidence"] == 0.92
    assert "low_confidence" not in data


async def test_transcribe_low_confidence_flag(test_app, mock_app_state):
    """When confidence < 0.4, response includes low_confidence=True."""
    mock_app_state.whisper_client.transcribe_with_confidence.return_value = (
        _FakeTranscriptionResult(text="garbled input", confidence=0.25)
    )

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/transcribe",
            files={"file": ("audio.wav", b"RIFF" + b"\x00" * 100, "audio/wav")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "garbled input"
    assert data["confidence"] == 0.25
    assert data["low_confidence"] is True


async def test_transcribe_webm_direct(test_app, mock_app_state):
    """POST with webm content type transcribes directly via whisper_client."""
    mock_app_state.whisper_client.transcribe_with_confidence.return_value = (
        _FakeTranscriptionResult(text="request flight following", confidence=0.88)
    )

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/transcribe",
            files={"file": ("audio.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 100, "audio/webm")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "request flight following"
    assert data["confidence"] == 0.88


# ---------------------------------------------------------------------------
# WTST-05: TTS phrase cache and synthesis
# ---------------------------------------------------------------------------


async def test_tts_cache_hit(test_app, mock_app_state):
    """Pre-populated tts_cache returns cached audio without calling tts_client."""
    fake_mp3 = b"\xff\xfb\x90\x00" * 50
    mock_app_state.tts_cache["Roger."] = fake_mp3

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/tts", json={"text": "Roger."})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == fake_mp3
    # tts_client.post should NOT have been called
    mock_app_state.tts_client.post.assert_not_called()


async def test_tts_cache_miss_calls_client(test_app, mock_app_state):
    """POST /api/tts with uncached text calls tts_client.post and returns response."""
    fake_audio = b"fake-mp3-audio-bytes"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = fake_audio
    mock_response.raise_for_status = MagicMock()
    mock_app_state.tts_client.post = AsyncMock(return_value=mock_response)

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/tts", json={"text": "Climb and maintain flight level three five zero."})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == fake_audio
    mock_app_state.tts_client.post.assert_called_once()


async def test_tts_not_configured_returns_503(test_app, mock_app_state):
    """When elevenlabs_api_key is empty, TTS returns 503."""
    mock_app_state.settings.elevenlabs_api_key = ""

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/tts", json={"text": "Roger."})

    assert resp.status_code == 503
    assert "not configured" in resp.json()["error"].lower()
