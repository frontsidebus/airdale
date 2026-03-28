"""Unit tests for web server helper functions.

Covers:
- _split_at_sentence: sentence boundary detection for TTS chunking
- _transcribe_with_confidence: Whisper transcription wrapper
- _send_tts_chunk_rest: REST-based TTS fallback
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# _split_at_sentence tests
# ---------------------------------------------------------------------------


def test_split_at_sentence_period_at_end():
    """Complete sentence ending with period is split correctly."""
    import web.server as srv

    sent, remaining = srv._split_at_sentence("Roger that Captain.")
    assert sent == "Roger that Captain."
    assert remaining == ""


def test_split_at_sentence_period_mid_text():
    """Text with sentence boundary mid-buffer splits at the period."""
    import web.server as srv

    sent, remaining = srv._split_at_sentence("Roger that. Climbing now.")
    assert sent == "Roger that. Climbing now."
    assert remaining == ""


def test_split_at_sentence_period_with_trailing():
    """Splits at last sentence boundary, keeps remainder."""
    import web.server as srv

    sent, remaining = srv._split_at_sentence("Roger that. Climbing to")
    assert sent == "Roger that."
    assert remaining == "Climbing to"


def test_split_at_sentence_no_boundary():
    """Without punctuation, returns empty sent and full text as remaining."""
    import web.server as srv

    sent, remaining = srv._split_at_sentence("climbing to altitude")
    assert sent == ""
    assert remaining == "climbing to altitude"


def test_split_at_sentence_question_mark():
    """Question mark is a valid sentence boundary."""
    import web.server as srv

    sent, remaining = srv._split_at_sentence("Say again? I didn't")
    assert sent == "Say again?"
    assert remaining == "I didn't"


def test_split_at_sentence_exclamation():
    """Exclamation mark is a valid sentence boundary."""
    import web.server as srv

    sent, remaining = srv._split_at_sentence("Mayday! We have")
    assert sent == "Mayday!"
    assert remaining == "We have"


def test_split_at_sentence_comma_fallback_long_buffer():
    """For buffers >50 chars with no sentence end, falls back to comma."""
    import web.server as srv

    long_text = "A" * 30 + ", " + "B" * 25 + " still going"
    sent, remaining = srv._split_at_sentence(long_text)
    # Should split at the comma since buffer > 50 chars
    assert sent.endswith(",")
    assert remaining


def test_split_at_sentence_force_split_very_long():
    """Very long buffers (>200 chars) with no punctuation force-split at space."""
    import web.server as srv

    words = " ".join(["word"] * 60)  # ~300 chars
    sent, remaining = srv._split_at_sentence(words)
    assert sent  # Should have content
    assert remaining  # Should have remaining


def test_split_at_sentence_empty_string():
    """Empty string returns no boundary."""
    import web.server as srv

    sent, remaining = srv._split_at_sentence("")
    assert sent == ""
    assert remaining == ""


# ---------------------------------------------------------------------------
# _transcribe_with_confidence tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeTranscriptionResult:
    """Minimal stand-in for orchestrator.whisper_client.TranscriptionResult."""

    text: str
    confidence: float
    language: str = "en"
    duration: float = 1.0


async def test_transcribe_with_confidence_success(mock_app_state):
    """Successful transcription returns (text, confidence) tuple."""
    import web.server as srv

    mock_app_state.whisper_client.transcribe_with_confidence.return_value = (
        _FakeTranscriptionResult(text="check altimeter", confidence=0.95)
    )

    text, confidence = await srv._transcribe_with_confidence(
        b"audio-bytes", state=mock_app_state
    )

    assert text == "check altimeter"
    assert confidence == 0.95


async def test_transcribe_with_confidence_no_client(mock_app_state):
    """When whisper_client is None, returns empty text and 0.0 confidence."""
    import web.server as srv

    mock_app_state.whisper_client = None

    text, confidence = await srv._transcribe_with_confidence(
        b"audio-bytes", state=mock_app_state
    )

    assert text == ""
    assert confidence == 0.0


async def test_transcribe_with_confidence_exception(mock_app_state):
    """When whisper raises, returns empty text and 0.0 confidence."""
    import web.server as srv

    mock_app_state.whisper_client.transcribe_with_confidence.side_effect = Exception(
        "connection refused"
    )

    text, confidence = await srv._transcribe_with_confidence(
        b"audio-bytes", state=mock_app_state
    )

    assert text == ""
    assert confidence == 0.0


# ---------------------------------------------------------------------------
# _send_tts_chunk_rest tests
# ---------------------------------------------------------------------------


async def test_send_tts_chunk_rest_cache_hit(mock_app_state):
    """When text is in TTS cache, sends cached audio via WebSocket."""
    import web.server as srv

    fake_mp3 = b"\xff\xfb\x90\x00" * 10
    mock_app_state.tts_cache["Roger."] = fake_mp3

    mock_ws = AsyncMock()

    await srv._send_tts_chunk_rest(mock_ws, "Roger.", mock_app_state)

    mock_ws.send_json.assert_called_once()
    call_args = mock_ws.send_json.call_args[0][0]
    assert call_args["type"] == "tts_audio"
    assert call_args["size"] == len(fake_mp3)
    mock_ws.send_bytes.assert_called_once_with(fake_mp3)


async def test_send_tts_chunk_rest_calls_elevenlabs(mock_app_state):
    """When text is not cached, calls ElevenLabs REST API."""
    import web.server as srv

    fake_audio = b"fake-mp3"
    mock_response = MagicMock()
    mock_response.content = fake_audio
    mock_response.raise_for_status = MagicMock()
    mock_app_state.tts_client.post = AsyncMock(return_value=mock_response)

    mock_ws = AsyncMock()

    await srv._send_tts_chunk_rest(mock_ws, "Climb and maintain.", mock_app_state)

    mock_app_state.tts_client.post.assert_called_once()
    mock_ws.send_bytes.assert_called_once_with(fake_audio)


async def test_send_tts_chunk_rest_empty_text(mock_app_state):
    """Empty text after preprocessing is a no-op."""
    import web.server as srv

    mock_ws = AsyncMock()

    # preprocess_for_tts("") should return empty, so nothing happens
    await srv._send_tts_chunk_rest(mock_ws, "", mock_app_state)

    mock_ws.send_json.assert_not_called()
    mock_ws.send_bytes.assert_not_called()


async def test_send_tts_chunk_rest_no_client(mock_app_state):
    """When tts_client is None, does nothing (no crash)."""
    import web.server as srv

    mock_app_state.tts_client = None
    mock_app_state.tts_cache.clear()

    mock_ws = AsyncMock()

    await srv._send_tts_chunk_rest(mock_ws, "Some text here.", mock_app_state)

    mock_ws.send_bytes.assert_not_called()


async def test_send_tts_chunk_rest_api_error(mock_app_state):
    """When ElevenLabs API raises, logs warning but doesn't crash."""
    import httpx

    import web.server as srv

    mock_app_state.tts_client.post = AsyncMock(
        side_effect=httpx.HTTPError("Connection refused")
    )

    mock_ws = AsyncMock()

    # Should not raise
    await srv._send_tts_chunk_rest(mock_ws, "Test phrase here.", mock_app_state)

    mock_ws.send_bytes.assert_not_called()
