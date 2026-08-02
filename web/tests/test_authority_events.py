"""Browser half of AUTH-06: authority announcements over ``/ws/chat``.

``OverrideDetector`` builds two ``ProactiveEvent`` announcements -- one when it
sees the pilot working a control MERLIN did not command, one when the override
cooldown lapses -- and puts them on a bounded queue. ``web/server.py``
constructed that queue, subscribed the detector to telemetry, and then never
read it (VERIFICATION Gap 3 / WR-06): the drop to advisory happened and nobody
told the pilot.

Covers:
- the ``authority_event`` wire frame, including the deliberate ``None``s when no
  ``AuthorityState`` exists -- inventing ``config`` there would report a crashed
  subsystem as an operator's own choice
- the fan-out: *every* registered socket receives the frame, rather than
  whichever one won a race for the queue
- a socket whose send raises is discarded and the remaining ones still receive it
- the pump survives a failing broadcast, returns quietly with no detector, and
  cancels without raising
- ``ws_chat`` registers on ``accept()`` and deregisters in a ``finally``
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport
from orchestrator.authority import AuthorityLevel, AuthorityState
from orchestrator.proactive_monitor import ProactiveEvent

# The finding this module exists to keep closed. Named in assertion messages so a
# future failure points at the gap rather than at a bare boolean.
_GAP3_REGRESSION = (
    "VERIFICATION Gap 3 / WR-06: OverrideDetector.events had no consumer on the "
    "browser path, so a pilot override dropped MERLIN to advisory and the browser "
    "was never told"
)

# ---------------------------------------------------------------------------
# Fixtures / doubles
# ---------------------------------------------------------------------------


def _override_event(fields: list[str] | None = None) -> ProactiveEvent:
    """The exact announcement ``OverrideDetector._record_override`` publishes."""
    return ProactiveEvent(
        type="authority",
        priority=1,
        message="You've taken the flaps. I'm advisory only until you're done.",
        data={"event": "override", "fields": fields or ["surfaces.flaps_percent"]},
    )


def _restore_event(level: str = "full") -> ProactiveEvent:
    """The exact announcement ``OverrideDetector._announce_restore`` publishes."""
    return ProactiveEvent(
        type="authority",
        priority=0,
        message=f"Back to {level} authority whenever you want me.",
        data={"event": "restore", "level": level},
    )


class _StubDetector:
    """Stands in for ``OverrideDetector``.

    The pump touches exactly one attribute, so the double supplies exactly one:
    a *real* ``asyncio.PriorityQueue``, because ordering and blocking-get
    semantics are part of what is under test here.
    """

    def __init__(self, queue: asyncio.PriorityQueue[ProactiveEvent] | None = None) -> None:
        self.events = queue if queue is not None else asyncio.PriorityQueue(maxsize=32)


def _fake_socket(*, fail: bool = False) -> MagicMock:
    """A stand-in chat socket whose only exercised method is ``send_json``.

    The fan-out and disconnect cases drive ``_broadcast_chat`` directly against
    these rather than over a real WebSocket: the behaviour under test is registry
    bookkeeping, and a real transport would add connection timing to a test that
    is not about connection timing.
    """
    ws = MagicMock()
    ws.send_json = AsyncMock(side_effect=RuntimeError("socket gone") if fail else None)
    return ws


async def _wait_for_clients(state, count: int, timeout: float = 2.0) -> None:
    """Block until ``state.chat_clients`` holds ``count`` sockets."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if len(state.chat_clients) == count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"expected {count} chat clients, saw {len(state.chat_clients)}")


# ---------------------------------------------------------------------------
# Frame shape
# ---------------------------------------------------------------------------


def test_override_frame_carries_the_message_event_and_fields():
    """The announcement reaches the wire as words, not as a colour."""
    import web.server as srv

    frame = srv._authority_event_frame(_override_event(), None)

    assert frame["type"] == "authority_event"
    assert frame["event"] == "override"
    assert frame["message"] == "You've taken the flaps. I'm advisory only until you're done."
    assert frame["fields"] == ["surfaces.flaps_percent"]
    assert frame["priority"] == 1


