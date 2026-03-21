"""Tests for orchestrator.sim_client — SimState model and SimConnectClient."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.sim_client import (
    Attitude,
    AutopilotState,
    EngineData,
    Engines,
    Environment,
    FlightPhase,
    FuelState,
    Position,
    RadioState,
    SimConnectClient,
    SimState,
    Speeds,
    SurfaceState,
)


# ---------------------------------------------------------------------------
# SimState model parsing
# ---------------------------------------------------------------------------


class TestSimStateParsing:
    """Test that SimState correctly parses from JSON / dict payloads."""

    def test_parse_full_payload(self, sample_bridge_broadcast: dict[str, Any]) -> None:
        state = SimState.model_validate(sample_bridge_broadcast)
        assert state.aircraft == "Cessna 172 Skyhawk"
        assert state.position.altitude_msl == 6500
        assert state.speeds.indicated_airspeed == 120
        assert state.autopilot.master is True
        # flight_phase is not in the bridge payload, so it defaults
        assert state.on_ground is False  # AGL=6400, far above 10

    def test_parse_minimal_payload_uses_defaults(self) -> None:
        state = SimState.model_validate({})
        assert state.aircraft == ""
        assert state.position.altitude_msl == 0.0
        assert state.on_ground is True  # AGL=0, < 10
        assert state.flight_phase == FlightPhase.PREFLIGHT

    def test_parse_position(self) -> None:
        pos = Position(latitude=40.6413, longitude=-73.7781, altitude_msl=13, altitude_agl=0)
        assert pos.latitude == pytest.approx(40.6413)
        assert pos.altitude_agl == 0

    def test_parse_engine_data(self) -> None:
        engines = Engines(
            engine_count=2,
            engines=[
                EngineData(rpm=2400, fuel_flow_gph=9.0, oil_temp=190, oil_pressure=60),
                EngineData(rpm=2400, fuel_flow_gph=8.5, oil_temp=188, oil_pressure=59),
            ],
        )
        assert len(engines.active_engines) == 2
        assert engines.active_engines[1].fuel_flow_gph == pytest.approx(8.5)

    def test_parse_flight_phase_enum(self) -> None:
        state = SimState.model_validate({"flight_phase": "APPROACH"})
        assert state.flight_phase == FlightPhase.APPROACH

    def test_parse_invalid_flight_phase_raises(self) -> None:
        with pytest.raises(Exception):
            SimState.model_validate({"flight_phase": "HOVERING"})

    def test_radios_defaults(self) -> None:
        radio = RadioState()
        assert radio.com1 == 0.0
        assert radio.nav1 == 0.0

    def test_environment_default_pressure(self) -> None:
        env = Environment()
        assert env.barometer_inhg == pytest.approx(29.92)

    def test_fuel_state_default_empty(self) -> None:
        fuel = FuelState()
        assert fuel.total_gallons == 0.0
        assert fuel.total_weight_lbs == 0.0

    def test_on_ground_derived_from_agl(self) -> None:
        state = SimState(position=Position(altitude_agl=5))
        assert state.on_ground is True
        state2 = SimState(position=Position(altitude_agl=15))
        assert state2.on_ground is False


class TestSimStateTelemetrySummary:
    """Test the telemetry_summary() output format."""

    def test_on_ground_excludes_ground_speed(self, sim_state_parked: SimState) -> None:
        summary = sim_state_parked.telemetry_summary()
        assert "GS:" not in summary
        assert "Phase: PREFLIGHT" in summary

    def test_airborne_includes_ground_speed(self, sim_state_cruise: SimState) -> None:
        summary = sim_state_cruise.telemetry_summary()
        assert "GS:" in summary
        assert "135kt" in summary

    def test_autopilot_on_shows_ap_flag(self, sim_state_cruise: SimState) -> None:
        summary = sim_state_cruise.telemetry_summary()
        assert "AP:ON" in summary

    def test_autopilot_off_hides_ap_flag(self, sim_state_parked: SimState) -> None:
        summary = sim_state_parked.telemetry_summary()
        assert "AP:ON" not in summary

    def test_summary_contains_altitude(self, sim_state_cruise: SimState) -> None:
        summary = sim_state_cruise.telemetry_summary()
        assert "Alt: 6500ft" in summary

    def test_summary_contains_ias(self, sim_state_cruise: SimState) -> None:
        summary = sim_state_cruise.telemetry_summary()
        assert "IAS: 120kt" in summary

    def test_summary_contains_heading(self, sim_state_cruise: SimState) -> None:
        summary = sim_state_cruise.telemetry_summary()
        # heading_magnetic is 42
        assert "HDG: 42" in summary

    def test_summary_contains_vertical_speed(self, sim_state_descent: SimState) -> None:
        summary = sim_state_descent.telemetry_summary()
        assert "VS: -500fpm" in summary


# ---------------------------------------------------------------------------
# SimConnectClient
# ---------------------------------------------------------------------------


class TestSimConnectClient:
    """Test WebSocket client behavior with mocked connections."""

    def test_initial_state_is_default(self) -> None:
        client = SimConnectClient("ws://localhost:8080")
        assert client.state.aircraft == ""
        assert client.state.on_ground is True

    @pytest.mark.asyncio
    async def test_connect_creates_listen_task(self) -> None:
        client = SimConnectClient("ws://localhost:8080")
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = MagicMock(return_value=iter([]))
        with patch("orchestrator.sim_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
            await client.connect()
            assert client._listen_task is not None
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_closes_websocket(self) -> None:
        client = SimConnectClient("ws://localhost:8080")
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = MagicMock(return_value=iter([]))
        with patch("orchestrator.sim_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
            await client.connect()
            await client.disconnect()
            mock_ws.close.assert_awaited_once()
            assert client._ws is None

    @pytest.mark.asyncio
    async def test_get_state_returns_cached_state(self) -> None:
        """get_state now returns cached state — no WS send needed."""
        client = SimConnectClient("ws://localhost:8080")
        state = await client.get_state()
        assert state.aircraft == ""  # default cached state

    @pytest.mark.asyncio
    async def test_subscribe_callback_called_on_broadcast(self, sample_bridge_broadcast: dict[str, Any]) -> None:
        client = SimConnectClient("ws://localhost:8080")
        callback = AsyncMock()
        client.subscribe(callback)

        # Bridge broadcasts raw state JSON (no type wrapper)
        message = json.dumps(sample_bridge_broadcast)
        mock_ws = AsyncMock()

        async def fake_aiter():
            yield message

        mock_ws.__aiter__ = lambda self: fake_aiter()
        client._ws = mock_ws

        await client._listen_loop()

        callback.assert_awaited_once()
        received_state = callback.call_args[0][0]
        assert received_state.aircraft == "Cessna 172 Skyhawk"

    @pytest.mark.asyncio
    async def test_listen_loop_ignores_invalid_json(self) -> None:
        client = SimConnectClient("ws://localhost:8080")
        callback = AsyncMock()
        client.subscribe(callback)

        async def fake_aiter():
            yield "not valid json {{{{"

        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: fake_aiter()
        client._ws = mock_ws

        await client._listen_loop()
        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_listen_loop_ignores_typed_messages(self) -> None:
        """Messages with a 'type' field but no 'position' are ignored."""
        client = SimConnectClient("ws://localhost:8080")
        callback = AsyncMock()
        client.subscribe(callback)

        async def fake_aiter():
            yield json.dumps({"type": "state_response", "message": "OK"})

        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: fake_aiter()
        client._ws = mock_ws

        await client._listen_loop()
        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_subscriber_exception_does_not_crash_loop(self, sample_bridge_broadcast: dict[str, Any]) -> None:
        client = SimConnectClient("ws://localhost:8080")
        bad_callback = AsyncMock(side_effect=RuntimeError("boom"))
        good_callback = AsyncMock()
        client.subscribe(bad_callback)
        client.subscribe(good_callback)

        message = json.dumps(sample_bridge_broadcast)

        async def fake_aiter():
            yield message

        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: fake_aiter()
        client._ws = mock_ws

        await client._listen_loop()

        bad_callback.assert_awaited_once()
        good_callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_listen_loop_preserves_flight_phase(self, sample_bridge_broadcast: dict[str, Any]) -> None:
        """The listen loop should preserve the current flight_phase across updates."""
        client = SimConnectClient("ws://localhost:8080")
        client._state.flight_phase = FlightPhase.CRUISE

        message = json.dumps(sample_bridge_broadcast)

        async def fake_aiter():
            yield message

        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: fake_aiter()
        client._ws = mock_ws

        await client._listen_loop()

        assert client.state.flight_phase == FlightPhase.CRUISE
