"""Tests for the CLI's authority surface -- announcements and status rendering.

This file deliberately never constructs an ``Orchestrator``. That constructor
builds four network clients eagerly (``TelemetryClient``, ``ContextStore``,
``WhisperClient`` and ``ClaudeClient``, plus a TTS client), so it is not a
unit-test-shaped object; both things under test here are therefore module-level
functions taking plain arguments.

What is under test is the half of AUTH-06 that shipped orphaned: the detector
built a ``ProactiveEvent`` for every override and every restore and nothing in
the process ever read the queue. ``drain_authority_events`` is the CLI consumer,
so a test that lets its loop die silently would restore exactly that failure.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from orchestrator.main import drain_authority_events, format_authority_status
from orchestrator.proactive_monitor import ProactiveEvent

SETTLE_TIMEOUT_S = 2.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _override_event(message: str = "You've taken the flaps. I'm advisory only.") -> ProactiveEvent:
    return ProactiveEvent(
        type="authority",
        priority=1,
        message=message,
        data={"event": "override", "fields": ["surfaces.flaps_percent"]},
    )


def _restore_event(message: str = "Back to full authority whenever you want me.") -> ProactiveEvent:
    return ProactiveEvent(
        type="authority",
        priority=0,
        message=message,
        data={"event": "restore", "level": "full"},
    )


def _queue(*events: ProactiveEvent) -> asyncio.PriorityQueue[ProactiveEvent]:
    queue: asyncio.PriorityQueue[ProactiveEvent] = asyncio.PriorityQueue()
    for event in events:
        queue.put_nowait(event)
    return queue


async def _settle(predicate: Callable[[], bool], timeout: float = SETTLE_TIMEOUT_S) -> None:
    """Yield to the loop until ``predicate`` holds, or fail the test."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("drain did not reach the expected state within the timeout")


async def _drain_until(
    queue: asyncio.PriorityQueue[ProactiveEvent],
    *,
    announce: Callable[[str], None],
    speak: Callable[[str], Awaitable[None]] | None = None,
    until: Callable[[], bool],
) -> None:
    """Run the drain as a task until ``until`` holds, then cancel it."""
    task = asyncio.create_task(drain_authority_events(queue, announce=announce, speak=speak))
    try:
        await _settle(until)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# drain_authority_events
# ---------------------------------------------------------------------------