def test_restore_frame_is_distinguishable_from_an_override():
    """D-14's auto-restore rides the same channel and must not look like a drop."""
    import web.server as srv

    frame = srv._authority_event_frame(_restore_event(), None)

    assert frame["event"] == "restore"
    assert frame["priority"] == 0
    assert "Back to full authority" in frame["message"]


def test_frame_authority_fields_come_from_the_live_summary():
    """The badge must be able to move from the frame alone (IN-04).

    ``renderAuthority`` reads exactly ``authority_level``, ``authority_reason``
    and ``authority``; a frame missing any of the three sends the browser back to
    the 10 s poll it was meant to stop waiting on.
    """
    import web.server as srv

    authority = AuthorityState(AuthorityLevel.FULL)
    authority.record_override()

    frame = srv._authority_event_frame(_override_event(), authority)

    summary = authority.summary()
    assert frame["authority_level"] == summary["level"] == "advisory"
    assert frame["authority_reason"] == summary["reason"] == "override"
    assert frame["authority"]["configured_level"] == "full"
    assert frame["authority"]["cooldown_remaining_s"] > 0


def test_frame_with_no_authority_reports_none_rather_than_a_default():
    """A missing AuthorityState is not a deliberate ``full``/``config`` setup.

    Same rule ``_on_tool_result`` follows for ``command_advisory``: the level and
    reason are copied through or reported absent, never invented.
    """
    import web.server as srv

    frame = srv._authority_event_frame(_override_event(), None)

    assert frame["message"], "the announcement survives an absent AuthorityState"
    assert frame["authority_level"] is None
    assert frame["authority_reason"] is None
    assert frame["authority"] is None
    # Present-and-None, not absent: the browser branches on the key's type.
    assert "authority_level" in frame
    assert "authority_reason" in frame


# ---------------------------------------------------------------------------
# Fan-out
# ---------------------------------------------------------------------------


async def test_broadcast_reaches_every_registered_socket(mock_app_state):
    """Two tabs, one announcement, two deliveries."""
    import web.server as srv

    first, second = _fake_socket(), _fake_socket()
    mock_app_state.chat_clients.update({first, second})
    frame = srv._authority_event_frame(_override_event(), None)

    await srv._broadcast_chat(mock_app_state, frame)

    first.send_json.assert_awaited_once_with(frame)
    second.send_json.assert_awaited_once_with(frame)
    assert len(mock_app_state.chat_clients) == 2


async def test_a_failing_socket_is_discarded_and_the_others_still_receive(mock_app_state):
    """One dead tab cannot silence the announcement for a live one (T-02-15-02)."""
    import web.server as srv

    dead, alive = _fake_socket(fail=True), _fake_socket()
    mock_app_state.chat_clients.update({dead, alive})

    await srv._broadcast_chat(mock_app_state, {"type": "authority_event"})

    alive.send_json.assert_awaited_once()
    assert dead not in mock_app_state.chat_clients, (
        "a socket whose send raised must leave the registry (T-02-15-03)"
    )
    assert alive in mock_app_state.chat_clients


async def test_broadcast_does_not_raise_when_every_socket_is_dead(mock_app_state):
    """The pump's caller must never see a broadcast failure as an event failure."""
    import web.server as srv

    mock_app_state.chat_clients.update({_fake_socket(fail=True), _fake_socket(fail=True)})

    await srv._broadcast_chat(mock_app_state, {"type": "authority_event"})

    assert mock_app_state.chat_clients == set()


# ---------------------------------------------------------------------------
# The pump
# ---------------------------------------------------------------------------


async def test_pump_broadcasts_a_queued_announcement(mock_app_state):
    """The queue that shipped with no consumer now has one."""
    import web.server as srv

    detector = _StubDetector()
    mock_app_state.override_detector = detector
    mock_app_state.authority = AuthorityState(AuthorityLevel.FULL)
    sock = _fake_socket()
    mock_app_state.chat_clients.add(sock)

    task = asyncio.create_task(srv._authority_event_pump(mock_app_state))
    try:
        await detector.events.put(_override_event())
        for _ in range(200):
            if sock.send_json.await_count:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    sock.send_json.assert_awaited_once()
    frame = sock.send_json.await_args.args[0]
    assert frame["type"] == "authority_event", _GAP3_REGRESSION
    assert frame["event"] == "override"
    assert frame["authority_level"] == "full"


