"""Tests for orchestrator.override_detector -- pilot override attribution.

Every test drives an injected ``_FakeClock``, so the 120 s rolling cooldown and
the 30 s attribution grace are exercised in microseconds and nothing sleeps.
Dispatch timestamps are literals in a mocked ledger, which is the same thing:
one monotonic clock, fully under the test's control.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from unittest.mock import MagicMock

import pytest
from orchestrator.authority import AuthorityLevel, AuthorityReason, AuthorityState
from orchestrator.command_history import _get_nested_attr
from orchestrator.override_detector import (
    COMMAND_WATCHED_FIELDS,
    MAX_PENDING_ANNOUNCEMENTS,
    WATCHED_FIELD_EPSILON,
    WATCHED_FIELDS,
    OverrideDetector,
)
from orchestrator.proactive_monitor import ProactiveEvent
from orchestrator.sim_client import (
    AutopilotState,
    Environment,
    RadioState,
    SimState,
    SurfaceState,
    TelemetryClient,
)

GRACE_S = 30.0
SETTLE_S = 2.0
VERIFY_TIMEOUT_S = 3.0
COOLDOWN_S = 120.0

# A command with a verification rule is accounted for over
# VERIFY_TIMEOUT_S + GRACE_S = 33 s; one without, over SETTLE_S + GRACE_S = 32 s.
# This elapsed time falls between the two windows.
BETWEEN_LEADS_S = 32.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeClock:
    """Advanceable stand-in for ``time.monotonic`` (mirrors test_authority.py)."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make_state(
    *,
    aircraft: str = "C172",
    connected: bool = True,
    gear: bool = False,
    flaps: float = 0.0,
    spoilers: float = 0.0,
    ap_master: bool = False,
    ap_heading: float = 180.0,
    ap_altitude: float = 5000.0,
    ap_vertical_speed: float = 0.0,
    ap_airspeed: float = 120.0,
    com1: float = 121.9,
    com2: float = 118.5,
    nav1: float = 110.5,
    nav2: float = 112.3,
    barometer: float = 29.92,
) -> SimState:
    """Build a SimState with every watched field at a stable, non-default value."""
    return SimState(
        connected=connected,
        aircraft=aircraft,
        surfaces=SurfaceState(
            gear_handle=gear,
            flaps_percent=flaps,
            spoilers_percent=spoilers,
        ),
        autopilot=AutopilotState(
            master=ap_master,
            heading=ap_heading,
            altitude=ap_altitude,
            vertical_speed=ap_vertical_speed,
            airspeed=ap_airspeed,
        ),
        radios=RadioState(com1=com1, com2=com2, nav1=nav1, nav2=nav2),
        environment=Environment(barometer_inhg=barometer),
    )


def _client(dispatches: Iterable[tuple[str, float]] = ()) -> MagicMock:
    """A TelemetryClient whose dispatch ledger is a fixed literal tuple."""
    client = MagicMock(spec=TelemetryClient)
    fixed = tuple(dispatches)
    client.recent_dispatches = lambda: fixed
    return client


def _detector(clock: _FakeClock, client: MagicMock) -> tuple[OverrideDetector, AuthorityState]:
    authority = AuthorityState(
        AuthorityLevel.FULL,
        override_cooldown_s=COOLDOWN_S,
        clock=clock,
    )
    detector = OverrideDetector(
        authority,
        client,
        grace_s=GRACE_S,
        settle_s=SETTLE_S,
        verify_timeout_s=VERIFY_TIMEOUT_S,
        clock=clock,
    )
    return detector, authority


async def _feed(detector: OverrideDetector, *states: SimState) -> None:
    for state in states:
        await detector.on_telemetry_update(state)


def _drain(queue: asyncio.PriorityQueue[ProactiveEvent]) -> list[ProactiveEvent]:
    events: list[ProactiveEvent] = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


# ---------------------------------------------------------------------------
# Table integrity
# ---------------------------------------------------------------------------


