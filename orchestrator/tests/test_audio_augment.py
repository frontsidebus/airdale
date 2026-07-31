"""Tests for evaluation audio degradation.

The point of this module is to make synthetic audio *harder* in a controlled,
reproducible way. The properties worth pinning are therefore: the requested SNR
is actually achieved, band-limiting removes the energy it claims to, and the
same seed gives the same result -- because a backend comparison confounded by
different noise draws would be worthless.
"""

from __future__ import annotations

import numpy as np
import pytest
from orchestrator.eval.audio_augment import (
    CLEAN,
    HEADSET,
    PROFILES,
    VHF,
    augment,
    bandlimit,
    engine_noise,
    mix_at_snr,
    pink_noise,
    soft_clip,
    speech_rms,
)

SR = 16000


def _speech_like(seconds: float = 2.0, seed: int = 0) -> np.ndarray:
    """Amplitude-modulated tone stack: crude, but has speech-ish structure."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    carrier = sum(np.sin(2 * np.pi * f * t) for f in (200, 500, 1200, 2400))
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)
    signal = carrier * envelope + rng.standard_normal(t.size) * 0.01
    return (signal / np.abs(signal).max()).astype(np.float32)


def _with_silence(signal: np.ndarray, pad_seconds: float = 1.0) -> np.ndarray:
    pad = np.zeros(int(pad_seconds * SR), dtype=np.float32)
    return np.concatenate([pad, signal, pad])


class TestSpeechRms:
    def test_ignores_leading_and_trailing_silence(self) -> None:
        """Measuring across silence would deflate the level and skew every SNR."""
        speech = _speech_like()
        assert speech_rms(_with_silence(speech)) == pytest.approx(speech_rms(speech), rel=0.1)

    def test_naive_rms_would_have_been_wrong(self) -> None:
        """Pins the reason this helper exists rather than np.sqrt(mean(x**2))."""
        padded = _with_silence(_speech_like())
        naive = float(np.sqrt(np.mean(padded**2)))
        assert speech_rms(padded) > naive * 1.3

    def test_empty_and_silent_are_zero(self) -> None:
        assert speech_rms(np.zeros(0, dtype=np.float32)) == 0.0
        assert speech_rms(np.zeros(SR, dtype=np.float32)) == 0.0


class TestNoiseGenerators:
    def test_pink_noise_is_low_frequency_weighted(self) -> None:
        spectrum = np.abs(np.fft.rfft(pink_noise(SR, np.random.default_rng(0))))
        low = spectrum[1 : len(spectrum) // 8].mean()
        high = spectrum[len(spectrum) // 2 :].mean()
        assert low > high * 2, "pink noise must carry more low-frequency energy"

    def test_engine_noise_has_a_tonal_peak(self) -> None:
        noise = engine_noise(SR * 2, SR, np.random.default_rng(0), fundamental_hz=90.0)
        spectrum = np.abs(np.fft.rfft(noise))
        freqs = np.fft.rfftfreq(noise.size, 1 / SR)
        near_fundamental = spectrum[(freqs > 80) & (freqs < 100)].max()
        broadband = np.median(spectrum[(freqs > 1000) & (freqs < 4000)])
        assert near_fundamental > broadband * 5

    def test_generators_are_bounded_and_deterministic(self) -> None:
        for fn in (
            lambda r: pink_noise(SR, r),
            lambda r: engine_noise(SR, SR, r),
        ):
            first = fn(np.random.default_rng(7))
            second = fn(np.random.default_rng(7))
            assert np.array_equal(first, second)
            assert np.abs(first).max() <= 1.0 + 1e-6

    def test_zero_length(self) -> None:
        assert pink_noise(0, np.random.default_rng(0)).size == 0
        assert engine_noise(0, SR, np.random.default_rng(0)).size == 0


class TestMixAtSnr:
    @pytest.mark.parametrize("target_db", [30.0, 20.0, 10.0, 0.0])
    def test_achieves_the_requested_ratio(self, target_db: float) -> None:
        speech = _speech_like()
        noise = pink_noise(speech.size, np.random.default_rng(0))
        mixed = mix_at_snr(speech, noise, target_db)

        residual = mixed - speech  # exactly the scaled noise
        measured = 20 * np.log10(speech_rms(speech) / float(np.sqrt(np.mean(residual**2))))
        assert measured == pytest.approx(target_db, abs=0.5)

    def test_lower_snr_adds_more_noise(self) -> None:
        speech = _speech_like()
        noise = pink_noise(speech.size, np.random.default_rng(0))
        quiet = np.abs(mix_at_snr(speech, noise, 30.0) - speech).mean()
        loud = np.abs(mix_at_snr(speech, noise, 5.0) - speech).mean()
        assert loud > quiet

    def test_degenerate_inputs_pass_through(self) -> None:
        speech = _speech_like()
        assert mix_at_snr(np.zeros(0, dtype=np.float32), speech, 20.0).size == 0
        # Silent signal has no level to measure against; return it unchanged
        # rather than dividing by zero.
        silent = np.zeros(SR, dtype=np.float32)
        assert np.array_equal(mix_at_snr(silent, speech, 20.0), silent)


class TestBandlimit:
    def test_removes_energy_outside_the_band(self) -> None:
        t = np.arange(SR) / SR
        low_tone = np.sin(2 * np.pi * 60 * t).astype(np.float32)
        in_band = np.sin(2 * np.pi * 1000 * t).astype(np.float32)

        filtered_low = bandlimit(low_tone, SR, 300.0, 3400.0)
        filtered_in = bandlimit(in_band, SR, 300.0, 3400.0)

        assert np.abs(filtered_low).max() < 0.1
        assert np.abs(filtered_in).max() > 0.8

    def test_removes_energy_above_the_band(self) -> None:
        t = np.arange(SR) / SR
        high_tone = np.sin(2 * np.pi * 6000 * t).astype(np.float32)
        assert np.abs(bandlimit(high_tone, SR, 300.0, 3400.0)).max() < 0.1

    def test_zero_bounds_disable_filtering(self) -> None:
        signal = _speech_like()
        assert np.allclose(bandlimit(signal, SR, 0.0, 0.0), signal)

    def test_empty_input(self) -> None:
        assert bandlimit(np.zeros(0, dtype=np.float32), SR, 300.0, 3400.0).size == 0


class TestSoftClip:
    def test_limits_peaks(self) -> None:
        signal = np.array([-2.0, -0.1, 0.0, 0.1, 2.0], dtype=np.float32)
        assert np.abs(soft_clip(signal, 0.8)).max() < 0.8

    def test_threshold_of_one_is_a_passthrough(self) -> None:
        signal = _speech_like()
        assert np.array_equal(soft_clip(signal, 1.0), signal)

    def test_preserves_sign(self) -> None:
        signal = np.array([-0.5, 0.5], dtype=np.float32)
        clipped = soft_clip(signal, 0.8)
        assert clipped[0] < 0 < clipped[1]


class TestAugment:
    def test_is_deterministic_for_a_seed(self) -> None:
        """A backend comparison must not be confounded by different noise draws."""
        speech = _speech_like()
        first = augment(speech, SR, profile="headset", snr_db=15.0, seed=42)
        second = augment(speech, SR, profile="headset", snr_db=15.0, seed=42)
        assert np.array_equal(first, second)

    def test_different_seeds_differ(self) -> None:
        speech = _speech_like()
        a = augment(speech, SR, snr_db=15.0, seed=1)
        b = augment(speech, SR, snr_db=15.0, seed=2)
        assert not np.array_equal(a, b)

    def test_clean_profile_without_noise_is_identity_given_headroom(self) -> None:
        """Input already below the 0.99 ceiling passes through untouched."""
        speech = (_speech_like() * 0.5).astype(np.float32)
        assert np.allclose(augment(speech, SR, profile="clean", snr_db=None), speech, atol=1e-5)

    def test_full_scale_input_is_scaled_to_headroom_not_clipped(self) -> None:
        """A signal peaking at 1.0 is attenuated, preserving waveform shape."""
        speech = _speech_like()  # normalized to peak 1.0
        out = augment(speech, SR, profile="clean", snr_db=None)
        assert np.abs(out).max() == pytest.approx(0.99, abs=1e-3)
        # Scaling, not clipping: the shape must survive intact.
        correlation = np.corrcoef(out, speech)[0, 1]
        assert correlation > 0.9999

    def test_output_has_headroom(self) -> None:
        """int16 conversion downstream must not wrap."""
        loud = (_speech_like() * 0.99).astype(np.float32)
        for snr in (20.0, 5.0, 0.0):
            assert np.abs(augment(loud, SR, snr_db=snr)).max() <= 0.99 + 1e-6

    def test_vhf_is_more_band_limited_than_headset(self) -> None:
        t = np.arange(SR) / SR
        tone_5k = np.sin(2 * np.pi * 5000 * t).astype(np.float32)
        headset = np.abs(augment(tone_5k, SR, profile="headset", snr_db=None)).max()
        vhf = np.abs(augment(tone_5k, SR, profile="vhf", snr_db=None)).max()
        assert vhf < headset

    @pytest.mark.parametrize("name", sorted(PROFILES))
    def test_every_profile_runs(self, name: str) -> None:
        out = augment(_speech_like(0.5), SR, profile=name, snr_db=20.0)
        assert out.size == int(0.5 * SR)
        assert np.isfinite(out).all()

    def test_accepts_a_profile_object(self) -> None:
        out = augment(_speech_like(0.5), SR, profile=VHF, snr_db=20.0)
        assert np.isfinite(out).all()

    def test_unknown_profile_names_the_alternatives(self) -> None:
        with pytest.raises(ValueError, match="Unknown channel profile") as exc:
            augment(_speech_like(0.5), SR, profile="underwater")
        for name in PROFILES:
            assert name in str(exc.value)

    def test_empty_input(self) -> None:
        assert augment(np.zeros(0, dtype=np.float32), SR).size == 0

    def test_profiles_registry_is_consistent(self) -> None:
        for profile in (CLEAN, HEADSET, VHF):
            assert PROFILES[profile.name] is profile
