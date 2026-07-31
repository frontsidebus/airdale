"""Loading evaluation corpora from disk.

Three sources, in increasing order of how much you should trust their absolute
numbers:

``synthetic``
    TTS output, optionally degraded (see :mod:`.audio_augment`). Reproducible and
    free. Good for CI regression and SNR sweeps; do **not** set thresholds from
    it.

``manifest``
    A TSV of ``audio_path<TAB>transcript``. The general escape hatch -- anything
    can be converted into one.

``paired directory``
    A directory of ``*.wav`` each beside a ``*.txt`` holding its transcript. The
    convention most public speech corpora either use or can be trivially
    converted to.

Public ATC corpora (ATCOSIM, ATCO2, UWB-ATCC) are deliberately **not**
auto-downloaded. Their licence terms are not uniformly stated -- ATCOSIM's
distribution page advertises free-of-charge access without publishing the licence
text, and UWB-ATCC is CC BY-NC-SA. Fetching them silently on a user's behalf
would be presumptuous about terms this project has not verified. Obtain them
yourself, then point the loader at the result.
"""

from __future__ import annotations

import csv
import logging
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000


@dataclass(frozen=True)
class CorpusItem:
    """One reference utterance."""

    id: str
    transcript: str
    audio_path: Path | None = None
    category: str = "uncategorized"

    @property
    def has_audio(self) -> bool:
        return self.audio_path is not None and self.audio_path.is_file()


def read_wav_mono16k(path: Path) -> np.ndarray:
    """Read a WAV as mono float32 at 16 kHz.

    Handles the common cases without pulling in soundfile or librosa: 8/16/32-bit
    PCM, mono or multi-channel, any sample rate. Resampling is linear
    interpolation -- adequate for downsampling speech to 16 kHz, and notably
    ATCOSIM ships at 32 kHz, an exact 2:1 ratio.

    Raises:
        ValueError: If the file uses an unsupported sample width.
    """
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    dtype_for_width = {1: np.uint8, 2: np.int16, 4: np.int32}
    if width not in dtype_for_width:
        raise ValueError(f"{path}: unsupported sample width {width * 8} bits")

    samples = np.frombuffer(frames, dtype=dtype_for_width[width]).astype(np.float32)
    if width == 1:  # 8-bit PCM is unsigned, centred on 128
        samples = (samples - 128.0) / 128.0
    else:
        samples /= float(2 ** (width * 8 - 1))

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    if rate != TARGET_SAMPLE_RATE:
        duration = samples.size / rate
        target_n = int(duration * TARGET_SAMPLE_RATE)
        if target_n <= 0:
            return np.zeros(0, dtype=np.float32)
        samples = np.interp(
            np.linspace(0, samples.size - 1, target_n),
            np.arange(samples.size),
            samples,
        ).astype(np.float32)

    return samples.astype(np.float32)


def write_wav_mono16k(path: Path, samples: np.ndarray) -> None:
    """Write mono float32 audio as 16-bit PCM at 16 kHz."""
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(TARGET_SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())


def load_phrase_corpus(path: Path) -> list[CorpusItem]:
    """Load the project's YAML phrase corpus."""
    try:
        import yaml
    except ImportError:  # pragma: no cover - environment-dependent
        raise RuntimeError("PyYAML is required to read the phrase corpus") from None

    with path.open() as fh:
        data = yaml.safe_load(fh)

    items: list[CorpusItem] = []
    for phrase in data.get("phrases", []):
        audio = phrase.get("audio")
        items.append(
            CorpusItem(
                id=phrase["id"],
                transcript=phrase["text"],
                audio_path=(path.parent.parent.parent / audio) if audio else None,
                category=phrase.get("category", "uncategorized"),
            )
        )
    return items


def load_manifest(path: Path, category: str = "manifest") -> list[CorpusItem]:
    """Load a TSV of ``audio_path<TAB>transcript``.

    Paths are resolved relative to the manifest's own directory, so a corpus
    directory stays portable.

    Raises:
        ValueError: If a non-comment line has no tab separator.
    """
    items: list[CorpusItem] = []
    with path.open(newline="") as fh:
        for lineno, row in enumerate(csv.reader(fh, delimiter="\t"), start=1):
            if not row or row[0].lstrip().startswith("#"):
                continue
            if len(row) < 2:
                raise ValueError(f"{path}:{lineno}: expected audio_path<TAB>transcript")
            audio_path = (path.parent / row[0].strip()).resolve()
            items.append(
                CorpusItem(
                    id=Path(row[0]).stem,
                    transcript=row[1].strip(),
                    audio_path=audio_path,
                    category=category,
                )
            )
    return items


def load_paired_directory(
    directory: Path,
    category: str = "external",
    transcript_suffix: str = ".txt",
) -> list[CorpusItem]:
    """Load ``*.wav`` files each paired with a same-stem transcript file.

    Recurses, so nested corpus layouts work. Audio without a matching transcript
    is skipped with a warning rather than silently dropped -- a corpus that
    half-loads should be visible, not quietly smaller.
    """
    items: list[CorpusItem] = []
    missing = 0
    for wav_path in sorted(directory.rglob("*.wav")):
        transcript_path = wav_path.with_suffix(transcript_suffix)
        if not transcript_path.is_file():
            missing += 1
            continue
        transcript = transcript_path.read_text(encoding="utf-8", errors="replace").strip()
        if not transcript:
            missing += 1
            continue
        items.append(
            CorpusItem(
                id=str(wav_path.relative_to(directory).with_suffix("")),
                transcript=transcript,
                audio_path=wav_path,
                category=category,
            )
        )
    if missing:
        logger.warning(
            "%d audio file(s) under %s had no usable %s transcript and were skipped",
            missing,
            directory,
            transcript_suffix,
        )
    return items


def iter_with_audio(items: list[CorpusItem]) -> Iterator[CorpusItem]:
    """Yield only items whose audio actually exists on disk."""
    for item in items:
        if item.has_audio:
            yield item
