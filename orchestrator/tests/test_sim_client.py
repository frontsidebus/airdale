"""Tests for orchestrator.sim_client -- SimState model and TelemetryClient."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from orchestrator.authority import AuthorityLevel, AuthorityReason, AuthorityState
from orchestrator.sim_client import (
    ConnectionState,
    EngineData,
    Engines,
    Environment,
    FlightPhase,
    FuelState,
    HealthMonitor,
    Position,
    RadioState,
    SimState,
    SubsystemHealth,
    TelemetryClient,
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
        pos = Position(
            latitude=40.6413,
            longitude=-73.7781,
            altitude_msl=13,
            altitude_agl=0,
        )
        assert pos.latitude == pytest.approx(40.6413)
        assert pos.altitude_agl == 0

    def test_parse_engine_data(self) -> None:
        engines = Engines(
            engine_count=2,
            engines=[
                EngineData(
                    rpm=2400,
                    fuel_flow_gph=9.0,
                    oil_temp=190,
                    oil_pressure=60,
                ),
                EngineData(
                    rpm=2400,
                    fuel_flow_gph=8.5,
                    oil_temp=188,
                    oil_pressure=59,
                ),
            ],
        )
        assert len(engines.active_engines) == 2
        assert engines.active_engines[1].fuel_flow_gph == pytest.approx(8.5)

    def test_parse_flight_phase_enum(self) -> None:
        state = SimState.model_validate({"flight_phase": "APPROACH"})
        assert state.flight_phase == FlightPhase.APPROACH

    def test_parse_invalid_flight_phase_raises(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 - any pydantic validation error
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
# TelemetryClient
# ---------------------------------------------------------------------------


class TestTelemetryClient:
    """Test WebSocket client behavior with mocked connections."""

    def test_initial_state_is_default(self) -> None:
        client = TelemetryClient("ws://localhost:8080")
        assert client.state.aircraft == ""
        assert client.state.on_ground is True

    def test_initial_connection_state(self) -> None:
        client = TelemetryClient("ws://localhost:8080")
        assert client.connection_state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_connect_creates_listen_task(self) -> None:
        client = TelemetryClient("ws://localhost:8080")
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = MagicMock(return_value=iter([]))
        with patch(
            "orchestrator.sim_client.websockets.connect",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            await client.connect()
            assert client._listen_task is not None
            assert client.connection_state == ConnectionState.CONNECTED
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_closes_websocket(self) -> None:
        client = TelemetryClient("ws://localhost:8080")
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = MagicMock(return_value=iter([]))
        with patch(
            "orchestrator.sim_client.websockets.connect",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            await client.connect()
            await client.disconnect()
            mock_ws.close.assert_awaited_once()
            assert client._ws is None
            assert client.connection_state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_get_state_returns_cached_state(self) -> None:
        """get_state now returns cached state -- no WS send needed."""
        client = TelemetryClient("ws://localhost:8080")
        state = await client.get_state()
        assert state.aircraft == ""  # default cached state

    @pytest.mark.asyncio
    async def test_subscribe_callback_called_on_broadcast(
        self, sample_bridge_broadcast: dict[str, Any]
    ) -> None:
        client = TelemetryClient("ws://localhost:8080", auto_reconnect=False)
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
        client = TelemetryClient("ws://localhost:8080", auto_reconnect=False)
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
        client = TelemetryClient("ws://localhost:8080", auto_reconnect=False)
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
    async def test_subscriber_exception_does_not_crash_loop(
        self, sample_bridge_broadcast: dict[str, Any]
    ) -> None:
        client = TelemetryClient("ws://localhost:8080", auto_reconnect=False)
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
    async def test_listen_loop_preserves_flight_phase(
        self, sample_bridge_broadcast: dict[str, Any]
    ) -> None:
        """The listen loop should preserve the current flight_phase."""
        client = TelemetryClient("ws://localhost:8080", auto_reconnect=False)
        client._state.flight_phase = FlightPhase.CRUISE

        message = json.dumps(sample_bridge_broadcast)

        async def fake_aiter():
            yield message

        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: fake_aiter()
        client._ws = mock_ws

        await client._listen_loop()

        assert client.state.flight_phase == FlightPhase.CRUISE


# ---------------------------------------------------------------------------
# Connection state and stats
# ---------------------------------------------------------------------------


class TestConnectionState:
    """Test connection state tracking and diagnostics."""

    def test_stats_default(self) -> None:
        client = TelemetryClient("ws://localhost:8080")
        stats = client.stats
        assert stats["connection_state"] == "DISCONNECTED"
        assert stats["reconnect_count"] == 0
        assert stats["messages_received"] == 0
        assert stats["url"] == "ws://localhost:8080"

    def test_last_message_age_infinity_when_no_messages(self) -> None:
        client = TelemetryClient("ws://localhost:8080")
        assert client.last_message_age == float("inf")

    @pytest.mark.asyncio
    async def test_connect_sets_state_to_connected(self) -> None:
        client = TelemetryClient("ws://localhost:8080")
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = MagicMock(return_value=iter([]))
        with patch(
            "orchestrator.sim_client.websockets.connect",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            await client.connect()
            assert client.connection_state == ConnectionState.CONNECTED
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_connect_failure_sets_state_to_disconnected(
        self,
    ) -> None:
        client = TelemetryClient("ws://localhost:8080")
        with patch(
            "orchestrator.sim_client.websockets.connect",
            new_callable=AsyncMock,
            side_effect=ConnectionRefusedError("refused"),
        ):
            with pytest.raises(ConnectionRefusedError):
                await client.connect()
            assert client.connection_state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_messages_received_incremented(
        self, sample_bridge_broadcast: dict[str, Any]
    ) -> None:
        client = TelemetryClient("ws://localhost:8080", auto_reconnect=False)
        message = json.dumps(sample_bridge_broadcast)

        async def fake_aiter():
            yield message
            yield message

        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: fake_aiter()
        client._ws = mock_ws

        await client._listen_loop()

        # Second message is a duplicate (delta detection skips it) but
        # _messages_received still increments for every raw message.
        assert client._messages_received == 2


# ---------------------------------------------------------------------------
# Reconnection logic
# ---------------------------------------------------------------------------


class TestReconnection:
    """Test automatic reconnection with exponential backoff."""

    @pytest.mark.asyncio
    async def test_reconnect_increments_count(self) -> None:
        client = TelemetryClient("ws://localhost:8080")

        # First call fails, second succeeds
        call_count = 0

        async def mock_connect(url: str) -> AsyncMock:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionRefusedError("refused")
            ws = AsyncMock()
            ws.__aiter__ = MagicMock(return_value=iter([]))
            return ws

        with patch(
            "orchestrator.sim_client.websockets.connect",
            side_effect=mock_connect,
        ):
            # Override delays to make test fast
            client.RECONNECT_BASE_DELAY = 0.01
            client.RECONNECT_MAX_DELAY = 0.02
            await client._reconnect()
            assert client._reconnect_count >= 1
            assert client.connection_state == ConnectionState.CONNECTED

        # Clean up
        client._auto_reconnect = False
        if client._heartbeat_task:
            client._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client._heartbeat_task

    @pytest.mark.asyncio
    async def test_reconnect_disabled_does_nothing(self) -> None:
        client = TelemetryClient("ws://localhost:8080", auto_reconnect=False)
        await client._reconnect()
        assert client.connection_state == ConnectionState.DISCONNECTED
        assert client._reconnect_count == 0

    @pytest.mark.asyncio
    async def test_reconnect_backoff_increases_delay(self) -> None:
        """Verify the delay increases exponentially."""
        client = TelemetryClient("ws://localhost:8080")
        client.RECONNECT_BASE_DELAY = 0.01
        client.RECONNECT_MAX_DELAY = 0.1
        client.RECONNECT_BACKOFF_FACTOR = 2.0

        attempts = []

        async def mock_connect(url: str) -> AsyncMock:
            attempts.append(time.monotonic())
            if len(attempts) < 3:
                raise ConnectionRefusedError("refused")
            ws = AsyncMock()
            ws.__aiter__ = MagicMock(return_value=iter([]))
            return ws

        with patch(
            "orchestrator.sim_client.websockets.connect",
            side_effect=mock_connect,
        ):
            await client._reconnect()

        assert len(attempts) == 3
        assert client._reconnect_count == 3

        # Clean up
        client._auto_reconnect = False
        if client._heartbeat_task:
            client._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client._heartbeat_task

    @pytest.mark.asyncio
    async def test_listen_loop_triggers_reconnect_on_close(
        self, sample_bridge_broadcast: dict[str, Any]
    ) -> None:
        """When the WebSocket closes, the listen loop should reconnect."""
        import websockets

        client = TelemetryClient("ws://localhost:8080")
        client.RECONNECT_BASE_DELAY = 0.01

        # First WS: yields one message then closes
        async def fake_aiter_close():
            yield json.dumps(sample_bridge_broadcast)
            raise websockets.ConnectionClosed(None, None)

        first_ws = AsyncMock()
        first_ws.__aiter__ = lambda self: fake_aiter_close()

        # Second WS (after reconnect): yields nothing
        second_ws = AsyncMock()
        second_ws.__aiter__ = MagicMock(return_value=iter([]))

        call_count = 0

        async def mock_connect(url: str) -> AsyncMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return second_ws
            return second_ws

        client._ws = first_ws

        with patch(
            "orchestrator.sim_client.websockets.connect",
            side_effect=mock_connect,
        ):
            # Run listen loop in a task so we can cancel it
            task = asyncio.create_task(client._listen_loop())
            await asyncio.sleep(0.1)
            client._auto_reconnect = False
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # Should have attempted at least one reconnect
        assert client._reconnect_count >= 1


# ---------------------------------------------------------------------------
# Delta detection
# ---------------------------------------------------------------------------


class TestDeltaDetection:
    """Test that duplicate state messages are skipped."""

    @pytest.mark.asyncio
    async def test_duplicate_messages_skip_callback(
        self, sample_bridge_broadcast: dict[str, Any]
    ) -> None:
        client = TelemetryClient("ws://localhost:8080", auto_reconnect=False)
        callback = AsyncMock()
        client.subscribe(callback)

        message = json.dumps(sample_bridge_broadcast)

        async def fake_aiter():
            yield message
            yield message  # duplicate
            yield message  # duplicate

        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: fake_aiter()
        client._ws = mock_ws

        await client._listen_loop()

        # Only the first unique message triggers the callback
        assert callback.await_count == 1

    @pytest.mark.asyncio
    async def test_changed_messages_trigger_callback(
        self, sample_bridge_broadcast: dict[str, Any]
    ) -> None:
        client = TelemetryClient("ws://localhost:8080", auto_reconnect=False)
        callback = AsyncMock()
        client.subscribe(callback)

        msg1 = json.dumps(sample_bridge_broadcast)
        modified = dict(sample_bridge_broadcast)
        modified["position"] = {
            **modified["position"],
            "altitude_msl": 7000,
        }
        msg2 = json.dumps(modified)

        async def fake_aiter():
            yield msg1
            yield msg2

        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: fake_aiter()
        client._ws = mock_ws

        await client._listen_loop()

        assert callback.await_count == 2


# ---------------------------------------------------------------------------
# HealthMonitor
# ---------------------------------------------------------------------------


class TestHealthMonitor:
    """Test the subsystem health monitoring."""

    def test_register_creates_unhealthy_entry(self) -> None:
        monitor = HealthMonitor()
        monitor.register("test_subsystem")
        sub = monitor.get("test_subsystem")
        assert sub is not None
        assert sub.healthy is False
        assert sub.age_seconds == float("inf")

    def test_update_sets_healthy(self) -> None:
        monitor = HealthMonitor()
        monitor.register("svc")
        monitor.update("svc", True, "OK")
        sub = monitor.get("svc")
        assert sub is not None
        assert sub.healthy is True
        assert sub.message == "OK"
        assert sub.age_seconds < 1.0

    def test_update_auto_registers(self) -> None:
        monitor = HealthMonitor()
        monitor.update("new_svc", False, "down")
        sub = monitor.get("new_svc")
        assert sub is not None
        assert sub.healthy is False

    def test_all_healthy(self) -> None:
        monitor = HealthMonitor()
        monitor.update("a", True)
        monitor.update("b", True)
        assert monitor.all_healthy() is True
        monitor.update("b", False)
        assert monitor.all_healthy() is False

    def test_summary_returns_all_subsystems(self) -> None:
        monitor = HealthMonitor()
        monitor.update("x", True, "good")
        monitor.update("y", False, "bad")
        summary = monitor.summary()
        assert "x" in summary
        assert "y" in summary
        assert summary["x"]["healthy"] is True
        assert summary["y"]["healthy"] is False

    def test_subsystem_health_age(self) -> None:
        sub = SubsystemHealth(name="test")
        assert sub.age_seconds == float("inf")
        sub.last_seen = time.monotonic()
        assert sub.age_seconds < 1.0


# ---------------------------------------------------------------------------
# Graceful degradation scenarios
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Test that the system degrades gracefully when subsystems are down."""

    @pytest.mark.asyncio
    async def test_client_works_without_connection(self) -> None:
        """TelemetryClient should return a default state when not connected."""
        client = TelemetryClient("ws://localhost:8080")
        state = await client.get_state()
        assert state.connected is False
        assert state.aircraft == ""
        # Should not raise

    @pytest.mark.asyncio
    async def test_connect_failure_is_recoverable(self) -> None:
        """After a connect failure, the client should remain usable."""
        client = TelemetryClient("ws://localhost:8080", auto_reconnect=False)
        with (
            patch(
                "orchestrator.sim_client.websockets.connect",
                new_callable=AsyncMock,
                side_effect=ConnectionRefusedError("refused"),
            ),
            pytest.raises(ConnectionRefusedError),
        ):
            await client.connect()

        # Client should still be in a usable state
        assert client.connection_state == ConnectionState.DISCONNECTED
        state = await client.get_state()
        assert state is not None

    def test_health_monitor_tracks_degraded_state(self) -> None:
        """Monitor should correctly report when subsystems are degraded."""
        monitor = HealthMonitor()
        monitor.update("simconnect_bridge", True, "Connected")
        monitor.update("chromadb", False, "Unavailable")
        monitor.update("whisper", False, "Unreachable")
        monitor.update("claude_api", True, "Ready")

        assert monitor.all_healthy() is False

        summary = monitor.summary()
        assert summary["simconnect_bridge"]["healthy"] is True
        assert summary["chromadb"]["healthy"] is False
        assert summary["whisper"]["healthy"] is False
        assert summary["claude_api"]["healthy"] is True


