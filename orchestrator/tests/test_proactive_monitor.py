"""Tests for the unified proactive monitoring system."""

from __future__ import annotations

from orchestrator.emergency import EmergencyDetector, EmergencyThresholds
from orchestrator.proactive_monitor import (
    CalloutThresholds,
    DeviationThresholds,
    ProactiveEvent,
    ProactiveMonitor,
)
from orchestrator.sim_client import (
    Attitude,
    AutopilotState,
    EngineData,
    Engines,
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
    phase: FlightPhase = FlightPhase.CRUISE,
    rpm: float = 2400.0,
    egt: float = 800.0,
    altitude_msl: float = 5000.0,
    altitude_agl: float = 4500.0,
    ias: float = 120.0,
    ground_speed: float = 110.0,
    vertical_speed: float = 0.0,
    bank: float = 0.0,
    heading: float = 180.0,
    on_ground: bool = False,
    gear: bool = False,
    flaps: float = 0.0,
    ap_master: bool = False,
    ap_altitude: float = 5000.0,
) -> SimState:
    """Create a SimState with sensible defaults for testing."""
    return SimState(
        connected=True,
        aircraft="C172",
        flight_phase=phase,
        position=Position(
            latitude=40.0,
            longitude=-74.0,
            altitude_msl=altitude_msl,
            altitude_agl=altitude_agl,
        ),
        attitude=Attitude(
            pitch=0.0,
            bank=bank,
            heading_true=heading,
            heading_magnetic=heading,
        ),
        speeds=Speeds(
            indicated_airspeed=ias,
            ground_speed=ground_speed,
            vertical_speed=vertical_speed,
        ),
        engines=Engines(
            engine_count=1,
            engines=[EngineData(rpm=rpm, egt=egt, oil_temp=180.0, oil_pressure=60.0)],
        ),
        autopilot=AutopilotState(master=ap_master, altitude=ap_altitude),
        surfaces=SurfaceState(gear_handle=gear, flaps_percent=flaps),
    )


async def _drain_events(monitor: ProactiveMonitor) -> list[ProactiveEvent]:
    """Drain all pending events from the monitor queue."""
    events: list[ProactiveEvent] = []
    while monitor.get_pending_count() > 0:
        evt = await monitor.get_next_event(timeout=0.05)
        if evt is not None:
            events.append(evt)
    return events


# ---------------------------------------------------------------------------
# ProactiveEvent dataclass
# ---------------------------------------------------------------------------


class TestProactiveEvent:
    def test_fields(self) -> None:
        evt = ProactiveEvent(type="callout", priority=1, message="V1.")
        assert evt.type == "callout"
        assert evt.priority == 1
        assert evt.message == "V1."
        assert evt.tts_override is False
        assert evt.data == {}

    def test_tts_override_default(self) -> None:
        evt = ProactiveEvent(type="emergency", priority=3, message="Fire!", tts_override=True)
        assert evt.tts_override is True

    def test_priority_ordering(self) -> None:
        """Higher priority events should sort before lower priority."""
        low = ProactiveEvent(type="callout", priority=0, message="low")
        high = ProactiveEvent(type="emergency", priority=3, message="high")
        assert high < low  # higher priority sorts first

    def test_same_priority_no_error(self) -> None:
        """Events with the same priority should be comparable without error."""
        a = ProactiveEvent(type="callout", priority=1, message="a")
        b = ProactiveEvent(type="callout", priority=1, message="b")
        # Should not raise -- both have equal sort key
        assert not (a < b) or not (b < a) or (a == b)


# ---------------------------------------------------------------------------
# ProactiveMonitor -- emergency integration
# ---------------------------------------------------------------------------


