"""Export validated conversations as train/val JSONL splits with metadata."""

from __future__ import annotations

import json
import logging
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .config import DatasetConfig
from .format_openai import format_training_example
from .validate import validate_conversation

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """Rough token count estimate (~4 chars per token for English)."""
    return max(1, len(text) // 4)


def _count_message_tokens(messages: list[dict]) -> int:
    """Estimate total tokens across all messages in a conversation."""
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        if isinstance(content, str):
            total += _estimate_tokens(content)
        # Count tool call arguments
        for tc in msg.get("tool_calls", []):
            func = tc.get("function", {})
            total += _estimate_tokens(func.get("arguments", ""))
            total += _estimate_tokens(func.get("name", ""))
    return total


def export_dataset(config: DatasetConfig) -> dict:
    """Export validated conversations to train/val JSONL files.

    1. Load raw conversations from conversations_raw.jsonl
    2. Convert each to OpenAI format
    3. Validate and filter by quality score
    4. Shuffle deterministically
    5. Split 90/10 train/val
    6. Write train.jsonl, val.jsonl, metadata.json

    Returns metadata dict.
    """
    config.ensure_output_dir()
    raw_path = config.raw_conversations_path

    if not raw_path.exists():
        raise FileNotFoundError(
            f"Raw conversations not found at {raw_path}. "
            f"Run 'generate' first."
        )

    # ------------------------------------------------------------------
    # 1. Load raw conversations
    # ------------------------------------------------------------------
    raw_conversations: list[dict] = []
    with raw_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw_conversations.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Line %d: invalid JSON, skipping", line_num)

    logger.info("Loaded %d raw conversations", len(raw_conversations))

    # ------------------------------------------------------------------
    # 2. Convert to OpenAI format
    # ------------------------------------------------------------------
    converted: list[dict] = []
    for raw in raw_conversations:
        system_prompt = raw.get("system_prompt", "")
        anthropic_messages = raw.get("messages", [])
        scenario_id = raw.get("scenario_id", "unknown")
        phase = raw.get("phase")
        expected_tools = raw.get("expected_tools")

        example = format_training_example(system_prompt, anthropic_messages)
        example["scenario_id"] = scenario_id
        example["phase"] = phase
        example["expected_tools"] = expected_tools

        # Carry through metadata fields for distribution tracking
        example["category"] = raw.get("category")
        example["aircraft"] = raw.get("aircraft")
        example["weather"] = raw.get("weather")
        example["pilot_level"] = raw.get("pilot_level")

        converted.append(example)

    # ------------------------------------------------------------------
    # 3. Validate and filter
    # ------------------------------------------------------------------
    accepted: list[dict] = []
    filtered_count = 0

    for example in converted:
        result = validate_conversation(example)
        if result.score >= config.min_quality_score:
            example["quality_score"] = result.score
            accepted.append(example)
        else:
            filtered_count += 1
            logger.debug(
                "Filtered %s (score=%d): %s",
                example.get("scenario_id"),
                result.score,
                "; ".join(result.issues),
            )

    logger.info(
        "Validation: %d accepted, %d filtered (threshold=%d)",
        len(accepted),
        filtered_count,
        config.min_quality_score,
    )

    # ------------------------------------------------------------------
    # 4. Shuffle deterministically
    # ------------------------------------------------------------------
    rng = random.Random(config.random_seed)
    rng.shuffle(accepted)

    # ------------------------------------------------------------------
    # 5. Split train/val
    # ------------------------------------------------------------------
    split_idx = int(len(accepted) * config.train_split)
    train_set = accepted[:split_idx]
    val_set = accepted[split_idx:]

    # ------------------------------------------------------------------
    # 6. Write output files
    # ------------------------------------------------------------------
    def _write_jsonl(path: Path, examples: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as f:
            for ex in examples:
                # Only write the 'messages' key for training
                record = {"messages": ex["messages"]}
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    _write_jsonl(config.train_path, train_set)
    _write_jsonl(config.val_path, val_set)
    logger.info(
        "Wrote %d train examples to %s", len(train_set), config.train_path
    )
    logger.info(
        "Wrote %d val examples to %s", len(val_set), config.val_path
    )

    # ------------------------------------------------------------------
    # Build metadata
    # ------------------------------------------------------------------
    phase_dist = Counter(ex.get("phase") or "unknown" for ex in accepted)
    category_dist = Counter(ex.get("category") or "unknown" for ex in accepted)
    aircraft_dist = Counter(ex.get("aircraft") or "unknown" for ex in accepted)
    weather_dist = Counter(ex.get("weather") or "unknown" for ex in accepted)
    pilot_dist = Counter(ex.get("pilot_level") or "unknown" for ex in accepted)

    # Turns per conversation
    turns = [
        sum(1 for m in ex["messages"] if m.get("role") in ("user", "assistant"))
        for ex in accepted
    ]
    avg_turns = sum(turns) / len(turns) if turns else 0.0

    # Token estimates
    token_counts = [_count_message_tokens(ex["messages"]) for ex in accepted]
    avg_tokens = sum(token_counts) / len(token_counts) if token_counts else 0.0

    # Tool call frequency
    tool_freq: Counter = Counter()
    for ex in accepted:
        for msg in ex["messages"]:
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                name = func.get("name", "unknown")
                tool_freq[name] += 1

    # Quality score distribution (buckets of 10)
    quality_dist: dict[str, int] = {}
    for bucket_start in range(0, 101, 10):
        bucket_end = min(bucket_start + 9, 100)
        key = f"{bucket_start}-{bucket_end}"
        quality_dist[key] = sum(
            1
            for ex in accepted
            if bucket_start <= ex.get("quality_score", 0) <= bucket_end
        )

    metadata = {
        "total_conversations": len(accepted),
        "train_count": len(train_set),
        "val_count": len(val_set),
        "filtered_count": filtered_count,
        "distribution": {
            "phase": dict(phase_dist),
            "category": dict(category_dist),
            "aircraft": dict(aircraft_dist),
            "weather": dict(weather_dist),
            "pilot_level": dict(pilot_dist),
        },
        "avg_turns_per_conversation": round(avg_turns, 2),
        "avg_tokens_estimated": round(avg_tokens, 1),
        "tool_call_frequency": dict(tool_freq.most_common()),
        "quality_score_distribution": quality_dist,
        "generation_timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "model": config.model,
            "min_quality_score": config.min_quality_score,
            "train_split": config.train_split,
            "random_seed": config.random_seed,
        },
    }

    with config.metadata_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    logger.info("Wrote metadata to %s", config.metadata_path)

    return metadata
