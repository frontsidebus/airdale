"""Whisper-compatible log-mel spectrogram, implemented in numpy.

The Smart Turn ONNX model takes ``input_features`` of shape ``[batch, 80, 800]``
-- Whisper log-mel features, not raw audio. The upstream reference implementation
produces them with ``transformers.WhisperFeatureExtractor``, but pulling in
``transformers`` (and transitively torch) to compute a mel spectrogram would be a
disproportionate dependency for this project.

This module reimplements exactly what ``WhisperFeatureExtractor(chunk_length=8)``
produces with ``do_normalize=True``, using only numpy, which is already a
dependency. Correctness is not assumed: ``tests/test_turn_features.py`` pins the
output against golden vectors captured from the reference extractor, and the
implementation was verified elementwise against it to < 1e-4 across noise,
silence, tones, chirps, and short inputs.

If you change anything here, re-run that verification. A silent divergence would
not raise -- it would just make turn predictions quietly wrong.
"""

from __future__ import annotations

import numpy as np

N_FFT = 400
HOP_LENGTH = 160
N_MELS = 80
SAMPLE_RATE = 16000
CHUNK_SECONDS = 8
#: 8 s at 16 kHz with hop 160 yields 800 frames, matching the ONNX input shape.
N_SAMPLES = CHUNK_SECONDS * SAMPLE_RATE
N_FRAMES = N_SAMPLES // HOP_LENGTH

_EPS = 1e-10


def _hz_to_mel_slaney(freq: np.ndarray) -> np.ndarray:
    """Slaney-scale Hz -> mel, matching ``mel_scale="slaney"``."""
    f_min, f_sp = 0.0, 200.0 / 3.0
    mels = (freq - f_min) / f_sp
    min_log_hz = 1000.0
    min_log_mel = (min_log_hz - f_min) / f_sp
    logstep = np.log(6.4) / 27.0
    log_region = freq >= min_log_hz
    mels[log_region] = min_log_mel + np.log(freq[log_region] / min_log_hz) / logstep
    return mels


def _mel_to_hz_slaney(mels: np.ndarray) -> np.ndarray:
    """Slaney-scale mel -> Hz."""
    f_min, f_sp = 0.0, 200.0 / 3.0
    freq = f_min + f_sp * mels
    min_log_hz = 1000.0
    min_log_mel = (min_log_hz - f_min) / f_sp
    logstep = np.log(6.4) / 27.0
    log_region = mels >= min_log_mel
    freq[log_region] = min_log_hz * np.exp(logstep * (mels[log_region] - min_log_mel))
    return freq


def mel_filter_bank() -> np.ndarray:
    """Triangular mel filterbank, slaney-normalized. Shape ``(80, 201)``."""
    num_frequency_bins = N_FFT // 2 + 1
    fft_freqs = np.linspace(0, SAMPLE_RATE / 2, num_frequency_bins)

    mel_min = _hz_to_mel_slaney(np.array([0.0]))[0]
    mel_max = _hz_to_mel_slaney(np.array([SAMPLE_RATE / 2.0]))[0]
    mel_points = np.linspace(mel_min, mel_max, N_MELS + 2)
    filter_freqs = _mel_to_hz_slaney(mel_points)

    # Triangles: rising edge from filter_freqs[i] to [i+1], falling to [i+2].
    filter_diff = np.diff(filter_freqs)
    slopes = filter_freqs[np.newaxis, :] - fft_freqs[:, np.newaxis]
    down_slopes = -slopes[:, :-2] / filter_diff[:-1]
    up_slopes = slopes[:, 2:] / filter_diff[1:]
    filters = np.maximum(np.zeros(1), np.minimum(down_slopes, up_slopes))

    # Slaney normalization: equal area per filter rather than equal peak.
    enorm = 2.0 / (filter_freqs[2 : N_MELS + 2] - filter_freqs[:N_MELS])
    filters *= enorm[np.newaxis, :]
    return filters.T


def _prepare_waveform(audio: np.ndarray, n_samples: int = N_SAMPLES) -> np.ndarray:
    """Fit audio to the window and normalize it the way the reference does.

    Ordering matters and is easy to get subtly wrong: statistics come from the
    *real* audio only, the whole vector is scaled by them, and the padding region
    is then zeroed. Normalizing over the padded vector instead diverges by ~0.64
    absolute -- enough to change predictions, not enough to look broken.
    """
    real = truncate_or_pad(audio, n_samples)
    length = min(int(np.asarray(audio).size), n_samples)
    if length <= 0:
        return real

    segment = real[:length]
    normed = (real - segment.mean()) / np.sqrt(segment.var() + 1e-7)
    if length < n_samples:
        normed[length:] = 0.0
    return normed.astype(np.float32)


def truncate_or_pad(audio: np.ndarray, n_samples: int = N_SAMPLES) -> np.ndarray:
    """Fit audio to the 8 s window: keep the last samples, right-pad when short.

    Long audio is truncated from the *front* -- the model judges whether the most
    recent speech has ended, so the end of the utterance is what matters.

    Short audio is padded on the *right*.

    .. note::
       Upstream's README states that short input should be left-padded "such that
       the audio data is at the end of the input vector". Its shipped
       ``inference.py`` does the opposite: it calls ``WhisperFeatureExtractor``
       with ``padding="max_length"``, which right-pads. We match the executable
       reference, not the prose, since that is the path the model is actually
       used through. Verified elementwise against that extractor -- left-padding
       diverges by ~2.15 absolute, which is not a rounding difference.
    """
    audio = np.asarray(audio, dtype=np.float32).flatten()
    if audio.shape[0] >= n_samples:
        return audio[-n_samples:]
    return np.pad(audio, (0, n_samples - audio.shape[0]))


def log_mel_spectrogram(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Return Whisper log-mel features of shape ``(80, 800)``.

    Args:
        audio: Mono waveform. Truncated or padded to an 8 s window.
        sample_rate: Must be 16 kHz; the mel filterbank is precomputed for it.

    Raises:
        ValueError: If ``sample_rate`` is not 16 kHz.
    """
    if sample_rate != SAMPLE_RATE:
        raise ValueError(
            f"Smart Turn features require {SAMPLE_RATE} Hz audio, got {sample_rate}. "
            "Resample before calling."
        )

    waveform = _prepare_waveform(audio)

    # Periodic Hann, matching the reference implementation's window.
    window = np.hanning(N_FFT + 1)[:-1].astype(np.float64)

    # Centered STFT: reflect-pad by n_fft//2 so frame k is centred on sample k*hop.
    padded = np.pad(waveform.astype(np.float64), N_FFT // 2, mode="reflect")
    shape = (N_FRAMES + 1, N_FFT)
    strides = (padded.strides[0] * HOP_LENGTH, padded.strides[0])
    frames = np.lib.stride_tricks.as_strided(padded, shape=shape, strides=strides)

    spectrum = np.fft.rfft(frames * window, n=N_FFT, axis=-1)
    # Drop the final frame: it extends past the signal and Whisper discards it.
    magnitudes = (np.abs(spectrum[:-1]) ** 2).T

    mel_spec = mel_filter_bank() @ magnitudes

    log_spec = np.log10(np.maximum(mel_spec, _EPS))
    # Clamp the dynamic range to 8 decades below the peak, then map to ~[-1, 1].
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    log_spec = (log_spec + 4.0) / 4.0
    return log_spec.astype(np.float32)
