"""Response validation for aviation-critical numerical data.

Scans Claude's responses for V-speeds, altitudes, frequencies, and other
safety-critical numbers, then cross-references against a structured
lookup database. Flags discrepancies and appends corrections.

Also provides telemetry sanity checks to protect against garbage data
from SimConnect.

Usage:
    validator = ResponseValidator()
    corrected, warnings = validator.validate_response(
        response_text, aircraft_type="C172"
    )
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .sim_client import SimState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Aircraft performance database
# ---------------------------------------------------------------------------


@dataclass
class AircraftLimits:
    """Operating limitations and V-speeds for a specific aircraft type."""

    # V-speeds (knots)
    vs0: float = 0.0  # Stall speed, landing configuration
    vs1: float = 0.0  # Stall speed, clean configuration
    vfe: float = 0.0  # Max flap extended speed
    vno: float = 0.0  # Max structural cruising speed
    vne: float = 0.0  # Never exceed speed
    vr: float = 0.0  # Rotation speed
    vx: float = 0.0  # Best angle of climb
    vy: float = 0.0  # Best rate of climb
    vglide: float = 0.0  # Best glide speed

    # Operating limits
    max_altitude: float = 0.0  # feet (service ceiling)
    max_gross_weight: float = 0.0  # lbs
    fuel_capacity_gal: float = 0.0  # gallons

    # Common aliases for aircraft name matching
    aliases: set[str] = field(default_factory=set)


# Pre-populated database for common sim aircraft
AIRCRAFT_DATABASE: dict[str, AircraftLimits] = {
    "C172": AircraftLimits(
        vs0=48,
        vs1=53,
        vfe=110,
        vno=129,
        vne=163,
        vr=55,
        vx=62,
        vy=74,
        vglide=65,
        max_altitude=14000,
        max_gross_weight=2550,
        fuel_capacity_gal=56,
        aliases={"Cessna 172", "C172S", "Cessna 172 Skyhawk", "172SP"},
    ),
    "C152": AircraftLimits(
        vs0=43,
        vs1=48,
        vfe=85,
        vno=111,
        vne=149,
        vr=50,
        vx=55,
        vy=67,
        vglide=60,
        max_altitude=14700,
        max_gross_weight=1670,
        fuel_capacity_gal=26,
        aliases={"Cessna 152"},
    ),
    "PA28": AircraftLimits(
        vs0=50,
        vs1=55,
        vfe=103,
        vno=125,
        vne=154,
        vr=60,
        vx=64,
        vy=79,
        vglide=73,
        max_altitude=14000,
        max_gross_weight=2325,
        fuel_capacity_gal=50,
        aliases={"Piper Cherokee", "PA-28", "Piper Warrior", "PA28-161"},
    ),
    "SR22": AircraftLimits(
        vs0=59,
        vs1=69,
        vfe=119,
        vno=176,
        vne=201,
        vr=73,
        vx=82,
        vy=101,
        vglide=88,
        max_altitude=17500,
        max_gross_weight=3400,
        fuel_capacity_gal=92,
        aliases={"Cirrus SR22", "SR22T"},
    ),
    "DA40": AircraftLimits(
        vs0=49,
        vs1=57,
        vfe=108,
        vno=129,
        vne=178,
        vr=59,
        vx=66,
        vy=78,
        vglide=73,
        max_altitude=16400,
        max_gross_weight=2535,
        fuel_capacity_gal=40,
        aliases={"Diamond DA40", "DA40NG"},
    ),
    "B738": AircraftLimits(
        vs0=115,
        vs1=130,
        vfe=230,
        vno=340,
        vne=365,
        vr=145,
        vx=0,
        vy=0,
        vglide=220,
        max_altitude=41000,
        max_gross_weight=174200,
        fuel_capacity_gal=6875,
        aliases={"Boeing 737-800", "737-800", "738", "B737"},
    ),
    "A320": AircraftLimits(
        vs0=118,
        vs1=133,
        vfe=230,
        vno=350,
        vne=381,
        vr=148,
        vx=0,
        vy=0,
        vglide=220,
        max_altitude=39800,
        max_gross_weight=170000,
        fuel_capacity_gal=6300,
        aliases={"Airbus A320", "A320neo", "A320-200"},
    ),
}

# Standard aviation frequencies
STANDARD_FREQUENCIES: dict[str, float] = {
    "emergency": 121.5,
    "guard": 121.5,
    "universal_unicom": 122.8,
    "multicom": 122.9,
    "ctaf_default": 122.7,
    "flight_service": 122.2,
}


# ---------------------------------------------------------------------------
# V-speed extraction patterns
# ---------------------------------------------------------------------------

_VSPEED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("vs0", re.compile(r"\bVs0\b.*?(\d{2,3})\s*(?:knots|kt)", re.I)),
    ("vs1", re.compile(r"\bVs1\b.*?(\d{2,3})\s*(?:knots|kt)", re.I)),
    ("vfe", re.compile(r"\bVfe\b.*?(\d{2,3})\s*(?:knots|kt)", re.I)),
    ("vno", re.compile(r"\bVno\b.*?(\d{2,3})\s*(?:knots|kt)", re.I)),
    ("vne", re.compile(r"\bVne\b.*?(\d{2,3})\s*(?:knots|kt)", re.I)),
    ("vr", re.compile(r"\bVr\b.*?(\d{2,3})\s*(?:knots|kt)", re.I)),
    ("vx", re.compile(r"\bVx\b.*?(\d{2,3})\s*(?:knots|kt)", re.I)),
    ("vy", re.compile(r"\bVy\b.*?(\d{2,3})\s*(?:knots|kt)", re.I)),
    ("vglide", re.compile(r"\b(?:Vg|best\s+glide)\b.*?(\d{2,3})\s*(?:knots|kt)", re.I)),
]

# Pattern to extract altitude mentions
_ALTITUDE_PATTERN = re.compile(
    r"(\d{1,3}(?:,\d{3})*)\s*(?:feet|ft)\b",
    re.I,
)

# Pattern to extract frequency mentions
_FREQUENCY_PATTERN = re.compile(
    r"\b(\d{3}\.\d{1,3})\b",
)


@dataclass
class ValidationWarning:
    """A warning about a potentially incorrect number in a response."""

    field: str
    claimed_value: float
    correct_value: float
    message: str
    severity: str = "warning"  # "warning" or "critical"


def resolve_aircraft_type(aircraft_name: str) -> AircraftLimits | None:
    """Look up aircraft limits by name, type code, or alias."""
    name_upper = aircraft_name.upper().strip()
    # Direct match
    if name_upper in AIRCRAFT_DATABASE:
        return AIRCRAFT_DATABASE[name_upper]
    # Search aliases
    for _code, limits in AIRCRAFT_DATABASE.items():
        for alias in limits.aliases:
            if alias.upper() in name_upper or name_upper in alias.upper():
                return limits
    return None


class ResponseValidator:
    """Validates Claude's responses against known aircraft data."""

    def __init__(self, tolerance_pct: float = 10.0) -> None:
        self._tolerance_pct = tolerance_pct

    def validate_response(
        self,
        response_text: str,
        aircraft_type: str = "",
    ) -> tuple[str, list[ValidationWarning]]:
        """Scan response for aviation numbers and validate against database.

        Returns:
            Tuple of (potentially corrected response text, list of warnings).
        """
        warnings: list[ValidationWarning] = []

        limits = resolve_aircraft_type(aircraft_type) if aircraft_type else None

        if limits:
            warnings.extend(self._check_vspeeds(response_text, limits))

        warnings.extend(self._check_frequencies(response_text))

        # Append correction notes if there are critical warnings
        corrected = response_text
        critical = [w for w in warnings if w.severity == "critical"]
        if critical:
            corrections = []
            for w in critical:
                corrections.append(f"[CORRECTION: {w.message}]")
                logger.warning("Validation: %s", w.message)
            corrected = response_text + "\n\n" + "\n".join(corrections)

        return corrected, warnings

    def _check_vspeeds(
        self,
        text: str,
        limits: AircraftLimits,
    ) -> list[ValidationWarning]:
        """Extract V-speed mentions and validate against aircraft database."""
        warnings = []
        for vname, pattern in _VSPEED_PATTERNS:
            match = pattern.search(text)
            if match:
                claimed = float(match.group(1))
                correct = getattr(limits, vname, 0.0)
                if correct > 0 and not self._within_tolerance(claimed, correct):
                    severity = "critical" if vname in ("vfe", "vne", "vs0") else "warning"
                    warnings.append(
                        ValidationWarning(
                            field=vname.upper(),
                            claimed_value=claimed,
                            correct_value=correct,
                            message=(
                                f"{vname.upper()} stated as {claimed:.0f} kt "
                                f"but database shows {correct:.0f} kt"
                            ),
                            severity=severity,
                        )
                    )
        return warnings

    def _check_frequencies(
        self,
        text: str,
    ) -> list[ValidationWarning]:
        """Check for obviously invalid frequency references."""
        warnings = []
        for match in _FREQUENCY_PATTERN.finditer(text):
            freq = float(match.group(1))
            # Comm band is 118.000-136.975, Nav band is 108.0-117.95
            if 108.0 <= freq <= 136.975:
                continue  # Valid aviation range
            if 200.0 <= freq <= 400.0:
                continue  # Military UHF range
            # Flag frequencies outside valid aviation ranges
            if freq > 0 and (freq < 108.0 or freq > 400.0):
                warnings.append(
                    ValidationWarning(
                        field="frequency",
                        claimed_value=freq,
                        correct_value=0,
                        message=f"Frequency {freq:.3f} is outside aviation bands",
                        severity="warning",
                    )
                )
        return warnings

    def _within_tolerance(self, claimed: float, correct: float) -> bool:
        """Check if a claimed value is within tolerance of the correct value."""
        if correct == 0:
            return True
        diff_pct = abs(claimed - correct) / correct * 100
        return diff_pct <= self._tolerance_pct