class TestEmergencyIntegration:
    async def test_engine_failure_generates_emergency_event(self) -> None:
        detector = EmergencyDetector(thresholds=EmergencyThresholds(min_detection_duration=0))
        monitor = ProactiveMonitor(emergency_detector=detector)

        healthy = _make_state(phase=FlightPhase.CRUISE, rpm=2400.0)
        failed = _make_state(phase=FlightPhase.CRUISE, rpm=0.0)

        await monitor.on_telemetry_update(healthy)
        await monitor.on_telemetry_update(failed)

        events = await _drain_events(monitor)
        assert len(events) == 1
        evt = events[0]
        assert evt.type == "emergency"
        assert evt.priority == 3
        assert evt.tts_override is True
        assert "ENGINE FAILURE" in evt.message
        assert "emergency_type" in evt.data

    async def test_no_duplicate_emergency(self) -> None:
        """EmergencyDetector should only fire once per active emergency."""
        detector = EmergencyDetector(thresholds=EmergencyThresholds(min_detection_duration=0))
        monitor = ProactiveMonitor(emergency_detector=detector)

        healthy = _make_state(phase=FlightPhase.CRUISE, rpm=2400.0)
        failed = _make_state(phase=FlightPhase.CRUISE, rpm=0.0)

        await monitor.on_telemetry_update(healthy)
        await monitor.on_telemetry_update(failed)
        await monitor.on_telemetry_update(failed)  # second update with same failure

        events = await _drain_events(monitor)
        emergency_events = [e for e in events if e.type == "emergency"]
        assert len(emergency_events) == 1

    async def test_engine_fire_emergency(self) -> None:
        detector = EmergencyDetector(
            thresholds=EmergencyThresholds(min_detection_duration=0, egt_fire_threshold=1500.0)
        )
        monitor = ProactiveMonitor(emergency_detector=detector)

        normal = _make_state(phase=FlightPhase.CRUISE, rpm=2400.0, egt=800.0)
        fire = _make_state(phase=FlightPhase.CRUISE, rpm=2400.0, egt=1600.0)

        await monitor.on_telemetry_update(normal)
        await monitor.on_telemetry_update(fire)

        events = await _drain_events(monitor)
        emergency_events = [e for e in events if e.type == "emergency"]
        assert len(emergency_events) == 1
        assert "FIRE" in emergency_events[0].message


# ---------------------------------------------------------------------------
# ProactiveMonitor -- deviation detection
# ---------------------------------------------------------------------------


class TestDeviationDetection:
    async def test_overspeed_alert(self) -> None:
        monitor = ProactiveMonitor(deviation_thresholds=DeviationThresholds(overspeed_ias=180.0))

        state = _make_state(ias=200.0, altitude_agl=5000.0)
        await monitor.on_telemetry_update(state)

        events = await _drain_events(monitor)
        deviation_events = [e for e in events if e.type == "deviation"]
        assert len(deviation_events) >= 1
        assert "Overspeed" in deviation_events[0].message
        assert deviation_events[0].priority == 2

    async def test_no_overspeed_on_ground(self) -> None:
        """Overspeed should not fire when on the ground."""
        monitor = ProactiveMonitor(deviation_thresholds=DeviationThresholds(overspeed_ias=50.0))

        state = _make_state(ias=60.0, altitude_agl=5.0)  # on_ground: agl < 10
        await monitor.on_telemetry_update(state)

        events = await _drain_events(monitor)
        deviation_events = [e for e in events if e.type == "deviation"]
        assert len(deviation_events) == 0

    async def test_bank_angle_alert(self) -> None:
        monitor = ProactiveMonitor(deviation_thresholds=DeviationThresholds(max_bank_angle=45.0))

        state = _make_state(bank=50.0, altitude_agl=3000.0)
        await monitor.on_telemetry_update(state)

        events = await _drain_events(monitor)
        deviation_events = [e for e in events if e.type == "deviation"]
        assert len(deviation_events) >= 1
        assert "Bank angle" in deviation_events[0].message

    async def test_negative_bank_angle_detected(self) -> None:
        """Bank angle check should use absolute value."""
        monitor = ProactiveMonitor(deviation_thresholds=DeviationThresholds(max_bank_angle=45.0))

        state = _make_state(bank=-55.0, altitude_agl=3000.0)
        await monitor.on_telemetry_update(state)

        events = await _drain_events(monitor)
        deviation_events = [e for e in events if e.type == "deviation"]
        assert len(deviation_events) >= 1

    async def test_altitude_bust_alert(self) -> None:
        monitor = ProactiveMonitor(deviation_thresholds=DeviationThresholds(altitude_bust_ft=200.0))

        state = _make_state(
            phase=FlightPhase.CRUISE,
            altitude_msl=5500.0,
            ap_master=True,
            ap_altitude=5000.0,
        )
        await monitor.on_telemetry_update(state)

        events = await _drain_events(monitor)
        deviation_events = [e for e in events if e.type == "deviation"]
        assert len(deviation_events) >= 1
        assert "Altitude deviation" in deviation_events[0].message

    async def test_no_altitude_bust_without_autopilot(self) -> None:
        """Altitude bust only fires when AP is engaged."""
        monitor = ProactiveMonitor(deviation_thresholds=DeviationThresholds(altitude_bust_ft=200.0))

        state = _make_state(
            phase=FlightPhase.CRUISE,
            altitude_msl=5500.0,
            ap_master=False,
            ap_altitude=5000.0,
        )
        await monitor.on_telemetry_update(state)

        events = await _drain_events(monitor)
        deviation_events = [e for e in events if e.type == "deviation"]
        assert len(deviation_events) == 0

    async def test_no_altitude_bust_outside_cruise(self) -> None:
        """Altitude bust only fires during cruise phase."""
        monitor = ProactiveMonitor(deviation_thresholds=DeviationThresholds(altitude_bust_ft=200.0))

        state = _make_state(
            phase=FlightPhase.CLIMB,
            altitude_msl=5500.0,
            ap_master=True,
            ap_altitude=5000.0,
        )
        await monitor.on_telemetry_update(state)

        events = await _drain_events(monitor)
        deviation_events = [e for e in events if e.type == "deviation"]
        assert len(deviation_events) == 0


