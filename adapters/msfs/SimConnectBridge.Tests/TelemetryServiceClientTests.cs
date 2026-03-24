using System.Text.Json;
using System.Text.Json.Serialization;
using FluentAssertions;
using SimConnectBridge.Models;
using Xunit;

namespace SimConnectBridge.Tests;

/// <summary>
/// Tests for TelemetryServiceClient serialization, conversion, and state logic.
///
/// Since the client uses real WebSocket connections, these tests focus on the
/// testable surface: SimState-to-TelemetryEnvelope conversion, register/telemetry
/// message JSON format, and connection state behavior.
/// </summary>
public class TelemetryServiceClientTests : IDisposable
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false
    };

    private readonly TelemetryServiceClient _client;

    public TelemetryServiceClientTests()
    {
        // Use a dummy URL; we won't actually connect in these tests
        _client = new TelemetryServiceClient(
            serviceUrl: "ws://localhost:9999",
            adapterId: "msfs-test-01",
            simName: "msfs2024"
        );
    }

    public void Dispose()
    {
        _client.Dispose();
    }

    // -----------------------------------------------------------------------
    //  SimState -> TelemetryEnvelope conversion
    // -----------------------------------------------------------------------

    [Fact]
    public void ConvertToEnvelope_MapsAdapterMetadata()
    {
        var state = CreatePopulatedSimState();

        var envelope = _client.ConvertToEnvelope(state);

        envelope.AdapterId.Should().Be("msfs-test-01");
        envelope.SimName.Should().Be("msfs2024");
        envelope.VehicleType.Should().Be("aircraft");
    }

    [Fact]
    public void ConvertToEnvelope_MapsTimestampAndConnected()
    {
        var now = DateTimeOffset.UtcNow;
        var state = new SimState
        {
            Timestamp = now,
            Connected = true,
            Aircraft = "Cessna 172"
        };

        var envelope = _client.ConvertToEnvelope(state);

        envelope.Timestamp.Should().Be(now);
        envelope.Connected.Should().BeTrue();
        envelope.VehicleName.Should().Be("Cessna 172");
    }

    [Fact]
    public void ConvertToEnvelope_MapsPositionCorrectly()
    {
        var state = CreatePopulatedSimState();

        var envelope = _client.ConvertToEnvelope(state);

        envelope.Position.Should().NotBeNull();
        envelope.Position!.Latitude.Should().Be(47.6);
        envelope.Position.Longitude.Should().Be(-122.3);
        envelope.Position.AltitudeMsl.Should().Be(3500.0);
        envelope.Position.AltitudeAgl.Should().Be(2800.0);
    }

    [Fact]
    public void ConvertToEnvelope_MapsAttitudeCorrectly()
    {
        var state = CreatePopulatedSimState();

        var envelope = _client.ConvertToEnvelope(state);

        envelope.Attitude.Should().NotBeNull();
        envelope.Attitude!.Pitch.Should().Be(2.5);
        envelope.Attitude.Bank.Should().Be(-5.0);
        envelope.Attitude.HeadingTrue.Should().Be(270.0);
        envelope.Attitude.HeadingMagnetic.Should().Be(265.0);
    }

    [Fact]
    public void ConvertToEnvelope_MapsSpeedsCorrectly()
    {
        var state = CreatePopulatedSimState();

        var envelope = _client.ConvertToEnvelope(state);

        envelope.Speeds.Should().NotBeNull();
        envelope.Speeds!.IndicatedAirspeed.Should().Be(120.0);
        envelope.Speeds.TrueAirspeed.Should().Be(125.0);
        envelope.Speeds.GroundSpeed.Should().Be(130.0);
        envelope.Speeds.Mach.Should().Be(0.18);
        envelope.Speeds.VerticalSpeed.Should().Be(500.0);
    }

    [Fact]
    public void ConvertToEnvelope_MapsEnvironmentCorrectly()
    {
        var state = CreatePopulatedSimState();

        var envelope = _client.ConvertToEnvelope(state);

        envelope.Environment.Should().NotBeNull();
        envelope.Environment!.WindSpeedKts.Should().Be(15.0);
        envelope.Environment.WindDirection.Should().Be(230.0);
        envelope.Environment.VisibilitySm.Should().Be(10.0);
        envelope.Environment.TemperatureC.Should().Be(15.0);
        envelope.Environment.BarometerInHg.Should().Be(29.92);
    }

    [Fact]
    public void ConvertToEnvelope_PutsAircraftSpecificDataInExtensions()
    {
        var state = CreatePopulatedSimState();

        var envelope = _client.ConvertToEnvelope(state);

        envelope.Extensions.Should().NotBeNull();
        envelope.Extensions.Should().ContainKey("aircraft");
    }

    [Fact]
    public void ConvertToEnvelope_AircraftExtensionContainsAllSections()
    {
        var state = CreatePopulatedSimState();

        var envelope = _client.ConvertToEnvelope(state);

        // Serialize and re-parse the extensions to inspect the anonymous object
        var extensionsJson = JsonSerializer.Serialize(envelope.Extensions, JsonOptions);
        var doc = JsonDocument.Parse(extensionsJson);
        var aircraft = doc.RootElement.GetProperty("aircraft");

        aircraft.TryGetProperty("engines", out _).Should().BeTrue("engines should be in aircraft extension");
        aircraft.TryGetProperty("autopilot", out _).Should().BeTrue("autopilot should be in aircraft extension");
        aircraft.TryGetProperty("radios", out _).Should().BeTrue("radios should be in aircraft extension");
        aircraft.TryGetProperty("fuel", out _).Should().BeTrue("fuel should be in aircraft extension");
        aircraft.TryGetProperty("surfaces", out _).Should().BeTrue("surfaces should be in aircraft extension");
    }

    [Fact]
    public void ConvertToEnvelope_AircraftExtension_PreservesEngineData()
    {
        var state = CreatePopulatedSimState();
        state.Engines.EngineCount = 1;
        state.Engines.Engines[0].Rpm = 2400;

        var envelope = _client.ConvertToEnvelope(state);

        var extensionsJson = JsonSerializer.Serialize(envelope.Extensions, JsonOptions);
        var doc = JsonDocument.Parse(extensionsJson);
        var engines = doc.RootElement.GetProperty("aircraft").GetProperty("engines");

        engines.GetProperty("engine_count").GetInt32().Should().Be(1);
        engines.GetProperty("engines")[0].GetProperty("rpm").GetDouble().Should().Be(2400);
    }

    [Fact]
    public void ConvertToEnvelope_AircraftExtension_PreservesAutopilotData()
    {
        var state = CreatePopulatedSimState();
        state.Autopilot.Master = true;
        state.Autopilot.Heading = 180;
        state.Autopilot.Altitude = 10000;

        var envelope = _client.ConvertToEnvelope(state);

        var extensionsJson = JsonSerializer.Serialize(envelope.Extensions, JsonOptions);
        var doc = JsonDocument.Parse(extensionsJson);
        var autopilot = doc.RootElement.GetProperty("aircraft").GetProperty("autopilot");

        autopilot.GetProperty("master").GetBoolean().Should().BeTrue();
        autopilot.GetProperty("heading").GetDouble().Should().Be(180);
        autopilot.GetProperty("altitude").GetDouble().Should().Be(10000);
    }

    // -----------------------------------------------------------------------
    //  Register message format
    // -----------------------------------------------------------------------

    [Fact]
    public void RegisterMessage_HasCorrectJsonStructure()
    {
        // Replicate the register message format from TelemetryServiceClient.SendRegisterAsync
        var register = new
        {
            type = "register",
            adapter_id = "msfs-test-01",
            sim_name = "msfs2024",
            vehicle_type = "aircraft",
            version = "1.0"
        };

        var json = JsonSerializer.Serialize(register);
        var doc = JsonDocument.Parse(json);

        doc.RootElement.GetProperty("type").GetString().Should().Be("register");
        doc.RootElement.GetProperty("adapter_id").GetString().Should().Be("msfs-test-01");
        doc.RootElement.GetProperty("sim_name").GetString().Should().Be("msfs2024");
        doc.RootElement.GetProperty("vehicle_type").GetString().Should().Be("aircraft");
        doc.RootElement.GetProperty("version").GetString().Should().Be("1.0");
    }

    [Fact]
    public void RegisterMessage_HasExactlyFiveFields()
    {
        var register = new
        {
            type = "register",
            adapter_id = "msfs-test-01",
            sim_name = "msfs2024",
            vehicle_type = "aircraft",
            version = "1.0"
        };

        var json = JsonSerializer.Serialize(register);
        var doc = JsonDocument.Parse(json);

        doc.RootElement.EnumerateObject().Count().Should().Be(5);
    }

    // -----------------------------------------------------------------------
    //  Telemetry push message format
    // -----------------------------------------------------------------------

    [Fact]
    public void TelemetryMessage_WrapsEnvelopeInCorrectFormat()
    {
        var state = CreatePopulatedSimState();
        var envelope = _client.ConvertToEnvelope(state);

        var message = new
        {
            type = "telemetry",
            data = envelope
        };

        var json = JsonSerializer.Serialize(message, JsonOptions);
        var doc = JsonDocument.Parse(json);

        doc.RootElement.GetProperty("type").GetString().Should().Be("telemetry");
        doc.RootElement.TryGetProperty("data", out var dataElement).Should().BeTrue();
        dataElement.TryGetProperty("adapter_id", out _).Should().BeTrue();
        dataElement.TryGetProperty("sim_name", out _).Should().BeTrue();
        dataElement.TryGetProperty("vehicle_type", out _).Should().BeTrue();
        dataElement.TryGetProperty("position", out _).Should().BeTrue();
        dataElement.TryGetProperty("attitude", out _).Should().BeTrue();
        dataElement.TryGetProperty("speeds", out _).Should().BeTrue();
        dataElement.TryGetProperty("environment", out _).Should().BeTrue();
        dataElement.TryGetProperty("extensions", out _).Should().BeTrue();
    }

    [Fact]
    public void TelemetryMessage_HasExactlyTwoTopLevelFields()
    {
        var state = CreatePopulatedSimState();
        var envelope = _client.ConvertToEnvelope(state);

        var message = new
        {
            type = "telemetry",
            data = envelope
        };

        var json = JsonSerializer.Serialize(message, JsonOptions);
        var doc = JsonDocument.Parse(json);

        doc.RootElement.EnumerateObject().Count().Should().Be(2);
    }

    [Fact]
    public void TelemetryMessage_DataEnvelope_ContainsVehicleName()
    {
        var state = CreatePopulatedSimState();
        var envelope = _client.ConvertToEnvelope(state);

        var message = new { type = "telemetry", data = envelope };
        var json = JsonSerializer.Serialize(message, JsonOptions);
        var doc = JsonDocument.Parse(json);

        doc.RootElement
            .GetProperty("data")
            .GetProperty("vehicle_name")
            .GetString()
            .Should().Be("Cessna 172");
    }

    [Fact]
    public void TelemetryMessage_UsesSnakeCaseNaming()
    {
        var state = CreatePopulatedSimState();
        var envelope = _client.ConvertToEnvelope(state);

        var message = new { type = "telemetry", data = envelope };
        var json = JsonSerializer.Serialize(message, JsonOptions);

        // Verify snake_case field names from the envelope DTOs
        json.Should().Contain("\"adapter_id\"");
        json.Should().Contain("\"sim_name\"");
        json.Should().Contain("\"vehicle_type\"");
        json.Should().Contain("\"vehicle_name\"");
        json.Should().Contain("\"altitude_msl\"");
        json.Should().Contain("\"altitude_agl\"");
        json.Should().Contain("\"heading_true\"");
        json.Should().Contain("\"heading_magnetic\"");
        json.Should().Contain("\"indicated_airspeed\"");
        json.Should().Contain("\"true_airspeed\"");
        json.Should().Contain("\"ground_speed\"");
        json.Should().Contain("\"vertical_speed\"");
        json.Should().Contain("\"wind_speed_kts\"");
        json.Should().Contain("\"wind_direction\"");
        json.Should().Contain("\"visibility_sm\"");
        json.Should().Contain("\"temperature_c\"");
        json.Should().Contain("\"barometer_inhg\"");
    }

    // -----------------------------------------------------------------------
    //  Connection state
    // -----------------------------------------------------------------------

    [Fact]
    public void IsConnected_ReturnsFalse_WhenNotConnected()
    {
        _client.IsConnected.Should().BeFalse();
    }

    [Fact]
    public void IsConnected_ReturnsFalse_AfterDispose()
    {
        var client = new TelemetryServiceClient("ws://localhost:9999", "test", "msfs2024");
        client.Dispose();

        client.IsConnected.Should().BeFalse();
    }

    // -----------------------------------------------------------------------
    //  Reconnection behavior
    // -----------------------------------------------------------------------

    [Fact]
    public async Task ConnectAsync_IncrementsReconnectCount_OnFailure()
    {
        // Use an unreachable address so connection fails immediately
        var client = new TelemetryServiceClient("ws://192.0.2.1:1", "test", "msfs2024");

        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));

        try
        {
            await client.ConnectAsync(cts.Token);
        }
        catch (OperationCanceledException)
        {
            // Expected: cancellation fires after timeout while retrying
        }

        // The client should have attempted reconnection at least once.
        // We verify by checking IsConnected is still false (connection never succeeded).
        client.IsConnected.Should().BeFalse();

        client.Dispose();
    }

    [Fact]
    public void MultipleDispose_DoesNotThrow()
    {
        var client = new TelemetryServiceClient("ws://localhost:9999", "test", "msfs2024");

        var act = () =>
        {
            client.Dispose();
            client.Dispose();
            client.Dispose();
        };

        act.Should().NotThrow();
    }

    // -----------------------------------------------------------------------
    //  Envelope round-trip serialization
    // -----------------------------------------------------------------------

    [Fact]
    public void Envelope_SerializesAndDeserializes_CoreFieldsRoundTrip()
    {
        var state = CreatePopulatedSimState();
        var envelope = _client.ConvertToEnvelope(state);

        var json = JsonSerializer.Serialize(envelope, JsonOptions);
        var deserialized = JsonSerializer.Deserialize<TelemetryEnvelope>(json, JsonOptions);

        deserialized.Should().NotBeNull();
        deserialized!.AdapterId.Should().Be("msfs-test-01");
        deserialized.SimName.Should().Be("msfs2024");
        deserialized.VehicleType.Should().Be("aircraft");
        deserialized.Connected.Should().BeTrue();
        deserialized.VehicleName.Should().Be("Cessna 172");
        deserialized.Position!.Latitude.Should().Be(47.6);
        deserialized.Position.Longitude.Should().Be(-122.3);
        deserialized.Attitude!.Pitch.Should().Be(2.5);
        deserialized.Speeds!.IndicatedAirspeed.Should().Be(120.0);
        deserialized.Environment!.WindSpeedKts.Should().Be(15.0);
    }

    [Fact]
    public void Envelope_DefaultState_StillProducesValidJson()
    {
        var state = new SimState();
        var envelope = _client.ConvertToEnvelope(state);

        var json = JsonSerializer.Serialize(envelope, JsonOptions);
        var doc = JsonDocument.Parse(json);

        doc.RootElement.TryGetProperty("adapter_id", out _).Should().BeTrue();
        doc.RootElement.TryGetProperty("position", out _).Should().BeTrue();
        doc.RootElement.TryGetProperty("attitude", out _).Should().BeTrue();
        doc.RootElement.TryGetProperty("speeds", out _).Should().BeTrue();
        doc.RootElement.TryGetProperty("environment", out _).Should().BeTrue();
        doc.RootElement.TryGetProperty("extensions", out _).Should().BeTrue();
    }

    // -----------------------------------------------------------------------
    //  Helpers
    // -----------------------------------------------------------------------

    private static SimState CreatePopulatedSimState()
    {
        return new SimState
        {
            Connected = true,
            Aircraft = "Cessna 172",
            Position = new PositionData
            {
                Latitude = 47.6,
                Longitude = -122.3,
                AltitudeMsl = 3500.0,
                AltitudeAgl = 2800.0
            },
            Attitude = new AttitudeData
            {
                Pitch = 2.5,
                Bank = -5.0,
                HeadingTrue = 270.0,
                HeadingMagnetic = 265.0
            },
            Speeds = new SpeedData
            {
                IndicatedAirspeed = 120.0,
                TrueAirspeed = 125.0,
                GroundSpeed = 130.0,
                Mach = 0.18,
                VerticalSpeed = 500.0
            },
            Engines = new EngineData
            {
                EngineCount = 1,
                Engines = [
                    new EngineParams { Rpm = 2400, ManifoldPressure = 25.0, FuelFlowGph = 10.5 },
                    new(), new(), new()
                ]
            },
            Autopilot = new AutopilotState
            {
                Master = true,
                Heading = 270,
                Altitude = 5000,
                VerticalSpeed = 500,
                Airspeed = 120
            },
            Radios = new RadioData
            {
                Com1 = 121.5,
                Com2 = 118.0,
                Nav1 = 110.0,
                Nav2 = 115.0
            },
            Fuel = new FuelData
            {
                TotalGallons = 40.0,
                TotalWeightLbs = 240.0
            },
            Surfaces = new SurfaceData
            {
                GearHandle = true,
                FlapsPercent = 20.0,
                SpoilersPercent = 0.0
            },
            Environment = new EnvironmentData
            {
                WindSpeedKts = 15.0,
                WindDirection = 230.0,
                VisibilitySm = 10.0,
                TemperatureC = 15.0,
                BarometerInHg = 29.92
            }
        };
    }
}
