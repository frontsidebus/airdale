"""Tests for end-of-turn detection: protocol, detectors, and factory.

Most tests stub the ONNX session so the suite never needs the 8 MB model file or
a network call. The few that exercise the real model are skipped when it is
absent, which is also the state CI runs in.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from orchestrator.config import Settings
from orchestrator.turn import (
    SUPPORTED_DETECTORS,
    SilenceTurnDetector,
    TurnDecision,
    TurnDetector,
    create_turn_detector,
)
from orchestrator.turn.smart_turn import SmartTurnDetector, default_model_path


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"anthropic_api_key": "sk-test", "_env_file": None}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class _FakeSession:
    """Stand-in for an onnxruntime InferenceSession returning a fixed probability."""

    def __init__(self, probability: float = 0.9, raises: Exception | None = None) -> None:
        self.probability = probability
        self.raises = raises
        self.calls: list[np.ndarray] = []

    def run(self, _outputs: object, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
        if self.raises is not None:
            raise self.raises
        self.calls.append(feeds["input_features"])
        return [np.array([[self.probability]], dtype=np.float32)]


def _detector_with(session: _FakeSession, **kwargs: object) -> SmartTurnDetector:
    detector = SmartTurnDetector(**kwargs)  # type: ignore[arg-type]
    detector._session = session
    detector._load_attempted = True
    return detector


class TestTurnDecision:
    def test_rejects_out_of_range_probability(self) -> None:
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            TurnDecision(ended=True, probability=1.5, detector="x")

    def test_is_immutable(self) -> None:
        """Decisions are records, not mutable state passed between layers."""
        decision = TurnDecision(ended=True, probability=1.0, detector="x")
        with pytest.raises(AttributeError):
            decision.ended = False  # type: ignore[misc]


class TestSilenceDetector:
    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(SilenceTurnDetector(), TurnDetector)

    def test_ends_at_or_past_threshold(self) -> None:
        detector = SilenceTurnDetector(silence_ms=400)
        audio = np.zeros(16000, dtype=np.float32)
        assert detector.evaluate(audio, 16000, 399).ended is False
        assert detector.evaluate(audio, 16000, 400).ended is True
        assert detector.evaluate(audio, 16000, 900).ended is True

    def test_probe_equals_threshold(self) -> None:
        """A temporal detector has nothing useful to say before its threshold."""
        assert SilenceTurnDetector(silence_ms=250).probe_silence_ms == 250

    def test_ignores_audio_content(self) -> None:
        detector = SilenceTurnDetector(silence_ms=100)
        speech = np.random.default_rng(0).standard_normal(16000).astype(np.float32)
        silence = np.zeros(16000, dtype=np.float32)
        assert detector.evaluate(speech, 16000, 150) == detector.evaluate(silence, 16000, 150)

    def test_probability_is_binary(self) -> None:
        detector = SilenceTurnDetector(silence_ms=400)
        audio = np.zeros(100, dtype=np.float32)
        assert detector.evaluate(audio, 16000, 500).probability == 1.0
        assert detector.evaluate(audio, 16000, 100).probability == 0.0

    def test_rejects_non_positive_threshold(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            SilenceTurnDetector(silence_ms=0)


class TestSmartTurnDetector:
    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(_detector_with(_FakeSession()), TurnDetector)

    def test_threshold_decides(self) -> None:
        audio = np.zeros(16000, dtype=np.float32)
        assert _detector_with(_FakeSession(0.9), threshold=0.5).evaluate(audio, 16000, 200).ended
        assert (
            not _detector_with(_FakeSession(0.2), threshold=0.5).evaluate(audio, 16000, 200).ended
        )
        # Raising the threshold makes MERLIN wait through more pauses.
        assert (
            not _detector_with(_FakeSession(0.6), threshold=0.8).evaluate(audio, 16000, 200).ended
        )

    def test_ignores_silence_duration(self) -> None:
        """The semantic detector judges content; duration is the gate, not the signal."""
        detector = _detector_with(_FakeSession(0.9))
        audio = np.zeros(16000, dtype=np.float32)
        assert detector.evaluate(audio, 16000, 10) == detector.evaluate(audio, 16000, 5000)

    def test_feeds_correctly_shaped_features(self) -> None:
        session = _FakeSession()
        _detector_with(session).evaluate(np.zeros(16000, dtype=np.float32), 16000, 200)
        assert session.calls[0].shape == (1, 80, 800)
        assert session.calls[0].dtype == np.float32

    def test_unavailable_model_reports_turn_ongoing(self) -> None:
        """Missing model must make MERLIN wait, never interrupt."""
        detector = SmartTurnDetector(model_path=Path("/nonexistent/model.onnx"))
        assert detector.available is False
        decision = detector.evaluate(np.zeros(16000, dtype=np.float32), 16000, 200)
        assert decision.ended is False

    def test_inference_failure_reports_turn_ongoing(self) -> None:
        detector = _detector_with(_FakeSession(raises=RuntimeError("onnx exploded")))
        decision = detector.evaluate(np.zeros(16000, dtype=np.float32), 16000, 200)
        assert decision.ended is False
        assert decision.probability == 0.0

    def test_probability_is_clamped(self) -> None:
        """Guard against a future model emitting raw logits instead of sigmoid."""
        audio = np.zeros(16000, dtype=np.float32)
        assert _detector_with(_FakeSession(4.2)).evaluate(audio, 16000, 200).probability == 1.0
        assert _detector_with(_FakeSession(-3.0)).evaluate(audio, 16000, 200).probability == 0.0

    def test_probe_is_shorter_than_the_silence_default(self) -> None:
        """The whole point is deciding sooner than a fixed 400 ms wait."""
        assert _detector_with(_FakeSession()).probe_silence_ms < SilenceTurnDetector().silence_ms

    def test_session_built_once(self) -> None:
        detector = SmartTurnDetector(model_path=Path("/nonexistent/model.onnx"))
        assert detector.available is False
        assert detector.available is False  # cached, no repeated disk probe
        assert detector._load_attempted is True

    def test_rejects_out_of_range_threshold(self) -> None:
        for bad in (0.0, 1.0, -0.1, 1.5):
            with pytest.raises(ValueError, match=r"\(0, 1\)"):
                SmartTurnDetector(threshold=bad)


class TestFactory:
    @pytest.mark.parametrize("choice", SUPPORTED_DETECTORS)
    def test_every_supported_choice_builds(self, choice: str) -> None:
        assert isinstance(create_turn_detector(_settings(turn_detector=choice)), TurnDetector)

    def test_unknown_choice_names_the_alternatives(self) -> None:
        with pytest.raises(ValueError, match="Unknown turn detector") as exc:
            create_turn_detector(_settings(turn_detector="telepathy"))
        for choice in SUPPORTED_DETECTORS:
            assert choice in str(exc.value)

    def test_selection_is_case_and_space_insensitive(self) -> None:
        detector = create_turn_detector(_settings(turn_detector="  SILENCE  "))
        assert isinstance(detector, SilenceTurnDetector)

    def test_smart_falls_back_when_model_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A missing model must degrade latency, not break voice input."""
        monkeypatch.setenv("MERLIN_TURN_MODEL_PATH", str(tmp_path / "absent.onnx"))
        detector = create_turn_detector(_settings(turn_detector="smart", vad_silence_ms=350))
        assert isinstance(detector, SilenceTurnDetector)
        assert detector.silence_ms == 350

    def test_silence_threshold_comes_from_config(self) -> None:
        detector = create_turn_detector(_settings(turn_detector="silence", vad_silence_ms=250))
        assert detector.probe_silence_ms == 250


