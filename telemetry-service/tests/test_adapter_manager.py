"""Tests for the adapter manager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from telemetry.adapter_manager import AdapterManager
from telemetry.schema import Position, TelemetryEnvelope


def _mock_ws() -> MagicMock:
    """Create a mock WebSocket that supports async send."""
    ws = MagicMock()
    ws.send_text = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


class TestAdapterRegistration:
    @pytest.mark.asyncio
    async def test_register_adapter(self):
        mgr = AdapterManager()
        ws = _mock_ws()
        ack = await mgr.register_adapter(ws, "msfs-1", "msfs2024", "aircraft")
        assert ack.accepted is True
        assert ack.adapter_id == "msfs-1"
        assert mgr.adapter_count == 1

    @pytest.mark.asyncio
    async def test_register_replaces_existing(self):
        mgr = AdapterManager()
        ws1 = _mock_ws()
        ws2 = _mock_ws()
        await mgr.register_adapter(ws1, "msfs-1", "msfs2024", "aircraft")
        await mgr.register_adapter(ws2, "msfs-1", "msfs2024", "aircraft")
        assert mgr.adapter_count == 1

    @pytest.mark.asyncio
    async def test_unregister_adapter(self):
        mgr = AdapterManager()
        ws = _mock_ws()
        await mgr.register_adapter(ws, "msfs-1", "msfs2024", "aircraft")
        await mgr.unregister_adapter("msfs-1")
        assert mgr.adapter_count == 0

    @pytest.mark.asyncio
    async def test_unregister_nonexistent(self):
        mgr = AdapterManager()
        await mgr.unregister_adapter("nope")  # should not raise


class TestTelemetryUpdate:
    @pytest.mark.asyncio
    async def test_update_stores_state(self):
        mgr = AdapterManager()
        ws = _mock_ws()
        await mgr.register_adapter(ws, "msfs-1", "msfs2024", "aircraft")

        envelope = TelemetryEnvelope(
            adapter_id="msfs-1",
            connected=True,
            position=Position(latitude=47.0),
        )
        await mgr.update_telemetry("msfs-1", envelope)

        current = mgr.get_current_state()
        assert current is not None
        assert current.position is not None
        assert current.position.latitude == 47.0

    @pytest.mark.asyncio
    async def test_update_from_unknown_adapter(self):
        mgr = AdapterManager()
        envelope = TelemetryEnvelope(adapter_id="unknown")
        # Should log warning but not raise
        await mgr.update_telemetry("unknown", envelope)
        assert mgr.get_current_state() is None


class TestConsumerBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast_to_consumer(self):
        mgr = AdapterManager()
        ws_adapter = _mock_ws()
        ws_consumer = _mock_ws()

        await mgr.register_adapter(ws_adapter, "msfs-1", "msfs2024", "aircraft")
        consumer = await mgr.add_consumer(ws_consumer)

        envelope = TelemetryEnvelope(
            adapter_id="msfs-1",
            connected=True,
            timestamp="2026-01-01T00:00:00Z",
            vehicle_name="C172",
            position=Position(latitude=47.0),
        )
        await mgr.update_telemetry("msfs-1", envelope)

        ws_consumer.send_text.assert_called_once()
        assert consumer.messages_sent == 1

    @pytest.mark.asyncio
    async def test_filtered_broadcast(self):
        mgr = AdapterManager()
        ws_adapter = _mock_ws()
        ws_consumer = _mock_ws()

        await mgr.register_adapter(ws_adapter, "msfs-1", "msfs2024", "aircraft")
        consumer = await mgr.add_consumer(ws_consumer)
        mgr.set_consumer_subscription(consumer, ["position"])

        envelope = TelemetryEnvelope(
            adapter_id="msfs-1",
            connected=True,
            timestamp="2026-01-01T00:00:00Z",
            position=Position(latitude=47.0),
        )
        await mgr.update_telemetry("msfs-1", envelope)

        ws_consumer.send_text.assert_called_once()
        import json

        sent_data = json.loads(ws_consumer.send_text.call_args[0][0])
        assert "position" in sent_data
        assert "speeds" not in sent_data


class TestActiveAdapters:
    @pytest.mark.asyncio
    async def test_get_active_adapters(self):
        mgr = AdapterManager()
        ws = _mock_ws()
        await mgr.register_adapter(ws, "msfs-1", "msfs2024", "aircraft")

        adapters = mgr.get_active_adapters()
        assert len(adapters) == 1
        assert adapters[0]["adapter_id"] == "msfs-1"
        assert adapters[0]["sim_name"] == "msfs2024"

    @pytest.mark.asyncio
    async def test_stale_adapter_cleanup(self):
        mgr = AdapterManager(stale_timeout=0.01)
        ws = _mock_ws()
        await mgr.register_adapter(ws, "msfs-1", "msfs2024", "aircraft")

        await asyncio.sleep(0.05)
        await mgr.cleanup_stale_adapters()
        assert mgr.adapter_count == 0


class TestCommandRouting:
    @pytest.mark.asyncio
    async def test_send_command_to_adapter_success(self):
        mgr = AdapterManager()
        ws_adapter = _mock_ws()
        ws_consumer = _mock_ws()
        await mgr.register_adapter(ws_adapter, "msfs-1", "msfs2024", "aircraft")

        result = await mgr.send_command_to_adapter(
            adapter_id="msfs-1",
            command_id="cmd-001",
            command="FLAPS_2",
            value=0,
            consumer_ws=ws_consumer,
        )

        assert result is True
        ws_adapter.send_text.assert_called_once()
        import json

        sent = json.loads(ws_adapter.send_text.call_args[0][0])
        assert sent["type"] == "command"
        assert sent["command_id"] == "cmd-001"
        assert sent["command"] == "FLAPS_2"
        assert sent["value"] == 0

    @pytest.mark.asyncio
    async def test_send_command_to_unknown_adapter(self):
        mgr = AdapterManager()
        ws_consumer = _mock_ws()

        result = await mgr.send_command_to_adapter(
            adapter_id="nonexistent",
            command_id="cmd-002",
            command="GEAR_DOWN",
            value=0,
            consumer_ws=ws_consumer,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_route_command_ack(self):
        mgr = AdapterManager()
        ws_adapter = _mock_ws()
        ws_consumer = _mock_ws()
        await mgr.register_adapter(ws_adapter, "msfs-1", "msfs2024", "aircraft")

        # Send command to register pending ack
        await mgr.send_command_to_adapter(
            adapter_id="msfs-1",
            command_id="cmd-003",
            command="GEAR_DOWN",
            value=0,
            consumer_ws=ws_consumer,
        )

        # Route the ack back to consumer
        await mgr.route_command_ack("cmd-003", success=True, message="Gear extended")

        # Consumer should have received the ack (adapter send_text + consumer send_text)
        ws_consumer.send_text.assert_called_once()
        import json

        ack_data = json.loads(ws_consumer.send_text.call_args[0][0])
        assert ack_data["type"] == "command_ack"
        assert ack_data["command_id"] == "cmd-003"
        assert ack_data["success"] is True
        assert ack_data["message"] == "Gear extended"
