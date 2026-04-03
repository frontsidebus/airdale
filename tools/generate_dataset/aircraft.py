"""Aircraft profiles with realistic performance data for telemetry generation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AircraftProfile:
    """Performance and configuration data for a specific aircraft type."""

    name: str
    aircraft_class: str  # "single_engine_piston" | "turboprop" | "jet_turbofan"
    engine_count: int
    engine_type: str  # "piston" | "turboprop" | "turbofan"

    # V-speeds (knots indicated)
    vr: int  # Rotation
    vy: int  # Best rate of climb
    vref: int  # Reference approach speed
    best_glide: int
    cruise_speed_kias: int
    vne: int  # Never exceed

    # Performance
    max_altitude: int  # Service ceiling (feet)
    typical_cruise_altitude: int  # Typical cruise FL/altitude
    climb_rate_fpm: int  # Typical climb rate
    fuel_capacity_gal: float
    fuel_burn_gph: float  # Cruise fuel burn per engine

    # Configuration
    has_retractable_gear: bool
    has_constant_speed_prop: bool
    has_pressurization: bool

    # Engine parameters (typical cruise)
    typical_cruise_rpm: int | None = None  # Piston
    typical_cruise_mp: float | None = None  # Manifold pressure (piston)
    typical_cruise_n1: float | None = None  # Jet/turboprop percent


# ---------------------------------------------------------------------------
# Aircraft profiles
# ---------------------------------------------------------------------------

CESSNA_172 = AircraftProfile(
    name="Cessna 172 Skyhawk",
    aircraft_class="single_engine_piston",
    engine_count=1,
    engine_type="piston",
    vr=55,
    vy=74,
    vref=65,
    best_glide=68,
    cruise_speed_kias=122,
    vne=163,
    max_altitude=14000,
    typical_cruise_altitude=6500,
    climb_rate_fpm=730,
    fuel_capacity_gal=56,
    fuel_burn_gph=8.5,
    has_retractable_gear=False,
    has_constant_speed_prop=False,
    has_pressurization=False,
    typical_cruise_rpm=2400,
    typical_cruise_mp=23.0,
)

PIPER_PA28 = AircraftProfile(
    name="Piper PA-28 Cherokee",
    aircraft_class="single_engine_piston",
    engine_count=1,
    engine_type="piston",
    vr=60,
    vy=76,
    vref=66,
    best_glide=73,
    cruise_speed_kias=128,
    vne=171,
    max_altitude=14300,
    typical_cruise_altitude=6500,
    climb_rate_fpm=660,
    fuel_capacity_gal=50,
    fuel_burn_gph=9.0,
    has_retractable_gear=False,
    has_constant_speed_prop=False,
    has_pressurization=False,
    typical_cruise_rpm=2450,
    typical_cruise_mp=24.0,
)

DIAMOND_DA40 = AircraftProfile(
    name="Diamond DA40 Diamond Star",
    aircraft_class="single_engine_piston",
    engine_count=1,
    engine_type="piston",
    vr=59,
    vy=78,
    vref=67,
    best_glide=73,
    cruise_speed_kias=135,
    vne=178,
    max_altitude=16400,
    typical_cruise_altitude=7500,
    climb_rate_fpm=1070,
    fuel_capacity_gal=40,
    fuel_burn_gph=7.5,
    has_retractable_gear=False,
    has_constant_speed_prop=False,
    has_pressurization=False,
    typical_cruise_rpm=2300,
    typical_cruise_mp=23.0,
)

CIRRUS_SR22 = AircraftProfile(
    name="Cirrus SR22",
    aircraft_class="single_engine_piston",
    engine_count=1,
    engine_type="piston",
    vr=70,
    vy=101,
    vref=80,
    best_glide=88,
    cruise_speed_kias=176,
    vne=200,
    max_altitude=17500,
    typical_cruise_altitude=9000,
    climb_rate_fpm=1270,
    fuel_capacity_gal=81,
    fuel_burn_gph=13.5,
    has_retractable_gear=False,
    has_constant_speed_prop=True,
    has_pressurization=False,
    typical_cruise_rpm=2500,
    typical_cruise_mp=25.0,
)

KING_AIR_350 = AircraftProfile(
    name="Beechcraft King Air 350",
    aircraft_class="turboprop",
    engine_count=2,
    engine_type="turboprop",
    vr=107,
    vy=140,
    vref=112,
    best_glide=130,
    cruise_speed_kias=270,
    vne=310,
    max_altitude=35000,
    typical_cruise_altitude=27000,
    climb_rate_fpm=2730,
    fuel_capacity_gal=539,
    fuel_burn_gph=55.0,
    has_retractable_gear=True,
    has_constant_speed_prop=True,
    has_pressurization=True,
    typical_cruise_n1=96.0,
)

CITATION_CJ4 = AircraftProfile(
    name="Cessna Citation CJ4",
    aircraft_class="jet_turbofan",
    engine_count=2,
    engine_type="turbofan",
    vr=108,
    vy=170,
    vref=113,
    best_glide=155,
    cruise_speed_kias=340,
    vne=365,
    max_altitude=45000,
    typical_cruise_altitude=39000,
    climb_rate_fpm=3854,
    fuel_capacity_gal=580,
    fuel_burn_gph=80.0,
    has_retractable_gear=True,
    has_constant_speed_prop=False,
    has_pressurization=True,
    typical_cruise_n1=88.0,
)

BOEING_747 = AircraftProfile(
    name="Boeing 747-8",
    aircraft_class="jet_turbofan",
    engine_count=4,
    engine_type="turbofan",
    vr=160,
    vy=250,
    vref=152,
    best_glide=220,
    cruise_speed_kias=490,
    vne=530,
    max_altitude=43100,
    typical_cruise_altitude=37000,
    climb_rate_fpm=2500,
    fuel_capacity_gal=63705,
    fuel_burn_gph=2600.0,
    has_retractable_gear=True,
    has_constant_speed_prop=False,
    has_pressurization=True,
    typical_cruise_n1=85.0,
)

AIRBUS_A320 = AircraftProfile(
    name="Airbus A320neo",
    aircraft_class="jet_turbofan",
    engine_count=2,
    engine_type="turbofan",
    vr=145,
    vy=210,
    vref=137,
    best_glide=200,
    cruise_speed_kias=447,
    vne=480,
    max_altitude=39800,
    typical_cruise_altitude=36000,
    climb_rate_fpm=2500,
    fuel_capacity_gal=6300,
    fuel_burn_gph=640.0,
    has_retractable_gear=True,
    has_constant_speed_prop=False,
    has_pressurization=True,
    typical_cruise_n1=87.0,
)

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

ALL_AIRCRAFT: list[AircraftProfile] = [
    CESSNA_172,
    PIPER_PA28,
    DIAMOND_DA40,
    CIRRUS_SR22,
    KING_AIR_350,
    CITATION_CJ4,
    BOEING_747,
    AIRBUS_A320,
]

AIRCRAFT_BY_NAME: dict[str, AircraftProfile] = {a.name: a for a in ALL_AIRCRAFT}

PISTON_AIRCRAFT = [a for a in ALL_AIRCRAFT if a.engine_type == "piston"]
JET_AIRCRAFT = [a for a in ALL_AIRCRAFT if a.engine_type == "turbofan"]
TURBOPROP_AIRCRAFT = [a for a in ALL_AIRCRAFT if a.engine_type == "turboprop"]
GA_AIRCRAFT = PISTON_AIRCRAFT + TURBOPROP_AIRCRAFT  # General aviation

# Checklist YAML mapping
CHECKLIST_FILE_MAP: dict[str, str] = {
    "single_engine_piston": "generic_single_engine.yaml",
    "turboprop": "generic_jet.yaml",
    "jet_turbofan": "generic_jet.yaml",
}
