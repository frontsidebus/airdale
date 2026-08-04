"""Tests for orchestrator.tools — tool function implementations."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from orchestrator.authority import AuthorityLevel, AuthorityState
from orchestrator.command_history import CommandHistory
from orchestrator.command_safety import CommandSafetyCheck, SafetyResult
from orchestrator.command_verifier import CommandVerifier
from orchestrator.sim_client import (
    AutopilotState,
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
    _was_transmitted,
    create_flight_plan,
    get_checklist,
    get_sim_state,
    lookup_airport,
    search_manual,
    set_aircraft_control,
    undo_last_command,
)

from orchestrator import tools as tools_module


def _control_client(send_result: dict[str, object] | None = None) -> MagicMock:
    """Mocked telemetry client wired the way ``set_aircraft_control`` expects."""
    mock_client = MagicMock(spec=TelemetryClient)
    mock_client.get_state = AsyncMock(return_value=SimState())
    mock_client.send_command = AsyncMock(
        return_value=send_result if send_result is not None else {"success": True, "message": ""}
    )
    return mock_client


class _StubSafetyCheck(CommandSafetyCheck):
    """Safety checker returning a fixed verdict.

    Injected through the existing ``safety_check=`` parameter so the authority
    matrix drives the gate from a known severity rather than depending on which
    of ``DEFAULT_RULES`` happens to fire for the chosen command.
    """

    def __init__(self, severity: str = "", reason: str = "") -> None:
        super().__init__(rules=[])
        self._severity = severity
        self._reason = reason

    def check(
        self,
        command: str,
        value: int,
        sim_state: SimState,
        aircraft_type: str = "",
    ) -> SafetyResult:
        return SafetyResult(
            safe=self._severity != "blocked",
            command=command,
            reason=self._reason,
            severity=self._severity,
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
        result = _resolve_command("autopilot", "vertical_speed", -500)
        assert result == ("AP_VS_VAR_SET_ENGLISH", -500)

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
# CMD-08 -- carb_heat / fuel_pump absolute on/off refusal
# ---------------------------------------------------------------------------


class TestUnconfirmablePositionRefusal:
    """`carb_heat` and `fuel_pump` must never blind-toggle an absolute on/off.

    Both map "on", "off" and "toggle" to the same toggle event, so today "carb heat
    off" turns it *on* whenever it was already off. No telemetry carries either
    position, so state-aware resolution is not implementable (D-02) -- the command
    is refused instead.
    """

    @pytest.mark.parametrize(
        ("system", "action"),
        [
            ("carb_heat", "off"),
            ("carb_heat", "on"),
            ("fuel_pump", "on"),
            ("fuel_pump", "off"),
        ],
        ids=["carb_heat-off", "carb_heat-on", "fuel_pump-on", "fuel_pump-off"],
    )
    @pytest.mark.asyncio
    async def test_absolute_on_off_is_refused(self, system: str, action: str) -> None:
        mock_client = _control_client()

        result = await set_aircraft_control(mock_client, system, action)

        mock_client.send_command.assert_not_called()
        assert result["unresolvable"] is True
        assert result["system"] == system
        assert result["action"] == action
        assert "current position" in result["error"]
        assert "toggle" in result["error"]

    @pytest.mark.parametrize(
        ("system", "expected_event"),
        [
            ("carb_heat", "ANTI_ICE_CARB_HEAT_TOGGLE"),
            ("fuel_pump", "FUEL_PUMP_TOGGLE"),
        ],
        ids=["carb_heat-toggle", "fuel_pump-toggle"],
    )
    @pytest.mark.asyncio
    async def test_toggle_still_executes(self, system: str, expected_event: str) -> None:
        mock_client = _control_client()

        await set_aircraft_control(mock_client, system, "toggle")

        mock_client.send_command.assert_awaited_once_with(expected_event, 0)

    def test_resolver_is_unchanged(self) -> None:
        """The refusal lives in ``set_aircraft_control``; the resolver stays a pure lookup."""
        assert _resolve_command("carb_heat", "off", None) == ("ANTI_ICE_CARB_HEAT_TOGGLE", 0)
        assert _resolve_command("fuel_pump", "on", None) == ("FUEL_PUMP_TOGGLE", 0)


# ---------------------------------------------------------------------------
# CR-04 / CMD-08 -- parking_brake, the blind toggle that was actually reachable
# ---------------------------------------------------------------------------

_CR04_REGRESSION = (
    "parking_brake resolved EVERY action -- 'on', 'off', 'release', 'toggle' -- to the "
    "same PARKING_BRAKES toggle event. Unlike carb_heat and fuel_pump it is in the "
    "set_aircraft_control enum, in CRITICAL_COMMANDS and registered in the adapter's "
    "CommandMap, so this was the one blind toggle a pilot could actually reach: "
    "'parking brake off' on landing rollout SET the brake (CR-04)."
)


class TestParkingBrakeRefusal:
    """`parking_brake` accepts an explicit toggle and nothing else.

    No telemetry anywhere in the chain reports parking-brake position -- not the
    SimConnect data definition, the adapter model, the universal schema,
    ``SurfaceState`` or the mock adapter -- so an absolute "on"/"off"/"release"
    cannot be resolved into the right direction. It is refused with the same
    actionable message ``carb_heat`` gets rather than guessed at.
    """

    @pytest.mark.parametrize(
        ("action", "expected"),
        [
            ("toggle", ("PARKING_BRAKES", 0)),
            ("on", (None, 0)),
            ("off", (None, 0)),
            ("release", (None, 0)),
            ("set", (None, 0)),
            ("apply", (None, 0)),
            ("engage", (None, 0)),
        ],
        ids=[
            "toggle-resolves",
            "on-unresolvable",
            "off-unresolvable",
            "release-unresolvable",
            "set-unresolvable",
            "apply-unresolvable",
            "engage-unresolvable",
        ],
    )
    def test_resolver_only_understands_toggle(
        self, action: str, expected: tuple[str | None, int]
    ) -> None:
        """Defence in depth: the resolver itself cannot emit a blind parking-brake toggle."""
        assert _resolve_command("parking_brake", action, None) == expected, _CR04_REGRESSION

    @pytest.mark.parametrize(
        "action",
        ["on", "off", "release", "set", "apply", "engage", " OFF ", "Release"],
        ids=[
            "on",
            "off",
            "release",
            "set",
            "apply",
            "engage",
            "padded-uppercase-off",
            "mixed-case-release",
        ],
    )
    @pytest.mark.asyncio
    async def test_absolute_position_is_refused(self, action: str) -> None:
        mock_client = _control_client()

        result = await set_aircraft_control(mock_client, "parking_brake", action)

        mock_client.send_command.assert_not_called()
        assert result["unresolvable"] is True, _CR04_REGRESSION
        assert "parking brake" in result["error"], _CR04_REGRESSION
        assert "current position" in result["error"]
        assert "toggle" in result["error"]
        assert result["system"] == "parking_brake"
        assert result["action"] == action
        # The refusal now runs before the resolver's None is turned into an error,
        # so a refused parking-brake action carries no resolved event at all.
        assert result["command"] is None

    @pytest.mark.asyncio
    async def test_toggle_still_executes(self) -> None:
        mock_client = _control_client()

        await set_aircraft_control(mock_client, "parking_brake", "toggle")

        mock_client.send_command.assert_awaited_once_with("PARKING_BRAKES", 0)

    @pytest.mark.asyncio
    async def test_unknown_system_still_reports_unknown_control(self) -> None:
        """The reorder must not swallow a genuinely unknown system.

        Moving the refusal above the ``command is None`` return is what makes the
        parking-brake message reachable; if it swallowed everything unresolvable the
        pilot would get a lecture about telemetry for a typo (T-02-14-06).
        """
        mock_client = _control_client()

        result = await set_aircraft_control(mock_client, "nonsense", "wibble")

        mock_client.send_command.assert_not_called()
        assert "Unknown control" in result["error"]
        assert "unresolvable" not in result

    def test_refused_action_table_covers_every_unconfirmable_system(self) -> None:
        """The two tables are read together and must not drift apart.

        ``set_aircraft_control`` looks the action up in ``UNCONFIRMABLE_REFUSED_ACTIONS``
        and then reads the label out of ``UNCONFIRMABLE_POSITION_SYSTEMS``. A system in
        one table but not the other is either an unreachable refusal or a ``KeyError``
        inside the command path.
        """
        assert set(tools_module.UNCONFIRMABLE_REFUSED_ACTIONS) == set(
            tools_module.UNCONFIRMABLE_POSITION_SYSTEMS
        )
        assert "parking_brake" in tools_module.UNCONFIRMABLE_REFUSED_ACTIONS
        assert tools_module.UNCONFIRMABLE_POSITION_SYSTEMS["parking_brake"] == "parking brake"


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
        result = await set_aircraft_control(mock_client, "gear", "down", verifier=verifier)

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
        result = await set_aircraft_control(mock_client, "gear", "down", verifier=verifier)

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
        result = await set_aircraft_control(mock_client, "gear", "down", verifier=verifier)

        assert "verification" not in result


# ---------------------------------------------------------------------------
# AUTH-01..04 -- the authority gate
# ---------------------------------------------------------------------------


class TestAuthorityGateMatrix:
    """All three authority levels crossed with all three safety severities.

    Nine cells. This is the single highest-value test in the phase: it pins that
    ``blocked`` still wins everywhere, that ``assisted`` differs from ``full``
    only on a ``warning`` verdict, and that ``advisory`` transmits nothing.
    """

    @pytest.mark.parametrize(
        ("level", "severity", "expect_sent", "expect_marker"),
        [
            (AuthorityLevel.FULL, "", True, None),
            (AuthorityLevel.FULL, "warning", True, "safety_warning"),
            (AuthorityLevel.FULL, "blocked", False, "blocked"),
            (AuthorityLevel.ASSISTED, "", True, None),
            (AuthorityLevel.ASSISTED, "warning", False, "withheld"),
            (AuthorityLevel.ASSISTED, "blocked", False, "blocked"),
            (AuthorityLevel.ADVISORY, "", False, "advisory"),
            (AuthorityLevel.ADVISORY, "warning", False, "advisory"),
            (AuthorityLevel.ADVISORY, "blocked", False, "blocked"),
        ],
        ids=[
            "full-clean-executes",
            "full-warning-executes-with-advisory",
            "full-blocked-refused",
            "assisted-clean-executes",
            "assisted-warning-withheld",
            "assisted-blocked-refused",
            "advisory-clean-dry-run",
            "advisory-warning-dry-run",
            "advisory-blocked-refused",
        ],
    )
    @pytest.mark.asyncio
    async def test_level_by_severity_matrix(
        self,
        level: AuthorityLevel,
        severity: str,
        expect_sent: bool,
        expect_marker: str | None,
    ) -> None:
        mock_client = _control_client()
        reason = "safety rule fired" if severity else ""

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            safety_check=_StubSafetyCheck(severity, reason),
            authority=AuthorityState(level),
        )

        if expect_sent:
            mock_client.send_command.assert_awaited_once_with("GEAR_DOWN", 0)
        else:
            mock_client.send_command.assert_not_called()

        markers = {"advisory", "withheld", "blocked"}
        present = {key for key in markers if key in result}
        if expect_marker in markers:
            assert present == {expect_marker}, result
        else:
            assert present == set(), result

        if expect_marker == "safety_warning":
            assert result["safety_warning"] == reason
        if expect_marker == "blocked":
            assert result["severity"] == "blocked"
        if expect_marker in ("advisory", "withheld"):
            # These are decisions, not failures -- an "error" key makes the web
            # layer render a dry run as a failed command (B8).
            assert "error" not in result, result
            assert result["authority_level"] == level.value
            assert result["safety"]["severity"] == severity


class TestAuthorityAdvisoryDryRun:
    """AUTH-02: advisory describes the intended action and transmits nothing."""

    @pytest.mark.asyncio
    async def test_advisory_returns_dry_run_and_sends_nothing(self) -> None:
        mock_client = _control_client()
        history = CommandHistory()

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            command_history=history,
            authority=AuthorityState(AuthorityLevel.ADVISORY),
        )

        mock_client.send_command.assert_not_called()
        assert result["advisory"] is True
        assert result["would_execute"] == "GEAR_DOWN"
        assert result["command"] == "GEAR_DOWN"
        assert result["system"] == "gear"
        assert result["action"] == "down"
        assert result["authority_reason"] == "config"
        assert "error" not in result
        assert result["message"]
        # A dry run is not a command: nothing is recorded for undo.
        assert len(history) == 0

    @pytest.mark.asyncio
    async def test_advisory_message_carries_the_safety_warning(self) -> None:
        mock_client = _control_client()

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            safety_check=_StubSafetyCheck("warning", "gear extension above 180 kt"),
            authority=AuthorityState(AuthorityLevel.ADVISORY),
        )

        assert result["safety"] == {
            "severity": "warning",
            "reason": "gear extension above 180 kt",
        }
        assert "gear extension above 180 kt" in result["message"]

    @pytest.mark.asyncio
    async def test_advisory_unknown_system_still_returns_unknown_control(self) -> None:
        """The gate sits *after* resolution, so a bad request is still a bad request."""
        mock_client = _control_client()

        result = await set_aircraft_control(
            mock_client,
            "weapons",
            "fire",
            authority=AuthorityState(AuthorityLevel.ADVISORY),
        )

        assert "Unknown control" in result["error"]
        assert "advisory" not in result
        mock_client.send_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_degraded_authority_reaches_the_gate_as_advisory(self) -> None:
        """The phase's fail-safe path must arrive as advisory, attributed as degraded."""
        mock_client = _control_client()

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            authority=AuthorityState.degraded_fallback("settings failed to load"),
        )

        mock_client.send_command.assert_not_called()
        assert result["advisory"] is True
        assert result["authority_level"] == "advisory"
        assert result["authority_reason"] == "degraded"


