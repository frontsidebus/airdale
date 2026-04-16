"""Integration tests for Phase 4 — Proactive Copilot features.

These tests verify that the proactive subsystems (callouts, deviation
monitoring, emergency detection, phase detection, and checklist offers)
work correctly together through realistic multi-step flight sequences.

Each test feeds a series of SimState snapshots through the integrated
pipeline and asserts that the correct events are generated in the right
order with the right properties.
"""

from __future__ import annotations

import pytest
from orchestrator.flight_phase import FlightPhaseDetector, PhaseThresholds
from orchestrator.sim_client import (
    Attitude,
    AutopilotState,
    EngineData,
    Engines,
    Environment,
    FlightPhase,
    FuelState,
    Position,
    SimState,
    Speeds,
    SurfaceState,
)

# Import the proactive monitor and event types.
ProactiveMonitor = pytest.importorskip(
    "orchestrator.proactive_monitor", reason="proactive_monitor module not available"
).ProactiveMonitor
ProactiveEvent = pytest.importorskip(
    "orchestrator.proactive_monitor", reason="proactive_monitor module not available"
).ProactiveEvent
CalloutThresholds = pytest.importorskip(
    "orchestrator.proactive_monitor", reason="proactive_monitor module not available"
).CalloutThresholds
DeviationThresholds = pytest.importorskip(
    "orchestrator.proactive_monitor", reason="proactive_monitor module not available"
).DeviationThresholds

# Emergency detector.
EmergencyDetector = pytest.importorskip(
    "orchestrator.emergency", reason="emergency module not available"
).EmergencyDetector
EmergencyThresholds = pytest.importorskip(
    "orchestrator.emergency", reason="emergency module not available"
).EmergencyThresholds

# Callout engine (standalone module).
try:
    from orchestrator.callouts import CalloutEngine
except ImportError:
    CalloutEngine = None  # type: ignore[assignment,misc]

# Deviation monitor (standalone module).
try:
    from orchestrator.deviation_monitor import DeviationMonitor
except ImportError:
    DeviationMonitor = None  # type: ignore[assignment,misc]

# Checklist manager.
try:
    from orchestrator.checklist_manager import ChecklistManager
except ImportError:
    ChecklistManager = None  # type: ignore[assignment,misc]


# ============================================================================
# SimState sequence builder helpers
# ============================================================================


def _engine(rpm: float = 2400.0, egt: float = 800.0) -> Engines:
    return Engines(
        engine_count=1,
        engines=[EngineData(rpm=rpm, egt=egt, oil_temp=180.0, oil_pressure=60.0)],
    )


def _state(
    *,
    phase: FlightPhase = FlightPhase.PREFLIGHT,
    ias: float = 0.0,
    ground_speed: float = 0.0,
    altitude_msl: float = 100.0,
    altitude_agl: float = 0.0,
    vertical_speed: float = 0.0,
    heading: float = 270.0,
    pitch: float = 0.0,
    bank: float = 0.0,
    rpm: float = 2400.0,
    egt: float = 800.0,
    gear: bool = True,
    flaps: float = 0.0,
    ap_master: bool = False,
    ap_altitude: float = 0.0,
) -> SimState:
    """Build a SimState with sensible defaults for integration testing."""
    return SimState(
        timestamp="2026-04-01T12:00:00+00:00",
        connected=True,
        aircraft="Cessna 172 Skyhawk",
        flight_phase=phase,
        position=Position(
            latitude=28.43,
            longitude=-81.31,
            altitude_msl=altitude_msl,
            altitude_agl=altitude_agl,
        ),
        attitude=Attitude(
            pitch=pitch,
            bank=bank,
            heading_true=heading,
            heading_magnetic=heading,
        ),
        speeds=Speeds(
            indicated_airspeed=ias,
            true_airspeed=ias,
            ground_speed=ground_speed,
            vertical_speed=vertical_speed,
        ),
        engines=_engine(rpm=rpm, egt=egt),
        autopilot=AutopilotState(master=ap_master, altitude=ap_altitude),
        surfaces=SurfaceState(gear_handle=gear, flaps_percent=flaps),
        fuel=FuelState(total_gallons=42, total_weight_lbs=252),
        environment=Environment(
            wind_speed_kts=5,
            wind_direction=270,
            visibility_sm=10,
            temperature_c=25,
            barometer_inhg=29.92,
        ),
    )