# ---------------------------------------------------------------------------
# ProactiveMonitor -- callouts
# ---------------------------------------------------------------------------


class TestCallouts:
    async def test_v1_callout(self) -> None:
        monitor = ProactiveMonitor(callout_thresholds=CalloutThresholds(v1_speed=60.0))

        slow = _make_state(phase=FlightPhase.TAKEOFF, ias=50.0, altitude_agl=5.0)
        fast = _make_state(phase=FlightPhase.TAKEOFF, ias=62.0, altitude_agl=5.0)

        await monitor.on_telemetry_update(slow)
        await monitor.on_telemetry_update(fast)

        events = await _drain_events(monitor)
        callout_events = [e for e in events if e.type == "callout"]
        v1_events = [e for e in callout_events if "V1" in e.message]
        assert len(v1_events) == 1
        assert v1_events[0].priority == 1

    async def test_rotate_callout(self) -> None:
        monitor = ProactiveMonitor(callout_thresholds=CalloutThresholds(rotate_speed=65.0))

        slow = _make_state(phase=FlightPhase.TAKEOFF, ias=60.0, altitude_agl=5.0)
        fast = _make_state(phase=FlightPhase.TAKEOFF, ias=67.0, altitude_agl=5.0)

        await monitor.on_telemetry_update(slow)
        await monitor.on_telemetry_update(fast)

        events = await _drain_events(monitor)
        callout_events = [e for e in events if e.type == "callout"]
        rotate_events = [e for e in callout_events if "Rotate" in e.message]
        assert len(rotate_events) == 1

    async def test_v1_does_not_repeat(self) -> None:
        """V1 callout should only fire once per takeoff phase."""
        monitor = ProactiveMonitor(callout_thresholds=CalloutThresholds(v1_speed=60.0))

        below = _make_state(phase=FlightPhase.TAKEOFF, ias=50.0, altitude_agl=5.0)
        above = _make_state(phase=FlightPhase.TAKEOFF, ias=62.0, altitude_agl=5.0)
        back_below = _make_state(phase=FlightPhase.TAKEOFF, ias=55.0, altitude_agl=5.0)
        above_again = _make_state(phase=FlightPhase.TAKEOFF, ias=63.0, altitude_agl=5.0)

        await monitor.on_telemetry_update(below)
        await monitor.on_telemetry_update(above)
        await monitor.on_telemetry_update(back_below)
        await monitor.on_telemetry_update(above_again)

        events = await _drain_events(monitor)
        v1_events = [e for e in events if e.type == "callout" and "V1" in e.message]
        assert len(v1_events) == 1

    async def test_altitude_crossing_callout(self) -> None:
        monitor = ProactiveMonitor(
            callout_thresholds=CalloutThresholds(altitude_callout_levels=(500.0, 200.0, 100.0))
        )

        high = _make_state(phase=FlightPhase.APPROACH, altitude_agl=550.0, gear=True)
        crossing = _make_state(phase=FlightPhase.APPROACH, altitude_agl=480.0, gear=True)

        await monitor.on_telemetry_update(high)
        await monitor.on_telemetry_update(crossing)

        events = await _drain_events(monitor)
        alt_events = [e for e in events if e.type == "callout" and "500" in e.message]
        assert len(alt_events) == 1
        assert alt_events[0].priority == 0

    async def test_multiple_altitude_crossings(self) -> None:
        monitor = ProactiveMonitor(
            callout_thresholds=CalloutThresholds(altitude_callout_levels=(500.0, 200.0, 100.0))
        )

        states = [
            _make_state(phase=FlightPhase.APPROACH, altitude_agl=550.0, gear=True),
            _make_state(phase=FlightPhase.APPROACH, altitude_agl=480.0, gear=True),
            _make_state(phase=FlightPhase.APPROACH, altitude_agl=180.0, gear=True),
            _make_state(phase=FlightPhase.LANDING, altitude_agl=90.0, gear=True),
        ]

        for s in states:
            await monitor.on_telemetry_update(s)

        events = await _drain_events(monitor)
        alt_callouts = [
            e for e in events if e.type == "callout" and e.data.get("callout") == "altitude"
        ]
        # Should fire for 500, 200, and 100
        levels_called = {e.data["altitude_agl"] for e in alt_callouts}
        assert 500.0 in levels_called
        assert 200.0 in levels_called
        assert 100.0 in levels_called

    async def test_no_callouts_wrong_phase(self) -> None:
        """V1/rotate should not fire outside takeoff phase."""
        monitor = ProactiveMonitor(
            callout_thresholds=CalloutThresholds(v1_speed=60.0, rotate_speed=65.0)
        )

        slow = _make_state(phase=FlightPhase.CRUISE, ias=50.0)
        fast = _make_state(phase=FlightPhase.CRUISE, ias=70.0)

        await monitor.on_telemetry_update(slow)
        await monitor.on_telemetry_update(fast)

        events = await _drain_events(monitor)
        callout_events = [e for e in events if e.type == "callout"]
        assert len(callout_events) == 0


