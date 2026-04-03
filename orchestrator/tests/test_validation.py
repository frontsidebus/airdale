"""Tests for response validation and telemetry sanity checks."""

from __future__ import annotations

from orchestrator.sim_client import (
    EngineData,
    Engines,
    Position,
    SimState,
    Speeds,
)
from orchestrator.validation import (
    AIRCRAFT_DATABASE,
    ResponseValidator,
    check_telemetry_sanity,
    resolve_aircraft_type,
)

# ---------------------------------------------------------------------------
# Aircraft resolution
# ---------------------------------------------------------------------------


class TestAircraftResolution:
    def test_direct_match(self) -> None:
        limits = resolve_aircraft_type("C172")
        assert limits is not None
        assert limits.vfe == 110

    def test_alias_match(self) -> None:
        limits = resolve_aircraft_type("Cessna 172 Skyhawk")
        assert limits is not None
        assert limits.vs0 == 48

    def test_case_insensitive(self) -> None:
        limits = resolve_aircraft_type("c172")
        assert limits is not None

    def test_unknown_aircraft(self) -> None:
        limits = resolve_aircraft_type("Lockheed SR-71")
        assert limits is None

    def test_all_database_entries_have_vfe(self) -> None:
        for code, limits in AIRCRAFT_DATABASE.items():
            assert limits.vfe > 0, f"{code} has no Vfe"


# ---------------------------------------------------------------------------
# V-speed validation
# ---------------------------------------------------------------------------


class TestVSpeedValidation:
    def setup_method(self) -> None:
        self.validator = ResponseValidator(tolerance_pct=10.0)

    def test_correct_vfe_passes(self) -> None:
        text = "The Vfe for this aircraft is 110 knots."
        _corrected, warnings = self.validator.validate_response(text, "C172")
        vfe_warnings = [w for w in warnings if w.field == "VFE"]
        assert len(vfe_warnings) == 0

    def test_wrong_vfe_flagged(self) -> None:
        text = "The Vfe is 85 knots."
        _corrected, warnings = self.validator.validate_response(text, "C172")
        vfe_warnings = [w for w in warnings if w.field == "VFE"]
        assert len(vfe_warnings) == 1
        assert vfe_warnings[0].claimed_value == 85
        assert vfe_warnings[0].correct_value == 110
        assert vfe_warnings[0].severity == "critical"

    def test_within_tolerance_passes(self) -> None:
        # 10% tolerance: 110 ± 11 → 99-121 is OK
        text = "The Vfe is 105 knots."
        _corrected, warnings = self.validator.validate_response(text, "C172")
        vfe_warnings = [w for w in warnings if w.field == "VFE"]
        assert len(vfe_warnings) == 0

    def test_no_aircraft_skips_vspeed_check(self) -> None:
        text = "The Vfe is 999 knots."
        _corrected, warnings = self.validator.validate_response(text, "")
        assert len(warnings) == 0

    def test_critical_warning_appends_correction(self) -> None:
        text = "The Vfe is 85 knots."
        corrected, _warnings = self.validator.validate_response(text, "C172")
        assert "[CORRECTION:" in corrected

    def test_multiple_vspeeds(self) -> None:
        text = "Vs0 is 48 knots and Vne is 163 knots."
        _corrected, warnings = self.validator.validate_response(text, "C172")
        assert len(warnings) == 0  # Both correct


# ---------------------------------------------------------------------------
# Frequency validation
# ---------------------------------------------------------------------------


class TestFrequencyValidation:
    def setup_method(self) -> None:
        self.validator = ResponseValidator()

    def test_valid_comm_frequency(self) -> None:
        text = "Contact tower on 121.500."
        _corrected, warnings = self.validator.validate_response(text)
        assert len(warnings) == 0

    def test_valid_nav_frequency(self) -> None:
        text = "Tune NAV1 to 110.300."
        _corrected, warnings = self.validator.validate_response(text)
        assert len(warnings) == 0

    def test_invalid_frequency_flagged(self) -> None:
        text = "Contact on 500.000."
        _corrected, warnings = self.validator.validate_response(text)
        freq_warnings = [w for w in warnings if w.field == "frequency"]
        assert len(freq_warnings) == 1


# ---------------------------------------------------------------------------
# Telemetry sanity checks
# ---------------------------------------------------------------------------


class TestTelemetrySanity:
    def test_normal_state_passes(self) -> None:
        state = SimState(
            position=Position(latitude=40.0, longitude=-74.0, altitude_msl=5000, altitude_agl=4500),
            speeds=Speeds(indicated_airspeed=120, mach=0.18),
        )
        warnings = check_telemetry_sanity(state)
        assert len(warnings) == 0

    def test_impossible_altitude(self) -> None:
        state = SimState(
            position=Position(altitude_msl=-2000),
        )
        warnings = check_telemetry_sanity(state)
        fields = [w.field for w in warnings]
        assert "altitude_msl" in fields

    def test_impossible_agl(self) -> None:
        state = SimState(
            position=Position(altitude_agl=-200),
        )
        warnings = check_telemetry_sanity(state)
        fields = [w.field for w in warnings]
        assert "altitude_agl" in fields

    def test_impossible_mach(self) -> None:
        state = SimState(
            speeds=Speeds(mach=3.0, indicated_airspeed=200),
        )
        warnings = check_telemetry_sanity(state)
        fields = [w.field for w in warnings]
        assert "mach" in fields

    def test_negative_airspeed(self) -> None:
        state = SimState(
            speeds=Speeds(indicated_airspeed=-50),
        )
        warnings = check_telemetry_sanity(state)
        fields = [w.field for w in warnings]
        assert "indicated_airspeed" in fields

    def test_impossible_airspeed(self) -> None:
        state = SimState(
            speeds=Speeds(indicated_airspeed=900),
        )
        warnings = check_telemetry_sanity(state)
        fields = [w.field for w in warnings]
        assert "indicated_airspeed" in fields

    def test_impossible_latitude(self) -> None:
        state = SimState(
            position=Position(latitude=100.0, longitude=-74.0),
        )
        warnings = check_telemetry_sanity(state)
        fields = [w.field for w in warnings]
        assert "latitude" in fields

    def test_impossible_longitude(self) -> None:
        state = SimState(
            position=Position(latitude=40.0, longitude=-200.0),
        )
        warnings = check_telemetry_sanity(state)
        fields = [w.field for w in warnings]
        assert "longitude" in fields

    def test_negative_rpm(self) -> None:
        state = SimState(
            engines=Engines(
                engine_count=1,
                engines=[EngineData(rpm=-100)],
            ),
        )
        warnings = check_telemetry_sanity(state)
        fields = [w.field for w in warnings]
        assert "engine_0_rpm" in fields

    def test_impossible_oil_temp(self) -> None:
        state = SimState(
            engines=Engines(
                engine_count=1,
                engines=[EngineData(oil_temp=600)],
            ),
        )
        warnings = check_telemetry_sanity(state)
        fields = [w.field for w in warnings]
        assert "engine_0_oil_temp" in fields

    def test_zero_position_not_flagged(self) -> None:
        """Zero lat/lon is a valid position (Gulf of Guinea), don't flag it."""
        state = SimState(
            position=Position(latitude=0.0, longitude=0.0),
        )
        warnings = check_telemetry_sanity(state)
        assert len(warnings) == 0
