using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using SimConnectBridge.Models;

namespace SimConnectBridge;

/// <summary>
/// WebSocket client that pushes telemetry to the universal telemetry service.
///
/// Replaces the old TelemetryWebSocketServer: instead of hosting a WS server
/// and broadcasting directly, this adapter connects as a client to the
/// telemetry service's ingest endpoint and pushes TelemetryEnvelope frames.
/// </summary>
public sealed class TelemetryServiceClient : IDisposable
{
    private ClientWebSocket? _ws;
    private readonly string _serviceUrl;
    private readonly string _adapterId;
    private readonly string _simName;
    private readonly CancellationTokenSource _cts = new();
    private readonly JsonSerializerOptions _jsonOptions;
    private Task? _receiveTask;
    private bool _disposed;
    private bool _registered;
    private int _reconnectCount;

    // Reconnection parameters
    private const double ReconnectBaseDelay = 1.0;
    private const double ReconnectMaxDelay = 30.0;
    private const double ReconnectBackoffFactor = 2.0;

    public TelemetryServiceClient(string serviceUrl, string adapterId, string simName = "msfs2024")
    {
        _serviceUrl = serviceUrl;
        _adapterId = adapterId;
        _simName = simName;

        _jsonOptions = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            WriteIndented = false
        };
    }

    public bool IsConnected => _ws?.State == WebSocketState.Open && _registered;

    /// <summary>
    /// Connect to the telemetry service and register as an adapter.
    /// Runs a background receive loop and auto-reconnects on failure.
    /// </summary>
    public async Task ConnectAsync(CancellationToken ct)
    {
        var linked = CancellationTokenSource.CreateLinkedTokenSource(ct, _cts.Token);

        while (!linked.Token.IsCancellationRequested)
        {
            try
            {
                Log("INFO", $"Connecting to telemetry service at {_serviceUrl}");
                _ws = new ClientWebSocket();
                await _ws.ConnectAsync(new Uri(_serviceUrl), linked.Token);
                Log("INFO", "Connected to telemetry service");

                await SendRegisterAsync(linked.Token);
                _registered = true;
                _reconnectCount = 0;

                // Background receive loop (for acks, commands, etc.)
                _receiveTask = Task.Run(() => ReceiveLoopAsync(linked.Token), linked.Token);

                return;
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception ex)
            {
                _registered = false;
                _reconnectCount++;
                var delay = Math.Min(
                    ReconnectBaseDelay * Math.Pow(ReconnectBackoffFactor, _reconnectCount - 1),
                    ReconnectMaxDelay
                );
                Log("WARN", $"Connection failed (attempt {_reconnectCount}): {ex.Message}. Retrying in {delay:F1}s");
                try { await Task.Delay(TimeSpan.FromSeconds(delay), linked.Token); }
                catch (OperationCanceledException) { return; }
            }
        }
    }

    /// <summary>
    /// Push a SimState update to the telemetry service as a TelemetryEnvelope.
    /// </summary>
    public async Task PushStateAsync(SimState state)
    {
        if (_ws?.State != WebSocketState.Open || !_registered)
            return;

        try
        {
            var envelope = ConvertToEnvelope(state);
            var message = new
            {
                type = "telemetry",
                data = envelope
            };

            var json = JsonSerializer.Serialize(message, _jsonOptions);
            var bytes = Encoding.UTF8.GetBytes(json);
            await _ws.SendAsync(
                new ArraySegment<byte>(bytes),
                WebSocketMessageType.Text,
                endOfMessage: true,
                cancellationToken: _cts.Token
            );
        }
        catch (WebSocketException ex)
        {
            Log("WARN", $"Send failed: {ex.Message}");
            _registered = false;
            _ = Task.Run(() => ReconnectAsync());
        }
        catch (Exception ex)
        {
            Log("DEBUG", $"PushState error: {ex.Message}");
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _cts.Cancel();
        try
        {
            if (_ws?.State == WebSocketState.Open)
            {
                _ws.CloseAsync(
                    WebSocketCloseStatus.NormalClosure,
                    "Adapter shutting down",
                    CancellationToken.None
                ).GetAwaiter().GetResult();
            }
        }
        catch { /* best-effort */ }
        _ws?.Dispose();
        _cts.Dispose();
        Log("INFO", "Telemetry service client disposed");
    }

    // -----------------------------------------------------------------------
    //  Registration
    // -----------------------------------------------------------------------

    private async Task SendRegisterAsync(CancellationToken ct)
    {
        var register = new
        {
            type = "register",
            adapter_id = _adapterId,
            sim_name = _simName,
            vehicle_type = "aircraft",
            version = "1.0"
        };

        var json = JsonSerializer.Serialize(register);
        var bytes = Encoding.UTF8.GetBytes(json);
        await _ws!.SendAsync(
            new ArraySegment<byte>(bytes),
            WebSocketMessageType.Text,
            endOfMessage: true,
            cancellationToken: ct
        );

        Log("INFO", $"Registered as adapter '{_adapterId}' (sim={_simName})");
    }

    // -----------------------------------------------------------------------
    //  Receive loop (for acks, commands, errors)
    // -----------------------------------------------------------------------

    private async Task ReceiveLoopAsync(CancellationToken ct)
    {
        var buffer = new byte[4096];
        try
        {
            while (!ct.IsCancellationRequested && _ws?.State == WebSocketState.Open)
            {
                var result = await _ws.ReceiveAsync(new ArraySegment<byte>(buffer), ct);
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    Log("INFO", "Telemetry service closed connection");
                    break;
                }

                if (result.MessageType == WebSocketMessageType.Text)
                {
                    var msg = Encoding.UTF8.GetString(buffer, 0, result.Count);
                    Log("DEBUG", $"Received from service: {msg}");
                }
            }
        }
        catch (OperationCanceledException) { }
        catch (WebSocketException ex)
        {
            Log("WARN", $"Receive loop error: {ex.Message}");
        }

        // Trigger reconnect if not shutting down
        if (!ct.IsCancellationRequested)
        {
            _registered = false;
            _ = Task.Run(() => ReconnectAsync());
        }
    }

    // -----------------------------------------------------------------------
    //  Reconnection
    // -----------------------------------------------------------------------

    private async Task ReconnectAsync()
    {
        _registered = false;
        var delay = ReconnectBaseDelay;

        while (!_cts.Token.IsCancellationRequested)
        {
            _reconnectCount++;
            Log("INFO", $"Reconnection attempt {_reconnectCount} (delay={delay:F1}s)");

            try
            {
                await Task.Delay(TimeSpan.FromSeconds(delay), _cts.Token);
                _ws?.Dispose();
                _ws = new ClientWebSocket();
                await _ws.ConnectAsync(new Uri(_serviceUrl), _cts.Token);
                await SendRegisterAsync(_cts.Token);
                _registered = true;
                Log("INFO", $"Reconnected to telemetry service (attempt {_reconnectCount})");

                _receiveTask = Task.Run(() => ReceiveLoopAsync(_cts.Token));
                return;
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception ex)
            {
                Log("WARN", $"Reconnect attempt {_reconnectCount} failed: {ex.Message}");
                delay = Math.Min(delay * ReconnectBackoffFactor, ReconnectMaxDelay);
            }
        }
    }

    // -----------------------------------------------------------------------
    //  SimState → TelemetryEnvelope conversion
    // -----------------------------------------------------------------------

    /// <summary>
    /// Converts the internal SimState to the universal TelemetryEnvelope format.
    /// Core fields map directly; aircraft-specific data goes into extensions.
    /// </summary>
    private TelemetryEnvelope ConvertToEnvelope(SimState state)
    {
        return new TelemetryEnvelope
        {
            AdapterId = _adapterId,
            SimName = _simName,
            VehicleType = "aircraft",
            Timestamp = state.Timestamp,
            Connected = state.Connected,
            VehicleName = state.Aircraft,
            Position = new EnvelopePosition
            {
                Latitude = state.Position.Latitude,
                Longitude = state.Position.Longitude,
                AltitudeMsl = state.Position.AltitudeMsl,
                AltitudeAgl = state.Position.AltitudeAgl
            },
            Attitude = new EnvelopeAttitude
            {
                Pitch = state.Attitude.Pitch,
                Bank = state.Attitude.Bank,
                HeadingTrue = state.Attitude.HeadingTrue,
                HeadingMagnetic = state.Attitude.HeadingMagnetic
            },
            Speeds = new EnvelopeSpeeds
            {
                IndicatedAirspeed = state.Speeds.IndicatedAirspeed,
                TrueAirspeed = state.Speeds.TrueAirspeed,
                GroundSpeed = state.Speeds.GroundSpeed,
                Mach = state.Speeds.Mach,
                VerticalSpeed = state.Speeds.VerticalSpeed
            },
            Environment = new EnvelopeEnvironment
            {
                WindSpeedKts = state.Environment.WindSpeedKts,
                WindDirection = state.Environment.WindDirection,
                VisibilitySm = state.Environment.VisibilitySm,
                TemperatureC = state.Environment.TemperatureC,
                BarometerInHg = state.Environment.BarometerInHg
            },
            Extensions = new Dictionary<string, object>
            {
                ["aircraft"] = new
                {
                    engines = state.Engines,
                    autopilot = state.Autopilot,
                    radios = state.Radios,
                    fuel = state.Fuel,
                    surfaces = state.Surfaces
                }
            }
        };
    }

    private static void Log(string level, string message)
    {
        var ts = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ");
        Console.WriteLine($"{ts} [{level}] TelemetryClient: {message}");
    }
}

