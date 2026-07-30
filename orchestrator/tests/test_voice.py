"""Tests for the voice pipeline's backend abstraction.

`voice.py` had no test file, and that is precisely why commit a1b508a was able
to silently revert `VoiceOutput` from the `TTSClient` protocol back to inline
ElevenLabs httpx calls -- undetected for four months across two verified phases.

The regression guards below are deliberately structural: they assert that
`VoiceOutput` holds no credentials, hardcodes no voice settings, and contains no
provider URLs. Those are the exact properties that were lost, so they are the
exact properties worth pinning.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import pytest

from orchestrator.tts.base import TTSClient
from orchestrator.voice import VoiceOutput

VOICE_SOURCE = Path(inspect.getfile(VoiceOutput)).read_text()


class FakeTTSClient:
    """Minimal TTSClient implementation recording what it was asked to say."""

    def __init__(self, audio: bytes = b"\xff\xfb\x90\x00", content_type: str = "audio/mpeg"):
        self._audio = audio
        self._content_type = content_type
        self.calls: list[str] = []
        self.closed = False
        self.raises: Exception | None = None

    @property
    def audio_content_type(self) -> str:
        return self._content_type

    async def synthesize(self, text: str) -> bytes:
        self.calls.append(text)
        if self.raises is not None:
            raise self.raises
        return self._audio

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        yield await self.synthesize(text)

    async def synthesize_ws_stream(self, text_chunks: AsyncIterator[str]) -> AsyncIterator[bytes]:
        async for chunk in text_chunks:
            yield await self.synthesize(chunk)

    async def aclose(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# Regression guards -- these are the properties commit a1b508a destroyed
# ---------------------------------------------------------------------------


class TestNoProviderCouplingRegression:
    """Guard against re-introducing provider specifics into VoiceOutput."""

    def test_constructor_takes_a_tts_client_not_credentials(self) -> None:
        params = list(inspect.signature(VoiceOutput.__init__).parameters)
        assert "tts_client" in params, (
            "VoiceOutput must accept a TTSClient. If this fails, the Phase 02-02 "
            "protocol refactor has been reverted again (see commit a1b508a)."
        )
        for leaked in ("api_key", "voice_id", "model_id"):
            assert leaked not in params, (
                f"VoiceOutput must not accept {leaked!r} -- credentials and voice "
                "selection are the backend's concern, not the player's."
            )

    def test_no_provider_urls_in_source(self) -> None:
        for url in ("api.elevenlabs.io", "api.cartesia.ai", "xi-api-key"):
            assert url not in VOICE_SOURCE, f"provider detail {url!r} leaked back into voice.py"

    def test_no_hardcoded_voice_settings_in_source(self) -> None:
        """Voice settings live in config; duplicating them caused CLI/web drift."""
        for setting in ('"stability"', '"similarity_boost"', '"style"'):
            assert setting not in VOICE_SOURCE, (
                f"hardcoded {setting} found in voice.py -- these belong in Settings, "
                "and duplicating them is what made CLI and web audio diverge."
            )

    def test_fake_client_satisfies_the_protocol(self) -> None:
        assert isinstance(FakeTTSClient(), TTSClient)


# ---------------------------------------------------------------------------
# Delegation behaviour
# ---------------------------------------------------------------------------


class TestSynthesisDelegation:
    async def test_synthesize_delegates_to_client(self) -> None:
        tts = FakeTTSClient()
        out = VoiceOutput(tts_client=tts)
        assert await out._synthesize("Roger.") == b"\xff\xfb\x90\x00"
        assert tts.calls == ["Roger."]

    async def test_synthesis_failure_degrades_to_none(self) -> None:
        """A backend error must not propagate into the conversation loop."""
        tts = FakeTTSClient()
        tts.raises = RuntimeError("backend exploded")
        out = VoiceOutput(tts_client=tts)
        assert await out._synthesize("Roger.") is None

    async def test_speak_skips_empty_text(self) -> None:
        tts = FakeTTSClient()
        out = VoiceOutput(tts_client=tts)
        await out.speak("   ")
        assert tts.calls == []

    async def test_speak_streamed_splits_on_sentence_boundaries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tts = FakeTTSClient()
        out = VoiceOutput(tts_client=tts)
        # Suppress actual audio device work; we only care about synthesis calls.
        monkeypatch.setattr(out, "_play_audio", _noop_play)

        async def chunks() -> AsyncIterator[str]:
            for piece in ("Gear up. ", "Flaps ten. ", "Positive rate"):
                yield piece

        await out.speak_streamed(chunks())
        assert tts.calls == ["Gear up.", "Flaps ten.", "Positive rate"]

    async def test_cancel_stops_further_synthesis(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Barge-in must halt synthesis mid-stream, not just stop playback."""
        tts = FakeTTSClient()
        out = VoiceOutput(tts_client=tts)
        monkeypatch.setattr(out, "_play_audio", _noop_play)

        async def chunks() -> AsyncIterator[str]:
            yield "First sentence. "
            out.cancel()
            yield "Second sentence. "
            yield "Third sentence."

        await out.speak_streamed(chunks())
        assert tts.calls == ["First sentence."]


# ---------------------------------------------------------------------------
# Backend-aware playback -- required for the local-default hybrid
# ---------------------------------------------------------------------------


class TestContentTypeRouting:
    """MP3 backends need ffmpeg; WAV/PCM backends must not spawn a subprocess."""

    async def test_mp3_backend_uses_ffmpeg_decode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out = VoiceOutput(tts_client=FakeTTSClient(content_type="audio/mpeg"))
        decoded: list[str] = []

        async def fake_decode(data: bytes) -> np.ndarray:
            decoded.append("mp3")
            return np.zeros(4, dtype=np.float32)

        monkeypatch.setattr(out, "_decode_mp3", fake_decode)
        monkeypatch.setattr(out, "_play_pcm", lambda samples: None)
        await out._play_audio(b"\xff\xfb\x90\x00")
        assert decoded == ["mp3"]

    async def test_wav_backend_skips_ffmpeg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kokoro emits WAV -- routing it through ffmpeg would be wasteful and wrong."""
        out = VoiceOutput(tts_client=FakeTTSClient(content_type="audio/wav"))

        async def fail_decode(data: bytes) -> np.ndarray:
            raise AssertionError("ffmpeg must not be used for a WAV backend")

        monkeypatch.setattr(out, "_decode_mp3", fail_decode)
        monkeypatch.setattr(out, "_play_pcm", lambda samples: None)
        await out._play_audio(b"RIFF" + b"\x00" * 40 + b"\x01\x00\x02\x00")

    def test_decode_pcm_strips_riff_header(self) -> None:
        payload = b"\x01\x00\x02\x00"
        samples = VoiceOutput._decode_pcm(b"RIFF" + b"\x00" * 40 + payload)
        assert samples is not None
        assert len(samples) == 2

    def test_decode_pcm_handles_raw_pcm(self) -> None:
        samples = VoiceOutput._decode_pcm(b"\x01\x00\x02\x00")
        assert samples is not None
        assert len(samples) == 2

    def test_decode_pcm_tolerates_odd_length(self) -> None:
        """An odd trailing byte would make the int16 view raise."""
        samples = VoiceOutput._decode_pcm(b"\x01\x00\x02")
        assert samples is not None
        assert len(samples) == 1

    def test_decode_pcm_empty_returns_none(self) -> None:
        assert VoiceOutput._decode_pcm(b"RIFF" + b"\x00" * 40) is None


async def _noop_play(audio: bytes) -> None:
    """Stand-in for _play_audio that touches no audio device."""
    return None