class TestAuthorityWithhold:
    """AUTH-03: assisted defers to the pilot on a flagged command."""

    @pytest.mark.asyncio
    async def test_assisted_withhold_reads_as_deferral_not_failure(self) -> None:
        mock_client = _control_client()

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            safety_check=_StubSafetyCheck("warning", "gear extension above 180 kt"),
            authority=AuthorityState(AuthorityLevel.ASSISTED),
        )

        mock_client.send_command.assert_not_called()
        assert result["withheld"] is True
        assert result["command"] == "GEAR_DOWN"
        assert result["authority_level"] == "assisted"
        assert "error" not in result
        assert "gear extension above 180 kt" in result["message"]


# ---------------------------------------------------------------------------
# Gap 1 / CR-02 -- "executed" is a claim, and it must be earned
# ---------------------------------------------------------------------------


_CR02_REGRESSION = (
    "REGRESSION (VERIFICATION Gap 1, finding CR-02, threat T-02-11-01): "
    '`safety_note` said "Critical system change executed" on a command the '
    "adapter NACKed or the authority floor refused -- in the same dict whose "
    "`error` said nothing was sent. Claude relays that dict to the pilot on both "
    "the CLI and the browser path, so a gear that never moved is reported as a "
    "critical system change. Gate the note on `_was_transmitted(result)`, never on "
    "membership in CRITICAL_COMMANDS alone."
)

