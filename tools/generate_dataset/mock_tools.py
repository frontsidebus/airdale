"""Generate realistic mock tool responses for MERLIN fine-tuning data.

Each function produces output matching the exact format returned by the
real orchestrator tools, so that training conversations contain authentic
tool-call/tool-response pairs.
"""

from __future__ import annotations

import json
import math
import random
from typing import Any

# ---------------------------------------------------------------------------
# Common airports database
# ---------------------------------------------------------------------------

COMMON_AIRPORTS: dict[str, dict[str, Any]] = {
    "KJFK": {
        "identifier": "KJFK",
        "facility_name": "John F Kennedy International",
        "city": "New York",
        "state": "NY",
        "elevation": 13,
        "latitude": 40.6398,
        "longitude": -73.7789,
        "status_code": "O",
    },
    "KLAX": {
        "identifier": "KLAX",
        "facility_name": "Los Angeles International",
        "city": "Los Angeles",
        "state": "CA",
        "elevation": 128,
        "latitude": 33.9425,
        "longitude": -118.4081,
        "status_code": "O",
    },
    "KATL": {
        "identifier": "KATL",
        "facility_name": "Hartsfield-Jackson Atlanta International",
        "city": "Atlanta",
        "state": "GA",
        "elevation": 1026,
        "latitude": 33.6367,
        "longitude": -84.4281,
        "status_code": "O",
    },
    "KORD": {
        "identifier": "KORD",
        "facility_name": "Chicago O'Hare International",
        "city": "Chicago",
        "state": "IL",
        "elevation": 672,
        "latitude": 41.9742,
        "longitude": -87.9073,
        "status_code": "O",
    },
    "KDFW": {
        "identifier": "KDFW",
        "facility_name": "Dallas/Fort Worth International",
        "city": "Dallas-Fort Worth",
        "state": "TX",
        "elevation": 607,
        "latitude": 32.8968,
        "longitude": -97.0380,
        "status_code": "O",
    },
    "KSFO": {
        "identifier": "KSFO",
        "facility_name": "San Francisco International",
        "city": "San Francisco",
        "state": "CA",
        "elevation": 13,
        "latitude": 37.6213,
        "longitude": -122.3790,
        "status_code": "O",
    },
    "KDEN": {
        "identifier": "KDEN",
        "facility_name": "Denver International",
        "city": "Denver",
        "state": "CO",
        "elevation": 5431,
        "latitude": 39.8561,
        "longitude": -104.6737,
        "status_code": "O",
    },
    "KMIA": {
        "identifier": "KMIA",
        "facility_name": "Miami International",
        "city": "Miami",
        "state": "FL",
        "elevation": 8,
        "latitude": 25.7959,
        "longitude": -80.2870,
        "status_code": "O",
    },
    "KBOS": {
        "identifier": "KBOS",
        "facility_name": "General Edward Lawrence Logan International",
        "city": "Boston",
        "state": "MA",
        "elevation": 20,
        "latitude": 42.3656,
        "longitude": -71.0096,
        "status_code": "O",
    },
    "KPDK": {
        "identifier": "KPDK",
        "facility_name": "DeKalb-Peachtree",
        "city": "Atlanta",
        "state": "GA",
        "elevation": 1003,
        "latitude": 33.8756,
        "longitude": -84.3020,
        "status_code": "O",
    },
    "KORL": {
        "identifier": "KORL",
        "facility_name": "Orlando Executive",
        "city": "Orlando",
        "state": "FL",
        "elevation": 113,
        "latitude": 28.5455,
        "longitude": -81.3329,
        "status_code": "O",
    },
    "KFXE": {
        "identifier": "KFXE",
        "facility_name": "Fort Lauderdale Executive",
        "city": "Fort Lauderdale",
        "state": "FL",
        "elevation": 13,
        "latitude": 26.1973,
        "longitude": -80.1707,
        "status_code": "O",
    },
    "KOSH": {
        "identifier": "KOSH",
        "facility_name": "Wittman Regional",
        "city": "Oshkosh",
        "state": "WI",
        "elevation": 808,
        "latitude": 43.9844,
        "longitude": -88.5570,
        "status_code": "O",
    },
    "KSNA": {
        "identifier": "KSNA",
        "facility_name": "John Wayne Airport-Orange County",
        "city": "Santa Ana",
        "state": "CA",
        "elevation": 56,
        "latitude": 33.6762,
        "longitude": -117.8674,
        "status_code": "O",
    },
    "KSDL": {
        "identifier": "KSDL",
        "facility_name": "Scottsdale",
        "city": "Scottsdale",
        "state": "AZ",
        "elevation": 1510,
        "latitude": 33.6229,
        "longitude": -111.9106,
        "status_code": "O",
    },
    "KVNY": {
        "identifier": "KVNY",
        "facility_name": "Van Nuys",
        "city": "Van Nuys",
        "state": "CA",
        "elevation": 802,
        "latitude": 34.2098,
        "longitude": -118.4900,
        "status_code": "O",
    },
    "KTEB": {
        "identifier": "KTEB",
        "facility_name": "Teterboro",
        "city": "Teterboro",
        "state": "NJ",
        "elevation": 9,
        "latitude": 40.8501,
        "longitude": -74.0608,
        "status_code": "O",
    },
    "KHPN": {
        "identifier": "KHPN",
        "facility_name": "Westchester County",
        "city": "White Plains",
        "state": "NY",
        "elevation": 439,
        "latitude": 41.0670,
        "longitude": -73.7076,
        "status_code": "O",
    },
    "KBED": {
        "identifier": "KBED",
        "facility_name": "Laurence G Hanscom Field",
        "city": "Bedford",
        "state": "MA",
        "elevation": 133,
        "latitude": 42.4700,
        "longitude": -71.2890,
        "status_code": "O",
    },
    "KPWK": {
        "identifier": "KPWK",
        "facility_name": "Chicago Executive",
        "city": "Chicago/Prospect Heights/Wheeling",
        "state": "IL",
        "elevation": 647,
        "latitude": 42.1142,
        "longitude": -87.9015,
        "status_code": "O",
    },
}

