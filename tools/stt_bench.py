#!/usr/bin/env python3
"""Benchmark an STT backend on aviation phraseology.

Gate for STT backend swaps (see `.planning/TECH-STACK-REVIEW.md` Step 2). Reports
aviation-weighted metrics rather than headline WER, because a backend can improve
its published WER while getting worse at the only thing that matters here --
hearing altitudes, squawk codes, and callsigns correctly.

Usage
-----
Score a backend against recorded audio::

    python3 tools/stt_bench.py --backend whisper
    python3 tools/stt_bench.py --backend deepgram --json results-deepgram.json

Compare two backends' saved runs::

    python3 tools/stt_bench.py --compare results-deepgram.json results-whisper.json

Score transcripts directly, no audio or services needed -- useful for validating
the metric itself or scoring transcripts produced elsewhere::

    python3 tools/stt_bench.py --pairs pairs.tsv

where ``pairs.tsv`` has one ``reference<TAB>hypothesis`` per line.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "orchestrator"))

from orchestrator.eval.aviation_wer import (  # noqa: E402
    AviationScore,
    score_corpus,
    score_transcript,
)

DEFAULT_CORPUS = REPO_ROOT / "data" / "eval" / "aviation_stt_corpus.yaml"


def load_corpus(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML is required: pip install pyyaml")
    with path.open() as fh:
        return yaml.safe_load(fh)


async def transcribe_items(backend: str, items: list) -> list[tuple[str, str, str]]:
    """Transcribe CorpusItems. Returns (id, reference, hypothesis)."""
    from orchestrator.config import load_settings
    from orchestrator.stt import create_stt_client

    settings = load_settings()
    object.__setattr__(settings, "stt_backend", backend)
    if not settings.stt_configured:
        sys.exit(
            f"STT backend {backend!r} is not configured. "
            "Check the relevant credentials in .env before benchmarking."
        )

    client = create_stt_client(settings)
    results: list[tuple[str, str, str]] = []
    skipped = 0
    try:
        for item in items:
            if not item.has_audio:
                skipped += 1
                continue
            result = await client.transcribe(item.audio_path.read_bytes())
            results.append((item.id, item.transcript, result.text))
    finally:
        await client.aclose()

    if skipped:
        print(
            f"  {skipped} item(s) skipped for missing audio.",
            file=sys.stderr,
        )
    return results


async def transcribe_all(backend: str, phrases: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Return (id, reference, hypothesis) for every phrase with usable audio."""
    from orchestrator.config import load_settings
    from orchestrator.stt import create_stt_client

    settings = load_settings()
    object.__setattr__(settings, "stt_backend", backend)
    if not settings.stt_configured:
        sys.exit(
            f"STT backend {backend!r} is not configured. "
            "Check the relevant credentials in .env before benchmarking."
        )

    client = create_stt_client(settings)
    results: list[tuple[str, str, str]] = []
    skipped = 0
    try:
        for phrase in phrases:
            audio_path = phrase.get("audio")
            if not audio_path:
                skipped += 1
                continue
            resolved = (REPO_ROOT / audio_path).resolve()
            if not resolved.is_file():
                print(f"  ! {phrase['id']}: audio not found at {resolved}", file=sys.stderr)
                skipped += 1
                continue
            result = await client.transcribe(resolved.read_bytes())
            results.append((phrase["id"], phrase["text"], result.text))
    finally:
        await client.aclose()

    if skipped:
        print(
            f"  {skipped} phrase(s) skipped for missing audio. "
            "Record them to make this a full gate.",
            file=sys.stderr,
        )
    return results


def report(
    label: str,
    rows: list[tuple[str, str, str]],
    phrases: list[dict[str, Any]],
    gates: dict[str, float],
) -> tuple[AviationScore, bool]:
    """Print a per-category report and return (overall score, gates_passed)."""
    by_id = {p["id"]: p for p in phrases}
    overall = score_corpus([(ref, hyp) for _pid, ref, hyp in rows])

    print(f"\n=== {label} ===")
    print(f"utterances scored: {len(rows)}")
    print(f"overall: {overall.summary()}")

    # Per-category breakdown makes a regression attributable.
    categories: dict[str, list[tuple[str, str]]] = {}
    for pid, ref, hyp in rows:
        category = by_id.get(pid, {}).get("category", "uncategorized")
        categories.setdefault(category, []).append((ref, hyp))

    if categories:
        print("\nby category:")
        for category in sorted(categories):
            score = score_corpus(categories[category])
            flag = "  <-- values lost" if score.value_recall < 1.0 else ""
            print(f"  {category:16} {score.summary()}{flag}")

    # Individual misses are what you act on.
    misses = [
        (pid, ref, hyp)
        for pid, ref, hyp in rows
        if score_transcript(ref, hyp).value_recall < 1.0
    ]
    if misses:
        print("\nutterances with lost values:")
        for pid, ref, hyp in misses:
            score = score_transcript(ref, hyp)
            print(f"  [{pid}] missed {score.missed_values}")
            print(f"      ref: {ref}")
            print(f"      hyp: {hyp}")

    passed = True
    if rows:
        print("\ngates:")
        checks = [
            ("value_recall", overall.value_recall, gates.get("value_recall_min", 0.98), "min"),
            ("cter", overall.cter, gates.get("cter_max", 0.05), "max"),
            ("wer", overall.wer, gates.get("wer_max", 0.15), "max"),
        ]
        for name, actual, threshold, direction in checks:
            ok = actual >= threshold if direction == "min" else actual <= threshold
            passed = passed and ok
            symbol = "PASS" if ok else "FAIL"
            print(f"  {symbol}  {name:14} {actual:7.2%}  ({direction} {threshold:.2%})")

    return overall, passed


