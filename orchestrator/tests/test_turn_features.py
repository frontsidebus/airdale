"""Golden-value tests for the Whisper log-mel implementation.

The Smart Turn ONNX model consumes Whisper log-mel features. Upstream produces
them with `transformers.WhisperFeatureExtractor`; we reimplement in numpy to
avoid a torch-sized dependency for a spectrogram.

The expected values below were captured from `WhisperFeatureExtractor(chunk_length=8)`
with `do_normalize=True`, the exact call upstream's `inference.py` makes. The
numpy implementation was verified elementwise against it to < 1e-4 across noise,
silence, tones, chirps, and short inputs.

These tests exist because a divergence here would not raise -- it would silently
shift every turn prediction. Two bugs were caught this way during implementation:
padding side (~2.15 absolute error) and normalization ordering (~0.64).
"""

from __future__ import annotations

import numpy as np
import pytest
from orchestrator.turn.features import (
    N_FRAMES,
    N_MELS,
    N_SAMPLES,
    log_mel_spectrogram,
    mel_filter_bank,
    truncate_or_pad,
)

#: (mean, std, min, max) from the reference extractor, to 6 dp.
GOLDEN: dict[str, tuple[float, float, float, float]] = {
    "noise": (1.112866, 0.089835, 0.079126, 1.390819),
    "silence": (-1.500000, 0.000000, -1.500000, -1.500000),
    "tone": (-0.240087, 0.410779, -0.336024, 1.663976),
    "short": (-0.296894, 0.276922, -0.361441, 1.638559),
}


def _case(name: str) -> np.ndarray:
    rng = np.random.default_rng(1234)
    if name == "noise":
        return rng.standard_normal(N_SAMPLES).astype(np.float32) * 0.1
    if name == "silence":
        return np.zeros(N_SAMPLES, dtype=np.float32)
    if name == "tone":
        return np.sin(2 * np.pi * 440 * np.arange(N_SAMPLES) / 16000).astype(np.float32)
    if name == "short":
        return (np.sin(2 * np.pi * 300 * np.arange(2 * 16000) / 16000) * 0.5).astype(np.float32)
    raise AssertionError(f"unknown case {name}")


class TestGoldenValues:
    @pytest.mark.parametrize("name", sorted(GOLDEN))
    def test_matches_reference_extractor(self, name: str) -> None:
        features = log_mel_spectrogram(_case(name))
        expected_mean, expected_std, expected_min, expected_max = GOLDEN[name]
        assert features.mean() == pytest.approx(expected_mean, abs=1e-4)
        assert features.std() == pytest.approx(expected_std, abs=1e-4)
        assert features.min() == pytest.approx(expected_min, abs=1e-4)
        assert features.max() == pytest.approx(expected_max, abs=1e-4)

    @pytest.mark.parametrize("name", sorted(GOLDEN))
    def test_shape_matches_onnx_input(self, name: str) -> None:
        """The model declares input [batch, 80, 800]; anything else fails at runtime."""
        assert log_mel_spectrogram(_case(name)).shape == (N_MELS, N_FRAMES)

    def test_output_is_float32(self) -> None:
        """ONNX rejects float64 silently-ish; pin the dtype."""
        assert log_mel_spectrogram(_case("noise")).dtype == np.float32


class TestWindowing:
    def test_long_audio_keeps_the_end(self) -> None:
        """The model judges whether recent speech ended, so keep the tail."""
        audio = np.arange(N_SAMPLES * 2, dtype=np.float32)
        fitted = truncate_or_pad(audio)
        assert fitted.shape == (N_SAMPLES,)
        assert fitted[-1] == audio[-1]

    def test_short_audio_is_right_padded(self) -> None:
        """Upstream's README says left-pad; its shipped inference.py right-pads.

        We match the executable reference. Left-padding diverges by ~2.15
        absolute against the extractor, which is not a rounding difference.
        """
        audio = np.ones(1000, dtype=np.float32)
        fitted = truncate_or_pad(audio)
        assert fitted.shape == (N_SAMPLES,)
        assert fitted[0] == 1.0
        assert fitted[-1] == 0.0

    def test_exact_length_is_unchanged(self) -> None:
        audio = np.arange(N_SAMPLES, dtype=np.float32)
        assert np.array_equal(truncate_or_pad(audio), audio)

    def test_empty_audio_does_not_crash(self) -> None:
        features = log_mel_spectrogram(np.array([], dtype=np.float32))
        assert features.shape == (N_MELS, N_FRAMES)


class TestMelFilterBank:
    def test_shape(self) -> None:
        assert mel_filter_bank().shape == (N_MELS, 201)

    def test_filters_are_non_negative(self) -> None:
        assert (mel_filter_bank() >= 0).all()

    def test_every_filter_has_energy(self) -> None:
        """An all-zero row means a dead mel band and silently lost information."""
        assert (mel_filter_bank().sum(axis=1) > 0).all()


class TestSampleRateGuard:
    def test_non_16k_is_rejected_loudly(self) -> None:
        """The filterbank is precomputed for 16 kHz; silently accepting 48 kHz
        would produce plausible-looking, wrong features."""
        with pytest.raises(ValueError, match="16000 Hz"):
            log_mel_spectrogram(np.zeros(1000, dtype=np.float32), sample_rate=48000)