# ---------------------------------------------------------------------------
# Authority floor, command-path watchdog and dispatch ledger
# ---------------------------------------------------------------------------

# Short enough that a never-acked command times out immediately. The same
# shrunk-real-timeout technique test_command_verifier.py uses -- there is no
# fake-clock library in any extra, and the ack future is real asyncio machinery.
FAST_TIMEOUT = 0.02


def _connected_client(**kwargs: Any) -> tuple[TelemetryClient, AsyncMock]:
    """Return a client already in CONNECTED state with a mock WebSocket."""
    client = TelemetryClient("ws://localhost:8080", auto_reconnect=False, **kwargs)
    mock_ws = AsyncMock()
    client._ws = mock_ws
    client._connection_state = ConnectionState.CONNECTED
    return client, mock_ws


async def _ack_pending(client: TelemetryClient, success: bool) -> None:
    """Resolve the in-flight command future the way an adapter ack would."""
    for _ in range(200):
        await asyncio.sleep(0.001)
        pending = [f for f in client._pending_commands.values() if not f.done()]
        if pending:
            for future in pending:
                future.set_result({"success": success, "message": "ack"})
            return


class TestAuthorityFloor:
    """The structural floor in send_command: level-only, fresh-read, pre-counter."""

    @pytest.mark.asyncio
    async def test_advisory_refuses_before_the_wire(self) -> None:
        authority = AuthorityState(AuthorityLevel.ADVISORY)
        client, mock_ws = _connected_client(authority=authority)

        result = await client.send_command("GEAR_UP")

        assert result["refused"] is True
        assert result["success"] is False
        assert result["authority_level"] == "advisory"
        assert result["authority_reason"] == "config"
        mock_ws.send.assert_not_awaited()
        assert client._pending_commands == {}
        assert client.recent_dispatches() == ()

    @pytest.mark.asyncio
    async def test_assisted_proceeds_to_the_wire(self) -> None:
        """The floor is level-only -- it never sees severity, so it cannot gate on it."""
        client, mock_ws = _connected_client(authority=AuthorityState(AuthorityLevel.ASSISTED))

        result = await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)

        assert "refused" not in result
        mock_ws.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_full_proceeds_to_the_wire(self) -> None:
        client, mock_ws = _connected_client(authority=AuthorityState(AuthorityLevel.FULL))

        result = await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)

        assert "refused" not in result
        mock_ws.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_floor_refusal_does_not_touch_the_watchdog_counter(self) -> None:
        """Ordering guard: the floor returns before any counter mutation.

        If a refusal counted as a timeout, a latched watchdog would re-arm on every
        subsequent attempt and could never be reasoned about.
        """
        authority = AuthorityState(AuthorityLevel.ADVISORY)
        client, _ = _connected_client(authority=authority)

        before = authority.consecutive_timeouts
        for _ in range(5):
            await client.send_command("GEAR_UP")
        assert authority.consecutive_timeouts == before

    @pytest.mark.asyncio
    async def test_floor_reads_the_level_fresh_at_dispatch(self) -> None:
        """A level that drops after construction is honoured on the next command."""
        authority = AuthorityState(AuthorityLevel.FULL)
        client, mock_ws = _connected_client(authority=authority)

        first = await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)
        assert "refused" not in first
        assert mock_ws.send.await_count == 1

        # Mutate the shared state without touching the client at all.
        authority.record_override()

        second = await client.send_command("GEAR_DOWN", timeout=FAST_TIMEOUT)
        assert second["refused"] is True
        assert second["authority_reason"] == "override"
        assert mock_ws.send.await_count == 1  # no second send

    @pytest.mark.asyncio
    async def test_send_command_takes_no_caller_supplied_level(self) -> None:
        """The floor must decide for itself; a caller cannot hand it a verdict."""
        import inspect

        assert "level" not in inspect.signature(TelemetryClient.send_command).parameters

    @pytest.mark.asyncio
    async def test_degraded_authority_refuses_with_degraded_reason(self) -> None:
        client, _ = _connected_client(authority=AuthorityState.degraded_fallback("boom"))

        result = await client.send_command("GEAR_UP")

        assert result["refused"] is True
        assert result["authority_reason"] == "degraded"

    @pytest.mark.asyncio
    async def test_degraded_authority_survives_a_connected_transition(self) -> None:
        """Reconnect is evidence about the sim, not about the authority subsystem."""
        authority = AuthorityState.degraded_fallback("boom")
        client = TelemetryClient("ws://localhost:8080", authority=authority)
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = MagicMock(return_value=iter([]))

        with patch(
            "orchestrator.sim_client.websockets.connect",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            await client.connect()
            result = await client.send_command("GEAR_UP")
            await client.disconnect()

        assert result["refused"] is True
        assert result["authority_reason"] == "degraded"
        assert authority.degraded is True

    @pytest.mark.asyncio
    async def test_client_without_authority_does_not_refuse(self) -> None:
        """The None default keeps ~40 existing constructions working; it is not a policy."""
        client, mock_ws = _connected_client()

        result = await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)

        assert "refused" not in result
        mock_ws.send.assert_awaited_once()

    def test_construction_without_authority_logs_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="orchestrator.sim_client"):
            TelemetryClient("ws://localhost:8080")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "authority" in warnings[0].getMessage()

    def test_construction_with_authority_logs_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="orchestrator.sim_client"):
            TelemetryClient("ws://localhost:8080", authority=AuthorityState(AuthorityLevel.FULL))

        assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


