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
# Checks for the remaining observable commands.
#
# Every command below moves a field that exists on ``SimState``, yet each one
# used to fall through to the rule-less early return in ``verify_command`` --
# ``verified=True`` roughly zero milliseconds after dispatch, before the sim had
# done anything and before the next 1 Hz telemetry frame. Override detection
# calls ``has_verification_rule`` to tell a real confirmation from that
# placeholder, so these rules are what let the detector open a suppression
# window it can trust.
#
# Tolerances are reused verbatim from the checks above (flaps ±5 %, heading ±1°,
# altitude ±50 ft) so the verifier and the override detector agree about what
# counts as movement.
# ---------------------------------------------------------------------------


def _check_gear_toggle(before: SimState, after: SimState, value: int) -> VerificationResult:
    toggled = after.surfaces.gear_handle != before.surfaces.gear_handle
    position = "down" if after.surfaces.gear_handle else "up"
    return VerificationResult(
        verified=toggled,
        command="GEAR_TOGGLE",
        expected=f"gear_handle flipped from {before.surfaces.gear_handle}",
        actual=f"gear_handle={after.surfaces.gear_handle}",
        message=(
            f"Gear {position} confirmed." if toggled else f"Gear did not move (still {position})."
        ),
    )


#: Nominal detent positions, used *only* to derive the commanded direction of
#: travel. Real detent percentages are aircraft-specific (a C172 has three
#: notches, an airliner five), so these are never compared as absolute targets.
_FLAPS_DETENT_PCT: dict[str, float] = {
    "FLAPS_UP": 0.0,
    "FLAPS_1": 25.0,
    "FLAPS_2": 50.0,
    "FLAPS_3": 75.0,
    "FLAPS_FULL": 100.0,
}


def _check_flaps_detent(before: SimState, after: SimState, command: str) -> VerificationResult:
    """Verify a flaps detent command moved the flaps the way it was asked to.

    Directional rather than absolute: the check asks whether ``flaps_percent``
    travelled toward the commanded detent, using the same ±5 % tolerance as
    :func:`_check_flaps_set`. When the aircraft is already at the commanded
    detent the correct outcome is *no* movement, which is verified too --
    otherwise re-selecting the current detent would always read as a failure.
    """
    nominal = _FLAPS_DETENT_PCT[command]
    start = before.surfaces.flaps_percent
    actual = after.surfaces.flaps_percent

    if nominal > start + 5:
        direction = "extend"
        moved_correctly = actual > start + 5
    elif nominal < start - 5:
        direction = "retract"
        moved_correctly = actual < start - 5
    else:
        direction = "hold"
        moved_correctly = abs(actual - start) <= 5

    if moved_correctly:
        message = f"Flaps at {actual:.0f}%."
    elif direction == "hold":
        message = f"Flaps moved to {actual:.0f}% when already at the commanded detent."
    else:
        message = f"Flaps did not {direction} (still at {actual:.0f}%)."

    return VerificationResult(
        verified=moved_correctly,
        command=command,
        expected=f"flaps_percent to {direction} from {start:.0f}%",
        actual=f"flaps_percent={actual:.0f}%",
        message=message,
    )


def _check_flaps_up(before: SimState, after: SimState, value: int) -> VerificationResult:
    return _check_flaps_detent(before, after, "FLAPS_UP")


def _check_flaps_1(before: SimState, after: SimState, value: int) -> VerificationResult:
    return _check_flaps_detent(before, after, "FLAPS_1")


def _check_flaps_2(before: SimState, after: SimState, value: int) -> VerificationResult:
    return _check_flaps_detent(before, after, "FLAPS_2")


def _check_flaps_3(before: SimState, after: SimState, value: int) -> VerificationResult:
    return _check_flaps_detent(before, after, "FLAPS_3")


def _check_flaps_full(before: SimState, after: SimState, value: int) -> VerificationResult:
    return _check_flaps_detent(before, after, "FLAPS_FULL")


