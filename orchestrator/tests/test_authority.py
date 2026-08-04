"""Tests for the authority state machine.

Time is injected, never slept. There is no freezegun or time-machine in any
extra of ``orchestrator/pyproject.toml``, and the alternative -- shrinking real
timeouts, as ``test_command_verifier.py`` does -- would make a 120 s rolling
cooldown either slow or untestable.

The structural guard at the bottom pins the property that makes this module
usable from ``sim_client.py``: it imports nothing from the orchestrator package.
Lose that and the import cycle forces a duck-typed authority object at the floor,
which is exactly the gate this phase exists to make un-bypassable.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from orchestrator.authority import (
    SUPPORTED_AUTHORITY_LEVELS,
    AuthorityLevel,
    AuthorityReason,
    AuthorityState,
    parse_authority_level,
)

AUTHORITY_SOURCE = Path(inspect.getfile(AuthorityState)).read_text()


class _FakeClock:
    """Advanceable stand-in for ``time.monotonic``."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _state(level: AuthorityLevel = AuthorityLevel.FULL, **kwargs: object) -> AuthorityState:
    return AuthorityState(level, **kwargs)  # type: ignore[arg-type]


class TestEnums:
    def test_authority_level_has_exactly_three_members(self) -> None:
        assert len(AuthorityLevel) == 3

    def test_authority_reason_has_exactly_four_members(self) -> None:
        # DEGRADED is a *reason*, not a fourth level -- D-17 rejected a fourth
        # authority state because it would thread through gate, floor, status and UI.
        assert len(AuthorityReason) == 4
        assert AuthorityReason.DEGRADED in set(AuthorityReason)

    def test_supported_levels_stay_in_sync_with_the_enum(self) -> None:
        assert tuple(level.value for level in AuthorityLevel) == SUPPORTED_AUTHORITY_LEVELS

    def test_levels_are_lowercase_strings(self) -> None:
        assert SUPPORTED_AUTHORITY_LEVELS == ("advisory", "assisted", "full")
        assert AuthorityLevel.FULL == "full"