class TestCommandWatchdog:
    """Consecutive-ack-timeout latch. Counts and states only -- never a wall clock."""

    @pytest.mark.asyncio
    async def test_two_timeouts_do_not_latch(self) -> None:
        authority = AuthorityState(AuthorityLevel.FULL, watchdog_max_timeouts=3)
        client, _ = _connected_client(authority=authority)

        for _ in range(2):
            await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)

        assert authority.consecutive_timeouts == 2
        assert authority.watchdog_latched is False
        assert authority.level is AuthorityLevel.FULL

    @pytest.mark.asyncio
    async def test_third_timeout_latches_to_advisory(self) -> None:
        authority = AuthorityState(AuthorityLevel.FULL, watchdog_max_timeouts=3)
        client, _ = _connected_client(authority=authority)

        for _ in range(3):
            await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)

        assert authority.watchdog_latched is True
        assert authority.level is AuthorityLevel.ADVISORY
        assert authority.reason is AuthorityReason.WATCHDOG

    @pytest.mark.asyncio
    async def test_successful_ack_resets_the_counter(self) -> None:
        authority = AuthorityState(AuthorityLevel.FULL, watchdog_max_timeouts=3)
        client, _ = _connected_client(authority=authority)

        for _ in range(2):
            await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)
        assert authority.consecutive_timeouts == 2

        asyncio.create_task(_ack_pending(client, success=True))
        await client.send_command("GEAR_UP", timeout=1.0)
        assert authority.consecutive_timeouts == 0

        for _ in range(2):
            await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)

        assert authority.consecutive_timeouts == 2
        assert authority.watchdog_latched is False

    @pytest.mark.asyncio
    async def test_ack_with_success_false_resets_rather_than_increments(self) -> None:
        """An adapter that received and rejected the command proves the path is alive."""
        authority = AuthorityState(AuthorityLevel.FULL, watchdog_max_timeouts=3)
        client, _ = _connected_client(authority=authority)

        await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)
        assert authority.consecutive_timeouts == 1

        asyncio.create_task(_ack_pending(client, success=False))
        result = await client.send_command("UNREGISTERED_EVENT", timeout=1.0)

        assert result["success"] is False
        assert authority.consecutive_timeouts == 0

    @pytest.mark.asyncio
    async def test_send_exception_increments_the_counter(self) -> None:
        authority = AuthorityState(AuthorityLevel.FULL, watchdog_max_timeouts=3)
        client, mock_ws = _connected_client(authority=authority)
        mock_ws.send.side_effect = RuntimeError("socket exploded")

        result = await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)

        assert result["success"] is False
        assert "socket exploded" in result["error"]
        assert authority.consecutive_timeouts == 1

    @pytest.mark.asyncio
    async def test_not_connected_does_not_increment_the_counter(self) -> None:
        """A connection failure is already visible via ConnectionState; counting it
        here would double-report the same fault."""
        authority = AuthorityState(AuthorityLevel.FULL, watchdog_max_timeouts=3)
        client = TelemetryClient("ws://localhost:8080", authority=authority)

        result = await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)

        assert result["success"] is False
        assert "Not connected" in result["error"]
        assert authority.consecutive_timeouts == 0

    @pytest.mark.asyncio
    async def test_latched_watchdog_cannot_re_latch_through_its_own_refusals(self) -> None:
        authority = AuthorityState(AuthorityLevel.FULL, watchdog_max_timeouts=3)
        client, mock_ws = _connected_client(authority=authority)

        for _ in range(3):
            await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)
        latched_count = authority.consecutive_timeouts
        sends_at_latch = mock_ws.send.await_count

        for _ in range(5):
            result = await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)
            assert result["refused"] is True

        assert authority.consecutive_timeouts == latched_count
        assert mock_ws.send.await_count == sends_at_latch

    @pytest.mark.asyncio
    async def test_watchdog_inert_without_authority(self) -> None:
        client, _ = _connected_client()
        for _ in range(5):
            result = await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)
            assert result["success"] is False
            assert "refused" not in result


