"""Wrapper around the Anthropic API with MERLIN persona and tool definitions."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator

import anthropic

from .context_store import ContextStore
from .sim_client import SimConnectClient, SimState

from .tools import (
    create_flight_plan,
    get_checklist,
    get_sim_state,
    lookup_airport,
    search_manual,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MERLIN persona — prefer the rich markdown version from disk when available.
# ---------------------------------------------------------------------------

_MERLIN_SYSTEM_PATH = Path(__file__).resolve().parents[2] / "data" / "prompts" / "merlin_system.md"

_INLINE_PERSONA = """\
You are MERLIN, an AI co-pilot assistant for Microsoft Flight Simulator 2024. Your persona:

- **Background**: Former Navy Test Pilot School graduate turned digital co-pilot. You carry \
the precision and discipline of military aviation with the adaptability of a seasoned instructor.
- **Tone**: Professional but approachable. Dry, understated humor — the kind you'd hear in a \
ready room. Never flippant about safety.
- **Address**: Always call the pilot "Captain." You respect the chain of command — they fly, \
you advise.
- **Communication style**: Clear, concise, and structured like radio calls when time-critical. \
More conversational during low-workload phases. Use aviation terminology naturally but explain \
it when a Captain seems unsure.
- **Philosophy**: "Aviate, Navigate, Communicate" — always prioritize in that order. Never \
distract the Captain during critical phases unless safety demands it.
- **Knowledge**: Deep expertise in aerodynamics, navigation, weather, aircraft systems, ATC \
procedures, regulations, and emergency procedures. You know the POH for common aircraft types.
- **Limitations**: You always remind the Captain that you're a simulator assistant, not a \
replacement for real flight training or certified flight instructors.

