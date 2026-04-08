"""Tests for orchestrator.tools — tool function implementations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from orchestrator.command_verifier import CommandVerifier
from orchestrator.sim_client import (
    EngineData,
    Engines,
    Environment,
    FlightPhase,
    FuelState,
    Position,
    SimState,
    SurfaceState,
    TelemetryClient,
)
from orchestrator.tools import (
    DEFAULT_CHECKLISTS,
    _resolve_command,
    create_flight_plan,
    get_checklist,
    get_sim_state,
    lookup_airport,
    search_manual,
    set_aircraft_control,
)

# ---------------------------------------------------------------------------
# get_sim_state
# ---------------------------------------------------------------------------


class TestGetSimState:
    """Test formatted sim state retrieval."""

    @pytest.mark.asyncio
    async def test_returns_formatted_dict(self, sim_state_cruise: SimState) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=sim_state_cruise)

        result = await get_sim_state(mock_client)

        assert result["aircraft"] == "Cessna 172 Skyhawk"
        assert result["flight_phase"] == "CRUISE"
        assert result["on_ground"] is False
        assert result["position"]["altitude_msl"] == 6500
        assert result["position"]["altitude_agl"] == 6400
        assert result["speeds"]["indicated_airspeed"] == 120
        assert result["autopilot"]["master"] is True

    @pytest.mark.asyncio
    async def test_position_rounding(self) -> None:
        state = SimState(
            position=Position(
                latitude=28.429412345,
                longitude=-81.30912345,
                altitude_msl=6543.7,
                altitude_agl=6443.2,
            ),
        )
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=state)
        result = await get_sim_state(mock_client)
        assert result["position"]["lat"] == pytest.approx(28.429412, abs=1e-6)
        assert result["position"]["altitude_msl"] == 6544

    @pytest.mark.asyncio
    async def test_engine_params_formatting(self) -> None:
        state = SimState(
            engines=Engines(
                engine_count=1,
                engines=[
                    EngineData(rpm=2412.6, fuel_flow_gph=9.37, oil_temp=192.4, oil_pressure=61.8),
                ],
            ),
        )
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=state)
        result = await get_sim_state(mock_client)
        eng = result["engines"]["engines"][0]
        assert eng["rpm"] == 2413
        assert eng["fuel_flow_gph"] == pytest.approx(9.4, abs=0.1)
        assert eng["oil_temp"] == 192

    @pytest.mark.asyncio
    async def test_fuel_formatting(self) -> None:
        state = SimState(fuel=FuelState(total_gallons=42.37, total_weight_lbs=252.22))
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=state)
        result = await get_sim_state(mock_client)
        assert result["fuel"]["total_gallons"] == pytest.approx(42.4, abs=0.1)
        assert result["fuel"]["total_weight_lbs"] == pytest.approx(252.2, abs=0.1)

    @pytest.mark.asyncio
    async def test_environment_wind_string(self) -> None:
        state = SimState(
            environment=Environment(wind_direction=270.4, wind_speed_kts=12.3),
        )
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=state)
        result = await get_sim_state(mock_client)
        assert result["environment"]["wind"] == "270° at 12kt"

    @pytest.mark.asyncio
    async def test_surfaces_state(self, sim_state_approach: SimState) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=sim_state_approach)
        result = await get_sim_state(mock_client)
        assert result["surfaces"]["gear_handle"] is True
        assert result["surfaces"]["flaps_percent"] == 50
        assert result["surfaces"]["spoilers_percent"] == 0


# ---------------------------------------------------------------------------
# lookup_airport
# ---------------------------------------------------------------------------


class TestLookupAirport:
    """Test airport lookup with mocked HTTP responses."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_lookup_icao(self) -> None:
        respx.get("https://api.aviationapi.com/v1/airports", params={"apt": "KJFK"}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "KJFK": [
                        {
                            "facility_name": "JOHN F KENNEDY INTL",
                            "city": "NEW YORK",
                            "state_full": "NEW YORK",
                            "elevation": "13",
                            "latitude": "40.6413",
                            "longitude": "-73.7781",
                            "status_code": "O",
                        }
                    ],
                },
            )
        )
        result = await lookup_airport("KJFK")
        assert result["identifier"] == "KJFK"
        assert result["name"] == "JOHN F KENNEDY INTL"
        assert result["city"] == "NEW YORK"

    @pytest.mark.asyncio
    @respx.mock
    async def test_three_letter_code_gets_k_prefix(self) -> None:
        respx.get("https://api.aviationapi.com/v1/airports", params={"apt": "KJFK"}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "KJFK": [{"facility_name": "JOHN F KENNEDY INTL"}],
                },
            )
        )
        result = await lookup_airport("JFK")
        assert result["identifier"] == "KJFK"

    @pytest.mark.asyncio
    @respx.mock
    async def test_four_letter_code_starting_with_k_no_prefix(self) -> None:
        respx.get("https://api.aviationapi.com/v1/airports", params={"apt": "KLAX"}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "KLAX": [{"facility_name": "LOS ANGELES INTL"}],
                },
            )
        )
        result = await lookup_airport("KLAX")
        assert result["identifier"] == "KLAX"

    @pytest.mark.asyncio
    @respx.mock
    async def test_airport_not_found(self) -> None:
        respx.get("https://api.aviationapi.com/v1/airports", params={"apt": "KZZZ"}).mock(
            return_value=httpx.Response(200, json={"KZZZ": []})
        )
        result = await lookup_airport("KZZZ")
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_airport_identifier_missing_from_response(self) -> None:
        respx.get("https://api.aviationapi.com/v1/airports", params={"apt": "KXYZ"}).mock(
            return_value=httpx.Response(200, json={})
        )
        result = await lookup_airport("KXYZ")
        assert "error" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_http_error_returns_error_dict(self) -> None:
        respx.get("https://api.aviationapi.com/v1/airports", params={"apt": "KJFK"}).mock(
            return_value=httpx.Response(500)
        )
        result = await lookup_airport("KJFK")
        assert "error" in result
        assert "Lookup failed" in result["error"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_whitespace_and_case_normalization(self) -> None:
        respx.get("https://api.aviationapi.com/v1/airports", params={"apt": "KJFK"}).mock(
            return_value=httpx.Response(200, json={"KJFK": [{"facility_name": "JFK"}]})
        )
        result = await lookup_airport("  kjfk  ")
        assert result["identifier"] == "KJFK"

    @pytest.mark.asyncio
    @respx.mock
    async def test_dict_response_instead_of_list(self) -> None:
        """API sometimes returns a dict instead of a list for the airport."""
        respx.get("https://api.aviationapi.com/v1/airports", params={"apt": "KJFK"}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "KJFK": {"facility_name": "JOHN F KENNEDY INTL", "city": "NEW YORK"},
                },
            )
        )
        result = await lookup_airport("KJFK")
        assert result["name"] == "JOHN F KENNEDY INTL"


