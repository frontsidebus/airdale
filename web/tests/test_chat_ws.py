"""WebSocket chat tests for the MERLIN web server.

Covers:
- WTST-01: Chat round-trip (text message -> streamed response -> done)
- WTST-02: Barge-in (second message cancels active response)
- WTST-03: TTS audio chunks streamed alongside text

Uses ``httpx-ws`` (``aconnect_ws``) over an ASGI transport so the tests
run entirely in-process without a real uvicorn server.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _collect_until(ws, stop_types, timeout=5.0, max_messages=100):
    """Receive JSON messages until one of ``stop_types`` is seen.

    Binary frames (tts_audio payloads) are stored as ``{"_binary": bytes}``
    entries so tests can assert both the JSON header and the following
    binary frame in order.
    """
    messages: list[dict] = []
    for _ in range(max_messages):
        msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
        if isinstance(msg, bytes):
            messages.append({"_binary": msg})
            continue
        # httpx-ws TextMessage -> .data, or already a dict/json
        import json as _json

        if hasattr(msg, "data"):
            data = _json.loads(msg.data)
        elif isinstance(msg, (bytes, bytearray)):
            messages.append({"_binary": bytes(msg)})
            continue
        elif isinstance(msg, str):
            data = _json.loads(msg)
        else:
            data = msg
        messages.append(data)
        if isinstance(data, dict) and data.get("type") in stop_types:
            break
    return messages


async def _recv_all(ws, *, stop_types, min_dones=1, timeout=5.0, max_messages=200):
    """Receive both text (JSON) and binary frames until ``min_dones`` stop events seen.

    Uses ``ws.receive_json`` for text and ``ws.receive_bytes`` when a
    ``tts_audio`` header arrives. Returns a mixed list of dicts and bytes.
    """
    import json as _json

    out: list = []
    dones = 0
    for _ in range(max_messages):
        # We don't know if next frame is text or binary; use the low level
        # receive() and dispatch.
        try:
            raw = await asyncio.wait_for(ws.receive(), timeout=timeout)
        except asyncio.TimeoutError:
            break
        # httpx-ws may surface TextMessage/BytesMessage (wsproto) or
        # already-unpacked str/bytes depending on version.
        data_obj = None
        binary = None
        if hasattr(raw, "data"):
            payload = raw.data
            if isinstance(payload, (bytes, bytearray)):
                binary = bytes(payload)
            else:
                data_obj = _json.loads(payload)
        elif isinstance(raw, (bytes, bytearray)):
            binary = bytes(raw)
        elif isinstance(raw, str):
            data_obj = _json.loads(raw)
        elif isinstance(raw, dict):
            data_obj = raw

        if binary is not None:
            out.append(binary)
            continue
        out.append(data_obj)
        if isinstance(data_obj, dict) and data_obj.get("type") in stop_types:
            dones += 1
            if dones >= min_dones:
                break
    return out


# ---------------------------------------------------------------------------
# WTST-01: Chat round-trip
# ---------------------------------------------------------------------------


async def test_chat_text_round_trip(test_app, mock_app_state):
    """Client sends text, receives streamed chunks and a final done frame."""

    async def fake_chat(text, sim_state=None, on_tool_result=None):
        yield "Roger"
        yield " that."

    mock_app_state.claude_client.chat = fake_chat
    # Disable TTS for a clean text-only round-trip
    mock_app_state.settings.elevenlabs_api_key = ""
    mock_app_state.cartesia_client = None

    transport = ASGIWebSocketTransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with aconnect_ws("http://test/ws/chat", client) as ws:
            await ws.send_json({"text": "Hello MERLIN"})
            messages = await _recv_all(
                ws, stop_types={"done", "error"}, min_dones=1, timeout=5.0
            )

    text_chunks = [
        m["content"]
        for m in messages
        if isinstance(m, dict) and m.get("type") == "text"
    ]
    assert "".join(text_chunks) == "Roger that."
    assert any(isinstance(m, dict) and m.get("type") == "done" for m in messages)


async def test_chat_error_on_empty_text(test_app, mock_app_state):
    """Empty text payload should produce an error message."""

    async def fake_chat(text, sim_state=None, on_tool_result=None):
        yield "should not stream"

    mock_app_state.claude_client.chat = fake_chat
    mock_app_state.settings.elevenlabs_api_key = ""
    mock_app_state.cartesia_client = None

    transport = ASGIWebSocketTransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with aconnect_ws("http://test/ws/chat", client) as ws:
            await ws.send_json({"text": ""})
            msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

    assert msg["type"] == "error"
    assert "no text" in msg["content"].lower()


# ---------------------------------------------------------------------------
# WTST-02: Barge-in cancels active response
# ---------------------------------------------------------------------------


async def test_barge_in_cancels_active_response(test_app, mock_app_state):
    """A second send during an in-progress response should cancel the first."""

    call_count = {"n": 0}

    async def slow_chat(text, sim_state=None, on_tool_result=None):
        call_count["n"] += 1
        # First call is slow so the test can barge in; second call is fast.
        if call_count["n"] == 1:
            for chunk in ["Standby", " while", " I", " check", " that", "."]:
                yield chunk
                await asyncio.sleep(0.05)
        else:
            yield "Second"
            yield " response."

    mock_app_state.claude_client.chat = slow_chat
    mock_app_state.settings.elevenlabs_api_key = ""
    mock_app_state.cartesia_client = None

    transport = ASGIWebSocketTransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with aconnect_ws("http://test/ws/chat", client) as ws:
            await ws.send_json({"text": "First question"})
            # Wait for at least one text chunk from the first response
            first_chunk = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
            assert first_chunk.get("type") in ("text", "interrupted")
            # Barge in immediately with a second message
            await ws.send_json({"text": "Never mind, second question"})

            messages = await _recv_all(
                ws, stop_types={"done", "error"}, min_dones=1, timeout=5.0
            )

    types = [m.get("type") for m in messages if isinstance(m, dict)]
    assert "interrupted" in types, f"expected interrupted in {types}"
    assert "done" in types, f"expected done in {types}"
    # Second response should have produced text
    text_chunks = [
        m["content"]
        for m in messages
        if isinstance(m, dict) and m.get("type") == "text"
    ]
    assert any("Second" in c or "response" in c for c in text_chunks)


# ---------------------------------------------------------------------------
# WTST-03: TTS audio streaming
# ---------------------------------------------------------------------------


async def test_chat_with_tts_streaming(test_app, mock_app_state):
    """When TTS is enabled, response includes tts_audio JSON + binary frames."""

    async def fake_chat(text, sim_state=None, on_tool_result=None):
        yield "Roger that."

    mock_app_state.claude_client.chat = fake_chat

    # Enable ElevenLabs REST TTS path (_tts_elevenlabs_stream)
    mock_app_state.settings.elevenlabs_api_key = "test-key"
    mock_app_state.settings.voice_id = "test-voice"
    mock_app_state.settings.elevenlabs_voice_id = "test-voice"
    mock_app_state.settings.elevenlabs_model_id = "eleven_multilingual_v2"
    mock_app_state.settings.tts_stability = 0.75
    mock_app_state.settings.tts_similarity_boost = 0.80
    mock_app_state.settings.tts_style = 0.15
    mock_app_state.cartesia_client = None
    # Ensure cache misses hit the mocked HTTP client
    mock_app_state.tts_cache = {}

    fake_audio = b"fake-mp3-audio-bytes"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = fake_audio
    mock_response.raise_for_status = MagicMock()
    mock_app_state.tts_client.post = AsyncMock(return_value=mock_response)

    transport = ASGIWebSocketTransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with aconnect_ws("http://test/ws/chat", client) as ws:
            await ws.send_json({"text": "Say hi"})
            messages = await _recv_all(
                ws, stop_types={"done", "error"}, min_dones=1, timeout=10.0
            )

    # Find a tts_audio header followed by a binary frame
    tts_header_indices = [
        i
        for i, m in enumerate(messages)
        if isinstance(m, dict) and m.get("type") == "tts_audio"
    ]
    assert tts_header_indices, (
        f"expected at least one tts_audio header in {[type(m).__name__ for m in messages]}"
    )

    header_idx = tts_header_indices[0]
    header = messages[header_idx]
    assert header["size"] == len(fake_audio)
    # Next frame should be the binary audio
    assert header_idx + 1 < len(messages), "missing binary frame after tts_audio header"
    binary = messages[header_idx + 1]
    assert isinstance(binary, (bytes, bytearray))
    assert bytes(binary) == fake_audio

    # And the response ultimately completes
    assert any(isinstance(m, dict) and m.get("type") == "done" for m in messages)
    mock_app_state.tts_client.post.assert_called()
