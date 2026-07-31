"""Semantic end-of-turn detection via the Smart Turn v3 ONNX model.

Smart Turn reads the waveform, not a transcript, so it works identically on the
local Whisper path and the Deepgram streaming path and needs no STT round-trip.
It is small enough to be effectively free: ~8 MB int8, single-digit to tens of
milliseconds on CPU.

Model: https://huggingface.co/pipecat-ai/smart-turn-v3 (BSD-2-Clause)

The model is *not* vendored. It is fetched on first use and cached, or
pre-fetched with ``tools/fetch_turn_model.py``. If it is missing -- or
onnxruntime is unavailable -- this detector reports ``available = False`` and the
factory falls back to the temporal detector, so a missing model degrades latency
rather than breaking voice input.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import numpy as np

from .base import TurnDecision
from .features import log_mel_spectrogram

logger = logging.getLogger(__name__)

MODEL_FILENAME = "smart-turn-v3.2-cpu.onnx"
MODEL_URL = f"https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/{MODEL_FILENAME}"

#: Above this, the model considers the utterance complete. 0.5 is the reference
#: threshold; raise it to make MERLIN more willing to wait through a pause.
DEFAULT_THRESHOLD = 0.5

#: Silence to observe before asking the model. Well below the temporal
#: detector's 400 ms -- the point of semantic detection is to decide sooner,
#: using content rather than duration.
DEFAULT_PROBE_SILENCE_MS = 150


def default_model_path() -> Path:
    """Cache location, overridable with ``MERLIN_TURN_MODEL_PATH``."""
    override = os.environ.get("MERLIN_TURN_MODEL_PATH")
    if override:
        return Path(override)
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_root / "merlin" / "turn" / MODEL_FILENAME


class SmartTurnDetector:
    """End-of-turn classification from raw audio.

    The ONNX session is built lazily on first use so that constructing the
    detector -- which happens during orchestrator startup -- never blocks on disk
    or model load.
    """

    def __init__(
        self,
        model_path: Path | None = None,
        threshold: float = DEFAULT_THRESHOLD,
        probe_silence_ms: int = DEFAULT_PROBE_SILENCE_MS,
    ) -> None:
        if not 0.0 < threshold < 1.0:
            raise ValueError(f"threshold must be in (0, 1), got {threshold}")
        self._model_path = model_path or default_model_path()
        self._threshold = threshold
        self._probe_silence_ms = probe_silence_ms
        self._session: object | None = None
        self._load_attempted = False
        self._load_lock = threading.Lock()

    @property
    def name(self) -> str:
        return "smart_turn"

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def model_path(self) -> Path:
        return self._model_path

    @property
    def probe_silence_ms(self) -> int:
        return self._probe_silence_ms

    @property
    def available(self) -> bool:
        """Whether onnxruntime and the model file are both present."""
        return self._ensure_session() is not None

    def _ensure_session(self) -> object | None:
        """Build the ONNX session once; cache the outcome including failure."""
        if self._load_attempted:
            return self._session
        with self._load_lock:
            if self._load_attempted:  # another thread won the race
                return self._session
            self._load_attempted = True
            self._session = self._build_session()
        return self._session

    def _build_session(self) -> object | None:
        try:
            import onnxruntime as ort
        except ImportError:
            logger.info(
                "onnxruntime not installed; semantic turn detection unavailable, "
                "falling back to fixed-silence detection"
            )
            return None

        if not self._model_path.is_file():
            logger.info(
                "Turn model not found at %s; falling back to fixed-silence detection. "
                "Fetch it with: python3 tools/fetch_turn_model.py",
                self._model_path,
            )
            return None

        try:
            options = ort.SessionOptions()
            # Single-threaded sequential execution: inference is sub-20ms and
            # runs on the audio callback path, where thread-pool churn costs
            # more than it saves.
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.inter_op_num_threads = 1
            options.intra_op_num_threads = 1
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            session = ort.InferenceSession(
                str(self._model_path),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        except Exception:
            logger.exception("Failed to load turn model from %s", self._model_path)
            return None

        logger.info("Semantic turn detection ready (%s)", self._model_path.name)
        return session

    def evaluate(
        self,
        audio: np.ndarray,
        sample_rate: int,
        silence_ms: int,  # noqa: ARG002 - semantic detector judges content, not duration
    ) -> TurnDecision:
        """Classify whether the utterance is complete.

        Returns a not-ended decision if the model is unavailable or inference
        fails, so a broken model makes MERLIN wait rather than interrupt.
        """
        session = self._ensure_session()
        if session is None:
            return TurnDecision(ended=False, probability=0.0, detector=self.name)

        try:
            features = log_mel_spectrogram(audio, sample_rate=sample_rate)
            outputs = session.run(None, {"input_features": features[np.newaxis, ...]})  # type: ignore[attr-defined]
            # The output tensor is named "logits" but the sigmoid is baked into
            # the graph -- values arrive already in [0, 1]. Verified empirically
            # against the published model; see tests.
            probability = float(outputs[0][0][0])
        except Exception:
            logger.exception("Turn model inference failed; treating turn as ongoing")
            return TurnDecision(ended=False, probability=0.0, detector=self.name)

        probability = min(1.0, max(0.0, probability))
        return TurnDecision(
            ended=probability >= self._threshold,
            probability=probability,
            detector=self.name,
        )

    def reset(self) -> None:
        """No per-utterance state: each evaluation sees the full window."""


def fetch_model(destination: Path | None = None, *, force: bool = False) -> Path:
    """Download the Smart Turn model to the cache.

    Separated from inference so that the network call is always explicit --
    nothing downloads implicitly during a flight.

    Raises:
        RuntimeError: If the download fails or returns an implausibly small file.
    """
    import urllib.request

    target = destination or default_model_path()
    if target.is_file() and not force:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".partial")
    logger.info("Downloading turn model to %s", target)
    try:
        urllib.request.urlretrieve(MODEL_URL, tmp)  # noqa: S310 - fixed https URL
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download turn model from {MODEL_URL}: {exc}") from exc

    # A 404 from the CDN arrives as a short HTML/text body, not an error.
    size = tmp.stat().st_size
    if size < 1_000_000:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"Downloaded turn model is only {size} bytes, expected ~8 MB. "
            "The URL may have moved; check the model repository."
        )

    tmp.replace(target)
    return target
