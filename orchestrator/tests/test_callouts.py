"""Tests for the proactive callout engine."""

from __future__ import annotations

from orchestrator.callouts import (
    CalloutEngine,
    CalloutRule,
    _crossed_above,
    _crossed_below,
)
from orchestrator.sim_client import (
    Attitude,
    AutopilotState,
    FlightPhase,
    Position,
    SimState,
    Speeds,
    SurfaceState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    *,
    ias: float = 0.0,
    vs: float = 0.0,
    alt_msl: float = 0.0,
    alt_agl: float = 0.0,
    bank: float = 0.0,
    ground_speed: float = 0.0,
    ap_master: bool = False,
    ap_altitude: float = 0.0,
    gear_handle: bool = False,
    flaps_percent: float = 0.0,
) -> SimState:
    return SimState(
        position=Position(altitude_msl=alt_msl, altitude_agl=alt_agl),
        attitude=Attitude(bank=bank),
        speeds=Speeds(
            indicated_airspeed=ias,
            vertical_speed=vs,
            ground_speed=ground_speed,
        ),
        autopilot=AutopilotState(master=ap_master, altitude=ap_altitude),
        surfaces=SurfaceState(
            gear_handle=gear_handle,
            flaps_percent=flaps_percent,
        ),
    )


# ---------------------------------------------------------------------------
# Crossing detection helpers
# ---------------------------------------------------------------------------


class TestCrossedAbove:
    def test_crosses_above(self) -> None:
        assert _crossed_above(81.0, 79.0, 80.0) is True

    def test_exactly_at_threshold(self) -> None:
        assert _crossed_above(80.0, 79.0, 80.0) is True

    def test_already_above(self) -> None:
        assert _crossed_above(82.0, 81.0, 80.0) is False

    def test_below_threshold(self) -> None:
        assert _crossed_above(78.0, 77.0, 80.0) is False

    def test_no_previous(self) -> None:
        assert _crossed_above(81.0, None, 80.0) is False


class TestCrossedBelow:
    def test_crosses_below(self) -> None:
        assert _crossed_below(499.0, 501.0, 500.0) is True

    def test_exactly_at_threshold_from_above(self) -> None:
        # previous >= threshold > current => True when current < threshold
        assert _crossed_below(499.0, 500.0, 500.0) is True

    def test_at_threshold_not_below(self) -> None:
        # current == threshold => threshold > current is False
        assert _crossed_below(500.0, 501.0, 500.0) is False

    def test_already_below(self) -> None:
        assert _crossed_below(490.0, 495.0, 500.0) is False

    def test_no_previous(self) -> None:
        assert _crossed_below(499.0, None, 500.0) is False


# ---------------------------------------------------------------------------
# Takeoff callouts
# ---------------------------------------------------------------------------


class TestTakeoffCallouts:
    def test_v1_fires_at_80kt(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.TAKEOFF)

        prev = _make_state(ias=78.0)
        cur = _make_state(ias=81.0)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "V1" in names

    def test_rotate_fires_at_85kt(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.TAKEOFF)

        prev = _make_state(ias=83.0)
        cur = _make_state(ias=86.0)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "ROTATE" in names

    def test_v1_and_rotate_both_fire_when_crossing_both(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.TAKEOFF)

        prev = _make_state(ias=70.0)
        cur = _make_state(ias=90.0)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "V1" in names
        assert "ROTATE" in names

    def test_positive_rate(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.TAKEOFF)

        cur = _make_state(vs=200, alt_agl=50)
        callouts = engine.update(cur, None)

        names = [c.name for c in callouts]
        assert "POSITIVE_RATE" in names

    def test_gear_up(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.TAKEOFF)

        cur = _make_state(vs=400, alt_agl=150)
        callouts = engine.update(cur, None)

        names = [c.name for c in callouts]
        assert "GEAR_UP" in names

    def test_v1_does_not_fire_in_cruise(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CRUISE)

        prev = _make_state(ias=78.0)
        cur = _make_state(ias=81.0)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "V1" not in names

    def test_v1_one_shot(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.TAKEOFF)

        prev = _make_state(ias=78.0)
        cur = _make_state(ias=81.0)
        engine.update(cur, prev)

        # Fire again - should NOT trigger
        prev2 = _make_state(ias=78.0)
        cur2 = _make_state(ias=81.0)
        callouts = engine.update(cur2, prev2)

        names = [c.name for c in callouts]
        assert "V1" not in names


