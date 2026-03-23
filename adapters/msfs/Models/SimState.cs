using System.Text.Json.Serialization;

namespace SimConnectBridge.Models;

/// <summary>
/// Complete simulation state transmitted to clients. Mirrors the Python-side SimState model.
/// </summary>
public sealed class SimState
{
    [JsonPropertyName("timestamp")]
    public DateTimeOffset Timestamp { get; set; } = DateTimeOffset.UtcNow;

    [JsonPropertyName("connected")]
    public bool Connected { get; set; }

    [JsonPropertyName("aircraft")]
    public string Aircraft { get; set; } = string.Empty;

    [JsonPropertyName("position")]
    public PositionData Position { get; set; } = new();

    [JsonPropertyName("attitude")]
    public AttitudeData Attitude { get; set; } = new();

    [JsonPropertyName("speeds")]
    public SpeedData Speeds { get; set; } = new();

    [JsonPropertyName("engines")]
    public EngineData Engines { get; set; } = new();

    [JsonPropertyName("autopilot")]
    public AutopilotState Autopilot { get; set; } = new();

    [JsonPropertyName("radios")]
    public RadioData Radios { get; set; } = new();

    [JsonPropertyName("fuel")]
    public FuelData Fuel { get; set; } = new();

    [JsonPropertyName("surfaces")]
    public SurfaceData Surfaces { get; set; } = new();

    [JsonPropertyName("environment")]
    public EnvironmentData Environment { get; set; } = new();
}

/// <summary>
/// Aircraft position in the world.
/// </summary>
public sealed class PositionData
{
    [JsonPropertyName("latitude")]
    public double Latitude { get; set; }

    [JsonPropertyName("longitude")]
    public double Longitude { get; set; }

    [JsonPropertyName("altitude_msl")]
    public double AltitudeMsl { get; set; }

    [JsonPropertyName("altitude_agl")]
    public double AltitudeAgl { get; set; }
}

/// <summary>
/// Aircraft attitude (orientation).
/// </summary>
public sealed class AttitudeData
{
    [JsonPropertyName("pitch")]
    public double Pitch { get; set; }

    [JsonPropertyName("bank")]
    public double Bank { get; set; }

    [JsonPropertyName("heading_true")]
    public double HeadingTrue { get; set; }

    [JsonPropertyName("heading_magnetic")]
    public double HeadingMagnetic { get; set; }
}

/// <summary>
/// Aircraft speed values.
/// </summary>
public sealed class SpeedData
{
    [JsonPropertyName("indicated_airspeed")]
    public double IndicatedAirspeed { get; set; }

    [JsonPropertyName("true_airspeed")]
    public double TrueAirspeed { get; set; }

    [JsonPropertyName("ground_speed")]
    public double GroundSpeed { get; set; }

    [JsonPropertyName("mach")]
    public double Mach { get; set; }

    [JsonPropertyName("vertical_speed")]
    public double VerticalSpeed { get; set; }
}

/// <summary>
/// Engine parameters for up to four engines.
/// </summary>
public sealed class EngineData
{
    [JsonPropertyName("engine_count")]
    public int EngineCount { get; set; }

    [JsonPropertyName("engines")]
    public EngineParams[] Engines { get; set; } = [new(), new(), new(), new()];
}

/// <summary>
/// Parameters for a single engine.
/// </summary>
public sealed class EngineParams
{
    [JsonPropertyName("rpm")]
    public double Rpm { get; set; }

    [JsonPropertyName("manifold_pressure")]
    public double ManifoldPressure { get; set; }

    [JsonPropertyName("fuel_flow_gph")]
    public double FuelFlowGph { get; set; }

    [JsonPropertyName("egt")]
    public double ExhaustGasTemp { get; set; }

    [JsonPropertyName("oil_temp")]
    public double OilTemp { get; set; }

    [JsonPropertyName("oil_pressure")]
    public double OilPressure { get; set; }
}

/// <summary>
/// Autopilot state and settings.
/// </summary>
public sealed class AutopilotState
{
    [JsonPropertyName("master")]
    public bool Master { get; set; }

    [JsonPropertyName("heading")]
    public double Heading { get; set; }

    [JsonPropertyName("altitude")]
    public double Altitude { get; set; }

    [JsonPropertyName("vertical_speed")]
    public double VerticalSpeed { get; set; }

    [JsonPropertyName("airspeed")]
    public double Airspeed { get; set; }
}

/// <summary>
/// Radio frequencies.
/// </summary>
public sealed class RadioData
{
    [JsonPropertyName("com1")]
    public double Com1 { get; set; }

    [JsonPropertyName("com2")]
    public double Com2 { get; set; }

    [JsonPropertyName("nav1")]
    public double Nav1 { get; set; }

    [JsonPropertyName("nav2")]
    public double Nav2 { get; set; }
}

/// <summary>
/// Fuel state.
/// </summary>
public sealed class FuelData
{
    [JsonPropertyName("total_gallons")]
    public double TotalGallons { get; set; }

    [JsonPropertyName("total_weight_lbs")]
    public double TotalWeightLbs { get; set; }
}

/// <summary>
/// Control surface positions.
/// </summary>
public sealed class SurfaceData
{
    [JsonPropertyName("gear_handle")]
    public bool GearHandle { get; set; }

    [JsonPropertyName("flaps_percent")]
    public double FlapsPercent { get; set; }

    [JsonPropertyName("spoilers_percent")]
    public double SpoilersPercent { get; set; }
}

/// <summary>
/// Ambient environment conditions.
/// </summary>
public sealed class EnvironmentData
{
    [JsonPropertyName("wind_speed_kts")]
    public double WindSpeedKts { get; set; }

    [JsonPropertyName("wind_direction")]
    public double WindDirection { get; set; }

    [JsonPropertyName("visibility_sm")]
    public double VisibilitySm { get; set; }

    [JsonPropertyName("temperature_c")]
    public double TemperatureC { get; set; }

    [JsonPropertyName("barometer_inhg")]
    public double BarometerInHg { get; set; }
}
