"""Tests for the universal telemetry schema."""

from __future__ import annotations

from telemetry.schema import (
    AircraftExtensions,
    EngineData,
    Engines,
    FuelState,
    Position,
    TelemetryEnvelope,
)


class TestPosition:
    def test_defaults(self):
        pos = Position()
        assert pos.latitude == 0.0
        assert pos.longitude == 0.0
        assert pos.altitude_msl == 0.0
        assert pos.altitude_agl == 0.0

    def test_from_values(self):
        pos = Position(latitude=47.45, longitude=-122.31, altitude_msl=5500)
        assert pos.latitude == 47.45


class TestTelemetryEnvelope:
    def test_defaults(self):
        env = TelemetryEnvelope()
        assert env.adapter_id == ""
        assert env.vehicle_type == "aircraft"
        assert env.connected is False
        assert env.extensions == {}

    def test_full_roundtrip(self, sample_envelope: TelemetryEnvelope):
        """Serialize and deserialize a full envelope."""
        data = sample_envelope.model_dump()
        restored = TelemetryEnvelope.model_validate(data)
        assert restored.adapter_id == "msfs-adapter"
        assert restored.sim_name == "msfs2024"
        assert restored.position is not None
        assert restored.position.latitude == 47.4502

    def test_aircraft_extensions(self, sample_envelope: TelemetryEnvelope):
        """Aircraft extensions should be accessible via the property."""
        ext = sample_envelope.aircraft
        assert ext is not None
        assert ext.engines is not None
        assert ext.engines.engine_count == 1
        assert ext.autopilot is not None
        assert ext.radios is not None
        assert ext.fuel is not None
        assert ext.surfaces is not None

    def test_to_legacy_simstate(self, sample_envelope: TelemetryEnvelope):
        """Legacy format should flatten aircraft extensions to top level."""
        legacy = sample_envelope.to_legacy_simstate()
        assert legacy["aircraft"] == "Cessna 172 Skyhawk"
        assert legacy["connected"] is True
        assert "position" in legacy
        assert legacy["position"]["latitude"] == 47.4502
        # Aircraft-specific should be at top level
        assert "engines" in legacy
        assert legacy["engines"]["engine_count"] == 1
        assert "autopilot" in legacy
        assert "radios" in legacy
        assert "fuel" in legacy
        assert "surfaces" in legacy

    def test_with_aircraft_extensions(self):
        """Test the convenience method for setting aircraft extensions."""
        env = TelemetryEnvelope(adapter_id="test")
        ext = AircraftExtensions(fuel=FuelState(total_gallons=50.0))
        env.with_aircraft_extensions(ext)
        assert "aircraft" in env.extensions
        restored_ext = env.aircraft
        assert restored_ext is not None
        assert restored_ext.fuel is not None
        assert restored_ext.fuel.total_gallons == 50.0

    def test_no_aircraft_extensions(self):
        """Envelope without extensions should return None."""
        env = TelemetryEnvelope(adapter_id="car-adapter", vehicle_type="car")
        assert env.aircraft is None


class TestAircraftExtensions:
    def test_engines_active(self):
        ext = AircraftExtensions(
            engines=Engines(
                engine_count=2,
                engines=[
                    EngineData(rpm=2400),
                    EngineData(rpm=2350),
                    EngineData(),
                    EngineData(),
                ],
            )
        )
        assert len(ext.engines.active_engines) == 2
        assert ext.engines.active_engines[0].rpm == 2400

    def test_all_none(self):
        ext = AircraftExtensions()
        assert ext.engines is None
        assert ext.autopilot is None
        assert ext.radios is None
        assert ext.fuel is None
        assert ext.surfaces is None