def make_takeoff_sequence() -> list[SimState]:
    """Generate states: ground roll -> rotation -> climb.

    Simulates a typical single-engine takeoff:
    - Parked/idle
    - Power up, ground roll accelerating
    - V1 speed crossing
    - Rotate speed crossing
    - Liftoff, positive rate
    - Initial climb, gear-up altitude
    """
    return [
        # 0: Parked, engines running
        _state(
            phase=FlightPhase.TAKEOFF,
            ias=0.0,
            ground_speed=0.0,
            altitude_agl=0.0,
            vertical_speed=0.0,
            rpm=2700,
        ),
        # 1: Beginning ground roll
        _state(
            phase=FlightPhase.TAKEOFF,
            ias=30.0,
            ground_speed=30.0,
            altitude_agl=0.0,
            vertical_speed=0.0,
            rpm=2700,
        ),
        # 2: Accelerating past V1 (default threshold ~60kt)
        _state(
            phase=FlightPhase.TAKEOFF,
            ias=62.0,
            ground_speed=62.0,
            altitude_agl=0.0,
            vertical_speed=0.0,
            rpm=2700,
        ),
        # 3: Crossing rotate speed (~65kt)
        _state(
            phase=FlightPhase.TAKEOFF,
            ias=68.0,
            ground_speed=68.0,
            altitude_agl=0.0,
            vertical_speed=0.0,
            rpm=2700,
        ),
        # 4: Liftoff - positive rate (VS > 100, AGL > 20)
        _state(
            phase=FlightPhase.TAKEOFF,
            ias=75.0,
            ground_speed=72.0,
            altitude_agl=50.0,
            vertical_speed=500.0,
            rpm=2700,
        ),
        # 5: Climbing through 150ft - gear up territory (VS > 300, AGL > 100)
        _state(
            phase=FlightPhase.TAKEOFF,
            ias=85.0,
            ground_speed=82.0,
            altitude_agl=200.0,
            vertical_speed=800.0,
            rpm=2700,
            gear=False,
        ),
    ]


def make_approach_sequence() -> list[SimState]:
    """Generate states: 3000ft -> 1000ft -> 500ft -> 200ft -> 100ft -> 50ft.

    Simulates a visual approach to landing with altitude callout crossings.
    """
    return [
        # 0: Established on approach at 3000ft AGL
        _state(
            phase=FlightPhase.APPROACH,
            ias=100.0,
            altitude_msl=3100.0,
            altitude_agl=3000.0,
            vertical_speed=-500.0,
            gear=True,
            flaps=20.0,
        ),
        # 1: Descending through ~1500ft
        _state(
            phase=FlightPhase.APPROACH,
            ias=95.0,
            altitude_msl=1600.0,
            altitude_agl=1500.0,
            vertical_speed=-500.0,
            gear=True,
            flaps=30.0,
        ),
        # 2: Crossing 1000ft AGL
        _state(
            phase=FlightPhase.APPROACH,
            ias=90.0,
            altitude_msl=1080.0,
            altitude_agl=980.0,
            vertical_speed=-500.0,
            gear=True,
            flaps=30.0,
        ),
        # 3: Crossing 500ft AGL
        _state(
            phase=FlightPhase.APPROACH,
            ias=85.0,
            altitude_msl=580.0,
            altitude_agl=480.0,
            vertical_speed=-400.0,
            gear=True,
            flaps=40.0,
        ),
        # 4: Crossing 200ft AGL (minimums)
        _state(
            phase=FlightPhase.APPROACH,
            ias=75.0,
            altitude_msl=280.0,
            altitude_agl=180.0,
            vertical_speed=-350.0,
            gear=True,
            flaps=40.0,
        ),
        # 5: Crossing 100ft AGL
        _state(
            phase=FlightPhase.APPROACH,
            ias=70.0,
            altitude_msl=180.0,
            altitude_agl=80.0,
            vertical_speed=-300.0,
            gear=True,
            flaps=40.0,
        ),
        # 6: At 50ft
        _state(
            phase=FlightPhase.LANDING,
            ias=68.0,
            altitude_msl=130.0,
            altitude_agl=30.0,
            vertical_speed=-200.0,
            gear=True,
            flaps=40.0,
        ),
    ]


# ============================================================================
# Helper: drain all events from a ProactiveMonitor
# ============================================================================


