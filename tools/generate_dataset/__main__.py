"""CLI for the MERLIN fine-tuning dataset generation pipeline.

Usage:
    python -m generate_dataset scenarios    # Export expanded scenario templates
    python -m generate_dataset generate     # Generate conversations via Claude API
    python -m generate_dataset validate     # Validate generated conversations
    python -m generate_dataset export       # Export train/val splits
    python -m generate_dataset all          # Run full pipeline
    python -m generate_dataset stats        # Print dataset statistics
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import DatasetConfig

logger = logging.getLogger("generate_dataset")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_scenarios(config: DatasetConfig, args: argparse.Namespace) -> None:
    """Export expanded scenario templates to JSONL."""
    from .scenarios import SCENARIO_TEMPLATES

    config.ensure_output_dir()

    count = 0
    with config.scenarios_path.open("w", encoding="utf-8") as f:
        for template in SCENARIO_TEMPLATES:
            # Expand across variable axes
            aircraft_list = template.aircraft_types or [
                "Cessna 172 Skyhawk",
                "Piper PA-28 Cherokee",
                "Cirrus SR22",
                "Beechcraft King Air 350",
                "Cessna Citation CJ4",
            ]
            for aircraft in aircraft_list:
                for weather in template.weather_conditions:
                    for pilot in template.pilot_levels:
                        scenario = {
                            "scenario_id": f"{template.id}__{aircraft.replace(' ', '_')}__{weather}__{pilot}",
                            "template_id": template.id,
                            "phase": template.phase,
                            "category": template.category,
                            "description": template.description,
                            "user_prompts": template.user_prompts,
                            "expected_tools": template.expected_tools,
                            "aircraft": aircraft,
                            "weather": weather,
                            "pilot_level": pilot,
                            "tags": template.tags,
                        }
                        f.write(json.dumps(scenario, ensure_ascii=False) + "\n")
                        count += 1

    logger.info("Exported %d expanded scenarios to %s", count, config.scenarios_path)


def cmd_generate(config: DatasetConfig, args: argparse.Namespace) -> None:
    """Generate conversations via the Claude API.

    This is a placeholder that logs instructions. The actual generation
    requires an async implementation with the Anthropic client, which
    lives in the generate module.
    """
    limit = args.limit
    resume = args.resume

    # Check for scenarios file
    if not config.scenarios_path.exists():
        logger.error(
            "Scenarios file not found at %s. Run 'scenarios' first.",
            config.scenarios_path,
        )
        sys.exit(1)

    # Count scenarios
    with config.scenarios_path.open("r", encoding="utf-8") as f:
        scenario_count = sum(1 for line in f if line.strip())

    if limit:
        scenario_count = min(scenario_count, limit)

    # Check for resume state
    already_done = 0
    if resume and config.raw_conversations_path.exists():
        with config.raw_conversations_path.open("r", encoding="utf-8") as f:
            already_done = sum(1 for line in f if line.strip())
        logger.info("Resuming: %d conversations already generated", already_done)

    remaining = scenario_count - already_done
    if remaining <= 0:
        logger.info("All %d conversations already generated", scenario_count)
        return

    logger.info(
        "Generating %d conversations (limit=%s, resume=%s)",
        remaining,
        limit,
        resume,
    )

    # Import and run the generation module
    try:
        from .generate import run_generation

        run_generation(config, limit=limit, resume=resume)
    except ImportError:
        logger.error(
            "Generation module not found. Create generate_dataset/generate.py "
            "with a run_generation(config, limit, resume) function."
        )
        sys.exit(1)


def cmd_validate(config: DatasetConfig, args: argparse.Namespace) -> None:
    """Run quality validation on generated conversations."""
    from .validate import validate_dataset

    if not config.raw_conversations_path.exists():
        logger.error(
            "Raw conversations not found at %s. Run 'generate' first.",
            config.raw_conversations_path,
        )
        sys.exit(1)

    summary = validate_dataset(config.raw_conversations_path)

    print(f"\n{'='*60}")
    print(f"  Validation Summary")
    print(f"{'='*60}")
    print(f"  Total:      {summary['total']}")
    print(f"  Passed:     {summary['passed']}")
    print(f"  Failed:     {summary['failed']}")
    print(f"  Pass rate:  {summary['pass_rate']*100:.1f}%")
    print(f"  Avg score:  {summary['avg_score']:.1f}")
    print()

    if summary["common_issues"]:
        print("  Top issues:")
        for issue, count in summary["common_issues"]:
            print(f"    - {issue}: {count}")
    print()

    print("  Score distribution:")
    for bucket, count in sorted(summary["score_distribution"].items()):
        bar = "#" * min(count, 50)
        print(f"    {bucket:>7}: {count:>4}  {bar}")
    print(f"{'='*60}\n")


def cmd_export(config: DatasetConfig, args: argparse.Namespace) -> None:
    """Export validated conversations as train/val splits."""
    from .export import export_dataset

    metadata = export_dataset(config)

    print(f"\n{'='*60}")
    print(f"  Export Summary")
    print(f"{'='*60}")
    print(f"  Total accepted: {metadata['total_conversations']}")
    print(f"  Train:          {metadata['train_count']}")
    print(f"  Val:            {metadata['val_count']}")
    print(f"  Filtered:       {metadata['filtered_count']}")
    print(f"  Avg turns:      {metadata['avg_turns_per_conversation']}")
    print(f"  Avg tokens:     {metadata['avg_tokens_estimated']}")
    print()
    print(f"  Files:")
    print(f"    {config.train_path}")
    print(f"    {config.val_path}")
    print(f"    {config.metadata_path}")
    print(f"{'='*60}\n")


def cmd_all(config: DatasetConfig, args: argparse.Namespace) -> None:
    """Run the full pipeline: scenarios -> generate -> validate -> export."""
    logger.info("Running full pipeline")

    logger.info("Step 1/4: Expanding scenarios")
    cmd_scenarios(config, args)

    logger.info("Step 2/4: Generating conversations")
    cmd_generate(config, args)

    logger.info("Step 3/4: Validating conversations")
    cmd_validate(config, args)

    logger.info("Step 4/4: Exporting train/val splits")
    cmd_export(config, args)

    logger.info("Pipeline complete")


def cmd_stats(config: DatasetConfig, args: argparse.Namespace) -> None:
    """Print dataset statistics from metadata.json."""
    if not config.metadata_path.exists():
        logger.error(
            "Metadata not found at %s. Run 'export' first.",
            config.metadata_path,
        )
        sys.exit(1)

    with config.metadata_path.open("r", encoding="utf-8") as f:
        metadata = json.load(f)

    print(f"\n{'='*60}")
    print(f"  Dataset Statistics")
    print(f"{'='*60}")
    print(f"  Generated:  {metadata.get('generation_timestamp', 'N/A')}")
    print(f"  Total:      {metadata.get('total_conversations', 0)}")
    print(f"  Train:      {metadata.get('train_count', 0)}")
    print(f"  Val:        {metadata.get('val_count', 0)}")
    print(f"  Filtered:   {metadata.get('filtered_count', 0)}")
    print(f"  Avg turns:  {metadata.get('avg_turns_per_conversation', 0)}")
    print(f"  Avg tokens: {metadata.get('avg_tokens_estimated', 0)}")
    print()

    dist = metadata.get("distribution", {})
    for axis_name, axis_data in dist.items():
        print(f"  {axis_name.title()} distribution:")
        if isinstance(axis_data, dict):
            for k, v in sorted(axis_data.items(), key=lambda x: -x[1]):
                print(f"    {k:>30}: {v}")
        print()

    tool_freq = metadata.get("tool_call_frequency", {})
    if tool_freq:
        print("  Tool call frequency:")
        for name, count in sorted(tool_freq.items(), key=lambda x: -x[1]):
            print(f"    {name:>25}: {count}")
        print()

    quality = metadata.get("quality_score_distribution", {})
    if quality:
        print("  Quality score distribution:")
        for bucket, count in sorted(quality.items()):
            bar = "#" * min(count, 50)
            print(f"    {bucket:>7}: {count:>4}  {bar}")

    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="generate_dataset",
        description="MERLIN fine-tuning dataset generation pipeline.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # scenarios
    subparsers.add_parser(
        "scenarios",
        help="Export expanded scenario templates to JSONL",
    )

    # generate
    gen_parser = subparsers.add_parser(
        "generate",
        help="Generate conversations via Claude API",
    )
    gen_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of conversations to generate",
    )
    gen_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from where a previous run left off",
    )

    # validate
    subparsers.add_parser(
        "validate",
        help="Validate generated conversations",
    )

    # export
    subparsers.add_parser(
        "export",
        help="Export train/val JSONL splits",
    )

    # all
    all_parser = subparsers.add_parser(
        "all",
        help="Run full pipeline (scenarios -> generate -> validate -> export)",
    )
    all_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of conversations to generate",
    )
    all_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume generation from where a previous run left off",
    )

    # stats
    subparsers.add_parser(
        "stats",
        help="Print dataset statistics from metadata.json",
    )

    args = parser.parse_args()
    _setup_logging(args.verbose)

    config = DatasetConfig()

    commands = {
        "scenarios": cmd_scenarios,
        "generate": cmd_generate,
        "validate": cmd_validate,
        "export": cmd_export,
        "all": cmd_all,
        "stats": cmd_stats,
    }

    cmd_func = commands[args.command]
    cmd_func(config, args)


if __name__ == "__main__":
    main()