class TestWatchedFieldTables:
    def test_every_watched_path_resolves_on_a_default_sim_state(self) -> None:
        state = SimState()
        for command, paths in COMMAND_WATCHED_FIELDS.items():
            for path in paths:
                # Raises AttributeError if the path names a field that does not exist.
                _get_nested_attr(state, path)
                assert path in WATCHED_FIELDS, f"{command} watches unlisted path {path}"

    def test_every_float_path_has_a_movement_tolerance(self) -> None:
        state = SimState()
        for path in WATCHED_FIELDS:
            if isinstance(_get_nested_attr(state, path), bool):
                continue  # booleans compare with !=, no epsilon
            assert path in WATCHED_FIELD_EPSILON, f"{path} has no movement tolerance"

    def test_throttle_is_deliberately_not_watched(self) -> None:
        assert "THROTTLE_SET" not in COMMAND_WATCHED_FIELDS, (
            "engines[].rpm moves continuously with airspeed, mixture and propeller "
            "pitch, so watching throttle would report a pilot override on every "
            "power change (RESEARCH B6)"
        )


# ---------------------------------------------------------------------------
# Detection and attribution
# ---------------------------------------------------------------------------


class TestDetection:
    @pytest.mark.asyncio
    async def test_unattributed_change_is_an_override(self) -> None:
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())

        await _feed(detector, _make_state(flaps=0.0), _make_state(flaps=30.0))

        assert authority.level is AuthorityLevel.ADVISORY
        assert authority.reason is AuthorityReason.OVERRIDE
        events = _drain(detector.events)
        assert len(events) == 1
        assert events[0].type == "authority"
        assert events[0].priority == 1

    @pytest.mark.asyncio
    async def test_matching_dispatch_with_a_rule_suppresses(self) -> None:
        clock = _FakeClock()
        detector, authority = _detector(clock, _client([("FLAPS_SET", 0.0)]))
        clock.advance(1.0)

        await _feed(detector, _make_state(flaps=0.0), _make_state(flaps=30.0))

        assert authority.level is AuthorityLevel.FULL
        assert detector.events.empty()

    @pytest.mark.asyncio
    async def test_matching_dispatch_without_a_rule_suppresses(self) -> None:
        clock = _FakeClock()
        detector, authority = _detector(clock, _client([("FLAPS_INCR", 0.0)]))
        clock.advance(1.0)

        await _feed(detector, _make_state(flaps=0.0), _make_state(flaps=30.0))

        assert authority.level is AuthorityLevel.FULL
        assert detector.events.empty()

    @pytest.mark.asyncio
    async def test_rule_lead_still_covers_the_change(self) -> None:
        """FLAPS_SET has a verification rule, so its window is verify_timeout + grace."""
        clock = _FakeClock()
        detector, authority = _detector(clock, _client([("FLAPS_SET", 0.0)]))
        clock.advance(BETWEEN_LEADS_S)

        await _feed(detector, _make_state(flaps=0.0), _make_state(flaps=30.0))

        assert authority.level is AuthorityLevel.FULL

    @pytest.mark.asyncio
    async def test_no_rule_lead_has_already_expired(self) -> None:
        """FLAPS_INCR has none, so its window is settle + grace -- one second shorter.

        Same field, same movement, same elapsed time as the test above. Only the
        suppression lead differs, which is what D-13-as-amended asks for.
        """
        clock = _FakeClock()
        detector, authority = _detector(clock, _client([("FLAPS_INCR", 0.0)]))
        clock.advance(BETWEEN_LEADS_S)

        await _feed(detector, _make_state(flaps=0.0), _make_state(flaps=30.0))

        assert authority.level is AuthorityLevel.ADVISORY

    @pytest.mark.asyncio
    async def test_expired_window_no_longer_accounts_for_the_change(self) -> None:
        clock = _FakeClock()
        detector, authority = _detector(clock, _client([("FLAPS_SET", 0.0)]))
        clock.advance(VERIFY_TIMEOUT_S + GRACE_S + 10.0)

        await _feed(detector, _make_state(flaps=0.0), _make_state(flaps=30.0))

        assert authority.level is AuthorityLevel.ADVISORY

    @pytest.mark.asyncio
    async def test_dispatch_on_a_different_field_does_not_account(self) -> None:
        clock = _FakeClock()
        detector, authority = _detector(clock, _client([("GEAR_DOWN", 0.0)]))
        clock.advance(1.0)

        await _feed(detector, _make_state(flaps=0.0), _make_state(flaps=30.0))

        assert authority.level is AuthorityLevel.ADVISORY

    @pytest.mark.asyncio
    async def test_extending_flaps_detects(self) -> None:
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())

        await _feed(detector, _make_state(flaps=20.0), _make_state(flaps=30.0))

        assert authority.level is AuthorityLevel.ADVISORY

    @pytest.mark.asyncio
    async def test_retracting_flaps_detects_the_same_way(self) -> None:
        """Direction-agnostic: both directions mean the pilot is working that system."""
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())

        await _feed(detector, _make_state(flaps=20.0), _make_state(flaps=0.0))

        assert authority.level is AuthorityLevel.ADVISORY

    @pytest.mark.asyncio
    async def test_boolean_field_movement_detects(self) -> None:
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())

        await _feed(detector, _make_state(gear=False), _make_state(gear=True))

        assert authority.level is AuthorityLevel.ADVISORY