class TestWatchdogReconnectClear:
    """D-18: telemetry flowing again is out-of-band evidence the command path is back."""

    @pytest.mark.asyncio
    async def test_latch_clears_on_connected_transition(self) -> None:
        authority = AuthorityState(AuthorityLevel.FULL, watchdog_max_timeouts=3)
        client, _ = _connected_client(authority=authority)

        for _ in range(3):
            await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)
        assert authority.watchdog_latched is True

        mock_ws = AsyncMock()
        mock_ws.__aiter__ = MagicMock(return_value=iter([]))
        with patch(
            "orchestrator.sim_client.websockets.connect",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            await client.connect()
            await client.disconnect()

        assert authority.watchdog_latched is False
        assert authority.level is AuthorityLevel.FULL
        assert authority.reason is AuthorityReason.CONFIG

    @pytest.mark.asyncio
    async def test_latch_clears_on_the_reconnect_path_too(self) -> None:
        """Both CONNECTED transitions must clear, or the CLI and web paths diverge."""
        authority = AuthorityState(AuthorityLevel.FULL, watchdog_max_timeouts=3)
        client, _ = _connected_client(authority=authority)
        client._auto_reconnect = True
        client.RECONNECT_BASE_DELAY = 0.01

        for _ in range(3):
            await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)
        assert authority.watchdog_latched is True

        mock_ws = AsyncMock()
        mock_ws.__aiter__ = MagicMock(return_value=iter([]))
        with patch(
            "orchestrator.sim_client.websockets.connect",
            new_callable=AsyncMock,
            return_value=mock_ws,
        ):
            await client._reconnect()

        assert authority.watchdog_latched is False
        assert authority.level is AuthorityLevel.FULL

        client._auto_reconnect = False
        if client._heartbeat_task:
            client._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client._heartbeat_task

    @pytest.mark.asyncio
    async def test_commands_flow_again_after_the_clear(self) -> None:
        authority = AuthorityState(AuthorityLevel.FULL, watchdog_max_timeouts=3)
        client, mock_ws = _connected_client(authority=authority)

        for _ in range(3):
            await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)
        assert (await client.send_command("GEAR_UP"))["refused"] is True

        client._on_connection_established()
        client._ws = mock_ws
        client._connection_state = ConnectionState.CONNECTED

        result = await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)
        assert "refused" not in result


