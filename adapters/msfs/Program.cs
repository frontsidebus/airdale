using System.Text.Json;
using SimConnectBridge;

// ---------------------------------------------------------------------------
//  MERLIN MSFS Adapter
//  Connects to MSFS 2024 via SimConnect and pushes telemetry to the
//  universal telemetry service.
//
//  The adapter automatically reconnects to both MSFS and the telemetry
//  service independently.
// ---------------------------------------------------------------------------

Log("INFO", "=== MERLIN MSFS Adapter ===");

// Load configuration
var config = LoadConfiguration();

string appName = config.GetProperty("SimConnect").GetProperty("AppName").GetString()
    ?? "MERLIN SimConnect Bridge";
int highHz = config.GetProperty("SimConnect").GetProperty("HighFrequencyHz").GetInt32();
int lowHz = config.GetProperty("SimConnect").GetProperty("LowFrequencyHz").GetInt32();

// Telemetry service configuration
string serviceUrl = config.GetProperty("TelemetryService").GetProperty("Url").GetString()
    ?? "ws://localhost:8081/ws/ingest";
string adapterId = config.GetProperty("TelemetryService").GetProperty("AdapterId").GetString()
    ?? "msfs-adapter";

Log("INFO", $"Config: HF={highHz}Hz, LF={lowHz}Hz, Service={serviceUrl}");

// Set up cancellation for graceful shutdown
using var cts = new CancellationTokenSource();

Console.CancelKeyPress += (_, e) =>
{
    e.Cancel = true;
    Log("INFO", "Shutdown requested...");
    cts.Cancel();
};

AppDomain.CurrentDomain.ProcessExit += (_, _) =>
{
    cts.Cancel();
};

// Connect to telemetry service
using var telemetryClient = new TelemetryServiceClient(serviceUrl, adapterId);
_ = telemetryClient.ConnectAsync(cts.Token);

// Start SimConnect manager
using var simConnect = new SimConnectManager(appName, highHz, lowHz);

// Wire up state updates to telemetry service push
simConnect.StateUpdated += state => _ = telemetryClient.PushStateAsync(state);

simConnect.ConnectionChanged += connected =>
{
    Log("INFO", $"SimConnect connected: {connected}");
};

simConnect.FlightStateChanged += active =>
{
    Log("INFO", active
        ? "Flight is active — telemetry streaming"
        : "Flight ended — idling (telemetry paused)");
    // Send status heartbeat on flight state change to keep connection alive
    _ = telemetryClient.SendStatusAsync(active ? "connected" : "connected");
};

// Periodic heartbeat to keep telemetry service connection alive during sim pauses.
// The telemetry service has a stale adapter timeout — this prevents reaping.
var heartbeatTimer = new System.Threading.Timer(
    _ => _ = telemetryClient.SendStatusAsync("connected"),
    null,
    TimeSpan.FromSeconds(10),
    TimeSpan.FromSeconds(30));

// Connect with retry -- the ConnectWithRetryAsync loop now handles
// MSFS crashes/restarts automatically by re-entering the retry loop
// when the connection is lost.
try
{
    Log("INFO", $"Attempting SimConnect connection as \"{appName}\"...");
    await simConnect.ConnectWithRetryAsync(cts.Token);
}
catch (OperationCanceledException)
{
    // Expected on shutdown
}
catch (Exception ex)
{
    Log("ERROR", $"Fatal error: {ex.Message}");
    Log("ERROR", ex.StackTrace ?? "(no stack trace)");
}

Log("INFO", "Shutting down...");
simConnect.Disconnect();
Log("INFO", "Goodbye.");

// ---------------------------------------------------------------------------
//  Helpers
// ---------------------------------------------------------------------------

static void Log(string level, string message)
{
    var ts = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ");
    Console.WriteLine($"{ts} [{level}] MsfsAdapter: {message}");
}

static JsonElement LoadConfiguration()
{
    const string configPath = "appsettings.json";

    if (!File.Exists(configPath))
    {
        Log("WARN", $"{configPath} not found. Using defaults.");
        var defaults = """
        {
          "SimConnect": {
            "AppName": "MERLIN SimConnect Bridge",
            "HighFrequencyHz": 30,
            "LowFrequencyHz": 1
          },
          "TelemetryService": {
            "Url": "ws://localhost:8081/ws/ingest",
            "AdapterId": "msfs-adapter"
          }
        }
        """;
        return JsonDocument.Parse(defaults).RootElement;
    }

    var json = File.ReadAllText(configPath);
    return JsonDocument.Parse(json).RootElement;
}
