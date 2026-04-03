"""Base protocol for STT client abstraction layer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class TranscriptionResult:
    """Result from speech-to-text transcription."""

    text: str
    confidence: float = 1.0  # 0.0 to 1.0
    is_final: bool = True
    speech_final: bool = False  # End-of-turn detected by STT
    duration_secs: float = 0.0


@runtime_checkable
class STTClient(Protocol):
    """Protocol that all STT backend clients must satisfy."""

    async def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """Transcribe a complete audio buffer (batch mode)."""
        ...

    async def stream_transcribe(
        self,
        audio_chunks: AsyncIterator[bytes],
    ) -> AsyncIterator[TranscriptionResult]:
        """Stream audio chunks and yield partial/final transcriptions.

        Yields TranscriptionResult objects as they arrive. Partial results
        have is_final=False. The stream ends when speech_final=True (end
        of utterance detected) or the audio stream ends.
        """
        ...
        if False:  # pragma: no cover
            yield  # type: ignore[misc]

    async def aclose(self) -> None:
        """Release resources."""
        ...