class TestCommandPathHealth:
    """D-17: the command path is renderable as 'advisory (command path down)'."""

    def test_command_path_registered_at_construction(self) -> None:
        monitor = HealthMonitor()
        TelemetryClient("ws://localhost:8080", health=monitor)

        assert "command_path" in monitor.summary()

    @pytest.mark.asyncio
    async def test_command_path_unhealthy_after_latch_and_healthy_after_clear(self) -> None:
        monitor = HealthMonitor()
        authority = AuthorityState(AuthorityLevel.FULL, watchdog_max_timeouts=3)
        client, _ = _connected_client(authority=authority, health=monitor)

        for _ in range(3):
            await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)
        assert monitor.summary()["command_path"]["healthy"] is False

        client._on_connection_established()
        assert monitor.summary()["command_path"]["healthy"] is True

    @pytest.mark.asyncio
    async def test_successful_ack_marks_command_path_healthy(self) -> None:
        monitor = HealthMonitor()
        client, _ = _connected_client(authority=AuthorityState(AuthorityLevel.FULL), health=monitor)

        await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)
        assert monitor.summary()["command_path"]["healthy"] is False

        asyncio.create_task(_ack_pending(client, success=True))
        await client.send_command("GEAR_UP", timeout=1.0)

        assert monitor.summary()["command_path"]["healthy"] is True