class TestParseAuthorityLevel:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("advisory", AuthorityLevel.ADVISORY),
            ("ASSISTED", AuthorityLevel.ASSISTED),
            ("  Full  ", AuthorityLevel.FULL),
        ],
    )
    def test_parses_case_insensitively_after_stripping(
        self, raw: str, expected: AuthorityLevel
    ) -> None:
        assert parse_authority_level(raw) is expected

    def test_unknown_value_raises_listing_the_supported_levels(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            parse_authority_level("banana")

        message = str(excinfo.value)
        for level in SUPPORTED_AUTHORITY_LEVELS:
            assert level in message
        assert "banana" in message

    @pytest.mark.parametrize("bogus", ["", "  ", "fully", "FULLL", "read-only", "none"])
    def test_never_falls_back_to_a_default(self, bogus: str) -> None:
        # A silent fallback here would grant authority to a typo.
        with pytest.raises(ValueError):
            parse_authority_level(bogus)


class TestConfiguredLevel:
    def test_fresh_state_reports_configured_level_and_reason(self) -> None:
        state = _state(AuthorityLevel.FULL)
        assert state.level is AuthorityLevel.FULL
        assert state.reason is AuthorityReason.CONFIG
        assert state.configured_level is AuthorityLevel.FULL
        assert state.degraded is False
        assert state.degraded_detail == ""
        assert state.watchdog_latched is False
        assert state.consecutive_timeouts == 0

    def test_assisted_is_reported_verbatim(self) -> None:
        state = _state(AuthorityLevel.ASSISTED)
        assert state.level is AuthorityLevel.ASSISTED
        assert state.reason is AuthorityReason.CONFIG


class TestWatchdog:
    def test_latches_on_the_nth_consecutive_timeout(self) -> None:
        state = _state(AuthorityLevel.FULL, watchdog_max_timeouts=3)

        assert state.record_command_timeout() is False
        assert state.record_command_timeout() is False
        assert state.level is AuthorityLevel.FULL

        assert state.record_command_timeout() is True
        assert state.level is AuthorityLevel.ADVISORY
        assert state.reason is AuthorityReason.WATCHDOG
        assert state.watchdog_latched is True

    def test_further_timeouts_after_a_latch_return_false(self) -> None:
        state = _state(AuthorityLevel.FULL, watchdog_max_timeouts=2)
        state.record_command_timeout()
        assert state.record_command_timeout() is True
        assert state.record_command_timeout() is False
        assert state.watchdog_latched is True

    def test_success_resets_the_counter_before_a_latch(self) -> None:
        state = _state(AuthorityLevel.FULL, watchdog_max_timeouts=3)
        state.record_command_timeout()
        state.record_command_timeout()
        state.record_command_success()
        assert state.consecutive_timeouts == 0

        assert state.record_command_timeout() is False
        assert state.level is AuthorityLevel.FULL

    def test_success_does_not_clear_an_existing_latch(self) -> None:
        # D-18: a latch that stops command issuance can never produce the
        # successful ack that would otherwise clear it.
        state = _state(AuthorityLevel.FULL, watchdog_max_timeouts=1)
        assert state.record_command_timeout() is True

        state.record_command_success()
        assert state.watchdog_latched is True
        assert state.level is AuthorityLevel.ADVISORY
        assert state.reason is AuthorityReason.WATCHDOG

    def test_clear_watchdog_restores_the_configured_level(self) -> None:
        state = _state(AuthorityLevel.FULL, watchdog_max_timeouts=1)
        state.record_command_timeout()

        assert state.clear_watchdog() is True
        assert state.watchdog_latched is False
        assert state.consecutive_timeouts == 0
        assert state.level is AuthorityLevel.FULL
        assert state.reason is AuthorityReason.CONFIG

    def test_clear_watchdog_returns_false_when_nothing_was_latched(self) -> None:
        state = _state(AuthorityLevel.FULL)
        assert state.clear_watchdog() is False


class TestOverrideCooldown:
    def test_override_drops_to_advisory_and_reports_the_reason(self) -> None:
        clock = _FakeClock()
        state = _state(AuthorityLevel.FULL, override_cooldown_s=120.0, clock=clock)

        assert state.record_override() is True
        assert state.level is AuthorityLevel.ADVISORY
        assert state.reason is AuthorityReason.OVERRIDE

        clock.advance(60.0)
        assert state.reason is AuthorityReason.OVERRIDE

    def test_a_second_override_rolls_the_expiry_forward(self) -> None:
        clock = _FakeClock()
        state = _state(AuthorityLevel.FULL, override_cooldown_s=120.0, clock=clock)
        state.record_override()

        clock.advance(60.0)
        # Already advisory, so this call causes no *drop* -- but it must still extend.
        assert state.record_override() is False

        clock.advance(90.0)  # t=150, past the original 120 s expiry
        assert state.level is AuthorityLevel.ADVISORY
        assert state.reason is AuthorityReason.OVERRIDE

        clock.advance(31.0)  # t=181, past the rolled 180 s expiry
        assert state.level is AuthorityLevel.FULL
        assert state.reason is AuthorityReason.CONFIG

    def test_cooldown_expires_lazily_with_no_background_task(self) -> None:
        clock = _FakeClock()
        state = _state(AuthorityLevel.ASSISTED, override_cooldown_s=10.0, clock=clock)
        state.record_override()

        clock.advance(10.0)
        assert state.level is AuthorityLevel.ASSISTED
        assert state.reason is AuthorityReason.CONFIG

    def test_summary_reports_remaining_cooldown_rounded(self) -> None:
        clock = _FakeClock()
        state = _state(AuthorityLevel.FULL, override_cooldown_s=120.0, clock=clock)
        state.record_override()
        clock.advance(30.04)

        assert state.summary()["cooldown_remaining_s"] == 90.0

    def test_summary_reports_zero_cooldown_when_none_is_active(self) -> None:
        assert _state(AuthorityLevel.FULL).summary()["cooldown_remaining_s"] == 0.0


class TestRestoreEvent:
    def test_fires_once_and_only_once_after_the_cooldown_lapses(self) -> None:
        clock = _FakeClock()
        state = _state(AuthorityLevel.FULL, override_cooldown_s=10.0, clock=clock)
        state.record_override()

        assert state.take_restore_event() is False

        clock.advance(11.0)
        assert state.take_restore_event() is True
        assert state.take_restore_event() is False

    def test_does_not_fire_while_a_watchdog_latch_holds_authority_down(self) -> None:
        clock = _FakeClock()
        state = _state(
            AuthorityLevel.FULL, override_cooldown_s=10.0, watchdog_max_timeouts=1, clock=clock
        )
        state.record_override()
        state.record_command_timeout()

        clock.advance(11.0)
        assert state.take_restore_event() is False
        assert state.reason is AuthorityReason.WATCHDOG

        state.clear_watchdog()
        assert state.take_restore_event() is True

    def test_a_new_override_disarms_a_pending_restore(self) -> None:
        clock = _FakeClock()
        state = _state(AuthorityLevel.FULL, override_cooldown_s=10.0, clock=clock)
        state.record_override()
        clock.advance(11.0)
        state.record_override()

        assert state.take_restore_event() is False


class TestPrecedence:
    def test_degraded_beats_latch_beats_cooldown_beats_config(self) -> None:
        clock = _FakeClock()
        state = _state(
            AuthorityLevel.FULL, override_cooldown_s=10.0, watchdog_max_timeouts=1, clock=clock
        )

        assert state.reason is AuthorityReason.CONFIG

        state.record_override()
        assert state.reason is AuthorityReason.OVERRIDE

        state.record_command_timeout()
        assert state.reason is AuthorityReason.WATCHDOG  # latch outranks the cooldown

        degraded = AuthorityState.degraded_fallback("boom")
        degraded.record_override()
        degraded.record_command_timeout()
        assert degraded.reason is AuthorityReason.DEGRADED  # degraded outranks both

    def test_a_lapsed_cooldown_does_not_unmask_a_latch(self) -> None:
        clock = _FakeClock()
        state = _state(
            AuthorityLevel.FULL, override_cooldown_s=10.0, watchdog_max_timeouts=1, clock=clock
        )
        state.record_override()
        state.record_command_timeout()

        clock.advance(100.0)
        assert state.level is AuthorityLevel.ADVISORY
        assert state.reason is AuthorityReason.WATCHDOG


class TestDegradedFallback:
    def test_is_advisory_and_degraded(self) -> None:
        state = AuthorityState.degraded_fallback("boom")
        assert state.level is AuthorityLevel.ADVISORY
        assert state.reason is AuthorityReason.DEGRADED
        assert state.degraded is True
        assert state.degraded_detail == "boom"

    def test_logs_at_error_so_a_degraded_start_is_never_silent(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("ERROR", logger="orchestrator.authority"):
            AuthorityState.degraded_fallback("settings blew up")

        assert any("settings blew up" in record.getMessage() for record in caplog.records)

    def test_no_method_lifts_it(self) -> None:
        clock = _FakeClock()
        state = AuthorityState.degraded_fallback("boom")
        state._clock = clock  # the fallback takes no clock; degraded ignores time anyway

        assert state.clear_watchdog() is False
        state.record_command_success()
        state.record_override()
        clock.advance(10_000.0)

        assert state.level is AuthorityLevel.ADVISORY
        assert state.reason is AuthorityReason.DEGRADED
        assert state.take_restore_event() is False

    def test_record_override_reports_no_drop_because_it_is_already_advisory(self) -> None:
        assert AuthorityState.degraded_fallback("boom").record_override() is False

    def test_constructs_when_parse_authority_level_is_broken(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The fallback runs inside the `except` block handling the failure of the
        # normal construction path, so it must depend on nothing that can fail.
        def _explode(_value: str) -> AuthorityLevel:
            raise RuntimeError("parse is broken")

        monkeypatch.setattr("orchestrator.authority.parse_authority_level", _explode)

        state = AuthorityState.degraded_fallback("construction failed")
        assert state.level is AuthorityLevel.ADVISORY
        assert state.reason is AuthorityReason.DEGRADED


class TestSummary:
    def test_key_set_is_exact(self) -> None:
        assert set(_state(AuthorityLevel.FULL).summary()) == {
            "level",
            "reason",
            "configured_level",
            "cooldown_remaining_s",
            "watchdog_latched",
            "consecutive_timeouts",
            "degraded_detail",
        }

    def test_values_are_json_friendly_primitives(self) -> None:
        clock = _FakeClock()
        state = _state(AuthorityLevel.ASSISTED, override_cooldown_s=20.0, clock=clock)
        state.record_override()
        state.record_command_timeout()

        summary = state.summary()
        assert summary["level"] == "advisory"
        assert summary["reason"] == "override"
        assert summary["configured_level"] == "assisted"
        assert summary["cooldown_remaining_s"] == 20.0
        assert summary["watchdog_latched"] is False
        assert summary["consecutive_timeouts"] == 1
        assert summary["degraded_detail"] == ""

    def test_degraded_detail_is_always_present(self) -> None:
        healthy = _state(AuthorityLevel.FULL).summary()
        degraded = AuthorityState.degraded_fallback("boom").summary()

        assert healthy["degraded_detail"] == ""
        assert degraded["degraded_detail"] == "boom"
        assert degraded["reason"] == "degraded"


class TestNoPackageImportsRegression:
    """`authority.py` must stay importable from the base of the dependency graph."""

    def test_source_has_no_orchestrator_package_imports(self) -> None:
        offenders = [
            line
            for line in AUTHORITY_SOURCE.splitlines()
            if re.match(r"^\s*(from \.|from orchestrator|import orchestrator)", line)
        ]
        assert offenders == [], (
            "authority.py imported from the orchestrator package: "
            f"{offenders}. sim_client.py consumes AuthorityState and sits at the base "
            "of the dependency graph, so this creates an import cycle."
        )

    def test_module_only_needs_the_standard_library(self) -> None:
        for forbidden in ("SimState", "Settings", "websockets", "pydantic"):
            assert f"import {forbidden}" not in AUTHORITY_SOURCE
