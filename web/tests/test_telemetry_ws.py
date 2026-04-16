"""WebSocket telemetry proxy tests for the MERLIN web server.

Covers:
- WTST-06: /ws/telemetry forwards upstream telemetry and handles disconnect
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import httpx
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

# ---------------------------------------------------------------------------
# Fake upstream WebSocket
# ---------------------------------------------------------------------------


class _FakeUpstreamWS:
    """Minimal async context manager + async iterable stand-in for
    ``websockets.connect``'s return value.

    Yields a finite list of JSON strings then raises ``StopAsyncIteration``
    so the ``async for`` loop in ``ws_telemetry`` exits cleanly and the
    outer reconnect loop re-enters (the test disconnects before that
    matters).
    """

    def __init__(self, messages):
        self._messages = list(messages)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            # Yield control briefly so the handler has time to send out
            # everything before we simulate the upstream closing.
            await asyncio.sleep(0.05)
            raise StopAsyncIteration
        return self._messages.pop(0)


# ---------------------------------------------------------------------------
# WTST-06: Proxy forwards upstream telemetry
# ---------------------------------------------------------------------------


async def test_telemetry_proxy_forwards_data(test_app, mock_app_state):
    """Mocked upstream telemetry should be forwarded to the browser client."""

    telemetry_payload = {
        "connected": True,
        "position": {"lat": 47.45, "lon": -122.31, "alt_ft": 1200.0},
        "airspeed_kts": 98.5,
    }
    fake_upstream = _FakeUpstreamWS([json.dumps(telemetry_payload)])

    def _fake_connect(url, *args, **kwargs):  # noqa: ARG001
        return fake_upstream

    transport = ASGIWebSocketTransport(app=test_app)
    with patch("web.server.ws_lib.connect", side_effect=_fake_connect):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            async with aconnect_ws("http://test/ws/telemetry", client) as ws:
                # 1. Initial "not yet confirmed" frame
                first = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                assert first["type"] == "telemetry"
                assert first["connected"] is False
                assert first["data"] is None

                # 2. Proxied telemetry frame from upstream
                second = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                assert second["type"] == "telemetry"
                assert second["connected"] is True
                assert second["data"]["airspeed_kts"] == 98.5
                assert second["data"]["position"]["lat"] == 47.45


async def test_telemetry_proxy_handles_upstream_failure(test_app, mock_app_state):
    """If the upstream connect fails, the client still receives a fallback frame."""

    def _raise(url, *args, **kwargs):  # noqa: ARG001
        raise ConnectionRefusedError("upstream offline")

    transport = ASGIWebSocketTransport(app=test_app)
    with patch("web.server.ws_lib.connect", side_effect=_raise):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            async with aconnect_ws("http://test/ws/telemetry", client) as ws:
                frame = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                assert frame["type"] == "telemetry"
                assert frame["connected"] is False
                assert frame["data"] is None
