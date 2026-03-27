"""Kokoro TTS backend -- local text-to-speech via HTTP API."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)


class KokoroClient:
    """TTS client that calls a local Kokoro TTS HTTP server.

    Satisfies the ``TTSClient`` protocol defined in ``base.py``.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:9091",
        voice_id: str = "af_heart",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._voice_id = voice_id

    # -- TTSClient protocol ---------------------------------------------------

    @property
    def audio_content_type(self) -> str:
        return "audio/wav"

    async def synthesize(self, text: str) -> bytes:
        """Synthesize *text* via the local Kokoro server and return WAV bytes."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
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
        async with (
            httpx.AsyncClient(timeout=30.0) as client,
            client.stream(
                "POST",
                f"{self._base_url}/tts",
                json={"text": text, "voice_id": self._voice_id},
            ) as resp,
        ):
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                yield chunk
