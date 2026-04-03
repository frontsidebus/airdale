"""Tests for Cartesia Sonic-3 TTS client."""

from __future__ import annotations

import httpx
import pytest
import respx

from orchestrator.tts.cartesia import CartesiaClient

# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


class TestCartesiaConstruction:
    def test_default_config(self) -> None:
        client = CartesiaClient(api_key="key", voice_id="vid")
        assert client._model_id == "sonic-2"
        assert client._sample_rate == 24000
        assert client._output_format == "pcm_s16le"
        assert client._language == "en"

    def test_audio_content_type_pcm(self) -> None:
        client = CartesiaClient(api_key="k", voice_id="v", output_format="pcm_s16le")
        assert client.audio_content_type == "audio/pcm"

    def test_audio_content_type_mp3(self) -> None:
        client = CartesiaClient(api_key="k", voice_id="v", output_format="mp3")
        assert client.audio_content_type == "audio/mpeg"


# ---------------------------------------------------------------------------
# REST synthesis
# ---------------------------------------------------------------------------


class TestCartesiaSynthesize:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_synthesis(self) -> None:
        respx.post("https://api.cartesia.ai/tts/bytes").mock(
            return_value=httpx.Response(200, content=b"\x00\x01\x02\x03")
        )
        client = CartesiaClient(api_key="test-key", voice_id="test-voice")
        audio = await client.synthesize("Hello Captain")

        assert len(audio) == 4
        assert audio == b"\x00\x01\x02\x03"

    @pytest.mark.asyncio
    @respx.mock
    async def test_api_error_returns_empty(self) -> None:
        respx.post("https://api.cartesia.ai/tts/bytes").mock(
            return_value=httpx.Response(500)
        )
        client = CartesiaClient(api_key="key", voice_id="voice")
        audio = await client.synthesize("test")
        assert audio == b""


# ---------------------------------------------------------------------------
# Emotion control
# ---------------------------------------------------------------------------


class TestEmotionControl:
    def test_set_emotion(self) -> None:
        client = CartesiaClient(api_key="k", voice_id="v")
        assert client._emotion is None
        client.set_emotion("urgent")
        assert client._emotion == "urgent"

    def test_clear_emotion(self) -> None:
        client = CartesiaClient(api_key="k", voice_id="v", emotion="calm")
        client.set_emotion(None)
        assert client._emotion is None


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    @pytest.mark.asyncio
    async def test_aclose(self) -> None:
        client = CartesiaClient(api_key="key", voice_id="voice")
        await client.aclose()  # Should not raise