class TestDrainAuthorityEvents:
    @pytest.mark.asyncio
    async def test_an_override_is_printed_and_spoken(self) -> None:
        event = _override_event()
        printed: list[str] = []
        spoken: list[str] = []

        async def speak(text: str) -> None:
            spoken.append(text)

        await _drain_until(
            _queue(event),
            announce=printed.append,
            speak=speak,
            until=lambda: bool(printed and spoken),
        )

        assert printed == [event.message]
        assert spoken == [event.message]

    @pytest.mark.asyncio
    async def test_without_tts_the_announcement_is_still_printed(self) -> None:
        event = _override_event()
        printed: list[str] = []

        await _drain_until(
            _queue(event),
            announce=printed.append,
            speak=None,
            until=lambda: bool(printed),
        )

        assert printed == [event.message]

    @pytest.mark.asyncio
    async def test_a_raising_announce_is_logged_and_the_loop_continues(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        first = _override_event("first")
        second = _override_event("second")
        seen: list[str] = []

        def announce(text: str) -> None:
            seen.append(text)
            if text == "first":
                raise RuntimeError("stdout is closed")

        with caplog.at_level(logging.ERROR, logger="orchestrator.main"):
            await _drain_until(
                _queue(first, second),
                announce=announce,
                until=lambda: len(seen) == 2,
            )

        assert seen == ["first", "second"]
        assert [r for r in caplog.records if r.levelno == logging.ERROR]

    @pytest.mark.asyncio
    async def test_a_raising_speak_is_logged_and_the_loop_continues(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        first = _override_event("first")
        second = _override_event("second")
        printed: list[str] = []

        async def speak(text: str) -> None:
            if text == "first":
                raise RuntimeError("no audio device")

        with caplog.at_level(logging.ERROR, logger="orchestrator.main"):
            await _drain_until(
                _queue(first, second),
                announce=printed.append,
                speak=speak,
                until=lambda: len(printed) == 2,
            )

        assert printed == ["first", "second"]
        assert [r for r in caplog.records if r.levelno == logging.ERROR]

    @pytest.mark.asyncio
    async def test_cancelling_the_drain_exits_cleanly(self) -> None:
        printed: list[str] = []
        task = asyncio.create_task(
            drain_authority_events(_queue(), announce=printed.append, speak=None)
        )
        await asyncio.sleep(0)

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert task.cancelled()
        assert printed == []

    @pytest.mark.asyncio
    async def test_the_higher_priority_event_is_announced_first(self) -> None:
        restore = _restore_event("restore")
        override = _override_event("override")
        printed: list[str] = []

        # Queued restore-then-override; the priority queue must invert that.
        await _drain_until(
            _queue(restore, override),
            announce=printed.append,
            until=lambda: len(printed) == 2,
        )

        assert printed == ["override", "restore"]


# ---------------------------------------------------------------------------
# format_authority_status
# ---------------------------------------------------------------------------


def _summary(**overrides: Any) -> dict[str, Any]:
    """A default AuthorityState.summary() payload, with overrides applied."""
    base: dict[str, Any] = {
        "level": "full",
        "reason": "config",
        "configured_level": "full",
        "cooldown_remaining_s": 0.0,
        "watchdog_latched": False,
        "consecutive_timeouts": 0,
        "degraded_detail": "",
    }
    base.update(overrides)
    return base


class TestFormatAuthorityStatus:
    def test_an_override_cooldown_reports_level_reason_and_seconds(self) -> None:
        lines = format_authority_status(
            _summary(
                level="advisory",
                reason="override",
                configured_level="full",
                cooldown_remaining_s=42.0,
            )
        )

        text = "\n".join(lines)
        assert "advisory" in text
        assert "override" in text
        assert "full" in text
        assert "42" in text

    def test_no_cooldown_line_when_no_cooldown_is_running(self) -> None:
        lines = format_authority_status(_summary())

        assert lines, "the level line is always emitted"
        assert not any("cooldown" in line.lower() for line in lines)

    def test_a_latched_watchdog_names_the_latch_and_the_count(self) -> None:
        lines = format_authority_status(
            _summary(
                level="advisory",
                reason="watchdog",
                watchdog_latched=True,
                consecutive_timeouts=3,
            )
        )

        watchdog_lines = [line for line in lines if "watchdog" in line.lower()]
        assert watchdog_lines
        assert "3" in " ".join(watchdog_lines)

    def test_no_watchdog_line_when_the_watchdog_is_clear(self) -> None:
        lines = format_authority_status(_summary())

        assert not any("watchdog" in line.lower() for line in lines)

    def test_degraded_detail_is_carried_verbatim(self) -> None:
        detail = "authority construction failed: bad AUTHORITY_LEVEL"
        lines = format_authority_status(
            _summary(level="advisory", reason="degraded", degraded_detail=detail)
        )

        assert any(detail in line for line in lines)

    def test_no_degraded_line_on_a_healthy_state(self) -> None:
        lines = format_authority_status(_summary())

        assert not any("degraded" in line.lower() for line in lines)

    def test_the_raw_reason_is_printed_rather_than_friendly_prose(self) -> None:
        """An unmapped reason must be obviously unmapped, not plausibly wrong.

        CLAUDE.md's ``tts_configured`` lesson: a missing branch that prints
        something believable hides for months. The CLI reader is the operator.
        """
        for reason in ("config", "override", "watchdog", "degraded"):
            lines = format_authority_status(_summary(reason=reason))
            assert reason in lines[0], f"{reason} must appear verbatim"
