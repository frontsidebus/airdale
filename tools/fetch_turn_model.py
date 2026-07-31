#!/usr/bin/env python3
"""Pre-fetch the Smart Turn v3 model used for semantic end-of-turn detection.

Semantic turn detection is optional: without the model, MERLIN falls back to the
fixed-silence detector and voice input still works, just less responsively. Run
this once to enable it.

    python3 tools/fetch_turn_model.py            # download to the default cache
    python3 tools/fetch_turn_model.py --force    # re-download
    python3 tools/fetch_turn_model.py --path /some/where.onnx

Set MERLIN_TURN_MODEL_PATH to point the orchestrator at a non-default location.

Model: pipecat-ai/smart-turn-v3 (BSD-2-Clause), ~8 MB int8 ONNX.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "orchestrator"))

from orchestrator.turn.smart_turn import (  # noqa: E402
    MODEL_URL,
    SmartTurnDetector,
    default_model_path,
    fetch_model,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--path", type=Path, help="Destination (default: user cache)")
    parser.add_argument("--force", action="store_true", help="Re-download if already present")
    args = parser.parse_args()

    target = args.path or default_model_path()
    if target.is_file() and not args.force:
        print(f"Already present: {target} ({target.stat().st_size / 1e6:.1f} MB)")
    else:
        print(f"Downloading {MODEL_URL}\n         -> {target}")
        try:
            target = fetch_model(target, force=args.force)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Downloaded {target.stat().st_size / 1e6:.1f} MB")

    # Confirm the file actually loads and produces a prediction, rather than
    # just reporting bytes on disk.
    detector = SmartTurnDetector(model_path=target)
    if not detector.available:
        print(
            "error: model downloaded but failed to load. Is onnxruntime installed?",
            file=sys.stderr,
        )
        return 1

    import numpy as np

    decision = detector.evaluate(np.zeros(16000, dtype=np.float32), 16000, silence_ms=200)
    print(f"Verified: inference OK (silence -> p={decision.probability:.3f})")
    print("\nSemantic turn detection is enabled. Set TURN_DETECTOR=silence to disable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
