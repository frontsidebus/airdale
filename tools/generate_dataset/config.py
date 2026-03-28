"""Configuration for the dataset generation pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Project root (airdale/)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class DatasetConfig:
    """Settings for the dataset generation pipeline."""

    # Anthropic API
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "")
    )
    model: str = "claude-sonnet-4-20250514"

    # Generation parameters
    concurrency: int = 8
    max_retries: int = 3
    target_conversations: int = 2500

    # Output paths
    output_dir: Path = field(default_factory=lambda: _PROJECT_ROOT / "data" / "finetune")
    airport_db_path: Path = field(default_factory=lambda: _PROJECT_ROOT / "data" / "airports.db")
    checklists_dir: Path = field(default_factory=lambda: _PROJECT_ROOT / "data" / "checklists")
    prompts_dir: Path = field(default_factory=lambda: _PROJECT_ROOT / "data" / "prompts")

    # Quality & splitting
    min_quality_score: int = 60
    train_split: float = 0.9
    random_seed: int = 42

    # Distribution targets
    normal_pct: float = 0.60
    abnormal_pct: float = 0.25
    emergency_pct: float = 0.15

    @property
    def scenarios_path(self) -> Path:
        return self.output_dir / "scenarios.jsonl"

    @property
    def raw_conversations_path(self) -> Path:
        return self.output_dir / "conversations_raw.jsonl"

    @property
    def train_path(self) -> Path:
        return self.output_dir / "train.jsonl"

    @property
    def val_path(self) -> Path:
        return self.output_dir / "val.jsonl"

    @property
    def metadata_path(self) -> Path:
        return self.output_dir / "metadata.json"

    def ensure_output_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