_NACK = {"success": False, "message": "Unknown command"}
_FLOOR_REFUSAL = {
    "success": False,
    "error": (
        "Refused: MERLIN holds advisory authority only (watchdog); "
        "nothing was sent to the aircraft."
    ),
    "refused": True,
    "authority_level": "advisory",
    "authority_reason": "watchdog",
}


class TestWasTransmitted:
    """The one predicate every "did this actually reach the aircraft" check reads.

    Both halves of the expression are load-bearing. ``success`` alone misses the
    floor refusal and the ack timeout (both set ``success: False`` *and* an
    ``error``); ``"error" not in result`` alone misses the negative adapter ack,
    which ``sim_client.py`` documents as routine and which carries no ``error``
    key at all. It is the shape every heuristic in this codebase has got wrong.
    """

    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            ({"success": True, "message": ""}, True),
            ({"success": True}, True),
            (_NACK, False),
            (_FLOOR_REFUSAL, False),
            ({"success": False, "error": "Command timed out"}, False),
            ({"success": False, "error": "Failed to send command: boom"}, False),
            ({"advisory": True, "would_execute": "GEAR_DOWN"}, False),
            ({"withheld": True, "command": "GEAR_DOWN"}, False),
            ({"command": "GEAR_DOWN"}, False),
            ({}, False),
            ({"success": True, "error": "Command timed out"}, False),
        ],
        ids=[
            "positive-ack-is-a-transmission",
            "bare-success-is-a-transmission",
            "negative-ack-carries-no-error-key",
            "authority-floor-refusal",
            "ack-timeout",
            "send-failure",
            "advisory-dry-run",
            "assisted-withhold",
            "neither-key-fails-closed",
            "empty-dict-fails-closed",
            "contradictory-dict-fails-closed",
        ],
    )
    def test_predicate(self, result: dict[str, object], expected: bool) -> None:
        assert _was_transmitted(result) is expected, _CR02_REGRESSION