// ---------------------------------------------------------------------------
//  TelemetryEnvelope DTOs (serialized to JSON for the telemetry service)
// ---------------------------------------------------------------------------

/// <summary>
/// Universal telemetry envelope matching the Python TelemetryEnvelope schema.
/// </summary>
public sealed class TelemetryEnvelope
{
    [JsonPropertyName("adapter_id")]
    public string AdapterId { get; set; } = "";

    [JsonPropertyName("sim_name")]
    public string SimName { get; set; } = "";

    [JsonPropertyName("vehicle_type")]
    public string VehicleType { get; set; } = "aircraft";

    [JsonPropertyName("timestamp")]
    public DateTimeOffset Timestamp { get; set; }

    [JsonPropertyName("connected")]
    public bool Connected { get; set; }

    [JsonPropertyName("vehicle_name")]
    public string VehicleName { get; set; } = "";

    [JsonPropertyName("position")]
    public EnvelopePosition? Position { get; set; }

    [JsonPropertyName("attitude")]
    public EnvelopeAttitude? Attitude { get; set; }

    [JsonPropertyName("speeds")]
    public EnvelopeSpeeds? Speeds { get; set; }

    [JsonPropertyName("environment")]
    public EnvelopeEnvironment? Environment { get; set; }

    [JsonPropertyName("extensions")]
    public Dictionary<string, object>? Extensions { get; set; }
}

public sealed class EnvelopePosition
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

public sealed class EnvelopeAttitude
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

public sealed class EnvelopeSpeeds
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

public sealed class EnvelopeEnvironment
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