async def test_pump_returns_immediately_with_no_detector(mock_app_state):
    """The degrade-and-continue path in ``lifespan`` can leave it ``None``."""
    import web.server as srv

    mock_app_state.override_detector = None

    await asyncio.wait_for(srv._authority_event_pump(mock_app_state), timeout=2.0)


async def test_pump_survives_a_failing_broadcast(mock_app_state, monkeypatch):
    """One bad frame must not end the loop for every later announcement.

    A pump that dies on its first failure silently restores exactly the gap it
    exists to close (T-02-15-01), which is why the per-event body is guarded.
    """
    import web.server as srv

    detector = _StubDetector()
    mock_app_state.override_detector = detector
    seen: list[dict] = []
    calls = {"n": 0}

    async def flaky_broadcast(state, frame):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first broadcast explodes")
        seen.append(frame)

    monkeypatch.setattr(srv, "_broadcast_chat", flaky_broadcast)

    task = asyncio.create_task(srv._authority_event_pump(mock_app_state))
    try:
        await detector.events.put(_override_event())
        await detector.events.put(_restore_event())
        for _ in range(200):
            if seen:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert calls["n"] == 2, "the pump kept consuming after the failure"
    assert seen and seen[0]["event"] == "restore"


async def test_cancelling_the_pump_raises_nothing(mock_app_state):
    """Shutdown cancels it; ``except Exception`` must not swallow CancelledError."""
    import web.server as srv

    mock_app_state.override_detector = _StubDetector()

    task = asyncio.create_task(srv._authority_event_pump(mock_app_state))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


# ---------------------------------------------------------------------------
# ws_chat registry membership
# ---------------------------------------------------------------------------


async def test_chat_socket_is_registered_and_deregistered(test_app, mock_app_state):
    """Membership is owned entirely by ``ws_chat``'s accept and its ``finally``."""
    assert mock_app_state.chat_clients == set()

    transport = ASGIWebSocketTransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with aconnect_ws("http://test/ws/chat", client):
            await _wait_for_clients(mock_app_state, 1)

    await _wait_for_clients(mock_app_state, 0)


async def test_connected_browser_receives_the_announcement(test_app, mock_app_state):
    """End to end over a real socket: queue -> pump -> browser frame."""
    import web.server as srv

    detector = _StubDetector()
    mock_app_state.override_detector = detector
    mock_app_state.authority = AuthorityState(AuthorityLevel.FULL)

    transport = ASGIWebSocketTransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with aconnect_ws("http://test/ws/chat", client) as ws:
            await _wait_for_clients(mock_app_state, 1)
            task = asyncio.create_task(srv._authority_event_pump(mock_app_state))
            try:
                await detector.events.put(_override_event())
                frame = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    assert frame["type"] == "authority_event", _GAP3_REGRESSION
    assert frame["message"] == "You've taken the flaps. I'm advisory only until you're done."
    assert frame["authority_level"] == "full"
    assert frame["authority"]["configured_level"] == "full"


async def test_both_connected_browsers_receive_the_announcement(test_app, mock_app_state):
    """Two open tabs both hear it; the queue is drained once and fanned out."""
    import web.server as srv

    detector = _StubDetector()
    mock_app_state.override_detector = detector

    transport = ASGIWebSocketTransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with aconnect_ws("http://test/ws/chat", client) as first:
            async with aconnect_ws("http://test/ws/chat", client) as second:
                await _wait_for_clients(mock_app_state, 2)
                task = asyncio.create_task(srv._authority_event_pump(mock_app_state))
                try:
                    await detector.events.put(_restore_event())
                    first_frame = await asyncio.wait_for(first.receive_json(), timeout=5.0)
                    second_frame = await asyncio.wait_for(second.receive_json(), timeout=5.0)
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    assert first_frame == second_frame
    assert first_frame["event"] == "restore"
