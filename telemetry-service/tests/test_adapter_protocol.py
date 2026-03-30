"""Tests for adapter protocol message types and parsers."""

from __future__ import annotations

import pytest

from telemetry.adapter_protocol import (
    AdapterCommandAck,
    ConsumerCommand,
    ServiceCommand,
    ServiceCommandAck,
    parse_adapter_message,
    parse_consumer_message,
)


class TestParseAdapterMessage:
    def test_parse_command_ack(self) -> None:
        data = {
            "type": "command_ack",
            "command_id": "abc-123",
            "success": True,
            "message": "FLAPS_2 executed",
        }
        msg = parse_adapter_message(data)
        assert isinstance(msg, AdapterCommandAck)
        assert msg.command_id == "abc-123"
        assert msg.success is True
        assert msg.message == "FLAPS_2 executed"

    def test_parse_unknown_type_returns_none(self) -> None:
        assert parse_adapter_message({"type": "bogus"}) is None


class TestParseConsumerMessage:
    def test_parse_consumer_command(self) -> None:
        data = {
            "type": "command",
            "command_id": "cmd-456",
            "adapter_id": "msfs-adapter",
            "command": "GEAR_DOWN",
            "value": 0,
        }
        msg = parse_consumer_message(data)
        assert isinstance(msg, ConsumerCommand)
        assert msg.command_id == "cmd-456"
        assert msg.adapter_id == "msfs-adapter"
        assert msg.command == "GEAR_DOWN"
        assert msg.value == 0

    def test_parse_unknown_type_returns_none(self) -> None:
        assert parse_consumer_message({"type": "bogus"}) is None


class TestMessageSerialization:
    def test_consumer_command_roundtrip(self) -> None:
        original = ConsumerCommand(
            command_id="id-1",
            adapter_id="msfs-adapter",
            command="FLAPS_SET",
            value=8191,
        )
        dumped = original.model_dump()
        restored = ConsumerCommand.model_validate(dumped)
        assert restored.command_id == original.command_id
        assert restored.adapter_id == original.adapter_id
        assert restored.command == original.command
        assert restored.value == original.value
        assert dumped["type"] == "command"

    def test_service_command_roundtrip(self) -> None:
        original = ServiceCommand(
            command_id="id-2",
            command="THROTTLE_SET",
            value=12287,
        )
        dumped = original.model_dump()
        restored = ServiceCommand.model_validate(dumped)
        assert restored.command_id == original.command_id
        assert restored.command == original.command
        assert restored.value == original.value
        assert dumped["type"] == "command"

    def test_adapter_command_ack_roundtrip(self) -> None:
        original = AdapterCommandAck(
            command_id="id-3",
            success=False,
            message="SimConnect error",
        )
        dumped = original.model_dump()
        restored = AdapterCommandAck.model_validate(dumped)
        assert restored.command_id == original.command_id
        assert restored.success is False
        assert restored.message == "SimConnect error"
        assert dumped["type"] == "command_ack"
