using System.Collections.Concurrent;
using System.Text.Json;
using System.Text.Json.Serialization;
using Fleck;
using SimConnectBridge.Models;

namespace SimConnectBridge;

/// <summary>
/// Fleck-based WebSocket server that broadcasts sim state to connected clients
/// and handles incoming request messages.
/// </summary>
public sealed class TelemetryWebSocketServer : IDisposable
{
    private readonly WebSocketServer _server;
    private readonly ConcurrentDictionary<Guid, ClientConnection> _clients = new();
    private readonly JsonSerializerOptions _jsonOptions;
    private bool _disposed;

    /// <summary>
    /// Creates the WebSocket server bound to the given host and port.
    /// </summary>
    /// <param name="host">Bind address (e.g., "0.0.0.0").</param>
    /// <param name="port">Port number (e.g., 8080).</param>
    public TelemetryWebSocketServer(string host, int port)
    {
        _server = new WebSocketServer($"ws://{host}:{port}");

        _jsonOptions = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            WriteIndented = false
        };
    }

    /// <summary>
    /// Starts listening for WebSocket connections.
    /// </summary>
    public void Start()
    {
        _server.Start(socket =>
        {
            socket.OnOpen = () => OnClientOpen(socket);
            socket.OnClose = () => OnClientClose(socket);
            socket.OnMessage = message => OnClientMessage(socket, message);
            socket.OnError = ex => OnClientError(socket, ex);
        });

        Console.WriteLine($"[WebSocket] Server started on {_server.Location}");
    }

    /// <summary>
    /// Broadcasts the current sim state to all connected clients.
    /// Respects per-client field subscriptions.
    /// </summary>
    /// <param name="state">The current simulation state.</param>
    public void BroadcastState(SimState state)
    {
        if (_clients.IsEmpty) return;

        // Pre-serialize the full state once for clients with no filter
        string? fullJson = null;

        foreach (var (_, client) in _clients)
        {
            try
            {
                string json;
                if (client.SubscribedFields is null || client.SubscribedFields.Count == 0)
                {
                    fullJson ??= JsonSerializer.Serialize(state, _jsonOptions);
                    json = fullJson;
                }
                else
                {
                    json = SerializeFilteredState(state, client.SubscribedFields);
                }

                client.Socket.Send(json);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[WebSocket] Error sending to client {client.Id}: {ex.Message}");
            }
        }
    }

    /// <summary>
    /// Stops the WebSocket server and disconnects all clients.
    /// </summary>
    public void Stop()
    {
        foreach (var (_, client) in _clients)
        {
            try { client.Socket.Close(); }
            catch { /* best-effort */ }
        }
        _clients.Clear();
        _server.Dispose();
        Console.WriteLine("[WebSocket] Server stopped.");
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        Stop();
    }

    // -----------------------------------------------------------------------
    //  Connection handlers
    // -----------------------------------------------------------------------

    private void OnClientOpen(IWebSocketConnection socket)
    {
        var client = new ClientConnection(socket);
        _clients[client.Id] = client;
        Console.WriteLine($"[WebSocket] Client connected: {client.Id} ({socket.ConnectionInfo.ClientIpAddress})");
    }

    private void OnClientClose(IWebSocketConnection socket)
    {
        var id = GetClientId(socket);
        if (id is not null && _clients.TryRemove(id.Value, out _))
        {
            Console.WriteLine($"[WebSocket] Client disconnected: {id}");
        }
    }

    private void OnClientMessage(IWebSocketConnection socket, string message)
    {
        try
        {
            var request = JsonSerializer.Deserialize<ClientRequest>(message, _jsonOptions);
            if (request is null) return;

            var clientId = GetClientId(socket);
            if (clientId is null) return;

            switch (request.Type)
            {
                case "get_state":
                    HandleGetState(socket);
                    break;

                case "subscribe":
                    HandleSubscribe(clientId.Value, request.Fields);
                    break;

                default:
                    var errorResponse = JsonSerializer.Serialize(new
                    {
                        type = "error",
                        message = $"Unknown request type: {request.Type}"
                    }, _jsonOptions);
                    socket.Send(errorResponse);
                    break;
            }
        }
        catch (JsonException ex)
        {
            Console.WriteLine($"[WebSocket] Invalid JSON from client: {ex.Message}");
            var errorResponse = JsonSerializer.Serialize(new
            {
                type = "error",
                message = "Invalid JSON"
            }, _jsonOptions);
            socket.Send(errorResponse);
        }
    }

    private void OnClientError(IWebSocketConnection socket, Exception ex)
    {
        Console.WriteLine($"[WebSocket] Client error: {ex.Message}");
    }

    // -----------------------------------------------------------------------
    //  Request handlers
    // -----------------------------------------------------------------------

    private void HandleGetState(IWebSocketConnection socket)
    {
        // The caller can obtain the current state from SimConnectManager.
        // We send a response indicating the request was received;
        // the next broadcast will deliver the full state.
        // For an immediate response, the BroadcastState path handles it.
        var response = new { type = "state_response", message = "Full state will be delivered on next update cycle." };
        socket.Send(JsonSerializer.Serialize(response, _jsonOptions));
    }

    private void HandleSubscribe(Guid clientId, List<string>? fields)
    {
        if (_clients.TryGetValue(clientId, out var client))
        {
            client.SubscribedFields = fields;
            Console.WriteLine($"[WebSocket] Client {clientId} subscribed to: {(fields is null ? "all" : string.Join(", ", fields))}");

            var ack = new { type = "subscribe_ack", fields = fields ?? new List<string> { "all" } };
            client.Socket.Send(JsonSerializer.Serialize(ack, _jsonOptions));
        }
    }

    // -----------------------------------------------------------------------
    //  Helpers
    // -----------------------------------------------------------------------

    private Guid? GetClientId(IWebSocketConnection socket)
    {
        foreach (var (id, client) in _clients)
        {
            if (client.Socket == socket) return id;
        }
        return null;
    }

    /// <summary>
    /// Serializes only the requested top-level fields of the sim state.
    /// </summary>
    private string SerializeFilteredState(SimState state, List<string> fields)
    {
        var dict = new Dictionary<string, object?>
        {
            ["timestamp"] = state.Timestamp,
            ["connected"] = state.Connected
        };

        foreach (var field in fields)
        {
            switch (field.ToLowerInvariant())
            {
                case "position": dict["position"] = state.Position; break;
                case "attitude": dict["attitude"] = state.Attitude; break;
                case "speeds": dict["speeds"] = state.Speeds; break;
                case "engines": dict["engines"] = state.Engines; break;
                case "autopilot": dict["autopilot"] = state.Autopilot; break;
                case "radios": dict["radios"] = state.Radios; break;
                case "fuel": dict["fuel"] = state.Fuel; break;
                case "surfaces": dict["surfaces"] = state.Surfaces; break;
                case "environment": dict["environment"] = state.Environment; break;
                case "aircraft": dict["aircraft"] = state.Aircraft; break;
            }
        }

        return JsonSerializer.Serialize(dict, _jsonOptions);
    }

    // -----------------------------------------------------------------------
    //  Inner types
    // -----------------------------------------------------------------------

    /// <summary>
    /// Tracks a single WebSocket client connection and its subscription preferences.
    /// </summary>
    private sealed class ClientConnection
    {
        public Guid Id { get; } = Guid.NewGuid();
        public IWebSocketConnection Socket { get; }
        public List<string>? SubscribedFields { get; set; }

        public ClientConnection(IWebSocketConnection socket)
        {
            Socket = socket;
        }
    }

    /// <summary>
    /// Deserialized client request message.
    /// </summary>
    private sealed class ClientRequest
    {
        [JsonPropertyName("type")]
        public string Type { get; set; } = string.Empty;

        [JsonPropertyName("fields")]
        public List<string>? Fields { get; set; }
    }
}
