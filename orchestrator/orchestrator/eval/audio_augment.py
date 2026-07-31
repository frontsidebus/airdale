"""Degrade clean audio to approximate cockpit and radio conditions.

Clean TTS audio is useless as an STT accuracy gate: every backend scores near
100% on it, so the gate passes everything. The interesting question is how each
backend *degrades* -- value recall against signal-to-noise ratio -- and that
requires deliberately damaged audio.

Absolute scores on synthetic audio remain untrustworthy (synthetic speech is
widely used as ASR training augmentation, which can flatter some backends over
others). Degradation *curves* are far more robust to that bias, which is why
``tools/stt_bench.py`` reports a sweep rather than a single synthetic number.

Filtering is FFT-based numpy rather than scipy: scipy is importable in this
environment but is not a declared dependency, and offline evaluation has no
realtime constraint that would justify an IIR design.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Fraction of peak RMS above which a frame counts as speech when measuring
#: signal power. Without this, leading and trailing silence deflates the
#: measured level and every SNR comes out wrong in the same direction.
_SPEECH_FRAME_FLOOR = 0.15
_FRAME_SAMPLES = 400


@dataclass(frozen=True)
class ChannelProfile:
    """A named degradation profile."""

    name: str
    low_hz: float
    high_hz: float
    #: Soft-clip threshold as a fraction of full scale; 1.0 disables clipping.
    clip_threshold: float
    description: str


#: Close-talk headset in a piston cockpit -- MERLIN's actual input channel.
HEADSET = ChannelProfile(
    name="headset",
    low_hz=100.0,
    high_hz=8000.0,
    clip_threshold=0.95,
    description="Close-talk headset, cockpit ambient",
)

#: VHF radio: narrower band, harder limiting. Relevant for ATC corpora and for
#: any future path where MERLIN hears radio rather than intercom.
VHF = ChannelProfile(
    name="vhf",
    low_hz=300.0,
    high_hz=3400.0,
    clip_threshold=0.8,
    description="VHF voice channel",
)

CLEAN = ChannelProfile(
    name="clean",
    low_hz=0.0,
    high_hz=0.0,  # 0 disables band-limiting
    clip_threshold=1.0,
    description="Unmodified",
)

PROFILES: dict[str, ChannelProfile] = {p.name: p for p in (CLEAN, HEADSET, VHF)}


def speech_rms(signal: np.ndarray) -> float:
    """RMS over speech-active frames only.

    Measuring across the whole clip would let silence pad the denominator and
    make every mix quieter than the requested SNR.
    """
    if signal.size == 0:
        return 0.0
    n_frames = max(1, signal.size // _FRAME_SAMPLES)
    usable = signal[: n_frames * _FRAME_SAMPLES].reshape(n_frames, _FRAME_SAMPLES)
    frame_rms = np.sqrt(np.mean(usable**2, axis=1))
    peak = frame_rms.max()
    if peak <= 0:
        return 0.0
    active = frame_rms[frame_rms >= peak * _SPEECH_FRAME_FLOOR]
    return float(np.sqrt(np.mean(active**2)))


def pink_noise(n_samples: int, rng: np.random.Generator) -> np.ndarray:
    """Pink (1/f) noise -- a reasonable stand-in for broadband cabin noise."""
    if n_samples <= 0:
        return np.zeros(0, dtype=np.float32)
    white = rng.standard_normal(n_samples)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n_samples)
    scaling = np.ones_like(freqs)
    scaling[1:] = 1.0 / np.sqrt(freqs[1:])
    scaling[0] = 0.0  # drop DC; it carries no audible energy and biases RMS
    shaped = np.fft.irfft(spectrum * scaling, n=n_samples)
    peak = np.abs(shaped).max()
    return (shaped / peak if peak > 0 else shaped).astype(np.float32)


def engine_noise(
    n_samples: int,
    sample_rate: int,
    rng: np.random.Generator,
    fundamental_hz: float = 90.0,
) -> np.ndarray:
    """Pink noise plus a low-frequency tonal component.

    A piston engine is not spectrally flat -- it has a prop/cylinder fundamental
    and harmonics. Broadband noise alone understates how much low-frequency
    energy sits under the speech.
    """
    if n_samples <= 0:
        return np.zeros(0, dtype=np.float32)
    noise = pink_noise(n_samples, rng)
    t = np.arange(n_samples) / sample_rate
    tonal = np.zeros(n_samples)
    for harmonic, weight in ((1, 1.0), (2, 0.5), (3, 0.25)):
        phase = rng.uniform(0, 2 * np.pi)
        tonal += weight * np.sin(2 * np.pi * fundamental_hz * harmonic * t + phase)
    tonal /= np.abs(tonal).max() or 1.0
    combined = 0.7 * noise + 0.3 * tonal
    peak = np.abs(combined).max()
    return (combined / peak if peak > 0 else combined).astype(np.float32)


def bandlimit(
    signal: np.ndarray,
    sample_rate: int,
    low_hz: float,
    high_hz: float,
    taper_hz: float = 50.0,
) -> np.ndarray:
    """Band-limit via FFT with cosine-tapered edges.

    The taper avoids the ringing a brick-wall cutoff would add -- artefacts an
    ASR model could plausibly react to, which would make the measurement about
    the filter rather than the channel.
    """
    if signal.size == 0 or (low_hz <= 0 and high_hz <= 0):
        return signal.astype(np.float32)

    spectrum = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(signal.size, d=1.0 / sample_rate)
    gain = np.ones_like(freqs)

    if low_hz > 0:
        gain *= np.clip((freqs - low_hz) / taper_hz + 1.0, 0.0, 1.0)
    if high_hz > 0:
        gain *= np.clip((high_hz - freqs) / taper_hz + 1.0, 0.0, 1.0)

    return np.fft.irfft(spectrum * gain, n=signal.size).astype(np.float32)


def soft_clip(signal: np.ndarray, threshold: float) -> np.ndarray:
    """Smoothly limit peaks, approximating mic or preamp overload."""
    if threshold >= 1.0 or signal.size == 0:
        return signal.astype(np.float32)
    return (threshold * np.tanh(signal / threshold)).astype(np.float32)


def mix_at_snr(
    signal: np.ndarray,
    noise: np.ndarray,
    snr_db: float,
) -> np.ndarray:
    """Add ``noise`` to ``signal`` scaled to hit ``snr_db``.

    SNR is measured against speech-active frames, so the requested ratio holds
    over the speech rather than over the whole clip.
    """
    if signal.size == 0:
        return signal.astype(np.float32)

    signal_rms = speech_rms(signal)
    noise_rms = float(np.sqrt(np.mean(noise**2)))
    if signal_rms <= 0 or noise_rms <= 0:
        return signal.astype(np.float32)

    target_noise_rms = signal_rms / (10 ** (snr_db / 20.0))
    return (signal + noise * (target_noise_rms / noise_rms)).astype(np.float32)


def augment(
    signal: np.ndarray,
    sample_rate: int,
    profile: str | ChannelProfile = "headset",
    snr_db: float | None = 20.0,
    seed: int = 0,
) -> np.ndarray:
    """Apply a channel profile and optional noise at a target SNR.

    Deterministic for a given ``seed``, so a benchmark run is reproducible and a
    backend comparison is not confounded by different noise draws.

    Args:
        signal: Clean mono audio.
        sample_rate: Sample rate of ``signal``.
        profile: Name from :data:`PROFILES`, or a :class:`ChannelProfile`.
        snr_db: Target SNR. ``None`` skips noise entirely.
        seed: Noise RNG seed.

    Raises:
        ValueError: If ``profile`` names an unknown profile.
    """
    if isinstance(profile, str):
        try:
            channel = PROFILES[profile]
        except KeyError:
            known = ", ".join(sorted(PROFILES))
            raise ValueError(
                f"Unknown channel profile {profile!r}. Expected one of {known}."
            ) from None
    else:
        channel = profile

    out = np.asarray(signal, dtype=np.float32).flatten()
    if out.size == 0:
        return out

    if snr_db is not None:
        rng = np.random.default_rng(seed)
        out = mix_at_snr(out, engine_noise(out.size, sample_rate, rng), snr_db)

    # Band-limit after mixing: the channel degrades signal and noise alike.
    out = bandlimit(out, sample_rate, channel.low_hz, channel.high_hz)
    out = soft_clip(out, channel.clip_threshold)

    # Keep headroom so downstream int16 conversion does not wrap.
    peak = float(np.abs(out).max())
    if peak > 0.99:
        out = out * (0.99 / peak)
    return out.astype(np.float32)