# ---------------------------------------------------------------------------
# Manual snippets bank
# ---------------------------------------------------------------------------

_MANUAL_SNIPPETS: list[dict[str, Any]] = [
    # V-speeds
    {"content": "Vr (Rotation Speed): Rotate at this speed during takeoff to initiate climb. For standard conditions at max gross weight, Vr is specified in the Performance section. Ensure appropriate back-pressure to achieve a positive rate of climb.", "source": "POH Section 5.2", "tags": ["vr", "rotation", "takeoff", "v-speed"]},
    {"content": "Vy (Best Rate of Climb): This speed provides the greatest gain in altitude per unit of time. Use Vy for normal climb operations unless obstacle clearance is required. Vy decreases with altitude.", "source": "POH Section 5.3", "tags": ["vy", "climb", "v-speed", "best rate"]},
    {"content": "Vx (Best Angle of Climb): This speed provides the greatest gain in altitude per unit of horizontal distance. Use Vx for obstacle clearance immediately after takeoff. Vx is lower than Vy.", "source": "POH Section 5.3", "tags": ["vx", "climb", "v-speed", "best angle", "obstacle"]},
    {"content": "Vref (Reference Landing Speed): Approach at Vref + wind correction factor. In gusty conditions, add half the gust factor to Vref. Maintain stabilized approach speed until flare.", "source": "POH Section 5.8", "tags": ["vref", "landing", "approach", "v-speed"]},
    {"content": "Vne (Never Exceed Speed): The red line on the airspeed indicator. Flight above Vne may result in structural damage or failure. This speed must not be exceeded in any flight condition.", "source": "POH Section 2.1", "tags": ["vne", "limitations", "v-speed", "structural"]},
    {"content": "Va (Maneuvering Speed): Do not apply full or abrupt control inputs above Va. Va decreases with decreasing weight. At max gross weight, Va is specified in the Limitations section.", "source": "POH Section 2.2", "tags": ["va", "maneuvering", "v-speed", "turbulence"]},
    # Emergency procedures
    {"content": "ENGINE FAILURE DURING TAKEOFF (before liftoff): Throttle - IDLE. Brakes - APPLY. Flaps - RETRACT. Mixture - IDLE CUT-OFF. Ignition - OFF. Master Switch - OFF (when safe).", "source": "POH Section 3.1", "tags": ["engine failure", "takeoff", "emergency", "abort"]},
    {"content": "ENGINE FAILURE IN FLIGHT: Airspeed - BEST GLIDE. Fuel Selector - SWITCH TANKS. Mixture - RICH. Carburetor Heat - ON. Magnetos - CHECK (both, then individual). Primer - IN and LOCKED.", "source": "POH Section 3.2", "tags": ["engine failure", "flight", "emergency", "restart", "glide"]},
    {"content": "ENGINE FIRE IN FLIGHT: Mixture - IDLE CUT-OFF. Fuel Selector - OFF. Master Switch - OFF. Cabin Heat and Air - OFF. Airspeed - INCREASE to extinguish. Execute forced landing.", "source": "POH Section 3.3", "tags": ["engine fire", "fire", "emergency", "in flight"]},
    {"content": "ELECTRICAL FIRE IN FLIGHT: Master Switch - OFF. All electrical switches - OFF. Vents/Cabin Air - OPEN (to clear smoke). If fire extinguishes, Master Switch - ON. Check circuits individually.", "source": "POH Section 3.4", "tags": ["electrical fire", "fire", "emergency", "smoke"]},
    {"content": "EMERGENCY LANDING WITHOUT ENGINE POWER: Establish best glide speed immediately. Select suitable landing area. When field is assured: Flaps - AS REQUIRED. Touchdown - SLIGHTLY TAIL LOW. Ignition - OFF before touchdown.", "source": "POH Section 3.5", "tags": ["emergency landing", "forced landing", "engine failure", "glide"]},
    {"content": "SPIN RECOVERY: Throttle - IDLE. Ailerons - NEUTRAL. Rudder - FULL OPPOSITE to spin direction. Control Wheel - BRISKLY FORWARD through neutral. Rudder - NEUTRAL after rotation stops. Recover from dive.", "source": "POH Section 3.6", "tags": ["spin", "recovery", "emergency", "stall"]},
    # Engine operations
    {"content": "ENGINE START (Normal): Preflight inspection - COMPLETE. Brakes - SET. Fuel Selector - BOTH. Mixture - RICH. Carburetor Heat - COLD. Prime - AS REQUIRED (2-6 strokes in cold weather). Throttle - OPEN 1/4 INCH. Master - ON. Beacon - ON. Ignition - START.", "source": "POH Section 4.1", "tags": ["engine start", "normal", "procedure"]},
    {"content": "ENGINE WARM-UP: Run at 1000-1200 RPM until oil temperature reaches the green arc. Avoid prolonged idling below 1000 RPM. Check oil pressure within 30 seconds of start; if no pressure, shut down immediately.", "source": "POH Section 4.2", "tags": ["warm-up", "engine", "oil pressure", "temperature"]},
    {"content": "MIXTURE LEANING: Above 3000 feet density altitude, lean mixture for best economy. Lean by reducing mixture until RPM peaks, then enrichen slightly. For best power, lean to peak RPM. Always enrichen mixture before increasing power.", "source": "POH Section 4.5", "tags": ["mixture", "leaning", "fuel", "economy", "power"]},
    {"content": "MAGNETO CHECK: At 1800 RPM, check each magneto individually. Maximum RPM drop: 150 RPM. Maximum differential between magnetos: 50 RPM. If drop exceeds limits, the engine is not airworthy.", "source": "POH Section 4.3", "tags": ["magneto", "runup", "check", "rpm"]},
    # Fuel systems
    {"content": "FUEL SYSTEM: Two wing tanks (left and right) connected to a fuel selector valve. BOTH position feeds from both tanks simultaneously. Check fuel quantity visually before each flight. Minimum fuel for VFR day: 30 minutes reserve at cruise.", "source": "POH Section 7.1", "tags": ["fuel", "system", "tanks", "selector", "reserve"]},
    {"content": "FUEL MANAGEMENT: Monitor fuel burn rate and remaining fuel regularly. Switch tanks every 30 minutes during cruise to maintain balance. Total usable fuel capacity is less than total tank capacity due to unusable fuel.", "source": "POH Section 7.2", "tags": ["fuel", "management", "balance", "endurance"]},
    {"content": "FUEL CONTAMINATION: Drain fuel sumps before every flight. Check for water (clear droplets or blue-tinted water at bottom), sediment, and proper fuel color (100LL is blue). Contaminated fuel must be completely drained.", "source": "POH Section 7.3", "tags": ["fuel", "contamination", "sump", "water", "preflight"]},
    # Electrical systems
    {"content": "ELECTRICAL SYSTEM: 28-volt direct current system powered by engine-driven alternator and 24-volt battery. Circuit breakers protect all circuits. If a breaker pops, allow to cool before resetting. Do not reset a breaker more than once.", "source": "POH Section 7.4", "tags": ["electrical", "system", "alternator", "battery", "breaker"]},
    {"content": "ALTERNATOR FAILURE: LOW VOLTAGE annunciator illuminates. Non-essential electrical load - REDUCE. If voltage does not recover: Alternator - OFF. Conserve battery for essential systems. Land as soon as practical.", "source": "POH Section 3.7", "tags": ["alternator", "failure", "electrical", "emergency", "battery"]},
    # Flight controls
    {"content": "FLAP OPERATION: Flaps are electrically actuated. Available positions: 0°, 10°, 20°, 30° (full). Do not exceed Vfe (flap extended speed) with flaps deployed. Use 10° flaps for short-field takeoff.", "source": "POH Section 7.5", "tags": ["flaps", "controls", "operation", "speed"]},
    {"content": "TRIM SYSTEM: Manual elevator trim via trim wheel. Trim for hands-off flight at desired airspeed. Nose-up trim for slow flight and climb. Verify trim set for takeoff before every departure.", "source": "POH Section 7.6", "tags": ["trim", "elevator", "controls"]},
    # Autopilot
    {"content": "AUTOPILOT OPERATION: Engage autopilot above 800 feet AGL. Modes: HDG (heading hold), NAV (navigation tracking), APR (approach), ALT (altitude hold), VS (vertical speed). Always monitor autopilot performance and be prepared to disconnect.", "source": "POH Section 7.7", "tags": ["autopilot", "operation", "modes", "engagement"]},
    {"content": "AUTOPILOT DISCONNECT: Press the red disconnect button on the control yoke, or press the AP button on the autopilot panel. If autopilot fails to disconnect, pull the AP circuit breaker. Always hand-fly through turbulence if AP performance is erratic.", "source": "POH Section 7.8", "tags": ["autopilot", "disconnect", "failure", "override"]},
    # Landing gear
    {"content": "LANDING GEAR OPERATION: Retractable gear is hydraulically actuated. Extend gear below Vle (gear extended speed). Verify three green lights before landing. Emergency gear extension available via manual release handle.", "source": "POH Section 7.9", "tags": ["landing gear", "retractable", "operation", "hydraulic"]},
    {"content": "LANDING GEAR EMERGENCY EXTENSION: If normal extension fails, reduce speed below Vle. Pull emergency gear release handle. Allow gear to free-fall into locked position. Verify three green indicator lights.", "source": "POH Section 3.8", "tags": ["landing gear", "emergency", "extension", "failure"]},
    # Performance charts
    {"content": "TAKEOFF DISTANCE: At sea level, standard conditions, max gross weight: ground roll approximately 960 feet, total distance over 50-foot obstacle approximately 1685 feet. Increase distances by 15% for each 1000 feet of density altitude.", "source": "POH Section 5.4", "tags": ["takeoff", "distance", "performance", "density altitude"]},
    {"content": "LANDING DISTANCE: At sea level, standard conditions, max gross weight: ground roll approximately 550 feet, total distance over 50-foot obstacle approximately 1335 feet. Add 10% for each 1000 feet of density altitude.", "source": "POH Section 5.9", "tags": ["landing", "distance", "performance", "density altitude"]},
    {"content": "CRUISE PERFORMANCE: At 8000 feet, 75% power, standard temperature: TAS approximately 122 knots, fuel burn 8.5 GPH. Lean mixture for best economy at cruise. Performance degrades approximately 2% per 1000 feet above service ceiling.", "source": "POH Section 5.5", "tags": ["cruise", "performance", "speed", "fuel burn"]},
    {"content": "CLIMB PERFORMANCE: Best rate of climb at sea level: 730 FPM at 74 KIAS (Vy). Service ceiling: 14,000 feet. Time to climb to 10,000 feet: approximately 22 minutes under standard conditions.", "source": "POH Section 5.6", "tags": ["climb", "performance", "rate", "ceiling"]},
    # Weight & balance
    {"content": "WEIGHT AND BALANCE: Maximum ramp weight: 2558 lbs. Maximum takeoff weight: 2550 lbs. Useful load: approximately 878 lbs. CG must remain within envelope for all phases of flight. Compute W&B before every flight.", "source": "POH Section 6.1", "tags": ["weight", "balance", "loading", "cg", "limits"]},
    {"content": "LOADING: Front seats: max 400 lbs combined. Rear seats: max 400 lbs combined. Baggage area: max 120 lbs. Fuel: 56 gallons usable (336 lbs). Verify CG is within forward and aft limits after loading.", "source": "POH Section 6.2", "tags": ["loading", "weight", "passengers", "baggage", "fuel"]},
    # Weather minimums
    {"content": "VFR WEATHER MINIMUMS (Class G, day, below 1200 AGL): Visibility 1 statute mile, clear of clouds. Above 1200 AGL: Visibility 1 SM, 500 below, 1000 above, 2000 horizontal from clouds.", "source": "POH Section 2.5", "tags": ["vfr", "weather", "minimums", "class g", "visibility"]},
    {"content": "VFR WEATHER MINIMUMS (Class B/C/D): Visibility 3 statute miles. Cloud clearance: 500 feet below, 1000 feet above, 2000 feet horizontal. Class B: clear of clouds, 3 SM visibility.", "source": "POH Section 2.6", "tags": ["vfr", "weather", "minimums", "class b", "class c", "controlled"]},
    {"content": "IFR FUEL REQUIREMENTS: Enough fuel to fly to the first airport of intended landing, then to the alternate (if required), then 45 minutes at normal cruise speed. File an alternate if destination forecast is below minimums.", "source": "POH Section 2.7", "tags": ["ifr", "fuel", "requirements", "alternate", "reserve"]},
    # Oxygen systems
    {"content": "OXYGEN REQUIREMENTS: Above 12,500 MSL for more than 30 minutes, required flight crew must use supplemental oxygen. Above 14,000 MSL, all crew must use oxygen at all times. Above 15,000 MSL, all occupants must be provided oxygen.", "source": "POH Section 2.8", "tags": ["oxygen", "altitude", "requirements", "hypoxia"]},
    {"content": "SUPPLEMENTAL OXYGEN SYSTEM: Portable oxygen system available. Verify oxygen pressure before high-altitude flights. Nasal cannula effective up to 18,000 feet; use mask above 18,000 feet. Never use oxygen near open flame or grease.", "source": "POH Section 7.10", "tags": ["oxygen", "system", "equipment", "portable"]},
    # Additional
    {"content": "CARBURETOR ICE: Apply carburetor heat when conditions favor icing (visible moisture, temperature 20-70°F). Initial RPM drop is normal when applying carb heat. RPM should recover and increase as ice melts.", "source": "POH Section 4.6", "tags": ["carburetor", "ice", "icing", "carb heat", "engine"]},
    {"content": "CROSSWIND LANDING TECHNIQUE: Use wing-low (sideslip) method: aileron into the wind, opposite rudder to maintain runway alignment. Touchdown on upwind main wheel first. Maximum demonstrated crosswind component: 15 knots.", "source": "POH Section 5.10", "tags": ["crosswind", "landing", "technique", "wind"]},
    {"content": "GO-AROUND PROCEDURE: Full power - APPLY. Carburetor heat - COLD. Flaps - RETRACT to 20° immediately. Establish positive rate of climb. Flaps - RETRACT fully above safe altitude. Trim as necessary.", "source": "POH Section 3.9", "tags": ["go-around", "missed approach", "procedure", "landing"]},
]

