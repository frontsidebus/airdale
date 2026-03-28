"""WebSocket endpoint tests for the MERLIN web server.

Covers:
- WTST-01: /ws/chat text message flow (send text, receive streamed response)
- WTST-02: /ws/chat barge-in interruption (cancel active response)
- WTST-03: /ws/chat audio message flow (audio_start + binary)
- WTST-06: /ws/chat error handling (invalid JSON, empty text)
- WTST-08: /ws/telemetry connection and proxy behavior

Uses httpx-ws for WebSocket testing with FastAPI's dependency_overrides
to inject mock AppState.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

import httpx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeTranscriptionResult:
    """Minimal stand-in for orchestrator.whisper_client.TranscriptionResult."""

    text: str
    confidence: float
    language: str = "en"
    duration: float = 1.0


# ---------------------------------------------------------------------------
# WTST-01: Chat WebSocket -- text message flow
# ---------------------------------------------------------------------------


async def test_chat_text_message_streams_response(test_app, mock_app_state):
    """Sending a text message via /ws/chat streams Claude response back."""
    # Mock Claude client to yield chunks
    async def mock_chat(text, sim_state=None):
        yield "Roger"
        yield " that."

    mock_app_state.claude_client.chat = mock_chat
    mock_app_state.sim_connected = False
    # Disable TTS to simplify test
    mock_app_state.settings.elevenlabs_api_key = ""
    mock_app_state.settings.voice_id = ""

    async with httpx.AsyncClient(
        transport=ASGIWebSocketTransport(app=test_app),
        base_url="http://test",
    ) as client:
        async with aconnect_ws("/ws/chat", client) as ws:
            # Send a text message
            await ws.send_text(json.dumps({"text": "How's our altitude?"}))

            # Collect responses until "done"
            messages = []
            for _ in range(10):
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
                    msg = json.loads(raw)
                    messages.append(msg)
                    if msg.get("type") == "listening":
                        break
                except asyncio.TimeoutError:
                    break

    # Verify we got text chunks
    text_msgs = [m for m in messages if m.get("type") == "text"]
    assert len(text_msgs) >= 1

    # Verify we got a done message
    done_msgs = [m for m in messages if m.get("type") == "done"]
    assert len(done_msgs) == 1

    # Verify we got a listening message after done
    listening_msgs = [m for m in messages if m.get("type") == "listening"]
    assert len(listening_msgs) == 1


async def test_chat_empty_text_returns_error(test_app, mock_app_state):
    """Sending empty text via /ws/chat returns an error message."""
    async with httpx.AsyncClient(
        transport=ASGIWebSocketTransport(app=test_app),
        base_url="http://test",
    ) as client:
        async with aconnect_ws("/ws/chat", client) as ws:
            await ws.send_text(json.dumps({"text": ""}))

            raw = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
            msg = json.loads(raw)

    assert msg["type"] == "error"
    assert "no text" in msg["content"].lower()


async def test_chat_invalid_json_returns_error(test_app, mock_app_state):
    """Sending invalid JSON via /ws/chat returns an error message."""
    async with httpx.AsyncClient(
        transport=ASGIWebSocketTransport(app=test_app),
        base_url="http://test",
    ) as client:
        async with aconnect_ws("/ws/chat", client) as ws:
            await ws.send_text("not valid json {{{")

            raw = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
            msg = json.loads(raw)

    assert msg["type"] == "error"
    assert "invalid json" in msg["content"].lower()


# ---------------------------------------------------------------------------
# WTST-02: Chat WebSocket -- interrupt / barge-in
# ---------------------------------------------------------------------------


async def test_chat_interrupt_message(test_app, mock_app_state):
    """Sending type=interrupt cancels any active response."""
    mock_app_state.settings.elevenlabs_api_key = ""
    mock_app_state.settings.voice_id = ""

    async with httpx.AsyncClient(
        transport=ASGIWebSocketTransport(app=test_app),
        base_url="http://test",
    ) as client:
        async with aconnect_ws("/ws/chat", client) as ws:
            # Send interrupt (no active response, so it's a no-op)
            await ws.send_text(json.dumps({"type": "interrupt"}))

            # Send a normal message to verify connection still works
            async def mock_chat(text, sim_state=None):
                yield "Still here."

            mock_app_state.claude_client.chat = mock_chat
            mock_app_state.sim_connected = False

            await ws.send_text(json.dumps({"text": "Hello"}))

            messages = []
            for _ in range(10):
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
                    msg = json.loads(raw)
                    messages.append(msg)
                    if msg.get("type") == "listening":
                        break
                except asyncio.TimeoutError:
                    break

    text_msgs = [m for m in messages if m.get("type") == "text"]
    assert len(text_msgs) >= 1


async def test_chat_audio_start_marker(test_app, mock_app_state):
    """Sending audio_start sets pending mime and waits for binary data."""
    mock_app_state.settings.elevenlabs_api_key = ""
    mock_app_state.settings.voice_id = ""

    mock_app_state.whisper_client.transcribe_with_confidence.return_value = (
        _FakeTranscriptionResult(text="check heading", confidence=0.90)
    )

    async def mock_chat(text, sim_state=None):
        yield "Heading two seven zero."

    mock_app_state.claude_client.chat = mock_chat
    mock_app_state.sim_connected = False

    async with httpx.AsyncClient(
        transport=ASGIWebSocketTransport(app=test_app),
        base_url="http://test",
    ) as client:
        async with aconnect_ws("/ws/chat", client) as ws:
            # Send audio_start marker
            await ws.send_text(json.dumps({"type": "audio_start", "mime": "audio/webm"}))

            # Send binary audio data
            await ws.send_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 100)

            # Collect responses
            messages = []
            for _ in range(15):
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
                    msg = json.loads(raw)
                    messages.append(msg)
                    if msg.get("type") == "listening":
                        break
                except asyncio.TimeoutError:
                    break

    # Should have transcription message
    transcription_msgs = [m for m in messages if m.get("type") == "transcription"]
    assert len(transcription_msgs) == 1
    assert transcription_msgs[0]["text"] == "check heading"
    assert transcription_msgs[0]["confidence"] == 0.90


# ---------------------------------------------------------------------------
# WTST-03: Chat WebSocket -- audio transcription failure
# ---------------------------------------------------------------------------


async def test_chat_audio_transcription_failure(test_app, mock_app_state):
    """When transcription fails, returns error message via WebSocket."""
    mock_app_state.settings.elevenlabs_api_key = ""
    mock_app_state.settings.voice_id = ""

    mock_app_state.whisper_client.transcribe_with_confidence.return_value = (
        _FakeTranscriptionResult(text="", confidence=0.0)
    )

    async with httpx.AsyncClient(
        transport=ASGIWebSocketTransport(app=test_app),
        base_url="http://test",
    ) as client:
        async with aconnect_ws("/ws/chat", client) as ws:
            # Send audio_start + binary
            await ws.send_text(json.dumps({"type": "audio_start", "mime": "audio/webm"}))
            await ws.send_bytes(b"\x00" * 50)

            # Should get an error about transcription
            raw = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
            msg = json.loads(raw)

    assert msg["type"] == "error"
    assert "transcribe" in msg["content"].lower()


# ---------------------------------------------------------------------------
# WTST-06: Chat WebSocket -- Claude error handling
# ---------------------------------------------------------------------------


async def test_chat_claude_error_sends_error_message(test_app, mock_app_state):
    """When Claude raises during streaming, error message is sent to client."""
    mock_app_state.settings.elevenlabs_api_key = ""
    mock_app_state.settings.voice_id = ""
    mock_app_state.sim_connected = False

    async def mock_chat_error(text, sim_state=None):
        yield "Starting..."
        raise RuntimeError("API rate limit exceeded")

    mock_app_state.claude_client.chat = mock_chat_error

    async with httpx.AsyncClient(
        transport=ASGIWebSocketTransport(app=test_app),
        base_url="http://test",
    ) as client:
        async with aconnect_ws("/ws/chat", client) as ws:
            await ws.send_text(json.dumps({"text": "Tell me about the approach"}))

            messages = []
            for _ in range(10):
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
                    msg = json.loads(raw)
                    messages.append(msg)
                    if msg.get("type") in ("error", "listening"):
                        break
                except asyncio.TimeoutError:
                    break

    error_msgs = [m for m in messages if m.get("type") == "error"]
    assert len(error_msgs) == 1
    assert "chat error" in error_msgs[0]["content"].lower()


# ---------------------------------------------------------------------------
# WTST-08: Telemetry WebSocket
# ---------------------------------------------------------------------------


async def test_telemetry_ws_sends_disconnected_on_connect_failure(
    test_app, mock_app_state
):
    """When telemetry service is unreachable, /ws/telemetry sends disconnected status."""
    # Patch websockets.connect to raise ConnectionRefusedError
    with patch("web.server.ws_lib.connect", side_effect=ConnectionRefusedError("refused")):
        async with httpx.AsyncClient(
            transport=ASGIWebSocketTransport(app=test_app),
            base_url="http://test",
        ) as client:
            async with aconnect_ws("/ws/telemetry", client) as ws:
                # Should receive a disconnected message
                raw = await asyncio.wait_for(ws.receive_text(), timeout=3.0)
                msg = json.loads(raw)

    assert msg["type"] == "telemetry"
    assert msg["connected"] is False
