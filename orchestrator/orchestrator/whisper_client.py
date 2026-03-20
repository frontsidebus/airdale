"""Client for the local Whisper speech-to-text HTTP service.

Communicates with a Whisper ASR server (onerahmet/openai-whisper-asr-webservice)
to transcribe audio without sending data to any external API.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

OutputFormat = Literal["text", "json", "verbose_json", "srt", "vtt"]

# Defaults
_DEFAULT_WHISPER_URL = "http://localhost:9000"
_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.5  # seconds, multiplied by attempt number


class WhisperClientError(Exception):
    """Raised when the Whisper service returns an error or is unreachable."""


class WhisperClient:
    """HTTP client for a local Whisper ASR service.

    Args:
        base_url: Root URL of the Whisper service (e.g. http://whisper:9000).
        timeout: Request timeout in seconds.
        language: Optional language hint (ISO 639-1 code, e.g. "en").
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_WHISPER_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        language: str | None = "en",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.language = language
        self._client = httpx.Client(timeout=self.timeout)

    # -- Public API -----------------------------------------------------------

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        output_format: OutputFormat = "text",
        language: str | None = None,
    ) -> str:
        """Transcribe audio bytes to text.

        Args:
            audio_bytes: Raw audio data (WAV, MP3, FLAC, etc.).
            output_format: Desired response format from the ASR server.
            language: Override the default language for this request.

        Returns:
            The transcribed text.

        Raises:
            WhisperClientError: If transcription fails after all retries.
        """
        lang = language or self.language
        params: dict[str, str] = {
            "output": output_format,
        }
        if lang:
            params["language"] = lang

        url = f"{self.base_url}/asr"
        files = {"audio_file": ("audio.wav", audio_bytes, "audio/wav")}

        last_error: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self._client.post(url, params=params, files=files)
                response.raise_for_status()
                result = response.text.strip()
                logger.debug("Whisper transcription (%d chars): %s...", len(result), result[:80])
                return result
            except httpx.ConnectError as exc:
                last_error = exc
                wait = _RETRY_BACKOFF * attempt
                logger.warning(
                    "Whisper service unreachable (attempt %d/%d), retrying in %.1fs: %s",
                    attempt,
                    _MAX_RETRIES,
                    wait,
                    exc,
                )
                time.sleep(wait)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                logger.error(
                    "Whisper returned HTTP %d: %s",
                    exc.response.status_code,
                    exc.response.text[:200],
                )
                # Don't retry on client errors (4xx) -- the request itself is bad
                if 400 <= exc.response.status_code < 500:
                    break
                wait = _RETRY_BACKOFF * attempt
                time.sleep(wait)
            except httpx.TimeoutException as exc:
                last_error = exc
                wait = _RETRY_BACKOFF * attempt
                logger.warning(
                    "Whisper request timed out (attempt %d/%d), retrying in %.1fs",
                    attempt,
                    _MAX_RETRIES,
                    wait,
                )
                time.sleep(wait)

        msg = f"Whisper transcription failed after {_MAX_RETRIES} attempts"
        raise WhisperClientError(msg) from last_error

    def is_available(self) -> bool:
        """Check whether the Whisper service is reachable."""
        try:
            resp = self._client.get(f"{self.base_url}/docs", timeout=5.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> WhisperClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
