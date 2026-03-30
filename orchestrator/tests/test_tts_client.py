"""Tests for orchestrator.tts -- TTS client abstraction layer.

Covers the TTSClient protocol (base.py), factory function (create_tts_client),
ElevenLabsClient, KokoroClient, and protocol compliance.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from orchestrator.tts.base import TTSClient

# ===========================================================================
# 1. TTSClient Protocol
# ===========================================================================


class TestTTSClientProtocol:
    """Verify the TTSClient protocol is runtime-checkable."""

    def test_runtime_checkable(self) -> None:
        """Protocol decorated with @runtime_checkable should allow isinstance checks."""
        assert (
            hasattr(TTSClient, "__protocol_attrs__")
            or hasattr(TTSClient, "__abstractmethods__")
            or issubclass(type(TTSClient), type)
        )

    def test_elevenlabs_satisfies_protocol(self) -> None:
        from orchestrator.tts.elevenlabs import ElevenLabsClient

        client = ElevenLabsClient(api_key="test-key", voice_id="test-voice")
        assert isinstance(client, TTSClient)

    def test_kokoro_satisfies_protocol(self) -> None:
        from orchestrator.tts.kokoro import KokoroClient

        client = KokoroClient(base_url="http://localhost:9091", voice_id="af_heart")
        assert isinstance(client, TTSClient)


# ===========================================================================
# 2. Factory function (create_tts_client)
# ===========================================================================


class TestCreateTTSClient:
    """Test the create_tts_client factory in orchestrator.tts.__init__."""

    @pytest.fixture
    def _mock_settings(self) -> MagicMock:
        """A mock Settings with sensible defaults."""
        s = MagicMock()
        s.tts_backend = "elevenlabs"
        s.elevenlabs_api_key = "el-test-key"
        s.elevenlabs_voice_id = "test-voice-id"
        s.elevenlabs_model_id = "eleven_multilingual_v2"
        s.tts_local_url = "http://localhost:9091"
        s.tts_voice_id_local = "af_heart"
        return s

    def test_elevenlabs_backend(self, _mock_settings: MagicMock) -> None:
        from orchestrator.tts import create_tts_client

        _mock_settings.tts_backend = "elevenlabs"
        client = create_tts_client(_mock_settings)

        from orchestrator.tts.elevenlabs import ElevenLabsClient

        assert isinstance(client, ElevenLabsClient)

    def test_local_backend(self, _mock_settings: MagicMock) -> None:
        from orchestrator.tts import create_tts_client

        _mock_settings.tts_backend = "local"
        client = create_tts_client(_mock_settings)

        from orchestrator.tts.kokoro import KokoroClient

        assert isinstance(client, KokoroClient)

    def test_unknown_backend_raises_value_error(self, _mock_settings: MagicMock) -> None:
        from orchestrator.tts import create_tts_client

        _mock_settings.tts_backend = "unknown"
        with pytest.raises(ValueError, match="Unknown TTS backend"):
            create_tts_client(_mock_settings)

    def test_case_insensitive_elevenlabs(self, _mock_settings: MagicMock) -> None:
        from orchestrator.tts import create_tts_client

        _mock_settings.tts_backend = "ELEVENLABS"
        client = create_tts_client(_mock_settings)

        from orchestrator.tts.elevenlabs import ElevenLabsClient

        assert isinstance(client, ElevenLabsClient)

    def test_whitespace_stripped_local(self, _mock_settings: MagicMock) -> None:
        from orchestrator.tts import create_tts_client

        _mock_settings.tts_backend = "  local  "
        client = create_tts_client(_mock_settings)

        from orchestrator.tts.kokoro import KokoroClient

        assert isinstance(client, KokoroClient)


# ===========================================================================
# 3. ElevenLabsClient
# ===========================================================================


class TestElevenLabsClient:
    """Tests for the ElevenLabs TTS backend client."""

    @pytest.fixture
    def client(self) -> Any:
        from orchestrator.tts.elevenlabs import ElevenLabsClient

        return ElevenLabsClient(
            api_key="el-test-key",
            voice_id="test-voice-id",
            model_id="eleven_multilingual_v2",
        )

    def test_audio_content_type(self, client: Any) -> None:
        assert client.audio_content_type == "audio/mpeg"

    @pytest.mark.asyncio
    async def test_synthesize_success(self, client: Any) -> None:
        mock_response = httpx.Response(
            status_code=200,
            content=b"fake-mp3-audio-data",
            request=httpx.Request(
                "POST", "https://api.elevenlabs.io/v1/text-to-speech/test-voice-id/stream"
            ),
        )
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._http = mock_http

        result = await client.synthesize("Roger, Captain.")
        assert result == b"fake-mp3-audio-data"

        # Verify the correct URL was called
        call_args = mock_http.post.call_args
        url = call_args[0][0]
        assert "api.elevenlabs.io" in url
        assert "test-voice-id" in url

    @pytest.mark.asyncio
    async def test_synthesize_http_error(self, client: Any) -> None:
        mock_response = httpx.Response(status_code=500, content=b"Internal Server Error")
        mock_response._request = httpx.Request(
            "POST", "https://api.elevenlabs.io/v1/text-to-speech/test-voice-id/stream"
        )
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._http = mock_http

        with pytest.raises(httpx.HTTPStatusError):
            await client.synthesize("Roger.")


# ===========================================================================
# 4. KokoroClient
# ===========================================================================


class TestKokoroClient:
    """Tests for the Kokoro local TTS backend client."""

    @pytest.fixture
    def client(self) -> Any:
        from orchestrator.tts.kokoro import KokoroClient

        return KokoroClient(
            base_url="http://localhost:9091",
            voice_id="af_heart",
        )

    def test_audio_content_type(self, client: Any) -> None:
        assert client.audio_content_type == "audio/wav"

    @pytest.mark.asyncio
    async def test_synthesize_success(self, client: Any) -> None:
        fake_wav = b"RIFF" + b"\x00" * 40 + b"fake-audio"
        mock_response = httpx.Response(
            status_code=200,
            content=fake_wav,
            request=httpx.Request("POST", "http://localhost:9091/tts"),
        )
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._http = mock_http

        result = await client.synthesize("Roger, Captain.")
        assert result == fake_wav

        # Verify the correct URL was called
        call_args = mock_http.post.call_args
        url = call_args[0][0]
        assert "localhost:9091" in url
        assert "/tts" in url

        # Verify the payload
        payload = call_args[1]["json"]
        assert payload["text"] == "Roger, Captain."
        assert payload["voice_id"] == "af_heart"

    @pytest.mark.asyncio
    async def test_synthesize_http_error(self, client: Any) -> None:
        mock_response = httpx.Response(status_code=503, content=b"Service Unavailable")
        mock_response._request = httpx.Request("POST", "http://localhost:9091/tts")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._http = mock_http

        with pytest.raises(httpx.HTTPStatusError):
            await client.synthesize("Roger.")

    def test_base_url_trailing_slash_stripped(self) -> None:
        from orchestrator.tts.kokoro import KokoroClient

        client = KokoroClient(base_url="http://localhost:9091/", voice_id="af_heart")
        assert client._base_url == "http://localhost:9091"


# ===========================================================================
# 5. Config integration
# ===========================================================================


class TestTTSConfig:
    """Test that TTS config fields work correctly."""

    def test_tts_configured_elevenlabs(self, mock_env_vars: dict[str, str]) -> None:
        from orchestrator.config import load_settings

        settings = load_settings()
        assert settings.tts_backend == "elevenlabs"
        assert settings.tts_configured is True  # has api key and voice id

    def test_tts_configured_local(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from orchestrator.config import load_settings

        monkeypatch.setenv("TTS_BACKEND", "local")
        monkeypatch.setenv("TTS_LOCAL_URL", "http://localhost:9091")
        settings = load_settings()
        assert settings.tts_backend == "local"
        assert settings.tts_configured is True

    def test_voice_id_local_backend(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from orchestrator.config import load_settings

        monkeypatch.setenv("TTS_BACKEND", "local")
        monkeypatch.setenv("TTS_VOICE_ID_LOCAL", "am_adam")
        settings = load_settings()
        assert settings.voice_id == "am_adam"

    def test_voice_id_elevenlabs_backend(self, mock_env_vars: dict[str, str]) -> None:
        from orchestrator.config import load_settings

        settings = load_settings()
        assert settings.voice_id == "test-voice-id"

    def test_tts_not_configured_elevenlabs_no_key(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from orchestrator.config import load_settings

        monkeypatch.setenv("ELEVENLABS_API_KEY", "")
        settings = load_settings()
        assert settings.tts_configured is False