# ---------------------------------------------------------------------------
# ProactiveMonitor -- phase transitions / checklist offers
# ---------------------------------------------------------------------------


class TestPhaseTransitions:
    async def test_taxi_to_takeoff_offers_checklist(self) -> None:
        monitor = ProactiveMonitor()

        taxi = _make_state(phase=FlightPhase.TAXI, ias=10.0, altitude_agl=5.0)
        takeoff = _make_state(phase=FlightPhase.TAKEOFF, ias=50.0, altitude_agl=5.0)

        # Need to set prev_phase to TAXI first
        await monitor.on_telemetry_update(taxi)
        await _drain_events(monitor)  # clear any events from first update

        await monitor.on_telemetry_update(takeoff)
        events = await _drain_events(monitor)

        checklist_events = [e for e in events if e.type == "checklist_offer"]
        assert len(checklist_events) == 1
        assert checklist_events[0].priority == 0
        assert "TAXI" in checklist_events[0].data["from_phase"]
        assert "TAKEOFF" in checklist_events[0].data["to_phase"]

    async def test_climb_to_cruise_offers_checklist(self) -> None:
        monitor = ProactiveMonitor()

        climb = _make_state(phase=FlightPhase.CLIMB, altitude_agl=3000.0)
        cruise = _make_state(phase=FlightPhase.CRUISE, altitude_agl=5000.0)

        await monitor.on_telemetry_update(climb)
        await _drain_events(monitor)

        await monitor.on_telemetry_update(cruise)
        events = await _drain_events(monitor)

        checklist_events = [e for e in events if e.type == "checklist_offer"]
        assert len(checklist_events) == 1
        assert "Cruise checklist" in checklist_events[0].message

    async def test_no_checklist_for_unmapped_transition(self) -> None:
        """Transitions not in _PHASE_CHECKLIST_OFFERS should not generate events."""
        monitor = ProactiveMonitor()

        # LANDED -> PREFLIGHT is not mapped
        landed = _make_state(phase=FlightPhase.LANDED, ias=10.0, altitude_agl=5.0)
        preflight = _make_state(phase=FlightPhase.PREFLIGHT, ias=0.0, altitude_agl=5.0)

        await monitor.on_telemetry_update(landed)
        await _drain_events(monitor)

        await monitor.on_telemetry_update(preflight)
        events = await _drain_events(monitor)

        checklist_events = [e for e in events if e.type == "checklist_offer"]
        assert len(checklist_events) == 0

    async def test_phase_transition_resets_fired_callouts(self) -> None:
        """Changing phases should clear fired callouts so they can fire again."""
        monitor = ProactiveMonitor(callout_thresholds=CalloutThresholds(v1_speed=60.0))

        # First takeoff: fire V1
        below = _make_state(phase=FlightPhase.TAKEOFF, ias=50.0, altitude_agl=5.0)
        above = _make_state(phase=FlightPhase.TAKEOFF, ias=62.0, altitude_agl=5.0)
        await monitor.on_telemetry_update(below)
        await monitor.on_telemetry_update(above)
        events1 = await _drain_events(monitor)
        v1_count_1 = len([e for e in events1 if "V1" in e.message])
        assert v1_count_1 == 1

        # Transition to climb, then back to takeoff (go-around scenario)
        climb = _make_state(phase=FlightPhase.CLIMB, altitude_agl=500.0)
        await monitor.on_telemetry_update(climb)
        await _drain_events(monitor)

        # Second takeoff: V1 should fire again
        below2 = _make_state(phase=FlightPhase.TAKEOFF, ias=50.0, altitude_agl=5.0)
        above2 = _make_state(phase=FlightPhase.TAKEOFF, ias=62.0, altitude_agl=5.0)
        await monitor.on_telemetry_update(below2)
        await monitor.on_telemetry_update(above2)
        events2 = await _drain_events(monitor)
        v1_count_2 = len([e for e in events2 if "V1" in e.message])
        assert v1_count_2 == 1