def _check_spoilers_set(before: SimState, after: SimState, value: int) -> VerificationResult:
    # SimConnect spoilers range: 0-16383 (tools.py:174). Convert to percentage.
    target_pct = round(value / 16383 * 100)
    actual_pct = round(after.surfaces.spoilers_percent)
    within_tolerance = abs(actual_pct - target_pct) <= 5
    return VerificationResult(
        verified=within_tolerance,
        command="SPOILERS_SET",
        expected=f"spoilers_percent~={target_pct}%",
        actual=f"spoilers_percent={actual_pct}%",
        message=(
            f"Spoilers set to {actual_pct}%."
            if within_tolerance
            else f"Spoilers at {actual_pct}%, expected ~{target_pct}%."
        ),
    )


def _check_spoilers_toggle(before: SimState, after: SimState, value: int) -> VerificationResult:
    # Direction-free: deploying and stowing are both a successful toggle. The
    # ±5 % floor is the tolerance _check_flaps_set uses, so float jitter on the
    # 1 Hz surfaces feed cannot read as a deployment.
    start = before.surfaces.spoilers_percent
    actual = after.surfaces.spoilers_percent
    moved = abs(actual - start) > 5
    return VerificationResult(
        verified=moved,
        command="SPOILERS_TOGGLE",
        expected=f"spoilers_percent to move from {start:.0f}%",
        actual=f"spoilers_percent={actual:.0f}%",
        message=(
            f"Spoilers now at {actual:.0f}%."
            if moved
            else f"Spoilers did not move (still {actual:.0f}%)."
        ),
    )


def _check_ap_speed(before: SimState, after: SimState, value: int) -> VerificationResult:
    actual = round(after.autopilot.airspeed)
    within_tolerance = abs(actual - value) <= 2
    return VerificationResult(
        verified=within_tolerance,
        command="AP_SPD_VAR_SET",
        expected=f"airspeed~={value}kt",
        actual=f"airspeed={actual}kt",
        message=(
            f"Autopilot speed set to {actual}kt."
            if within_tolerance
            else f"Autopilot speed at {actual}kt, expected {value}kt."
        ),
    )


def _check_ap_vertical_speed(before: SimState, after: SimState, value: int) -> VerificationResult:
    actual = round(after.autopilot.vertical_speed)
    within_tolerance = abs(actual - value) <= 50
    return VerificationResult(
        verified=within_tolerance,
        command="AP_VS_VAR_SET_ENGLISH",
        expected=f"vertical_speed~={value}fpm",
        actual=f"vertical_speed={actual}fpm",
        message=(
            f"Autopilot vertical speed set to {actual}fpm."
            if within_tolerance
            else f"Autopilot vertical speed at {actual}fpm, expected {value}fpm."
        ),
    )


def _check_kohlsman(before: SimState, after: SimState, value: int) -> VerificationResult:
    # tools.py:135 sends inHg x 100, so scale back before comparing.
    target = value / 100.0
    actual = after.environment.barometer_inhg
    within_tolerance = abs(actual - target) <= 0.02
    return VerificationResult(
        verified=within_tolerance,
        command="KOHLSMAN_SET",
        expected=f"barometer_inhg~={target:.2f}",
        actual=f"barometer_inhg={actual:.2f}",
        message=(
            f"Altimeter set to {actual:.2f} inHg."
            if within_tolerance
            else f"Altimeter at {actual:.2f} inHg, expected {target:.2f}."
        ),
    )


#: Radio set command -> the ``SimState.radios`` field it drives.
_RADIO_FIELDS: dict[str, str] = {
    "COM_RADIO_SET_HZ": "com1",
    "COM2_RADIO_SET_HZ": "com2",
    "NAV1_RADIO_SET_HZ": "nav1",
    "NAV2_RADIO_SET_HZ": "nav2",
}