class TestCriticalSafetyNoteRequiresTransmission:
    """CR-02: the note is attached only to a command the adapter acknowledged."""

    @pytest.mark.asyncio
    async def test_nacked_critical_command_has_no_safety_note(self) -> None:
        mock_client = _control_client(dict(_NACK))

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            safety_check=_StubSafetyCheck(),
            authority=AuthorityState(AuthorityLevel.FULL),
        )

        assert result["success"] is False
        assert "safety_note" not in result, _CR02_REGRESSION

    @pytest.mark.asyncio
    async def test_floor_refused_critical_command_has_no_safety_note(self) -> None:
        """The floor re-reads authority at dispatch, so the gate can allow and it refuse."""
        mock_client = _control_client(dict(_FLOOR_REFUSAL))

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            safety_check=_StubSafetyCheck(),
            authority=AuthorityState(AuthorityLevel.FULL),
        )

        assert result["refused"] is True
        assert "safety_note" not in result, _CR02_REGRESSION

    @pytest.mark.asyncio
    async def test_advisory_dry_run_has_no_safety_note(self) -> None:
        mock_client = _control_client()

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            safety_check=_StubSafetyCheck(),
            authority=AuthorityState(AuthorityLevel.ADVISORY),
        )

        mock_client.send_command.assert_not_called()
        assert result["advisory"] is True
        assert "safety_note" not in result, _CR02_REGRESSION

    @pytest.mark.asyncio
    async def test_transmitted_critical_command_still_carries_the_note(self) -> None:
        mock_client = _control_client({"success": True})

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            safety_check=_StubSafetyCheck(),
            authority=AuthorityState(AuthorityLevel.FULL),
        )

        assert result["safety_note"] == "Critical system change executed"

    @pytest.mark.parametrize(
        "send_result",
        [{"success": True, "message": ""}, dict(_NACK)],
        ids=["acknowledged", "nacked"],
    )
    @pytest.mark.asyncio
    async def test_non_critical_command_never_carries_the_note(
        self, send_result: dict[str, object]
    ) -> None:
        mock_client = _control_client(send_result)

        result = await set_aircraft_control(
            mock_client,
            "flaps",
            "2",
            safety_check=_StubSafetyCheck(),
            authority=AuthorityState(AuthorityLevel.FULL),
        )

        assert "safety_note" not in result


