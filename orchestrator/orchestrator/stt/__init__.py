"""Speech-to-text backends for MERLIN voice input.

Mirrors the ``tts`` package: a protocol (:class:`STTClient`), one module per
backend, and a config-driven factory. Both backends receive the same aviation
vocabulary bias -- Whisper via ``initial_prompt``, Deepgram via ``keywords`` --
so switching backends does not silently degrade recognition of callsigns,
V-speeds, and the NATO phonetic alphabet.

Usage::

    from orchestrator.stt import create_stt_client
    from orchestrator.config import load_settings

    client = create_stt_client(load_settings())
    result = await client.transcribe(wav_bytes)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import STTClient, TranscriptionResult

if TYPE_CHECKING:
    from ..config import Settings

__all__ = [
    "STTClient",
    "TranscriptionResult",
    "aviation_keywords",
    "create_stt_client",
]

#: Backends ``create_stt_client`` knows how to build. Keep in sync with the
#: branches below and with ``Settings.stt_configured``.
SUPPORTED_BACKENDS = ("deepgram", "whisper")


def aviation_keywords() -> list[str]:
    """Aviation terms to bias STT toward, derived from ``AVIATION_PROMPT``.

    Whisper consumes the prompt as free text; Deepgram wants a keyword list.
    Deriving both from one source keeps them from drifting apart -- the exact
    failure the duplicated TTS voice settings caused previously.
    """
    from ..audio_processing import AVIATION_PROMPT

    seen: dict[str, None] = {}
    for raw in AVIATION_PROMPT.replace("\n", " ").split(","):
        term = raw.strip()
        # Deepgram keyword boosting works on single tokens and short phrases;
        # anything longer adds cost without improving recall.
        if term and len(term.split()) <= 3:
            seen.setdefault(term, None)
    return list(seen)


def create_stt_client(settings: Settings) -> STTClient:
    """Factory: instantiate the appropriate STT client based on config.

    Reads ``settings.stt_backend``:

    - ``"deepgram"`` (default) -- cloud streaming, partial hypotheses.
    - ``"whisper"`` -- local batch via the Whisper HTTP service.

    Returns:
        An object satisfying the ``STTClient`` protocol.

    Raises:
        ValueError: If ``stt_backend`` is not a recognised value.
    """
    backend = settings.stt_backend.lower().strip()

    if backend == "deepgram":
        from .deepgram import DeepgramSTTClient

        return DeepgramSTTClient(
            api_key=settings.deepgram_api_key,
            model=settings.deepgram_model,
            endpointing_ms=settings.deepgram_endpointing_ms,
            keywords=aviation_keywords(),
        )

    if backend == "whisper":
        from ..whisper_client import WhisperClient
        from .whisper_adapter import WhisperSTTAdapter

        return WhisperSTTAdapter(
            WhisperClient(
                base_url=settings.whisper_url,
                model=settings.whisper_model,
            )
        )

    expected = ", ".join(repr(b) for b in SUPPORTED_BACKENDS)
    raise ValueError(f"Unknown STT backend: {backend!r}. Expected one of {expected}.")


# Lazy imports so the module doesn't pull in every client at import time.
def __getattr__(name: str) -> type:
    if name == "DeepgramSTTClient":
        from .deepgram import DeepgramSTTClient

        return DeepgramSTTClient
    if name == "WhisperSTTAdapter":
        from .whisper_adapter import WhisperSTTAdapter

        return WhisperSTTAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
