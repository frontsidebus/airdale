"""Wrapper around the Anthropic API with MERLIN persona and tool definitions."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import anthropic

from .command_history import CommandHistory
from .command_verifier import CommandVerifier
from .context_store import ContextStore
from .procedures import PROCEDURES, ProcedureExecutor, get_procedure
from .sim_client import FlightPhase, SimState, TelemetryClient
from .tools import (
    create_flight_plan,
    get_checklist,
    get_sim_state,
    lookup_airport,
    search_manual,
    set_aircraft_control,
    undo_last_command,
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

# ---------------------------------------------------------------------------
# Response pacing directives appended to every system prompt.
# ---------------------------------------------------------------------------

_RESPONSE_PACING = """\

--- RESPONSE RULES ---
Keep responses concise and tactical. In a cockpit, brevity saves lives.
- Use standard aviation phraseology wherever appropriate.
- Pause after key information to allow the pilot to acknowledge.
- For routine comms, acknowledgments, and simple questions: 1-3 sentences MAX.
- For procedures and checklists: present items in groups of 3-5, then wait.
- For briefings and flight plans: be thorough but structured — use bullet points, not prose.
- NEVER ramble. If you catch yourself writing a paragraph, stop and restructure.
- After asking a question, STOP. Do not answer your own question.
- After giving a key callout, STOP. Let the Captain respond.
- End radio-style exchanges with "over" or a clear pause point.
"""

# ---------------------------------------------------------------------------
# Flight-phase-specific response style directives.
# ---------------------------------------------------------------------------

_PHASE_STYLE: dict[FlightPhase, str] = {
    FlightPhase.PREFLIGHT: (
        "Phase: PREFLIGHT. Relaxed tone, moderate length. Good time for banter and briefings."
    ),
    FlightPhase.TAXI: (
        "Phase: TAXI. Professional, concise. 1-2 sentences unless reading a checklist."
    ),
    FlightPhase.TAKEOFF: ("Phase: TAKEOFF. ULTRA-BRIEF. Callouts only. No humor. No filler."),
    FlightPhase.CLIMB: (
        "Phase: CLIMB. Professional, moderate length. Light humor once established."
    ),
    FlightPhase.CRUISE: (
        "Phase: CRUISE. Conversational, can be more detailed. Good time to teach."
    ),
    FlightPhase.DESCENT: ("Phase: DESCENT. Briefing mode. Structured and clear. Minimal humor."),
    FlightPhase.APPROACH: (
        "Phase: APPROACH. ULTRA-BRIEF. Concise callouts only. No humor. No filler."
    ),
    FlightPhase.LANDING: ("Phase: LANDING. ULTRA-BRIEF. Callouts only. Crisp and precise."),
    FlightPhase.LANDED: ("Phase: LANDED. Relaxed debrief mode. Can use humor. Moderate length."),
}

# ---------------------------------------------------------------------------
# Stop sequences for natural conversation breaks.
# ---------------------------------------------------------------------------

STOP_SEQUENCES: list[str] = ["\nover.", "\nOver.", "\nover", "\nOver"]


def _load_merlin_persona() -> str:
    """Return the full MERLIN system prompt, preferring the on-disk markdown file."""
    if _MERLIN_SYSTEM_PATH.exists():
        try:
            return _MERLIN_SYSTEM_PATH.read_text(encoding="utf-8")
        except Exception:
            logger.warning(
                "Failed to read %s; falling back to inline persona",
                _MERLIN_SYSTEM_PATH,
            )
    return _INLINE_PERSONA


MERLIN_PERSONA: str = _load_merlin_persona()

# ---------------------------------------------------------------------------
# Query classification for response budgeting.
# ---------------------------------------------------------------------------

# Patterns that indicate the pilot wants a detailed response.
_BRIEFING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(brief|briefing|checklist|flight\s*plan|plan\s+a\s+flight)\b", re.I),
    re.compile(r"\b(walk\s+me\s+through|explain|teach|how\s+does)\b", re.I),
    re.compile(r"\b(create|build|make)\s+(a\s+)?(flight\s*plan|route)\b", re.I),
]

# Patterns that indicate a short acknowledgment is expected.
_SHORT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(roger|copy|wilco|affirm|negative|check|say again)\b", re.I),
    re.compile(r"^(thanks|thank you|got it|ok|okay)\b", re.I),
    re.compile(r"\b(what\s*'?s?\s+(my|our|the)\s+(altitude|heading|speed|fuel))\b", re.I),
    re.compile(r"\b(how\s+(much|far|long|high|fast))\b", re.I),
    re.compile(r"^(yes|no|yep|nope|yeah)\b", re.I),
]

# Patterns indicating an emergency or urgent situation.
_EMERGENCY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(mayday|pan\s*pan|declare\s+(?:an?\s+)?emergency)\b", re.I),
    re.compile(r"\b(engine\s+(fire|failure|out|flameout)|fire\s+in\s+the)\b", re.I),
    re.compile(r"\b(smoke\s+in|decompress|ditching|crash\s+land)\b", re.I),
    re.compile(r"\b(pull\s+up|GPWS\s+warning|TCAS\s+RA|terrain\s+alert)\b", re.I),
]


def classify_query(user_message: str) -> str:
    """Classify a pilot message as 'emergency', 'short', 'briefing', or 'normal'.

    Returns one of: 'emergency', 'short', 'briefing', 'normal'.
    """
    text = user_message.strip()
    # Emergency takes priority over everything
    for pat in _EMERGENCY_PATTERNS:
        if pat.search(text):
            return "emergency"
    for pat in _SHORT_PATTERNS:
        if pat.search(text):
            return "short"
    for pat in _BRIEFING_PATTERNS:
        if pat.search(text):
            return "briefing"
    return "normal"


# ---------------------------------------------------------------------------
# Dynamic temperature by flight phase and query type
# ---------------------------------------------------------------------------

# Phase → temperature tier
_PHASE_TEMPERATURE: dict[FlightPhase, str] = {
    FlightPhase.TAKEOFF: "critical",
    FlightPhase.APPROACH: "critical",
    FlightPhase.LANDING: "critical",
    FlightPhase.CLIMB: "normal",
    FlightPhase.DESCENT: "normal",
    FlightPhase.TAXI: "normal",
    FlightPhase.PREFLIGHT: "relaxed",
    FlightPhase.CRUISE: "relaxed",
    FlightPhase.LANDED: "relaxed",
}


def get_temperature_for_context(
    phase: FlightPhase,
    query_type: str,
    *,
    temp_critical: float = 0.1,
    temp_normal: float = 0.3,
    temp_relaxed: float = 0.5,
) -> float:
    """Return the appropriate temperature for the current flight context.

    Emergency and short queries always use the normal (deterministic) temp.
    Briefings use normal temp for accuracy. Otherwise, phase determines tier.
    """
    if query_type in ("emergency", "short", "briefing"):
        return temp_normal

    tier = _PHASE_TEMPERATURE.get(phase, "normal")
    return {"critical": temp_critical, "normal": temp_normal, "relaxed": temp_relaxed}[tier]


def get_model_for_query(
    query_type: str,
    *,
    model_default: str,
    model_fast: str,
) -> str:
    """Route to the appropriate model based on query complexity.

    Short queries go to the fast/cheap model (Haiku).
    Everything else uses the default model (Sonnet).
    """
    if query_type == "short":
        return model_fast
    return model_default


def max_tokens_for_query(
    query_type: str,
    default_max: int = 1024,
    briefing_max: int = 2048,
) -> int:
    """Return the appropriate max_tokens budget for a query type."""
    if query_type == "short":
        return min(256, default_max)
    if query_type == "briefing":
        return briefing_max
    return default_max


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
                    "description": ("Airport ICAO or FAA identifier (e.g., KJFK, KLAX, ORL)"),
                },
            },
            "required": ["identifier"],
        },
    },
    {
        "name": "search_manual",
        "description": (
            "Search the aircraft operating manual and aviation knowledge base. Use this to "
            "look up procedures, limitations, V-speeds, systems descriptions, or any "
            "aircraft-specific information."
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
                    "description": (
                        "Flight phase (PREFLIGHT, TAXI, TAKEOFF, CLIMB, CRUISE, "
                        "DESCENT, APPROACH, LANDING, LANDED)"
                    ),
                },
            },
            "required": ["phase"],
        },
    },
    {
        "name": "create_flight_plan",
        "description": (
            "Create a basic flight plan between two airports. Returns a draft route "
            "structure with departure, destination, and waypoints."
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
    {
        "name": "set_aircraft_control",
        "description": (
            "Control an aircraft system in the simulator. Can set flaps, gear, "
            "autopilot settings, throttle, radios, trim, and other controls. "
            "EXECUTE IMMEDIATELY when the Captain gives a direct order like "
            "'give me full flaps', 'gear down', 'set heading to 270'. "
            "Do NOT ask for clarification when the order is unambiguous. "
            "After executing, give a brief confirmation like 'Flaps full.' "
            "or 'Gear down, three green.'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "system": {
                    "type": "string",
                    "enum": [
                        "flaps",
                        "gear",
                        "autopilot",
                        "throttle",
                        "radio",
                        "barometer",
                        "trim",
                        "parking_brake",
                        "spoilers",
                        "mixture",
                        "propeller",
                        "fuel_selector",
                        "crossfeed",
                        "deice",
                    ],
                    "description": "The aircraft system to control",
                },
                "action": {
                    "type": "string",
                    "description": (
                        "The action to perform. Examples by system: "
                        "flaps: 'up', 'full', '1', '2', '3', '10', '20', '30', "
                        "'set', 'incr', 'decr'; "
                        "gear: 'up', 'down', 'toggle'; "
                        "autopilot: 'on', 'off', 'heading', 'heading_hold', "
                        "'altitude', 'altitude_hold', 'vertical_speed', 'vs_hold', "
                        "'speed', 'speed_hold', 'nav', 'approach'; "
                        "throttle: 'set'; "
                        "radio: 'com1', 'com2', 'nav1', 'nav2'; "
                        "barometer: 'set'; "
                        "trim: 'set', 'up', 'nose_up', 'down', 'nose_down', "
                        "'rudder_left', 'rudder_right', 'rudder_set', "
                        "'aileron_left', 'aileron_right', 'aileron_set'; "
                        "deice: 'pitot', 'pitot_heat', 'structural', 'airframe', "
                        "'windshield', 'props', 'prop_deice'; "
                        "spoilers: 'toggle', 'set'; "
                        "mixture/propeller: 'set'; "
                        "fuel_selector: 'off', 'all', 'both', 'left', 'right', 'set'; "
                        "crossfeed: 'open', 'close', 'toggle'"
                    ),
                },
                "value": {
                    "type": "number",
                    "description": (
                        "Numeric value when needed. Units depend on system: "
                        "flaps set: percentage (0-100) or notch (1-4); "
                        "autopilot heading: degrees (0-360); "
                        "autopilot altitude: feet; "
                        "autopilot vertical_speed: fpm (-6000 to +6000); "
                        "autopilot speed: knots; "
                        "throttle/mixture/propeller/spoilers set: percentage (0-100); "
                        "radio: frequency in MHz (e.g. 121.5); "
                        "barometer: inHg (e.g. 29.92)"
                    ),
                },
            },
            "required": ["system", "action"],
        },
    },
    {
        "name": "execute_procedure",
        "description": (
            "Execute a named multi-step procedure that configures multiple aircraft "
            "systems in sequence. Use when the Captain requests a configuration change "
            "that involves multiple systems, such as 'configure for landing', 'clean up', "
            "'go around', or 'shut down'. Available procedures: "
            + ", ".join(PROCEDURES.keys())
            + ". Report each step as it executes. If a step fails, report which step "
            "failed — remaining steps still execute."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "procedure": {
                    "type": "string",
                    "description": ("Procedure name. One of: " + ", ".join(PROCEDURES.keys())),
                },
            },
            "required": ["procedure"],
        },
    },
    {
        "name": "undo_last_command",
        "description": (
            "Reverse the last aircraft control command. Use when the Captain says "
            "'cancel that', 'undo', 'never mind', 'put that back', or similar. "
            "Reports what was undone. If nothing to undo or the command is not "
            "reversible, reports that instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


class ClaudeClient:
    """Manages conversations with Claude using the MERLIN persona."""

    def __init__(
        self,
        api_key: str,
        model: str,
        sim_client: TelemetryClient,
        context_store: ContextStore,
        max_tokens: int = 1024,
        max_tokens_briefing: int = 2048,
        max_history: int = 20,
        temperature: float = 0.3,
        model_fast: str = "claude-haiku-4-5-20251001",
        temp_critical: float = 0.1,
        temp_normal: float = 0.3,
        temp_relaxed: float = 0.5,
        summary_interval: int = 10,
        summary_max_tokens: int = 256,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._model_fast = model_fast
        self._sim_client = sim_client
        self._context_store = context_store
        self._conversation: list[dict[str, Any]] = []
        self._max_history = max_history
        self._max_tokens = max_tokens
        self._max_tokens_briefing = max_tokens_briefing
        self._temperature = temperature
        self._temp_critical = temp_critical
        self._temp_normal = temp_normal
        self._temp_relaxed = temp_relaxed
        self._summary_interval = summary_interval
        self._summary_max_tokens = summary_max_tokens
        self._conversation_summary: str = ""
        self._turns_since_summary: int = 0
        self._procedure_executor = ProcedureExecutor(sim_client)
        self._command_verifier = CommandVerifier(sim_client)
        self._command_history = CommandHistory()

    def _build_system_prompt(
        self,
        sim_state: SimState,
        context_docs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        # Block 1 (cached): static persona + response pacing rules.
        # These never change between calls, so we mark them for ephemeral
        # caching to reduce time-to-first-token and API cost.
        static_text = MERLIN_PERSONA + _RESPONSE_PACING
        static_block: dict[str, Any] = {
            "type": "text",
            "text": static_text,
            "cache_control": {"type": "ephemeral"},
        }

        # Block 2 (not cached): dynamic flight context that changes per turn.
        dynamic_parts: list[str] = []

        # Flight-phase-aware response style
        phase = sim_state.flight_phase
        if phase in _PHASE_STYLE:
            dynamic_parts.append(f"\n--- CURRENT RESPONSE STYLE ---\n{_PHASE_STYLE[phase]}")

        dynamic_parts.append(f"\n--- CURRENT FLIGHT STATE ---\n{sim_state.telemetry_summary()}")
        dynamic_parts.append(f"Aircraft: {sim_state.aircraft or 'Unknown'}")
        dynamic_parts.append(f"On ground: {sim_state.on_ground}")

        if sim_state.autopilot.master:
            ap = sim_state.autopilot
            dynamic_parts.append(
                f"Autopilot: HDG {ap.heading:.0f} | ALT {ap.altitude:.0f} | "
                f"VS {ap.vertical_speed:+.0f} | IAS {ap.airspeed:.0f}"
            )

        env = sim_state.environment
        dynamic_parts.append(
            f"Weather: Wind {env.wind_direction:.0f}\u00b0/"
            f"{env.wind_speed_kts:.0f}kt | "
            f"Vis {env.visibility_sm:.0f}sm | "
            f"Temp {env.temperature_c:.0f}\u00b0C | "
            f'QNH {env.barometer_inhg:.2f}"Hg'
        )

        if self._conversation_summary:
            dynamic_parts.append("\n--- FLIGHT SESSION SUMMARY ---\n" + self._conversation_summary)

        if context_docs:
            dynamic_parts.append("\n--- RELEVANT REFERENCE MATERIAL ---")
            for doc in context_docs[:3]:
                source = doc.get("metadata", {}).get("source", "unknown")
                dynamic_parts.append(f"[{source}]\n{doc['content'][:500]}")

        dynamic_block: dict[str, Any] = {
            "type": "text",
            "text": "\n".join(dynamic_parts),
        }

        return [static_block, dynamic_block]

    async def chat(
        self,
        user_message: str,
        sim_state: SimState | None = None,
        image_base64: str | None = None,
        on_tool_result: Callable[[str, dict[str, Any], Any], None] | None = None,
    ) -> AsyncIterator[str]:
        """Send a message and yield streamed response text chunks.

        Handles tool use loops internally, yielding text as it arrives.

        Args:
            on_tool_result: Optional callback invoked after each tool execution
                with (tool_name, tool_input, tool_result). Useful for notifying
                callers about command executions.
        """
        if sim_state is None:
            try:
                sim_state = await self._sim_client.get_state()
            except Exception:
                sim_state = SimState()

        context_docs = await self._context_store.get_relevant_context(sim_state)
        system = self._build_system_prompt(sim_state, context_docs)

        # Classify the query to set an appropriate token budget
        query_type = classify_query(user_message)
        effective_max_tokens = max_tokens_for_query(
            query_type,
            default_max=self._max_tokens,
            briefing_max=self._max_tokens_briefing,
        )

        # Dynamic temperature based on flight phase and query type
        effective_temp = get_temperature_for_context(
            sim_state.flight_phase,
            query_type,
            temp_critical=self._temp_critical,
            temp_normal=self._temp_normal,
            temp_relaxed=self._temp_relaxed,
        )

        # Model routing: short queries → fast model, everything else → default
        effective_model = get_model_for_query(
            query_type,
            model_default=self._model,
            model_fast=self._model_fast,
        )

        # Build user message content
        content: list[dict[str, Any]] = []
        if image_base64:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_base64,
                    },
                }
            )
        content.append({"type": "text", "text": user_message})

        self._conversation.append({"role": "user", "content": content})
        self._trim_history()
        await self._maybe_summarize()

        # Agentic loop: keep going while Claude wants to use tools
        while True:
            collected_text = ""
            tool_use_blocks: list[dict[str, Any]] = []
            current_tool_input = ""
            current_tool_id = ""
            current_tool_name = ""
            stop_reason = None

            async with self._client.messages.stream(
                model=effective_model,
                max_tokens=effective_max_tokens,
                system=system,
                messages=self._conversation,
                tools=TOOL_DEFINITIONS,
                stop_sequences=STOP_SEQUENCES,
                temperature=effective_temp,
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
                            tool_input = (
                                json.loads(current_tool_input) if current_tool_input else {}
                            )
                            tool_use_blocks.append(
                                {
                                    "id": current_tool_id,
                                    "name": current_tool_name,
                                    "input": tool_input,
                                }
                            )
                            current_tool_name = ""
                    elif event.type == "message_delta":
                        stop_reason = event.delta.stop_reason

            # Record assistant turn
            assistant_content: list[dict[str, Any]] = []
            if collected_text:
                assistant_content.append({"type": "text", "text": collected_text})
            for tb in tool_use_blocks:
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": tb["id"],
                        "name": tb["name"],
                        "input": tb["input"],
                    }
                )
            self._conversation.append({"role": "assistant", "content": assistant_content})

            if stop_reason != "tool_use" or not tool_use_blocks:
                break

            # Execute tools and feed results back
            tool_results: list[dict[str, Any]] = []
            for tb in tool_use_blocks:
                result = await self._execute_tool(tb["name"], tb["input"], sim_state)
                if on_tool_result is not None:
                    try:
                        on_tool_result(tb["name"], tb["input"], result)
                    except Exception:
                        logger.warning("on_tool_result callback failed", exc_info=True)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tb["id"],
                        "content": json.dumps(result),
                    }
                )
            self._conversation.append({"role": "user", "content": tool_results})

    # Timeout configuration per tool category (seconds)
    _TOOL_TIMEOUTS: dict[str, float] = {
        "get_sim_state": 2.0,
        "lookup_airport": 10.0,
        "search_manual": 5.0,
        "get_checklist": 5.0,
        "create_flight_plan": 10.0,
        "set_aircraft_control": 5.0,
        "undo_last_command": 5.0,
        "execute_procedure": 30.0,
    }
    _DEFAULT_TOOL_TIMEOUT: float = 5.0

    async def _execute_tool(self, name: str, args: dict[str, Any], sim_state: SimState) -> Any:
        logger.info("Executing tool: %s(%s)", name, args)
        timeout = self._TOOL_TIMEOUTS.get(name, self._DEFAULT_TOOL_TIMEOUT)
        try:
            result = await asyncio.wait_for(
                self._dispatch_tool(name, args, sim_state),
                timeout=timeout,
            )
            return result
        except TimeoutError:
            logger.warning("Tool %s timed out after %.1fs", name, timeout)
            return {"error": f"Tool '{name}' timed out after {timeout:.0f} seconds"}
        except Exception as e:
            logger.exception("Tool execution failed: %s", name)
            return {"error": str(e)}

    async def _dispatch_tool(self, name: str, args: dict[str, Any], sim_state: SimState) -> Any:
        """Route tool call to the appropriate handler."""
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
        elif name == "set_aircraft_control":
            return await set_aircraft_control(
                self._sim_client,
                args["system"],
                args["action"],
                value=args.get("value"),
                verifier=self._command_verifier,
                command_history=self._command_history,
            )
        elif name == "undo_last_command":
            return await undo_last_command(
                self._sim_client,
                self._command_history,
                verifier=self._command_verifier,
            )
        elif name == "execute_procedure":
            proc = get_procedure(args["procedure"])
            if proc is None:
                available = ", ".join(PROCEDURES.keys())
                return {"error": f"Unknown procedure: {args['procedure']}. Available: {available}"}
            result = await self._procedure_executor.execute(proc)
            return result.to_dict()
        else:
            return {"error": f"Unknown tool: {name}"}

    def clear_history(self) -> None:
        self._conversation.clear()
        self._conversation_summary = ""
        self._turns_since_summary = 0

    async def _maybe_summarize(self) -> None:
        """Generate a rolling summary of old conversation history.

        Every N turns, summarize the oldest messages being trimmed and
        inject the summary into the system prompt. This preserves key
        decisions, commitments, and flight-relevant facts across long
        sessions without consuming the full context window.
        """
        self._turns_since_summary += 1
        if self._turns_since_summary < self._summary_interval:
            return
        if len(self._conversation) <= self._max_history:
            return

        self._turns_since_summary = 0

        # Extract the messages that will be trimmed
        trim_count = len(self._conversation) - self._max_history
        old_messages = self._conversation[:trim_count]

        # Build a text representation of old messages for summarization
        summary_input: list[str] = []
        for msg in old_messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    c.get("text", "") for c in content if isinstance(c, dict) and "text" in c
                ]
                content = " ".join(text_parts)
            if content:
                summary_input.append(f"{role}: {content[:200]}")

        if not summary_input:
            return

        prior_summary = ""
        if self._conversation_summary:
            prior_summary = f"Previous summary: {self._conversation_summary}\n\n"

        try:
            response = await self._client.messages.create(
                model=self._model_fast,  # Use Haiku for summaries
                max_tokens=self._summary_max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"{prior_summary}"
                            "Summarize the key decisions, commitments, and flight-relevant "
                            "facts from this conversation. Focus on: diversion plans, weather "
                            "briefings, clearances received, altitude/heading assignments, "
                            "fuel state discussions, and any problems discussed. Be concise.\n\n"
                            + "\n".join(summary_input)
                        ),
                    }
                ],
                temperature=0.1,
            )
            self._conversation_summary = response.content[0].text
            logger.info(
                "Generated conversation summary (%d chars)",
                len(self._conversation_summary),
            )
        except Exception:
            logger.warning("Failed to generate conversation summary", exc_info=True)

    def _trim_history(self) -> None:
        if len(self._conversation) > self._max_history * 2:
            self._conversation = self._conversation[-(self._max_history * 2) :]
