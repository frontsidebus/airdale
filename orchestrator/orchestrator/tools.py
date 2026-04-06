"""Tool implementations callable by Claude during conversations."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .context_store import ContextStore
from .sim_client import FlightPhase, TelemetryClient

# ---------------------------------------------------------------------------
# Aircraft control commands
# ---------------------------------------------------------------------------

# Commands that affect critical systems — Claude should confirm with the pilot
CRITICAL_COMMANDS = {
    "GEAR_UP",
    "GEAR_DOWN",
    "GEAR_TOGGLE",
    "AP_MASTER",
    "PARKING_BRAKES",
}


def _resolve_command(
    system: str, action: str, value: float | None
) -> tuple[str | None, int]:
    """Translate human-friendly system/action/value to (SimConnect event, dwData)."""
    system = system.lower()
    action = action.lower()

    if system == "flaps":
        if action == "set" and value is not None:
            # Accept notch (0-4) or percentage (0-100)
            if value <= 4:
                return "FLAPS_SET", int(value * 16383 / 4)
            return "FLAPS_SET", int(value * 16383 / 100)
        if action in ("up", "retract"):
            return "FLAPS_UP", 0
        if action in ("full", "down"):
            return "FLAPS_FULL", 0
        if action == "1" or action == "10":
            return "FLAPS_1", 0
        if action == "2" or action == "20":
            return "FLAPS_2", 0
        if action == "3" or action == "30":
            return "FLAPS_3", 0
        if action in ("incr", "increase"):
            return "FLAPS_INCR", 0
        if action in ("decr", "decrease"):
            return "FLAPS_DECR", 0

    elif system == "gear":
        if action in ("up", "retract"):
            return "GEAR_UP", 0
        if action in ("down", "extend"):
            return "GEAR_DOWN", 0
        if action == "toggle":
            return "GEAR_TOGGLE", 0

    elif system == "autopilot":
        if action in ("on", "off", "toggle"):
            return "AP_MASTER", 0
        if action == "heading" and value is not None:
            return "HEADING_BUG_SET", int(value)
        if action == "heading_hold":
            return "AP_HDG_HOLD", 0
        if action == "altitude" and value is not None:
            return "AP_ALT_VAR_SET_ENGLISH", int(value)
        if action == "altitude_hold":
            return "AP_ALT_HOLD", 0
        if action == "vertical_speed" and value is not None:
            return "AP_VS_VAR_SET_ENGLISH", int(value)
        if action == "vs_hold":
            return "AP_VS_HOLD", 0
        if action == "speed" and value is not None:
            return "AP_SPD_VAR_SET", int(value)
        if action == "speed_hold":
            return "AP_AIRSPEED_HOLD", 0
        if action == "nav":
            return "AP_NAV1_HOLD", 0
        if action == "approach":
            return "AP_APR_HOLD", 0

    elif system == "throttle":
        if action == "set" and value is not None:
            return "THROTTLE_SET", int(value * 16383 / 100)

    elif system == "radio":
        if action == "com1" and value is not None:
            return "COM_RADIO_SET_HZ", int(value * 1_000_000)
        if action == "com2" and value is not None:
            return "COM2_RADIO_SET_HZ", int(value * 1_000_000)
        if action == "nav1" and value is not None:
            return "NAV1_RADIO_SET_HZ", int(value * 1_000_000)
        if action == "nav2" and value is not None:
            return "NAV2_RADIO_SET_HZ", int(value * 1_000_000)

    elif system == "barometer":
        if action == "set" and value is not None:
            return "KOHLSMAN_SET", int(value * 100)

    elif system == "trim":
        if action == "set" and value is not None:
            return "ELEVATOR_TRIM_SET", int(value)
        if action in ("up", "nose_up"):
            return "ELEV_TRIM_UP", 0
        if action in ("down", "nose_down"):
            return "ELEV_TRIM_DN", 0
        if action == "rudder_left":
            return "RUDDER_TRIM_LEFT", 0
        if action == "rudder_right":
            return "RUDDER_TRIM_RIGHT", 0
        if action == "rudder_set" and value is not None:
            return "RUDDER_TRIM_SET", int(value)
        if action == "aileron_left":
            return "AILERON_TRIM_LEFT", 0
        if action == "aileron_right":
            return "AILERON_TRIM_RIGHT", 0
        if action == "aileron_set" and value is not None:
            return "AILERON_TRIM_SET", int(value)

    elif system == "deice":
        if action in ("pitot", "pitot_heat"):
            return "PITOT_HEAT_TOGGLE", 0
        if action in ("structural", "airframe"):
            return "TOGGLE_STRUCTURAL_DEICE", 0
        if action == "windshield":
            return "WINDSHIELD_DEICE_TOGGLE", 0
        if action in ("props", "prop_deice"):
            return "TOGGLE_PROPELLER_DEICE", 0

    elif system == "parking_brake":
        return "PARKING_BRAKES", 0

    elif system == "spoilers":
        if action == "toggle":
            return "SPOILERS_TOGGLE", 0
        if action == "set" and value is not None:
            return "SPOILERS_SET", int(value * 16383 / 100)

    elif system == "mixture":
        if action == "set" and value is not None:
            return "MIXTURE_SET", int(value * 16383 / 100)

    elif system == "propeller":
        if action == "set" and value is not None:
            return "PROP_PITCH_SET", int(value * 16383 / 100)

    elif system == "fuel_selector":
        if action == "off":
            return "FUEL_SELECTOR_OFF", 0
        if action in ("all", "both"):
            return "FUEL_SELECTOR_ALL", 0
        if action == "left":
            return "FUEL_SELECTOR_LEFT", 0
        if action == "right":
            return "FUEL_SELECTOR_RIGHT", 0
        if action == "set" and value is not None:
            return "FUEL_SELECTOR_SET", int(value)

    elif system == "crossfeed":
        if action in ("open", "on"):
            return "CROSS_FEED_OPEN", 0
        if action in ("close", "off"):
            return "CROSS_FEED_OFF", 0
        if action == "toggle":
            return "CROSS_FEED_TOGGLE", 0

    elif system == "magnetos":
        positions = {"off": 0, "right": 1, "left": 2, "both": 3, "start": 4}
        if action in positions:
            return "MAGNETO_SET", positions[action]

    elif system == "carb_heat":
        if action in ("on", "off", "toggle"):
            return "ANTI_ICE_CARB_HEAT_TOGGLE", 0

    elif system == "fuel_pump":
        if action in ("on", "off", "toggle"):
            return "FUEL_PUMP_TOGGLE", 0

    elif system == "starter":
        if action in ("engage", "start"):
            return "TOGGLE_STARTER1", 0

    elif system == "primer":
        if action in ("prime", "pump"):
            return "TOGGLE_PRIMER", 0

    elif system == "lights":
        if action in ("landing", "landing_on"):
            return "LANDING_LIGHTS_TOGGLE", 0
        if action in ("taxi", "taxi_on"):
            return "TOGGLE_TAXI_LIGHTS", 0
        if action in ("nav", "navigation"):
            return "TOGGLE_NAV_LIGHTS", 0
        if action == "beacon":
            return "TOGGLE_BEACON_LIGHTS", 0
        if action == "strobe":
            return "STROBES_TOGGLE", 0
        if action == "panel":
            return "PANEL_LIGHTS_TOGGLE", 0

    return None, 0


async def set_aircraft_control(
    sim_client: TelemetryClient,
    system: str,
    action: str,
    value: float | None = None,
) -> dict[str, Any]:
    """Execute a sim control command via the telemetry service."""
    command, sim_value = _resolve_command(system, action, value)

    if command is None:
        return {"error": f"Unknown control: system={system}, action={action}"}

    result = await sim_client.send_command(command, sim_value)
    logger.info("Command result for %s: %s", command, result)
    result["command"] = command
    result["sim_value"] = sim_value

    if command in CRITICAL_COMMANDS:
        result["safety_note"] = "Critical system change executed"

    return result

logger = logging.getLogger(__name__)

# Phase-appropriate checklists (simplified defaults; real ones come from the context store)
DEFAULT_CHECKLISTS: dict[FlightPhase, list[str]] = {
    FlightPhase.PREFLIGHT: [
        "Documents - CHECK (ARROW)",
        "Weather briefing - OBTAINED",
        "NOTAMs - REVIEWED",
        "Weight and balance - COMPUTED",
        "Fuel - CHECKED AND SUFFICIENT",
        "Preflight inspection - COMPLETE",
        "Seat belts - FASTENED",
        "Circuit breakers - CHECK",
    ],
    FlightPhase.TAXI: [
        "Brakes - TEST",
        "Flight instruments - CHECK",
        "Radios - SET",
        "Transponder - SET",
        "Taxi clearance - OBTAINED",
    ],
    FlightPhase.TAKEOFF: [
        "Flaps - SET FOR TAKEOFF",
        "Trim - SET",
        "Mixture - RICH (or as required)",
        "Fuel pump - ON",
        "Lights - ON",
        "Doors - SECURE",
        "Controls - FREE AND CORRECT",
        "Takeoff clearance - OBTAINED",
    ],
    FlightPhase.CLIMB: [
        "Flaps - RETRACT on schedule",
        "Power - SET climb power",
        "Mixture - ADJUST for altitude",
        "Engine gauges - GREEN",
        "Fuel pump - AS REQUIRED",
    ],
    FlightPhase.CRUISE: [
        "Power - SET cruise power",
        "Mixture - LEAN as required",
        "Engine gauges - MONITOR",
        "Fuel management - CHECK",
        "Navigation - VERIFY",
    ],
    FlightPhase.DESCENT: [
        "ATIS/Weather - OBTAIN",
        "Altimeter - SET",
        "Approach briefing - COMPLETE",
        "Fuel pump - ON",
        "Seat belts - SECURE",
    ],
    FlightPhase.APPROACH: [
        "Approach type - IDENTIFIED",
        "Minimums - SET",
        "Missed approach - BRIEFED",
        "Gear - DOWN (if retractable)",
        "Flaps - AS REQUIRED",
        "Speed - ON TARGET",
    ],
    FlightPhase.LANDING: [
        "Gear - CONFIRMED DOWN",
        "Flaps - FULL (as required)",
        "Speed - Vref + corrections",
        "Runway - CLEAR",
    ],
    FlightPhase.LANDED: [
        "Flaps - RETRACT",
        "Transponder - STANDBY",
        "Lights - AS REQUIRED",
        "Mixture - CUTOFF (shutdown)",
        "Master switch - OFF (shutdown)",
    ],
}


async def get_sim_state(sim_client: TelemetryClient) -> dict[str, Any]:
    """Return formatted current telemetry."""
    try:
        state = await sim_client.get_state()
    except ConnectionError:
        return {"error": "Not connected to simulator"}

    # Build active engine data from the new per-engine model
    active = state.engines.active_engines
    engine_data: dict[str, Any] = {
        "engine_count": state.engines.engine_count,
        "engines": [
            {
                "rpm": round(e.rpm),
                "manifold_pressure": round(e.manifold_pressure, 1),
                "fuel_flow_gph": round(e.fuel_flow_gph, 1),
                "egt": round(e.egt),
                "oil_temp": round(e.oil_temp),
                "oil_pressure": round(e.oil_pressure),
            }
            for e in active
        ],
    }

    return {
        "aircraft": state.aircraft,
        "flight_phase": state.flight_phase.value,
        "position": {
            "lat": round(state.position.latitude, 6),
            "lon": round(state.position.longitude, 6),
            "altitude_msl": round(state.position.altitude_msl),
            "altitude_agl": round(state.position.altitude_agl),
        },
        "attitude": {
            "pitch": round(state.attitude.pitch, 1),
            "bank": round(state.attitude.bank, 1),
            "heading_magnetic": round(state.attitude.heading_magnetic),
            "heading_true": round(state.attitude.heading_true),
        },
        "speeds": {
            "indicated_airspeed": round(state.speeds.indicated_airspeed),
            "true_airspeed": round(state.speeds.true_airspeed),
            "ground_speed": round(state.speeds.ground_speed),
            "mach": round(state.speeds.mach, 3),
            "vertical_speed": round(state.speeds.vertical_speed),
        },
        "engines": engine_data,
        "autopilot": {
            "master": state.autopilot.master,
            "heading": round(state.autopilot.heading),
            "altitude": round(state.autopilot.altitude),
            "vertical_speed": round(state.autopilot.vertical_speed),
            "airspeed": round(state.autopilot.airspeed),
        },
        "fuel": {
            "total_gallons": round(state.fuel.total_gallons, 1),
            "total_weight_lbs": round(state.fuel.total_weight_lbs, 1),
        },
        "environment": {
            "wind": (
                f"{round(state.environment.wind_direction)}° at "
                f"{round(state.environment.wind_speed_kts)}kt"
            ),
            "visibility_sm": round(state.environment.visibility_sm, 1),
            "temperature_c": round(state.environment.temperature_c),
            "barometer_inhg": round(state.environment.barometer_inhg, 2),
        },
        "surfaces": {
            "gear_handle": state.surfaces.gear_handle,
            "flaps_percent": round(state.surfaces.flaps_percent),
            "spoilers_percent": round(state.surfaces.spoilers_percent),
        },
        "on_ground": state.on_ground,
    }


async def lookup_airport(identifier: str) -> dict[str, Any]:
    """Look up airport information from the Aviation API."""
    identifier = identifier.strip().upper()
    if not identifier.startswith("K") and len(identifier) == 3:
        identifier = f"K{identifier}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                "https://api.aviationapi.com/v1/airports",
                params={"apt": identifier},
            )
            resp.raise_for_status()
            data = resp.json()

            if identifier in data and data[identifier]:
                raw = data[identifier]
                apt = raw[0] if isinstance(raw, list) else raw
                return {
                    "identifier": identifier,
                    "name": apt.get("facility_name", "Unknown"),
                    "city": apt.get("city", ""),
                    "state": apt.get("state_full", ""),
                    "elevation": apt.get("elevation", ""),
                    "latitude": apt.get("latitude", ""),
                    "longitude": apt.get("longitude", ""),
                    "status": apt.get("status_code", ""),
                }

            return {"error": f"Airport {identifier} not found"}

        except httpx.HTTPError as e:
            logger.warning("Airport lookup failed for %s: %s", identifier, e)
            return {"error": f"Lookup failed: {e}"}


async def search_manual(
    query: str,
    context_store: ContextStore,
    aircraft_type: str = "",
    n_results: int = 5,
) -> list[dict[str, Any]]:
    """Search the aircraft manual / knowledge base via vector store."""
    filters = None
    if aircraft_type:
        filters = {"aircraft_type": aircraft_type}

    results = await context_store.query(query, n_results=n_results, filters=filters)
    return [
        {"content": r["content"], "source": r["metadata"].get("source", "unknown")} for r in results
    ]


async def get_checklist(
    phase: str | FlightPhase,
    context_store: ContextStore,
    aircraft_type: str = "",
) -> dict[str, Any]:
    """Return the checklist appropriate for the given flight phase.

    Accepts the phase as a string (case-insensitive) or a FlightPhase enum.
    """
    if isinstance(phase, str):
        phase_upper = phase.strip().upper()
        try:
            phase = FlightPhase(phase_upper)
        except ValueError:
            # Try matching by enum name as well
            matched = None
            for fp in FlightPhase:
                if fp.value == phase_upper or fp.name == phase_upper:
                    matched = fp
                    break
            if matched is None:
                valid = ", ".join(fp.value for fp in FlightPhase)
                return {"error": f"Unknown flight phase: {phase}. Valid phases: {valid}"}
            phase = matched

    # Try to find an aircraft-specific checklist in the knowledge base
    if aircraft_type:
        results = await context_store.query(
            f"{aircraft_type} {phase.value.lower()} checklist",
            n_results=1,
            filters={"aircraft_type": aircraft_type},
        )
        if results:
            return {
                "phase": phase.value,
                "aircraft": aircraft_type,
                "source": "aircraft_manual",
                "checklist": results[0]["content"],
            }

    # Fall back to generic checklist
    items = DEFAULT_CHECKLISTS.get(phase, ["No checklist available for this phase"])
    return {
        "phase": phase.value,
        "aircraft": aircraft_type or "generic",
        "source": "default",
        "items": items,
    }


async def create_flight_plan(
    departure: str,
    destination: str,
    altitude: int = 5000,
    route: str = "",
) -> dict[str, Any]:
    """Build a basic flight plan route structure."""
    dep_info = await lookup_airport(departure)
    dest_info = await lookup_airport(destination)

    waypoints = [departure.upper()]
    if route:
        waypoints.extend(w.strip().upper() for w in route.split() if w.strip())
    waypoints.append(destination.upper())

    return {
        "departure": dep_info,
        "destination": dest_info,
        "cruise_altitude": altitude,
        "route": " ".join(waypoints),
        "waypoints": waypoints,
        "status": "draft",
        "notes": "This is a draft plan. Verify airways, altitudes, and NOTAMs before use.",
    }
