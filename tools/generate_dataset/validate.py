"""Validate generated conversations for quality, structure, and persona consistency."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Patterns that indicate AI disclaimers MERLIN should never use
_AI_DISCLAIMER_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bAs an AI\b", re.IGNORECASE),
    re.compile(r"\bI'm just a\b", re.IGNORECASE),
    re.compile(r"\bI cannot actually\b", re.IGNORECASE),
    re.compile(r"\bI'm an AI\b", re.IGNORECASE),
    re.compile(r"\bAs a language model\b", re.IGNORECASE),
    re.compile(r"\bI don't have the ability to\b", re.IGNORECASE),
]

# Critical phases where brevity matters
_BRIEF_PHASES = {"TAKEOFF", "APPROACH", "LANDING"}
_BRIEF_MAX_CHARS = 200

# Minimum turns before we require "Captain" address
_CAPTAIN_MIN_TURNS = 3


@dataclass
class ValidationResult:
    scenario_id: str
    score: int  # 0-100
    passed: bool
    issues: list[str]


def _check_structural(messages: list[dict], issues: list[str]) -> int:
    """Check structural integrity of the message sequence. Returns penalty."""
    penalty = 0

    if not messages:
        issues.append("Empty message list")
        return 30

    # First message should be system
    if messages[0].get("role") != "system":
        issues.append("First message is not a system message")
        penalty += 10

    # Track pending tool calls to verify tool responses match
    pending_tool_calls: dict[str, str] = {}  # id -> name

    for i, msg in enumerate(messages):
        role = msg.get("role")

        if role is None:
            issues.append(f"Message {i}: missing 'role' field")
            penalty += 30
            continue

        if role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    tc_id = tc.get("id")
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    args_str = func.get("arguments", "")

                    if not tc_id:
                        issues.append(f"Message {i}: tool_call missing 'id'")
                        penalty += 10

                    if not name:
                        issues.append(f"Message {i}: tool_call missing function name")
                        penalty += 10

                    # Validate arguments are valid JSON
                    if args_str:
                        try:
                            json.loads(args_str)
                        except (json.JSONDecodeError, TypeError):
                            issues.append(
                                f"Message {i}: tool_call '{name}' has invalid JSON arguments"
                            )
                            penalty += 15

                    if tc_id:
                        pending_tool_calls[tc_id] = name

        elif role == "tool":
            tc_id = msg.get("tool_call_id")
            if not tc_id:
                issues.append(f"Message {i}: tool message missing 'tool_call_id'")
                penalty += 15
            elif tc_id not in pending_tool_calls:
                issues.append(
                    f"Message {i}: tool response for unknown tool_call_id '{tc_id}'"
                )
                penalty += 15
            else:
                del pending_tool_calls[tc_id]

            if not msg.get("name"):
                issues.append(f"Message {i}: tool message missing 'name'")
                penalty += 5

    # Unrematched tool calls
    if pending_tool_calls:
        issues.append(
            f"Unrematched tool calls without responses: "
            f"{list(pending_tool_calls.values())}"
        )
        penalty += 15

    return min(penalty, 30)


def _check_persona(
    messages: list[dict], phase: str | None, issues: list[str]
) -> int:
    """Check persona consistency. Returns penalty."""
    penalty = 0

    assistant_texts: list[str] = []
    for msg in messages:
        if msg.get("role") == "assistant":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                assistant_texts.append(content)

    all_assistant_text = " ".join(assistant_texts)

    # Check for AI disclaimers
    for pattern in _AI_DISCLAIMER_PATTERNS:
        if pattern.search(all_assistant_text):
            issues.append(f"AI disclaimer detected: {pattern.pattern}")
            penalty += 20
            break  # Only penalize once

    # Check for "Captain" address in longer conversations
    turn_count = sum(1 for m in messages if m.get("role") in ("user", "assistant"))
    if turn_count >= _CAPTAIN_MIN_TURNS:
        captain_found = any(
            "captain" in t.lower() for t in assistant_texts
        )
        if not captain_found:
            issues.append("Missing 'Captain' address in multi-turn conversation")
            penalty += 20

    # Check brevity in critical phases
    if phase and phase.upper() in _BRIEF_PHASES:
        for text in assistant_texts:
            if len(text) > _BRIEF_MAX_CHARS:
                issues.append(
                    f"Response too long for {phase} phase: "
                    f"{len(text)} chars (max {_BRIEF_MAX_CHARS})"
                )
                penalty += 15
                break  # Only penalize once

    return min(penalty, 40)


def _check_content(
    messages: list[dict],
    expected_tools: list[str] | None,
    issues: list[str],
) -> int:
    """Check content quality. Returns penalty."""
    penalty = 0

    # Check for empty assistant responses
    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content")
            tool_calls = msg.get("tool_calls")
            if (not content or (isinstance(content, str) and not content.strip())) and not tool_calls:
                issues.append(f"Message {i}: empty assistant response with no tool calls")
                penalty += 10

    # Check if expected tools were used
    if expected_tools:
        used_tools: set[str] = set()
        for msg in messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls", []):
                    func = tc.get("function", {})
                    name = func.get("name", "")
                    if name:
                        used_tools.add(name)

        if not used_tools:
            issues.append(
                f"No tool calls made; expected: {expected_tools}"
            )
            penalty += 5

    return min(penalty, 20)


def validate_conversation(conversation: dict) -> ValidationResult:
    """Validate a single generated conversation.

    Checks:
    1. Structural: messages well-formed, tool call IDs consistent, valid JSON args
    2. Persona: "Captain" address, no AI disclaimers, phase-appropriate brevity
    3. Content: tool calls appropriate for scenario, reasonable response lengths

    The ``conversation`` dict should have:
        - messages: list[dict]  (OpenAI format)
        - scenario_id: str
        - phase: str (optional)
        - expected_tools: list[str] (optional)
    """
    scenario_id = conversation.get("scenario_id", "unknown")
    messages = conversation.get("messages", [])
    phase = conversation.get("phase")
    expected_tools = conversation.get("expected_tools")

    issues: list[str] = []
    score = 100

    score -= _check_structural(messages, issues)
    score -= _check_persona(messages, phase, issues)
    score -= _check_content(messages, expected_tools, issues)

    score = max(0, score)
    passed = score >= 60

    result = ValidationResult(
        scenario_id=scenario_id,
        score=score,
        passed=passed,
        issues=issues,
    )

    if not passed:
        logger.warning(
            "Conversation %s failed validation (score=%d): %s",
            scenario_id,
            score,
            "; ".join(issues),
        )

    return result


def validate_dataset(conversations_path: str | Path) -> dict:
    """Validate all conversations in a JSONL file. Returns summary stats.

    Each line of the JSONL file should be a JSON object with at least
    a ``messages`` key (OpenAI format) and optionally ``scenario_id``,
    ``phase``, and ``expected_tools``.

    Returns a dict with:
        - total: int
        - passed: int
        - failed: int
        - pass_rate: float
        - avg_score: float
        - score_distribution: dict[str, int]  (bucketed)
        - common_issues: list[tuple[str, int]]  (top 10 most frequent)
        - results: list[ValidationResult]
    """
    path = Path(conversations_path)
    results: list[ValidationResult] = []
    issue_counts: dict[str, int] = {}

    with path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                conversation = json.loads(line)
            except json.JSONDecodeError:
                logger.error("Line %d: invalid JSON, skipping", line_num)
                results.append(
                    ValidationResult(
                        scenario_id=f"line_{line_num}",
                        score=0,
                        passed=False,
                        issues=["Invalid JSON"],
                    )
                )
                continue

            # Ensure scenario_id is set
            if "scenario_id" not in conversation:
                conversation["scenario_id"] = f"line_{line_num}"

            result = validate_conversation(conversation)
            results.append(result)

            for issue in result.issues:
                # Normalize issue text for grouping
                issue_key = issue.split(":")[0] if ":" in issue else issue
                issue_counts[issue_key] = issue_counts.get(issue_key, 0) + 1

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    avg_score = sum(r.score for r in results) / total if total > 0 else 0.0

    # Score distribution in buckets of 10
    score_dist: dict[str, int] = {}
    for bucket_start in range(0, 101, 10):
        bucket_end = min(bucket_start + 9, 100)
        key = f"{bucket_start}-{bucket_end}"
        score_dist[key] = sum(
            1 for r in results if bucket_start <= r.score <= bucket_end
        )

    # Top issues
    common_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    logger.info(
        "Validation complete: %d total, %d passed (%.1f%%), avg score %.1f",
        total,
        passed,
        (passed / total * 100) if total else 0,
        avg_score,
    )

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "avg_score": round(avg_score, 2),
        "score_distribution": score_dist,
        "common_issues": common_issues,
        "results": results,
    }
