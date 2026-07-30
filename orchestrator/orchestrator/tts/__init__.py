"""TTS client abstraction layer for multiple synthesis backends.

Provides a unified interface (``TTSClient`` protocol) with concrete
implementations for ElevenLabs (cloud) and Kokoro (local).

Usage::

    from orchestrator.tts import create_tts_client
    from orchestrator.config import load_settings

    settings = load_settings()
    client = create_tts_client(settings)

    audio = await client.synthesize("Roger, Captain.")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import TTSClient

if TYPE_CHECKING:
    from ..config import Settings

__all__ = [
    "CartesiaClient",
    "ElevenLabsClient",
    "KokoroClient",
    "TTSClient",
    "create_tts_client",
]

#: Backends ``create_tts_client`` knows how to build. Keep in sync with the
#: branches below and with ``Settings.tts_configured`` / ``Settings.voice_id``.
SUPPORTED_BACKENDS = ("cartesia", "elevenlabs", "local")


def create_tts_client(settings: Settings) -> TTSClient:
    """Factory: instantiate the appropriate TTS client based on config.

    Reads ``settings.tts_backend`` to decide which backend to use:

    - ``"cartesia"`` (default) -- Cartesia cloud API, lowest latency.
    - ``"elevenlabs"`` -- ElevenLabs cloud API.
    - ``"local"`` -- Local Kokoro TTS server.

    Returns:
        An object satisfying the ``TTSClient`` protocol.

    Raises:
        ValueError: If ``tts_backend`` is not a recognised value.
    """
    backend = settings.tts_backend.lower().strip()

    if backend == "cartesia":
        from .cartesia import CartesiaClient

        return CartesiaClient(
            api_key=settings.cartesia_api_key,
            voice_id=settings.cartesia_voice_id,
            model_id=settings.cartesia_model_id,
        )

    if backend == "elevenlabs":
        from .elevenlabs import ElevenLabsClient

        return ElevenLabsClient(
            api_key=settings.elevenlabs_api_key,
            voice_id=settings.elevenlabs_voice_id,
            model_id=settings.elevenlabs_model_id,
            stability=settings.tts_stability,
            similarity_boost=settings.tts_similarity_boost,
            style=settings.tts_style,
        )

    if backend == "local":
        from .kokoro import KokoroClient

        return KokoroClient(
            base_url=settings.tts_local_url,
            voice_id=settings.tts_voice_id_local,
        )

    expected = ", ".join(repr(b) for b in SUPPORTED_BACKENDS)
    raise ValueError(f"Unknown TTS backend: {backend!r}. Expected one of {expected}.")


# Lazy imports so the module doesn't pull in every client at import time.
def __getattr__(name: str) -> type:
    if name == "CartesiaClient":
        from .cartesia import CartesiaClient

        return CartesiaClient
    if name == "ElevenLabsClient":
        from .elevenlabs import ElevenLabsClient

        return ElevenLabsClient
    if name == "KokoroClient":
        from .kokoro import KokoroClient

        return KokoroClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