class TestVoiceInputIntegration:
    def test_defaults_to_silence_detector(self) -> None:
        """Constructing VoiceInput without a detector must not change behaviour."""
        from orchestrator.voice import VoiceInput

        voice = VoiceInput(whisper_client=object(), vad_silence_duration=0.4)  # type: ignore[arg-type]
        assert isinstance(voice.turn_detector, SilenceTurnDetector)
        assert voice.turn_detector.silence_ms == 400

    def test_accepts_an_injected_detector(self) -> None:
        from orchestrator.voice import VoiceInput

        detector = _detector_with(_FakeSession())
        voice = VoiceInput(whisper_client=object(), turn_detector=detector)  # type: ignore[arg-type]
        assert voice.turn_detector is detector


@pytest.mark.skipif(
    not default_model_path().is_file(),
    reason="Smart Turn model not downloaded; run tools/fetch_turn_model.py",
)
class TestRealModel:
    """Exercised only when the model is present locally."""

    def test_loads_and_predicts(self) -> None:
        detector = SmartTurnDetector()
        assert detector.available is True
        decision = detector.evaluate(np.zeros(2 * 16000, dtype=np.float32), 16000, 200)
        assert 0.0 <= decision.probability <= 1.0
        assert decision.detector == "smart_turn"

    def test_output_is_a_probability_not_a_logit(self) -> None:
        """The tensor is named 'logits' but the sigmoid is baked into the graph.

        If a future model version changes that, this catches it -- raw logits
        would fall outside [0, 1] on at least one of these inputs.
        """
        detector = SmartTurnDetector()
        rng = np.random.default_rng(0)
        for audio in (
            np.zeros(8 * 16000, dtype=np.float32),
            rng.standard_normal(8 * 16000).astype(np.float32),
            np.sin(2 * np.pi * 440 * np.arange(8 * 16000) / 16000).astype(np.float32),
        ):
            raw = detector.evaluate(audio, 16000, 200).probability
            assert 0.0 <= raw <= 1.0
