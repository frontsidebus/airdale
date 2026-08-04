"""Authority state -- how much MERLIN may do to the aircraft, and why.

A single :class:`AuthorityState` carries both the *effective* authority level and
the *reason* it holds that level. The two travel together deliberately: a pilot
seeing "advisory" needs to know whether that is how they configured MERLIN, a
consequence of them grabbing the yoke, a sign MERLIN cannot reach the sim, or an
admission that the authority subsystem itself failed to start.

**Import constraint (load-bearing).** This module imports *nothing* from the
``orchestrator`` package -- only the standard library. ``sim_client.py`` is the
base of the dependency graph (stdlib + ``websockets`` + ``pydantic`` only) and it
is a consumer of this state, so importing ``SimState``, ``Settings`` or anything
else from ``orchestrator.*`` here would create a cycle. Seeded values arrive as
constructor arguments; they are never read from a global. ``test_authority.py``
asserts this structurally -- do not casually add ``from .sim_client import ...``.

**Failure direction.** Every failure mode resolves toward *less* authority.
``DEGRADED`` is the fail-safe reason: a caller that cannot build a real authority
state calls :meth:`AuthorityState.degraded_fallback` and gets ADVISORY authority
rather than no object at all (an absent authority object reads as FULL to every
consumer). No method on this class can raise the level out of a degraded state --
degraded is terminal for the lifetime of the process, because the code that would
decide otherwise is the code that just failed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class AuthorityLevel(StrEnum):
    """How far MERLIN may go when a command is proposed.

    Exactly three members. A degraded authority subsystem is *not* a fourth
    level -- it is a fourth :class:`AuthorityReason`, so it threads only through
    the display rather than through the gate, the floor, the status endpoint and
    every test that branches on a level.
    """

    ADVISORY = "advisory"
    ASSISTED = "assisted"
    FULL = "full"


class AuthorityReason(StrEnum):
    """Why :attr:`AuthorityState.level` holds its current value.

    ``CONFIG``    -- the level the operator asked for.
    ``OVERRIDE``  -- the pilot took manual control; MERLIN is deferring.
    ``WATCHDOG``  -- the command path stopped acknowledging; MERLIN cannot reach the sim.
    ``DEGRADED``  -- the authority subsystem failed to start; MERLIN restricted itself.
    """

    CONFIG = "config"
    OVERRIDE = "override"
    WATCHDOG = "watchdog"
    DEGRADED = "degraded"


#: Levels ``parse_authority_level`` accepts. Kept in sync with
#: :class:`AuthorityLevel`; ``test_authority.py`` asserts the sync rather than
#: this module doing it at import time.
SUPPORTED_AUTHORITY_LEVELS: tuple[str, ...] = ("advisory", "assisted", "full")


def parse_authority_level(value: str) -> AuthorityLevel:
    """Resolve a configured string to an :class:`AuthorityLevel`.

    Fails loudly. There is deliberately no fallback branch: a typo that silently
    resolved to a default would be a typo that granted authority nobody asked for.

    Raises:
        ValueError: If ``value`` is not one of ``SUPPORTED_AUTHORITY_LEVELS``.
    """
    choice = value.lower().strip()
    for level in AuthorityLevel:
        if level.value == choice:
            return level

    expected = ", ".join(repr(name) for name in SUPPORTED_AUTHORITY_LEVELS)
    raise ValueError(f"Unknown authority level: {value!r}. Expected one of {expected}.")


class AuthorityState:
    """Mutable runtime authority: the configured level plus everything overriding it.

    Precedence, highest first:

    0. **Degraded** -- ``degraded_detail`` is non-empty. ADVISORY / ``DEGRADED``.
       Terminal: no override, watchdog clear, cooldown lapse or other method lifts it.
    1. **Watchdog latched** -- ADVISORY / ``WATCHDOG``.
    2. **Override cooldown active** -- ADVISORY / ``OVERRIDE``.
    3. Otherwise the configured level, reason ``CONFIG``.

    Reading :attr:`level` lazily expires a lapsed cooldown; there is no background
    task and no timer to leak.
    """

    def __init__(
        self,
        configured_level: AuthorityLevel,
        *,
        override_cooldown_s: float = 120.0,
        watchdog_max_timeouts: int = 3,
        clock: Callable[[], float] = time.monotonic,
        degraded_detail: str = "",
    ) -> None:
        """Build an authority state.

        Args:
            configured_level: The level the operator configured (``Settings.authority_level``).
            override_cooldown_s: Seconds of advisory authority after a pilot override.
                Rolling: each new override pushes the expiry out from *now*.
            watchdog_max_timeouts: Consecutive command-path timeouts that latch the watchdog.
            clock: Monotonic time source. Injected so tests need no sleeping and no
                fake-time library (there is none in any extra).
            degraded_detail: Non-empty means the authority subsystem failed to build;
                this state is permanently ADVISORY / ``DEGRADED``. Prefer
                :meth:`degraded_fallback` over passing this directly.
        """
        self._configured_level = configured_level
        self._override_cooldown_s = override_cooldown_s
        self._watchdog_max_timeouts = watchdog_max_timeouts
        self._clock = clock
        self._degraded_detail = degraded_detail

        self._cooldown_active: bool = False
        self._cooldown_expiry: float = 0.0
        self._restore_pending: bool = False
        self._consecutive_timeouts: int = 0
        self._watchdog_latched: bool = False

        if degraded_detail:
            logger.error(
                "Authority DEGRADED: restricted to %s because the authority subsystem "
                "could not be built -- %s",
                AuthorityLevel.ADVISORY.value,
                degraded_detail,
            )

    @classmethod
    def degraded_fallback(cls, detail: str) -> AuthorityState:
        """Return a permanently ADVISORY state for a composition root that failed.

        Built from enum literals only -- it reads no ``Settings``, calls no
        :func:`parse_authority_level`, and takes no collaborator -- so it is safe to
        construct from inside the ``except`` block handling the failure of the normal
        construction path. A fallback that can fail the same way as the thing it
        replaces is not a fallback.
        """
        return cls(AuthorityLevel.ADVISORY, degraded_detail=detail)

    # -- effective state ----------------------------------------------------

    @property
    def level(self) -> AuthorityLevel:
        """The effective authority level right now."""
        if self._degraded_detail:
            return AuthorityLevel.ADVISORY
        self._expire_cooldown()
        if self._watchdog_latched or self._cooldown_active:
            return AuthorityLevel.ADVISORY
        return self._configured_level

    @property
    def reason(self) -> AuthorityReason:
        """Why :attr:`level` holds its current value."""
        if self._degraded_detail:
            return AuthorityReason.DEGRADED
        self._expire_cooldown()
        if self._watchdog_latched:
            return AuthorityReason.WATCHDOG
        if self._cooldown_active:
            return AuthorityReason.OVERRIDE
        return AuthorityReason.CONFIG

    @property
    def configured_level(self) -> AuthorityLevel:
        """The level the operator configured, regardless of what overrides it."""
        return self._configured_level

    @property
    def watchdog_latched(self) -> bool:
        """Whether the command-path watchdog has latched."""
        return self._watchdog_latched

    @property
    def consecutive_timeouts(self) -> int:
        """Command-path timeouts since the last success or watchdog clear."""
        return self._consecutive_timeouts

    @property
    def degraded(self) -> bool:
        """Whether the authority subsystem failed to build."""
        return bool(self._degraded_detail)

    @property
    def degraded_detail(self) -> str:
        """Why the authority subsystem failed to build; ``""`` on a healthy state."""
        return self._degraded_detail

    # -- transitions --------------------------------------------------------

    def record_override(self) -> bool:
        """Note a pilot override; drop to advisory for a rolling cooldown.

        The expiry is always pushed out to ``now + override_cooldown_s``, so a pilot
        who keeps flying keeps MERLIN deferring.

        Returns:
            True only when this call caused the effective level to drop to advisory.
        """
        before = self.level
        self._cooldown_active = True
        self._cooldown_expiry = self._clock() + self._override_cooldown_s
        self._restore_pending = False
        after = self.level

        dropped = before != AuthorityLevel.ADVISORY and after == AuthorityLevel.ADVISORY
        if dropped:
            logger.warning(
                "Authority: %s -> %s (pilot override; restoring in %.0fs unless extended)",
                before.value,
                after.value,
                self._override_cooldown_s,
            )
        return dropped

    def record_command_timeout(self) -> bool:
        """Note a command-path timeout.

        Returns:
            True only on the call that latched the watchdog.
        """
        self._consecutive_timeouts += 1
        if self._watchdog_latched:
            return False
        if self._consecutive_timeouts < self._watchdog_max_timeouts:
            return False

        self._watchdog_latched = True
        logger.warning(
            "Authority: %s -> %s (command path unresponsive after %d consecutive timeouts)",
            self._configured_level.value,
            AuthorityLevel.ADVISORY.value,
            self._consecutive_timeouts,
        )
        return True

    def record_command_success(self) -> None:
        """Note a live command path; reset the timeout counter.

        Deliberately does **not** clear an existing latch. A latch that stops command
        issuance can never produce the successful acknowledgment that would clear it,
        so the only clear path is the out-of-band :meth:`clear_watchdog`.
        """
        self._consecutive_timeouts = 0

    def clear_watchdog(self) -> bool:
        """Clear a latched watchdog out of band (e.g. on reconnect).

        Returns:
            True only when a latch actually existed and this state is not degraded.
        """
        if self._degraded_detail:
            return False
        if not self._watchdog_latched:
            self._consecutive_timeouts = 0
            return False

        self._watchdog_latched = False
        self._consecutive_timeouts = 0
        logger.info(
            "Authority watchdog cleared; effective level is now %s",
            self.level.value,
        )
        return True

    def take_restore_event(self) -> bool:
        """Consume the one-shot "override cooldown lapsed" event.

        Drives AUTH-06's spoken restore without a timer: callers poll it, and it
        returns True exactly once per lapse. Stays pending while a watchdog latch
        holds authority down, so the announcement matches what actually happened.

        Returns:
            True on the first call after a cooldown lapsed with no latch active.
        """
        if self._degraded_detail:
            return False
        self._expire_cooldown()
        if not self._restore_pending or self._watchdog_latched:
            return False
        self._restore_pending = False
        return True

    # -- reporting ----------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot for ``/api/status`` and the CLI."""
        self._expire_cooldown()
        return {
            "level": self.level.value,
            "reason": self.reason.value,
            "configured_level": self._configured_level.value,
            "cooldown_remaining_s": self._cooldown_remaining_s(),
            "watchdog_latched": self._watchdog_latched,
            "consecutive_timeouts": self._consecutive_timeouts,
            "degraded_detail": self._degraded_detail,
        }

    # -- internals ----------------------------------------------------------

    def _expire_cooldown(self) -> None:
        """Retire a lapsed override cooldown, arming the one-shot restore event."""
        if not self._cooldown_active:
            return
        if self._clock() < self._cooldown_expiry:
            return
        self._cooldown_active = False
        self._cooldown_expiry = 0.0
        self._restore_pending = True
        logger.info(
            "Authority override cooldown lapsed; configured level %s is available again",
            self._configured_level.value,
        )

    def _cooldown_remaining_s(self) -> float:
        """Seconds left on the override cooldown, ``0.0`` when none is active."""
        if not self._cooldown_active:
            return 0.0
        return round(max(0.0, self._cooldown_expiry - self._clock()), 1)
