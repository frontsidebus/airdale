"""WebSocket chat tests for the MERLIN web server.

Covers:
- WTST-01: Chat round-trip (text message -> streamed response -> done)
- WTST-02: Barge-in (second message cancels active response)
- WTST-03: TTS audio chunks streamed alongside text
- AUTH-02: advisory, withheld, blocked and executed are four distinguishable
  outcomes on the wire; a dry run is never reported as a success (RESEARCH B8)

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
            messages = await _recv_all(ws, stop_types={"done", "error"}, min_dones=1, timeout=5.0)

    text_chunks = [
        m["content"] for m in messages if isinstance(m, dict) and m.get("type") == "text"
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

            messages = await _recv_all(ws, stop_types={"done", "error"}, min_dones=1, timeout=5.0)

    types = [m.get("type") for m in messages if isinstance(m, dict)]
    assert "interrupted" in types, f"expected interrupted in {types}"
    assert "done" in types, f"expected done in {types}"
    # Second response should have produced text
    text_chunks = [
        m["content"] for m in messages if isinstance(m, dict) and m.get("type") == "text"
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
            messages = await _recv_all(ws, stop_types={"done", "error"}, min_dones=1, timeout=10.0)

    # Find a tts_audio header followed by a binary frame
    tts_header_indices = [
        i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("type") == "tts_audio"
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


# ---------------------------------------------------------------------------
# AUTH-02 / RESEARCH B8: a restrained command is not a successful one
# ---------------------------------------------------------------------------

_B8_REGRESSION = (
    "REGRESSION (RESEARCH B8, threat T-02-09-01): the authority gate's advisory "
    "and withheld result dicts carry no `error` key by design (plan 02-04), so a "
    '`success = "error" not in tool_result` heuristic renders a command MERLIN '
    "deliberately did not transmit as `{'success': true}`. The pilot is then told "
    "GEAR DOWN for a gear that never moved. Classify on the `advisory` / "
    "`withheld` markers, not on the absence of an error."
)

#: The command-outcome message types the chat socket can emit.
_OUTCOME_TYPES = {"command_status", "command_advisory", "command_withheld"}

# The dict shapes below are the ones plan 02-04 froze in
# orchestrator/orchestrator/tools.py -- copied from the source, not paraphrased.
_ADVISORY_RESULT = {
    "advisory": True,
    "would_execute": "GEAR_DOWN",
    "sim_value": 0,
    "system": "gear",
    "action": "down",
    "command": "GEAR_DOWN",
    "authority_level": "advisory",
    "authority_reason": "config",
    "safety": {"severity": "", "reason": ""},
    "message": "Advisory authority -- I would lower the gear (GEAR_DOWN), nothing was sent.",
}

_WITHHELD_RESULT = {
    "withheld": True,
    "command": "GEAR_UP",
    "sim_value": 0,
    "system": "gear",
    "action": "up",
    "authority_level": "assisted",
    "authority_reason": "config",
    "safety": {"severity": "warning", "reason": "Gear up while on the ground"},
    "message": "Holding GEAR_UP -- Gear up while on the ground.",
}

_BLOCKED_RESULT = {
    "error": "Gear up while on the ground",
    "blocked": True,
    "severity": "blocked",
}

_EXECUTED_RESULT = {
    "success": True,
    "command": "GEAR_DOWN",
    "sim_value": 0,
}


def _chat_emitting(tool_result, *, tool_input=None, tool_name="set_aircraft_control"):
    """Build a fake ``ClaudeClient.chat`` that fires one tool result, then a chunk."""
    payload = tool_input or {"system": "gear", "action": "down"}

    async def fake_chat(text, sim_state=None, on_tool_result=None):
        if on_tool_result is not None:
            on_tool_result(tool_name, payload, tool_result)
        yield "Understood."

    return fake_chat


async def _outcome_messages(test_app, mock_app_state, tool_result, **kwargs):
    """Run one chat turn that produces ``tool_result`` and return its outcome frames."""
    mock_app_state.claude_client.chat = _chat_emitting(tool_result, **kwargs)
    # Text-only round trip: TTS would just add frames to sift through.
    mock_app_state.settings.elevenlabs_api_key = ""
    mock_app_state.cartesia_client = None

    transport = ASGIWebSocketTransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with aconnect_ws("http://test/ws/chat", client) as ws:
            await ws.send_json({"text": "gear down"})
            messages = await _recv_all(ws, stop_types={"done", "error"}, min_dones=1, timeout=5.0)

    return [m for m in messages if isinstance(m, dict) and m.get("type") in _OUTCOME_TYPES]


async def test_advisory_result_is_not_reported_as_a_successful_command(test_app, mock_app_state):
    """The B8 regression, stated as an assertion: a dry run must never read as done."""
    outcomes = await _outcome_messages(test_app, mock_app_state, _ADVISORY_RESULT)

    assert not [m for m in outcomes if m.get("success") is True], _B8_REGRESSION
    assert not [m for m in outcomes if m.get("type") == "command_status"], _B8_REGRESSION


async def test_advisory_result_produces_exactly_one_command_advisory(test_app, mock_app_state):
    """An advisory dry run yields one command_advisory frame and nothing else."""
    outcomes = await _outcome_messages(test_app, mock_app_state, _ADVISORY_RESULT)

    assert len(outcomes) == 1, f"expected one outcome frame, got {outcomes}"
    assert outcomes[0]["type"] == "command_advisory"
    assert "success" not in outcomes[0], _B8_REGRESSION


async def test_advisory_frame_carries_intent_and_authority(test_app, mock_app_state):
    """The browser can label the state without a second /api/status round trip."""
    outcomes = await _outcome_messages(test_app, mock_app_state, _ADVISORY_RESULT)

    frame = outcomes[0]
    assert frame["system"] == "gear"
    assert frame["action"] == "down"
    assert frame["would_execute"] == "GEAR_DOWN"
    assert frame["authority_level"] == "advisory"
    assert frame["authority_reason"] == "config"
    # Describes what MERLIN would do, not what it did.
    assert "not sent" in frame["message"].lower()


async def test_withheld_result_produces_a_command_withheld_frame(test_app, mock_app_state):
    """An assisted withhold is distinguishable from both success and failure."""
    outcomes = await _outcome_messages(test_app, mock_app_state, _WITHHELD_RESULT)

    assert len(outcomes) == 1, f"expected one outcome frame, got {outcomes}"
    frame = outcomes[0]
    assert frame["type"] == "command_withheld"
    assert "success" not in frame, _B8_REGRESSION
    assert frame["authority_level"] == "assisted"
    assert frame["authority_reason"] == "config"
    # Why MERLIN deferred, so the pilot is not left guessing.
    assert frame["safety_reason"] == "Gear up while on the ground"


async def test_advisory_forwards_a_degraded_reason_verbatim(test_app, mock_app_state):
    """`degraded` is one of four reasons and must survive the trip unmapped."""
    degraded = dict(_ADVISORY_RESULT, authority_reason="degraded")

    outcomes = await _outcome_messages(test_app, mock_app_state, degraded)

    assert outcomes[0]["authority_reason"] == "degraded", (
        "authority_reason must be copied through verbatim. Substituting `config` "
        "for anything unexpected would report a failed authority subsystem as a "
        "deliberate configuration (threat T-02-09-07)."
    )


async def test_withheld_forwards_an_override_reason_verbatim(test_app, mock_app_state):
    """A withhold under a pilot-override cooldown keeps its reason."""
    overridden = dict(_WITHHELD_RESULT, authority_reason="override")

    outcomes = await _outcome_messages(test_app, mock_app_state, overridden)

    assert outcomes[0]["authority_reason"] == "override"


async def test_blocked_result_still_reports_a_failed_command_status(test_app, mock_app_state):
    """The pre-plan failure path is unchanged: blocked is a failed command_status."""
    outcomes = await _outcome_messages(
        test_app,
        mock_app_state,
        _BLOCKED_RESULT,
        tool_input={"system": "gear", "action": "up"},
    )

    assert len(outcomes) == 1
    frame = outcomes[0]
    assert frame["type"] == "command_status"
    assert frame["success"] is False
    assert frame["message"] == "GEAR UP failed"


async def test_executed_result_still_reports_a_successful_command_status(test_app, mock_app_state):
    """The pre-plan success path is unchanged: an executed command still succeeds."""
    outcomes = await _outcome_messages(test_app, mock_app_state, _EXECUTED_RESULT)

    assert len(outcomes) == 1
    frame = outcomes[0]
    assert frame["type"] == "command_status"
    assert frame["success"] is True
    assert frame["message"] == "GEAR DOWN"


async def test_non_command_tool_results_are_ignored(test_app, mock_app_state):
    """Only set_aircraft_control produces an outcome frame; other tools do not."""
    outcomes = await _outcome_messages(
        test_app,
        mock_app_state,
        {"metar": "KSFO 251456Z 28012KT 10SM CLR 18/09 A3001"},
        tool_name="get_weather",
    )

    assert outcomes == []
