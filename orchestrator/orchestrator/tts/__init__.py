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
    "ElevenLabsClient",
    "KokoroClient",
    "TTSClient",
    "create_tts_client",
]


def create_tts_client(settings: Settings) -> TTSClient:
    """Factory: instantiate the appropriate TTS client based on config.

    Reads ``settings.tts_backend`` to decide which backend to use:

    - ``"elevenlabs"`` (default) -- ElevenLabs cloud API.
    - ``"local"`` -- Local Kokoro TTS server.

    Returns:
        An object satisfying the ``TTSClient`` protocol.

    Raises:
        ValueError: If ``tts_backend`` is not a recognised value.
    """
    backend = settings.tts_backend.lower().strip()

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

    raise ValueError(f"Unknown TTS backend: {backend!r}. Expected 'elevenlabs' or 'local'.")


# Lazy imports so the module doesn't pull in both clients at import time.
def __getattr__(name: str) -> type:
    if name == "ElevenLabsClient":
        from .elevenlabs import ElevenLabsClient

        return ElevenLabsClient
    if name == "KokoroClient":
        from .kokoro import KokoroClient

        return KokoroClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
