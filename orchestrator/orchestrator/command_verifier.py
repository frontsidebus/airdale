"""Post-execution verification of aircraft control commands.

After a SimConnect command is acknowledged, the verifier polls telemetry
to confirm the aircraft actually changed state. This catches cases where
the sim acknowledged the command but the aircraft didn't respond (e.g.,
gear won't extend above Vle, autopilot won't engage without valid nav
source, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from .sim_client import SimState, TelemetryClient

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Outcome of a post-command state verification check."""

    verified: bool
    command: str
    expected: str
    actual: str
    message: str


# ---------------------------------------------------------------------------
# Verification check type: given (state_before, state_after, command_value)
# return a VerificationResult.
# ---------------------------------------------------------------------------

VerificationCheck = Callable[[SimState, SimState, int], VerificationResult]


def _check_gear_down(before: SimState, after: SimState, value: int) -> VerificationResult:
    return VerificationResult(
        verified=after.surfaces.gear_handle is True,
        command="GEAR_DOWN",
        expected="gear_handle=True",
        actual=f"gear_handle={after.surfaces.gear_handle}",
        message="Gear down confirmed." if after.surfaces.gear_handle else "Gear failed to extend.",
    )


def _check_gear_up(before: SimState, after: SimState, value: int) -> VerificationResult:
    return VerificationResult(
        verified=after.surfaces.gear_handle is False,
        command="GEAR_UP",
        expected="gear_handle=False",
        actual=f"gear_handle={after.surfaces.gear_handle}",
        message=(
            "Gear up confirmed." if not after.surfaces.gear_handle else "Gear failed to retract."
        ),
    )


def _check_flaps_set(before: SimState, after: SimState, value: int) -> VerificationResult:
    # SimConnect flaps range: 0-16383. Convert to percentage for comparison.
    target_pct = round(value / 16383 * 100)
    actual_pct = round(after.surfaces.flaps_percent)
    within_tolerance = abs(actual_pct - target_pct) <= 5
    return VerificationResult(
        verified=within_tolerance,
        command="FLAPS_SET",
        expected=f"flaps_percent~={target_pct}%",
        actual=f"flaps_percent={actual_pct}%",
        message=(
            f"Flaps set to {actual_pct}%."
            if within_tolerance
            else f"Flaps at {actual_pct}%, expected ~{target_pct}%."
        ),
    )


def _check_ap_master(before: SimState, after: SimState, value: int) -> VerificationResult:
    toggled = after.autopilot.master != before.autopilot.master
    new_state = "ON" if after.autopilot.master else "OFF"
    return VerificationResult(
        verified=toggled,
        command="AP_MASTER",
        expected=f"autopilot.master flipped from {before.autopilot.master}",
        actual=f"autopilot.master={after.autopilot.master}",
        message=(
            f"Autopilot {new_state}."
            if toggled
            else f"Autopilot did not toggle (still {new_state})."
        ),
    )


def _check_heading_bug(before: SimState, after: SimState, value: int) -> VerificationResult:
    actual = round(after.autopilot.heading)
    within_tolerance = abs(actual - value) <= 1 or abs(actual - value) >= 359
    return VerificationResult(
        verified=within_tolerance,
        command="HEADING_BUG_SET",
        expected=f"heading~={value}°",
        actual=f"heading={actual}°",
        message=(
            f"Heading bug set to {actual}°."
            if within_tolerance
            else f"Heading bug at {actual}°, expected {value}°."
        ),
    )


def _check_alt_set(before: SimState, after: SimState, value: int) -> VerificationResult:
    actual = round(after.autopilot.altitude)
    within_tolerance = abs(actual - value) <= 50
    return VerificationResult(
        verified=within_tolerance,
        command="AP_ALT_VAR_SET_ENGLISH",
        expected=f"altitude~={value}ft",
        actual=f"altitude={actual}ft",
        message=(
            f"Altitude selector set to {actual}ft."
            if within_tolerance
            else f"Altitude selector at {actual}ft, expected {value}ft."
        ),
    )