# ---------------------------------------------------------------------------
# WR-10 part 1 -- assisted must not read "I could not check" as "it checked out"
# ---------------------------------------------------------------------------


_WR10_REGRESSION = (
    "REGRESSION (VERIFICATION WR-10 part 1, threat T-02-11-04): at `assisted`, an "
    "absent safety verdict (`safety_result is None`, telemetry unreachable) took "
    "the same branch as a clean one, so the one level whose job is to be "
    "conservative transmitted an unchecked command the moment it could not see the "
    "aircraft. Missing evidence is not evidence of safety. Discriminate on "
    "`safety_result is None` -- never on the severity string, because a CLEAN "
    'verdict also renders as "" and gating on that withholds everything.'
)


def _blind_client() -> MagicMock:
    """A client that cannot report state: every safety check comes back absent."""
    mock_client = _control_client()
    mock_client.get_state = AsyncMock(side_effect=ConnectionError("telemetry down"))
    return mock_client


class TestAssistedWithholdsWithoutAVerdict:
    """AUTH-03: no verdict is not a clean verdict."""

    @pytest.mark.asyncio
    async def test_assisted_withholds_when_telemetry_is_unreachable(self) -> None:
        mock_client = _blind_client()

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            authority=AuthorityState(AuthorityLevel.ASSISTED),
        )

        mock_client.send_command.assert_not_called()
        assert result["withheld"] is True, _WR10_REGRESSION
        assert result["no_verdict"] is True, _WR10_REGRESSION
        assert result["command"] == "GEAR_DOWN"
        assert result["authority_level"] == "assisted"
        # A withhold is a decision, not a failure -- an "error" key makes the web
        # layer render it as a failed command (B8).
        assert "error" not in result, result

    @pytest.mark.asyncio
    async def test_no_verdict_withhold_does_not_claim_a_safety_warning(self) -> None:
        mock_client = _blind_client()

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            authority=AuthorityState(AuthorityLevel.ASSISTED),
        )

        assert result["safety"]["severity"] == "", _WR10_REGRESSION
        assert "no safety verdict" in result["safety"]["reason"]
        message = result["message"].lower()
        assert "nothing was sent" in message
        assert "no verdict" in message
        assert "warning" not in message, (
            "the no-verdict withhold must not be mistaken for a flagged command: "
            "nothing fired, MERLIN simply cannot see the aircraft (WR-10)"
        )

    @pytest.mark.asyncio
    async def test_assisted_clean_verdict_still_executes(self) -> None:
        """The other half of WR-10: a clean verdict must NOT be caught by the fix."""
        mock_client = _control_client()

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            safety_check=_StubSafetyCheck(),
            authority=AuthorityState(AuthorityLevel.ASSISTED),
        )

        mock_client.send_command.assert_awaited_once_with("GEAR_DOWN", 0)
        assert "withheld" not in result, _WR10_REGRESSION
        assert "no_verdict" not in result, _WR10_REGRESSION

    @pytest.mark.asyncio
    async def test_assisted_warning_withhold_is_not_marked_no_verdict(self) -> None:
        mock_client = _control_client()

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            safety_check=_StubSafetyCheck("warning", "gear extension above 180 kt"),
            authority=AuthorityState(AuthorityLevel.ASSISTED),
        )

        assert result["withheld"] is True
        assert "no_verdict" not in result, (
            "a flagged command and an unseeable aircraft are different states and "
            "must stay distinguishable in the dict Claude reads (WR-10)"
        )
        assert result["safety"]["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_full_still_executes_without_a_verdict(self) -> None:
        """AUTH-04: `full` deliberately keeps today's behaviour when telemetry is down."""
        mock_client = _blind_client()

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            authority=AuthorityState(AuthorityLevel.FULL),
        )

        mock_client.send_command.assert_awaited_once_with("GEAR_DOWN", 0)
        assert "withheld" not in result
        assert "no_verdict" not in result

    @pytest.mark.asyncio
    async def test_advisory_without_a_verdict_is_still_a_dry_run(self) -> None:
        """Advisory outranks the no-verdict withhold: it already sends nothing."""
        mock_client = _blind_client()

        result = await set_aircraft_control(
            mock_client,
            "gear",
            "down",
            authority=AuthorityState(AuthorityLevel.ADVISORY),
        )

        mock_client.send_command.assert_not_called()
        assert result["advisory"] is True
        assert "withheld" not in result

    def test_the_broken_review_fix_is_not_present(self) -> None:
        """02-REVIEW.md proposed a form that withholds every assisted command."""
        source = tools_module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        assert 'safety_severity in ("warning", "")' not in text, (
            "a CLEAN verdict also carries severity == '', so this form withholds "
            "every command at assisted, including the ones that checked out "
            "(WR-10). Discriminate on `safety_result is None`."
        )


