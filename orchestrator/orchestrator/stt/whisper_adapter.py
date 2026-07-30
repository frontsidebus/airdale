"""Adapter making the batch ``WhisperClient`` satisfy the ``STTClient`` protocol.

``WhisperClient`` predates the STT abstraction and has its own result type and
method signatures (``transcribe`` returns ``str``; ``transcribe_with_confidence``
returns a Whisper-specific dataclass). Rather than change that class -- it is
used directly elsewhere and has 35 tests pinned to its current API -- this
adapter translates it onto the protocol so Whisper and Deepgram are peers behind
``create_stt_client``.

Whisper is batch-only. ``stream_transcribe`` therefore accumulates the whole
audio stream and yields a single final result, which is correct but forfeits the
partial-hypothesis latency advantage a streaming backend gives you.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from ..whisper_client import WhisperClient, WhisperClientError
from .base import TranscriptionResult

logger = logging.getLogger(__name__)


class WhisperSTTAdapter:
    """Wrap a :class:`WhisperClient` behind the ``STTClient`` protocol."""

    def __init__(self, client: WhisperClient) -> None:
        self._client = client

    @property
    def supports_streaming(self) -> bool:
        """False -- Whisper transcribes complete buffers, not incremental audio."""
        return False

    async def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """Transcribe a complete buffer, mapping onto the protocol result type."""
        try:
            result = await self._client.transcribe_with_confidence(audio_bytes)
        except WhisperClientError as exc:
            logger.warning("Whisper transcription failed: %s", exc)
            return TranscriptionResult(text="", confidence=0.0)
        return TranscriptionResult(
            text=result.text,
            confidence=result.confidence,
            is_final=True,
            speech_final=True,
            duration_secs=result.duration_secs,
        )

    async def stream_transcribe(
        self,
        audio_chunks: AsyncIterator[bytes],
    ) -> AsyncIterator[TranscriptionResult]:
        """Buffer the stream, then yield one final result.

        Emits nothing until the input stream is exhausted -- there are no partial
        hypotheses to report. An empty stream yields nothing at all.
        """
        buffered = bytearray()
        async for chunk in audio_chunks:
            buffered.extend(chunk)
        if not buffered:
            return
        yield await self.transcribe(bytes(buffered))

    async def aclose(self) -> None:
        """Close the wrapped client's persistent HTTP connection."""
        await self._client.aclose()