# ---------------------------------------------------------------------------
# Climb callouts
# ---------------------------------------------------------------------------


class TestClimbCallouts:
    def test_altitude_callout_every_1000ft(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CLIMB)

        prev = _make_state(alt_msl=2900)
        cur = _make_state(alt_msl=3050)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "ALTITUDE_CALLOUT" in names
        msg = next(c for c in callouts if c.name == "ALTITUDE_CALLOUT")
        assert "3000" in msg.message

    def test_altitude_callout_does_not_fire_within_same_thousand(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CLIMB)

        prev = _make_state(alt_msl=3100)
        cur = _make_state(alt_msl=3500)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "ALTITUDE_CALLOUT" not in names

    def test_altitude_callout_not_on_descent(self) -> None:
        """Only fires when climbing (cur > prev in thousands)."""
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CLIMB)

        prev = _make_state(alt_msl=4050)
        cur = _make_state(alt_msl=3950)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "ALTITUDE_CALLOUT" not in names

    def test_level_off_with_autopilot(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CLIMB)

        cur = _make_state(alt_msl=9850, ap_master=True, ap_altitude=10000)
        callouts = engine.update(cur, None)

        names = [c.name for c in callouts]
        assert "LEVEL_OFF" in names

    def test_level_off_not_without_autopilot(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CLIMB)

        cur = _make_state(alt_msl=9850, ap_master=False, ap_altitude=10000)
        callouts = engine.update(cur, None)

        names = [c.name for c in callouts]
        assert "LEVEL_OFF" not in names


# ---------------------------------------------------------------------------
# Approach callouts
# ---------------------------------------------------------------------------


class TestApproachCallouts:
    def test_1000ft_callout(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.APPROACH)

        prev = _make_state(alt_agl=1050, vs=-500)
        cur = _make_state(alt_agl=990, vs=-500)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "APPROACH_1000" in names

    def test_500ft_callout(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.APPROACH)

        prev = _make_state(alt_agl=520, vs=-500)
        cur = _make_state(alt_agl=490, vs=-500)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "APPROACH_500" in names

    def test_minimums_callout(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.APPROACH)

        prev = _make_state(alt_agl=210, vs=-500)
        cur = _make_state(alt_agl=195, vs=-500)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "MINIMUMS" in names

    def test_100ft_callout(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.APPROACH)

        prev = _make_state(alt_agl=110, vs=-500)
        cur = _make_state(alt_agl=95, vs=-500)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "APPROACH_100" in names

    def test_no_callout_when_climbing(self) -> None:
        """Approach callouts should not fire if VS > 0 (go-around)."""
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.APPROACH)

        prev = _make_state(alt_agl=520, vs=500)
        cur = _make_state(alt_agl=490, vs=500)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "APPROACH_500" not in names


# ---------------------------------------------------------------------------
# Landing callouts
# ---------------------------------------------------------------------------


class TestLandingCallouts:
    def test_50ft_callout(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.LANDING)

        prev = _make_state(alt_agl=55)
        cur = _make_state(alt_agl=48)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "LANDING_50" in names

    def test_30ft_callout(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.LANDING)

        prev = _make_state(alt_agl=35)
        cur = _make_state(alt_agl=28)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "LANDING_30" in names

    def test_10ft_callout(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.LANDING)

        prev = _make_state(alt_agl=12)
        cur = _make_state(alt_agl=8)
        callouts = engine.update(cur, prev)

        names = [c.name for c in callouts]
        assert "LANDING_10" in names


