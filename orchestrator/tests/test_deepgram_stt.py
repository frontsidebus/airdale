"""Tests for Deepgram STT client."""

from __future__ import annotations

import httpx
import pytest
import respx

from orchestrator.stt.deepgram import _AVIATION_KEYWORDS, DeepgramSTTClient

# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


class TestDeepgramConstruction:
    def test_default_config(self) -> None:
        client = DeepgramSTTClient(api_key="test-key")
        assert client._model == "nova-3"
        assert client._language == "en"
        assert client._sample_rate == 16000

    def test_custom_config(self) -> None:
        client = DeepgramSTTClient(
            api_key="test-key",
            model="nova-2",
            language="fr",
            sample_rate=48000,
        )
        assert client._model == "nova-2"
        assert client._language == "fr"
        assert client._sample_rate == 48000

    def test_aviation_keywords_populated(self) -> None:
        assert len(_AVIATION_KEYWORDS) > 10
        assert "METAR" in _AVIATION_KEYWORDS
        assert "squawk" in _AVIATION_KEYWORDS
        assert "MERLIN" in _AVIATION_KEYWORDS


# ---------------------------------------------------------------------------
# WebSocket URL building
# ---------------------------------------------------------------------------


class TestWSUrlBuilding:
    def test_url_contains_model(self) -> None:
        client = DeepgramSTTClient(api_key="key", model="nova-3")
        url = client._build_ws_url()
        assert "model=nova-3" in url

    def test_url_contains_sample_rate(self) -> None:
        client = DeepgramSTTClient(api_key="key", sample_rate=16000)
        url = client._build_ws_url()
        assert "sample_rate=16000" in url

    def test_url_has_interim_results(self) -> None:
        client = DeepgramSTTClient(api_key="key")
        url = client._build_ws_url()
        assert "interim_results=true" in url

    def test_url_has_endpointing(self) -> None:
        client = DeepgramSTTClient(api_key="key", endpointing_ms=400)
        url = client._build_ws_url()
        assert "endpointing=400" in url

    def test_url_has_keywords(self) -> None:
        client = DeepgramSTTClient(api_key="key", keywords=["METAR", "ATIS"])
        url = client._build_ws_url()
        assert "keywords=METAR" in url
        assert "keywords=ATIS" in url


# ---------------------------------------------------------------------------
# Batch transcription (REST)
# ---------------------------------------------------------------------------


class TestBatchTranscription:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_transcription(self) -> None:
        respx.post("https://api.deepgram.com/v1/listen").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": {
                        "channels": [
                            {
                                "alternatives": [
                                    {
                                        "transcript": "Contact tower on 121.5",
                                        "confidence": 0.95,
                                    }
                                ]
                            }
                        ]
                    },
                    "metadata": {"duration": 2.5},
                },
            )
        )
        client = DeepgramSTTClient(api_key="test-key")
        result = await client.transcribe(b"fake-audio-data")

        assert result.text == "Contact tower on 121.5"
        assert result.confidence == 0.95
        assert result.is_final is True
        assert result.speech_final is True
        assert result.duration_secs == 2.5

    @pytest.mark.asyncio
    @respx.mock
    async def test_api_error(self) -> None:
        respx.post("https://api.deepgram.com/v1/listen").mock(
            return_value=httpx.Response(401)
        )
        client = DeepgramSTTClient(api_key="bad-key")
        result = await client.transcribe(b"audio")

        assert result.text == ""
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_transcript(self) -> None:
        respx.post("https://api.deepgram.com/v1/listen").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": {"channels": [{"alternatives": [{"transcript": ""}]}]},
                    "metadata": {"duration": 0.5},
                },
            )
        )
        client = DeepgramSTTClient(api_key="test-key")
        result = await client.transcribe(b"silence")
        assert result.text == ""


# ---------------------------------------------------------------------------
# TranscriptionResult
# ---------------------------------------------------------------------------


