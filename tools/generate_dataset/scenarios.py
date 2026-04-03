"""Scenario template definitions for the MERLIN aviation co-pilot fine-tuning dataset.

This module defines ~200 ScenarioTemplate instances across 9 flight phases plus
emergency scenarios. Each template is expanded with variable combinations
(aircraft type, weather condition, pilot experience level) to produce ~2,500
unique scenario instances for fine-tuning.

MERLIN is a Navy Test Pilot AI co-pilot personality:
- Ultra-brief during TAKEOFF, APPROACH, LANDING (callouts only)
- Conversational during CRUISE (teaching moments, war stories)
- Professional during other phases
- Addresses the pilot as "Captain"
- Uses dry Navy humor (never during emergencies or critical phases)

The 5 available tools MERLIN can invoke:
- get_sim_state: No args. Returns full telemetry snapshot.
- lookup_airport: Args: identifier (ICAO/FAA code).
- search_manual: Args: query (search string).
- get_checklist: Args: phase (flight phase string).
- create_flight_plan: Args: departure, destination, altitude?, route?
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field


@dataclass
class ScenarioTemplate:
    id: str                           # e.g. "cruise_fuel_check_01"
    phase: str                        # FlightPhase value string: "PREFLIGHT", "TAXI", etc.
    category: str                     # "normal" | "abnormal" | "emergency"
    description: str                  # Human-readable description
    user_prompts: list[str]           # 1-5 user messages for multi-turn conversation
    expected_tools: list[str]         # Tools MERLIN should call (from the 5 available)
    aircraft_types: list[str] = field(default_factory=list)  # Compatible aircraft names (empty = all)
    weather_conditions: list[str] = field(default_factory=lambda: ["CAVU", "marginal_vfr", "IFR", "crosswind", "turbulence"])
    pilot_levels: list[str] = field(default_factory=lambda: ["student", "private", "instrument", "ATP"])
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Aircraft groupings
# ---------------------------------------------------------------------------
GA_PISTON = [
    "Cessna 172 Skyhawk",
    "Piper PA-28 Cherokee",
    "Diamond DA40 Diamond Star",
    "Cirrus SR22",
]

GA_ALL = GA_PISTON + ["Beechcraft King Air 350"]

TURBOPROP = ["Beechcraft King Air 350"]

JETS = [
    "Cessna Citation CJ4",
    "Boeing 747-8",
    "Airbus A320neo",
]

LIGHT_JETS = ["Cessna Citation CJ4"]

HEAVY_JETS = ["Boeing 747-8", "Airbus A320neo"]

ALL_AIRCRAFT: list[str] = []  # empty means "all"

# Weather presets
ALL_WX = ["CAVU", "marginal_vfr", "IFR", "crosswind", "turbulence", "icing"]
VFR_WX = ["CAVU", "marginal_vfr", "crosswind"]
IFR_WX = ["IFR", "marginal_vfr", "crosswind", "turbulence", "icing"]
FAIR_WX = ["CAVU", "marginal_vfr"]
BAD_WX = ["IFR", "crosswind", "turbulence", "icing"]


# ===================================================================
# PREFLIGHT — 24 scenarios
# ===================================================================
def _preflight_scenarios() -> list[ScenarioTemplate]:
    return [
        ScenarioTemplate(
            id="preflight_weather_brief_01",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot requests a standard weather briefing for departure airport",
            user_prompts=[
                "MERLIN, pull up the weather for KOSH.",
                "How are the winds looking?",
                "Good enough. Let's plan on runway 18.",
            ],
            expected_tools=["lookup_airport"],
            tags=["weather", "briefing"],
        ),
        ScenarioTemplate(
            id="preflight_weather_brief_02",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot checks destination weather before departure",
            user_prompts=[
                "What's the current METAR at KJFK?",
                "And the TAF?",
            ],
            expected_tools=["lookup_airport"],
            tags=["weather", "destination"],
        ),
        ScenarioTemplate(
            id="preflight_checklist_01",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot requests the preflight checklist",
            user_prompts=[
                "Let's run the preflight checklist.",
                "Check.",
                "Check.",
                "All good, continue.",
            ],
            expected_tools=["get_checklist"],
            tags=["checklist"],
        ),
        ScenarioTemplate(
            id="preflight_checklist_02",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot asks for specific checklist item clarification",
            user_prompts=[
                "Run me through preflight.",
                "Wait, what's the proper procedure for checking the fuel sumps?",
            ],
            expected_tools=["get_checklist", "search_manual"],
            aircraft_types=GA_PISTON,
            tags=["checklist", "procedures"],
        ),
        ScenarioTemplate(
            id="preflight_flight_plan_01",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot requests creation of a VFR flight plan",
            user_prompts=[
                "I need a flight plan from KBED to KMVY.",
                "Cruise at four thousand five hundred.",
                "Looks good, file it.",
            ],
            expected_tools=["create_flight_plan", "lookup_airport"],
            aircraft_types=GA_PISTON,
            weather_conditions=VFR_WX,
            tags=["flight_plan", "VFR"],
        ),
        ScenarioTemplate(
            id="preflight_flight_plan_02",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot plans an IFR cross-country",
            user_prompts=[
                "Plan IFR from KBOS to KPHL, flight level two four zero.",
                "What's the preferred routing?",
                "File that.",
            ],
            expected_tools=["create_flight_plan", "lookup_airport"],
            aircraft_types=JETS + TURBOPROP,
            weather_conditions=IFR_WX,
            tags=["flight_plan", "IFR"],
        ),
        ScenarioTemplate(
            id="preflight_fuel_calc_01",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot asks MERLIN to verify fuel calculations",
            user_prompts=[
                "I've got 48 gallons on board. Is that enough for KBED to KACK with reserves?",
                "What's our planned fuel burn rate?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            aircraft_types=GA_PISTON,
            tags=["fuel", "planning"],
        ),
        ScenarioTemplate(
            id="preflight_fuel_calc_02",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot verifies fuel load on a turboprop",
            user_prompts=[
                "MERLIN, confirm fuel quantity and compare against flight plan requirements.",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            aircraft_types=TURBOPROP,
            tags=["fuel", "planning"],
        ),
        ScenarioTemplate(
            id="preflight_weight_balance_01",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot asks about weight and balance",
            user_prompts=[
                "Can you check our weight and balance? I've got two passengers in back, about 350 pounds total plus bags.",
                "Are we within CG limits?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=GA_PISTON,
            tags=["weight_balance"],
        ),
        ScenarioTemplate(
            id="preflight_airport_info_01",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot requests destination airport information",
            user_prompts=[
                "Pull up the airport info for KSFB.",
                "What runways do they have?",
                "Any NOTAMs I should know about?",
            ],
            expected_tools=["lookup_airport"],
            tags=["airport_info"],
        ),
        ScenarioTemplate(
            id="preflight_airport_info_02",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot researches an unfamiliar field",
            user_prompts=[
                "I've never been to KAVP. What can you tell me about it?",
                "Runway lengths?",
                "Any terrain concerns on approach?",
            ],
            expected_tools=["lookup_airport"],
            tags=["airport_info", "unfamiliar"],
        ),
        ScenarioTemplate(
            id="preflight_manual_lookup_01",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot looks up a V-speed in the manual",
            user_prompts=[
                "What's Vx for this aircraft at max gross weight?",
            ],
            expected_tools=["search_manual", "get_sim_state"],
            tags=["V-speeds", "performance"],
        ),
        ScenarioTemplate(
            id="preflight_manual_lookup_02",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot checks performance charts",
            user_prompts=[
                "MERLIN, look up takeoff distance for a 5,000-foot density altitude.",
                "That's with 10 degrees of flaps?",
            ],
            expected_tools=["search_manual", "get_sim_state"],
            tags=["performance", "takeoff"],
        ),
        ScenarioTemplate(
            id="preflight_notam_review_01",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot reviews NOTAMs for the route",
            user_prompts=[
                "Any TFRs along our route today?",
                "What about the destination?",
            ],
            expected_tools=["lookup_airport", "create_flight_plan"],
            tags=["NOTAMs", "TFR"],
        ),
        ScenarioTemplate(
            id="preflight_alternate_planning_01",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot asks about alternate airports",
            user_prompts=[
                "Destination weather is marginal. What are good alternates near KLGA?",
                "How about KTEB?",
                "Let's add that as our alternate.",
            ],
            expected_tools=["lookup_airport", "create_flight_plan"],
            weather_conditions=BAD_WX,
            tags=["alternates", "IFR"],
        ),
        ScenarioTemplate(
            id="preflight_abnormal_wx_01",
            phase="PREFLIGHT",
            category="abnormal",
            description="Pilot wants to fly in deteriorating weather conditions",
            user_prompts=[
                "Weather is getting worse but I think we can make it VFR.",
                "What's the ceiling at our destination now?",
                "I'm going to go for it.",
            ],
            expected_tools=["lookup_airport", "get_sim_state"],
            weather_conditions=BAD_WX,
            aircraft_types=GA_PISTON,
            pilot_levels=["student", "private"],
            tags=["weather_decision", "safety"],
        ),
        ScenarioTemplate(
            id="preflight_abnormal_wx_02",
            phase="PREFLIGHT",
            category="abnormal",
            description="Low-time pilot planning flight into known icing",
            user_prompts=[
                "Forecast shows light icing at six thousand. We should be fine, right?",
                "The aircraft doesn't have de-ice, does it?",
            ],
            expected_tools=["search_manual", "lookup_airport"],
            weather_conditions=["icing"],
            aircraft_types=GA_PISTON,
            pilot_levels=["student", "private"],
            tags=["icing", "safety", "go_no_go"],
        ),
        ScenarioTemplate(
            id="preflight_systems_check_01",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot asks about aircraft systems status",
            user_prompts=[
                "MERLIN, run me a systems check.",
                "How's the electrical system?",
            ],
            expected_tools=["get_sim_state"],
            tags=["systems", "status"],
        ),
        ScenarioTemplate(
            id="preflight_crosswind_check_01",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot checks crosswind component for runway selection",
            user_prompts=[
                "What's the crosswind component on runway 27 at KPWM?",
                "Is that within our demonstrated crosswind limit?",
            ],
            expected_tools=["lookup_airport", "search_manual", "get_sim_state"],
            weather_conditions=["crosswind"],
            tags=["crosswind", "runway_selection"],
        ),
        ScenarioTemplate(
            id="preflight_student_question_01",
            phase="PREFLIGHT",
            category="normal",
            description="Student pilot asks about airspace",
            user_prompts=[
                "MERLIN, our route goes near Bravo airspace. Do I need a clearance?",
                "How do I request that?",
            ],
            expected_tools=["search_manual", "create_flight_plan"],
            pilot_levels=["student"],
            tags=["airspace", "training"],
        ),
        ScenarioTemplate(
            id="preflight_squawk_setup_01",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot configures transponder and radios before departure",
            user_prompts=[
                "What squawk code did we get?",
                "And the departure frequency?",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            tags=["radios", "transponder"],
        ),
        ScenarioTemplate(
            id="preflight_abnormal_oil_01",
            phase="PREFLIGHT",
            category="abnormal",
            description="Low oil pressure noted during preflight engine check",
            user_prompts=[
                "Oil pressure is reading low on the gauge. What's minimum for this engine?",
                "It's just below that. Should we go?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=GA_PISTON,
            tags=["oil_pressure", "go_no_go", "abnormal"],
        ),
        ScenarioTemplate(
            id="preflight_runway_contamination_01",
            phase="PREFLIGHT",
            category="abnormal",
            description="Pilot asks about runway conditions after snow",
            user_prompts=[
                "KBTV is reporting patchy ice on the runway. What's the braking action?",
                "Do we have enough runway?",
            ],
            expected_tools=["lookup_airport", "search_manual"],
            weather_conditions=["icing"],
            tags=["runway_condition", "contamination"],
        ),
        ScenarioTemplate(
            id="preflight_personal_minimums_01",
            phase="PREFLIGHT",
            category="normal",
            description="Pilot discusses personal minimums",
            user_prompts=[
                "I set my personal minimums at 1000 and 3. What are the current conditions?",
                "That's cutting it close. What do you think?",
            ],
            expected_tools=["lookup_airport", "get_sim_state"],
            weather_conditions=["marginal_vfr", "IFR"],
            pilot_levels=["private", "instrument"],
            tags=["personal_minimums", "safety"],
        ),
    ]


# ===================================================================
# TAXI — 20 scenarios
# ===================================================================
def _taxi_scenarios() -> list[ScenarioTemplate]:
    return [
        ScenarioTemplate(
            id="taxi_checklist_01",
            phase="TAXI",
            category="normal",
            description="Pilot requests the taxi checklist",
            user_prompts=[
                "Run the taxi checklist.",
                "Check.",
                "Check.",
            ],
            expected_tools=["get_checklist"],
            tags=["checklist"],
        ),
        ScenarioTemplate(
            id="taxi_clearance_readback_01",
            phase="TAXI",
            category="normal",
            description="Pilot asks MERLIN to verify taxi clearance readback",
            user_prompts=[
                "I was told to taxi to runway 22L via Alpha, Charlie. Did I get that right?",
            ],
            expected_tools=["lookup_airport"],
            tags=["clearance", "taxi_route"],
        ),
        ScenarioTemplate(
            id="taxi_hot_spot_01",
            phase="TAXI",
            category="normal",
            description="Pilot asks about hot spots on the airport diagram",
            user_prompts=[
                "Any hot spots on the taxi route to 28R?",
                "Where exactly is hot spot 3?",
            ],
            expected_tools=["lookup_airport"],
            tags=["hot_spots", "safety"],
        ),
        ScenarioTemplate(
            id="taxi_runway_incursion_01",
            phase="TAXI",
            category="abnormal",
            description="Pilot approaching a runway hold short line without clearance",
            user_prompts=[
                "We're coming up on runway 14. We're clear to cross, right?",
            ],
            expected_tools=["lookup_airport", "get_sim_state"],
            tags=["runway_incursion", "safety"],
        ),
        ScenarioTemplate(
            id="taxi_systems_01",
            phase="TAXI",
            category="normal",
            description="Pilot verifies flight instruments during taxi",
            user_prompts=[
                "Heading indicator set?",
                "Gyros look good?",
            ],
            expected_tools=["get_sim_state"],
            tags=["instruments", "systems"],
        ),
        ScenarioTemplate(
            id="taxi_before_takeoff_01",
            phase="TAXI",
            category="normal",
            description="Pilot initiates before-takeoff checklist at the hold short line",
            user_prompts=[
                "We're holding short of 27. Run the before takeoff checklist.",
                "Check.",
                "Check.",
                "All set. Ready for takeoff.",
            ],
            expected_tools=["get_checklist", "get_sim_state"],
            tags=["checklist", "before_takeoff"],
        ),
        ScenarioTemplate(
            id="taxi_engine_runup_01",
            phase="TAXI",
            category="normal",
            description="Pilot performs engine run-up",
            user_prompts=[
                "Running up the engine now. What RPM should I see on the mag check?",
                "Drop looks about 100 RPM. That's good?",
            ],
            expected_tools=["search_manual", "get_sim_state"],
            aircraft_types=GA_PISTON,
            tags=["engine_runup", "magnetos"],
        ),
        ScenarioTemplate(
            id="taxi_abnormal_mag_drop_01",
            phase="TAXI",
            category="abnormal",
            description="Excessive mag drop during run-up",
            user_prompts=[
                "I'm seeing a 200 RPM drop on the left mag. What's the limit?",
                "Should we try to clear it?",
                "Still dropping 180. Can we go?",
            ],
            expected_tools=["search_manual", "get_sim_state"],
            aircraft_types=GA_PISTON,
            tags=["magneto", "abnormal", "go_no_go"],
        ),
        ScenarioTemplate(
            id="taxi_winds_check_01",
            phase="TAXI",
            category="normal",
            description="Pilot checks current winds before taking the runway",
            user_prompts=[
                "What are the current winds?",
                "Crosswind component?",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            weather_conditions=["crosswind"],
            tags=["winds", "crosswind"],
        ),
        ScenarioTemplate(
            id="taxi_flap_setting_01",
            phase="TAXI",
            category="normal",
            description="Pilot confirms flap setting for takeoff",
            user_prompts=[
                "What flap setting for takeoff today?",
            ],
            expected_tools=["search_manual", "get_sim_state"],
            tags=["flaps", "configuration"],
        ),
        ScenarioTemplate(
            id="taxi_lost_on_field_01",
            phase="TAXI",
            category="abnormal",
            description="Pilot is disoriented on a complex airport",
            user_prompts=[
                "MERLIN, I think I missed the turn onto Bravo. Where are we?",
                "How do I get back on course to runway 4R?",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            tags=["lost", "navigation", "taxi_route"],
        ),
        ScenarioTemplate(
            id="taxi_brake_check_01",
            phase="TAXI",
            category="normal",
            description="Pilot verifies brakes during initial taxi",
            user_prompts=[
                "Checking brakes... they feel spongy. What's normal brake pressure?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["brakes", "systems"],
        ),
        ScenarioTemplate(
            id="taxi_comm_frequency_01",
            phase="TAXI",
            category="normal",
            description="Pilot needs tower frequency",
            user_prompts=[
                "What's the tower frequency here?",
            ],
            expected_tools=["lookup_airport"],
            tags=["radio", "communications"],
        ),
        ScenarioTemplate(
            id="taxi_abnormal_warning_01",
            phase="TAXI",
            category="abnormal",
            description="Caution light illuminates during taxi",
            user_prompts=[
                "I just got a master caution. What's showing?",
                "Is it safe to continue?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["caution", "warning", "abnormal"],
        ),
        ScenarioTemplate(
            id="taxi_deice_01",
            phase="TAXI",
            category="normal",
            description="Pilot asks about deicing procedures",
            user_prompts=[
                "It's 28 degrees and light snow. Do we need to deice?",
                "What type of fluid should they use?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            weather_conditions=["icing"],
            tags=["deicing", "winter_ops"],
        ),
        ScenarioTemplate(
            id="taxi_altimeter_setting_01",
            phase="TAXI",
            category="normal",
            description="Pilot sets altimeter during taxi",
            user_prompts=[
                "What's the current altimeter setting?",
                "Set.",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            tags=["altimeter", "instruments"],
        ),
        ScenarioTemplate(
            id="taxi_departure_brief_01",
            phase="TAXI",
            category="normal",
            description="Pilot briefs the departure procedure",
            user_prompts=[
                "Brief me on the LOGAN TWO departure.",
                "What's the initial heading and altitude?",
            ],
            expected_tools=["create_flight_plan", "search_manual"],
            aircraft_types=JETS + TURBOPROP,
            weather_conditions=IFR_WX,
            tags=["departure", "SID", "briefing"],
        ),
        ScenarioTemplate(
            id="taxi_trim_setting_01",
            phase="TAXI",
            category="normal",
            description="Pilot sets trim for takeoff",
            user_prompts=[
                "What trim setting for takeoff?",
            ],
            expected_tools=["search_manual", "get_sim_state"],
            tags=["trim", "configuration"],
        ),
        ScenarioTemplate(
            id="taxi_wrong_runway_01",
            phase="TAXI",
            category="abnormal",
            description="Pilot appears to be taxiing to wrong runway",
            user_prompts=[
                "We were cleared to 22L, but this sign says 22R. Am I on the right taxiway?",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            tags=["wrong_runway", "safety"],
        ),
        ScenarioTemplate(
            id="taxi_passenger_brief_01",
            phase="TAXI",
            category="normal",
            description="Pilot asks for help with passenger briefing",
            user_prompts=[
                "I need to do the passenger brief. What are the required items?",
                "Thanks, anything else I'm forgetting?",
            ],
            expected_tools=["search_manual"],
            aircraft_types=GA_PISTON + TURBOPROP,
            tags=["passenger_brief", "regulations"],
        ),
    ]


# ===================================================================
# TAKEOFF — 18 scenarios
# ===================================================================
def _takeoff_scenarios() -> list[ScenarioTemplate]:
    return [
        ScenarioTemplate(
            id="takeoff_normal_01",
            phase="TAKEOFF",
            category="normal",
            description="Standard takeoff roll callouts",
            user_prompts=[
                "Rolling.",
            ],
            expected_tools=["get_sim_state"],
            tags=["callouts", "normal_takeoff"],
        ),
        ScenarioTemplate(
            id="takeoff_rotate_01",
            phase="TAKEOFF",
            category="normal",
            description="Pilot asks for rotate speed confirmation during roll",
            user_prompts=[
                "Vr?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["V-speeds", "rotate"],
        ),
        ScenarioTemplate(
            id="takeoff_crosswind_01",
            phase="TAKEOFF",
            category="normal",
            description="Crosswind takeoff technique",
            user_prompts=[
                "Crosswind from the left. Remind me of the correction.",
            ],
            expected_tools=["get_sim_state"],
            weather_conditions=["crosswind"],
            tags=["crosswind", "technique"],
        ),
        ScenarioTemplate(
            id="takeoff_soft_field_01",
            phase="TAKEOFF",
            category="normal",
            description="Soft field takeoff technique",
            user_prompts=[
                "Soft field takeoff. Ready.",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=GA_PISTON,
            weather_conditions=FAIR_WX,
            tags=["soft_field", "technique"],
        ),
        ScenarioTemplate(
            id="takeoff_short_field_01",
            phase="TAKEOFF",
            category="normal",
            description="Short field takeoff procedure",
            user_prompts=[
                "Short field. Brakes set, full power.",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=GA_PISTON,
            tags=["short_field", "technique"],
        ),
        ScenarioTemplate(
            id="takeoff_abort_01",
            phase="TAKEOFF",
            category="abnormal",
            description="Rejected takeoff due to engine anomaly",
            user_prompts=[
                "Engine doesn't feel right. Aborting!",
            ],
            expected_tools=["get_sim_state"],
            tags=["rejected_takeoff", "abort"],
        ),
        ScenarioTemplate(
            id="takeoff_abort_02",
            phase="TAKEOFF",
            category="abnormal",
            description="Rejected takeoff due to airspeed disagreement",
            user_prompts=[
                "Airspeed's not alive. Abort!",
            ],
            expected_tools=["get_sim_state"],
            tags=["rejected_takeoff", "airspeed"],
        ),
        ScenarioTemplate(
            id="takeoff_engine_failure_01",
            phase="TAKEOFF",
            category="emergency",
            description="Engine failure on takeoff roll before Vr",
            user_prompts=[
                "Engine out!",
            ],
            expected_tools=["get_sim_state"],
            tags=["engine_failure", "emergency"],
        ),
        ScenarioTemplate(
            id="takeoff_engine_failure_02",
            phase="TAKEOFF",
            category="emergency",
            description="Engine failure just after rotation",
            user_prompts=[
                "We lost the engine!",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            tags=["engine_failure", "emergency", "after_rotation"],
        ),
        ScenarioTemplate(
            id="takeoff_v1_cut_01",
            phase="TAKEOFF",
            category="emergency",
            description="Engine failure at V1 on multi-engine jet",
            user_prompts=[
                "V1... engine fire right side!",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=HEAVY_JETS,
            tags=["V1_cut", "engine_fire", "emergency"],
        ),
        ScenarioTemplate(
            id="takeoff_obstacle_departure_01",
            phase="TAKEOFF",
            category="normal",
            description="Obstacle departure procedure",
            user_prompts=[
                "Climbing. Obstacle departure procedure.",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            tags=["ODP", "obstacle"],
        ),
        ScenarioTemplate(
            id="takeoff_noise_abatement_01",
            phase="TAKEOFF",
            category="normal",
            description="Noise abatement departure",
            user_prompts=[
                "Noise abatement turn at 800 AGL?",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            tags=["noise_abatement"],
        ),
        ScenarioTemplate(
            id="takeoff_bird_strike_01",
            phase="TAKEOFF",
            category="emergency",
            description="Bird strike during takeoff",
            user_prompts=[
                "Bird strike! Check the engine!",
            ],
            expected_tools=["get_sim_state"],
            tags=["bird_strike", "emergency"],
        ),
        ScenarioTemplate(
            id="takeoff_windshear_01",
            phase="TAKEOFF",
            category="emergency",
            description="Windshear warning on departure",
            user_prompts=[
                "Windshear! Windshear!",
            ],
            expected_tools=["get_sim_state"],
            weather_conditions=["turbulence"],
            tags=["windshear", "emergency"],
        ),
        ScenarioTemplate(
            id="takeoff_terrain_01",
            phase="TAKEOFF",
            category="normal",
            description="Terrain awareness during departure",
            user_prompts=[
                "What's the terrain like off the departure end?",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            tags=["terrain", "awareness"],
        ),
        ScenarioTemplate(
            id="takeoff_flap_retract_01",
            phase="TAKEOFF",
            category="normal",
            description="Flap retraction schedule after takeoff",
            user_prompts=[
                "Positive rate. Gear up. When do I pull flaps?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=JETS + TURBOPROP,
            tags=["flaps", "cleanup"],
        ),
        ScenarioTemplate(
            id="takeoff_density_alt_01",
            phase="TAKEOFF",
            category="abnormal",
            description="High density altitude affecting performance",
            user_prompts=[
                "We're barely climbing. What's the density altitude?",
            ],
            expected_tools=["get_sim_state"],
            aircraft_types=GA_PISTON,
            weather_conditions=["CAVU"],
            tags=["density_altitude", "performance"],
        ),
        ScenarioTemplate(
            id="takeoff_door_ajar_01",
            phase="TAKEOFF",
            category="abnormal",
            description="Door ajar warning during takeoff roll",
            user_prompts=[
                "Door light just came on!",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["door_ajar", "abnormal"],
        ),
    ]


# ===================================================================
# CLIMB — 20 scenarios
# ===================================================================
def _climb_scenarios() -> list[ScenarioTemplate]:
    return [
        ScenarioTemplate(
            id="climb_checklist_01",
            phase="CLIMB",
            category="normal",
            description="After-takeoff / climb checklist",
            user_prompts=[
                "Run the climb checklist.",
                "Check.",
                "Check.",
            ],
            expected_tools=["get_checklist"],
            tags=["checklist", "after_takeoff"],
        ),
        ScenarioTemplate(
            id="climb_rate_check_01",
            phase="CLIMB",
            category="normal",
            description="Pilot checks climb performance",
            user_prompts=[
                "What's our climb rate?",
                "That's a bit low. What should we expect?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["climb_rate", "performance"],
        ),
        ScenarioTemplate(
            id="climb_power_setting_01",
            phase="CLIMB",
            category="normal",
            description="Pilot asks about climb power setting",
            user_prompts=[
                "What power setting should I be at for cruise climb?",
            ],
            expected_tools=["search_manual", "get_sim_state"],
            tags=["power_setting", "performance"],
        ),
        ScenarioTemplate(
            id="climb_altitude_assignment_01",
            phase="CLIMB",
            category="normal",
            description="Pilot confirms assigned altitude during climb",
            user_prompts=[
                "What's our assigned altitude?",
                "And our current altitude?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            tags=["altitude", "assignment"],
        ),
        ScenarioTemplate(
            id="climb_icing_01",
            phase="CLIMB",
            category="abnormal",
            description="Encountering icing during climb",
            user_prompts=[
                "I'm seeing ice building on the leading edge. Turn on the pitot heat.",
                "Is there an altitude we can climb to that's above the icing layer?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            weather_conditions=["icing"],
            tags=["icing", "abnormal"],
        ),
        ScenarioTemplate(
            id="climb_mixture_lean_01",
            phase="CLIMB",
            category="normal",
            description="Pilot adjusts mixture during climb",
            user_prompts=[
                "When should I start leaning the mixture?",
                "We're passing through 5,000. Good time?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=GA_PISTON,
            tags=["mixture", "engine_management"],
        ),
        ScenarioTemplate(
            id="climb_traffic_01",
            phase="CLIMB",
            category="normal",
            description="Traffic callout during climb",
            user_prompts=[
                "MERLIN, any traffic?",
            ],
            expected_tools=["get_sim_state"],
            tags=["traffic", "awareness"],
        ),
        ScenarioTemplate(
            id="climb_turbulence_01",
            phase="CLIMB",
            category="abnormal",
            description="Encountering turbulence during climb",
            user_prompts=[
                "Getting pretty rough. What's the turbulence penetration speed?",
                "Should we request a different altitude?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            weather_conditions=["turbulence"],
            tags=["turbulence", "speed"],
        ),
        ScenarioTemplate(
            id="climb_oxygen_01",
            phase="CLIMB",
            category="normal",
            description="Pilot asks about supplemental oxygen requirements",
            user_prompts=[
                "Climbing through 12,000. Do we need oxygen yet?",
                "What's the reg say?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=GA_PISTON + TURBOPROP,
            tags=["oxygen", "regulations"],
        ),
        ScenarioTemplate(
            id="climb_airspace_transition_01",
            phase="CLIMB",
            category="normal",
            description="Transitioning through airspace during climb",
            user_prompts=[
                "Are we about to enter Class B?",
                "We have a clearance for that?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            tags=["airspace", "clearance"],
        ),
        ScenarioTemplate(
            id="climb_engine_monitor_01",
            phase="CLIMB",
            category="normal",
            description="Pilot monitors engine temps during climb",
            user_prompts=[
                "How are the CHTs looking?",
                "Any cylinders running hot?",
            ],
            expected_tools=["get_sim_state"],
            aircraft_types=GA_PISTON,
            tags=["engine_monitor", "CHT"],
        ),
        ScenarioTemplate(
            id="climb_step_climb_01",
            phase="CLIMB",
            category="normal",
            description="Pilot asks about step climb for fuel efficiency",
            user_prompts=[
                "Should we do a step climb today or go straight to flight level three five zero?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            aircraft_types=HEAVY_JETS,
            tags=["step_climb", "fuel_efficiency"],
        ),
        ScenarioTemplate(
            id="climb_frequency_change_01",
            phase="CLIMB",
            category="normal",
            description="Pilot needs the next frequency during climb",
            user_prompts=[
                "What's the next center frequency?",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            tags=["frequency", "communications"],
        ),
        ScenarioTemplate(
            id="climb_abnormal_vsi_01",
            phase="CLIMB",
            category="abnormal",
            description="Unexpected loss of climb performance",
            user_prompts=[
                "VSI just dropped to zero and we're at full power. What's going on?",
                "Check the engine instruments.",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["VSI", "performance_loss", "abnormal"],
        ),
        ScenarioTemplate(
            id="climb_transition_altitude_01",
            phase="CLIMB",
            category="normal",
            description="Passing through transition altitude",
            user_prompts=[
                "Passing through 18,000. Set standard?",
            ],
            expected_tools=["get_sim_state"],
            aircraft_types=JETS + TURBOPROP,
            tags=["transition_altitude", "altimeter"],
        ),
        ScenarioTemplate(
            id="climb_cabin_pressurization_01",
            phase="CLIMB",
            category="normal",
            description="Monitoring cabin pressurization during climb",
            user_prompts=[
                "How's cabin pressure?",
                "What's the differential?",
            ],
            expected_tools=["get_sim_state"],
            aircraft_types=JETS + TURBOPROP,
            tags=["pressurization", "cabin"],
        ),
        ScenarioTemplate(
            id="climb_cabin_press_abnormal_01",
            phase="CLIMB",
            category="abnormal",
            description="Cabin pressurization not keeping up during climb",
            user_prompts=[
                "Cabin altitude is climbing fast. We're at 10,000 cabin already.",
                "What's the emergency procedure?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=JETS + TURBOPROP,
            tags=["pressurization", "abnormal"],
        ),
        ScenarioTemplate(
            id="climb_fuel_flow_01",
            phase="CLIMB",
            category="normal",
            description="Pilot checks fuel flow during climb",
            user_prompts=[
                "What's our fuel flow right now?",
                "Is that normal for this altitude?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["fuel_flow", "engine_management"],
        ),
        ScenarioTemplate(
            id="climb_nav_check_01",
            phase="CLIMB",
            category="normal",
            description="Pilot verifies navigation during climb",
            user_prompts=[
                "Are we on course?",
                "How far to the first waypoint?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            tags=["navigation", "waypoint"],
        ),
        ScenarioTemplate(
            id="climb_oil_temp_high_01",
            phase="CLIMB",
            category="abnormal",
            description="High oil temperature during prolonged climb",
            user_prompts=[
                "Oil temp is in the yellow arc. It keeps going up.",
                "Should I reduce power or level off?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=GA_PISTON,
            tags=["oil_temp", "abnormal", "engine"],
        ),
    ]


# ===================================================================
# CRUISE — 28 scenarios
# ===================================================================
def _cruise_scenarios() -> list[ScenarioTemplate]:
    return [
        ScenarioTemplate(
            id="cruise_fuel_check_01",
            phase="CRUISE",
            category="normal",
            description="Routine fuel state check",
            user_prompts=[
                "What's our fuel state?",
                "How does that compare to the flight plan?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            tags=["fuel", "routine"],
        ),
        ScenarioTemplate(
            id="cruise_checklist_01",
            phase="CRUISE",
            category="normal",
            description="Cruise checklist",
            user_prompts=[
                "Let's do the cruise check.",
                "Check.",
                "Check.",
            ],
            expected_tools=["get_checklist", "get_sim_state"],
            tags=["checklist"],
        ),
        ScenarioTemplate(
            id="cruise_position_report_01",
            phase="CRUISE",
            category="normal",
            description="Pilot asks for a position report",
            user_prompts=[
                "Where are we right now?",
                "How far to destination?",
                "ETA?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            tags=["position", "navigation"],
        ),
        ScenarioTemplate(
            id="cruise_weather_ahead_01",
            phase="CRUISE",
            category="normal",
            description="Pilot checks weather at destination during cruise",
            user_prompts=[
                "What's the weather looking like at our destination?",
                "Any changes from our brief?",
            ],
            expected_tools=["lookup_airport"],
            tags=["weather", "destination"],
        ),
        ScenarioTemplate(
            id="cruise_teaching_moment_01",
            phase="CRUISE",
            category="normal",
            description="MERLIN shares a teaching moment about navigation",
            user_prompts=[
                "MERLIN, you ever fly one of these?",
                "What's the coolest thing you've tested?",
            ],
            expected_tools=["get_sim_state"],
            tags=["teaching", "conversation"],
        ),
        ScenarioTemplate(
            id="cruise_teaching_moment_02",
            phase="CRUISE",
            category="normal",
            description="Pilot asks about an aviation concept",
            user_prompts=[
                "Why do we lean the mixture at cruise altitude?",
                "What happens if I forget?",
            ],
            expected_tools=["search_manual"],
            aircraft_types=GA_PISTON,
            tags=["teaching", "mixture", "engine"],
        ),
        ScenarioTemplate(
            id="cruise_teaching_moment_03",
            phase="CRUISE",
            category="normal",
            description="MERLIN explains a weather phenomenon",
            user_prompts=[
                "What causes those lenticular clouds over the mountains?",
                "Should I be worried about mountain wave turbulence?",
            ],
            expected_tools=["get_sim_state"],
            weather_conditions=["turbulence"],
            tags=["teaching", "weather", "mountain_wave"],
        ),
        ScenarioTemplate(
            id="cruise_diversion_planning_01",
            phase="CRUISE",
            category="abnormal",
            description="Pilot considers diverting due to weather",
            user_prompts=[
                "Destination weather just went below minimums. What are our options?",
                "How about KBDL? What's the weather there?",
                "Plan a divert to KBDL.",
            ],
            expected_tools=["lookup_airport", "create_flight_plan", "get_sim_state"],
            weather_conditions=BAD_WX,
            tags=["diversion", "weather", "planning"],
        ),
        ScenarioTemplate(
            id="cruise_diversion_planning_02",
            phase="CRUISE",
            category="abnormal",
            description="Pilot diverts for a passenger medical issue",
            user_prompts=[
                "My passenger isn't feeling well. Where's the nearest suitable airport?",
                "Can we make it there in under 20 minutes?",
                "Divert now.",
            ],
            expected_tools=["get_sim_state", "lookup_airport", "create_flight_plan"],
            tags=["diversion", "medical", "passenger"],
        ),
        ScenarioTemplate(
            id="cruise_power_adjustment_01",
            phase="CRUISE",
            category="normal",
            description="Pilot optimizes cruise power",
            user_prompts=[
                "What's the best economy cruise setting for this altitude?",
                "What's our current TAS?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["cruise_power", "economy"],
        ),
        ScenarioTemplate(
            id="cruise_turbulence_ride_01",
            phase="CRUISE",
            category="normal",
            description="Pilot encounters light turbulence at cruise",
            user_prompts=[
                "Getting some chop up here. Any reports of smoother air at a different altitude?",
            ],
            expected_tools=["get_sim_state"],
            weather_conditions=["turbulence"],
            tags=["turbulence", "ride_report"],
        ),
        ScenarioTemplate(
            id="cruise_altitude_change_01",
            phase="CRUISE",
            category="normal",
            description="Pilot considers altitude change",
            user_prompts=[
                "Would we get better winds at flight level three seven zero?",
                "What's the fuel penalty for climbing?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            aircraft_types=JETS,
            tags=["altitude_optimization", "winds"],
        ),
        ScenarioTemplate(
            id="cruise_systems_check_01",
            phase="CRUISE",
            category="normal",
            description="Routine systems check during cruise",
            user_prompts=[
                "Give me a quick systems rundown.",
                "Anything out of the ordinary?",
            ],
            expected_tools=["get_sim_state"],
            tags=["systems", "routine"],
        ),
        ScenarioTemplate(
            id="cruise_lost_comms_01",
            phase="CRUISE",
            category="abnormal",
            description="Pilot realizes they've lost communication capability",
            user_prompts=[
                "I can't raise center on any frequency. What's the lost comms procedure?",
                "What altitude should I maintain?",
            ],
            expected_tools=["search_manual", "get_sim_state", "create_flight_plan"],
            tags=["lost_comms", "abnormal", "procedures"],
        ),
        ScenarioTemplate(
            id="cruise_vfr_flight_following_01",
            phase="CRUISE",
            category="normal",
            description="VFR pilot asks about flight following",
            user_prompts=[
                "What frequency should I call for flight following?",
                "What information do they need from me?",
            ],
            expected_tools=["lookup_airport", "get_sim_state"],
            aircraft_types=GA_PISTON,
            weather_conditions=VFR_WX,
            pilot_levels=["student", "private"],
            tags=["flight_following", "VFR", "communications"],
        ),
        ScenarioTemplate(
            id="cruise_fuel_imbalance_01",
            phase="CRUISE",
            category="abnormal",
            description="Fuel imbalance detected during cruise",
            user_prompts=[
                "Left tank is reading a lot lower than the right. Is that normal?",
                "How do I correct a fuel imbalance?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["fuel_imbalance", "abnormal"],
        ),
        ScenarioTemplate(
            id="cruise_nav_system_comparison_01",
            phase="CRUISE",
            category="normal",
            description="Student asks about different navigation methods",
            user_prompts=[
                "What's the difference between VOR and GPS navigation?",
                "Which one should I be using right now?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            pilot_levels=["student", "private"],
            tags=["teaching", "navigation"],
        ),
        ScenarioTemplate(
            id="cruise_etops_01",
            phase="CRUISE",
            category="normal",
            description="Monitoring ETOPS constraints on oceanic flight",
            user_prompts=[
                "What's our nearest suitable airport right now?",
                "Are we still within ETOPS limits?",
            ],
            expected_tools=["get_sim_state", "lookup_airport", "create_flight_plan"],
            aircraft_types=HEAVY_JETS,
            tags=["ETOPS", "oceanic"],
        ),
        ScenarioTemplate(
            id="cruise_autopilot_question_01",
            phase="CRUISE",
            category="normal",
            description="Pilot asks about autopilot modes",
            user_prompts=[
                "MERLIN, explain the difference between LNAV and heading mode.",
                "When would I use one versus the other?",
            ],
            expected_tools=["search_manual"],
            tags=["autopilot", "teaching"],
        ),
        ScenarioTemplate(
            id="cruise_airspace_question_01",
            phase="CRUISE",
            category="normal",
            description="Pilot asks about upcoming airspace",
            user_prompts=[
                "What airspace are we about to enter?",
                "Do I need to do anything different?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            tags=["airspace", "awareness"],
        ),
        ScenarioTemplate(
            id="cruise_icing_encounter_01",
            phase="CRUISE",
            category="abnormal",
            description="Encountering icing conditions at cruise",
            user_prompts=[
                "I see ice forming on the windshield. Anti-ice is on.",
                "Is there an ice-free altitude?",
                "Request lower.",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            weather_conditions=["icing"],
            tags=["icing", "abnormal", "altitude_change"],
        ),
        ScenarioTemplate(
            id="cruise_checkpoint_01",
            phase="CRUISE",
            category="normal",
            description="VFR pilot identifies ground references",
            user_prompts=[
                "Is that lake down there my checkpoint?",
                "Am I on time?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            aircraft_types=GA_PISTON,
            weather_conditions=VFR_WX,
            pilot_levels=["student", "private"],
            tags=["pilotage", "VFR", "checkpoints"],
        ),
        ScenarioTemplate(
            id="cruise_cabin_comfort_01",
            phase="CRUISE",
            category="normal",
            description="Pilot adjusts cabin environment during cruise",
            user_prompts=[
                "Cabin altitude is reading 8,000. Can we bring that down?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=JETS + TURBOPROP,
            tags=["cabin", "pressurization", "comfort"],
        ),
        ScenarioTemplate(
            id="cruise_magnetic_compass_01",
            phase="CRUISE",
            category="normal",
            description="Teaching moment about magnetic compass errors",
            user_prompts=[
                "Why doesn't the compass agree with the heading indicator right now?",
                "What are those turning errors you mentioned?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            pilot_levels=["student", "private"],
            tags=["teaching", "compass", "instruments"],
        ),
        ScenarioTemplate(
            id="cruise_fuel_emergency_01",
            phase="CRUISE",
            category="abnormal",
            description="Fuel quantity lower than expected at cruise midpoint",
            user_prompts=[
                "We're burning more fuel than planned. How much do we have left?",
                "Can we still make the destination?",
                "What's the closest airport with fuel?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan", "lookup_airport"],
            tags=["fuel", "abnormal", "diversion"],
        ),
        ScenarioTemplate(
            id="cruise_electrical_01",
            phase="CRUISE",
            category="abnormal",
            description="Alternator failure in cruise",
            user_prompts=[
                "Low voltage light just came on.",
                "What's the procedure?",
                "How much battery time do we have?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["electrical", "alternator", "abnormal"],
        ),
        ScenarioTemplate(
            id="cruise_descent_planning_01",
            phase="CRUISE",
            category="normal",
            description="Pilot plans top of descent",
            user_prompts=[
                "When should we start our descent?",
                "What descent rate should I plan?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            tags=["descent_planning", "TOD"],
        ),
        ScenarioTemplate(
            id="cruise_war_story_01",
            phase="CRUISE",
            category="normal",
            description="Casual conversation about flying experiences",
            user_prompts=[
                "MERLIN, what's the hardest landing you've ever had to make?",
                "No kidding? On a carrier?",
                "I'll stick to land runways, thanks.",
            ],
            expected_tools=["get_sim_state"],
            tags=["conversation", "personality"],
        ),
    ]


# ===================================================================
# DESCENT — 20 scenarios
# ===================================================================
def _descent_scenarios() -> list[ScenarioTemplate]:
    return [
        ScenarioTemplate(
            id="descent_checklist_01",
            phase="DESCENT",
            category="normal",
            description="Descent checklist",
            user_prompts=[
                "Descent checklist.",
                "Check.",
                "Check.",
            ],
            expected_tools=["get_checklist"],
            tags=["checklist"],
        ),
        ScenarioTemplate(
            id="descent_rate_01",
            phase="DESCENT",
            category="normal",
            description="Pilot asks about descent rate",
            user_prompts=[
                "What descent rate do I need to make the crossing restriction?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            tags=["descent_rate", "restriction"],
        ),
        ScenarioTemplate(
            id="descent_atis_01",
            phase="DESCENT",
            category="normal",
            description="Pilot requests destination ATIS during descent",
            user_prompts=[
                "Pull up the weather at our destination.",
                "Which runway should we expect?",
            ],
            expected_tools=["lookup_airport", "get_sim_state"],
            tags=["ATIS", "weather", "arrival"],
        ),
        ScenarioTemplate(
            id="descent_arrival_brief_01",
            phase="DESCENT",
            category="normal",
            description="Pilot briefs the arrival procedure",
            user_prompts=[
                "Brief me on the arrival into KSFO.",
                "What's the expected approach?",
            ],
            expected_tools=["lookup_airport", "create_flight_plan"],
            tags=["arrival", "briefing"],
        ),
        ScenarioTemplate(
            id="descent_speed_restriction_01",
            phase="DESCENT",
            category="normal",
            description="Pilot asks about speed restrictions",
            user_prompts=[
                "Speed limit below 10,000?",
                "What's our current speed?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["speed_restriction", "regulations"],
        ),
        ScenarioTemplate(
            id="descent_altimeter_transition_01",
            phase="DESCENT",
            category="normal",
            description="Setting local altimeter during descent",
            user_prompts=[
                "What's the transition level?",
                "Set local altimeter.",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            aircraft_types=JETS + TURBOPROP,
            tags=["altimeter", "transition"],
        ),
        ScenarioTemplate(
            id="descent_cabin_prep_01",
            phase="DESCENT",
            category="normal",
            description="Cabin preparation for arrival",
            user_prompts=[
                "Set cabin for landing. What altitude should I target?",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            aircraft_types=JETS + TURBOPROP,
            tags=["cabin", "pressurization"],
        ),
        ScenarioTemplate(
            id="descent_approach_selection_01",
            phase="DESCENT",
            category="normal",
            description="Pilot selects approach type",
            user_prompts=[
                "What approaches are available at KORD?",
                "Let's set up for the ILS 10L.",
            ],
            expected_tools=["lookup_airport", "get_sim_state"],
            weather_conditions=IFR_WX,
            tags=["approach_selection", "ILS"],
        ),
        ScenarioTemplate(
            id="descent_weather_deviation_01",
            phase="DESCENT",
            category="abnormal",
            description="Weather at destination has deteriorated during flight",
            user_prompts=[
                "The weather is worse than forecast. What are the current minimums?",
                "Are we equipped for the CAT II approach?",
                "Pull up alternates.",
            ],
            expected_tools=["lookup_airport", "get_sim_state", "search_manual"],
            weather_conditions=BAD_WX,
            tags=["weather", "minimums", "alternates"],
        ),
        ScenarioTemplate(
            id="descent_holding_01",
            phase="DESCENT",
            category="abnormal",
            description="ATC puts pilot in holding pattern",
            user_prompts=[
                "We're being put in the hold. How long can we hold with our fuel?",
                "Set up the hold at BOSCO intersection.",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            tags=["holding", "fuel"],
        ),
        ScenarioTemplate(
            id="descent_terrain_awareness_01",
            phase="DESCENT",
            category="normal",
            description="Terrain awareness during descent into mountainous area",
            user_prompts=[
                "What's the minimum safe altitude around here?",
                "How far are we from the terrain?",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            tags=["terrain", "MSA", "safety"],
        ),
        ScenarioTemplate(
            id="descent_anti_ice_01",
            phase="DESCENT",
            category="normal",
            description="Anti-ice configuration for descent through icing layer",
            user_prompts=[
                "We'll be descending through the freezing level. Anti-ice procedures?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            weather_conditions=["icing"],
            tags=["anti_ice", "procedures"],
        ),
        ScenarioTemplate(
            id="descent_slam_dunk_01",
            phase="DESCENT",
            category="abnormal",
            description="Pilot is too high and too close for a normal descent",
            user_prompts=[
                "ATC just cleared us direct to the field and we're still at flight level two four zero. Can we make it?",
                "What descent rate do we need?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            aircraft_types=JETS,
            tags=["slam_dunk", "descent_rate", "abnormal"],
        ),
        ScenarioTemplate(
            id="descent_fuel_check_01",
            phase="DESCENT",
            category="normal",
            description="Fuel check before approach",
            user_prompts=[
                "Fuel check before we start the approach.",
                "Still above minimums?",
            ],
            expected_tools=["get_sim_state"],
            tags=["fuel", "pre_approach"],
        ),
        ScenarioTemplate(
            id="descent_nav_setup_01",
            phase="DESCENT",
            category="normal",
            description="Setting up navigation for the approach",
            user_prompts=[
                "I need the ILS frequency for runway 28 at KSEA.",
                "Set it up.",
            ],
            expected_tools=["lookup_airport", "get_sim_state"],
            weather_conditions=IFR_WX,
            tags=["ILS", "nav_setup"],
        ),
        ScenarioTemplate(
            id="descent_passenger_seat_belt_01",
            phase="DESCENT",
            category="normal",
            description="Pilot reminds passengers to prepare for landing",
            user_prompts=[
                "How far out are we? I need to get the passengers buckled up.",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            tags=["passengers", "preparation"],
        ),
        ScenarioTemplate(
            id="descent_abnormal_gear_01",
            phase="DESCENT",
            category="abnormal",
            description="Pilot gets no gear indication during descent check",
            user_prompts=[
                "Gear handle is down but I don't have three green. What do I do?",
                "What does the manual say about manual gear extension?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["gear", "abnormal", "landing_gear"],
        ),
        ScenarioTemplate(
            id="descent_speed_brake_01",
            phase="DESCENT",
            category="normal",
            description="Speed brake usage during descent",
            user_prompts=[
                "Should I deploy speed brakes?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=JETS,
            tags=["speed_brakes", "descent_management"],
        ),
        ScenarioTemplate(
            id="descent_crossing_restriction_01",
            phase="DESCENT",
            category="normal",
            description="Meeting a STAR crossing restriction",
            user_prompts=[
                "We need to cross BRAVO at 11,000 and 250 knots. Are we going to make it?",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            aircraft_types=JETS + TURBOPROP,
            tags=["crossing_restriction", "STAR"],
        ),
        ScenarioTemplate(
            id="descent_mixture_rich_01",
            phase="DESCENT",
            category="normal",
            description="Enriching mixture during descent in piston aircraft",
            user_prompts=[
                "When should I start pushing the mixture forward?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=GA_PISTON,
            tags=["mixture", "descent"],
        ),
    ]


# ===================================================================
# APPROACH — 18 scenarios
# ===================================================================
def _approach_scenarios() -> list[ScenarioTemplate]:
    return [
        ScenarioTemplate(
            id="approach_checklist_01",
            phase="APPROACH",
            category="normal",
            description="Approach checklist",
            user_prompts=[
                "Approach checklist.",
                "Check.",
                "Check.",
            ],
            expected_tools=["get_checklist"],
            tags=["checklist"],
        ),
        ScenarioTemplate(
            id="approach_ils_setup_01",
            phase="APPROACH",
            category="normal",
            description="Setting up for an ILS approach",
            user_prompts=[
                "Localizer alive.",
            ],
            expected_tools=["get_sim_state"],
            weather_conditions=IFR_WX,
            tags=["ILS", "localizer"],
        ),
        ScenarioTemplate(
            id="approach_glideslope_01",
            phase="APPROACH",
            category="normal",
            description="Intercepting the glideslope",
            user_prompts=[
                "Glideslope alive.",
            ],
            expected_tools=["get_sim_state"],
            weather_conditions=IFR_WX,
            tags=["glideslope", "ILS"],
        ),
        ScenarioTemplate(
            id="approach_minimums_01",
            phase="APPROACH",
            category="normal",
            description="Approaching minimums callout",
            user_prompts=[
                "Minimums.",
                "Runway in sight. Landing.",
            ],
            expected_tools=["get_sim_state"],
            weather_conditions=IFR_WX,
            tags=["minimums", "callouts"],
        ),
        ScenarioTemplate(
            id="approach_visual_01",
            phase="APPROACH",
            category="normal",
            description="Visual approach to the field",
            user_prompts=[
                "Field in sight. Requesting visual approach.",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            weather_conditions=VFR_WX,
            tags=["visual_approach"],
        ),
        ScenarioTemplate(
            id="approach_missed_01",
            phase="APPROACH",
            category="abnormal",
            description="Executing a missed approach",
            user_prompts=[
                "Going missed!",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            weather_conditions=BAD_WX,
            tags=["missed_approach"],
        ),
        ScenarioTemplate(
            id="approach_missed_02",
            phase="APPROACH",
            category="abnormal",
            description="Missed approach due to unstable approach",
            user_prompts=[
                "Too fast. Going around.",
            ],
            expected_tools=["get_sim_state"],
            tags=["missed_approach", "unstable"],
        ),
        ScenarioTemplate(
            id="approach_circling_01",
            phase="APPROACH",
            category="normal",
            description="Circling approach to a different runway",
            user_prompts=[
                "Circle to land runway 9.",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            weather_conditions=["marginal_vfr", "IFR"],
            tags=["circling", "approach"],
        ),
        ScenarioTemplate(
            id="approach_configuration_01",
            phase="APPROACH",
            category="normal",
            description="Configuration for approach",
            user_prompts=[
                "Gear down. Flaps approach.",
            ],
            expected_tools=["get_sim_state"],
            tags=["configuration", "gear", "flaps"],
        ),
        ScenarioTemplate(
            id="approach_crosswind_01",
            phase="APPROACH",
            category="normal",
            description="Crosswind approach technique",
            user_prompts=[
                "Strong crosswind on final. Crabbing.",
            ],
            expected_tools=["get_sim_state"],
            weather_conditions=["crosswind"],
            tags=["crosswind", "technique"],
        ),
        ScenarioTemplate(
            id="approach_vasi_papi_01",
            phase="APPROACH",
            category="normal",
            description="Using VASI/PAPI for glidepath",
            user_prompts=[
                "Two red, two white on the PAPI.",
            ],
            expected_tools=["get_sim_state"],
            weather_conditions=VFR_WX,
            tags=["PAPI", "visual_aids"],
        ),
        ScenarioTemplate(
            id="approach_traffic_pattern_01",
            phase="APPROACH",
            category="normal",
            description="Entering the traffic pattern at an uncontrolled field",
            user_prompts=[
                "MERLIN, which pattern entry should I use?",
                "Left traffic or right traffic for runway 32?",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            aircraft_types=GA_PISTON,
            weather_conditions=VFR_WX,
            tags=["traffic_pattern", "uncontrolled"],
        ),
        ScenarioTemplate(
            id="approach_windshear_01",
            phase="APPROACH",
            category="emergency",
            description="Windshear on approach",
            user_prompts=[
                "Windshear! Going around!",
            ],
            expected_tools=["get_sim_state"],
            weather_conditions=["turbulence"],
            tags=["windshear", "go_around", "emergency"],
        ),
        ScenarioTemplate(
            id="approach_rnav_01",
            phase="APPROACH",
            category="normal",
            description="RNAV GPS approach",
            user_prompts=[
                "Setting up the RNAV 28. LNAV minimums.",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            weather_conditions=IFR_WX,
            tags=["RNAV", "GPS"],
        ),
        ScenarioTemplate(
            id="approach_vor_01",
            phase="APPROACH",
            category="normal",
            description="VOR approach at a field without ILS",
            user_prompts=[
                "Setting up the VOR approach runway 18.",
                "Inbound on the final approach course.",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            weather_conditions=IFR_WX,
            tags=["VOR", "non_precision"],
        ),
        ScenarioTemplate(
            id="approach_unstable_callout_01",
            phase="APPROACH",
            category="abnormal",
            description="MERLIN should call out unstable approach parameters",
            user_prompts=[
                "How's my approach looking?",
            ],
            expected_tools=["get_sim_state"],
            tags=["stable_approach", "callouts"],
        ),
        ScenarioTemplate(
            id="approach_wake_turbulence_01",
            phase="APPROACH",
            category="abnormal",
            description="Wake turbulence concern on approach",
            user_prompts=[
                "Heavy just landed ahead of us. How long should we wait?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["wake_turbulence", "separation"],
        ),
        ScenarioTemplate(
            id="approach_night_01",
            phase="APPROACH",
            category="normal",
            description="Night approach considerations",
            user_prompts=[
                "Dark night, no city lights. Remind me what to watch for.",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            weather_conditions=["CAVU"],
            tags=["night", "visual_illusions"],
        ),
    ]


# ===================================================================
# LANDING — 16 scenarios
# ===================================================================
def _landing_scenarios() -> list[ScenarioTemplate]:
    return [
        ScenarioTemplate(
            id="landing_normal_01",
            phase="LANDING",
            category="normal",
            description="Normal landing callouts",
            user_prompts=[
                "Short final.",
            ],
            expected_tools=["get_sim_state"],
            tags=["callouts", "normal"],
        ),
        ScenarioTemplate(
            id="landing_crosswind_01",
            phase="LANDING",
            category="normal",
            description="Crosswind landing",
            user_prompts=[
                "Kicking it straight.",
            ],
            expected_tools=["get_sim_state"],
            weather_conditions=["crosswind"],
            tags=["crosswind", "technique"],
        ),
        ScenarioTemplate(
            id="landing_short_field_01",
            phase="LANDING",
            category="normal",
            description="Short field landing technique",
            user_prompts=[
                "Short field. Aiming for the numbers.",
            ],
            expected_tools=["get_sim_state"],
            aircraft_types=GA_PISTON,
            tags=["short_field", "technique"],
        ),
        ScenarioTemplate(
            id="landing_soft_field_01",
            phase="LANDING",
            category="normal",
            description="Soft field landing technique",
            user_prompts=[
                "Soft field. Holding it off.",
            ],
            expected_tools=["get_sim_state"],
            aircraft_types=GA_PISTON,
            weather_conditions=FAIR_WX,
            tags=["soft_field", "technique"],
        ),
        ScenarioTemplate(
            id="landing_go_around_01",
            phase="LANDING",
            category="abnormal",
            description="Go-around due to traffic on runway",
            user_prompts=[
                "Traffic on the runway! Going around!",
            ],
            expected_tools=["get_sim_state"],
            tags=["go_around", "traffic"],
        ),
        ScenarioTemplate(
            id="landing_go_around_02",
            phase="LANDING",
            category="abnormal",
            description="Go-around due to high and fast on final",
            user_prompts=[
                "Too high. Going around.",
            ],
            expected_tools=["get_sim_state"],
            tags=["go_around", "unstable"],
        ),
        ScenarioTemplate(
            id="landing_flare_01",
            phase="LANDING",
            category="normal",
            description="Flare and touchdown callouts",
            user_prompts=[
                "Fifty. Forty. Thirty.",
            ],
            expected_tools=["get_sim_state"],
            tags=["callouts", "flare"],
        ),
        ScenarioTemplate(
            id="landing_braking_01",
            phase="LANDING",
            category="normal",
            description="Braking action on touchdown",
            user_prompts=[
                "On the ground. Braking.",
            ],
            expected_tools=["get_sim_state"],
            tags=["braking", "rollout"],
        ),
        ScenarioTemplate(
            id="landing_contaminated_runway_01",
            phase="LANDING",
            category="abnormal",
            description="Landing on contaminated runway",
            user_prompts=[
                "Runway is wet. Braking action fair reported.",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            weather_conditions=BAD_WX,
            tags=["contaminated", "braking"],
        ),
        ScenarioTemplate(
            id="landing_bounced_01",
            phase="LANDING",
            category="abnormal",
            description="Bounced landing recovery",
            user_prompts=[
                "Bounced it. Recovering.",
            ],
            expected_tools=["get_sim_state"],
            tags=["bounced", "recovery"],
        ),
        ScenarioTemplate(
            id="landing_gusty_01",
            phase="LANDING",
            category="normal",
            description="Landing in gusty conditions",
            user_prompts=[
                "Gusts to 25 knots. Adding half gust factor.",
            ],
            expected_tools=["get_sim_state"],
            weather_conditions=["crosswind", "turbulence"],
            tags=["gusty", "speed_additive"],
        ),
        ScenarioTemplate(
            id="landing_reverse_thrust_01",
            phase="LANDING",
            category="normal",
            description="Deploying reverse thrust on landing",
            user_prompts=[
                "Reversers deployed.",
            ],
            expected_tools=["get_sim_state"],
            aircraft_types=JETS + TURBOPROP,
            tags=["reverse_thrust", "rollout"],
        ),
        ScenarioTemplate(
            id="landing_rollout_distance_01",
            phase="LANDING",
            category="normal",
            description="Pilot concerned about rollout distance",
            user_prompts=[
                "Halfway down the runway. How much is left?",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            tags=["rollout", "distance"],
        ),
        ScenarioTemplate(
            id="landing_no_flap_01",
            phase="LANDING",
            category="abnormal",
            description="Landing with partial or no flaps",
            user_prompts=[
                "Flaps won't extend. No-flap landing. Vref?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["no_flap", "abnormal", "emergency"],
        ),
        ScenarioTemplate(
            id="landing_tailwind_01",
            phase="LANDING",
            category="abnormal",
            description="Landing with a tailwind component",
            user_prompts=[
                "Winds shifted. We've got a tailwind now. Can we make it?",
            ],
            expected_tools=["get_sim_state", "lookup_airport"],
            tags=["tailwind", "performance"],
        ),
        ScenarioTemplate(
            id="landing_autobrakes_01",
            phase="LANDING",
            category="normal",
            description="Autobrake selection for landing",
            user_prompts=[
                "Autobrakes to three.",
            ],
            expected_tools=["get_sim_state"],
            aircraft_types=JETS,
            tags=["autobrakes", "configuration"],
        ),
    ]


# ===================================================================
# LANDED — 16 scenarios
# ===================================================================
def _landed_scenarios() -> list[ScenarioTemplate]:
    return [
        ScenarioTemplate(
            id="landed_checklist_01",
            phase="LANDED",
            category="normal",
            description="After-landing checklist",
            user_prompts=[
                "After landing checklist.",
                "Check.",
                "Check.",
            ],
            expected_tools=["get_checklist"],
            tags=["checklist"],
        ),
        ScenarioTemplate(
            id="landed_taxi_to_parking_01",
            phase="LANDED",
            category="normal",
            description="Taxi to parking after landing",
            user_prompts=[
                "Where's transient parking?",
                "Which taxiway?",
            ],
            expected_tools=["lookup_airport", "get_sim_state"],
            tags=["parking", "taxi"],
        ),
        ScenarioTemplate(
            id="landed_shutdown_checklist_01",
            phase="LANDED",
            category="normal",
            description="Engine shutdown and securing checklist",
            user_prompts=[
                "Run the shutdown checklist.",
                "Check.",
                "Check.",
            ],
            expected_tools=["get_checklist"],
            tags=["shutdown", "checklist"],
        ),
        ScenarioTemplate(
            id="landed_fuel_order_01",
            phase="LANDED",
            category="normal",
            description="Pilot orders fuel for the aircraft",
            user_prompts=[
                "How much fuel do we need for the return leg?",
                "Top off the mains then.",
            ],
            expected_tools=["get_sim_state", "create_flight_plan"],
            tags=["fuel", "turnaround"],
        ),
        ScenarioTemplate(
            id="landed_ground_frequency_01",
            phase="LANDED",
            category="normal",
            description="Pilot needs ground control frequency after landing",
            user_prompts=[
                "Ground frequency?",
            ],
            expected_tools=["lookup_airport"],
            tags=["frequency", "ground_control"],
        ),
        ScenarioTemplate(
            id="landed_debrief_01",
            phase="LANDED",
            category="normal",
            description="Post-flight debrief with MERLIN",
            user_prompts=[
                "How'd we do, MERLIN?",
                "Anything I should work on?",
            ],
            expected_tools=["get_sim_state"],
            tags=["debrief", "training"],
        ),
        ScenarioTemplate(
            id="landed_squawk_write_01",
            phase="LANDED",
            category="abnormal",
            description="Pilot needs to write up a maintenance squawk",
            user_prompts=[
                "I need to write up that rough-running engine. What should I note?",
                "And the sticky flap indicator too.",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["squawk", "maintenance"],
        ),
        ScenarioTemplate(
            id="landed_return_flight_plan_01",
            phase="LANDED",
            category="normal",
            description="Pilot plans the return flight",
            user_prompts=[
                "Let's plan the return trip to KBED.",
                "Same altitude as before?",
                "File it.",
            ],
            expected_tools=["create_flight_plan", "lookup_airport"],
            tags=["flight_plan", "return"],
        ),
        ScenarioTemplate(
            id="landed_unfamiliar_airport_01",
            phase="LANDED",
            category="normal",
            description="Pilot needs information about unfamiliar destination airport",
            user_prompts=[
                "Where do I get fuel here?",
                "Is there a restaurant on the field?",
            ],
            expected_tools=["lookup_airport"],
            tags=["airport_services", "unfamiliar"],
        ),
        ScenarioTemplate(
            id="landed_hobbs_time_01",
            phase="LANDED",
            category="normal",
            description="Recording flight times",
            user_prompts=[
                "What was our total flight time?",
                "And block time?",
            ],
            expected_tools=["get_sim_state"],
            tags=["flight_time", "logging"],
        ),
        ScenarioTemplate(
            id="landed_abnormal_brake_temp_01",
            phase="LANDED",
            category="abnormal",
            description="Hot brakes after landing",
            user_prompts=[
                "Brakes feel really hot after that short landing. What's the procedure?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["hot_brakes", "abnormal", "safety"],
        ),
        ScenarioTemplate(
            id="landed_customs_01",
            phase="LANDED",
            category="normal",
            description="International arrival procedures",
            user_prompts=[
                "We just landed from Canada. Where's customs?",
                "What forms do I need?",
            ],
            expected_tools=["lookup_airport", "search_manual"],
            tags=["customs", "international"],
        ),
        ScenarioTemplate(
            id="landed_passenger_deplane_01",
            phase="LANDED",
            category="normal",
            description="Passenger deplaning procedures",
            user_prompts=[
                "Safe to open the door?",
                "Engines and beacons off?",
            ],
            expected_tools=["get_sim_state"],
            tags=["passengers", "shutdown"],
        ),
        ScenarioTemplate(
            id="landed_weight_balance_return_01",
            phase="LANDED",
            category="normal",
            description="Weight and balance for return flight with different loading",
            user_prompts=[
                "We're picking up a third passenger on the way back. Recalculate weight and balance.",
                "Are we still within limits?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["weight_balance", "return"],
        ),
        ScenarioTemplate(
            id="landed_logbook_entry_01",
            phase="LANDED",
            category="normal",
            description="Pilot asks about logbook requirements",
            user_prompts=[
                "What should I log for this flight?",
                "Does the instrument approach count for currency?",
            ],
            expected_tools=["search_manual"],
            tags=["logbook", "currency", "regulations"],
        ),
        ScenarioTemplate(
            id="landed_tire_inspection_01",
            phase="LANDED",
            category="abnormal",
            description="Possible tire damage after landing",
            user_prompts=[
                "I heard a thump on landing. Should I check the tires?",
                "What am I looking for?",
            ],
            expected_tools=["search_manual", "get_sim_state"],
            tags=["tire", "inspection", "abnormal"],
        ),
    ]


# ===================================================================
# EMERGENCY — 30 scenarios
# ===================================================================
def _emergency_scenarios() -> list[ScenarioTemplate]:
    return [
        ScenarioTemplate(
            id="emergency_engine_failure_cruise_01",
            phase="CRUISE",
            category="emergency",
            description="Complete engine failure at cruise altitude",
            user_prompts=[
                "Engine just quit! Complete failure!",
                "Where can I land?",
            ],
            expected_tools=["get_sim_state", "lookup_airport", "search_manual"],
            aircraft_types=GA_PISTON,
            tags=["engine_failure", "single_engine", "glide"],
        ),
        ScenarioTemplate(
            id="emergency_engine_failure_cruise_02",
            phase="CRUISE",
            category="emergency",
            description="Engine failure in multi-engine aircraft",
            user_prompts=[
                "Number two engine is failing. Securing it.",
                "Can we maintain altitude on one engine?",
            ],
            expected_tools=["get_sim_state", "search_manual", "lookup_airport"],
            aircraft_types=JETS + TURBOPROP,
            tags=["engine_failure", "multi_engine"],
        ),
        ScenarioTemplate(
            id="emergency_fire_engine_01",
            phase="CRUISE",
            category="emergency",
            description="Engine fire in flight",
            user_prompts=[
                "Engine fire! Fire light is on!",
                "Extinguisher discharged. Is it out?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["fire", "engine_fire", "emergency"],
        ),
        ScenarioTemplate(
            id="emergency_fire_electrical_01",
            phase="CRUISE",
            category="emergency",
            description="Electrical fire / smoke in cockpit",
            user_prompts=[
                "I smell smoke! Electrical fire!",
                "What's the procedure?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["fire", "electrical_fire", "smoke"],
        ),
        ScenarioTemplate(
            id="emergency_rapid_depress_01",
            phase="CRUISE",
            category="emergency",
            description="Rapid cabin depressurization at high altitude",
            user_prompts=[
                "Cabin altitude warning! We're depressurizing!",
                "Emergency descent!",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=JETS + TURBOPROP,
            tags=["depressurization", "emergency_descent"],
        ),
        ScenarioTemplate(
            id="emergency_fuel_emergency_01",
            phase="CRUISE",
            category="emergency",
            description="Minimum fuel / fuel emergency declaration",
            user_prompts=[
                "We're down to 30 minutes of fuel. Declaring minimum fuel.",
                "Nearest airport NOW.",
            ],
            expected_tools=["get_sim_state", "lookup_airport", "create_flight_plan"],
            tags=["fuel_emergency", "mayday"],
        ),
        ScenarioTemplate(
            id="emergency_fuel_leak_01",
            phase="CRUISE",
            category="emergency",
            description="Fuel leak detected in flight",
            user_prompts=[
                "Fuel quantity is dropping way too fast. I think we have a leak.",
                "Nearest suitable?",
            ],
            expected_tools=["get_sim_state", "lookup_airport", "create_flight_plan"],
            tags=["fuel_leak", "diversion"],
        ),
        ScenarioTemplate(
            id="emergency_vacuum_failure_01",
            phase="CRUISE",
            category="emergency",
            description="Vacuum system failure in IMC",
            user_prompts=[
                "Vacuum just failed and we're in the clouds.",
                "Partial panel. What instruments do I still have?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=GA_PISTON,
            weather_conditions=["IFR"],
            tags=["vacuum_failure", "partial_panel", "IMC"],
        ),
        ScenarioTemplate(
            id="emergency_pitot_ice_01",
            phase="CRUISE",
            category="emergency",
            description="Pitot tube icing causing erroneous airspeed",
            user_prompts=[
                "Airspeed is going crazy. I think the pitot tube is iced up.",
                "What's my power setting for level flight without airspeed?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            weather_conditions=["icing"],
            tags=["pitot_ice", "unreliable_airspeed"],
        ),
        ScenarioTemplate(
            id="emergency_gear_failure_01",
            phase="APPROACH",
            category="emergency",
            description="Landing gear won't extend",
            user_prompts=[
                "Gear won't come down! Manual extension procedure?",
                "Still no green light.",
                "We might have to belly it in.",
            ],
            expected_tools=["get_sim_state", "search_manual", "lookup_airport"],
            tags=["gear_failure", "belly_landing"],
        ),
        ScenarioTemplate(
            id="emergency_medical_pilot_01",
            phase="CRUISE",
            category="emergency",
            description="Pilot experiencing medical issue in flight",
            user_prompts=[
                "I'm not feeling well. Vision is getting blurry.",
                "I might need to land soon.",
            ],
            expected_tools=["get_sim_state", "lookup_airport", "create_flight_plan"],
            tags=["pilot_incapacitation", "medical"],
        ),
        ScenarioTemplate(
            id="emergency_medical_passenger_01",
            phase="CRUISE",
            category="emergency",
            description="Passenger medical emergency requiring immediate diversion",
            user_prompts=[
                "My passenger is having chest pains. I need the nearest airport with medical facilities.",
                "Declaring emergency.",
            ],
            expected_tools=["get_sim_state", "lookup_airport", "create_flight_plan"],
            tags=["medical_emergency", "passenger", "diversion"],
        ),
        ScenarioTemplate(
            id="emergency_bird_strike_cruise_01",
            phase="CRUISE",
            category="emergency",
            description="Bird strike causing windshield damage",
            user_prompts=[
                "Bird strike! Windshield is cracked!",
                "Can we still fly with this?",
            ],
            expected_tools=["get_sim_state", "search_manual", "lookup_airport"],
            tags=["bird_strike", "windshield"],
        ),
        ScenarioTemplate(
            id="emergency_engine_rough_01",
            phase="CLIMB",
            category="emergency",
            description="Engine running extremely rough with vibration",
            user_prompts=[
                "Engine is vibrating badly! Losing power!",
                "Should I return to the field?",
            ],
            expected_tools=["get_sim_state", "search_manual", "lookup_airport"],
            aircraft_types=GA_PISTON,
            tags=["engine_rough", "vibration", "return_to_field"],
        ),
        ScenarioTemplate(
            id="emergency_icing_severe_01",
            phase="CRUISE",
            category="emergency",
            description="Severe icing accumulation",
            user_prompts=[
                "Ice is building fast and the boots can't keep up! We're losing airspeed.",
                "Requesting immediate descent.",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            weather_conditions=["icing"],
            tags=["severe_icing", "performance_degradation"],
        ),
        ScenarioTemplate(
            id="emergency_door_open_01",
            phase="CLIMB",
            category="emergency",
            description="Cabin door opens in flight",
            user_prompts=[
                "The door just popped open!",
                "What do I do?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=GA_PISTON,
            tags=["door_open", "structural"],
        ),
        ScenarioTemplate(
            id="emergency_trim_runaway_01",
            phase="CRUISE",
            category="emergency",
            description="Runaway pitch trim",
            user_prompts=[
                "The trim is running away nose-down! I can't stop it!",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["trim_runaway", "flight_controls"],
        ),
        ScenarioTemplate(
            id="emergency_hydraulic_failure_01",
            phase="DESCENT",
            category="emergency",
            description="Hydraulic system failure",
            user_prompts=[
                "Hydraulic pressure is zero. What systems are affected?",
                "Can we still land?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=JETS,
            tags=["hydraulic_failure", "systems"],
        ),
        ScenarioTemplate(
            id="emergency_total_electrical_01",
            phase="CRUISE",
            category="emergency",
            description="Total electrical failure in flight",
            user_prompts=[
                "Everything just went dark. Total electrical failure.",
                "Battery is dead too.",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["electrical_failure", "total"],
        ),
        ScenarioTemplate(
            id="emergency_structural_failure_01",
            phase="CRUISE",
            category="emergency",
            description="Structural damage from severe turbulence",
            user_prompts=[
                "We hit severe turbulence and I heard a loud bang. Something is bent on the wing.",
                "Reducing speed. Where do we land?",
            ],
            expected_tools=["get_sim_state", "lookup_airport", "search_manual"],
            weather_conditions=["turbulence"],
            tags=["structural", "turbulence_damage"],
        ),
        ScenarioTemplate(
            id="emergency_carb_ice_01",
            phase="CRUISE",
            category="emergency",
            description="Carburetor ice causing engine power loss",
            user_prompts=[
                "RPM is dropping and I've got carb heat on. It's not recovering.",
                "What else can I do?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=GA_PISTON,
            weather_conditions=["marginal_vfr", "IFR", "icing"],
            tags=["carb_ice", "engine_power_loss"],
        ),
        ScenarioTemplate(
            id="emergency_flap_asymmetry_01",
            phase="APPROACH",
            category="emergency",
            description="Asymmetric flap deployment",
            user_prompts=[
                "One flap is down and the other isn't! Rolling hard!",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["flap_asymmetry", "flight_controls"],
        ),
        ScenarioTemplate(
            id="emergency_comm_failure_imc_01",
            phase="CRUISE",
            category="emergency",
            description="Communications failure in instrument conditions",
            user_prompts=[
                "I've lost all radios in IMC. What's the procedure?",
                "Squawking 7600.",
            ],
            expected_tools=["get_sim_state", "search_manual", "create_flight_plan"],
            weather_conditions=["IFR"],
            tags=["comm_failure", "IMC", "7600"],
        ),
        ScenarioTemplate(
            id="emergency_spatial_disorientation_01",
            phase="CRUISE",
            category="emergency",
            description="Pilot experiencing spatial disorientation",
            user_prompts=[
                "MERLIN, I'm getting vertigo. I can't tell which way is up.",
                "Talk me through this.",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            weather_conditions=["IFR"],
            tags=["spatial_disorientation", "vertigo"],
        ),
        ScenarioTemplate(
            id="emergency_prop_strike_01",
            phase="TAKEOFF",
            category="emergency",
            description="Propeller strike on takeoff from debris",
            user_prompts=[
                "Hit something on the runway! Bad vibration!",
                "Aborting!",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            aircraft_types=GA_PISTON + TURBOPROP,
            tags=["prop_strike", "FOD"],
        ),
        ScenarioTemplate(
            id="emergency_oil_pressure_loss_01",
            phase="CRUISE",
            category="emergency",
            description="Sudden oil pressure loss in flight",
            user_prompts=[
                "Oil pressure just went to zero!",
                "How much time do I have before the engine seizes?",
            ],
            expected_tools=["get_sim_state", "search_manual", "lookup_airport"],
            aircraft_types=GA_PISTON,
            tags=["oil_pressure", "engine_failure_imminent"],
        ),
        ScenarioTemplate(
            id="emergency_dual_engine_failure_01",
            phase="CRUISE",
            category="emergency",
            description="Dual engine failure on a twin",
            user_prompts=[
                "Both engines are out! We're a glider!",
                "Best glide speed? Nearest runway?",
            ],
            expected_tools=["get_sim_state", "search_manual", "lookup_airport"],
            aircraft_types=HEAVY_JETS,
            tags=["dual_engine_failure", "glide"],
        ),
        ScenarioTemplate(
            id="emergency_stuck_throttle_01",
            phase="DESCENT",
            category="emergency",
            description="Throttle stuck in cruise position during descent",
            user_prompts=[
                "Throttle is jammed. I can't reduce power.",
                "How do I get down?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["stuck_throttle", "flight_controls"],
        ),
        ScenarioTemplate(
            id="emergency_cargo_smoke_01",
            phase="CRUISE",
            category="emergency",
            description="Smoke detected from cargo area",
            user_prompts=[
                "Smoke alarm from the cargo hold!",
                "Descending and diverting. Nearest field?",
            ],
            expected_tools=["get_sim_state", "search_manual", "lookup_airport", "create_flight_plan"],
            aircraft_types=JETS,
            tags=["cargo_fire", "smoke", "diversion"],
        ),
        ScenarioTemplate(
            id="emergency_flight_control_jam_01",
            phase="CRUISE",
            category="emergency",
            description="Jammed flight control surface",
            user_prompts=[
                "Ailerons are locked up. I can only use rudder for turns.",
                "What's the procedure?",
            ],
            expected_tools=["get_sim_state", "search_manual"],
            tags=["flight_control_jam", "partial_control"],
        ),
    ]


# ===================================================================
# Aggregate list
# ===================================================================
ALL_SCENARIOS: list[ScenarioTemplate] = (
    _preflight_scenarios()
    + _taxi_scenarios()
    + _takeoff_scenarios()
    + _climb_scenarios()
    + _cruise_scenarios()
    + _descent_scenarios()
    + _approach_scenarios()
    + _landing_scenarios()
    + _landed_scenarios()
    + _emergency_scenarios()
)


# ===================================================================
# Expansion function
# ===================================================================
_DEFAULT_AIRCRAFT = [
    "Cessna 172 Skyhawk",
    "Piper PA-28 Cherokee",
    "Diamond DA40 Diamond Star",
    "Cirrus SR22",
    "Beechcraft King Air 350",
    "Cessna Citation CJ4",
    "Boeing 747-8",
    "Airbus A320neo",
]


def expand_scenarios(
    scenarios: list[ScenarioTemplate] | None = None,
    max_per_template: int = 15,
    seed: int = 42,
) -> list[dict]:
    """Expand templates into concrete scenario instances.

    Each template is expanded with combinations of compatible aircraft,
    weather, and pilot level. Returns dicts with resolved values.

    Args:
        scenarios: Templates to expand. Defaults to ALL_SCENARIOS.
        max_per_template: Maximum number of unique (aircraft, weather,
            pilot_level) combinations to emit per template.
        seed: Random seed for reproducible sampling.

    Returns:
        List of dicts with keys: scenario_id, template_id, phase,
        category, description, user_prompts, expected_tools, aircraft,
        weather, pilot_level, tags.
    """
    if scenarios is None:
        scenarios = ALL_SCENARIOS

    rng = random.Random(seed)
    results: list[dict] = []

    for tmpl in scenarios:
        aircraft_pool = tmpl.aircraft_types if tmpl.aircraft_types else _DEFAULT_AIRCRAFT
        weather_pool = tmpl.weather_conditions
        pilot_pool = tmpl.pilot_levels

        all_combos = list(itertools.product(aircraft_pool, weather_pool, pilot_pool))
        rng.shuffle(all_combos)
        selected = all_combos[:max_per_template]

        for idx, (aircraft, weather, pilot_level) in enumerate(selected, start=1):
            scenario_id = f"{tmpl.id}_{idx:03d}"
            results.append(
                {
                    "scenario_id": scenario_id,
                    "template_id": tmpl.id,
                    "phase": tmpl.phase,
                    "category": tmpl.category,
                    "description": tmpl.description,
                    "user_prompts": list(tmpl.user_prompts),
                    "expected_tools": list(tmpl.expected_tools),
                    "aircraft": aircraft,
                    "weather": weather,
                    "pilot_level": pilot_level,
                    "tags": list(tmpl.tags),
                }
            )

    return results
