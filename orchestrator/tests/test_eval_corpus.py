"""Tests for evaluation corpus loading and WAV I/O.

The WAV reader exists so external corpora can be ingested without adding
soundfile or librosa. It therefore has to handle what real corpora actually
ship: differing bit depths, stereo, and non-16 kHz rates (ATCOSIM is 32 kHz).
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest
from orchestrator.eval.corpus import (
    TARGET_SAMPLE_RATE,
    CorpusItem,
    iter_with_audio,
    load_manifest,
    load_paired_directory,
    read_wav_mono16k,
    write_wav_mono16k,
)


def _write_raw_wav(
    path: Path,
    samples: np.ndarray,
    sample_rate: int = TARGET_SAMPLE_RATE,
    channels: int = 1,
    width: int = 2,
) -> None:
    """Write a WAV with arbitrary parameters, to exercise the reader."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if width == 2:
        pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    elif width == 4:
        pcm = (np.clip(samples, -1, 1) * 2147483647).astype(np.int32)
    elif width == 1:
        pcm = ((np.clip(samples, -1, 1) * 127) + 128).astype(np.uint8)
    else:
        raise AssertionError(width)
    if channels > 1:
        pcm = np.repeat(pcm[:, None], channels, axis=1).flatten()
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def _tone(n: int = TARGET_SAMPLE_RATE, freq: float = 440.0) -> np.ndarray:
    return (np.sin(2 * np.pi * freq * np.arange(n) / TARGET_SAMPLE_RATE) * 0.5).astype(np.float32)