# ---------------------------------------------------------------------------
# Suppression -- the failure modes research identified
# ---------------------------------------------------------------------------


class TestSuppression:
    @pytest.mark.asyncio
    async def test_first_frame_never_detects(self) -> None:
        """F6: the client's initial state is a default SimState(), all zeros and False."""
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())

        await detector.on_telemetry_update(_make_state(flaps=100.0, gear=True))

        assert authority.level is AuthorityLevel.FULL
        assert detector.events.empty()

    @pytest.mark.asyncio
    async def test_aircraft_change_never_detects(self) -> None:
        """F4: loading a different aircraft moves everything at once."""
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())

        await _feed(
            detector,
            _make_state(aircraft="C172", flaps=0.0),
            _make_state(aircraft="B738", flaps=100.0),
        )

        assert authority.level is AuthorityLevel.FULL

    @pytest.mark.asyncio
    async def test_frame_inside_the_settle_window_does_not_detect(self) -> None:
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())
        await _feed(
            detector,
            _make_state(aircraft="C172", flaps=0.0),
            _make_state(aircraft="B738", flaps=100.0),
        )

        clock.advance(SETTLE_S / 2)
        await detector.on_telemetry_update(_make_state(aircraft="B738", flaps=0.0))

        assert authority.level is AuthorityLevel.FULL

    @pytest.mark.asyncio
    async def test_detection_resumes_after_the_settle_window(self) -> None:
        """The settle window is a delay, not a permanent mute."""
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())
        await _feed(
            detector,
            _make_state(aircraft="C172", flaps=0.0),
            _make_state(aircraft="B738", flaps=100.0),
        )

        clock.advance(SETTLE_S + 1.0)
        await detector.on_telemetry_update(_make_state(aircraft="B738", flaps=0.0))

        assert authority.level is AuthorityLevel.ADVISORY

    @pytest.mark.asyncio
    async def test_disconnection_never_detects(self) -> None:
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())

        await _feed(
            detector,
            _make_state(connected=True, flaps=0.0),
            _make_state(connected=False, flaps=100.0),
        )

        assert authority.level is AuthorityLevel.FULL

    @pytest.mark.asyncio
    async def test_reconnection_never_detects(self) -> None:
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())

        await _feed(
            detector,
            _make_state(connected=False, flaps=0.0),
            _make_state(connected=True, flaps=100.0),
        )

        assert authority.level is AuthorityLevel.FULL

    @pytest.mark.asyncio
    async def test_sub_epsilon_jitter_does_not_detect(self) -> None:
        """F3: heading tolerance is 1.0, matching the verifier's ±1°."""
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())

        await _feed(detector, _make_state(ap_heading=180.0), _make_state(ap_heading=180.5))

        assert authority.level is AuthorityLevel.FULL
        assert detector.events.empty()

    @pytest.mark.asyncio
    async def test_supra_epsilon_movement_does_detect(self) -> None:
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())

        await _feed(detector, _make_state(ap_heading=180.0), _make_state(ap_heading=182.0))

        assert authority.level is AuthorityLevel.ADVISORY


