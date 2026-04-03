"""Generate realistic SimState snapshots for MERLIN fine-tuning training data.

Produces dicts matching the exact SimState JSON structure from the orchestrator
without requiring the orchestrator package at import time.
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure orchestrator package is importable
_ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2] / "orchestrator"
if str(_ORCHESTRATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATOR_ROOT))

from orchestrator.sim_client import (  # noqa: E402
    Attitude,
    AutopilotState,
    EngineData,
    Engines,
    Environment,
    FlightPhase,
    FuelState,
    Position,
    RadioState,
    SimState,
    Speeds,
    SurfaceState,
)

from tools.generate_dataset.aircraft import AircraftProfile  # noqa: E402

# ---------------------------------------------------------------------------
# Weather presets
# ---------------------------------------------------------------------------

_WEATHER_PRESETS: dict[str, dict[str, tuple[float, float]]] = {
    "CAVU": {
        "wind_speed": (0, 8),
        "wind_direction": (0, 360),
        "visibility": (10, 15),
        "temperature": (15, 25),
        "qnh": (29.80, 30.10),
    },
    "marginal_vfr": {
        "wind_speed": (8, 18),
        "wind_direction": (0, 360),
        "visibility": (3, 5),
        "temperature": (5, 30),
        "qnh": (29.70, 30.00),
    },
    "IFR": {
        "wind_speed": (10, 25),
        "wind_direction": (0, 360),
        "visibility": (1, 3),
        "temperature": (0, 20),
        "qnh": (29.50, 29.90),
    },
    "crosswind": {
        "wind_speed": (12, 25),
        "wind_direction": (0, 360),  # overridden relative to runway
        "visibility": (8, 15),
        "temperature": (10, 28),
        "qnh": (29.80, 30.10),
    },
    "turbulence": {
        "wind_speed": (15, 30),
        "wind_direction": (0, 360),
        "visibility": (5, 10),
        "temperature": (5, 25),
        "qnh": (29.60, 30.00),
    },
    "icing": {
        "wind_speed": (5, 20),
        "wind_direction": (0, 360),
        "visibility": (2, 5),
        "temperature": (-5, 2),
        "qnh": (29.50, 29.90),
    },
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _uniform(rng: random.Random, lo: float, hi: float) -> float:
    return rng.uniform(lo, hi)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _round2(value: float) -> float:
    return round(value, 2)


def _make_environment(
    rng: random.Random,
    weather: str,
    runway_heading: float | None = None,
) -> dict[str, Any]:
    """Build an Environment-compatible dict for a weather preset."""
    preset = _WEATHER_PRESETS.get(weather, _WEATHER_PRESETS["CAVU"])

    wind_speed = _round2(_uniform(rng, *preset["wind_speed"]))
    wind_dir = _round2(_uniform(rng, *preset["wind_direction"]))
    visibility = _round2(_uniform(rng, *preset["visibility"]))
    temperature = _round2(_uniform(rng, *preset["temperature"]))
    qnh = _round2(_uniform(rng, *preset["qnh"]))

    # For crosswind, offset wind direction 60-90 degrees from runway
    if weather == "crosswind" and runway_heading is not None:
        offset = rng.choice([-1, 1]) * _uniform(rng, 60, 90)
        wind_dir = _round2((runway_heading + offset) % 360)

    return {
        "wind_speed_kts": wind_speed,
        "wind_direction": wind_dir,
        "visibility_sm": visibility,
        "temperature_c": temperature,
        "barometer_inhg": qnh,
    }


def _make_engine_data(
    rng: random.Random,
    aircraft: AircraftProfile,
    phase: str,
) -> dict[str, Any]:
    """Build an Engines-compatible dict for a given phase/aircraft."""
    engine_list: list[dict[str, float]] = []

    for _ in range(aircraft.engine_count):
        if aircraft.engine_type == "piston":
            eng = _piston_engine(rng, aircraft, phase)
        elif aircraft.engine_type == "turboprop":
            eng = _turboprop_engine(rng, aircraft, phase)
        else:
            eng = _turbofan_engine(rng, aircraft, phase)
        engine_list.append(eng)

    return {
        "engine_count": aircraft.engine_count,
        "engines": engine_list,
    }


def _piston_engine(
    rng: random.Random, ac: AircraftProfile, phase: str
) -> dict[str, float]:
    """Generate piston engine parameters by flight phase."""
    cruise_rpm = ac.typical_cruise_rpm or 2400
    cruise_mp = ac.typical_cruise_mp or 23.0

    if phase in ("PREFLIGHT", "LANDED"):
        rpm = _uniform(rng, 700, 1000)
        mp = _uniform(rng, 12, 15)
        ff = _uniform(rng, 2.0, 3.5)
    elif phase == "TAXI":
        rpm = _uniform(rng, 900, 1200)
        mp = _uniform(rng, 14, 18)
        ff = _uniform(rng, 3.0, 5.0)
    elif phase == "TAKEOFF":
        rpm = _uniform(rng, cruise_rpm + 100, cruise_rpm + 350)
        mp = _uniform(rng, cruise_mp + 3, cruise_mp + 6)
        ff = _uniform(rng, ac.fuel_burn_gph * 1.3, ac.fuel_burn_gph * 1.6)
    elif phase == "CLIMB":
        rpm = _uniform(rng, cruise_rpm, cruise_rpm + 200)
        mp = _uniform(rng, cruise_mp + 1, cruise_mp + 4)
        ff = _uniform(rng, ac.fuel_burn_gph * 1.1, ac.fuel_burn_gph * 1.3)
    elif phase == "CRUISE":
        rpm = _uniform(rng, cruise_rpm - 100, cruise_rpm + 50)
        mp = _uniform(rng, cruise_mp - 1, cruise_mp + 1)
        ff = _uniform(rng, ac.fuel_burn_gph * 0.9, ac.fuel_burn_gph * 1.1)
    elif phase in ("DESCENT", "APPROACH"):
        rpm = _uniform(rng, cruise_rpm - 400, cruise_rpm - 100)
        mp = _uniform(rng, 15, cruise_mp - 2)
        ff = _uniform(rng, ac.fuel_burn_gph * 0.4, ac.fuel_burn_gph * 0.7)
    elif phase == "LANDING":
        rpm = _uniform(rng, cruise_rpm - 500, cruise_rpm - 200)
        mp = _uniform(rng, 14, 18)
        ff = _uniform(rng, ac.fuel_burn_gph * 0.3, ac.fuel_burn_gph * 0.6)
    else:
        rpm = _uniform(rng, 700, 1000)
        mp = _uniform(rng, 12, 15)
        ff = _uniform(rng, 2.0, 3.5)

    return {
        "rpm": _round2(rpm),
        "manifold_pressure": _round2(mp),
        "fuel_flow_gph": _round2(ff),
        "egt": _round2(_uniform(rng, 1200, 1500)),
        "oil_temp": _round2(_uniform(rng, 170, 220)),
        "oil_pressure": _round2(_uniform(rng, 55, 80)),
    }


def _turboprop_engine(
    rng: random.Random, ac: AircraftProfile, phase: str
) -> dict[str, float]:
    """Generate turboprop engine parameters by flight phase."""
    cruise_n1 = ac.typical_cruise_n1 or 96.0

    if phase in ("PREFLIGHT", "LANDED"):
        n1 = _uniform(rng, 20, 40)
        ff = _uniform(rng, 5, 15)
    elif phase == "TAXI":
        n1 = _uniform(rng, 40, 55)
        ff = _uniform(rng, 10, 20)
    elif phase == "TAKEOFF":
        n1 = _uniform(rng, 98, 101)
        ff = ac.fuel_burn_gph * _uniform(rng, 1.3, 1.5) / ac.engine_count
    elif phase == "CLIMB":
        n1 = _uniform(rng, 92, 98)
        ff = ac.fuel_burn_gph * _uniform(rng, 1.1, 1.3) / ac.engine_count
    elif phase == "CRUISE":
        n1 = _uniform(rng, cruise_n1 - 3, cruise_n1 + 1)
        ff = ac.fuel_burn_gph * _uniform(rng, 0.9, 1.1) / ac.engine_count
    elif phase in ("DESCENT", "APPROACH"):
        n1 = _uniform(rng, 50, 75)
        ff = ac.fuel_burn_gph * _uniform(rng, 0.3, 0.6) / ac.engine_count
    elif phase == "LANDING":
        n1 = _uniform(rng, 40, 60)
        ff = ac.fuel_burn_gph * _uniform(rng, 0.2, 0.4) / ac.engine_count
    else:
        n1 = _uniform(rng, 20, 40)
        ff = _uniform(rng, 5, 15)

    return {
        "rpm": _round2(n1),  # N1 mapped to RPM field for turboprops
        "manifold_pressure": 0.0,
        "fuel_flow_gph": _round2(ff),
        "egt": _round2(_uniform(rng, 600, 850)),
        "oil_temp": _round2(_uniform(rng, 60, 100)),
        "oil_pressure": _round2(_uniform(rng, 40, 70)),
    }


def _turbofan_engine(
    rng: random.Random, ac: AircraftProfile, phase: str
) -> dict[str, float]:
    """Generate turbofan engine parameters by flight phase."""
    cruise_n1 = ac.typical_cruise_n1 or 87.0

    if phase in ("PREFLIGHT", "LANDED"):
        n1 = _uniform(rng, 18, 25)
        ff = _uniform(rng, 10, 30)
    elif phase == "TAXI":
        n1 = _uniform(rng, 22, 35)
        ff = _uniform(rng, 20, 50)
    elif phase == "TAKEOFF":
        n1 = _uniform(rng, 92, 100)
        ff = ac.fuel_burn_gph * _uniform(rng, 1.3, 1.6) / ac.engine_count
    elif phase == "CLIMB":
        n1 = _uniform(rng, 85, 95)
        ff = ac.fuel_burn_gph * _uniform(rng, 1.0, 1.3) / ac.engine_count
    elif phase == "CRUISE":
        n1 = _uniform(rng, cruise_n1 - 3, cruise_n1 + 2)
        ff = ac.fuel_burn_gph * _uniform(rng, 0.9, 1.1) / ac.engine_count
    elif phase in ("DESCENT", "APPROACH"):
        n1 = _uniform(rng, 35, 60)
        ff = ac.fuel_burn_gph * _uniform(rng, 0.2, 0.5) / ac.engine_count
    elif phase == "LANDING":
        n1 = _uniform(rng, 30, 50)
        ff = ac.fuel_burn_gph * _uniform(rng, 0.15, 0.35) / ac.engine_count
    else:
        n1 = _uniform(rng, 18, 25)
        ff = _uniform(rng, 10, 30)

    return {
        "rpm": _round2(n1),  # N1 mapped to RPM field for jets
        "manifold_pressure": 0.0,
        "fuel_flow_gph": _round2(ff),
        "egt": _round2(_uniform(rng, 450, 700)),
        "oil_temp": _round2(_uniform(rng, 50, 90)),
        "oil_pressure": _round2(_uniform(rng, 35, 65)),
    }


def _make_radio_state(rng: random.Random) -> dict[str, float]:
    """Generate plausible COM/NAV frequencies."""
    com_freqs = [118.0, 118.3, 119.1, 120.9, 121.5, 122.8, 123.0, 124.0,
                 125.5, 126.2, 127.85, 128.35, 132.45, 133.9, 134.1]
    nav_freqs = [108.1, 109.3, 109.9, 110.1, 110.9, 111.3, 112.0, 113.0,
                 114.1, 115.0, 116.8, 117.3, 117.95]
    return {
        "com1": rng.choice(com_freqs),
        "com2": rng.choice(com_freqs),
        "nav1": rng.choice(nav_freqs),
        "nav2": rng.choice(nav_freqs),
    }


# ---------------------------------------------------------------------------
# Phase-specific state builders
# ---------------------------------------------------------------------------


def _state_preflight(
    rng: random.Random, ac: AircraftProfile, env: dict[str, Any]
) -> dict[str, Any]:
    field_elev = _uniform(rng, 0, 500)
    heading = _round2(_uniform(rng, 0, 360))
    lat = _round2(_uniform(rng, 25, 48))
    lon = _round2(_uniform(rng, -122, -72))

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connected": True,
        "aircraft": ac.name,
        "position": {
            "latitude": lat,
            "longitude": lon,
            "altitude_msl": _round2(field_elev),
            "altitude_agl": 0.0,
        },
        "attitude": {
            "pitch": 0.0,
            "bank": 0.0,
            "heading_true": heading,
            "heading_magnetic": _round2((heading + _uniform(rng, -15, 15)) % 360),
        },
        "speeds": {
            "indicated_airspeed": 0.0,
            "true_airspeed": 0.0,
            "ground_speed": 0.0,
            "mach": 0.0,
            "vertical_speed": 0.0,
        },
        "engines": _make_engine_data(rng, ac, "PREFLIGHT"),
        "autopilot": {
            "master": False,
            "heading": heading,
            "altitude": _round2(field_elev),
            "vertical_speed": 0.0,
            "airspeed": 0.0,
        },
        "radios": _make_radio_state(rng),
        "fuel": {
            "total_gallons": _round2(ac.fuel_capacity_gal * _uniform(rng, 0.6, 1.0)),
            "total_weight_lbs": 0.0,  # will be filled below
        },
        "environment": env,
        "surfaces": {
            "gear_handle": True,
            "flaps_percent": 0.0,
            "spoilers_percent": 0.0,
        },
        "flight_phase": "PREFLIGHT",
    }


def _state_taxi(
    rng: random.Random, ac: AircraftProfile, env: dict[str, Any]
) -> dict[str, Any]:
    field_elev = _uniform(rng, 0, 500)
    heading = _round2(_uniform(rng, 0, 360))
    gs = _round2(_uniform(rng, 5, 20))
    lat = _round2(_uniform(rng, 25, 48))
    lon = _round2(_uniform(rng, -122, -72))

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connected": True,
        "aircraft": ac.name,
        "position": {
            "latitude": lat,
            "longitude": lon,
            "altitude_msl": _round2(field_elev),
            "altitude_agl": 0.0,
        },
        "attitude": {
            "pitch": 0.0,
            "bank": _round2(_uniform(rng, -3, 3)),
            "heading_true": heading,
            "heading_magnetic": _round2((heading + _uniform(rng, -15, 15)) % 360),
        },
        "speeds": {
            "indicated_airspeed": _round2(gs * 0.9),
            "true_airspeed": _round2(gs * 0.9),
            "ground_speed": gs,
            "mach": 0.0,
            "vertical_speed": 0.0,
        },
        "engines": _make_engine_data(rng, ac, "TAXI"),
        "autopilot": {
            "master": False,
            "heading": heading,
            "altitude": _round2(field_elev),
            "vertical_speed": 0.0,
            "airspeed": 0.0,
        },
        "radios": _make_radio_state(rng),
        "fuel": {
            "total_gallons": _round2(ac.fuel_capacity_gal * _uniform(rng, 0.6, 1.0)),
            "total_weight_lbs": 0.0,
        },
        "environment": env,
        "surfaces": {
            "gear_handle": True,
            "flaps_percent": 0.0,
            "spoilers_percent": 0.0,
        },
        "flight_phase": "TAXI",
    }


def _state_takeoff(
    rng: random.Random, ac: AircraftProfile, env: dict[str, Any]
) -> dict[str, Any]:
    field_elev = _uniform(rng, 0, 500)
    heading = _round2(_uniform(rng, 0, 360))
    ias = _round2(_uniform(rng, ac.vr - 5, ac.vr + 10))
    vs = _round2(_uniform(rng, 0, 500))
    agl = _round2(_uniform(rng, 0, 50))
    lat = _round2(_uniform(rng, 25, 48))
    lon = _round2(_uniform(rng, -122, -72))

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connected": True,
        "aircraft": ac.name,
        "position": {
            "latitude": lat,
            "longitude": lon,
            "altitude_msl": _round2(field_elev + agl),
            "altitude_agl": agl,
        },
        "attitude": {
            "pitch": _round2(_uniform(rng, 5, 15)),
            "bank": _round2(_uniform(rng, -3, 3)),
            "heading_true": heading,
            "heading_magnetic": _round2((heading + _uniform(rng, -15, 15)) % 360),
        },
        "speeds": {
            "indicated_airspeed": ias,
            "true_airspeed": _round2(ias * 1.02),
            "ground_speed": _round2(ias + _uniform(rng, -10, 10)),
            "mach": _round2(ias / 660),
            "vertical_speed": vs,
        },
        "engines": _make_engine_data(rng, ac, "TAKEOFF"),
        "autopilot": {
            "master": False,
            "heading": heading,
            "altitude": _round2(field_elev + 3000),
            "vertical_speed": 0.0,
            "airspeed": _round2(float(ac.vy)),
        },
        "radios": _make_radio_state(rng),
        "fuel": {
            "total_gallons": _round2(ac.fuel_capacity_gal * _uniform(rng, 0.7, 1.0)),
            "total_weight_lbs": 0.0,
        },
        "environment": env,
        "surfaces": {
            "gear_handle": True,
            "flaps_percent": _round2(_uniform(rng, 0, 25)),
            "spoilers_percent": 0.0,
        },
        "flight_phase": "TAKEOFF",
    }


def _state_climb(
    rng: random.Random, ac: AircraftProfile, env: dict[str, Any]
) -> dict[str, Any]:
    agl = _round2(_uniform(rng, 500, 15000))
    field_elev = _uniform(rng, 0, 500)
    msl = _round2(field_elev + agl)
    heading = _round2(_uniform(rng, 0, 360))
    ias = _round2(_uniform(rng, ac.vy - 10, ac.vy + 15))
    vs = _round2(_uniform(rng, 500, ac.climb_rate_fpm))
    lat = _round2(_uniform(rng, 25, 48))
    lon = _round2(_uniform(rng, -122, -72))

    ap_on = rng.random() > 0.4

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connected": True,
        "aircraft": ac.name,
        "position": {
            "latitude": lat,
            "longitude": lon,
            "altitude_msl": msl,
            "altitude_agl": agl,
        },
        "attitude": {
            "pitch": _round2(_uniform(rng, 5, 12)),
            "bank": _round2(_uniform(rng, -10, 10)),
            "heading_true": heading,
            "heading_magnetic": _round2((heading + _uniform(rng, -15, 15)) % 360),
        },
        "speeds": {
            "indicated_airspeed": ias,
            "true_airspeed": _round2(ias * (1 + msl * 0.00002)),
            "ground_speed": _round2(ias + _uniform(rng, -15, 25)),
            "mach": _round2(ias / 660),
            "vertical_speed": vs,
        },
        "engines": _make_engine_data(rng, ac, "CLIMB"),
        "autopilot": {
            "master": ap_on,
            "heading": heading,
            "altitude": _round2(float(ac.typical_cruise_altitude)),
            "vertical_speed": vs if ap_on else 0.0,
            "airspeed": ias if ap_on else 0.0,
        },
        "radios": _make_radio_state(rng),
        "fuel": {
            "total_gallons": _round2(ac.fuel_capacity_gal * _uniform(rng, 0.6, 0.95)),
            "total_weight_lbs": 0.0,
        },
        "environment": env,
        "surfaces": {
            "gear_handle": not ac.has_retractable_gear or rng.random() < 0.1,
            "flaps_percent": _round2(_uniform(rng, 0, 10)) if agl < 1000 else 0.0,
            "spoilers_percent": 0.0,
        },
        "flight_phase": "CLIMB",
    }


def _state_cruise(
    rng: random.Random, ac: AircraftProfile, env: dict[str, Any]
) -> dict[str, Any]:
    alt = _round2(ac.typical_cruise_altitude + _uniform(rng, -500, 500))
    heading = _round2(_uniform(rng, 0, 360))
    ias = _round2(_uniform(rng, ac.cruise_speed_kias - 10, ac.cruise_speed_kias + 10))
    vs = _round2(_uniform(rng, -100, 100))
    lat = _round2(_uniform(rng, 25, 48))
    lon = _round2(_uniform(rng, -122, -72))

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connected": True,
        "aircraft": ac.name,
        "position": {
            "latitude": lat,
            "longitude": lon,
            "altitude_msl": alt,
            "altitude_agl": _round2(alt - _uniform(rng, 0, 500)),
        },
        "attitude": {
            "pitch": _round2(_uniform(rng, -2, 3)),
            "bank": _round2(_uniform(rng, -5, 5)),
            "heading_true": heading,
            "heading_magnetic": _round2((heading + _uniform(rng, -15, 15)) % 360),
        },
        "speeds": {
            "indicated_airspeed": ias,
            "true_airspeed": _round2(ias * (1 + alt * 0.00002)),
            "ground_speed": _round2(ias + _uniform(rng, -20, 30)),
            "mach": _round2(ias / 660),
            "vertical_speed": vs,
        },
        "engines": _make_engine_data(rng, ac, "CRUISE"),
        "autopilot": {
            "master": rng.random() > 0.2,
            "heading": heading,
            "altitude": alt,
            "vertical_speed": 0.0,
            "airspeed": ias,
        },
        "radios": _make_radio_state(rng),
        "fuel": {
            "total_gallons": _round2(ac.fuel_capacity_gal * _uniform(rng, 0.35, 0.85)),
            "total_weight_lbs": 0.0,
        },
        "environment": env,
        "surfaces": {
            "gear_handle": False if ac.has_retractable_gear else True,
            "flaps_percent": 0.0,
            "spoilers_percent": 0.0,
        },
        "flight_phase": "CRUISE",
    }


def _state_descent(
    rng: random.Random, ac: AircraftProfile, env: dict[str, Any]
) -> dict[str, Any]:
    alt = _round2(_uniform(rng, 3000, ac.typical_cruise_altitude - 2000))
    heading = _round2(_uniform(rng, 0, 360))
    ias = _round2(_uniform(rng, ac.cruise_speed_kias * 0.7, ac.cruise_speed_kias))
    vs = _round2(_uniform(rng, -1500, -500))
    lat = _round2(_uniform(rng, 25, 48))
    lon = _round2(_uniform(rng, -122, -72))

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connected": True,
        "aircraft": ac.name,
        "position": {
            "latitude": lat,
            "longitude": lon,
            "altitude_msl": alt,
            "altitude_agl": _round2(alt - _uniform(rng, 0, 500)),
        },
        "attitude": {
            "pitch": _round2(_uniform(rng, -5, 0)),
            "bank": _round2(_uniform(rng, -10, 10)),
            "heading_true": heading,
            "heading_magnetic": _round2((heading + _uniform(rng, -15, 15)) % 360),
        },
        "speeds": {
            "indicated_airspeed": ias,
            "true_airspeed": _round2(ias * (1 + alt * 0.00002)),
            "ground_speed": _round2(ias + _uniform(rng, -15, 20)),
            "mach": _round2(ias / 660),
            "vertical_speed": vs,
        },
        "engines": _make_engine_data(rng, ac, "DESCENT"),
        "autopilot": {
            "master": rng.random() > 0.3,
            "heading": heading,
            "altitude": _round2(_uniform(rng, 2000, 5000)),
            "vertical_speed": vs,
            "airspeed": ias,
        },
        "radios": _make_radio_state(rng),
        "fuel": {
            "total_gallons": _round2(ac.fuel_capacity_gal * _uniform(rng, 0.2, 0.6)),
            "total_weight_lbs": 0.0,
        },
        "environment": env,
        "surfaces": {
            "gear_handle": False if ac.has_retractable_gear else True,
            "flaps_percent": 0.0,
            "spoilers_percent": _round2(_uniform(rng, 0, 15)),
        },
        "flight_phase": "DESCENT",
    }


def _state_approach(
    rng: random.Random, ac: AircraftProfile, env: dict[str, Any]
) -> dict[str, Any]:
    agl = _round2(_uniform(rng, 500, 3000))
    field_elev = _uniform(rng, 0, 500)
    msl = _round2(field_elev + agl)
    heading = _round2(_uniform(rng, 0, 360))
    ias = _round2(_uniform(rng, ac.vref + 10, ac.vref + 30))
    vs = _round2(_uniform(rng, -800, -300))
    lat = _round2(_uniform(rng, 25, 48))
    lon = _round2(_uniform(rng, -122, -72))

    gear_down = ac.has_retractable_gear  # gear goes down on approach
    flaps = _round2(_uniform(rng, 15, 60))

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connected": True,
        "aircraft": ac.name,
        "position": {
            "latitude": lat,
            "longitude": lon,
            "altitude_msl": msl,
            "altitude_agl": agl,
        },
        "attitude": {
            "pitch": _round2(_uniform(rng, -5, 2)),
            "bank": _round2(_uniform(rng, -15, 15)),
            "heading_true": heading,
            "heading_magnetic": _round2((heading + _uniform(rng, -15, 15)) % 360),
        },
        "speeds": {
            "indicated_airspeed": ias,
            "true_airspeed": _round2(ias * (1 + msl * 0.00002)),
            "ground_speed": _round2(ias + _uniform(rng, -10, 10)),
            "mach": _round2(ias / 660),
            "vertical_speed": vs,
        },
        "engines": _make_engine_data(rng, ac, "APPROACH"),
        "autopilot": {
            "master": rng.random() > 0.5,
            "heading": heading,
            "altitude": _round2(field_elev + 200),
            "vertical_speed": vs,
            "airspeed": ias,
        },
        "radios": _make_radio_state(rng),
        "fuel": {
            "total_gallons": _round2(ac.fuel_capacity_gal * _uniform(rng, 0.15, 0.5)),
            "total_weight_lbs": 0.0,
        },
        "environment": env,
        "surfaces": {
            "gear_handle": gear_down or True,
            "flaps_percent": flaps,
            "spoilers_percent": 0.0,
        },
        "flight_phase": "APPROACH",
    }


def _state_landing(
    rng: random.Random, ac: AircraftProfile, env: dict[str, Any]
) -> dict[str, Any]:
    agl = _round2(_uniform(rng, 50, 200))
    field_elev = _uniform(rng, 0, 500)
    msl = _round2(field_elev + agl)
    heading = _round2(_uniform(rng, 0, 360))
    ias = _round2(_uniform(rng, ac.vref - 5, ac.vref + 10))
    vs = _round2(_uniform(rng, -700, -300))
    lat = _round2(_uniform(rng, 25, 48))
    lon = _round2(_uniform(rng, -122, -72))

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connected": True,
        "aircraft": ac.name,
        "position": {
            "latitude": lat,
            "longitude": lon,
            "altitude_msl": msl,
            "altitude_agl": agl,
        },
        "attitude": {
            "pitch": _round2(_uniform(rng, -2, 5)),
            "bank": _round2(_uniform(rng, -5, 5)),
            "heading_true": heading,
            "heading_magnetic": _round2((heading + _uniform(rng, -15, 15)) % 360),
        },
        "speeds": {
            "indicated_airspeed": ias,
            "true_airspeed": _round2(ias * 1.01),
            "ground_speed": _round2(ias + _uniform(rng, -8, 8)),
            "mach": _round2(ias / 660),
            "vertical_speed": vs,
        },
        "engines": _make_engine_data(rng, ac, "LANDING"),
        "autopilot": {
            "master": False,
            "heading": heading,
            "altitude": _round2(field_elev),
            "vertical_speed": 0.0,
            "airspeed": 0.0,
        },
        "radios": _make_radio_state(rng),
        "fuel": {
            "total_gallons": _round2(ac.fuel_capacity_gal * _uniform(rng, 0.1, 0.45)),
            "total_weight_lbs": 0.0,
        },
        "environment": env,
        "surfaces": {
            "gear_handle": True,
            "flaps_percent": 100.0,
            "spoilers_percent": 0.0,
        },
        "flight_phase": "LANDING",
    }


def _state_landed(
    rng: random.Random, ac: AircraftProfile, env: dict[str, Any]
) -> dict[str, Any]:
    field_elev = _uniform(rng, 0, 500)
    heading = _round2(_uniform(rng, 0, 360))
    gs = _round2(_uniform(rng, 5, 60))
    lat = _round2(_uniform(rng, 25, 48))
    lon = _round2(_uniform(rng, -122, -72))

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connected": True,
        "aircraft": ac.name,
        "position": {
            "latitude": lat,
            "longitude": lon,
            "altitude_msl": _round2(field_elev),
            "altitude_agl": 0.0,
        },
        "attitude": {
            "pitch": _round2(_uniform(rng, -2, 1)),
            "bank": _round2(_uniform(rng, -2, 2)),
            "heading_true": heading,
            "heading_magnetic": _round2((heading + _uniform(rng, -15, 15)) % 360),
        },
        "speeds": {
            "indicated_airspeed": _round2(gs * 0.9),
            "true_airspeed": _round2(gs * 0.9),
            "ground_speed": gs,
            "mach": 0.0,
            "vertical_speed": 0.0,
        },
        "engines": _make_engine_data(rng, ac, "LANDED"),
        "autopilot": {
            "master": False,
            "heading": heading,
            "altitude": _round2(field_elev),
            "vertical_speed": 0.0,
            "airspeed": 0.0,
        },
        "radios": _make_radio_state(rng),
        "fuel": {
            "total_gallons": _round2(ac.fuel_capacity_gal * _uniform(rng, 0.1, 0.4)),
            "total_weight_lbs": 0.0,
        },
        "environment": env,
        "surfaces": {
            "gear_handle": True,
            "flaps_percent": 100.0,
            "spoilers_percent": _round2(_uniform(rng, 0, 50)),
        },
        "flight_phase": "LANDED",
    }


# Map phase names to builder functions
_PHASE_BUILDERS: dict[str, Any] = {
    "PREFLIGHT": _state_preflight,
    "TAXI": _state_taxi,
    "TAKEOFF": _state_takeoff,
    "CLIMB": _state_climb,
    "CRUISE": _state_cruise,
    "DESCENT": _state_descent,
    "APPROACH": _state_approach,
    "LANDING": _state_landing,
    "LANDED": _state_landed,
}

# Fuel weight: 6.0 lbs per gallon of avgas
_FUEL_LBS_PER_GAL = 6.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_sim_state(
    phase: str,
    aircraft: AircraftProfile,
    weather: str = "CAVU",
    seed: int | None = None,
) -> dict:
    """Generate a realistic SimState dict for a given phase and aircraft.

    Parameters
    ----------
    phase:
        One of the FlightPhase values (PREFLIGHT, TAXI, TAKEOFF, etc.).
    aircraft:
        An AircraftProfile with performance data.
    weather:
        One of "CAVU", "marginal_vfr", "IFR", "crosswind", "turbulence", "icing".
    seed:
        Optional random seed for reproducibility.

    Returns
    -------
    dict
        A dict matching the exact SimState JSON structure.
    """
    rng = random.Random(seed)
    phase_upper = phase.upper()

    builder = _PHASE_BUILDERS.get(phase_upper)
    if builder is None:
        raise ValueError(
            f"Unknown phase {phase!r}. Valid phases: {list(_PHASE_BUILDERS)}"
        )

    runway_heading = _round2(_uniform(rng, 0, 360))
    env = _make_environment(rng, weather, runway_heading=runway_heading)
    state = builder(rng, aircraft, env)

    # Fill in fuel weight from gallons
    fuel_gal = state["fuel"]["total_gallons"]
    state["fuel"]["total_weight_lbs"] = _round2(fuel_gal * _FUEL_LBS_PER_GAL)

    # Validate against the real Pydantic model to catch structural errors
    SimState.model_validate(state)

    return state


def evolve_sim_state(
    base_state: dict,
    phase: str,
    elapsed_seconds: float = 30.0,
) -> dict:
    """Evolve a sim state slightly for multi-turn conversations.

    Fuel decreases, altitude changes slightly if climbing/descending, etc.
    The returned dict is a new copy -- the original is not modified.

    Parameters
    ----------
    base_state:
        An existing SimState dict (as produced by generate_sim_state).
    phase:
        The current flight phase (may differ from the phase in base_state).
    elapsed_seconds:
        Seconds elapsed since the base_state snapshot.

    Returns
    -------
    dict
        An updated SimState dict.
    """
    import copy

    state = copy.deepcopy(base_state)
    phase_upper = phase.upper()
    state["flight_phase"] = phase_upper
    state["timestamp"] = datetime.now(timezone.utc).isoformat()

    elapsed_hours = elapsed_seconds / 3600.0
    elapsed_minutes = elapsed_seconds / 60.0

    # Burn fuel
    engines_data = state.get("engines", {})
    total_ff = sum(
        e.get("fuel_flow_gph", 0) for e in engines_data.get("engines", [])
    )
    fuel_burned = total_ff * elapsed_hours
    fuel = state.get("fuel", {})
    new_gal = max(0.0, fuel.get("total_gallons", 0) - fuel_burned)
    fuel["total_gallons"] = _round2(new_gal)
    fuel["total_weight_lbs"] = _round2(new_gal * _FUEL_LBS_PER_GAL)

    # Altitude changes based on vertical speed
    vs = state.get("speeds", {}).get("vertical_speed", 0)
    alt_change = vs * elapsed_minutes  # VS is ft/min
    pos = state.get("position", {})
    new_msl = max(0.0, pos.get("altitude_msl", 0) + alt_change)
    pos["altitude_msl"] = _round2(new_msl)

    agl = pos.get("altitude_agl", 0)
    new_agl = max(0.0, agl + alt_change)
    pos["altitude_agl"] = _round2(new_agl)

    # Slight heading drift
    att = state.get("attitude", {})
    hdg = att.get("heading_magnetic", 0)
    att["heading_magnetic"] = _round2((hdg + random.uniform(-2, 2)) % 360)
    hdg_true = att.get("heading_true", 0)
    att["heading_true"] = _round2((hdg_true + random.uniform(-2, 2)) % 360)

    # Ground state: if we descended to ground, snap AGL to 0
    if phase_upper in ("LANDED", "TAXI", "PREFLIGHT"):
        pos["altitude_agl"] = 0.0
        state["speeds"]["vertical_speed"] = 0.0
        state["speeds"]["ground_speed"] = _round2(
            _clamp(state["speeds"].get("ground_speed", 0) - 5, 0, 60)
        )

    return state
