using System.Text.Json;
using SimConnectBridge;

// ---------------------------------------------------------------------------
//  MERLIN SimConnect Bridge — Entry Point
//  Connects to MSFS 2024 via SimConnect and broadcasts telemetry over WebSocket.
// ---------------------------------------------------------------------------

Console.WriteLine("=== MERLIN SimConnect Bridge ===");
Console.WriteLine();

// Load configuration
var config = LoadConfiguration();

string appName = config.GetProperty("SimConnect").GetProperty("AppName").GetString() ?? "MERLIN SimConnect Bridge";
int highHz = config.GetProperty("SimConnect").GetProperty("HighFrequencyHz").GetInt32();
int lowHz = config.GetProperty("SimConnect").GetProperty("LowFrequencyHz").GetInt32();
string wsHost = config.GetProperty("WebSocket").GetProperty("Host").GetString() ?? "0.0.0.0";
int wsPort = config.GetProperty("WebSocket").GetProperty("Port").GetInt32();

// Set up cancellation for graceful shutdown
using var cts = new CancellationTokenSource();

Console.CancelKeyPress += (_, e) =>
{
    e.Cancel = true;
    Console.WriteLine("\n[Bridge] Shutdown requested...");
    cts.Cancel();
};

AppDomain.CurrentDomain.ProcessExit += (_, _) =>
{
    cts.Cancel();
};

// Start WebSocket server
using var wsServer = new TelemetryWebSocketServer(wsHost, wsPort);
wsServer.Start();

// Start SimConnect manager
using var simConnect = new SimConnectManager(appName, highHz, lowHz);

// Wire up state updates to WebSocket broadcast
simConnect.StateUpdated += state => wsServer.BroadcastState(state);

simConnect.ConnectionChanged += connected =>
{
    Console.WriteLine($"[Bridge] SimConnect connected: {connected}");
};

// Connect with retry (blocks until connected or cancelled)
try
{
    Console.WriteLine($"[Bridge] Attempting SimConnect connection as \"{appName}\"...");
    await simConnect.ConnectWithRetryAsync(cts.Token);
    Console.WriteLine("[Bridge] SimConnect connected. Broadcasting telemetry.");
    Console.WriteLine("[Bridge] Press Ctrl+C to shut down.");
    Console.WriteLine();

    // Keep alive until cancellation
    await Task.Delay(Timeout.Infinite, cts.Token);
}
catch (OperationCanceledException)
{
    // Expected on shutdown
}
catch (Exception ex)
{
    Console.WriteLine($"[Bridge] Fatal error: {ex.Message}");
    Console.WriteLine(ex.StackTrace);
}

Console.WriteLine("[Bridge] Shutting down...");
simConnect.Disconnect();
wsServer.Stop();
Console.WriteLine("[Bridge] Goodbye.");

// ---------------------------------------------------------------------------
//  Configuration loader
// ---------------------------------------------------------------------------

static JsonElement LoadConfiguration()
{
    const string configPath = "appsettings.json";

    if (!File.Exists(configPath))
    {
        Console.WriteLine($"[Bridge] WARNING: {configPath} not found. Using defaults.");
        var defaults = """
        {
          "SimConnect": {
            "AppName": "MERLIN SimConnect Bridge",
            "HighFrequencyHz": 30,
            "LowFrequencyHz": 1
          },
          "WebSocket": {
            "Port": 8080,
            "Host": "0.0.0.0"
          }
        }
        """;
        return JsonDocument.Parse(defaults).RootElement;
    }

    var json = File.ReadAllText(configPath);
    return JsonDocument.Parse(json).RootElement;
}