# ---------------------------------------------------------------------------
# search_manual
# ---------------------------------------------------------------------------


class TestSearchManual:
    """Test manual search with mocked context store."""

    @pytest.mark.asyncio
    async def test_returns_formatted_results(self) -> None:
        mock_store = MagicMock()
        mock_store.query = AsyncMock(
            return_value=[
                {
                    "content": "V-speeds for C172: Vr=55, Vx=62, Vy=74",
                    "metadata": {"source": "poh.pdf"},
                    "distance": 0.1,
                },
                {
                    "content": "Normal climb: 75-85 KIAS",
                    "metadata": {"source": "poh.pdf"},
                    "distance": 0.2,
                },
            ]
        )

        result = await search_manual("V-speeds", mock_store)
        assert len(result) == 2
        assert result[0]["content"] == "V-speeds for C172: Vr=55, Vx=62, Vy=74"
        assert result[0]["source"] == "poh.pdf"

    @pytest.mark.asyncio
    async def test_passes_aircraft_type_filter(self) -> None:
        mock_store = MagicMock()
        mock_store.query = AsyncMock(return_value=[])

        await search_manual("V-speeds", mock_store, aircraft_type="Cessna 172")
        mock_store.query.assert_awaited_once()
        call_kwargs = mock_store.query.call_args[1]
        assert call_kwargs["filters"] == {"aircraft_type": "Cessna 172"}

    @pytest.mark.asyncio
    async def test_no_aircraft_type_passes_no_filter(self) -> None:
        mock_store = MagicMock()
        mock_store.query = AsyncMock(return_value=[])

        await search_manual("emergency procedures", mock_store, aircraft_type="")
        call_kwargs = mock_store.query.call_args[1]
        assert call_kwargs["filters"] is None

    @pytest.mark.asyncio
    async def test_custom_n_results(self) -> None:
        mock_store = MagicMock()
        mock_store.query = AsyncMock(return_value=[])

        await search_manual("stall", mock_store, n_results=3)
        call_kwargs = mock_store.query.call_args[1]
        assert call_kwargs["n_results"] == 3

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        mock_store = MagicMock()
        mock_store.query = AsyncMock(return_value=[])

        result = await search_manual("nonexistent topic", mock_store)
        assert result == []