class TestTranscriptionResult:
    def test_defaults(self) -> None:
        from orchestrator.stt.base import TranscriptionResult

        result = TranscriptionResult(text="hello")
        assert result.confidence == 1.0
        assert result.is_final is True
        assert result.speech_final is False

    def test_partial_result(self) -> None:
        from orchestrator.stt.base import TranscriptionResult

        result = TranscriptionResult(text="hel", is_final=False, confidence=0.7)
        assert result.is_final is False


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Empty / edge-case transcription handling
# ---------------------------------------------------------------------------


class TestEmptyTranscriptionHandling:
    """Verify graceful handling of empty or degenerate STT responses."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_transcript_text_returns_empty_string(self) -> None:
        """Deepgram 200 OK with empty transcript text -> result.text is ''."""
        respx.post("https://api.deepgram.com/v1/listen").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": {
                        "channels": [
                            {
                                "alternatives": [
                                    {"transcript": "", "confidence": 0.0}
                                ]
                            }
                        ]
                    },
                    "metadata": {"duration": 0.3},
                },
            )
        )
        client = DeepgramSTTClient(api_key="test-key")
        result = await client.transcribe(b"silence-audio")

        assert result.text == ""
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    @respx.mock
    async def test_very_short_audio_under_500_bytes(self) -> None:
        """Audio payload < 500 bytes should still be sent and handled."""
        short_audio = b"\x00" * 200  # 200 bytes of silence
        respx.post("https://api.deepgram.com/v1/listen").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": {
                        "channels": [
                            {
                                "alternatives": [
                                    {"transcript": "", "confidence": 0.0}
                                ]
                            }
                        ]
                    },
                    "metadata": {"duration": 0.01},
                },
            )
        )
        client = DeepgramSTTClient(api_key="test-key")
        result = await client.transcribe(short_audio)

        assert result.text == ""
        assert result.is_final is True

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.xfail(
        reason="BUG: transcribe() raises IndexError on empty alternatives list — "
        "needs defensive indexing in deepgram.py:122",
        raises=IndexError,
        strict=True,
    )
    async def test_200_ok_with_empty_alternatives(self) -> None:
        """Deepgram 200 OK with empty alternatives list -> empty text."""
        respx.post("https://api.deepgram.com/v1/listen").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": {
                        "channels": [{"alternatives": []}]
                    },
                    "metadata": {"duration": 0.5},
                },
            )
        )
        client = DeepgramSTTClient(api_key="test-key")
        result = await client.transcribe(b"some-audio")

        assert result.text == ""

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.xfail(
        reason="BUG: transcribe() raises IndexError on empty channels list — "
        "needs defensive indexing in deepgram.py:121",
        raises=IndexError,
        strict=True,
    )
    async def test_200_ok_with_empty_channels(self) -> None:
        """Deepgram 200 OK with empty channels list -> empty text."""
        respx.post("https://api.deepgram.com/v1/listen").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": {"channels": []},
                    "metadata": {"duration": 0.5},
                },
            )
        )
        client = DeepgramSTTClient(api_key="test-key")
        result = await client.transcribe(b"audio-data")

        assert result.text == ""

    @pytest.mark.asyncio
    @respx.mock
    async def test_200_ok_whitespace_only_transcript(self) -> None:
        """Deepgram returning whitespace-only transcript."""
        respx.post("https://api.deepgram.com/v1/listen").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": {
                        "channels": [
                            {
                                "alternatives": [
                                    {"transcript": "   ", "confidence": 0.1}
                                ]
                            }
                        ]
                    },
                    "metadata": {"duration": 0.8},
                },
            )
        )
        client = DeepgramSTTClient(api_key="test-key")
        result = await client.transcribe(b"audio")

        # The raw text comes through as-is; caller is responsible for stripping
        assert result.text.strip() == ""


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    @pytest.mark.asyncio
    async def test_aclose(self) -> None:
        client = DeepgramSTTClient(api_key="key")
        await client.aclose()  # Should not raise
