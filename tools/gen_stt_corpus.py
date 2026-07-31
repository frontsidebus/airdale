#!/usr/bin/env python3
"""Generate a synthetic STT evaluation corpus from the phrase list, via TTS.

**Read this before trusting the output.** Synthetic audio is not a substitute for
real recordings when selecting an STT backend. Clean TTS is studio-quality, so
every backend scores near-perfect on it and the gate stops discriminating. Worse,
synthetic speech is widely used as ASR training augmentation, so testing a cloud
backend on cloud TTS output can flatter it relative to a local model.

What this *is* good for:

* **CI regression.** Deterministic and offline: catches "the STT client broke",
  "normalization broke", "the factory wired the wrong backend".
* **SNR sweeps.** Absolute numbers stay untrustworthy, but *relative degradation*
  as noise increases is robust, and tells you which backend copes with a cockpit.

For backend selection, prefer real speech -- either a small set of your own
recordings or a public ATC corpus (ATCOSIM, ATCO2, UWB-ATCC), fed through
``stt_bench.py --paired-dir`` or ``--manifest``.

Usage
-----
    python3 tools/gen_stt_corpus.py --backend local            # Kokoro, offline
    python3 tools/gen_stt_corpus.py --snr 20 --profile headset
    python3 tools/gen_stt_corpus.py --snr-sweep 30,20,15,10,5

Output goes to ``data/eval/generated/<profile>/snr<N>/`` with a manifest per
condition, ready for ``stt_bench.py --manifest``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "orchestrator"))

from orchestrator.eval.audio_augment import PROFILES, augment  # noqa: E402
from orchestrator.eval.corpus import (  # noqa: E402
    TARGET_SAMPLE_RATE,
    load_phrase_corpus,
    read_wav_mono16k,
    write_wav_mono16k,
)

DEFAULT_CORPUS = REPO_ROOT / "data" / "eval" / "aviation_stt_corpus.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "eval" / "generated"


async def synthesize_all(backend: str, items: list, out_dir: Path) -> list[tuple[str, Path, str]]:
    """Synthesize every phrase once, clean. Returns (id, wav_path, transcript)."""
    from orchestrator.config import load_settings
    from orchestrator.tts import create_tts_client

    settings = load_settings()
    object.__setattr__(settings, "tts_backend", backend)
    if not settings.tts_configured:
        sys.exit(
            f"TTS backend {backend!r} is not configured. Check its credentials in .env, "
            "or use --backend local for offline Kokoro synthesis."
        )

    client = create_tts_client(settings)
    results: list[tuple[str, Path, str]] = []
    try:
        for item in items:
            audio_bytes = await client.synthesize(item.transcript)
            raw_path = out_dir / "clean" / f"{item.id}.wav"
            raw_path.parent.mkdir(parents=True, exist_ok=True)

            content_type = getattr(client, "audio_content_type", "")
            if "wav" in content_type or audio_bytes[:4] == b"RIFF":
                raw_path.write_bytes(audio_bytes)
                samples = read_wav_mono16k(raw_path)
                write_wav_mono16k(raw_path, samples)
            else:
                # MP3 and friends need decoding; ffmpeg is already required for
                # CLI playback, so reuse it rather than adding a decoder dep.
                samples = await _decode_via_ffmpeg(audio_bytes)
                if samples is None:
                    print(f"  ! {item.id}: could not decode {content_type}", file=sys.stderr)
                    continue
                write_wav_mono16k(raw_path, samples)

            results.append((item.id, raw_path, item.transcript))
            print(f"  synthesized {item.id}")
    finally:
        await client.aclose()
    return results


async def _decode_via_ffmpeg(audio_bytes: bytes):
    """Decode arbitrary encoded audio to mono float32 at 16 kHz."""
    import numpy as np

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", "pipe:0", "-f", "s16le", "-acodec", "pcm_s16le",
        "-ar", str(TARGET_SAMPLE_RATE), "-ac", "1", "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate(input=audio_bytes)
    if proc.returncode != 0 or not stdout:
        return None
    return np.frombuffer(stdout, dtype=np.int16).astype(np.float32) / 32768.0


def emit_condition(
    clean: list[tuple[str, Path, str]],
    out_dir: Path,
    profile: str,
    snr_db: float | None,
    seed: int,
) -> Path:
    """Write one degraded condition plus its manifest. Returns the manifest path."""
    label = "clean" if snr_db is None else f"snr{int(snr_db)}"
    condition_dir = out_dir / profile / label
    condition_dir.mkdir(parents=True, exist_ok=True)

    manifest = condition_dir / "manifest.tsv"
    with manifest.open("w", encoding="utf-8") as fh:
        fh.write(f"# synthetic corpus - profile={profile} snr={snr_db} seed={seed}\n")
        fh.write("# NOT a substitute for real speech; see tools/gen_stt_corpus.py\n")
        for phrase_id, wav_path, transcript in clean:
            samples = read_wav_mono16k(wav_path)
            degraded = augment(
                samples, TARGET_SAMPLE_RATE, profile=profile, snr_db=snr_db, seed=seed
            )
            target = condition_dir / f"{phrase_id}.wav"
            write_wav_mono16k(target, degraded)
            fh.write(f"{target.name}\t{transcript}\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--backend", default="local", help="TTS backend (default: local/Kokoro)")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--profile", default="headset", choices=sorted(PROFILES), help="Channel profile"
    )
    parser.add_argument("--snr", type=float, default=None, help="Single SNR in dB")
    parser.add_argument("--snr-sweep", help="Comma-separated SNRs, e.g. 30,20,15,10,5")
    parser.add_argument("--seed", type=int, default=0, help="Noise seed (reproducibility)")
    args = parser.parse_args()

    items = load_phrase_corpus(args.corpus)
    if not items:
        print(f"No phrases in {args.corpus}", file=sys.stderr)
        return 1

    print(f"Synthesizing {len(items)} phrases via TTS backend {args.backend!r}...")
    clean = asyncio.run(synthesize_all(args.backend, items, args.output))
    if not clean:
        print("Nothing synthesized.", file=sys.stderr)
        return 1

    if args.snr_sweep:
        snrs: list[float | None] = [float(s) for s in args.snr_sweep.split(",")]
    elif args.snr is not None:
        snrs = [args.snr]
    else:
        snrs = [None]

    print()
    for snr in snrs:
        manifest = emit_condition(clean, args.output, args.profile, snr, args.seed)
        label = "clean" if snr is None else f"{snr:g} dB SNR"
        print(f"  {label:>12}  ->  {manifest}")

    print(
        "\nScore with:\n"
        f"  python3 tools/stt_bench.py --backend whisper --manifest {args.output}/"
        f"{args.profile}/<condition>/manifest.tsv\n"
        "\nReminder: use these for CI regression and SNR curves, not for setting "
        "accuracy thresholds."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