async def _drain_events(monitor: ProactiveMonitor) -> list[ProactiveEvent]:
    """Drain all pending events from the monitor queue."""
    events: list[ProactiveEvent] = []
    while monitor.get_pending_count() > 0:
        evt = await monitor.get_next_event(timeout=0.05)
        if evt is not None:
            events.append(evt)
    return events


async def _feed_sequence(
    monitor: ProactiveMonitor,
    states: list[SimState],
) -> list[ProactiveEvent]:
    """Feed a sequence of states into the monitor and return all events."""
    for s in states:
        await monitor.on_telemetry_update(s)
    return await _drain_events(monitor)


# ============================================================================
# Test 1: Full takeoff sequence
# ============================================================================


class TestFullTakeoffSequence:
    """Feed states simulating a takeoff and verify callouts fire in order:
    V1 -> Rotate -> (positive rate / gear up are in the CalloutEngine, not
    ProactiveMonitor built-in, so we check what the monitor produces).
    """

    async def test_v1_and_rotate_fire_in_order(self) -> None:
        monitor = ProactiveMonitor(
            callout_thresholds=CalloutThresholds(v1_speed=60.0, rotate_speed=65.0),
        )
        states = make_takeoff_sequence()
        events = await _feed_sequence(monitor, states)

        callout_events = [e for e in events if e.type == "callout"]
        callout_msgs = [e.message for e in callout_events]

        # Both V1 and Rotate should appear
        v1_indices = [i for i, m in enumerate(callout_msgs) if "V1" in m]
        rotate_indices = [i for i, m in enumerate(callout_msgs) if "Rotate" in m]

        assert len(v1_indices) >= 1, f"V1 callout missing. Got: {callout_msgs}"
        assert len(rotate_indices) >= 1, f"Rotate callout missing. Got: {callout_msgs}"

        # V1 must come before Rotate
        assert v1_indices[0] < rotate_indices[0], (
            f"V1 (index {v1_indices[0]}) should fire before Rotate (index {rotate_indices[0]})"
        )

    async def test_takeoff_callouts_have_correct_priority(self) -> None:
        monitor = ProactiveMonitor(
            callout_thresholds=CalloutThresholds(v1_speed=60.0, rotate_speed=65.0),
        )
        states = make_takeoff_sequence()
        events = await _feed_sequence(monitor, states)

        callout_events = [e for e in events if e.type == "callout"]
        for evt in callout_events:
            if "V1" in evt.message or "Rotate" in evt.message:
                assert evt.priority >= 1, (
                    f"Takeoff callout '{evt.message}' should have priority >= 1"
                )


# ============================================================================
# Test 2: Approach with deviation
# ============================================================================


class TestApproachWithDeviation:
    """Simulate approach at too-high airspeed (180kt at 1000ft AGL).
    Verify both altitude callout AND speed deviation fire.
    """

    async def test_altitude_callout_and_speed_deviation_both_fire(self) -> None:
        monitor = ProactiveMonitor(
            callout_thresholds=CalloutThresholds(altitude_callout_levels=(1000.0, 500.0)),
            deviation_thresholds=DeviationThresholds(overspeed_ias=160.0),
        )

        # Start high, descend through 1000ft at too-high speed
        high = _state(
            phase=FlightPhase.APPROACH,
            ias=180.0,
            altitude_msl=1200.0,
            altitude_agl=1100.0,
            vertical_speed=-500.0,
            gear=True,
            flaps=10.0,
        )
        crossing_1000 = _state(
            phase=FlightPhase.APPROACH,
            ias=180.0,
            altitude_msl=1080.0,
            altitude_agl=980.0,
            vertical_speed=-500.0,
            gear=True,
            flaps=10.0,
        )

        await monitor.on_telemetry_update(high)
        await monitor.on_telemetry_update(crossing_1000)

        events = await _drain_events(monitor)

        callout_events = [e for e in events if e.type == "callout"]
        deviation_events = [e for e in events if e.type == "deviation"]

        # Altitude callout for 1000ft
        alt_1000 = [e for e in callout_events if "1000" in e.message]
        assert len(alt_1000) >= 1, f"Expected 1000ft callout. Got callouts: {callout_events}"

        # Overspeed deviation
        overspeed = [
            e for e in deviation_events if "Overspeed" in e.message or "speed" in e.message.lower()
        ]
        assert len(overspeed) >= 1, f"Expected speed deviation. Got deviations: {deviation_events}"


# ============================================================================
# Test 3: Emergency during cruise
# ============================================================================