# ---------------------------------------------------------------------------
# get_checklist
# ---------------------------------------------------------------------------


class TestGetChecklist:
    """Test checklist retrieval and phase filtering."""

    @pytest.mark.asyncio
    async def test_default_checklist_preflight(self) -> None:
        mock_store = MagicMock()
        mock_store.query = AsyncMock(return_value=[])

        result = await get_checklist("PREFLIGHT", mock_store)
        assert result["phase"] == "PREFLIGHT"
        assert result["source"] == "default"
        assert "items" in result
        assert len(result["items"]) > 0

    @pytest.mark.asyncio
    async def test_default_checklist_all_phases(self) -> None:
        mock_store = MagicMock()
        mock_store.query = AsyncMock(return_value=[])

        for phase in FlightPhase:
            result = await get_checklist(phase.value, mock_store)
            assert result["phase"] == phase.value

    @pytest.mark.asyncio
    async def test_case_insensitive_phase(self) -> None:
        mock_store = MagicMock()
        mock_store.query = AsyncMock(return_value=[])

        result = await get_checklist("preflight", mock_store)
        assert result["phase"] == "PREFLIGHT"

    @pytest.mark.asyncio
    async def test_invalid_phase_returns_error(self) -> None:
        mock_store = MagicMock()
        result = await get_checklist("HOVERING", mock_store)
        assert "error" in result
        assert "Unknown flight phase" in result["error"]

    @pytest.mark.asyncio
    async def test_aircraft_specific_checklist_from_store(self) -> None:
        mock_store = MagicMock()
        mock_store.query = AsyncMock(
            return_value=[
                {
                    "content": "C172 Preflight: 1. Check fuel...",
                    "metadata": {"source": "c172_checklist.pdf"},
                },
            ]
        )

        result = await get_checklist("PREFLIGHT", mock_store, aircraft_type="Cessna 172")
        assert result["source"] == "aircraft_manual"
        assert result["aircraft"] == "Cessna 172"
        assert "C172 Preflight" in result["checklist"]

    @pytest.mark.asyncio
    async def test_fallback_to_default_when_store_empty(self) -> None:
        mock_store = MagicMock()
        mock_store.query = AsyncMock(return_value=[])

        result = await get_checklist("TAKEOFF", mock_store, aircraft_type="Cessna 172")
        assert result["source"] == "default"
        assert result["aircraft"] == "Cessna 172"

    @pytest.mark.asyncio
    async def test_accepts_flight_phase_enum_directly(self) -> None:
        mock_store = MagicMock()
        mock_store.query = AsyncMock(return_value=[])

        result = await get_checklist(FlightPhase.CRUISE, mock_store)
        assert result["phase"] == "CRUISE"

    @pytest.mark.asyncio
    async def test_generic_aircraft_when_none_specified(self) -> None:
        mock_store = MagicMock()
        mock_store.query = AsyncMock(return_value=[])

        result = await get_checklist("LANDED", mock_store, aircraft_type="")
        assert result["aircraft"] == "generic"

    def test_default_checklists_cover_all_phases(self) -> None:
        for phase in FlightPhase:
            assert phase in DEFAULT_CHECKLISTS, f"Missing default checklist for {phase.value}"


# ---------------------------------------------------------------------------
# create_flight_plan
# ---------------------------------------------------------------------------


