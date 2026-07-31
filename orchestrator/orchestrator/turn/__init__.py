"""End-of-turn detection backends.

Mirrors ``stt`` and ``tts``: a protocol, one module per backend, and a
config-driven factory. Adding a detector means adding a module and a factory
branch -- consumers hold the protocol, never a concrete detector.

Usage::

    from orchestrator.turn import create_turn_detector
    from orchestrator.config import load_settings

    detector = create_turn_detector(load_settings())
    decision = detector.evaluate(audio, 16000, silence_ms=180)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import TurnDecision, TurnDetector
from .silence import SilenceTurnDetector

if TYPE_CHECKING:
    from ..config import Settings

logger = logging.getLogger(__name__)

__all__ = [
    "SUPPORTED_DETECTORS",
    "SilenceTurnDetector",
    "TurnDecision",
    "TurnDetector",
    "create_turn_detector",
]

#: Detectors ``create_turn_detector`` knows how to build. Keep in sync with the
#: branches below and with ``Settings.turn_detector``.
SUPPORTED_DETECTORS = ("smart", "silence")


def create_turn_detector(settings: Settings) -> TurnDetector:
    """Build the configured detector, degrading gracefully.

    ``smart`` falls back to ``silence`` when onnxruntime or the model file is
    missing. That check runs here, at startup, rather than mid-flight -- a
    fallback discovered during a takeoff callout would be the worst possible
    time to find out.

    Raises:
        ValueError: If ``turn_detector`` is not a recognised value.
    """
    choice = settings.turn_detector.lower().strip()

    if choice == "smart":
        from .smart_turn import SmartTurnDetector

        detector = SmartTurnDetector(
            threshold=settings.turn_threshold,
            probe_silence_ms=settings.turn_probe_silence_ms,
        )
        if detector.available:
            return detector
        logger.warning(
            "Semantic turn detection requested but unavailable; using fixed-silence "
            "detection at %d ms. Run `python3 tools/fetch_turn_model.py` to enable it.",
            settings.vad_silence_ms,
        )
        return SilenceTurnDetector(silence_ms=settings.vad_silence_ms)

    if choice == "silence":
        return SilenceTurnDetector(silence_ms=settings.vad_silence_ms)

    expected = ", ".join(repr(d) for d in SUPPORTED_DETECTORS)
    raise ValueError(f"Unknown turn detector: {choice!r}. Expected one of {expected}.")


def __getattr__(name: str) -> type:
    # Lazy so importing this package never pulls in onnxruntime.
    if name == "SmartTurnDetector":
        from .smart_turn import SmartTurnDetector

        return SmartTurnDetector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