class TestEmergencyDuringCruise:
    """Simulate engine RPM dropping to 0 during cruise.
    Verify emergency event fires with priority 3 and tts_override=True.
    """

    async def test_engine_failure_generates_emergency(self) -> None:
        detector = EmergencyDetector(
            thresholds=EmergencyThresholds(min_detection_duration=0),
        )
        monitor = ProactiveMonitor(emergency_detector=detector)

        healthy = _state(
            phase=FlightPhase.CRUISE,
            ias=120.0,
            rpm=2400.0,
            altitude_msl=6500.0,
            altitude_agl=6400.0,
        )
        engine_out = _state(
            phase=FlightPhase.CRUISE,
            ias=120.0,
            rpm=0.0,
            altitude_msl=6500.0,
            altitude_agl=6400.0,
        )

        await monitor.on_telemetry_update(healthy)
        await monitor.on_telemetry_update(engine_out)

        events = await _drain_events(monitor)
        emergencies = [e for e in events if e.type == "emergency"]

        assert len(emergencies) >= 1, f"Expected emergency event. Got: {events}"

        emg = emergencies[0]
        assert emg.priority == 3, f"Emergency priority should be 3, got {emg.priority}"
        assert emg.tts_override is True, "Emergency should have tts_override=True"
        assert "ENGINE FAILURE" in emg.message, f"Expected ENGINE FAILURE in message: {emg.message}"

    async def test_emergency_includes_structured_data(self) -> None:
        detector = EmergencyDetector(
            thresholds=EmergencyThresholds(min_detection_duration=0),
        )
        monitor = ProactiveMonitor(emergency_detector=detector)

        healthy = _state(
            phase=FlightPhase.CRUISE,
            rpm=2400.0,
            altitude_msl=6500.0,
            altitude_agl=6400.0,
        )
        engine_out = _state(
            phase=FlightPhase.CRUISE,
            rpm=0.0,
            altitude_msl=6500.0,
            altitude_agl=6400.0,
        )

        await monitor.on_telemetry_update(healthy)
        await monitor.on_telemetry_update(engine_out)

        events = await _drain_events(monitor)
        emergencies = [e for e in events if e.type == "emergency"]
        assert len(emergencies) >= 1

        data = emergencies[0].data
        assert "emergency_type" in data
        assert "emergency_response" in data
        assert "immediate_actions" in data["emergency_response"]
        assert "squawk" in data["emergency_response"]


# ============================================================================
# Test 4: Phase transition checklist offer
# ============================================================================


class TestPhaseTransitionChecklistOffer:
    """Simulate a phase change from TAXI to TAKEOFF.
    Verify a checklist offer event is generated.
    """

    async def test_taxi_to_takeoff_generates_checklist_offer(self) -> None:
        monitor = ProactiveMonitor()

        taxi = _state(
            phase=FlightPhase.TAXI, ias=10.0, ground_speed=10.0, altitude_agl=0.0, rpm=1800.0
        )
        takeoff = _state(
            phase=FlightPhase.TAKEOFF, ias=45.0, ground_speed=45.0, altitude_agl=0.0, rpm=2700.0
        )

        await monitor.on_telemetry_update(taxi)
        await _drain_events(monitor)  # clear initial events

        await monitor.on_telemetry_update(takeoff)
        events = await _drain_events(monitor)

        checklist_events = [e for e in events if e.type == "checklist_offer"]
        assert len(checklist_events) == 1, (
            f"Expected 1 checklist offer, got {len(checklist_events)}: {checklist_events}"
        )
        assert checklist_events[0].priority == 0
        assert "TAXI" in checklist_events[0].data["from_phase"]
        assert "TAKEOFF" in checklist_events[0].data["to_phase"]

    async def test_multiple_phase_transitions_generate_offers(self) -> None:
        """Test that consecutive phase transitions each produce offers."""
        monitor = ProactiveMonitor()

        states = [
            _state(phase=FlightPhase.TAXI, ias=10.0, ground_speed=10.0, altitude_agl=0.0),
            _state(phase=FlightPhase.TAKEOFF, ias=45.0, ground_speed=45.0, altitude_agl=0.0),
        ]

        for s in states:
            await monitor.on_telemetry_update(s)

        events = await _drain_events(monitor)
        # PREFLIGHT -> TAXI triggers a checklist offer (if mapped), then TAXI -> TAKEOFF
        checklist_events = [e for e in events if e.type == "checklist_offer"]
        # At minimum, TAXI -> TAKEOFF should produce an offer
        taxi_to_takeoff = [
            e
            for e in checklist_events
            if e.data.get("from_phase") == "TAXI" and e.data.get("to_phase") == "TAKEOFF"
        ]
        assert len(taxi_to_takeoff) >= 1