def _check_throttle(before: SimState, after: SimState, value: int) -> VerificationResult:
    # Check that RPM moved in the expected direction relative to before.
    before_engines = before.engines.active_engines
    after_engines = after.engines.active_engines
    if not before_engines or not after_engines:
        return VerificationResult(
            verified=False,
            command="THROTTLE_SET",
            expected="RPM change in expected direction",
            actual="no active engines",
            message="Cannot verify throttle — no active engines detected.",
        )
    before_rpm = before_engines[0].rpm
    after_rpm = after_engines[0].rpm
    # value is 0-16383; midpoint is ~8192
    if value > 8192:
        moved_correctly = after_rpm >= before_rpm - 50  # allow small RPM settling
    elif value < 8192:
        moved_correctly = after_rpm <= before_rpm + 50
    else:
        moved_correctly = True  # midpoint, any RPM is acceptable
    return VerificationResult(
        verified=moved_correctly,
        command="THROTTLE_SET",
        expected="RPM moved in expected direction",
        actual=f"RPM {before_rpm:.0f} -> {after_rpm:.0f}",
        message=(
            f"Throttle response confirmed (RPM {after_rpm:.0f})."
            if moved_correctly
            else f"Throttle may not have responded (RPM {before_rpm:.0f} -> {after_rpm:.0f})."
        ),
    )


# ---------------------------------------------------------------------------
# Command → verification check mapping
# ---------------------------------------------------------------------------

VERIFICATION_CHECKS: dict[str, VerificationCheck] = {
    "GEAR_DOWN": _check_gear_down,
    "GEAR_UP": _check_gear_up,
    "FLAPS_SET": _check_flaps_set,
    "AP_MASTER": _check_ap_master,
    "HEADING_BUG_SET": _check_heading_bug,
    "AP_ALT_VAR_SET_ENGLISH": _check_alt_set,
    "THROTTLE_SET": _check_throttle,
}


class CommandVerifier:
    """Polls telemetry to verify aircraft commands took effect."""

    def __init__(
        self,
        sim_client: TelemetryClient,
        timeout: float = 3.0,
        poll_interval: float = 0.5,
    ) -> None:
        self._sim_client = sim_client
        self._timeout = timeout
        self._poll_interval = poll_interval

    async def verify_command(
        self,
        command: str,
        value: int,
        sim_state_before: SimState,
    ) -> VerificationResult:
        """Poll telemetry and check if the command changed the expected state.

        Returns a VerificationResult. If the command has no registered check,
        returns a verified=True result (we can't verify what we can't measure).
        """
        check = VERIFICATION_CHECKS.get(command)
        if check is None:
            return VerificationResult(
                verified=True,
                command=command,
                expected="no verification rule",
                actual="skipped",
                message=f"No verification rule for {command}; assumed OK.",
            )

        elapsed = 0.0
        last_result: VerificationResult | None = None

        while elapsed < self._timeout:
            await asyncio.sleep(self._poll_interval)
            elapsed += self._poll_interval

            try:
                state_after = await self._sim_client.get_state()
            except ConnectionError:
                logger.warning("Lost telemetry connection during verification")
                continue

            last_result = check(sim_state_before, state_after, value)
            if last_result.verified:
                logger.info(
                    "Command %s verified after %.1fs: %s",
                    command,
                    elapsed,
                    last_result.message,
                )
                return last_result

        # Timed out — return the last check result (or a timeout result)
        if last_result is not None:
            last_result.message = (
                f"Verification timed out after {self._timeout}s: {last_result.message}"
            )
            logger.warning("Command %s verification timed out: %s", command, last_result.message)
            return last_result

        return VerificationResult(
            verified=False,
            command=command,
            expected="state change",
            actual="no telemetry received",
            message=f"Verification timed out after {self._timeout}s — no telemetry available.",
        )