# ---------------------------------------------------------------------------
# Rolling cooldown and announcements
# ---------------------------------------------------------------------------


class TestCooldownAndAnnouncements:
    @pytest.mark.asyncio
    async def test_two_overrides_inside_one_cooldown_announce_once(self) -> None:
        clock = _FakeClock()
        detector, _authority = _detector(clock, _client())

        await _feed(detector, _make_state(flaps=0.0), _make_state(flaps=30.0))
        clock.advance(COOLDOWN_S / 2)
        await detector.on_telemetry_update(_make_state(flaps=60.0))

        drops = [e for e in _drain(detector.events) if e.data["event"] == "override"]
        assert len(drops) == 1

    @pytest.mark.asyncio
    async def test_drop_then_restore_across_a_rolling_cooldown(self) -> None:
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())

        # t=0 -- override drops to advisory; expiry is t=120.
        await _feed(detector, _make_state(flaps=0.0), _make_state(flaps=30.0))
        assert authority.level is AuthorityLevel.ADVISORY

        # t=60 -- a second override rolls the expiry out to t=180.
        clock.advance(COOLDOWN_S / 2)
        await detector.on_telemetry_update(_make_state(flaps=60.0))
        assert authority.level is AuthorityLevel.ADVISORY

        # t=130 -- past the original expiry, inside the rolled one.
        steady = _make_state(flaps=60.0)
        clock.advance(COOLDOWN_S / 2 + 10.0)
        await detector.on_telemetry_update(steady)
        assert authority.level is AuthorityLevel.ADVISORY

        # t=250 -- past the rolled expiry; authority restores.
        clock.advance(COOLDOWN_S)
        await detector.on_telemetry_update(steady)
        assert authority.level is AuthorityLevel.FULL

        events = _drain(detector.events)
        assert len(events) == 2
        assert [e.type for e in events] == ["authority", "authority"]
        assert events[0].priority == 1
        assert events[0].data["event"] == "override"
        assert events[1].priority == 0
        assert events[1].data["event"] == "restore"

    @pytest.mark.asyncio
    async def test_restore_fires_exactly_once(self) -> None:
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())
        await _feed(detector, _make_state(flaps=0.0), _make_state(flaps=30.0))

        steady = _make_state(flaps=30.0)
        clock.advance(COOLDOWN_S + 1.0)
        await detector.on_telemetry_update(steady)
        clock.advance(1.0)
        await detector.on_telemetry_update(steady)

        restores = [e for e in _drain(detector.events) if e.data["event"] == "restore"]
        assert len(restores) == 1
        assert authority.level is AuthorityLevel.FULL

    @pytest.mark.asyncio
    async def test_the_announcement_names_the_system_in_pilot_terms(self) -> None:
        clock = _FakeClock()
        detector, _authority = _detector(clock, _client())

        await _feed(detector, _make_state(gear=False), _make_state(gear=True))

        events = _drain(detector.events)
        assert "the gear" in events[0].message
        assert events[0].data["fields"] == ["surfaces.gear_handle"]

    @pytest.mark.asyncio
    async def test_the_restore_announcement_names_the_configured_level(self) -> None:
        clock = _FakeClock()
        detector, _authority = _detector(clock, _client())
        await _feed(detector, _make_state(flaps=0.0), _make_state(flaps=30.0))

        steady = _make_state(flaps=30.0)
        clock.advance(COOLDOWN_S + 1.0)
        await detector.on_telemetry_update(steady)

        restore = [e for e in _drain(detector.events) if e.data["event"] == "restore"][0]
        assert restore.data["level"] == AuthorityLevel.FULL.value
        assert "full" in restore.message