# ---------------------------------------------------------------------------
# Any-phase safety callouts
# ---------------------------------------------------------------------------


class TestSafetyCallouts:
    def test_overspeed_below_10000(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CLIMB)

        cur = _make_state(ias=260, alt_msl=8000)
        callouts = engine.update(cur, None)

        names = [c.name for c in callouts]
        assert "OVERSPEED" in names

    def test_no_overspeed_above_10000(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CRUISE)

        cur = _make_state(ias=300, alt_msl=15000)
        callouts = engine.update(cur, None)

        names = [c.name for c in callouts]
        assert "OVERSPEED" not in names

    def test_no_overspeed_under_250(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CLIMB)

        cur = _make_state(ias=240, alt_msl=8000)
        callouts = engine.update(cur, None)

        names = [c.name for c in callouts]
        assert "OVERSPEED" not in names

    def test_bank_angle(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CRUISE)

        cur = _make_state(bank=50)
        callouts = engine.update(cur, None)

        names = [c.name for c in callouts]
        assert "BANK_ANGLE" in names

    def test_bank_angle_negative(self) -> None:
        """Left bank (negative) should also trigger."""
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CRUISE)

        cur = _make_state(bank=-48)
        callouts = engine.update(cur, None)

        names = [c.name for c in callouts]
        assert "BANK_ANGLE" in names

    def test_no_bank_angle_under_45(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CRUISE)

        cur = _make_state(bank=40)
        callouts = engine.update(cur, None)

        names = [c.name for c in callouts]
        assert "BANK_ANGLE" not in names

    def test_sink_rate(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.APPROACH)

        cur = _make_state(vs=-2500, alt_agl=1500)
        callouts = engine.update(cur, None)

        names = [c.name for c in callouts]
        assert "SINK_RATE" in names

    def test_no_sink_rate_above_2500_agl(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.APPROACH)

        cur = _make_state(vs=-2500, alt_agl=3000)
        callouts = engine.update(cur, None)

        names = [c.name for c in callouts]
        assert "SINK_RATE" not in names

    def test_no_sink_rate_above_minus_2000(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.APPROACH)

        cur = _make_state(vs=-1500, alt_agl=1500)
        callouts = engine.update(cur, None)

        names = [c.name for c in callouts]
        assert "SINK_RATE" not in names

    def test_safety_callouts_fire_in_any_phase(self) -> None:
        """Overspeed, bank angle, sink rate should work in multiple phases."""
        for phase in [FlightPhase.TAKEOFF, FlightPhase.CLIMB, FlightPhase.CRUISE]:
            engine = CalloutEngine()
            engine.on_phase_change(phase)

            cur = _make_state(bank=50)
            callouts = engine.update(cur, None)
            names = [c.name for c in callouts]
            assert "BANK_ANGLE" in names, f"BANK_ANGLE should fire in {phase}"


# ---------------------------------------------------------------------------
# Phase change and one-shot behavior
# ---------------------------------------------------------------------------


class TestPhaseChange:
    def test_phase_change_resets_one_shot(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.TAKEOFF)

        prev = _make_state(ias=78.0)
        cur = _make_state(ias=81.0)
        engine.update(cur, prev)
        assert "V1" in engine.triggered_names

        # Change phase and back
        engine.on_phase_change(FlightPhase.CLIMB)
        assert "V1" not in engine.triggered_names

        engine.on_phase_change(FlightPhase.TAKEOFF)
        callouts = engine.update(cur, prev)
        names = [c.name for c in callouts]
        assert "V1" in names

    def test_phase_change_same_phase_no_op(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.TAKEOFF)

        prev = _make_state(ias=78.0)
        cur = _make_state(ias=81.0)
        engine.update(cur, prev)
        assert "V1" in engine.triggered_names

        # "Change" to same phase - should NOT reset
        engine.on_phase_change(FlightPhase.TAKEOFF)
        assert "V1" in engine.triggered_names


