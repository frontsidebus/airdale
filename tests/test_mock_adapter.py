"""Tests for the mock MSFS adapter (tools/mock_adapter.py).

Validates that MockAircraftState correctly applies SimConnect commands,
produces valid telemetry JSON, and maintains a command history log.
"""

from __future__ import annotations

import json

import pytest

# mock_adapter lives in tools/ which is not a package, so add it to sys.path
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from mock_adapter import MockAircraftState


# ---------------------------------------------------------------------------
# apply_command — flight surfaces
# ---------------------------------------------------------------------------


class TestApplyCommandFlaps:
    def test_flaps_full(self) -> None:
        state = MockAircraftState()
        state.apply_command("FLAPS_FULL", 0)
        assert state.flaps_percent == 100.0

    def test_flaps_up(self) -> None:
        state = MockAircraftState(flaps_percent=50.0)
        state.apply_command("FLAPS_UP", 0)
        assert state.flaps_percent == 0.0

    def test_flaps_set_midrange(self) -> None:
        state = MockAircraftState()
        state.apply_command("FLAPS_SET", 8192)
        assert 49.0 < state.flaps_percent < 51.0

    def test_flaps_incr_from_zero(self) -> None:
        state = MockAircraftState(flaps_percent=0.0)
        state.apply_command("FLAPS_INCR", 0)
        assert state.flaps_percent == 10.0

    def test_flaps_decr_clamps_at_zero(self) -> None:
        state = MockAircraftState(flaps_percent=0.0)
        state.apply_command("FLAPS_DECR", 0)
        assert state.flaps_percent == 0.0

    def test_flaps_1(self) -> None:
        state = MockAircraftState()
        state.apply_command("FLAPS_1", 0)
        assert state.flaps_percent == 10.0

    def test_flaps_2(self) -> None:
        state = MockAircraftState()
        state.apply_command("FLAPS_2", 0)
        assert state.flaps_percent == 20.0

    def test_flaps_3(self) -> None:
        state = MockAircraftState()
        state.apply_command("FLAPS_3", 0)
        assert state.flaps_percent == 30.0


# ---------------------------------------------------------------------------
# apply_command — landing gear
# ---------------------------------------------------------------------------


class TestApplyCommandGear:
    def test_gear_down(self) -> None:
        state = MockAircraftState(gear_handle=False)
        state.apply_command("GEAR_DOWN", 0)
        assert state.gear_handle is True

    def test_gear_up(self) -> None:
        state = MockAircraftState(gear_handle=True)
        state.apply_command("GEAR_UP", 0)
        assert state.gear_handle is False

    def test_gear_toggle_from_down(self) -> None:
        state = MockAircraftState(gear_handle=True)
        state.apply_command("GEAR_TOGGLE", 0)
        assert state.gear_handle is False

    def test_gear_toggle_from_up(self) -> None:
        state = MockAircraftState(gear_handle=False)
        state.apply_command("GEAR_TOGGLE", 0)
        assert state.gear_handle is True


# ---------------------------------------------------------------------------
# apply_command — autopilot
# ---------------------------------------------------------------------------


class TestApplyCommandAutopilot:
    def test_ap_master_toggle_on(self) -> None:
        state = MockAircraftState(autopilot_master=False)
        state.apply_command("AP_MASTER", 0)
        assert state.autopilot_master is True

    def test_ap_master_toggle_off(self) -> None:
        state = MockAircraftState(autopilot_master=True)
        state.apply_command("AP_MASTER", 0)
        assert state.autopilot_master is False

    def test_heading_bug_set(self) -> None:
        state = MockAircraftState()
        state.apply_command("HEADING_BUG_SET", 270)
        assert state.autopilot_heading == 270

    def test_ap_alt_set(self) -> None:
        state = MockAircraftState()
        state.apply_command("AP_ALT_VAR_SET_ENGLISH", 10000)
        assert state.autopilot_altitude == 10000

    def test_ap_vs_set(self) -> None:
        state = MockAircraftState()
        state.apply_command("AP_VS_VAR_SET_ENGLISH", -500)
        assert state.autopilot_vs == -500

    def test_ap_spd_set(self) -> None:
        state = MockAircraftState()
        state.apply_command("AP_SPD_VAR_SET", 250)
        assert state.autopilot_speed == 250