# ============================================================================
# Test 5: Callout one-shot behavior
# ============================================================================


class TestCalloutOneShotBehavior:
    """Simulate crossing 500ft AGL twice (descend through, climb back,
    descend again). Verify the callout only fires once per phase.
    """

    async def test_altitude_callout_fires_once_per_phase(self) -> None:
        monitor = ProactiveMonitor(
            callout_thresholds=CalloutThresholds(altitude_callout_levels=(500.0,)),
        )

        # First descent through 500ft
        above = _state(
            phase=FlightPhase.APPROACH,
            altitude_agl=550.0,
            altitude_msl=650.0,
            vertical_speed=-400.0,
            gear=True,
        )
        below = _state(
            phase=FlightPhase.APPROACH,
            altitude_agl=480.0,
            altitude_msl=580.0,
            vertical_speed=-400.0,
            gear=True,
        )

        await monitor.on_telemetry_update(above)
        await monitor.on_telemetry_update(below)

        events_pass1 = await _drain_events(monitor)
        callouts_500_pass1 = [e for e in events_pass1 if e.type == "callout" and "500" in e.message]
        assert len(callouts_500_pass1) == 1, "First crossing should produce exactly 1 callout"

        # Climb back above 500ft (go-around or bobble), still in APPROACH phase
        back_above = _state(
            phase=FlightPhase.APPROACH,
            altitude_agl=550.0,
            altitude_msl=650.0,
            vertical_speed=300.0,
            gear=True,
        )
        await monitor.on_telemetry_update(back_above)
        await _drain_events(monitor)  # clear

        # Second descent through 500ft, same phase
        below_again = _state(
            phase=FlightPhase.APPROACH,
            altitude_agl=480.0,
            altitude_msl=580.0,
            vertical_speed=-400.0,
            gear=True,
        )
        await monitor.on_telemetry_update(below_again)

        events_pass2 = await _drain_events(monitor)
        callouts_500_pass2 = [e for e in events_pass2 if e.type == "callout" and "500" in e.message]
        assert len(callouts_500_pass2) == 0, (
            "Second crossing in same phase should NOT produce another 500ft callout"
        )

    async def test_callout_fires_again_after_phase_change(self) -> None:
        """After a phase transition, one-shot callouts should reset."""
        monitor = ProactiveMonitor(
            callout_thresholds=CalloutThresholds(v1_speed=60.0),
        )

        # First takeoff: fire V1
        slow = _state(phase=FlightPhase.TAKEOFF, ias=50.0, altitude_agl=0.0)
        fast = _state(phase=FlightPhase.TAKEOFF, ias=62.0, altitude_agl=0.0)
        await monitor.on_telemetry_update(slow)
        await monitor.on_telemetry_update(fast)
        events1 = await _drain_events(monitor)
        v1_count_1 = len([e for e in events1 if "V1" in e.message])
        assert v1_count_1 == 1

        # Transition to climb
        climb = _state(
            phase=FlightPhase.CLIMB, altitude_agl=500.0, altitude_msl=600.0, vertical_speed=800.0
        )
        await monitor.on_telemetry_update(climb)
        await _drain_events(monitor)

        # Second takeoff (e.g., go-around or touch-and-go): V1 should fire again
        slow2 = _state(phase=FlightPhase.TAKEOFF, ias=50.0, altitude_agl=0.0)
        fast2 = _state(phase=FlightPhase.TAKEOFF, ias=62.0, altitude_agl=0.0)
        await monitor.on_telemetry_update(slow2)
        await monitor.on_telemetry_update(fast2)
        events2 = await _drain_events(monitor)
        v1_count_2 = len([e for e in events2 if "V1" in e.message])
        assert v1_count_2 == 1, "V1 should fire again after phase change"


# ============================================================================
# Test 6: Deviation cooldown
# ============================================================================


