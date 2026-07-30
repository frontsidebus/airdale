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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", help="STT backend to benchmark (deepgram, whisper)")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--pairs", type=Path, help="Score a reference/hypothesis TSV instead")
    parser.add_argument("--json", type=Path, help="Write full results here")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"),
                        help="Compare two saved --json runs")
    args = parser.parse_args()

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
