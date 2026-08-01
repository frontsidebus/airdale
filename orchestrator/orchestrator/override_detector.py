"""Detects that the pilot has taken over a system MERLIN is commanding.

Telemetry reports *state*, never *provenance*. SimConnect exposes no per-simvar
"who wrote this", so "the pilot did it" can only ever mean "nothing MERLIN sent
accounts for it". Production autopilots do not work this way -- they read
actuator torque directly -- and no amount of state comparison makes this exact.
The bias is therefore deliberate and toward sensitivity: a false positive costs
one advisory window, a false negative leaves MERLIN commanding an aircraft the
pilot is already flying.

**Attribution runs on one clock.** Every window is measured against
``TelemetryClient.recent_dispatches()``, whose timestamps are ``time.monotonic()``
taken on the client side at the moment a command reached the wire -- the same
clock as this module's injected ``clock``. The adapter's ISO
``SimState.timestamp`` is a wall clock from another process and is never used for
correlation.

**Why the dispatch ledger and not the command history.** ``undo_last_command``
deliberately passes ``command_history=None`` so an undo is never recorded as a
``CommandRecord``; an undo's own state change would then be unattributed and read
as a pilot override. The dispatch ledger records *every* command that reached the
wire, undos and procedure steps included, so that failure mode does not arise.
Do not switch the basis back -- it would reintroduce the bug.

**Coverage is bounded, and AUTH-05 must not be read as universal.** Six systems
are cleanly observable: gear, flaps, spoilers, autopilot (master, heading,
altitude, vertical speed, airspeed), the four radios, and the altimeter setting.
Throttle is deliberately excluded: engine RPM moves continuously with airspeed,
mixture and propeller pitch, so watching it would fire on every power change
(RESEARCH B6). Thirteen further systems -- trim, mixture, propeller, parking
brake, fuel selector, crossfeed, de-ice, magnetos, carburettor heat, fuel pump,
starter, primer and lights -- are structurally undetectable because no
``SimState`` field exists for them anywhere in the telemetry chain.

The detector hangs off a plain ``TelemetryClient.subscribe`` callback rather than
``ProactiveMonitor``: that class is never constructed in production, and wiring
it here would silently commission callouts, deviation alerts, emergency
detection and checklist automation as a side effect. Only its
:class:`~orchestrator.proactive_monitor.ProactiveEvent` type is reused.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from .authority import AuthorityState
from .command_history import _get_nested_attr
from .command_verifier import has_verification_rule
from .proactive_monitor import ProactiveEvent
from .sim_client import SimState, TelemetryClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Command → the telemetry fields it can move
#
# A new table rather than a reuse of ``_extract_relevant_state``: that map
# answers "what value do I restore?" (a scalar snapshot, non-empty for 8 of 67
# commands) while this one answers "which fields should I watch?" (a field-path
# set). They coincide only for value-restore commands, and coupling them would
# break undo (RESEARCH B4).
# ---------------------------------------------------------------------------

COMMAND_WATCHED_FIELDS: dict[str, tuple[str, ...]] = {
    "GEAR_UP": ("surfaces.gear_handle",),
    "GEAR_DOWN": ("surfaces.gear_handle",),
    "GEAR_TOGGLE": ("surfaces.gear_handle",),
    "FLAPS_UP": ("surfaces.flaps_percent",),
    "FLAPS_1": ("surfaces.flaps_percent",),
    "FLAPS_2": ("surfaces.flaps_percent",),
    "FLAPS_3": ("surfaces.flaps_percent",),
    "FLAPS_FULL": ("surfaces.flaps_percent",),
    "FLAPS_SET": ("surfaces.flaps_percent",),
    "FLAPS_INCR": ("surfaces.flaps_percent",),
    "FLAPS_DECR": ("surfaces.flaps_percent",),
    "SPOILERS_TOGGLE": ("surfaces.spoilers_percent",),
    "SPOILERS_SET": ("surfaces.spoilers_percent",),
    "AP_MASTER": ("autopilot.master",),
    "AP_HDG_HOLD": ("autopilot.heading",),
    "HEADING_BUG_SET": ("autopilot.heading",),
    "AP_ALT_HOLD": ("autopilot.altitude",),
    "AP_ALT_VAR_SET_ENGLISH": ("autopilot.altitude",),
    "AP_VS_HOLD": ("autopilot.vertical_speed",),
    "AP_VS_VAR_SET_ENGLISH": ("autopilot.vertical_speed",),
    "AP_AIRSPEED_HOLD": ("autopilot.airspeed",),
    "AP_SPD_VAR_SET": ("autopilot.airspeed",),
    "COM_RADIO_SET_HZ": ("radios.com1",),
    "COM2_RADIO_SET_HZ": ("radios.com2",),
    "NAV1_RADIO_SET_HZ": ("radios.nav1",),
    "NAV2_RADIO_SET_HZ": ("radios.nav2",),
    "KOHLSMAN_SET": ("environment.barometer_inhg",),
    # Deliberately absent: THROTTLE_SET, and every engines[].rpm path with it.
    # RPM moves continuously with airspeed, mixture and propeller pitch, so a
    # watch on it would report a pilot override on every power change and on
    # every climb (RESEARCH B6). This is not an oversight -- do not "fix" it by
    # adding an engine path here.
}


# ---------------------------------------------------------------------------
# Per-field movement tolerance
#
# Numbers are the verifier's, verbatim (command_verifier.py: flaps ±5 %,
# heading ±1°, altitude ±50 ft), so the two layers cannot disagree about
# whether a surface moved. Float telemetry jitters and the client's delta
# detection compares raw JSON, so any wobble produces an update (F3).
# ---------------------------------------------------------------------------

WATCHED_FIELD_EPSILON: dict[str, float] = {
    "surfaces.flaps_percent": 5.0,
    "surfaces.spoilers_percent": 5.0,
    "autopilot.heading": 1.0,
    "autopilot.altitude": 50.0,
    "autopilot.vertical_speed": 50.0,
    "autopilot.airspeed": 2.0,
    "environment.barometer_inhg": 0.005,
    "radios.com1": 0.005,
    "radios.com2": 0.005,
    "radios.nav1": 0.005,
    "radios.nav2": 0.005,
}

#: Every field any watched command can move -- the set walked each update.
#: Booleans (``surfaces.gear_handle``, ``autopilot.master``) have no epsilon and
#: compare with ``!=``.
WATCHED_FIELDS: tuple[str, ...] = tuple(
    sorted({path for paths in COMMAND_WATCHED_FIELDS.values() for path in paths})
)


#: Dotted path → what a pilot calls it. Used only for the spoken announcement.
FIELD_LABELS: dict[str, str] = {
    "surfaces.gear_handle": "the gear",
    "surfaces.flaps_percent": "the flaps",
    "surfaces.spoilers_percent": "the spoilers",
    "autopilot.master": "the autopilot",
    "autopilot.heading": "the autopilot heading",
    "autopilot.altitude": "the autopilot altitude",
    "autopilot.vertical_speed": "the autopilot vertical speed",
    "autopilot.airspeed": "the autopilot speed",
    "radios.com1": "COM1",
    "radios.com2": "COM2",
    "radios.nav1": "NAV1",
    "radios.nav2": "NAV2",
    "environment.barometer_inhg": "the altimeter setting",
}


class OverrideDetector:
    """Watches telemetry for changes no MERLIN command accounts for.

    Level-triggered: every update compares the full watched-field set against
    the previous frame, rather than reacting once to a particular transition.
    Detection is direction-agnostic by construction -- flaps 2 to flaps 3 counts
    exactly as much as flaps 2 to flaps up, because both mean the pilot is
    working that system (D-12).
    """

    def __init__(
        self,
        authority: AuthorityState,
        sim_client: TelemetryClient,
        *,
        grace_s: float = 30.0,
        settle_s: float = 2.0,
        verify_timeout_s: float = 3.0,
        event_queue: asyncio.PriorityQueue[ProactiveEvent] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Build a detector.

        Args:
            authority: The state a detection drops to advisory.
            sim_client: Read for :meth:`~orchestrator.sim_client.TelemetryClient.recent_dispatches`.
            grace_s: Extra seconds a dispatch keeps accounting for its field after
                its lead has elapsed (``Settings.authority_override_grace_s``).
            settle_s: Suppression period after an aircraft change or a reconnect,
                and the attribution lead for a command with no verification rule
                (``Settings.authority_override_settle_s``).
            verify_timeout_s: Attribution lead for a command that *does* have a
                verification rule, which may still be polling when its change
                lands (``Settings.authority_verify_timeout_s``).
            event_queue: Shared announcement queue; one is created when omitted.
            clock: Monotonic time source, injected so tests need not sleep. Must
                be the same clock the dispatch ledger stamps with.
        """
        self._authority = authority
        self._sim_client = sim_client
        self._grace_s = grace_s
        self._settle_s = settle_s
        self._verify_timeout_s = verify_timeout_s
        self._clock = clock
        self._events: asyncio.PriorityQueue[ProactiveEvent] = (
            event_queue if event_queue is not None else asyncio.PriorityQueue()
        )

        self._prev_state: SimState | None = None
        self._settle_until: float = 0.0

    @property
    def events(self) -> asyncio.PriorityQueue[ProactiveEvent]:
        """Announcements awaiting a consumer.

        This phase's pilot-facing channel is ``/api/status`` plus the browser
        badge; the queue exists so a later consumer can drain it without this
        module knowing who that is.
        """
        return self._events

    # ------------------------------------------------------------------
    # Telemetry callback
    # ------------------------------------------------------------------

    async def on_telemetry_update(self, state: SimState) -> None:
        """Evaluate one telemetry frame. Matches ``StateCallback``."""
        prev = self._prev_state
        now = self._clock()

        # F6: the client initialises its state to a default SimState() -- all
        # zeros and False -- so every field differs on the first real frame.
        if prev is None:
            self._prev_state = state
            return

        # F4: an aircraft change, a flight load or a reconnect moves everything
        # at once and none of it is the pilot working a control.
        if (
            state.aircraft != prev.aircraft
            or state.connected != prev.connected
            or not state.connected
        ):
            self._prev_state = state
            self._settle_until = now + self._settle_s
            return

        if now < self._settle_until:
            self._prev_state = state
            return

        moved = [path for path in WATCHED_FIELDS if self._field_moved(prev, state, path)]
        unattributed = [path for path in moved if not self._is_attributed(path, now)]

        if unattributed:
            self._record_override(unattributed)

        if self._authority.take_restore_event():
            self._announce_restore()

        self._prev_state = state

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _field_moved(self, prev: SimState, state: SimState, path: str) -> bool:
        """Whether ``path`` changed by more than its tolerance between two frames."""
        old = _get_nested_attr(prev, path)
        new = _get_nested_attr(state, path)
        if isinstance(old, bool) or isinstance(new, bool):
            return bool(old != new)
        return abs(float(new) - float(old)) > WATCHED_FIELD_EPSILON.get(path, 0.0)

    def _is_attributed(self, path: str, now: float) -> bool:
        """Whether a recent MERLIN dispatch accounts for movement on ``path``.

        The suppression lead differs by command, which is D-13 as amended by
        RESEARCH F2. A command with a real verification rule may still be
        polling when its change lands, so it gets the full verify timeout. A
        rule-less command "confirms" in roughly zero milliseconds, long before
        the next 1 Hz frame, so its ``verified=True`` is no evidence the
        aircraft moved and it gets a fixed settle delay instead.
        """
        for command, dispatched_at in self._sim_client.recent_dispatches():
            if path not in COMMAND_WATCHED_FIELDS.get(command, ()):
                continue
            lead = self._verify_timeout_s if has_verification_rule(command) else self._settle_s
            if dispatched_at <= now <= dispatched_at + lead + self._grace_s:
                return True
        return False

    def _record_override(self, paths: list[str]) -> None:
        """Drop authority for the cooldown, announcing only on the first drop."""
        systems = ", ".join(FIELD_LABELS.get(path, path) for path in paths)
        if not self._authority.record_override():
            # The cooldown was merely extended. Sustained pilot activity would
            # otherwise re-announce on every frame.
            logger.info("Pilot still working %s; override cooldown extended", systems)
            return

        logger.warning(
            "Pilot override detected on %s; MERLIN is advisory only until the cooldown lapses",
            systems,
        )
        self._events.put_nowait(
            ProactiveEvent(
                type="authority",
                priority=1,
                message=f"You've taken {systems}. I'm advisory only until you're done.",
                data={"event": "override", "fields": list(paths)},
            )
        )

    def _announce_restore(self) -> None:
        """Announce the auto-restore half of D-14, once per lapsed cooldown."""
        level = self._authority.configured_level.value
        logger.info("Override cooldown lapsed; MERLIN is back to %s authority", level)
        self._events.put_nowait(
            ProactiveEvent(
                type="authority",
                priority=0,
                message=f"Back to {level} authority whenever you want me.",
                data={"event": "restore", "level": level},
            )
        )