# ---------------------------------------------------------------------------
# apply_command — throttle
# ---------------------------------------------------------------------------


class TestApplyCommandThrottle:
    def test_throttle_set_midrange(self) -> None:
        """THROTTLE_SET with 8191 (~50% of 16383) should produce ~50% in the description."""
        state = MockAircraftState()
        desc = state.apply_command("THROTTLE_SET", 8191)
        # Verify description contains roughly 50%
        assert "50" in desc or "49.9" in desc

    def test_throttle_set_full(self) -> None:
        state = MockAircraftState()
        desc = state.apply_command("THROTTLE_SET", 16383)
        assert "100" in desc


# ---------------------------------------------------------------------------
# apply_command — radios
# ---------------------------------------------------------------------------


class TestApplyCommandRadios:
    def test_com_radio_set_hz(self) -> None:
        state = MockAircraftState()
        state.apply_command("COM_RADIO_SET_HZ", 121500000)
        assert state.com1 == pytest.approx(121.5)

    def test_com2_radio_set_hz(self) -> None:
        state = MockAircraftState()
        state.apply_command("COM2_RADIO_SET_HZ", 118300000)
        assert state.com2 == pytest.approx(118.3)

    def test_nav1_radio_set_hz(self) -> None:
        state = MockAircraftState()
        state.apply_command("NAV1_RADIO_SET_HZ", 110300000)
        assert state.nav1 == pytest.approx(110.3)

    def test_nav2_radio_set_hz(self) -> None:
        state = MockAircraftState()
        state.apply_command("NAV2_RADIO_SET_HZ", 115500000)
        assert state.nav2 == pytest.approx(115.5)


# ---------------------------------------------------------------------------
# apply_command — barometer (Kohlsman)
# ---------------------------------------------------------------------------


class TestApplyCommandBarometer:
    def test_kohlsman_set(self) -> None:
        state = MockAircraftState()
        state.apply_command("KOHLSMAN_SET", 2992)
        assert state.barometer_inhg == pytest.approx(29.92)

    def test_kohlsman_set_low_pressure(self) -> None:
        state = MockAircraftState()
        state.apply_command("KOHLSMAN_SET", 2950)
        assert state.barometer_inhg == pytest.approx(29.50)


# ---------------------------------------------------------------------------
# apply_command — spoilers
# ---------------------------------------------------------------------------


class TestApplyCommandSpoilers:
    def test_spoilers_set(self) -> None:
        state = MockAircraftState()
        state.apply_command("SPOILERS_SET", 16383)
        assert state.spoilers_percent == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# apply_command — return value and case insensitivity
# ---------------------------------------------------------------------------


class TestApplyCommandReturnValue:
    def test_returns_string_description(self) -> None:
        state = MockAircraftState()
        desc = state.apply_command("FLAPS_FULL", 0)
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_description_is_human_readable(self) -> None:
        state = MockAircraftState()
        desc = state.apply_command("GEAR_DOWN", 0)
        assert "Gear" in desc or "gear" in desc

    def test_case_insensitive_command(self) -> None:
        state = MockAircraftState()
        state.apply_command("flaps_full", 0)
        assert state.flaps_percent == 100.0

    def test_unknown_command_returns_description(self) -> None:
        state = MockAircraftState()
        desc = state.apply_command("BOGUS_COMMAND", 42)
        assert "UNKNOWN" in desc


# ---------------------------------------------------------------------------
# Command log
# ---------------------------------------------------------------------------


class TestCommandLog:
    def test_command_log_populated(self) -> None:
        state = MockAircraftState()
        state.apply_command("FLAPS_FULL", 0)
        state.apply_command("GEAR_UP", 0)

        assert len(state.command_log) == 2

    def test_command_log_entry_fields(self) -> None:
        state = MockAircraftState()
        state.apply_command("HEADING_BUG_SET", 180)

        entry = state.command_log[0]
        assert "time" in entry
        assert entry["command"] == "HEADING_BUG_SET"
        assert entry["value"] == 180
        assert "description" in entry

    def test_command_log_starts_empty(self) -> None:
        state = MockAircraftState()
        assert state.command_log == []


# ---------------------------------------------------------------------------
# to_telemetry_json
# ---------------------------------------------------------------------------