class TestAuthorityNoneEquivalentToFull:
    """AUTH-04 regression guard: omitting ``authority`` must not change behaviour."""

    @pytest.mark.asyncio
    async def test_omitted_authority_matches_explicit_full(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tools_module, "_warned_missing_authority", False)

        omitted_client = _control_client()
        omitted = await set_aircraft_control(omitted_client, "gear", "down")

        explicit_client = _control_client()
        explicit = await set_aircraft_control(
            explicit_client,
            "gear",
            "down",
            authority=AuthorityState(AuthorityLevel.FULL),
        )

        # The WARNING the omitted call emits is asserted separately below; it is a
        # log record, not a behavioural difference.
        assert omitted == explicit
        assert omitted_client.send_command.await_args == explicit_client.send_command.await_args
        omitted_client.send_command.assert_awaited_once_with("GEAR_DOWN", 0)

    @pytest.mark.asyncio
    async def test_missing_authority_warns_once_then_stays_quiet(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(tools_module, "_warned_missing_authority", False)
        caplog.set_level(logging.WARNING, logger="orchestrator.tools")

        await set_aircraft_control(_control_client(), "flaps", "2")
        first = [r for r in caplog.records if "AuthorityState" in r.getMessage()]
        caplog.clear()
        await set_aircraft_control(_control_client(), "flaps", "2")
        second = [r for r in caplog.records if "AuthorityState" in r.getMessage()]

        assert len(first) == 1, "a missing authority injection must not be silent"
        assert second == [], "the warning must be deduped, not repeated per command"

    def test_no_module_level_authority_singleton(self) -> None:
        """D-09: the ``safety_check or _safety_check`` shape must not be copied."""
        source = tools_module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        assert "_authority = AuthorityState" not in text
        assert "authority or _authority" not in text


_CR03_REGRESSION = (
    "REGRESSION (VERIFICATION Gap 1, finding CR-03, threat T-02-11-02/03): "
    "`undo_last_command` popped the history record *before* the authority gate "
    'ran and then wrote `undo_description: "Reversed <cmd>"` unconditionally. At '
    "advisory, on a withhold, on a block or on an adapter NACK the pilot was told "
    "the command had been reversed, while the record that would have let them try "
    "again had already been destroyed -- they could neither undo it later nor tell "
    "that the undo had not happened. Pop only after `_was_transmitted(result)`."
)


def _history_with_gear_down() -> CommandHistory:
    """One reversible GEAR_DOWN record — the fixture every undo case starts from."""
    history = CommandHistory()
    history.record(
        command="GEAR_DOWN",
        value=0,
        system="gear",
        action="down",
        state_before=SimState(),
    )
    return history


class TestUndoThreadsAuthority:
    """The undo path is a command path; it must go through the same gate."""

    @pytest.mark.asyncio
    async def test_undo_at_advisory_sends_nothing(self) -> None:
        mock_client = _control_client()
        history = _history_with_gear_down()

        result = await undo_last_command(
            mock_client,
            history,
            # Clean verdict: this test is about the authority thread-through, not
            # about the real gear-up-on-the-ground rule the default SimState trips.
            safety_check=_StubSafetyCheck(),
            authority=AuthorityState(AuthorityLevel.ADVISORY),
        )

        mock_client.send_command.assert_not_called()
        assert result["advisory"] is True
        assert result["would_execute"] == "GEAR_UP"
        assert len(history) == 1, _CR03_REGRESSION
        assert result["undo_target"] == "GEAR_DOWN"
        assert result["undo_description"].startswith("Would reverse"), _CR03_REGRESSION
        assert "undone_command" not in result, _CR03_REGRESSION

    @pytest.mark.asyncio
    async def test_undo_withheld_at_assisted_keeps_the_record(self) -> None:
        mock_client = _control_client()
        history = _history_with_gear_down()

        result = await undo_last_command(
            mock_client,
            history,
            safety_check=_StubSafetyCheck("warning", "gear retraction below 50 ft"),
            authority=AuthorityState(AuthorityLevel.ASSISTED),
        )

        mock_client.send_command.assert_not_called()
        assert result["withheld"] is True
        assert len(history) == 1, _CR03_REGRESSION
        assert result["undo_description"].startswith("Would reverse"), _CR03_REGRESSION
        assert "undone_command" not in result, _CR03_REGRESSION

    @pytest.mark.asyncio
    async def test_undo_nacked_by_the_adapter_keeps_the_record(self) -> None:
        """The shape with no `error` key — the one every heuristic here has missed."""
        mock_client = _control_client(dict(_NACK))
        history = _history_with_gear_down()

        result = await undo_last_command(
            mock_client,
            history,
            safety_check=_StubSafetyCheck(),
            authority=AuthorityState(AuthorityLevel.FULL),
        )

        mock_client.send_command.assert_awaited_once_with("GEAR_UP", 0)
        assert result["success"] is False
        assert len(history) == 1, _CR03_REGRESSION
        assert result["undo_description"].startswith("Would reverse"), _CR03_REGRESSION
        assert "undone_command" not in result, _CR03_REGRESSION

    @pytest.mark.asyncio
    async def test_undo_refused_by_the_authority_floor_keeps_the_record(self) -> None:
        mock_client = _control_client(dict(_FLOOR_REFUSAL))
        history = _history_with_gear_down()

        result = await undo_last_command(
            mock_client,
            history,
            safety_check=_StubSafetyCheck(),
            authority=AuthorityState(AuthorityLevel.FULL),
        )

        assert result["refused"] is True
        assert len(history) == 1, _CR03_REGRESSION
        assert "undone_command" not in result, _CR03_REGRESSION

    @pytest.mark.asyncio
    async def test_undo_blocked_by_safety_keeps_the_record(self) -> None:
        mock_client = _control_client()
        history = _history_with_gear_down()

        result = await undo_last_command(
            mock_client,
            history,
            safety_check=_StubSafetyCheck("blocked", "gear up on the ground"),
            authority=AuthorityState(AuthorityLevel.FULL),
        )

        mock_client.send_command.assert_not_called()
        assert result["blocked"] is True
        assert len(history) == 1, _CR03_REGRESSION
        assert result["undo_description"].startswith("Would reverse"), _CR03_REGRESSION
        assert "undone_command" not in result, _CR03_REGRESSION

    @pytest.mark.asyncio
    async def test_undo_transmitted_pops_exactly_one_record(self) -> None:
        mock_client = _control_client({"success": True, "message": ""})
        history = _history_with_gear_down()

        result = await undo_last_command(
            mock_client,
            history,
            safety_check=_StubSafetyCheck(),
            authority=AuthorityState(AuthorityLevel.FULL),
        )

        mock_client.send_command.assert_awaited_once_with("GEAR_UP", 0)
        assert len(history) == 0, _CR03_REGRESSION
        assert result["undone_command"] == "GEAR_DOWN"
        assert result["undo_description"].startswith("Reversed GEAR_DOWN"), _CR03_REGRESSION

    @pytest.mark.asyncio
    async def test_undo_description_keeps_the_value_suffix_on_both_branches(self) -> None:
        """A value-restore undo names the value it would set, sent or not."""
        state_before = SimState(autopilot=AutopilotState(heading=270))
        history = CommandHistory()
        history.record(
            command="HEADING_BUG_SET",
            value=90,
            system="autopilot",
            action="heading",
            state_before=state_before,
        )

        withheld_client = _control_client()
        withheld = await undo_last_command(
            withheld_client,
            history,
            safety_check=_StubSafetyCheck(),
            authority=AuthorityState(AuthorityLevel.ADVISORY),
        )

        assert withheld["undo_description"].endswith("270.0"), _CR03_REGRESSION
        assert len(history) == 1, _CR03_REGRESSION

        sent = await undo_last_command(
            _control_client({"success": True, "message": ""}),
            history,
            safety_check=_StubSafetyCheck(),
            authority=AuthorityState(AuthorityLevel.FULL),
        )

        assert sent["undo_description"].endswith("270.0")
        assert sent["undone_command"] == "HEADING_BUG_SET"
        assert len(history) == 0

    @pytest.mark.asyncio
    async def test_undo_with_empty_history_is_unchanged(self) -> None:
        result = await undo_last_command(_control_client(), CommandHistory())

        assert result == {"error": "No commands to undo"}

    @pytest.mark.asyncio
    async def test_undo_non_reversible_does_not_pop(self) -> None:
        mock_client = _control_client()
        history = CommandHistory()
        history.record(
            command="TOGGLE_STARTER1",
            value=0,
            system="starter",
            action="engage",
            state_before=SimState(),
        )

        result = await undo_last_command(mock_client, history)

        assert "not reversible" in result["error"]
        mock_client.send_command.assert_not_called()
        assert len(history) == 1, _CR03_REGRESSION
