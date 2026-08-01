"""Tests for audio preprocessing helpers and the turn-detection decode path.

The ffmpeg subprocess is always faked: these tests pin *what we ask ffmpeg for*
and *what we do with what it returns*, not ffmpeg itself.

The important property here is a negative one. ``decode_webm_to_samples`` must
not preprocess, because ``preprocess_audio`` trims trailing silence and trailing
silence is the signal the end-of-turn model reads. That is asserted both
structurally (the source does not mention ``preprocess_audio``) and behaviourally
(a decoded waveform with a silent tail keeps its tail), because either check
alone is easy to defeat by accident.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import numpy as np
import pytest
from orchestrator.audio_processing import (
    TARGET_SAMPLE_RATE,
    decode_webm_to_samples,
    preprocess_audio,
)

# ---------------------------------------------------------------------------
# ffmpeg subprocess fake
# ---------------------------------------------------------------------------


class _FakeProc:
    """Stand-in for the ffmpeg process returned by create_subprocess_exec."""

    def __init__(self, stdout: bytes = b"", returncode: int = 0, stderr: bytes = b"") -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.stdin_received: bytes | None = None

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:  # noqa: A002
        self.stdin_received = input
        return self._stdout, self._stderr


def _patch_ffmpeg(
    monkeypatch: pytest.MonkeyPatch,
    proc: _FakeProc,
    captured_argv: list[Any] | None = None,
) -> _FakeProc:
    """Replace asyncio.create_subprocess_exec with one returning ``proc``."""

    async def _fake_exec(*args: Any, **kwargs: Any) -> _FakeProc:
        if captured_argv is not None:
            captured_argv.extend(args)
        return proc

    # The helper calls ``asyncio.create_subprocess_exec`` through the module
    # attribute, so patching it here reaches the call site.
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    return proc


def _pcm16(samples: np.ndarray) -> bytes:
    """Encode float samples the way ffmpeg's s16le output would."""
    return (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


# ---------------------------------------------------------------------------
# decode_webm_to_samples
# ---------------------------------------------------------------------------


class TestDecodeWebmToSamples:
    async def test_successful_decode_returns_float32_in_range(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = np.sin(np.linspace(0, 40 * np.pi, 1600)).astype(np.float32) * 0.5
        _patch_ffmpeg(monkeypatch, _FakeProc(stdout=_pcm16(original)))

        samples = await decode_webm_to_samples(b"fake-webm")

        assert samples is not None
        assert samples.dtype == np.float32
        assert samples.size == 1600
        assert np.max(np.abs(samples)) <= 1.0
        np.testing.assert_allclose(samples, original, atol=1e-4)

    async def test_nonzero_return_code_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_ffmpeg(
            monkeypatch,
            _FakeProc(stdout=b"", returncode=1, stderr=b"Invalid data found when processing input"),
        )

        assert await decode_webm_to_samples(b"not-really-webm") is None

    async def test_empty_stdout_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_ffmpeg(monkeypatch, _FakeProc(stdout=b"", returncode=0))

        assert await decode_webm_to_samples(b"fake-webm") is None

    async def test_failure_never_returns_the_input_bytes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The caller needs an unambiguous failure signal, not a passthrough.

        ``convert_webm_to_wav_normalized`` returns the input bytes on failure,
        which would reach the detector as garbage rather than as "unavailable".
        """
        _patch_ffmpeg(monkeypatch, _FakeProc(stdout=b"", returncode=1, stderr=b"boom"))

        result = await decode_webm_to_samples(b"fake-webm")

        assert result is None
        assert not isinstance(result, bytes | np.ndarray)

    async def test_requests_16k_mono_s16le_from_ffmpeg(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """log_mel_spectrogram raises on any rate other than 16 kHz."""
        argv: list[Any] = []
        _patch_ffmpeg(monkeypatch, _FakeProc(stdout=_pcm16(np.zeros(800) + 0.1)), argv)

        await decode_webm_to_samples(b"fake-webm")

        assert argv[0] == "ffmpeg"
        assert argv[argv.index("-ar") + 1] == str(TARGET_SAMPLE_RATE) == "16000"
        assert argv[argv.index("-ac") + 1] == "1"
        assert argv[argv.index("-f") + 1] == "s16le"

    async def test_pipes_the_container_bytes_to_stdin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proc = _patch_ffmpeg(monkeypatch, _FakeProc(stdout=_pcm16(np.zeros(800) + 0.1)))

        await decode_webm_to_samples(b"\x1a\x45\xdf\xa3payload")

        assert proc.stdin_received == b"\x1a\x45\xdf\xa3payload"

    def test_source_does_not_preprocess(self) -> None:
        """Structural guard: preprocessing destroys the signal the model reads."""
        source = inspect.getsource(decode_webm_to_samples)
        body = source.split('"""')[-1]
        assert "preprocess_audio(" not in body
        assert "trim_silence(" not in body
        assert "normalize_audio(" not in body
        assert "apply_highpass_filter(" not in body

    async def test_trailing_silence_survives_the_decode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Behavioural counterpart to the structural guard.

        Trailing silence is what the end-of-turn model judges. ``preprocess_audio``
        would strip it; this path must not.
        """
        speech = np.sin(np.linspace(0, 60 * np.pi, 8000)).astype(np.float32) * 0.6
        tail = np.zeros(TARGET_SAMPLE_RATE, dtype=np.float32)  # 1 s of silence
        original = np.concatenate([speech, tail])
        _patch_ffmpeg(monkeypatch, _FakeProc(stdout=_pcm16(original)))

        samples = await decode_webm_to_samples(b"fake-webm")

        assert samples is not None
        assert samples.size == original.size
        assert np.max(np.abs(samples[-TARGET_SAMPLE_RATE:])) < 1e-3
        # And confirm the contrast: the transcribe path would have eaten the tail.
        trimmed = preprocess_audio(original.copy(), TARGET_SAMPLE_RATE)
        assert trimmed.size < original.size

    async def test_does_not_truncate_to_eight_seconds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """truncate_or_pad inside the detector already keeps the last 8 s."""
        long_audio = np.zeros(TARGET_SAMPLE_RATE * 12, dtype=np.float32) + 0.2
        _patch_ffmpeg(monkeypatch, _FakeProc(stdout=_pcm16(long_audio)))

        samples = await decode_webm_to_samples(b"fake-webm")

        assert samples is not None
        assert samples.size == TARGET_SAMPLE_RATE * 12


# ---------------------------------------------------------------------------
# preprocess_audio -- the contrasting path, pinned so the contrast stays real
# ---------------------------------------------------------------------------


class TestPreprocessAudio:
    def test_trims_trailing_silence(self) -> None:
        speech = np.sin(np.linspace(0, 200 * np.pi, 16000)).astype(np.float32) * 0.6
        padded = np.concatenate([speech, np.zeros(16000, dtype=np.float32)])

        processed = preprocess_audio(padded, TARGET_SAMPLE_RATE)

        assert processed.size < padded.size

    def test_empty_input_is_returned_unchanged(self) -> None:
        empty = np.array([], dtype=np.float32)
        assert preprocess_audio(empty, TARGET_SAMPLE_RATE).size == 0
