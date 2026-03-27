"""ElevenLabs TTS backend -- cloud-hosted text-to-speech via REST API."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator

import httpx
import websockets

logger = logging.getLogger(__name__)


class ElevenLabsClient:
    """TTS client that calls the ElevenLabs REST API.

    Satisfies the ``TTSClient`` protocol defined in ``base.py``.
    Uses a persistent ``httpx.AsyncClient`` to avoid per-call TCP overhead.
    """

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
        stability: float = 0.75,
        similarity_boost: float = 0.80,
        style: float = 0.15,
    ) -> None:
        self._api_key = api_key
        self._voice_id = voice_id
        self._model_id = model_id
        self._stability = stability
        self._similarity_boost = similarity_boost
        self._style = style
        self._http = httpx.AsyncClient(timeout=30.0)

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
                "stability": self._stability,
                "similarity_boost": self._similarity_boost,
                "style": self._style,
            },
        }

        resp = await self._http.post(url, headers=headers, json=payload)
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
                "stability": self._stability,
                "similarity_boost": self._similarity_boost,
                "style": self._style,
            },
        }

        async with self._http.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                yield chunk

    async def synthesize_ws_stream(
        self,
        text_chunks: AsyncIterator[str],
    ) -> AsyncIterator[bytes]:
        """Stream text chunks to ElevenLabs via WebSocket and yield audio bytes.

        Opens a single WebSocket connection to the ElevenLabs stream-input
        endpoint, concurrently sends text and receives base64-encoded audio.
        """
        ws_url = (
            f"wss://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}"
            f"/stream-input?model_id={self._model_id}&output_format=mp3_44100_128"
        )

        audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        try:
            async with websockets.connect(
                ws_url,
                additional_headers={"xi-api-key": self._api_key},
            ) as ws:
                # Send initialization message with voice settings
                await ws.send(json.dumps({
                    "text": " ",
                    "voice_settings": {
                        "stability": self._stability,
                        "similarity_boost": self._similarity_boost,
                        "style": self._style,
                    },
                }))

                async def _receive_audio() -> None:
                    """Read WS messages, decode base64 audio, enqueue chunks."""
                    try:
                        async for msg in ws:
                            if isinstance(msg, str):
                                data = json.loads(msg)
                                if data.get("isFinal"):
                                    break
                                audio_b64 = data.get("audio")
                                if audio_b64:
                                    audio_bytes = base64.b64decode(audio_b64)
                                    if audio_bytes:
                                        await audio_queue.put(audio_bytes)
                            elif isinstance(msg, bytes):
                                if msg:
                                    await audio_queue.put(msg)
                    except Exception as exc:
                        logger.debug("ElevenLabs WS receive error: %s", exc)
                    finally:
                        await audio_queue.put(None)

                recv_task = asyncio.create_task(_receive_audio())

                try:
                    # Feed text chunks into the WebSocket
                    async for chunk in text_chunks:
                        if chunk:
                            await ws.send(json.dumps({
                                "text": chunk,
                                "try_trigger_generation": True,
                            }))

                    # Send flush signal to get final audio
                    await ws.send(json.dumps({"text": ""}))
                except Exception as exc:
                    logger.debug("ElevenLabs WS send error: %s", exc)

                # Yield audio chunks as they arrive
                while True:
                    audio = await asyncio.wait_for(audio_queue.get(), timeout=30.0)
                    if audio is None:
                        break
                    yield audio

                # Ensure receiver finishes cleanly
                try:
                    await asyncio.wait_for(recv_task, timeout=5.0)
                except (TimeoutError, asyncio.CancelledError):
                    recv_task.cancel()

        except Exception as exc:
            logger.warning("ElevenLabs WebSocket streaming failed: %s", exc)

    async def aclose(self) -> None:
        """Release the persistent HTTP client."""
        await self._http.aclose()