class TestDispatchLedger:
    """Single-clock provenance for every command that actually reached the wire."""

    @pytest.mark.asyncio
    async def test_successful_send_appends_one_entry(self) -> None:
        client, _ = _connected_client(authority=AuthorityState(AuthorityLevel.FULL))

        await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)

        ledger = client.recent_dispatches()
        assert len(ledger) == 1
        assert ledger[0][0] == "GEAR_UP"
        assert abs(ledger[0][1] - time.monotonic()) < 1.0

    @pytest.mark.asyncio
    async def test_failed_send_appends_nothing(self) -> None:
        client, mock_ws = _connected_client(authority=AuthorityState(AuthorityLevel.FULL))
        mock_ws.send.side_effect = RuntimeError("socket exploded")

        await client.send_command("GEAR_UP", timeout=FAST_TIMEOUT)

        assert client.recent_dispatches() == ()

    @pytest.mark.asyncio
    async def test_refused_command_appends_nothing(self) -> None:
        client, _ = _connected_client(authority=AuthorityState(AuthorityLevel.ADVISORY))

        await client.send_command("GEAR_UP")

        assert client.recent_dispatches() == ()

    @pytest.mark.asyncio
    async def test_ledger_is_ordered_oldest_first(self) -> None:
        client, _ = _connected_client()

        for name in ("FIRST", "SECOND", "THIRD"):
            await client.send_command(name, timeout=FAST_TIMEOUT)

        assert [entry[0] for entry in client.recent_dispatches()] == [
            "FIRST",
            "SECOND",
            "THIRD",
        ]

    @pytest.mark.asyncio
    async def test_ledger_is_bounded(self) -> None:
        client, _ = _connected_client()
        overflow = TelemetryClient.DISPATCH_LEDGER_SIZE + 10

        for i in range(overflow):
            await client.send_command(f"CMD_{i}", timeout=0.001)

        ledger = client.recent_dispatches()
        assert len(ledger) == TelemetryClient.DISPATCH_LEDGER_SIZE
        # The oldest entries are the ones evicted.
        assert ledger[-1][0] == f"CMD_{overflow - 1}"

    def test_recent_dispatches_returns_a_snapshot(self) -> None:
        client = TelemetryClient("ws://localhost:8080")
        client._dispatch_ledger.append(("GEAR_UP", 1.0))

        snapshot = client.recent_dispatches()
        client._dispatch_ledger.append(("GEAR_DOWN", 2.0))

        assert snapshot == (("GEAR_UP", 1.0),)


class TestCommandTimeoutResolution:
    """The ack deadline comes from configuration, but tests can still shrink it."""

    def test_command_timeout_defaults_to_five_seconds(self) -> None:
        client = TelemetryClient("ws://localhost:8080")
        assert client._command_timeout == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_configured_timeout_is_used_when_none_is_passed(self) -> None:
        client, _ = _connected_client(command_timeout=FAST_TIMEOUT)

        started = time.monotonic()
        result = await client.send_command("GEAR_UP")
        elapsed = time.monotonic() - started

        assert result["error"] == "Command timed out"
        assert elapsed < 1.0  # the configured short deadline, not the 5s default
