"""Fixed-duration silence detector -- the behaviour that predates semantic turn detection.

Retained as the always-available fallback and as the honest baseline to measure
semantic detection against. Its weakness is structural, not tunable: a threshold
short enough to feel responsive cuts off anyone who pauses mid-sentence, and one
long enough to tolerate pauses feels sluggish. Aviation phraseology is full of
pauses ("descend and maintain... one zero thousand"), so neither setting is good.
"""

from __future__ import annotations

import numpy as np

from .base import TurnDecision

DEFAULT_SILENCE_MS = 400


class SilenceTurnDetector:
    """Declare the turn over once silence exceeds a fixed threshold."""

    def __init__(self, silence_ms: int = DEFAULT_SILENCE_MS) -> None:
        if silence_ms <= 0:
            raise ValueError(f"silence_ms must be positive, got {silence_ms}")
        self._silence_ms = silence_ms

    @property
    def name(self) -> str:
        return "silence"

    @property
    def available(self) -> bool:
        """Always true -- this detector has no dependencies to be missing."""
        return True

    @property
    def probe_silence_ms(self) -> int:
        """Equal to the threshold: there is nothing to ask before it elapses."""
        return self._silence_ms

    @property
    def silence_ms(self) -> int:
        return self._silence_ms

    def evaluate(
        self,
        audio: np.ndarray,  # noqa: ARG002 - temporal detector ignores content
        sample_rate: int,  # noqa: ARG002
        silence_ms: int,
    ) -> TurnDecision:
        ended = silence_ms >= self._silence_ms
        return TurnDecision(
            ended=ended,
            probability=1.0 if ended else 0.0,
            detector=self.name,
        )

    def reset(self) -> None:
        """No per-utterance state to clear."""