# ---------------------------------------------------------------------------
# Default checklists
# ---------------------------------------------------------------------------

DEFAULT_CHECKLISTS: dict[str, list[str]] = {
    "PREFLIGHT": [
        "Documents - CHECK (ARROW: Airworthiness, Registration, Radio license, Operating handbook, Weight & balance)",
        "Fuel quantity - VERIFY VISUALLY",
        "Oil level - CHECK (6-8 quarts)",
        "Control surfaces - FREE AND CORRECT",
        "Fuel sumps - DRAIN AND CHECK",
        "Tires and brakes - INSPECT",
        "Pitot tube and static ports - CLEAR",
        "Lights and beacon - TEST",
    ],
    "TAXI": [
        "Brakes - TEST after initial movement",
        "Flight instruments - CHECK during taxi",
        "Heading indicator - SET to compass",
        "Radios - SET appropriate frequencies",
        "Transponder - SET code",
        "Taxi lights - ON",
    ],
    "TAKEOFF": [
        "Flaps - SET FOR TAKEOFF",
        "Trim - SET for takeoff",
        "Mixture - RICH (below 3000 ft DA)",
        "Fuel selector - BOTH",
        "Transponder - ALT",
        "Lights - LANDING, STROBE ON",
        "Doors and windows - CLOSED AND LOCKED",
    ],
    "CLIMB": [
        "Airspeed - Vy (best rate of climb)",
        "Engine instruments - GREEN ARC",
        "Mixture - LEAN above 3000 ft DA",
        "Flaps - RETRACTED",
        "Landing gear - UP (if retractable)",
        "Fuel pump - ON as required",
    ],
    "CRUISE": [
        "Altitude - SET and maintain",
        "Power - SET for cruise",
        "Mixture - LEAN for cruise",
        "Trim - ADJUST for level flight",
        "Engine instruments - MONITOR",
        "Fuel state - CHECK quantity and balance",
        "Autopilot - ENGAGE as desired",
    ],
    "DESCENT": [
        "ATIS/Weather - OBTAIN",
        "Altimeter - SET local pressure",
        "Mixture - ENRICHEN as required",
        "Fuel selector - BOTH",
        "Landing gear - CHECK speed limitations",
        "Approach briefing - COMPLETE",
    ],
    "APPROACH": [
        "Landing gear - DOWN (3 green)",
        "Flaps - SET for approach",
        "Airspeed - Vref + wind correction",
        "Mixture - FULL RICH",
        "Fuel pump - ON",
        "Autopilot - DISCONNECT by 500 AGL",
        "Stabilized approach - VERIFY",
    ],
    "LANDING": [
        "Airspeed - Vref",
        "Flaps - FULL",
        "Landing gear - DOWN AND LOCKED",
        "Brakes - READY",
    ],
    "LANDED": [
        "Flaps - RETRACT",
        "Carburetor heat - OFF",
        "Transponder - STANDBY",
        "Landing/taxi lights - AS REQUIRED",
        "Trim - SET for takeoff (in case of go-around taxi back)",
    ],
}

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _get_sim_state(sim_state: dict) -> dict[str, Any]:
    """Flatten a SimState dict into the tool response format."""
    pos = sim_state.get("position", {})
    att = sim_state.get("attitude", {})
    spd = sim_state.get("speeds", {})
    eng = sim_state.get("engines", {})
    ap = sim_state.get("autopilot", {})
    fuel = sim_state.get("fuel", {})
    env = sim_state.get("environment", {})
    surf = sim_state.get("surfaces", {})

    engine_list = []
    for e in eng.get("engines", []):
        engine_list.append({
            "rpm": e.get("rpm", 0),
            "mp": e.get("manifold_pressure", 0),
            "ff": e.get("fuel_flow_gph", 0),
            "egt": e.get("egt", 0),
            "oil_temp": e.get("oil_temp", 0),
            "oil_pressure": e.get("oil_pressure", 0),
        })

    agl = pos.get("altitude_agl", 0)
    on_ground = agl < 10

    return {
        "aircraft": sim_state.get("aircraft", ""),
        "flight_phase": sim_state.get("flight_phase", "PREFLIGHT"),
        "latitude": pos.get("latitude", 0),
        "longitude": pos.get("longitude", 0),
        "altitude_msl": pos.get("altitude_msl", 0),
        "altitude_agl": agl,
        "pitch": att.get("pitch", 0),
        "bank": att.get("bank", 0),
        "heading_magnetic": att.get("heading_magnetic", 0),
        "indicated_airspeed": spd.get("indicated_airspeed", 0),
        "true_airspeed": spd.get("true_airspeed", 0),
        "ground_speed": spd.get("ground_speed", 0),
        "mach": spd.get("mach", 0),
        "vertical_speed": spd.get("vertical_speed", 0),
        "engine_count": eng.get("engine_count", 0),
        "engines": engine_list,
        "autopilot_master": ap.get("master", False),
        "autopilot_heading": ap.get("heading", 0),
        "autopilot_altitude": ap.get("altitude", 0),
        "total_fuel_gallons": fuel.get("total_gallons", 0),
        "fuel_weight_lbs": fuel.get("total_weight_lbs", 0),
        "wind_speed": env.get("wind_speed_kts", 0),
        "wind_direction": env.get("wind_direction", 0),
        "visibility": env.get("visibility_sm", 0),
        "temperature": env.get("temperature_c", 0),
        "barometer": env.get("barometer_inhg", 29.92),
        "gear_down": surf.get("gear_handle", False),
        "flaps_percent": surf.get("flaps_percent", 0),
        "spoilers_percent": surf.get("spoilers_percent", 0),
        "on_ground": on_ground,
    }