class TestWavRoundTrip:
    def test_write_then_read_preserves_signal(self, tmp_path: Path) -> None:
        original = _tone()
        path = tmp_path / "a.wav"
        write_wav_mono16k(path, original)
        assert np.allclose(read_wav_mono16k(path), original, atol=1e-4)

    def test_written_file_has_expected_header(self, tmp_path: Path) -> None:
        path = tmp_path / "a.wav"
        write_wav_mono16k(path, _tone())
        with wave.open(str(path), "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == 2
            assert wav.getframerate() == TARGET_SAMPLE_RATE

    def test_out_of_range_input_is_clipped_not_wrapped(self, tmp_path: Path) -> None:
        """Without clipping, float overflow wraps to the opposite sign."""
        path = tmp_path / "loud.wav"
        write_wav_mono16k(path, np.array([3.0, -3.0, 0.0], dtype=np.float32))
        read_back = read_wav_mono16k(path)
        assert read_back[0] > 0.9
        assert read_back[1] < -0.9


class TestWavReaderCompatibility:
    @pytest.mark.parametrize("width", [1, 2, 4])
    def test_supported_bit_depths(self, tmp_path: Path, width: int) -> None:
        path = tmp_path / f"w{width}.wav"
        _write_raw_wav(path, _tone(1000), width=width)
        samples = read_wav_mono16k(path)
        assert samples.size == 1000
        assert samples.dtype == np.float32
        assert np.abs(samples).max() > 0.3

    def test_stereo_is_downmixed(self, tmp_path: Path) -> None:
        path = tmp_path / "stereo.wav"
        _write_raw_wav(path, _tone(1000), channels=2)
        assert read_wav_mono16k(path).size == 1000

    def test_resamples_to_16k(self, tmp_path: Path) -> None:
        """ATCOSIM ships at 32 kHz; the reader must normalize rate."""
        path = tmp_path / "32k.wav"
        n = 32000  # 1 second at 32 kHz
        _write_raw_wav(path, np.zeros(n, dtype=np.float32), sample_rate=32000)
        assert read_wav_mono16k(path).size == pytest.approx(TARGET_SAMPLE_RATE, abs=2)

    def test_resampling_preserves_a_tone(self, tmp_path: Path) -> None:
        """Downsampling must keep the dominant frequency, not alias it away."""
        path = tmp_path / "tone48k.wav"
        sr = 48000
        t = np.arange(sr) / sr
        _write_raw_wav(path, np.sin(2 * np.pi * 440 * t).astype(np.float32), sample_rate=sr)
        samples = read_wav_mono16k(path)
        spectrum = np.abs(np.fft.rfft(samples))
        peak_hz = np.fft.rfftfreq(samples.size, 1 / TARGET_SAMPLE_RATE)[spectrum.argmax()]
        assert peak_hz == pytest.approx(440, abs=5)

    def test_unsupported_width_is_rejected_clearly(self, tmp_path: Path) -> None:
        path = tmp_path / "odd.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(3)  # 24-bit
            wav.setframerate(TARGET_SAMPLE_RATE)
            wav.writeframes(b"\x00" * 300)
        with pytest.raises(ValueError, match="unsupported sample width"):
            read_wav_mono16k(path)


class TestManifest:
    def test_loads_paths_relative_to_the_manifest(self, tmp_path: Path) -> None:
        write_wav_mono16k(tmp_path / "one.wav", _tone(800))
        manifest = tmp_path / "manifest.tsv"
        manifest.write_text("one.wav\tcleared for takeoff\n")

        items = load_manifest(manifest)
        assert len(items) == 1
        assert items[0].transcript == "cleared for takeoff"
        assert items[0].has_audio is True

    def test_skips_comments_and_blank_lines(self, tmp_path: Path) -> None:
        write_wav_mono16k(tmp_path / "a.wav", _tone(800))
        manifest = tmp_path / "m.tsv"
        manifest.write_text("# a comment\n\na.wav\thello\n")
        assert len(load_manifest(manifest)) == 1

    def test_malformed_line_names_the_location(self, tmp_path: Path) -> None:
        manifest = tmp_path / "m.tsv"
        manifest.write_text("no-tab-here\n")
        with pytest.raises(ValueError, match=r"m\.tsv:1"):
            load_manifest(manifest)


class TestPairedDirectory:
    def test_pairs_wav_with_same_stem_txt(self, tmp_path: Path) -> None:
        write_wav_mono16k(tmp_path / "utt1.wav", _tone(800))
        (tmp_path / "utt1.txt").write_text("squawk seven seven zero zero")
        items = load_paired_directory(tmp_path)
        assert len(items) == 1
        assert items[0].transcript == "squawk seven seven zero zero"

    def test_recurses_into_subdirectories(self, tmp_path: Path) -> None:
        nested = tmp_path / "session01" / "spk3"
        write_wav_mono16k(nested / "a.wav", _tone(800))
        (nested / "a.txt").write_text("descend and maintain")
        assert len(load_paired_directory(tmp_path)) == 1

    def test_audio_without_transcript_is_skipped_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A half-loading corpus must be visible, not quietly smaller."""
        write_wav_mono16k(tmp_path / "orphan.wav", _tone(800))
        write_wav_mono16k(tmp_path / "paired.wav", _tone(800))
        (tmp_path / "paired.txt").write_text("roger")

        with caplog.at_level("WARNING"):
            items = load_paired_directory(tmp_path)
        assert len(items) == 1
        assert "1 audio file(s)" in caplog.text

    def test_empty_transcript_counts_as_missing(self, tmp_path: Path) -> None:
        write_wav_mono16k(tmp_path / "blank.wav", _tone(800))
        (tmp_path / "blank.txt").write_text("   ")
        assert load_paired_directory(tmp_path) == []

    def test_empty_directory(self, tmp_path: Path) -> None:
        assert load_paired_directory(tmp_path) == []


class TestCorpusItem:
    def test_has_audio_is_false_without_a_path(self) -> None:
        assert CorpusItem(id="x", transcript="y").has_audio is False

    def test_has_audio_is_false_for_a_missing_file(self, tmp_path: Path) -> None:
        item = CorpusItem(id="x", transcript="y", audio_path=tmp_path / "nope.wav")
        assert item.has_audio is False

    def test_iter_with_audio_filters(self, tmp_path: Path) -> None:
        write_wav_mono16k(tmp_path / "real.wav", _tone(800))
        items = [
            CorpusItem(id="real", transcript="a", audio_path=tmp_path / "real.wav"),
            CorpusItem(id="absent", transcript="b", audio_path=tmp_path / "absent.wav"),
            CorpusItem(id="none", transcript="c"),
        ]
        assert [i.id for i in iter_with_audio(items)] == ["real"]
