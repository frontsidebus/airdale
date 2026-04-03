"""Async conversation generator for MERLIN fine-tuning dataset.

Orchestrates Claude API calls to produce multi-turn conversations that match
MERLIN's persona, tool usage patterns, and phase-appropriate response styles.
Results are written incrementally to JSONL (one conversation per line).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from pathlib import Path
from typing import Any

import anthropic

from tools.generate_dataset.aircraft import AIRCRAFT_BY_NAME, AircraftProfile, ALL_AIRCRAFT
from tools.generate_dataset.config import DatasetConfig
from tools.generate_dataset.mock_tools import mock_tool_response
from tools.generate_dataset.prompts import build_system_prompt, format_telemetry_summary
from tools.generate_dataset.scenarios import ALL_SCENARIOS, expand_scenarios
from tools.generate_dataset.telemetry import evolve_sim_state, generate_sim_state

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions (matching MERLIN's claude_client.py)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "get_sim_state",
        "description": "Retrieve the current simulator state.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "lookup_airport",
        "description": "Look up airport information by ICAO or FAA identifier.",
        "input_schema": {
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "Airport ICAO or FAA identifier",
                }
            },
            "required": ["identifier"],
        },
    },
    {
        "name": "search_manual",
        "description": "Search the aircraft operating manual and knowledge base.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_checklist",
        "description": "Get the appropriate checklist for a given flight phase.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phase": {
                    "type": "string",
                    "description": "Flight phase",
                }
            },
            "required": ["phase"],
        },
    },
    {
        "name": "create_flight_plan",
        "description": "Create a basic flight plan between two airports.",
        "input_schema": {
            "type": "object",
            "properties": {
                "departure": {
                    "type": "string",
                    "description": "Departure airport",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport",
                },
                "altitude": {
                    "type": "integer",
                    "description": "Cruise altitude in feet MSL",
                    "default": 5000,
                },
                "route": {
                    "type": "string",
                    "description": "Route waypoints",
                    "default": "",
                },
            },
            "required": ["departure", "destination"],
        },
    },
]

# Maximum tool-use continuation loops per turn to prevent runaway calls
_MAX_TOOL_LOOPS = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_aircraft(aircraft_name: str) -> AircraftProfile:
    """Resolve an aircraft name to an AircraftProfile, with fallback."""
    profile = AIRCRAFT_BY_NAME.get(aircraft_name)
    if profile is not None:
        return profile
    # Fuzzy fallback: match by substring
    name_lower = aircraft_name.lower()
    for a in ALL_AIRCRAFT:
        if name_lower in a.name.lower() or a.name.lower() in name_lower:
            return a
    # Ultimate fallback: first aircraft
    return ALL_AIRCRAFT[0]


def _format_weather_summary(weather: str) -> str:
    """Turn a weather preset key into a human-readable summary."""
    summaries = {
        "CAVU": "Clear and visibility unlimited. Winds calm.",
        "marginal_vfr": "Marginal VFR. Visibility 3-5 SM, scattered clouds at 2500 AGL.",
        "IFR": "IFR conditions. Visibility 1-2 SM, overcast at 800 AGL.",
        "crosswind": "Crosswind conditions. Winds 15-20 kt gusting, 45° off runway heading.",
        "turbulence": "Moderate turbulence reported. Winds variable 15-25 kt.",
        "icing": "Icing conditions. Visible moisture, temperature near freezing.",
    }
    return summaries.get(weather, f"Weather: {weather}")


async def _call_with_retry(
    client: anthropic.AsyncAnthropic,
    *,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int,
    max_retries: int = 3,
) -> anthropic.types.Message:
    """Call the Anthropic API with exponential backoff retry."""
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            response = await client.messages.create(
                model=model,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
            )
            return response
        except anthropic.RateLimitError as e:
            last_error = e
            wait = min(2 ** (attempt + 1) + random.uniform(0, 1), 60)
            logger.warning(
                "Rate limited (attempt %d/%d). Retrying in %.1fs...",
                attempt + 1,
                max_retries,
                wait,
            )
            await asyncio.sleep(wait)
        except anthropic.APIStatusError as e:
            last_error = e
            if e.status_code >= 500:
                wait = min(2 ** (attempt + 1) + random.uniform(0, 1), 60)
                logger.warning(
                    "API error %d (attempt %d/%d). Retrying in %.1fs...",
                    e.status_code,
                    attempt + 1,
                    max_retries,
                    wait,
                )
                await asyncio.sleep(wait)
            else:
                raise
        except anthropic.APIConnectionError as e:
            last_error = e
            wait = min(2 ** (attempt + 1) + random.uniform(0, 1), 30)
            logger.warning(
                "Connection error (attempt %d/%d). Retrying in %.1fs...",
                attempt + 1,
                max_retries,
                wait,
            )
            await asyncio.sleep(wait)

    raise last_error  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Core generation
# ---------------------------------------------------------------------------


async def generate_conversation(
    client: anthropic.AsyncAnthropic,
    scenario: dict,
    config: DatasetConfig,
) -> dict | None:
    """Generate a single multi-turn conversation.

    Args:
        client: Anthropic async API client.
        scenario: An expanded scenario instance from expand_scenarios().
        config: Dataset generation configuration.

    Returns:
        A dict containing the conversation in Anthropic message format,
        or None if generation failed.
    """
    scenario_id = scenario["scenario_id"]
    phase = scenario["phase"]
    category = scenario["category"]
    aircraft_name = scenario["aircraft"]
    weather = scenario["weather"]
    pilot_level = scenario["pilot_level"]
    user_prompts = scenario["user_prompts"]
    is_emergency = category == "emergency"

    # Resolve aircraft profile
    aircraft = _resolve_aircraft(aircraft_name)

    # Generate initial sim state
    seed = hash(scenario_id) & 0xFFFFFFFF
    sim_state = generate_sim_state(
        phase=phase,
        aircraft=aircraft,
        weather=weather,
        seed=seed,
    )

    # Build telemetry and weather summaries
    telemetry_summary = format_telemetry_summary(sim_state)
    weather_summary = _format_weather_summary(weather)

    # Build system prompt
    system_prompt = build_system_prompt(
        phase=phase,
        aircraft_name=aircraft_name,
        telemetry_summary=telemetry_summary,
        pilot_level=pilot_level,
        weather_summary=weather_summary,
        is_emergency=is_emergency,
        diversity_seed=seed,
    )

    messages: list[dict[str, Any]] = []
    total_input_tokens = 0
    total_output_tokens = 0
    start_time = time.monotonic()

    try:
        for turn_idx, user_prompt in enumerate(user_prompts):
            # Add user message
            messages.append({"role": "user", "content": user_prompt})

            # Call Claude
            response = await _call_with_retry(
                client,
                model=config.model,
                system=system_prompt,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                max_tokens=1024,
                max_retries=config.max_retries,
            )

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            # Process response -- handle tool use loops
            tool_loop_count = 0
            while response.stop_reason == "tool_use" and tool_loop_count < _MAX_TOOL_LOOPS:
                tool_loop_count += 1

                # Build the assistant content blocks
                assistant_content: list[dict[str, Any]] = []
                tool_results: list[dict[str, Any]] = []

                for block in response.content:
                    if block.type == "text":
                        assistant_content.append({
                            "type": "text",
                            "text": block.text,
                        })
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })

                        # Generate mock tool response
                        try:
                            tool_response_str = mock_tool_response(
                                tool_name=block.name,
                                arguments=block.input,
                                sim_state=sim_state,
                            )
                        except Exception as e:
                            logger.warning(
                                "Mock tool error for %s in %s: %s",
                                block.name,
                                scenario_id,
                                e,
                            )
                            tool_response_str = json.dumps({"error": str(e)})

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": tool_response_str,
                        })

                # Append assistant message with tool_use blocks
                messages.append({"role": "assistant", "content": assistant_content})

                # Append tool results as a user message
                messages.append({"role": "user", "content": tool_results})

                # Continue the conversation with tool results
                response = await _call_with_retry(
                    client,
                    model=config.model,
                    system=system_prompt,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    max_tokens=1024,
                    max_retries=config.max_retries,
                )

                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens

            # Capture the final assistant response for this turn
            final_content: list[dict[str, Any]] = []
            for block in response.content:
                if block.type == "text":
                    final_content.append({
                        "type": "text",
                        "text": block.text,
                    })
                elif block.type == "tool_use":
                    # Shouldn't happen after max loops, but capture anyway
                    final_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            messages.append({"role": "assistant", "content": final_content})

            # Evolve sim state between turns
            if turn_idx < len(user_prompts) - 1:
                sim_state = evolve_sim_state(
                    base_state=sim_state,
                    phase=phase,
                    elapsed_seconds=30.0,
                )
                # Update telemetry summary in system prompt for next turn
                telemetry_summary = format_telemetry_summary(sim_state)
                system_prompt = build_system_prompt(
                    phase=phase,
                    aircraft_name=aircraft_name,
                    telemetry_summary=telemetry_summary,
                    pilot_level=pilot_level,
                    weather_summary=weather_summary,
                    is_emergency=is_emergency,
                    diversity_seed=seed,
                )

    except Exception as e:
        elapsed = time.monotonic() - start_time
        logger.error(
            "Failed to generate %s after %.1fs: %s",
            scenario_id,
            elapsed,
            e,
        )
        return None

    elapsed = time.monotonic() - start_time

    return {
        "scenario_id": scenario_id,
        "messages": messages,
        "phase": phase,
        "category": category,
        "aircraft": aircraft_name,
        "weather": weather,
        "pilot_level": pilot_level,
        "metadata": {
            "model": config.model,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "generation_time_seconds": round(elapsed, 2),
            "num_turns": len(user_prompts),
        },
    }


# ---------------------------------------------------------------------------
# Batch orchestration
# ---------------------------------------------------------------------------


def _load_existing_ids(output_path: Path) -> set[str]:
    """Read an existing JSONL file and return all scenario_ids found."""
    ids: set[str] = set()
    if not output_path.exists():
        return ids
    with open(output_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                sid = record.get("scenario_id")
                if sid:
                    ids.add(sid)
            except json.JSONDecodeError:
                continue
    return ids


async def generate_all(
    config: DatasetConfig,
    limit: int | None = None,
    resume: bool = False,
) -> None:
    """Generate all conversations with concurrency control.

    Args:
        config: Dataset generation configuration.
        limit: Optional cap on total conversations to generate.
        resume: If True, reads existing JSONL and skips already-generated
            scenario IDs.
    """
    config.ensure_output_dir()
    output_path = config.raw_conversations_path

    # Expand scenarios
    scenarios = expand_scenarios(
        scenarios=ALL_SCENARIOS,
        max_per_template=15,
        seed=config.random_seed,
    )
    logger.info("Expanded %d scenario instances from %d templates.", len(scenarios), len(ALL_SCENARIOS))

    # Apply limit
    if config.target_conversations and len(scenarios) > config.target_conversations:
        rng = random.Random(config.random_seed)
        rng.shuffle(scenarios)
        scenarios = scenarios[: config.target_conversations]
        logger.info("Capped to %d target conversations.", config.target_conversations)

    if limit is not None:
        scenarios = scenarios[:limit]
        logger.info("Limited to %d conversations by --limit flag.", limit)

    # Resume support: skip already-generated scenario IDs
    if resume:
        existing_ids = _load_existing_ids(output_path)
        before = len(scenarios)
        scenarios = [s for s in scenarios if s["scenario_id"] not in existing_ids]
        logger.info(
            "Resume mode: skipping %d already-generated conversations (%d remaining).",
            before - len(scenarios),
            len(scenarios),
        )

    if not scenarios:
        logger.info("Nothing to generate. All scenarios already complete.")
        return

    # Initialize client
    client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    # Concurrency control
    semaphore = asyncio.Semaphore(config.concurrency)

    # File lock for incremental writes
    file_lock = asyncio.Lock()

    completed = 0
    failed = 0
    total = len(scenarios)

    async def _worker(scenario: dict) -> None:
        nonlocal completed, failed

        async with semaphore:
            result = await generate_conversation(client, scenario, config)

        if result is not None:
            async with file_lock:
                with open(output_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(result, ensure_ascii=False) + "\n")
                completed += 1
        else:
            failed += 1

        done = completed + failed
        if done % 25 == 0 or done == total:
            logger.info(
                "Progress: %d/%d (%.0f%%) — %d completed, %d failed",
                done,
                total,
                done / total * 100 if total > 0 else 0,
                completed,
                failed,
            )

    # Launch all workers
    logger.info(
        "Starting generation: %d conversations, concurrency=%d, model=%s",
        total,
        config.concurrency,
        config.model,
    )
    start = time.monotonic()

    tasks = [asyncio.create_task(_worker(s)) for s in scenarios]
    await asyncio.gather(*tasks)

    elapsed = time.monotonic() - start
    logger.info(
        "Generation complete in %.1fs. %d completed, %d failed, %d total.",
        elapsed,
        completed,
        failed,
        total,
    )
    logger.info("Output written to %s", output_path)