# ---------------------------------------------------------------------------
# Announcement queue bounds (Gap 3 / WR-06)
# ---------------------------------------------------------------------------


class TestAnnouncementQueueIsBounded:
    """The queue is bounded and publishing cannot raise.

    The overflow cases call ``_publish`` directly rather than driving telemetry.
    That is the honest test here: reaching 33 announcements through
    ``on_telemetry_update`` needs 33 cooldown lapses at 120 s apiece, and every
    one of those frames exercises attribution and epsilon comparison rather than
    the drop policy under test. ``_publish`` is the only thing standing between
    the two production call sites and the queue, so it is the unit.
    """

    @staticmethod
    def _event(n: int) -> ProactiveEvent:
        """A synthetic announcement whose message identifies its ordinal."""
        return ProactiveEvent(
            type="authority",
            priority=0,
            message=f"announcement-{n}",
            data={"event": "override", "n": n},
        )

    @pytest.mark.asyncio
    async def test_the_default_queue_is_bounded(self) -> None:
        detector, _authority = _detector(_FakeClock(), _client())
        assert MAX_PENDING_ANNOUNCEMENTS == 32
        assert detector.events.maxsize == MAX_PENDING_ANNOUNCEMENTS

    @pytest.mark.asyncio
    async def test_a_caller_supplied_queue_is_used_as_given(self) -> None:
        clock = _FakeClock()
        supplied: asyncio.PriorityQueue[ProactiveEvent] = asyncio.PriorityQueue(maxsize=3)
        authority = AuthorityState(AuthorityLevel.FULL, override_cooldown_s=COOLDOWN_S, clock=clock)
        detector = OverrideDetector(authority, _client(), event_queue=supplied, clock=clock)

        assert detector.events is supplied
        assert detector.events.maxsize == 3

    @pytest.mark.asyncio
    async def test_overflow_does_not_raise_and_holds_at_the_bound(self) -> None:
        detector, _authority = _detector(_FakeClock(), _client())

        for n in range(MAX_PENDING_ANNOUNCEMENTS + 8):
            detector._publish(self._event(n))  # must never raise

        assert detector.events.qsize() == MAX_PENDING_ANNOUNCEMENTS

    @pytest.mark.asyncio
    async def test_the_newest_announcement_survives_an_overflow(self) -> None:
        detector, _authority = _detector(_FakeClock(), _client())
        last = MAX_PENDING_ANNOUNCEMENTS + 7

        for n in range(last + 1):
            detector._publish(self._event(n))

        messages = [event.message for event in _drain(detector.events)]
        assert f"announcement-{last}" in messages

    @pytest.mark.asyncio
    async def test_overflow_logs_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        detector, _authority = _detector(_FakeClock(), _client())

        with caplog.at_level(logging.WARNING, logger="orchestrator.override_detector"):
            for n in range(MAX_PENDING_ANNOUNCEMENTS + 2):
                detector._publish(self._event(n))

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings, "an overflow must be logged at WARNING"

    @pytest.mark.asyncio
    async def test_a_full_queue_does_not_break_detection(self) -> None:
        """A missing consumer must not stop authority dropping to advisory."""
        clock = _FakeClock()
        detector, authority = _detector(clock, _client())
        for n in range(MAX_PENDING_ANNOUNCEMENTS):
            detector._publish(self._event(n))

        await _feed(detector, _make_state(flaps=0.0), _make_state(flaps=30.0))

        assert authority.level is AuthorityLevel.ADVISORY
