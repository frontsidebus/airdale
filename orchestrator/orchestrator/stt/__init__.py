"""Speech-to-text backends for MERLIN voice input."""

from .base import STTClient, TranscriptionResult
from .deepgram import DeepgramSTTClient

__all__ = ["STTClient", "TranscriptionResult", "DeepgramSTTClient"]