# ---------------------------------------------------------------------------
# ProactiveMonitor -- priority queue ordering
# ---------------------------------------------------------------------------


class TestPriorityOrdering:
    async def test_emergency_delivered_before_deviation(self) -> None:
        """Emergency events (priority 3) should come out before deviations (priority 2)."""
        detector = EmergencyDetector(thresholds=EmergencyThresholds(min_detection_duration=0))
        monitor = ProactiveMonitor(
            emergency_detector=detector,
            deviation_thresholds=DeviationThresholds(overspeed_ias=100.0),
        )

        # Healthy state with normal speed
        healthy = _make_state(phase=FlightPhase.CRUISE, rpm=2400.0, ias=90.0)
        # Engine failure AND overspeed at the same time
        crisis = _make_state(phase=FlightPhase.CRUISE, rpm=0.0, ias=200.0)

        await monitor.on_telemetry_update(healthy)
        await monitor.on_telemetry_update(crisis)

        events = await _drain_events(monitor)
        assert len(events) >= 2

        # First event should be the emergency
        assert events[0].type == "emergency"
        assert events[0].priority == 3


# ---------------------------------------------------------------------------
# ProactiveMonitor -- queue API
# ---------------------------------------------------------------------------


class TestQueueAPI:
    async def test_get_next_event_returns_none_when_empty(self) -> None:
        monitor = ProactiveMonitor()
        result = await monitor.get_next_event(timeout=0.01)
        assert result is None

    async def test_get_pending_count_zero_initially(self) -> None:
        monitor = ProactiveMonitor()
        assert monitor.get_pending_count() == 0

    async def test_get_pending_count_reflects_queue_size(self) -> None:
        monitor = ProactiveMonitor(
            deviation_thresholds=DeviationThresholds(overspeed_ias=100.0, max_bank_angle=30.0)
        )

        # Trigger both overspeed and bank angle
        state = _make_state(ias=200.0, bank=45.0, altitude_agl=3000.0)
        await monitor.on_telemetry_update(state)

        assert monitor.get_pending_count() >= 2

    async def test_first_update_no_emergency_without_prev(self) -> None:
        """First telemetry update should not generate emergency (no prev_state)."""
        detector = EmergencyDetector(thresholds=EmergencyThresholds(min_detection_duration=0))
        monitor = ProactiveMonitor(emergency_detector=detector)

        # Even a dead engine on first update should not fire emergency
        dead = _make_state(phase=FlightPhase.CRUISE, rpm=0.0)
        await monitor.on_telemetry_update(dead)

        events = await _drain_events(monitor)
        emergency_events = [e for e in events if e.type == "emergency"]
        assert len(emergency_events) == 0
