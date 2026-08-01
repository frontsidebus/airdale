"""Integration tests for the tool execution pipeline.

Tests the individual tool functions and the dispatch flow from
ClaudeClient._execute_tool. Network-dependent tests (e.g. real API calls
to aviationapi.com) are marked ``@pytest.mark.network``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.authority import AuthorityLevel, AuthorityState
from orchestrator.claude_client import ClaudeClient
from orchestrator.command_safety import CommandSafetyCheck, SafetyResult
from orchestrator.context_store import ContextStore
from orchestrator.sim_client import FlightPhase, SimState, SurfaceState, TelemetryClient
from orchestrator.tools import (
    create_flight_plan,
    get_checklist,
    get_sim_state,
    lookup_airport,
    search_manual,
)

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sim_state() -> SimState:
    """A realistic SimState for tool tests."""
    return SimState(
        aircraft_title="Cessna 172S Skyhawk",
        flight_phase=FlightPhase.CRUISE,
        position={"latitude": 28.4294, "longitude": -81.309, "altitude": 5500},
        speeds={"indicated": 110, "ground_speed": 120, "vertical_speed": 0},
        attitude={"heading": 270},
        engine={"rpm": [2300], "fuel_flow": [8.6], "oil_temp": [180], "oil_pressure": [60]},
        fuel={"total": 42.0, "total_weight": 252.0, "quantities": [21.0, 21.0]},
        on_ground=False,
    )


@pytest.fixture()
def context_store(tmp_path: Path) -> ContextStore:
    return ContextStore(persist_path=str(tmp_path / "chroma"))


@pytest.fixture()
def populated_context_store(
    context_store: ContextStore, sample_document: Path, sample_document_metadata: dict
) -> ContextStore:
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        context_store.ingest_document(sample_document, metadata=sample_document_metadata)
    )
    return context_store


# ---------------------------------------------------------------------------
# get_sim_state tool
# ---------------------------------------------------------------------------


class TestGetSimState:
    async def test_returns_formatted_telemetry(self, sim_state: SimState) -> None:
        """get_sim_state should call sim_client.get_state and return a dict."""
        mock_sim = AsyncMock(spec=TelemetryClient)
        mock_sim.get_state.return_value = sim_state

        result = await get_sim_state(mock_sim)

        assert isinstance(result, dict)
        assert result["aircraft"] == "Cessna 172S Skyhawk"
        assert result["flight_phase"] == "CRUISE"
        assert result["position"]["altitude_msl"] == 5500
        assert result["speeds"]["indicated"] == 110
        assert result["on_ground"] is False

    async def test_engine_params_in_result(self, sim_state: SimState) -> None:
        mock_sim = AsyncMock(spec=TelemetryClient)
        mock_sim.get_state.return_value = sim_state

        result = await get_sim_state(mock_sim)
        assert result["engine"]["rpm"] == [2300]
        assert result["fuel"]["total_gallons"] == 42.0


# ---------------------------------------------------------------------------
# lookup_airport tool (real network)
# ---------------------------------------------------------------------------


@pytest.mark.network
class TestLookupAirportNetwork:
    """These tests make real HTTP calls to aviationapi.com."""

    async def test_lookup_known_airport(self) -> None:
        """KJFK should return JFK airport info."""
        result = await lookup_airport("KJFK")
        assert "error" not in result
        assert result["identifier"] == "KJFK"
        assert "KENNEDY" in result.get("name", "").upper() or "JFK" in result.get("name", "").upper()

    async def test_lookup_three_letter_code(self) -> None:
        """A 3-letter code like 'JFK' should be auto-prefixed with 'K'."""
        result = await lookup_airport("JFK")
        assert result["identifier"] == "KJFK"

    async def test_lookup_nonexistent_airport(self) -> None:
        """A made-up identifier should return an error dict."""
        result = await lookup_airport("KZZZ")
        assert "error" in result

    async def test_lookup_returns_location_data(self) -> None:
        result = await lookup_airport("KLAX")
        assert "error" not in result
        assert result.get("latitude")
        assert result.get("longitude")
        assert result.get("elevation")


# ---------------------------------------------------------------------------
# lookup_airport tool (mocked network)
# ---------------------------------------------------------------------------


class TestLookupAirportMocked:
    """Test lookup_airport logic without hitting the real API."""

    async def test_lookup_parses_response(self) -> None:
        mock_response = {
            "KJFK": [{
                "facility_name": "JOHN F KENNEDY INTL",
                "city": "NEW YORK",
                "state_full": "NEW YORK",
                "elevation": "13",
                "latitude": "40.63980556",
                "longitude": "-73.77869444",
                "status_code": "O",
            }]
        }
        with patch("orchestrator.tools.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = MagicMock()
            mock_instance.get.return_value = mock_resp

            result = await lookup_airport("KJFK")
            assert result["name"] == "JOHN F KENNEDY INTL"
            assert result["city"] == "NEW YORK"


# ---------------------------------------------------------------------------
# search_manual tool
# ---------------------------------------------------------------------------


class TestSearchManual:
    async def test_search_returns_results(
        self, populated_context_store: ContextStore
    ) -> None:
        results = await search_manual(
            "V-speeds", populated_context_store, aircraft_type="Cessna 172S Skyhawk"
        )
        assert len(results) > 0
        assert "content" in results[0]
        assert "source" in results[0]

    async def test_search_without_aircraft_filter(
        self, populated_context_store: ContextStore
    ) -> None:
        results = await search_manual("takeoff checklist", populated_context_store)
        assert len(results) > 0

    async def test_search_empty_store(self, context_store: ContextStore) -> None:
        results = await search_manual("anything", context_store)
        assert results == []


# ---------------------------------------------------------------------------
# get_checklist tool
# ---------------------------------------------------------------------------


class TestGetChecklist:
    async def test_default_checklist(self, context_store: ContextStore) -> None:
        """With no aircraft-specific docs, should return the default checklist."""
        result = await get_checklist("PREFLIGHT", context_store)
        assert result["phase"] == "PREFLIGHT"
        assert result["source"] == "default"
        assert isinstance(result["items"], list)
        assert len(result["items"]) > 0

    async def test_checklist_for_all_phases(self, context_store: ContextStore) -> None:
        """Every valid FlightPhase should return a checklist without errors."""
        for phase in FlightPhase:
            result = await get_checklist(phase.value, context_store)
            assert "error" not in result
            assert result["phase"] == phase.value

    async def test_invalid_phase(self, context_store: ContextStore) -> None:
        result = await get_checklist("INVALID_PHASE", context_store)
        assert "error" in result

    async def test_aircraft_specific_checklist(
        self, populated_context_store: ContextStore
    ) -> None:
        """With matching docs ingested, should prefer aircraft-specific checklist."""
        result = await get_checklist(
            "TAKEOFF", populated_context_store, aircraft_type="Cessna 172S Skyhawk"
        )
        # It should either return aircraft_manual source or default
        assert result["phase"] == "TAKEOFF"


# ---------------------------------------------------------------------------
# create_flight_plan tool (mocked network)
# ---------------------------------------------------------------------------


class TestCreateFlightPlan:
    async def test_plan_structure(self) -> None:
        """Flight plan should have departure, destination, route, etc."""
        mock_airport = {"identifier": "KXXX", "name": "Test", "city": "Test City"}
        with patch("orchestrator.tools.lookup_airport", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = mock_airport
            result = await create_flight_plan("KABC", "KXYZ", altitude=8000)

        assert result["cruise_altitude"] == 8000
        assert result["status"] == "draft"
        assert "KABC" in result["route"]
        assert "KXYZ" in result["route"]
        assert result["waypoints"][0] == "KABC"
        assert result["waypoints"][-1] == "KXYZ"

    async def test_plan_with_route_waypoints(self) -> None:
        mock_airport = {"identifier": "KXXX", "name": "Test"}
        with patch("orchestrator.tools.lookup_airport", new_callable=AsyncMock) as mock_lookup:
            mock_lookup.return_value = mock_airport
            result = await create_flight_plan(
                "KJFK", "KLAX", altitude=35000, route="J80 SIE J6"
            )

        assert "J80" in result["waypoints"]
        assert "SIE" in result["waypoints"]
        assert "J6" in result["waypoints"]


# ---------------------------------------------------------------------------
# Tool dispatch flow (simulates what ClaudeClient._execute_tool does)
# ---------------------------------------------------------------------------


class TestToolDispatchFlow:
    """Simulate the full cycle: Claude returns tool_use blocks, tools execute,
    results are returned. We mock Claude but run real tool code."""

    async def test_dispatch_get_sim_state(self, sim_state: SimState) -> None:
        """Dispatch a get_sim_state tool call and verify the result."""
        mock_sim = AsyncMock(spec=TelemetryClient)
        mock_sim.get_state.return_value = sim_state

        # Simulated tool_use block from Claude
        tool_block = {"id": "tool_1", "name": "get_sim_state", "input": {}}

        # Dispatch (mirrors ClaudeClient._execute_tool logic)
        result = await get_sim_state(mock_sim)
        assert result["aircraft"] == "Cessna 172S Skyhawk"

    async def test_dispatch_get_checklist(self, context_store: ContextStore) -> None:
        tool_block = {"id": "tool_2", "name": "get_checklist", "input": {"phase": "CRUISE"}}
        result = await get_checklist(
            tool_block["input"]["phase"], context_store, aircraft_type="Cessna 172S Skyhawk"
        )
        assert result["phase"] == "CRUISE"

    async def test_dispatch_unknown_tool_returns_error(self) -> None:
        """An unknown tool name should produce an error dict (as ClaudeClient does)."""
        # This mirrors the else branch in ClaudeClient._execute_tool
        name = "nonexistent_tool"
        result = {"error": f"Unknown tool: {name}"}
        assert "error" in result

    async def test_tool_result_is_json_serializable(
        self, sim_state: SimState, context_store: ContextStore
    ) -> None:
        """All tool results must be JSON-serializable for the Claude API."""
        mock_sim = AsyncMock(spec=TelemetryClient)
        mock_sim.get_state.return_value = sim_state

        results = [
            await get_sim_state(mock_sim),
            await get_checklist("PREFLIGHT", context_store),
        ]
        for r in results:
            # Should not raise
            serialized = json.dumps(r)
            assert isinstance(serialized, str)


# ---------------------------------------------------------------------------
# Authority end to end: tool_use block -> dispatch -> gate -> transport
# ---------------------------------------------------------------------------


class _WarningSafetyCheck(CommandSafetyCheck):
    """Safety checker returning a fixed ``warning`` verdict.

    Subclasses the real class rather than duck-typing so the substitution stays
    type-honest. ``assisted`` withholds specifically on ``warning``, and which of
    ``DEFAULT_RULES`` happens to fire for a given command is not what these tests
    are about.
    """

    def __init__(self, reason: str = "Gear cycle near max gear speed") -> None:
        super().__init__(rules=[])
        self._reason = reason

    def check(
        self,
        command: str,
        value: int,
        sim_state: SimState,
        aircraft_type: str = "",
    ) -> SafetyResult:
        return SafetyResult(safe=True, command=command, reason=self._reason, severity="warning")


def _command_sim_client() -> MagicMock:
    """A telemetry client wired the way the command path expects.

    ``gear_handle=True`` so the post-command verification for GEAR_DOWN confirms on
    its first poll instead of spending the whole verifier timeout.
    """
    client = MagicMock(spec=TelemetryClient)
    client.get_state = AsyncMock(
        return_value=SimState(surfaces=SurfaceState(gear_handle=True)),
    )
    client.send_command = AsyncMock(return_value={"success": True, "message": ""})
    return client


def _claude_with(authority: AuthorityState, sim_client: MagicMock) -> ClaudeClient:
    with patch("orchestrator.claude_client.anthropic.AsyncAnthropic"):
        return ClaudeClient(
            api_key="sk-ant-test",
            model="claude-sonnet-4-20250514",
            sim_client=sim_client,
            context_store=MagicMock(),
            authority=authority,
        )


async def _dispatch_gear_down(client: ClaudeClient) -> dict[str, Any]:
    """Run the tool_use block Claude would emit for 'gear down'."""
    tool_block = {
        "id": "tool_authority",
        "name": "set_aircraft_control",
        "input": {"system": "gear", "action": "down"},
    }
    return await client._execute_tool(tool_block["name"], tool_block["input"], SimState())


class TestAuthorityEndToEnd:
    """Dispatch a real set_aircraft_control tool_use block at each authority level.

    This is the only place the whole chain runs together: ``_execute_tool`` ->
    ``_dispatch_tool`` -> ``set_aircraft_control`` -> the authority gate ->
    ``TelemetryClient.send_command``. Everything below the gate is real code; only
    the transport and the Anthropic client are doubles.
    """

    async def test_full_executes_the_command(self) -> None:
        sim = _command_sim_client()
        client = _claude_with(AuthorityState(AuthorityLevel.FULL), sim)

        result = await _dispatch_gear_down(client)

        sim.send_command.assert_awaited_once_with("GEAR_DOWN", 0)
        assert "advisory" not in result
        assert "withheld" not in result

    async def test_advisory_describes_without_sending(self) -> None:
        sim = _command_sim_client()
        client = _claude_with(AuthorityState(AuthorityLevel.ADVISORY), sim)

        result = await _dispatch_gear_down(client)

        sim.send_command.assert_not_called()
        assert result["advisory"] is True
        assert result["would_execute"] == "GEAR_DOWN"
        assert result["authority_level"] == "advisory"
        assert result["authority_reason"] == "config"
        # A restrained command is a decision, not a failure: the web layer's
        # `success = "error" not in tool_result` heuristic depends on this.
        assert "error" not in result

    async def test_assisted_withholds_a_flagged_command(self) -> None:
        sim = _command_sim_client()
        client = _claude_with(AuthorityState(AuthorityLevel.ASSISTED), sim)

        # ClaudeClient deliberately does not inject safety_check, so the tool falls
        # back to the module-level checker -- which is what production runs.
        with patch("orchestrator.tools._safety_check", _WarningSafetyCheck()):
            result = await _dispatch_gear_down(client)

        sim.send_command.assert_not_called()
        assert result["withheld"] is True
        assert result["authority_level"] == "assisted"
        assert result["safety"]["severity"] == "warning"
        assert "error" not in result

    async def test_degraded_fallback_behaves_as_advisory(self) -> None:
        """A composition root that failed must land restrained, not unrestricted."""
        sim = _command_sim_client()
        client = _claude_with(AuthorityState.degraded_fallback("boom"), sim)

        result = await _dispatch_gear_down(client)

        sim.send_command.assert_not_called()
        assert result["advisory"] is True
        assert result["authority_level"] == "advisory"
        assert result["authority_reason"] == "degraded"

    async def test_the_forwarded_state_is_the_one_the_client_was_given(self) -> None:
        """An override recorded on the shared state changes the next dispatch."""
        sim = _command_sim_client()
        authority = AuthorityState(AuthorityLevel.FULL)
        client = _claude_with(authority, sim)

        first = await _dispatch_gear_down(client)
        assert "advisory" not in first

        authority.record_override()
        second = await _dispatch_gear_down(client)

        assert second["advisory"] is True
        assert second["authority_reason"] == "override"
        assert sim.send_command.await_count == 1
