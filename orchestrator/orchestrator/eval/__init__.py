"""Evaluation utilities for gating model swaps.

Kept separate from runtime code: nothing in the orchestrator's request path
imports this package. It exists so that changing an STT or TTS backend is a
measured decision rather than a vibe check.
"""

from .aviation_wer import (
    CRITICAL_CATEGORIES,
    AviationScore,
    normalize_tokens,
    score_corpus,
    score_transcript,
)

__all__ = [
    "CRITICAL_CATEGORIES",
    "AviationScore",
    "normalize_tokens",
    "score_corpus",
    "score_transcript",
]
