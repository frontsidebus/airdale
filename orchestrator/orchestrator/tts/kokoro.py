"""Kokoro TTS backend -- local text-to-speech via HTTP API."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)


class KokoroClient:
    """TTS client that calls a local Kokoro TTS HTTP server.

    Satisfies the ``TTSClient`` protocol defined in ``base.py``.
    Uses a persistent ``httpx.AsyncClient`` to avoid per-call TCP overhead.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:9091",
        voice_id: str = "af_heart",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._voice_id = voice_id
        self._http = httpx.AsyncClient(timeout=30.0)

    # -- TTSClient protocol ---------------------------------------------------

    @property
    def audio_content_type(self) -> str:
        return "audio/wav"

    async def synthesize(self, text: str) -> bytes:
        """Synthesize *text* via the local Kokoro server and return WAV bytes."""
        resp = await self._http.post(
            f"{self._base_url}/tts",
            json={"text": text, "voice_id": self._voice_id},
        )
        resp.raise_for_status()
        logger.info(
            "Kokoro synthesized %d bytes for: %s",
            len(resp.content),
            text[:60],
        )
        return resp.content

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Stream audio from the local Kokoro server in chunks."""
        async with self._http.stream(
            "POST",
            f"{self._base_url}/tts",
            json={"text": text, "voice_id": self._voice_id},
        ) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                yield chunk

    async def synthesize_ws_stream(
        self,
        text_chunks: AsyncIterator[str],
    ) -> AsyncIterator[bytes]:
        """Buffer text to sentence boundaries and flush via synthesize_stream.

        Kokoro does not support WebSocket streaming, so this method buffers
        incoming text chunks until a sentence boundary is detected, then
        synthesises each sentence via the REST streaming endpoint.
        """
        buffer = ""
        sentence_endings = ".!?\n"
        async for chunk in text_chunks:
            buffer += chunk
            last_boundary = max(buffer.rfind(ch) for ch in sentence_endings)
            if last_boundary >= 0:
                sentence = buffer[: last_boundary + 1].strip()
                buffer = buffer[last_boundary + 1 :]
                if sentence:
                    async for audio_chunk in self.synthesize_stream(sentence):
                        yield audio_chunk
        # Flush remaining text
        if buffer.strip():
            async for audio_chunk in self.synthesize_stream(buffer.strip()):
                yield audio_chunk

    async def aclose(self) -> None:
        """Release the persistent HTTP client."""
        await self._http.aclose()
