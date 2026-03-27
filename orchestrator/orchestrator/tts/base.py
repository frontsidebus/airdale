"""Base protocol for the TTS client abstraction layer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class TTSClient(Protocol):
    """Protocol that all TTS backend clients must satisfy.

    Implementations handle synthesis and streaming for a single voice.
    Audio is returned as raw bytes -- the format (MP3, WAV, etc.) is
    backend-specific and communicated via ``audio_content_type``.
    """

    @property
    def audio_content_type(self) -> str:
        """MIME type of the audio produced by this backend (e.g. ``audio/mpeg``, ``audio/wav``)."""
        ...

    async def synthesize(self, text: str) -> bytes:
        """Synthesize *text* into audio and return the complete byte payload."""
        ...

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Synthesize *text* and yield audio chunks as they become available."""
        ...
        # Make the protocol method a valid async iterator stub
        if False:  # pragma: no cover
            yield  # type: ignore[misc]

    async def synthesize_ws_stream(
        self,
        text_chunks: AsyncIterator[str],
    ) -> AsyncIterator[bytes]:
        """Accept streaming text and yield audio chunks via WebSocket (or fallback).

        For backends with native WS streaming (e.g. ElevenLabs), this opens a
        persistent connection and feeds text incrementally.  For backends without
        WS support (e.g. Kokoro), text is buffered to sentence boundaries and
        synthesised via ``synthesize_stream``.
        """
        ...
        if False:  # pragma: no cover
            yield  # type: ignore[misc]

    async def aclose(self) -> None:
        """Release resources held by the client (e.g. persistent HTTP connections)."""
        ...