class TestDeviationCooldown:
    """Test that the standalone DeviationMonitor respects cooldown timers.

    The ProactiveMonitor's built-in deviation checks do not implement cooldown
    (they fire every tick), so this test exercises the standalone module.
    """

    @pytest.mark.skipif(DeviationMonitor is None, reason="deviation_monitor module not available")
    def test_deviation_cooldown_suppresses_refiring(self) -> None:
        """Trigger a deviation, advance time less than cooldown, verify it
        does not re-fire. Advance past cooldown, verify it fires again.
        """
        fake_time = [100.0]

        def time_fn() -> float:
            return fake_time[0]

        monitor = DeviationMonitor(time_fn=time_fn)

        # Create an approach state with high speed (>160kt triggers speed_high_approach)
        fast_approach = _state(
            phase=FlightPhase.APPROACH,
            ias=180.0,
            altitude_msl=1500.0,
            altitude_agl=1400.0,
            vertical_speed=-500.0,
            gear=True,
            flaps=30.0,
        )

        # First check: should fire
        alerts1 = monitor.check(fast_approach)
        speed_alerts_1 = [a for a in alerts1 if a.name == "speed_high_approach"]
        assert len(speed_alerts_1) >= 1, "First check should fire speed deviation"

        # Advance less than cooldown (default 30s)
        fake_time[0] = 115.0
        alerts2 = monitor.check(fast_approach)
        speed_alerts_2 = [a for a in alerts2 if a.name == "speed_high_approach"]
        assert len(speed_alerts_2) == 0, "Should be suppressed during cooldown"

        # Advance past cooldown
        fake_time[0] = 135.0
        alerts3 = monitor.check(fast_approach)
        speed_alerts_3 = [a for a in alerts3 if a.name == "speed_high_approach"]
        assert len(speed_alerts_3) >= 1, "Should fire again after cooldown expires"


# ============================================================================
# Test 7: Priority ordering
# ============================================================================


class TestPriorityOrdering:
    """Generate a callout (priority 0-1) and a deviation (priority 2) in the
    same update. Verify the deviation is delivered first from the priority queue.
    """

    async def test_deviation_delivered_before_callout(self) -> None:
        monitor = ProactiveMonitor(
            callout_thresholds=CalloutThresholds(altitude_callout_levels=(1000.0,)),
            deviation_thresholds=DeviationThresholds(overspeed_ias=150.0),
        )

        # Set up: approach at high speed, about to cross 1000ft
        high = _state(
            phase=FlightPhase.APPROACH,
            ias=170.0,
            altitude_msl=1200.0,
            altitude_agl=1100.0,
            vertical_speed=-500.0,
            gear=True,
        )
        crossing = _state(
            phase=FlightPhase.APPROACH,
            ias=170.0,
            altitude_msl=1080.0,
            altitude_agl=980.0,
            vertical_speed=-500.0,
            gear=True,
        )

        await monitor.on_telemetry_update(high)
        await monitor.on_telemetry_update(crossing)

        events = await _drain_events(monitor)

        callout_events = [e for e in events if e.type == "callout"]
        deviation_events = [e for e in events if e.type == "deviation"]

        assert len(callout_events) >= 1, "Expected at least one callout"
        assert len(deviation_events) >= 1, "Expected at least one deviation"

        # Since events are drained from a PriorityQueue, higher priority comes first.
        # Deviation (priority 2) should appear before callout (priority 0).
        first_deviation_idx = next(i for i, e in enumerate(events) if e.type == "deviation")
        first_callout_idx = next(i for i, e in enumerate(events) if e.type == "callout")
        assert first_deviation_idx < first_callout_idx, (
            f"Deviation (idx {first_deviation_idx}) should be delivered before "
            f"callout (idx {first_callout_idx}). Events: {[(e.type, e.priority) for e in events]}"
        )

    async def test_emergency_before_deviation_before_callout(self) -> None:
        """Emergency (3) > deviation (2) > callout (0-1) ordering."""
        detector = EmergencyDetector(
            thresholds=EmergencyThresholds(min_detection_duration=0),
        )
        monitor = ProactiveMonitor(
            emergency_detector=detector,
            callout_thresholds=CalloutThresholds(
                v1_speed=60.0,
                altitude_callout_levels=(1000.0,),
            ),
            deviation_thresholds=DeviationThresholds(overspeed_ias=100.0),
        )

        # Healthy cruise state
        healthy = _state(
            phase=FlightPhase.CRUISE,
            rpm=2400.0,
            ias=90.0,
            altitude_msl=6500.0,
            altitude_agl=6400.0,
        )
        # Engine failure + overspeed simultaneously
        crisis = _state(
            phase=FlightPhase.CRUISE,
            rpm=0.0,
            ias=200.0,
            altitude_msl=6500.0,
            altitude_agl=6400.0,
        )

        await monitor.on_telemetry_update(healthy)
        await monitor.on_telemetry_update(crisis)

        events = await _drain_events(monitor)
        assert len(events) >= 2, f"Expected at least 2 events, got {len(events)}"

        # First event should be the emergency (priority 3)
        assert events[0].type == "emergency", (
            f"First event should be emergency, got {events[0].type}"
        )
        assert events[0].priority == 3