Current flight context will be injected below. Use it to make your responses situationally aware.
"""


def _load_merlin_persona() -> str:
    """Return the full MERLIN system prompt, preferring the on-disk markdown file."""
    if _MERLIN_SYSTEM_PATH.exists():
        try:
            return _MERLIN_SYSTEM_PATH.read_text(encoding="utf-8")
        except Exception:
            logger.warning("Failed to read %s; falling back to inline persona", _MERLIN_SYSTEM_PATH)
    return _INLINE_PERSONA


MERLIN_PERSONA: str = _load_merlin_persona()


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_sim_state",
        "description": (
            "Retrieve the current simulator state including position, attitude, speeds, "
            "engine parameters, autopilot, radios, fuel, weather, and surface states."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "lookup_airport",
        "description": (
            "Look up airport information by ICAO or FAA identifier. Returns name, location, "
            "elevation, and basic facility data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "Airport ICAO or FAA identifier (e.g., KJFK, KLAX, ORL)",
                },
            },
            "required": ["identifier"],
        },
    },
    {
        "name": "search_manual",
        "description": (
            "Search the aircraft operating manual and aviation knowledge base. Use this to look "
            "up procedures, limitations, V-speeds, systems descriptions, or any aircraft-specific "
            "information."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query describing what to look up",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_checklist",
        "description": (
            "Get the appropriate checklist for a given flight phase. Returns phase-specific "
            "checklist items, preferring aircraft-specific checklists when available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phase": {
                    "type": "string",
                    "description": "Flight phase (PREFLIGHT, TAXI, TAKEOFF, CLIMB, CRUISE, DESCENT, APPROACH, LANDING, LANDED)",
                },
            },
            "required": ["phase"],
        },
    },
    {
        "name": "create_flight_plan",
        "description": (
            "Create a basic flight plan between two airports. Returns a draft route structure "
            "with departure, destination, and waypoints."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "departure": {
                    "type": "string",
                    "description": "Departure airport identifier",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport identifier",
                },
                "altitude": {
                    "type": "integer",
                    "description": "Planned cruise altitude in feet MSL",
                    "default": 5000,
                },
                "route": {
                    "type": "string",
                    "description": "Optional route waypoints separated by spaces",
                    "default": "",
                },
            },
            "required": ["departure", "destination"],
        },
    },
]


class ClaudeClient:
    """Manages conversations with Claude using the MERLIN persona."""

    def __init__(
        self,
        api_key: str,
        model: str,
        sim_client: SimConnectClient,
        context_store: ContextStore,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._sim_client = sim_client
        self._context_store = context_store
        self._conversation: list[dict[str, Any]] = []
        self._max_history = 50  # max message pairs to retain

    def _build_system_prompt(self, sim_state: SimState, context_docs: list[dict[str, Any]]) -> str:
        parts = [MERLIN_PERSONA]

        parts.append(f"\n--- CURRENT FLIGHT STATE ---\n{sim_state.telemetry_summary()}")
        parts.append(f"Aircraft: {sim_state.aircraft or 'Unknown'}")
        parts.append(f"On ground: {sim_state.on_ground}")

        if sim_state.autopilot.master:
            ap = sim_state.autopilot
            parts.append(
                f"Autopilot: HDG {ap.heading:.0f} | ALT {ap.altitude:.0f} | "
                f"VS {ap.vertical_speed:+.0f} | IAS {ap.airspeed:.0f}"
            )

        env = sim_state.environment
        parts.append(
            f"Weather: Wind {env.wind_direction:.0f}°/{env.wind_speed_kts:.0f}kt | "
            f"Vis {env.visibility_sm:.0f}sm | Temp {env.temperature_c:.0f}°C | "
            f"QNH {env.barometer_inhg:.2f}\"Hg"
        )

        if context_docs:
            parts.append("\n--- RELEVANT REFERENCE MATERIAL ---")
            for doc in context_docs[:3]:
                source = doc.get("metadata", {}).get("source", "unknown")
                parts.append(f"[{source}]\n{doc['content'][:500]}")

        return "\n".join(parts)

    async def chat(
        self,
        user_message: str,
        sim_state: SimState | None = None,
        image_base64: str | None = None,
    ) -> AsyncIterator[str]:
        """Send a message and yield streamed response text chunks.

        Handles tool use loops internally, yielding text as it arrives.
        """
        if sim_state is None:
            try:
                sim_state = await self._sim_client.get_state()
            except Exception:
                sim_state = SimState()

        context_docs = await self._context_store.get_relevant_context(sim_state)
        system = self._build_system_prompt(sim_state, context_docs)

        # Build user message content
        content: list[dict[str, Any]] = []
        if image_base64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_base64,
                },
            })
        content.append({"type": "text", "text": user_message})

        self._conversation.append({"role": "user", "content": content})
        self._trim_history()

        # Agentic loop: keep going while Claude wants to use tools
        while True:
            collected_text = ""
            tool_use_blocks: list[dict[str, Any]] = []
            current_tool_input = ""
            current_tool_id = ""
            current_tool_name = ""
            stop_reason = None

            async with self._client.messages.stream(
                model=self._model,
                max_tokens=4096,
                system=system,
                messages=self._conversation,
                tools=TOOL_DEFINITIONS,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        if event.content_block.type == "tool_use":
                            current_tool_id = event.content_block.id
                            current_tool_name = event.content_block.name
                            current_tool_input = ""
                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            collected_text += event.delta.text
                            yield event.delta.text
                        elif event.delta.type == "input_json_delta":
                            current_tool_input += event.delta.partial_json
                    elif event.type == "content_block_stop":
                        if current_tool_name:
                            tool_input = json.loads(current_tool_input) if current_tool_input else {}
                            tool_use_blocks.append({
                                "id": current_tool_id,
                                "name": current_tool_name,
                                "input": tool_input,
                            })
                            current_tool_name = ""
                    elif event.type == "message_delta":
                        stop_reason = event.delta.stop_reason

            # Record assistant turn
            assistant_content: list[dict[str, Any]] = []
            if collected_text:
                assistant_content.append({"type": "text", "text": collected_text})
            for tb in tool_use_blocks:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tb["id"],
                    "name": tb["name"],
                    "input": tb["input"],
                })
            self._conversation.append({"role": "assistant", "content": assistant_content})

            if stop_reason != "tool_use" or not tool_use_blocks:
                break

            # Execute tools and feed results back
            tool_results: list[dict[str, Any]] = []
            for tb in tool_use_blocks:
                result = await self._execute_tool(tb["name"], tb["input"], sim_state)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tb["id"],
                    "content": json.dumps(result),
                })
            self._conversation.append({"role": "user", "content": tool_results})

    async def _execute_tool(
        self, name: str, args: dict[str, Any], sim_state: SimState
    ) -> Any:
        logger.info("Executing tool: %s(%s)", name, args)
        try:
            if name == "get_sim_state":
                return await get_sim_state(self._sim_client)
            elif name == "lookup_airport":
                return await lookup_airport(args["identifier"])
            elif name == "search_manual":
                return await search_manual(
                    args["query"],
                    self._context_store,
                    aircraft_type=sim_state.aircraft,
                )
            elif name == "get_checklist":
                return await get_checklist(
                    args["phase"],
                    self._context_store,
                    aircraft_type=sim_state.aircraft,
                )
            elif name == "create_flight_plan":
                return await create_flight_plan(
                    args["departure"],
                    args["destination"],
                    altitude=args.get("altitude", 5000),
                    route=args.get("route", ""),
                )
            else:
                return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.exception("Tool execution failed: %s", name)
            return {"error": str(e)}

    def clear_history(self) -> None:
        self._conversation.clear()

    def _trim_history(self) -> None:
        if len(self._conversation) > self._max_history * 2:
            self._conversation = self._conversation[-(self._max_history * 2) :]