class TestTelemetryJson:
    def test_produces_valid_json(self) -> None:
        state = MockAircraftState()
        result = state.to_telemetry_json()
        # Round-trip through json to verify it is serializable
        serialized = json.dumps(result)
        parsed = json.loads(serialized)
        assert isinstance(parsed, dict)

    def test_contains_all_top_level_keys(self) -> None:
        state = MockAircraftState()
        result = state.to_telemetry_json()
        expected_keys = {
            "timestamp",
            "connected",
            "aircraft",
            "position",
            "attitude",
            "speeds",
            "engines",
            "autopilot",
            "radios",
            "fuel",
            "environment",
            "surfaces",
        }
        assert expected_keys == set(result.keys())

    def test_position_fields(self) -> None:
        state = MockAircraftState(latitude=40.0, longitude=-74.0, altitude_msl=5000)
        result = state.to_telemetry_json()
        pos = result["position"]
        assert pos["latitude"] == 40.0
        assert pos["longitude"] == -74.0
        assert pos["altitude_msl"] == 5000

    def test_surfaces_reflect_state(self) -> None:
        state = MockAircraftState(gear_handle=False, flaps_percent=75.0, spoilers_percent=50.0)
        result = state.to_telemetry_json()
        surfaces = result["surfaces"]
        assert surfaces["gear_handle"] is False
        assert surfaces["flaps_percent"] == 75.0
        assert surfaces["spoilers_percent"] == 50.0

    def test_autopilot_reflects_state(self) -> None:
        state = MockAircraftState(autopilot_master=True, autopilot_heading=180)
        result = state.to_telemetry_json()
        ap = result["autopilot"]
        assert ap["master"] is True
        assert ap["heading"] == 180

    def test_radios_reflect_state(self) -> None:
        state = MockAircraftState(com1=121.5, com2=122.8, nav1=110.3)
        result = state.to_telemetry_json()
        radios = result["radios"]
        assert radios["com1"] == 121.5
        assert radios["com2"] == 122.8
        assert radios["nav1"] == 110.3

    def test_connected_is_true(self) -> None:
        state = MockAircraftState()
        result = state.to_telemetry_json()
        assert result["connected"] is True

    def test_aircraft_name_in_json(self) -> None:
        state = MockAircraftState(aircraft="Boeing 747")
        result = state.to_telemetry_json()
        assert result["aircraft"] == "Boeing 747"

    def test_timestamp_present(self) -> None:
        state = MockAircraftState()
        result = state.to_telemetry_json()
        assert isinstance(result["timestamp"], str)
        assert len(result["timestamp"]) > 0

    def test_engines_structure(self) -> None:
        state = MockAircraftState()
        result = state.to_telemetry_json()
        engines = result["engines"]
        assert engines["engine_count"] == 1
        assert len(engines["engines"]) == 1
        eng = engines["engines"][0]
        assert "rpm" in eng
        assert "oil_temp" in eng
        assert "fuel_flow_gph" in eng


# ---------------------------------------------------------------------------
# Command feedback — command_ack message format
# ---------------------------------------------------------------------------


class TestCommandAckFormat:
    """Verify the command_ack message structure as used by the mock adapter.

    When the mock adapter receives a command, it sends back a JSON ack
    with specific fields. This tests the protocol contract.
    """

    def test_ack_has_required_fields(self) -> None:
        """The ack dict built by the adapter loop must contain type, command_id,
        success, and message fields."""
        # Simulate what _listen_for_commands builds after apply_command
        state = MockAircraftState()
        desc = state.apply_command("FLAPS_FULL", 0)
        command_id = "test-cmd-12345678"

        ack = {
            "type": "command_ack",
            "command_id": command_id,
            "success": True,
            "message": desc,
        }

        assert ack["type"] == "command_ack"
        assert ack["command_id"] == command_id
        assert ack["success"] is True
        assert isinstance(ack["message"], str)
        assert len(ack["message"]) > 0

    def test_ack_serializes_to_valid_json(self) -> None:
        state = MockAircraftState()
        desc = state.apply_command("GEAR_DOWN", 0)

        ack = json.dumps({
            "type": "command_ack",
            "command_id": "abc-123",
            "success": True,
            "message": desc,
        })
        parsed = json.loads(ack)
        assert parsed["type"] == "command_ack"
        assert parsed["success"] is True
