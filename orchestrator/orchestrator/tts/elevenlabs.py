"""ElevenLabs TTS backend -- cloud-hosted text-to-speech via REST API."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)


class ElevenLabsClient:
    """TTS client that calls the ElevenLabs REST API.

    Satisfies the ``TTSClient`` protocol defined in ``base.py``.
    """

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
    ) -> None:
        self._api_key = api_key
        self._voice_id = voice_id
        self._model_id = model_id

    # -- TTSClient protocol ---------------------------------------------------

    @property
    def audio_content_type(self) -> str:
        return "audio/mpeg"

    async def synthesize(self, text: str) -> bytes:
        """Synthesize *text* via ElevenLabs REST and return MP3 bytes."""
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}/stream"
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": self._model_id,
            "voice_settings": {
                "stability": 0.75,
                "similarity_boost": 0.80,
                "style": 0.15,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            logger.info(
                "ElevenLabs synthesized %d bytes for: %s",
                len(resp.content),
                text[:60],
            )
            return resp.content

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Stream audio from ElevenLabs REST endpoint in chunks."""
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}/stream"
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": self._model_id,
            "voice_settings": {
                "stability": 0.75,
                "similarity_boost": 0.80,
                "style": 0.15,
            },
        }

        async with (
            httpx.AsyncClient(timeout=30.0) as client,
            client.stream("POST", url, headers=headers, json=payload) as resp,
        ):
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                yield chunk