def load_pairs(path: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" not in raw:
            sys.exit(f"{path}:{lineno}: expected reference<TAB>hypothesis")
        ref, hyp = raw.split("\t", 1)
        pairs.append((ref.strip(), hyp.strip()))
    return pairs


def snr_sweep(backend: str, manifests: list[Path]) -> int:
    """Score a backend across degradation conditions and print the curve.

    Absolute numbers on synthetic audio are not trustworthy, but the *shape* of
    the degradation is: a backend that holds value recall as SNR falls is the one
    that will survive a cockpit. Read the curve, not any single row.
    """
    from orchestrator.eval.corpus import load_manifest

    print(f"\n=== SNR sweep: {backend} ===")
    print(f"{'condition':>14}  {'WER':>8} {'CTER':>8} {'value-recall':>13}  {'n':>4}")
    rows: list[tuple[str, float]] = []
    for manifest in manifests:
        items = load_manifest(manifest)
        results = asyncio.run(transcribe_items(backend, items))
        if not results:
            print(f"{manifest.parent.name:>14}  (no audio)")
            continue
        score = score_corpus([(ref, hyp) for _pid, ref, hyp in results])
        print(
            f"{manifest.parent.name:>14}  {score.wer:7.2%} {score.cter:7.2%} "
            f"{score.value_recall:12.2%}  {len(results):4d}"
        )
        rows.append((manifest.parent.name, score.value_recall))

    if len(rows) >= 2:
        drop = rows[0][1] - rows[-1][1]
        print(
            f"\n  value recall falls {drop:.1%} from {rows[0][0]} to {rows[-1][0]}. "
            "Compare this drop across backends rather than any single score."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", help="STT backend to benchmark (deepgram, whisper)")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--pairs", type=Path, help="Score a reference/hypothesis TSV instead")
    parser.add_argument("--manifest", type=Path, help="Score a corpus manifest (audio<TAB>transcript)")
    parser.add_argument(
        "--paired-dir",
        type=Path,
        help="Score a directory of *.wav each beside a same-stem *.txt transcript. "
        "Use for external corpora (ATCOSIM, ATCO2, UWB-ATCC) you have obtained yourself.",
    )
    parser.add_argument(
        "--snr-sweep",
        nargs="+",
        type=Path,
        metavar="MANIFEST",
        help="Score across several manifests and print the degradation curve",
    )
    parser.add_argument("--json", type=Path, help="Write full results here")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"),
                        help="Compare two saved --json runs")
    args = parser.parse_args()

    if args.snr_sweep:
        if not args.backend:
            parser.error("--snr-sweep requires --backend")
        return snr_sweep(args.backend, args.snr_sweep)

    if args.manifest or args.paired_dir:
        if not args.backend:
            parser.error("--manifest/--paired-dir requires --backend")
        from orchestrator.eval.corpus import load_manifest, load_paired_directory

        if args.manifest:
            items = load_manifest(args.manifest)
            label = f"{args.backend} @ {args.manifest.parent.name}"
        else:
            items = load_paired_directory(args.paired_dir)
            label = f"{args.backend} @ {args.paired_dir.name}"
        if not items:
            print("No usable items found.", file=sys.stderr)
            return 1
        results = asyncio.run(transcribe_items(args.backend, items))
        if not results:
            print("No audio could be transcribed.", file=sys.stderr)
            return 1
        phrase_meta = [{"id": i.id, "category": i.category} for i in items]
        _overall, passed = report(label, results, phrase_meta, {})
        return 0 if passed else 1

    if args.compare:
        a, b = (json.loads(p.read_text()) for p in args.compare)
        print(f"\n{'metric':16} {'A':>10} {'B':>10}   delta (B-A)")
        for metric, better in (("value_recall", "higher"), ("cter", "lower"), ("wer", "lower")):
            av, bv = a["overall"][metric], b["overall"][metric]
            delta = bv - av
            improved = delta > 0 if better == "higher" else delta < 0
            marker = "better" if improved else ("same" if delta == 0 else "worse")
            print(f"{metric:16} {av:9.2%} {bv:9.2%}   {delta:+8.2%}  B is {marker}")
        print(f"\nA = {args.compare[0].name} ({a.get('label')})")
        print(f"B = {args.compare[1].name} ({b.get('label')})")
        return 0

    if args.pairs:
        pairs = load_pairs(args.pairs)
        overall = score_corpus(pairs)
        print(f"\n=== {args.pairs.name} ({len(pairs)} pairs) ===")
        print(overall.summary())
        if overall.missed_values:
            print(f"missed values: {overall.missed_values}")
        return 0

    if not args.backend:
        parser.error("one of --backend, --pairs, or --compare is required")

    corpus = load_corpus(args.corpus)
    phrases = corpus.get("phrases", [])
    gates = corpus.get("meta", {}).get("gates", {})

    rows = asyncio.run(transcribe_all(args.backend, phrases))
    if not rows:
        print(
            "\nNo audio available to score. Record clips and set `audio:` paths in "
            f"{args.corpus.name}, or use --pairs to score existing transcripts.",
            file=sys.stderr,
        )
        return 1

    overall, passed = report(f"backend: {args.backend}", rows, phrases, gates)

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "label": args.backend,
                    "overall": asdict(overall),
                    "utterances": [
                        {"id": pid, "reference": ref, "hypothesis": hyp}
                        for pid, ref, hyp in rows
                    ],
                },
                indent=2,
            )
        )
        print(f"\nwrote {args.json}")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