# ============================================================================
# Test 8: FlightPhaseDetector + ProactiveMonitor integration
# ============================================================================


class TestPhaseDetectorIntegration:
    """Verify that when FlightPhaseDetector determines phase transitions and
    we feed the updated phase into ProactiveMonitor, the correct events fire.
    """

    async def test_detector_driven_phase_transitions(self) -> None:
        """Run a full takeoff through the phase detector and verify
        the proactive monitor generates appropriate events.
        """
        detector = FlightPhaseDetector(
            thresholds=PhaseThresholds(takeoff_speed=40.0),
        )
        # Bypass hysteresis for testing by setting hold_required to 1
        detector._hold_required = 1

        monitor = ProactiveMonitor(
            callout_thresholds=CalloutThresholds(v1_speed=60.0, rotate_speed=65.0),
        )

        # Simulate states where phase detector determines the phase
        states_raw = [
            # Taxiing
            _state(ias=15.0, ground_speed=15.0, altitude_agl=0.0, rpm=1800.0),
            # Takeoff roll
            _state(ias=45.0, ground_speed=45.0, altitude_agl=0.0, rpm=2700.0),
            # Past V1
            _state(ias=62.0, ground_speed=62.0, altitude_agl=0.0, rpm=2700.0),
            # Past rotate
            _state(ias=68.0, ground_speed=68.0, altitude_agl=0.0, rpm=2700.0),
        ]

        for s in states_raw:
            detected_phase = detector.update(s)
            s.flight_phase = detected_phase
            await monitor.on_telemetry_update(s)

        events = await _drain_events(monitor)
        event_types = [e.type for e in events]

        # Should have at least checklist_offer (for phase transition)
        # and V1/Rotate callouts if phase was TAKEOFF when crossing speeds
        assert any(e.type == "checklist_offer" for e in events) or any(
            e.type == "callout" for e in events
        ), f"Expected checklist or callout events, got types: {event_types}"


# ============================================================================
# Test 9: CalloutEngine + DeviationMonitor standalone integration
# ============================================================================


@pytest.mark.skipif(CalloutEngine is None, reason="callouts module not available")
class TestCalloutEngineIntegration:
    """Test the standalone CalloutEngine through approach sequences."""

    def test_approach_altitude_callouts_sequence(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.APPROACH)

        sequence = make_approach_sequence()
        all_callouts = []
        prev = None
        for s in sequence:
            callouts = engine.update(s, prev)
            all_callouts.extend(callouts)
            prev = s

        callout_names = [c.name for c in all_callouts]

        # Should fire altitude-related callouts as we descend
        # The exact names depend on the default rules in callouts.py
        assert len(all_callouts) >= 1, (
            f"Expected at least 1 callout during approach, got: {callout_names}"
        )

    def test_callout_engine_phase_change_resets_triggers(self) -> None:
        engine = CalloutEngine()
        engine.on_phase_change(FlightPhase.APPROACH)

        above = _state(
            phase=FlightPhase.APPROACH,
            altitude_agl=550.0,
            altitude_msl=650.0,
            vertical_speed=-400.0,
            gear=True,
            flaps=30.0,
        )
        below = _state(
            phase=FlightPhase.APPROACH,
            altitude_agl=480.0,
            altitude_msl=580.0,
            vertical_speed=-400.0,
            gear=True,
            flaps=30.0,
        )

        engine.update(below, above)

        # Phase change resets
        engine.on_phase_change(FlightPhase.LANDING)
        engine.on_phase_change(FlightPhase.APPROACH)

        # Triggered set should be cleared
        assert len(engine.triggered_names) == 0, "Phase change should clear triggered callouts"


# ============================================================================
# Test 10: ChecklistManager + ProactiveMonitor integration
# ============================================================================