# ---------------------------------------------------------------------------
# Cooldown behavior
# ---------------------------------------------------------------------------


class TestCooldown:
    def test_cooldown_prevents_rapid_retrigger(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CRUISE)

        cur = _make_state(bank=50)
        callouts1 = engine.update(cur, None)
        assert any(c.name == "BANK_ANGLE" for c in callouts1)

        # Immediately again - should be blocked by cooldown
        callouts2 = engine.update(cur, None)
        assert not any(c.name == "BANK_ANGLE" for c in callouts2)

    def test_cooldown_expires(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.CRUISE)

        cur = _make_state(bank=50)
        engine.update(cur, None)

        # Fake time advancement past cooldown
        for name in engine._last_triggered:
            engine._last_triggered[name] -= 10.0

        callouts = engine.update(cur, None)
        assert any(c.name == "BANK_ANGLE" for c in callouts)


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------


class TestPriority:
    def test_callouts_sorted_by_priority_descending(self) -> None:
        low_rule = CalloutRule(
            name="LOW",
            phase=None,
            condition=lambda s, p: True,
            message="low",
            priority=1,
        )
        high_rule = CalloutRule(
            name="HIGH",
            phase=None,
            condition=lambda s, p: True,
            message="high",
            priority=10,
        )
        engine = CalloutEngine(rules=[low_rule, high_rule])

        callouts = engine.update(_make_state(), None)
        assert callouts[0].name == "HIGH"
        assert callouts[1].name == "LOW"


# ---------------------------------------------------------------------------
# Custom rules
# ---------------------------------------------------------------------------


class TestCustomRules:
    def test_custom_rule(self) -> None:
        rule = CalloutRule(
            name="CUSTOM",
            phase=FlightPhase.CRUISE,
            condition=lambda s, p: s.speeds.indicated_airspeed > 200,
            message="Fast cruise",
            priority=5,
        )
        engine = CalloutEngine(rules=[rule])
        engine.on_phase_change(FlightPhase.CRUISE)

        cur = _make_state(ias=210)
        callouts = engine.update(cur, None)
        assert len(callouts) == 1
        assert callouts[0].message == "Fast cruise"

    def test_callable_message(self) -> None:
        rule = CalloutRule(
            name="DYN_MSG",
            phase=None,
            condition=lambda s, p: True,
            message=lambda s, p: f"Speed is {int(s.speeds.indicated_airspeed)}",
            one_shot=True,
        )
        engine = CalloutEngine(rules=[rule])
        cur = _make_state(ias=150)
        callouts = engine.update(cur, None)
        assert callouts[0].message == "Speed is 150"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_previous_state(self) -> None:
        """Engine should not crash when prev_state is None."""
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.TAKEOFF)
        callouts = engine.update(_make_state(ias=90, vs=400, alt_agl=150), None)
        # Should still get non-crossing callouts
        names = [c.name for c in callouts]
        assert "POSITIVE_RATE" in names or "GEAR_UP" in names

    def test_empty_rules(self) -> None:
        engine = CalloutEngine(rules=[])
        callouts = engine.update(_make_state(), None)
        assert callouts == []

    def test_condition_exception_handled(self) -> None:
        def bad_condition(s: SimState, p: SimState | None) -> bool:
            raise ValueError("oops")

        rule = CalloutRule(
            name="BAD",
            phase=None,
            condition=bad_condition,
            message="never",
        )
        engine = CalloutEngine(rules=[rule])
        # Should not raise, just skip the rule
        callouts = engine.update(_make_state(), None)
        assert len(callouts) == 0

    def test_default_phase_is_preflight(self) -> None:
        engine = CalloutEngine()
        assert engine.current_phase == FlightPhase.PREFLIGHT