def _check_radio(
    before: SimState,
    after: SimState,
    value: int,
    command: str,
) -> VerificationResult:
    """Verify a radio frequency set. ``value`` is Hz (tools.py:125-131); telemetry is MHz."""
    field_name = _RADIO_FIELDS[command]
    target = value / 1_000_000
    actual = float(getattr(after.radios, field_name))
    within_tolerance = abs(actual - target) <= 0.005
    label = field_name.upper()
    return VerificationResult(
        verified=within_tolerance,
        command=command,
        expected=f"{field_name}~={target:.3f}MHz",
        actual=f"{field_name}={actual:.3f}MHz",
        message=(
            f"{label} set to {actual:.3f}."
            if within_tolerance
            else f"{label} at {actual:.3f}, expected {target:.3f}."
        ),
    )


def _check_com1(before: SimState, after: SimState, value: int) -> VerificationResult:
    return _check_radio(before, after, value, "COM_RADIO_SET_HZ")


def _check_com2(before: SimState, after: SimState, value: int) -> VerificationResult:
    return _check_radio(before, after, value, "COM2_RADIO_SET_HZ")


def _check_nav1(before: SimState, after: SimState, value: int) -> VerificationResult:
    return _check_radio(before, after, value, "NAV1_RADIO_SET_HZ")


def _check_nav2(before: SimState, after: SimState, value: int) -> VerificationResult:
    return _check_radio(before, after, value, "NAV2_RADIO_SET_HZ")


# ---------------------------------------------------------------------------
# Command → verification check mapping
# ---------------------------------------------------------------------------

VERIFICATION_CHECKS: dict[str, VerificationCheck] = {
    "GEAR_DOWN": _check_gear_down,
    "GEAR_UP": _check_gear_up,
    "GEAR_TOGGLE": _check_gear_toggle,
    "FLAPS_SET": _check_flaps_set,
    "FLAPS_UP": _check_flaps_up,
    "FLAPS_1": _check_flaps_1,
    "FLAPS_2": _check_flaps_2,
    "FLAPS_3": _check_flaps_3,
    "FLAPS_FULL": _check_flaps_full,
    "SPOILERS_SET": _check_spoilers_set,
    "SPOILERS_TOGGLE": _check_spoilers_toggle,
    "AP_MASTER": _check_ap_master,
    "HEADING_BUG_SET": _check_heading_bug,
    "AP_ALT_VAR_SET_ENGLISH": _check_alt_set,
    "AP_VS_VAR_SET_ENGLISH": _check_ap_vertical_speed,
    "AP_SPD_VAR_SET": _check_ap_speed,
    "KOHLSMAN_SET": _check_kohlsman,
    "COM_RADIO_SET_HZ": _check_com1,
    "COM2_RADIO_SET_HZ": _check_com2,
    "NAV1_RADIO_SET_HZ": _check_nav1,
    "NAV2_RADIO_SET_HZ": _check_nav2,
    "THROTTLE_SET": _check_throttle,
}


#: The ``expected`` value returned when a command has no registered check.
#: Named rather than inlined because ``override_detector.py`` must be able to
#: distinguish this placeholder from a confirmation the aircraft actually moved.
NO_RULE_EXPECTED: str = "no verification rule"


def has_verification_rule(command: str) -> bool:
    """Whether ``command`` has a real check, as opposed to the rule-less early return.

    Override detection uses this to pick a suppression lead. A command with a
    rule may still be polling when its change lands, so it gets the full verify
    timeout; a rule-less command "confirms" in roughly zero milliseconds and its
    ``verified=True`` is no evidence the aircraft moved at all.
    """
    return command in VERIFICATION_CHECKS


class CommandVerifier:
    """Polls telemetry to verify aircraft commands took effect."""

    def __init__(
        self,
        sim_client: TelemetryClient,
        timeout: float = 3.0,
        poll_interval: float = 0.5,
    ) -> None:
        """Build a verifier.

        Args:
            sim_client: Telemetry source polled for post-command state.
            timeout: Seconds to keep polling before giving up. The default matches
                ``Settings.authority_verify_timeout_s``; composition roots pass that
                setting explicitly. Deliberately a plain parameter -- this module
                reads no ``Settings``, so it stays importable without config.
            poll_interval: Seconds between telemetry polls.
        """
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
                expected=NO_RULE_EXPECTED,
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
