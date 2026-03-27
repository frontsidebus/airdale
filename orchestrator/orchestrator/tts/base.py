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
