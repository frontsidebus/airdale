"""MERLIN fine-tuning dataset generation pipeline.

Generates multi-turn aviation conversations with tool calls for
QLoRA fine-tuning of Qwen3.5-35B-A3B using Unsloth.

Usage::

    python -m generate_dataset all          # Full pipeline
    python -m generate_dataset scenarios    # Export scenario templates
    python -m generate_dataset generate     # Generate conversations via Claude
    python -m generate_dataset validate     # Run quality checks
    python -m generate_dataset export       # Export train/val splits
    python -m generate_dataset stats        # Print dataset statistics
"""