class TestCreateFlightPlan:
    """Test flight plan creation with mocked airport lookups."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_basic_flight_plan(self) -> None:
        respx.get("https://api.aviationapi.com/v1/airports", params={"apt": "KJFK"}).mock(
            return_value=httpx.Response(200, json={"KJFK": [{"facility_name": "JFK INTL"}]})
        )
        respx.get("https://api.aviationapi.com/v1/airports", params={"apt": "KLAX"}).mock(
            return_value=httpx.Response(200, json={"KLAX": [{"facility_name": "LAX INTL"}]})
        )

        result = await create_flight_plan("KJFK", "KLAX")
        assert result["departure"]["name"] == "JFK INTL"
        assert result["destination"]["name"] == "LAX INTL"
        assert result["cruise_altitude"] == 5000
        assert result["status"] == "draft"
        assert result["waypoints"] == ["KJFK", "KLAX"]
        assert result["route"] == "KJFK KLAX"

    @pytest.mark.asyncio
    @respx.mock
    async def test_flight_plan_with_route(self) -> None:
        respx.get("https://api.aviationapi.com/v1/airports").mock(
            return_value=httpx.Response(200, json={})
        )

        result = await create_flight_plan("KJFK", "KLAX", altitude=35000, route="MERIT J80 BOS")
        assert result["cruise_altitude"] == 35000
        assert result["waypoints"] == ["KJFK", "MERIT", "J80", "BOS", "KLAX"]
        assert result["route"] == "KJFK MERIT J80 BOS KLAX"

    @pytest.mark.asyncio
    @respx.mock
    async def test_flight_plan_normalizes_identifiers(self) -> None:
        respx.get("https://api.aviationapi.com/v1/airports").mock(
            return_value=httpx.Response(200, json={})
        )

        result = await create_flight_plan("kjfk", "klax")
        assert result["waypoints"][0] == "KJFK"
        assert result["waypoints"][-1] == "KLAX"

    @pytest.mark.asyncio
    @respx.mock
    async def test_flight_plan_includes_notes(self) -> None:
        respx.get("https://api.aviationapi.com/v1/airports").mock(
            return_value=httpx.Response(200, json={})
        )

        result = await create_flight_plan("KJFK", "KLAX")
        assert "draft" in result["notes"].lower() or "verify" in result["notes"].lower()


# ---------------------------------------------------------------------------
# _resolve_command
# ---------------------------------------------------------------------------


class TestResolveCommand:
    """Test the command resolution from human-friendly names to SimConnect events."""

    def test_flaps_up(self) -> None:
        assert _resolve_command("flaps", "up", None) == ("FLAPS_SET", 0)

    def test_flaps_1(self) -> None:
        assert _resolve_command("flaps", "1", None) == ("FLAPS_1", 0)

    def test_flaps_2(self) -> None:
        assert _resolve_command("flaps", "2", None) == ("FLAPS_2", 0)

    def test_flaps_3(self) -> None:
        assert _resolve_command("flaps", "3", None) == ("FLAPS_3", 0)

    def test_flaps_full(self) -> None:
        assert _resolve_command("flaps", "full", None) == ("FLAPS_SET", 16383)

    def test_flaps_set_percentage(self) -> None:
        event, val = _resolve_command("flaps", "set", 50)
        assert event == "FLAPS_SET"
        assert val == int(50 * 16383 / 100)

    def test_flaps_set_notch(self) -> None:
        event, val = _resolve_command("flaps", "set", 2)
        assert event == "FLAPS_SET"
        assert val == int(2 * 16383 / 4)

    def test_gear_up(self) -> None:
        assert _resolve_command("gear", "up", None) == ("GEAR_UP", 0)

    def test_gear_down(self) -> None:
        assert _resolve_command("gear", "down", None) == ("GEAR_DOWN", 0)

    def test_autopilot_toggle(self) -> None:
        assert _resolve_command("autopilot", "toggle", None) == ("AP_MASTER", 0)

    def test_autopilot_heading(self) -> None:
        assert _resolve_command("autopilot", "heading", 270) == ("HEADING_BUG_SET", 270)

    def test_autopilot_altitude(self) -> None:
        assert _resolve_command("autopilot", "altitude", 5000) == ("AP_ALT_VAR_SET_ENGLISH", 5000)

    def test_autopilot_vs(self) -> None:
        assert _resolve_command("autopilot", "vertical_speed", -500) == ("AP_VS_VAR_SET_ENGLISH", -500)

    def test_throttle_set(self) -> None:
        event, val = _resolve_command("throttle", "set", 75)
        assert event == "THROTTLE_SET"
        assert val == int(75 * 16383 / 100)

    def test_radio_com1(self) -> None:
        assert _resolve_command("radio", "com1", 121.5) == ("COM_RADIO_SET_HZ", 121500000)

    def test_radio_nav1(self) -> None:
        assert _resolve_command("radio", "nav1", 110.5) == ("NAV1_RADIO_SET_HZ", 110500000)

    def test_barometer_set(self) -> None:
        assert _resolve_command("barometer", "set", 29.92) == ("KOHLSMAN_SET", 2992)

    def test_unknown_system(self) -> None:
        assert _resolve_command("weapons", "fire", None) == (None, 0)

    def test_unknown_action(self) -> None:
        assert _resolve_command("flaps", "explode", None) == (None, 0)

    # --- Phase 2: Engine controls ---

    @pytest.mark.parametrize(
        ("system", "action", "value", "expected_event", "expected_value"),
        [
            ("magnetos", "off", None, "MAGNETO_SET", 0),
            ("magnetos", "both", None, "MAGNETO_SET", 3),
            ("magnetos", "start", None, "MAGNETO_SET", 4),
            ("carb_heat", "toggle", None, "ANTI_ICE_CARB_HEAT_TOGGLE", 0),
            ("fuel_pump", "toggle", None, "FUEL_PUMP_TOGGLE", 0),
            ("starter", "engage", None, "TOGGLE_STARTER1", 0),
            ("primer", "prime", None, "TOGGLE_PRIMER", 0),
        ],
        ids=[
            "magnetos-off",
            "magnetos-both",
            "magnetos-start",
            "carb_heat-toggle",
            "fuel_pump-toggle",
            "starter-engage",
            "primer-prime",
        ],
    )
    def test_engine_controls(
        self,
        system: str,
        action: str,
        value: float | None,
        expected_event: str,
        expected_value: int,
    ) -> None:
        assert _resolve_command(system, action, value) == (expected_event, expected_value)

    # --- Phase 2: Fuel controls ---

    @pytest.mark.parametrize(
        ("system", "action", "value", "expected_event", "expected_value"),
        [
            ("fuel_selector", "off", None, "FUEL_SELECTOR_OFF", 0),
            ("fuel_selector", "both", None, "FUEL_SELECTOR_ALL", 0),
            ("fuel_selector", "left", None, "FUEL_SELECTOR_LEFT", 0),
            ("crossfeed", "open", None, "CROSS_FEED_OPEN", 0),
            ("crossfeed", "toggle", None, "CROSS_FEED_TOGGLE", 0),
        ],
        ids=[
            "fuel_selector-off",
            "fuel_selector-both",
            "fuel_selector-left",
            "crossfeed-open",
            "crossfeed-toggle",
        ],
    )
    def test_fuel_controls(
        self,
        system: str,
        action: str,
        value: float | None,
        expected_event: str,
        expected_value: int,
    ) -> None:
        assert _resolve_command(system, action, value) == (expected_event, expected_value)

    # --- Phase 2: Lights ---

    @pytest.mark.parametrize(
        ("system", "action", "value", "expected_event", "expected_value"),
        [
            ("lights", "landing", None, "LANDING_LIGHTS_TOGGLE", 0),
            ("lights", "taxi", None, "TOGGLE_TAXI_LIGHTS", 0),
            ("lights", "nav", None, "TOGGLE_NAV_LIGHTS", 0),
            ("lights", "beacon", None, "TOGGLE_BEACON_LIGHTS", 0),
            ("lights", "strobe", None, "STROBES_TOGGLE", 0),
        ],
        ids=[
            "lights-landing",
            "lights-taxi",
            "lights-nav",
            "lights-beacon",
            "lights-strobe",
        ],
    )
    def test_lights(
        self,
        system: str,
        action: str,
        value: float | None,
        expected_event: str,
        expected_value: int,
    ) -> None:
        assert _resolve_command(system, action, value) == (expected_event, expected_value)

    # --- Phase 2: Trim expansion ---

    @pytest.mark.parametrize(
        ("system", "action", "value", "expected_event", "expected_value"),
        [
            ("trim", "up", None, "ELEV_TRIM_UP", 0),
            ("trim", "down", None, "ELEV_TRIM_DN", 0),
            ("trim", "rudder_left", None, "RUDDER_TRIM_LEFT", 0),
            ("trim", "rudder_right", None, "RUDDER_TRIM_RIGHT", 0),
        ],
        ids=[
            "trim-up",
            "trim-down",
            "trim-rudder_left",
            "trim-rudder_right",
        ],
    )
    def test_trim_expansion(
        self,
        system: str,
        action: str,
        value: float | None,
        expected_event: str,
        expected_value: int,
    ) -> None:
        assert _resolve_command(system, action, value) == (expected_event, expected_value)

    # --- Phase 2: Deice ---

    @pytest.mark.parametrize(
        ("system", "action", "value", "expected_event", "expected_value"),
        [
            ("deice", "pitot", None, "PITOT_HEAT_TOGGLE", 0),
            ("deice", "structural", None, "TOGGLE_STRUCTURAL_DEICE", 0),
            ("deice", "windshield", None, "WINDSHIELD_DEICE_TOGGLE", 0),
        ],
        ids=[
            "deice-pitot",
            "deice-structural",
            "deice-windshield",
        ],
    )
    def test_deice(
        self,
        system: str,
        action: str,
        value: float | None,
        expected_event: str,
        expected_value: int,
    ) -> None:
        assert _resolve_command(system, action, value) == (expected_event, expected_value)

    # --- Phase 2: Unknown commands ---

    def test_unknown_system_returns_none(self) -> None:
        assert _resolve_command("unknown_system", "action", None) == (None, 0)


# ---------------------------------------------------------------------------
# set_aircraft_control
# ---------------------------------------------------------------------------


class TestSetAircraftControl:
    """Test the high-level aircraft control command function."""

    @pytest.mark.asyncio
    async def test_successful_command(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=SimState())
        mock_client.send_command = AsyncMock(return_value={"success": True, "message": ""})

        result = await set_aircraft_control(mock_client, "flaps", "2")

        mock_client.send_command.assert_awaited_once_with("FLAPS_2", 0)
        assert result["command"] == "FLAPS_2"
        assert result["sim_value"] == 0
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_unknown_control_returns_error(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)

        result = await set_aircraft_control(mock_client, "invalid", "boom")

        assert "error" in result
        mock_client.send_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_critical_command_has_safety_note(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=SimState())
        mock_client.send_command = AsyncMock(return_value={"success": True, "message": ""})

        result = await set_aircraft_control(mock_client, "gear", "down")

        assert "safety_note" in result
        assert result["command"] == "GEAR_DOWN"

    @pytest.mark.asyncio
    async def test_non_critical_command_no_safety_note(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=SimState())
        mock_client.send_command = AsyncMock(return_value={"success": True, "message": ""})

        result = await set_aircraft_control(mock_client, "flaps", "2")

        assert "safety_note" not in result

    @pytest.mark.asyncio
    async def test_with_verifier_adds_verification(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.send_command = AsyncMock(return_value={"success": True, "message": ""})
        # get_state called twice: once before command (safety + state capture),
        # once during verification polling
        mock_client.get_state = AsyncMock(
            side_effect=[
                SimState(surfaces=SurfaceState(gear_handle=False)),  # before
                SimState(surfaces=SurfaceState(gear_handle=True)),  # after (verification)
            ]
        )

        verifier = CommandVerifier(mock_client, timeout=1.0, poll_interval=0.1)
        result = await set_aircraft_control(
            mock_client, "gear", "down", verifier=verifier
        )

        assert result["success"] is True
        assert "verification" in result
        assert result["verification"]["verified"] is True
        assert "verification_warning" not in result

    @pytest.mark.asyncio
    async def test_with_verifier_failed_verification(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.send_command = AsyncMock(return_value={"success": True, "message": ""})
        # Gear never extends
        mock_client.get_state = AsyncMock(
            return_value=SimState(surfaces=SurfaceState(gear_handle=False))
        )

        verifier = CommandVerifier(mock_client, timeout=0.3, poll_interval=0.1)
        result = await set_aircraft_control(
            mock_client, "gear", "down", verifier=verifier
        )

        assert "verification" in result
        assert result["verification"]["verified"] is False
        assert "verification_warning" in result

    @pytest.mark.asyncio
    async def test_without_verifier_no_verification(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.get_state = AsyncMock(return_value=SimState())
        mock_client.send_command = AsyncMock(return_value={"success": True, "message": ""})

        result = await set_aircraft_control(mock_client, "gear", "down")

        assert "verification" not in result

    @pytest.mark.asyncio
    async def test_verifier_skipped_on_failed_command(self) -> None:
        mock_client = MagicMock(spec=TelemetryClient)
        mock_client.send_command = AsyncMock(
            return_value={"success": False, "message": "SimConnect error"}
        )
        mock_client.get_state = AsyncMock(
            return_value=SimState(surfaces=SurfaceState(gear_handle=False))
        )

        verifier = CommandVerifier(mock_client, timeout=1.0, poll_interval=0.1)
        result = await set_aircraft_control(
            mock_client, "gear", "down", verifier=verifier
        )

        assert "verification" not in result