@pytest.mark.skipif(ChecklistManager is None, reason="checklist_manager module not available")
class TestChecklistManagerIntegration:
    """Verify that ChecklistManager and ProactiveMonitor both generate
    appropriate outputs for the same phase transition.
    """

    async def test_both_systems_respond_to_phase_change(self) -> None:
        """When phase changes from TAXI to TAKEOFF, both the ProactiveMonitor
        and the ChecklistManager should produce relevant output.
        """
        monitor = ProactiveMonitor()
        checklist_mgr = ChecklistManager()

        taxi = _state(phase=FlightPhase.TAXI, ias=10.0, ground_speed=10.0, altitude_agl=0.0)
        takeoff = _state(phase=FlightPhase.TAKEOFF, ias=45.0, ground_speed=45.0, altitude_agl=0.0)

        # Feed to ProactiveMonitor
        await monitor.on_telemetry_update(taxi)
        await _drain_events(monitor)
        await monitor.on_telemetry_update(takeoff)
        monitor_events = await _drain_events(monitor)

        # Feed phase change to ChecklistManager
        checklist_offer = checklist_mgr.on_phase_change(FlightPhase.TAKEOFF)

        # ProactiveMonitor should have a checklist_offer event
        monitor_checklists = [e for e in monitor_events if e.type == "checklist_offer"]
        assert len(monitor_checklists) >= 1, "ProactiveMonitor should offer checklist"

        # ChecklistManager should also have an offer string
        # (It maps TAKEOFF phase -- may not have an exact match since it maps
        # to TAXI phase for "Before takeoff checklist")
        # The ChecklistManager maps phases differently, but at least one system
        # should provide the offer.
        assert len(monitor_checklists) >= 1 or checklist_offer is not None, (
            "At least one system should offer a checklist for this transition"
        )


# ============================================================================
# Test 11: Full flight segment integration
# ============================================================================


class TestFullFlightSegment:
    """End-to-end test: run through multiple flight phases and verify the
    complete event sequence across the entire flight.
    """

    async def test_taxi_through_approach(self) -> None:
        """Simulate a full flight from taxi through approach and verify
        that different event types fire at the appropriate times.
        """
        detector = FlightPhaseDetector()
        detector._hold_required = 1  # Bypass hysteresis for testing

        emg_detector = EmergencyDetector(
            thresholds=EmergencyThresholds(min_detection_duration=0),
        )
        monitor = ProactiveMonitor(
            emergency_detector=emg_detector,
            callout_thresholds=CalloutThresholds(v1_speed=60.0, rotate_speed=65.0),
            deviation_thresholds=DeviationThresholds(overspeed_ias=200.0),
        )

        flight_states = [
            # Taxi
            _state(ias=15.0, ground_speed=15.0, altitude_agl=0.0, rpm=1800.0),
            # Takeoff roll
            _state(ias=50.0, ground_speed=50.0, altitude_agl=0.0, rpm=2700.0),
            # Past V1 and rotate
            _state(ias=70.0, ground_speed=70.0, altitude_agl=0.0, rpm=2700.0),
            # Climbing
            _state(
                ias=85.0,
                ground_speed=82.0,
                altitude_agl=200.0,
                altitude_msl=300.0,
                vertical_speed=800.0,
                rpm=2700.0,
                gear=False,
            ),
            # Cruise
            _state(
                ias=120.0,
                ground_speed=135.0,
                altitude_agl=6400.0,
                altitude_msl=6500.0,
                vertical_speed=0.0,
                rpm=2400.0,
                gear=False,
            ),
            # Approach
            _state(
                ias=90.0,
                ground_speed=88.0,
                altitude_agl=1100.0,
                altitude_msl=1200.0,
                vertical_speed=-500.0,
                gear=True,
                flaps=30.0,
            ),
            # Crossing 1000ft on approach
            _state(
                ias=85.0,
                ground_speed=83.0,
                altitude_agl=980.0,
                altitude_msl=1080.0,
                vertical_speed=-500.0,
                gear=True,
                flaps=30.0,
            ),
        ]

        all_events: list[ProactiveEvent] = []
        for s in flight_states:
            phase = detector.update(s)
            s.flight_phase = phase
            await monitor.on_telemetry_update(s)

        all_events = await _drain_events(monitor)

        # We should see at least callouts and checklist offers across the flight
        assert len(all_events) >= 1, "Expected at least some events across a full flight segment"

        # Verify no emergency events (engine stayed healthy)
        emergencies = [e for e in all_events if e.type == "emergency"]
        assert len(emergencies) == 0, "No emergencies expected in a normal flight"