def _lookup_airport(identifier: str) -> dict[str, Any]:
    """Return airport data for a given identifier."""
    ident = identifier.upper().strip()
    airport = COMMON_AIRPORTS.get(ident)
    if airport is not None:
        return airport

    # Generate a plausible fallback for unknown airports
    return {
        "identifier": ident,
        "facility_name": f"{ident} Airport",
        "city": "Unknown",
        "state": "US",
        "elevation": random.randint(0, 3000),
        "latitude": round(random.uniform(25, 48), 4),
        "longitude": round(random.uniform(-122, -72), 4),
        "status_code": "O",
    }


def _search_manual(query: str, aircraft_type: str | None = None) -> list[dict[str, Any]]:
    """Return 2-3 manual snippets matching the query by keyword overlap."""
    query_lower = query.lower()
    query_words = set(query_lower.split())

    scored: list[tuple[float, dict[str, Any]]] = []
    for snippet in _MANUAL_SNIPPETS:
        tag_set = set(snippet["tags"])
        # Score by overlap between query words and tags
        overlap = len(query_words & tag_set)
        # Also check partial matches in content
        content_lower = snippet["content"].lower()
        content_hits = sum(1 for w in query_words if w in content_lower)
        score = overlap * 2 + content_hits
        if score > 0:
            relevance = min(0.98, round(0.5 + score * 0.08, 2))
            scored.append((score, {
                "content": snippet["content"],
                "source": snippet["source"],
                "relevance": relevance,
            }))

    # Sort by score descending, return top 2-3
    scored.sort(key=lambda x: x[0], reverse=True)
    results = [item for _, item in scored[:3]]

    # If no keyword matches, return generic fallback snippets
    if not results:
        fallback_indices = random.sample(range(len(_MANUAL_SNIPPETS)), min(2, len(_MANUAL_SNIPPETS)))
        for idx in fallback_indices:
            s = _MANUAL_SNIPPETS[idx]
            results.append({
                "content": s["content"],
                "source": s["source"],
                "relevance": 0.45,
            })

    return results


