"""Deepgram Nova-3 streaming STT client.

Replaces batch-mode Whisper with sub-300ms streaming transcription.
Uses WebSocket for persistent connection with partial results while
the user is still speaking.

Supports:
- Streaming audio → streaming partial transcripts
- End-of-utterance detection (endpointing / speech_final)
- Aviation keyword prompting for domain vocabulary
- Batch transcription fallback via REST API
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import TranscriptionResult

logger = logging.getLogger(__name__)

# Aviation keywords for Deepgram's keyword boosting
_AVIATION_KEYWORDS = [
    "ATIS", "METAR", "TAF", "ILS", "VOR", "NDB", "DME", "GPS",
    "RNAV", "SID", "STAR", "squawk", "altimeter", "QNH",
    "roger", "wilco", "affirmative", "mayday", "pan-pan",
    "heading", "altitude", "airspeed", "vertical speed",
    "flaps", "gear", "trim", "throttle", "mixture",
    "Cessna", "Boeing", "Airbus", "Piper",
    "MERLIN", "Captain", "go-around", "missed approach",
    "V1", "VR", "V2", "rotate", "positive rate",
]


class DeepgramSTTClient:
    """Deepgram Nova-3 speech-to-text client.

    Satisfies the STTClient protocol. Provides both streaming WebSocket
    and batch REST transcription modes.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "nova-3",
        language: str = "en",
        sample_rate: int = 16000,
        encoding: str = "linear16",
        channels: int = 1,
        enable_smart_format: bool = True,
        endpointing_ms: int = 300,
        utterance_end_ms: int = 1000,
        keywords: list[str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._language = language
        self._sample_rate = sample_rate
        self._encoding = encoding
        self._channels = channels
        self._smart_format = enable_smart_format
        self._endpointing_ms = endpointing_ms
        self._utterance_end_ms = utterance_end_ms
        self._keywords = keywords or _AVIATION_KEYWORDS
        self._http = httpx.AsyncClient(timeout=30.0)

    def _build_ws_url(self) -> str:
        """Build the Deepgram WebSocket streaming URL with parameters."""
        params = [
            f"model={self._model}",
            f"language={self._language}",
            f"sample_rate={self._sample_rate}",
            f"encoding={self._encoding}",
            f"channels={self._channels}",
            f"smart_format={str(self._smart_format).lower()}",
            f"endpointing={self._endpointing_ms}",
            f"utterance_end_ms={self._utterance_end_ms}",
            "interim_results=true",
            "punctuate=true",
            "vad_events=true",
        ]
        # Add keyword boosting
        for kw in self._keywords[:50]:  # Deepgram limits keywords
            params.append(f"keywords={kw}")

        return f"wss://api.deepgram.com/v1/listen?{'&'.join(params)}"

    async def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """Batch transcription via Deepgram REST API.

        Used as fallback when streaming isn't needed (e.g., pre-recorded audio).
        """
        url = "https://api.deepgram.com/v1/listen"
        params: dict[str, Any] = {
            "model": self._model,
            "language": self._language,
            "smart_format": self._smart_format,
            "punctuate": True,
        }
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "audio/wav",
        }

        try:
            resp = await self._http.post(
                url,
                params=params,
                headers=headers,
                content=audio_bytes,
            )
            resp.raise_for_status()
            data = resp.json()

            channel = data.get("results", {}).get("channels", [{}])[0]
            alt = channel.get("alternatives", [{}])[0]
            text = alt.get("transcript", "")
            confidence = alt.get("confidence", 0.0)
            duration = data.get("metadata", {}).get("duration", 0.0)

            return TranscriptionResult(
                text=text,
                confidence=confidence,
                is_final=True,
                speech_final=True,
                duration_secs=duration,
            )
        except httpx.HTTPError as e:
            logger.warning("Deepgram batch transcription failed: %s", e)
            return TranscriptionResult(text="", confidence=0.0)

    async def stream_transcribe(
        self,
        audio_chunks: AsyncIterator[bytes],
    ) -> AsyncIterator[TranscriptionResult]:
        """Stream audio to Deepgram and yield partial/final transcriptions.

        Opens a WebSocket connection to Deepgram's streaming API. Sends
        audio chunks as they arrive and yields transcription results
        including partial (interim) results for low-latency feedback.
        """
        try:
            import websockets
        except ImportError:
            logger.error("websockets package required for streaming STT")
            return

        ws_url = self._build_ws_url()
        result_queue: asyncio.Queue[TranscriptionResult | None] = asyncio.Queue()

        try:
            async with websockets.connect(
                ws_url,
                additional_headers={"Authorization": f"Token {self._api_key}"},
            ) as ws:

                async def _send_audio() -> None:
                    """Send audio chunks to Deepgram."""
                    try:
                        async for chunk in audio_chunks:
                            await ws.send(chunk)
                        # Signal end of audio
                        await ws.send(json.dumps({"type": "CloseStream"}))
                    except Exception as exc:
                        logger.debug("Deepgram send error: %s", exc)

                async def _receive_results() -> None:
                    """Receive transcription results from Deepgram."""
                    try:
                        async for msg in ws:
                            if isinstance(msg, str):
                                data = json.loads(msg)
                                msg_type = data.get("type", "")

                                if msg_type == "Results":
                                    channel = data.get("channel", {})
                                    alt = channel.get("alternatives", [{}])[0]
                                    text = alt.get("transcript", "")
                                    confidence = alt.get("confidence", 0.0)
                                    is_final = data.get("is_final", False)
                                    speech_final = data.get("speech_final", False)
                                    duration = data.get("duration", 0.0)

                                    if text:
                                        await result_queue.put(
                                            TranscriptionResult(
                                                text=text,
                                                confidence=confidence,
                                                is_final=is_final,
                                                speech_final=speech_final,
                                                duration_secs=duration,
                                            )
                                        )

                                    if speech_final:
                                        break

                                elif msg_type == "UtteranceEnd":
                                    # Deepgram detected end of utterance
                                    await result_queue.put(
                                        TranscriptionResult(
                                            text="",
                                            is_final=True,
                                            speech_final=True,
                                        )
                                    )
                                    break

                    except Exception as exc:
                        logger.debug("Deepgram receive error: %s", exc)
                    finally:
                        await result_queue.put(None)

                send_task = asyncio.create_task(_send_audio())
                recv_task = asyncio.create_task(_receive_results())

                try:
                    while True:
                        result = await asyncio.wait_for(
                            result_queue.get(), timeout=30.0
                        )
                        if result is None:
                            break
                        yield result
                        if result.speech_final:
                            break
                except TimeoutError:
                    logger.warning("Deepgram stream timed out")

                # Clean up tasks
                for task in (send_task, recv_task):
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass

        except Exception as exc:
            logger.warning("Deepgram streaming failed: %s", exc)

    async def aclose(self) -> None:
        """Release the HTTP client."""
        await self._http.aclose()