# ---------------------------------------------------------------------------
# Telemetry sanity checks
# ---------------------------------------------------------------------------


@dataclass
class TelemetrySanityWarning:
    """A warning about impossible telemetry values."""

    field: str
    value: float
    message: str


def check_telemetry_sanity(state: SimState) -> list[TelemetrySanityWarning]:
    """Validate incoming telemetry for impossible values.

    Protects against SimConnect returning garbage data.
    """
    warnings: list[TelemetrySanityWarning] = []

    # Altitude checks
    if state.position.altitude_msl < -1500:
        warnings.append(
            TelemetrySanityWarning(
                field="altitude_msl",
                value=state.position.altitude_msl,
                message=f"Impossible altitude: {state.position.altitude_msl:.0f} ft MSL",
            )
        )

    if state.position.altitude_agl < -100:
        warnings.append(
            TelemetrySanityWarning(
                field="altitude_agl",
                value=state.position.altitude_agl,
                message=f"Impossible AGL: {state.position.altitude_agl:.0f} ft",
            )
        )

    # Speed checks (Mach 2+ for GA is impossible)
    if state.speeds.mach > 2.0 and state.speeds.indicated_airspeed < 500:
        warnings.append(
            TelemetrySanityWarning(
                field="mach",
                value=state.speeds.mach,
                message=f"Impossible Mach: {state.speeds.mach:.2f} for GA aircraft",
            )
        )

    if state.speeds.indicated_airspeed < -10:
        warnings.append(
            TelemetrySanityWarning(
                field="indicated_airspeed",
                value=state.speeds.indicated_airspeed,
                message=f"Negative IAS: {state.speeds.indicated_airspeed:.0f} kt",
            )
        )

    if state.speeds.indicated_airspeed > 800:
        warnings.append(
            TelemetrySanityWarning(
                field="indicated_airspeed",
                value=state.speeds.indicated_airspeed,
                message=f"Impossible IAS: {state.speeds.indicated_airspeed:.0f} kt",
            )
        )

    # Position checks
    lat = state.position.latitude
    lon = state.position.longitude
    if lat != 0 and (lat < -90 or lat > 90):
        warnings.append(
            TelemetrySanityWarning(
                field="latitude",
                value=lat,
                message=f"Impossible latitude: {lat:.6f}",
            )
        )
    if lon != 0 and (lon < -180 or lon > 180):
        warnings.append(
            TelemetrySanityWarning(
                field="longitude",
                value=lon,
                message=f"Impossible longitude: {lon:.6f}",
            )
        )

    # Engine checks
    for i, engine in enumerate(state.engines.active_engines):
        if engine.rpm < -1:
            warnings.append(
                TelemetrySanityWarning(
                    field=f"engine_{i}_rpm",
                    value=engine.rpm,
                    message=f"Negative RPM on engine {i}: {engine.rpm:.0f}",
                )
            )
        if engine.oil_temp > 500:
            warnings.append(
                TelemetrySanityWarning(
                    field=f"engine_{i}_oil_temp",
                    value=engine.oil_temp,
                    message=f"Impossible oil temp on engine {i}: {engine.oil_temp:.0f}°",
                )
            )

    for w in warnings:
        logger.warning("Telemetry sanity: %s", w.message)

    return warnings
