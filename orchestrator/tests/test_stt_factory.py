"""Tests for the STT factory, Whisper adapter, and aviation vocabulary bias.

The STT side had a protocol and a Deepgram backend but no factory, so Whisper
was reachable only by constructing `WhisperClient` directly. That asymmetry with
`tts/` is what let the two backends drift into different call sites with
different vocabulary handling.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from orchestrator.config import Settings
from orchestrator.stt import (
    SUPPORTED_BACKENDS,
    STTClient,
    aviation_keywords,
    create_stt_client,
)
from orchestrator.stt.base import TranscriptionResult
from orchestrator.stt.whisper_adapter import WhisperSTTAdapter


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "anthropic_api_key": "sk-test",
        "deepgram_api_key": "dg-test",
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestFactory:
    @pytest.mark.parametrize("backend", SUPPORTED_BACKENDS)
    def test_every_supported_backend_builds_and_conforms(self, backend: str) -> None:
        client = create_stt_client(_settings(stt_backend=backend))
        assert isinstance(client, STTClient)

    def test_unknown_backend_raises_with_the_valid_options(self) -> None:
        with pytest.raises(ValueError, match="Unknown STT backend") as exc:
            create_stt_client(_settings(stt_backend="nonexistent"))
        # The error must name the alternatives, or the user has to read source.
        for backend in SUPPORTED_BACKENDS:
            assert backend in str(exc.value)

    def test_backend_selection_is_case_and_space_insensitive(self) -> None:
        client = create_stt_client(_settings(stt_backend="  WHISPER  "))
        assert isinstance(client, WhisperSTTAdapter)

    def test_stt_configured_judges_the_selected_backend_only(self) -> None:
        """Deepgram credentials must not make a Whisper setup look configured."""
        deepgram_only = _settings(stt_backend="whisper", whisper_url="")
        assert deepgram_only.deepgram_api_key
        assert deepgram_only.stt_configured is False

        assert _settings(stt_backend="whisper").stt_configured is True
        assert _settings(stt_backend="deepgram", deepgram_api_key="").stt_configured is False
        assert _settings(stt_backend="nonexistent").stt_configured is False


class TestAviationVocabulary:
    def test_keywords_are_derived_from_the_shared_prompt(self) -> None:
        kws = aviation_keywords()
        # Spot-check the categories that matter for an aviation copilot.
        for term in ("ATIS", "METAR", "squawk", "VREF", "V1", "alpha", "zulu"):
            assert term in kws, f"{term!r} missing from aviation keyword bias"

    def test_keywords_are_deduplicated(self) -> None:
        kws = aviation_keywords()
        assert len(kws) == len(set(kws))

    def test_long_phrases_are_excluded(self) -> None:
        """Deepgram boosting works on tokens and short phrases, not sentences."""
        assert all(len(term.split()) <= 3 for term in aviation_keywords())

    def test_deepgram_backend_receives_the_keywords(self) -> None:
        client = create_stt_client(_settings(stt_backend="deepgram"))
        assert getattr(client, "_keywords", None), "Deepgram built without aviation bias"


class TestWhisperAdapter:
    class _FakeWhisper:
        def __init__(self) -> None:
            self.closed = False
            self.seen: list[bytes] = []

        async def transcribe_with_confidence(self, audio_bytes: bytes):
            from orchestrator.whisper_client import TranscriptionResult as WhisperResult

            self.seen.append(audio_bytes)
            return WhisperResult(
                text="cleared for takeoff runway two seven",
                confidence=0.91,
                language="en",
                duration_secs=2.5,
            )

        async def aclose(self) -> None:
            self.closed = True

    async def test_transcribe_maps_onto_the_protocol_result(self) -> None:
        adapter = WhisperSTTAdapter(self._FakeWhisper())  # type: ignore[arg-type]
        result = await adapter.transcribe(b"audio")
        assert isinstance(result, TranscriptionResult)
        assert result.text == "cleared for takeoff runway two seven"
        assert result.confidence == pytest.approx(0.91)
        assert result.is_final is True
        assert result.speech_final is True
        assert result.duration_secs == pytest.approx(2.5)

    async def test_transcribe_degrades_on_client_error(self) -> None:
        from orchestrator.whisper_client import WhisperClientError

        class Failing:
            async def transcribe_with_confidence(self, audio_bytes: bytes):
                raise WhisperClientError("whisper unreachable")

            async def aclose(self) -> None: ...

        adapter = WhisperSTTAdapter(Failing())  # type: ignore[arg-type]
        result = await adapter.transcribe(b"audio")
        assert result.text == ""
        assert result.confidence == 0.0

    async def test_stream_transcribe_buffers_then_yields_one_final(self) -> None:
        fake = self._FakeWhisper()
        adapter = WhisperSTTAdapter(fake)  # type: ignore[arg-type]

        async def chunks() -> AsyncIterator[bytes]:
            yield b"aa"
            yield b"bb"
            yield b"cc"

        results = [r async for r in adapter.stream_transcribe(chunks())]
        assert len(results) == 1
        assert results[0].speech_final is True
        # The whole stream must reach Whisper as one buffer, not three calls.
        assert fake.seen == [b"aabbcc"]

    async def test_stream_transcribe_on_empty_stream_yields_nothing(self) -> None:
        fake = self._FakeWhisper()
        adapter = WhisperSTTAdapter(fake)  # type: ignore[arg-type]

        async def empty() -> AsyncIterator[bytes]:
            return
            yield b""  # pragma: no cover

        assert [r async for r in adapter.stream_transcribe(empty())] == []
        assert fake.seen == []

    async def test_adapter_reports_no_streaming_support(self) -> None:
        """Whisper is batch-only; callers routing on this must see the truth."""
        adapter = WhisperSTTAdapter(self._FakeWhisper())  # type: ignore[arg-type]
        assert adapter.supports_streaming is False

    async def test_aclose_delegates(self) -> None:
        fake = self._FakeWhisper()
        adapter = WhisperSTTAdapter(fake)  # type: ignore[arg-type]
        await adapter.aclose()
        assert fake.closed is True
