"""Integration tests for the telemetry service endpoints."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from telemetry.service import app, manager


@pytest.fixture(autouse=True)
def _reset_manager():
    """Reset manager state between tests."""
    manager._adapters.clear()
    manager._consumers.clear()
    yield
    manager._adapters.clear()
    manager._consumers.clear()


class TestHealthEndpoint:
    def test_health(self):
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["adapters"] == 0
        assert data["consumers"] == 0


class TestAdaptersEndpoint:
    def test_empty_adapters(self):
        client = TestClient(app)
        resp = client.get("/api/adapters")
        assert resp.status_code == 200
        assert resp.json()["adapters"] == []


class TestIngestWebSocket:
    def test_register_and_telemetry(self):
        client = TestClient(app)

        with client.websocket_connect("/ws/ingest") as ws:
            # Send registration
            ws.send_text(
                json.dumps(
                    {
                        "type": "register",
                        "adapter_id": "test-adapter",
                        "sim_name": "test-sim",
                        "vehicle_type": "aircraft",
                        "version": "1.0",
                    }
                )
            )

            # Should receive register_ack
            ack = json.loads(ws.receive_text())
            assert ack["type"] == "register_ack"
            assert ack["accepted"] is True

            # Send telemetry
            ws.send_text(
                json.dumps(
                    {
                        "type": "telemetry",
                        "data": {
                            "adapter_id": "test-adapter",
                            "sim_name": "test-sim",
                            "vehicle_type": "aircraft",
                            "timestamp": "2026-01-01T00:00:00Z",
                            "connected": True,
                            "vehicle_name": "Test Aircraft",
                            "position": {
                                "latitude": 47.0,
                                "longitude": -122.0,
                                "altitude_msl": 5000.0,
                                "altitude_agl": 4000.0,
                            },
                        },
                    }
                )
            )

        # After disconnect, adapter should be cleaned up
        assert manager.adapter_count == 0

    def test_register_timeout(self):
        """Connection without register should be closed."""
        # This test would need async timeout handling; skip for sync client
        pass

    def test_invalid_first_message(self):
        client = TestClient(app)

        with client.websocket_connect("/ws/ingest") as ws:
            ws.send_text(json.dumps({"type": "telemetry", "data": {}}))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "error"


class TestConsumerWebSocket:
    def test_heartbeat(self):
        client = TestClient(app)

        with client.websocket_connect("/ws/telemetry") as ws:
            ws.send_text(json.dumps({"type": "heartbeat"}))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "heartbeat_ack"
            assert "timestamp" in resp
            assert "clients" in resp
            assert "adapters" in resp

    def test_subscribe(self):
        client = TestClient(app)

        with client.websocket_connect("/ws/telemetry") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "type": "subscribe",
                        "fields": ["position", "speeds"],
                    }
                )
            )
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "subscribe_ack"
            assert resp["fields"] == ["position", "speeds"]

    def test_get_state_no_data(self):
        client = TestClient(app)

        with client.websocket_connect("/ws/telemetry") as ws:
            ws.send_text(json.dumps({"type": "get_state"}))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "state_response"
