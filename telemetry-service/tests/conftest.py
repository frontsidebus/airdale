"""Shared test fixtures for the telemetry service."""

from __future__ import annotations

import pytest
from telemetry.schema import (
    AircraftExtensions,
    Attitude,
    AutopilotState,
    EngineData,
    Engines,
    Environment,
    FuelState,
    Position,
    RadioState,
    Speeds,
    SurfaceState,
    TelemetryEnvelope,
)


@pytest.fixture
def sample_position() -> Position:
    return Position(
        latitude=47.4502,
        longitude=-122.3088,
        altitude_msl=5500.0,
        altitude_agl=4200.0,
    )


@pytest.fixture
def sample_envelope(sample_position: Position) -> TelemetryEnvelope:
    """A fully-populated telemetry envelope for testing."""
    envelope = TelemetryEnvelope(
        adapter_id="msfs-adapter",
        sim_name="msfs2024",
        vehicle_type="aircraft",
        timestamp="2026-03-22T22:00:00Z",
        connected=True,
        vehicle_name="Cessna 172 Skyhawk",
        position=sample_position,
        attitude=Attitude(
            pitch=-2.5,
            bank=5.0,
            heading_true=270.0,
            heading_magnetic=268.0,
        ),
        speeds=Speeds(
            indicated_airspeed=120.0,
            true_airspeed=125.0,
            ground_speed=130.0,
            mach=0.18,
            vertical_speed=-200.0,
        ),
        environment=Environment(
            wind_speed_kts=10.0,
            wind_direction=180.0,
            visibility_sm=10.0,
            temperature_c=15.0,
            barometer_inhg=29.92,
        ),
    )
    aircraft_ext = AircraftExtensions(
        engines=Engines(
            engine_count=1,
            engines=[
                EngineData(
                    rpm=2400.0,
                    manifold_pressure=24.0,
                    fuel_flow_gph=10.5,
                    egt=1200.0,
                    oil_temp=180.0,
                    oil_pressure=60.0,
                )
            ],
        ),
        autopilot=AutopilotState(
            master=False,
            heading=270.0,
            altitude=5500.0,
        ),
        radios=RadioState(com1=124.0, com2=121.5, nav1=110.0, nav2=115.0),
        fuel=FuelState(total_gallons=40.0, total_weight_lbs=240.0),
        surfaces=SurfaceState(gear_handle=True, flaps_percent=0.0, spoilers_percent=0.0),
    )
    envelope.with_aircraft_extensions(aircraft_ext)
    return envelope


@pytest.fixture
def sample_register_message() -> dict:
    return {
        "type": "register",
        "adapter_id": "msfs-adapter",
        "sim_name": "msfs2024",
        "vehicle_type": "aircraft",
        "version": "1.0",
    }


@pytest.fixture
def sample_telemetry_message(sample_envelope: TelemetryEnvelope) -> dict:
    return {
        "type": "telemetry",
        "data": sample_envelope.model_dump(),
    }