def _get_checklist(phase: str, aircraft_type: str | None = None) -> dict[str, Any]:
    """Return checklist items for a given phase."""
    phase_upper = phase.upper().strip()
    items = DEFAULT_CHECKLISTS.get(phase_upper, DEFAULT_CHECKLISTS.get("PREFLIGHT", []))

    aircraft_name = aircraft_type or "Generic Aircraft"

    return {
        "phase": phase_upper,
        "aircraft": aircraft_name,
        "source": "default",
        "items": items,
    }


def _create_flight_plan(
    departure: str,
    destination: str,
    altitude: int | float | None = None,
    route: str | None = None,
) -> dict[str, Any]:
    """Create a mock flight plan between two airports."""
    dep_info = _lookup_airport(departure)
    dest_info = _lookup_airport(destination)

    # Compute approximate distance for notes
    dep_lat = math.radians(dep_info["latitude"])
    dep_lon = math.radians(dep_info["longitude"])
    dest_lat = math.radians(dest_info["latitude"])
    dest_lon = math.radians(dest_info["longitude"])
    dlat = dest_lat - dep_lat
    dlon = dest_lon - dep_lon
    a = math.sin(dlat / 2) ** 2 + math.cos(dep_lat) * math.cos(dest_lat) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance_nm = round(c * 3440.065, 1)

    cruise_alt = int(altitude) if altitude else 6500
    route_str = route or "DIRECT"

    # Build waypoints
    waypoints: list[dict[str, Any]] = [
        {"name": dep_info["identifier"], "type": "departure", "latitude": dep_info["latitude"], "longitude": dep_info["longitude"]},
    ]

    # Add a midpoint for longer routes
    if distance_nm > 100 and route_str == "DIRECT":
        mid_lat = round((dep_info["latitude"] + dest_info["latitude"]) / 2, 4)
        mid_lon = round((dep_info["longitude"] + dest_info["longitude"]) / 2, 4)
        waypoints.append({"name": "MIDPT", "type": "waypoint", "latitude": mid_lat, "longitude": mid_lon})

    waypoints.append({"name": dest_info["identifier"], "type": "destination", "latitude": dest_info["latitude"], "longitude": dest_info["longitude"]})

    # Estimated time en route
    cruise_gs = 120  # default assumption, knots
    ete_hours = distance_nm / cruise_gs if cruise_gs > 0 else 0
    ete_min = round(ete_hours * 60)

    notes = (
        f"Distance: {distance_nm} NM. "
        f"Estimated time en route: {ete_min} min at {cruise_gs} kt GS. "
        f"Check NOTAMs and TFRs along route before departure."
    )

    return {
        "departure": dep_info,
        "destination": dest_info,
        "cruise_altitude": cruise_alt,
        "route": route_str,
        "waypoints": waypoints,
        "status": "draft",
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------


def mock_tool_response(
    tool_name: str,
    arguments: dict,
    sim_state: dict | None = None,
) -> str:
    """Return a JSON string matching the tool's response format.

    Parameters
    ----------
    tool_name:
        One of "get_sim_state", "lookup_airport", "search_manual",
        "get_checklist", "create_flight_plan".
    arguments:
        The arguments dict that would be passed to the tool.
    sim_state:
        The current SimState dict (required for get_sim_state).

    Returns
    -------
    str
        A JSON-encoded string of the tool response.
    """
    if tool_name == "get_sim_state":
        if sim_state is None:
            raise ValueError("sim_state is required for get_sim_state")
        result = _get_sim_state(sim_state)

    elif tool_name == "lookup_airport":
        identifier = arguments.get("identifier", "")
        result = _lookup_airport(identifier)

    elif tool_name == "search_manual":
        query = arguments.get("query", "")
        aircraft_type = arguments.get("aircraft_type")
        result = _search_manual(query, aircraft_type)

    elif tool_name == "get_checklist":
        phase = arguments.get("phase", "PREFLIGHT")
        aircraft_type = arguments.get("aircraft_type")
        result = _get_checklist(phase, aircraft_type)

    elif tool_name == "create_flight_plan":
        departure = arguments.get("departure", "")
        destination = arguments.get("destination", "")
        altitude = arguments.get("altitude")
        route = arguments.get("route")
        result = _create_flight_plan(departure, destination, altitude, route)

    else:
        raise ValueError(
            f"Unknown tool {tool_name!r}. Valid tools: get_sim_state, "
            f"lookup_airport, search_manual, get_checklist, create_flight_plan"
        )

    return json.dumps(result, indent=2)
