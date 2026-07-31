"""Base protocol for end-of-turn detection.

Turn detection answers a narrower question than voice activity detection. VAD
asks "is there speech in this chunk"; turn detection asks "has the speaker
finished and does he expect a reply". A pause is speech-absent but not
necessarily turn-complete -- and cockpit speech is full of pauses.

Detectors are consulted only *after* an acoustic VAD observes silence, so the
caller supplies both the utterance audio and how long the silence has run. A
purely temporal detector uses the duration and ignores the audio; a semantic one
does the reverse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class TurnDecision:
    """Outcome of one end-of-turn evaluation."""

    ended: bool
    #: Confidence that the turn ended, in [0, 1]. Temporal detectors report 1.0
    #: or 0.0 -- they have no graded opinion.
    probability: float
    #: Which detector decided, for logging and diagnostics.
    detector: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(f"probability must be in [0, 1], got {self.probability}")


@runtime_checkable
class TurnDetector(Protocol):
    """Protocol every end-of-turn detector must satisfy."""

    @property
    def name(self) -> str:
        """Short identifier used in decisions and logs."""
        ...

    @property
    def available(self) -> bool:
        """Whether this detector can actually run.

        False when an optional dependency or model file is missing. The factory
        degrades to the temporal detector rather than failing, matching how
        ``SileroVAD`` falls back to RMS when torch is absent.
        """
        ...

    @property
    def probe_silence_ms(self) -> int:
        """Silence to observe before asking this detector.

        A semantic detector can be consulted early and cheaply, so it sets a
        short probe. A temporal detector must wait out its full threshold, so its
        probe *is* its threshold.
        """
        ...

    def evaluate(
        self,
        audio: np.ndarray,
        sample_rate: int,
        silence_ms: int,
    ) -> TurnDecision:
        """Judge whether the turn has ended.

        Args:
            audio: Utterance audio so far, mono float32.
            sample_rate: Sample rate of ``audio``.
            silence_ms: Milliseconds of silence observed since the last speech.
        """
        ...

    def reset(self) -> None:
        """Clear any per-utterance state before a new turn."""
        ...
