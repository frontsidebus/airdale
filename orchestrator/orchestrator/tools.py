"""Tool implementations callable by Claude during conversations."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .context_store import ContextStore
from .sim_client import FlightPhase, SimConnectClient, SimState

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


async def get_sim_state(sim_client: SimConnectClient) -> dict[str, Any]:
    """Return formatted current telemetry."""
    state = await sim_client.get_state()
    return {
        "aircraft": state.aircraft_title,
        "flight_phase": state.flight_phase.value,
        "position": {
            "lat": round(state.position.latitude, 6),
            "lon": round(state.position.longitude, 6),
            "altitude_msl": round(state.position.altitude),
            "altitude_agl": round(state.position.altitude_agl),
        },
        "attitude": {
            "pitch": round(state.attitude.pitch, 1),
            "bank": round(state.attitude.bank, 1),
            "heading": round(state.attitude.heading),
        },
        "speeds": {
            "indicated": round(state.speeds.indicated),
            "true_airspeed": round(state.speeds.true_airspeed),
            "ground_speed": round(state.speeds.ground_speed),
            "mach": round(state.speeds.mach, 3),
            "vertical_speed": round(state.speeds.vertical_speed),
        },
        "engine": {
            "rpm": [round(r) for r in state.engine.rpm],
            "fuel_flow": [round(f, 1) for f in state.engine.fuel_flow],
            "oil_temp": [round(t) for t in state.engine.oil_temp],
            "oil_pressure": [round(p) for p in state.engine.oil_pressure],
        },
        "autopilot": {
            "engaged": state.autopilot.master,
            "heading": round(state.autopilot.set_heading),
            "altitude": round(state.autopilot.set_altitude),
        },
        "fuel": {
            "total_gallons": round(state.fuel.total, 1),
            "total_weight_lbs": round(state.fuel.total_weight, 1),
        },
        "environment": {
            "wind": f"{round(state.environment.wind_direction)}° at {round(state.environment.wind_speed)}kt",
            "visibility_sm": round(state.environment.visibility, 1),
            "temperature_c": round(state.environment.temperature),
            "altimeter_inhg": round(state.environment.pressure, 2),
        },
        "surfaces": {
            "gear_down": state.surfaces.gear_down,
            "flaps": state.surfaces.flaps_position,
            "spoilers": state.surfaces.spoilers_deployed,
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
                f"https://api.aviationapi.com/v1/airports",
                params={"apt": identifier},
            )
            resp.raise_for_status()
            data = resp.json()

            if identifier in data and data[identifier]:
                apt = data[identifier][0] if isinstance(data[identifier], list) else data[identifier]
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
        {"content": r["content"], "source": r["metadata"].get("source", "unknown")}
        for r in results
    ]


async def get_checklist(
    phase: str | FlightPhase,
    context_store: ContextStore,
    aircraft_type: str = "",
) -> dict[str, Any]:
    """Return the checklist appropriate for the given flight phase."""
    if isinstance(phase, str):
        try:
            phase = FlightPhase(phase.upper())
        except ValueError:
            return {"error": f"Unknown flight phase: {phase}"}

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
