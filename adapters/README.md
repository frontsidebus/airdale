# Sim Adapters

Each adapter is a small standalone app that connects to a specific game's SDK/API
and pushes telemetry to the universal **telemetry service**.

## Architecture

```
Game SDK (SimConnect, X-Plane UDP, DCS Export.lua, etc.)
  │
  ▼
Per-Sim Adapter (standalone exe/app)
  │  WebSocket client → ws://telemetry-service:8081/ws/ingest
  ▼
Telemetry Service (Python/FastAPI)
  │  WebSocket server → ws://telemetry-service:8080/ws/telemetry
  ▼
Consumers (orchestrator, web UI, future apps)
```

## Available Adapters

| Adapter | Directory | Game | Language |
|---------|-----------|------|----------|
| MSFS 2024 | `msfs/` | Microsoft Flight Simulator 2024 | C# (.NET 8) |

## Writing a New Adapter

An adapter is any app that:

1. **Connects** to `ws://<telemetry-service>/ws/ingest` as a WebSocket client
2. **Registers** by sending a `register` message
3. **Streams** telemetry as `TelemetryEnvelope` frames

### Step 1: Register

On connect, send:

```json
{
  "type": "register",
  "adapter_id": "your-adapter-id",
  "sim_name": "your-sim-name",
  "vehicle_type": "aircraft",
  "version": "1.0"
}
```

The service responds with:

```json
{
  "type": "register_ack",
  "adapter_id": "your-adapter-id",
  "accepted": true
}
```

### Step 2: Stream Telemetry

For each frame, send:

```json
{
  "type": "telemetry",
  "data": {
    "adapter_id": "your-adapter-id",
    "sim_name": "your-sim-name",
    "vehicle_type": "aircraft",
    "timestamp": "2026-01-01T00:00:00Z",
    "connected": true,
    "vehicle_name": "Cessna 172",
    "position": {
      "latitude": 47.45,
      "longitude": -122.31,
      "altitude_msl": 5500.0,
      "altitude_agl": 4200.0
    },
    "attitude": {
      "pitch": -2.5,
      "bank": 5.0,
      "heading_true": 270.0,
      "heading_magnetic": 268.0
    },
    "speeds": {
      "indicated_airspeed": 120.0,
      "true_airspeed": 125.0,
      "ground_speed": 130.0,
      "mach": 0.18,
      "vertical_speed": -200.0
    },
    "environment": {
      "wind_speed_kts": 10.0,
      "wind_direction": 180.0,
      "visibility_sm": 10.0,
      "temperature_c": 15.0,
      "barometer_inhg": 29.92
    },
    "extensions": {
      "aircraft": {
        "engines": { "engine_count": 1, "engines": [{"rpm": 2400, ...}] },
        "autopilot": { "master": false, "heading": 270.0, ... },
        "radios": { "com1": 124.0, "com2": 121.5, ... },
        "fuel": { "total_gallons": 40.0, "total_weight_lbs": 240.0 },
        "surfaces": { "gear_handle": true, "flaps_percent": 0.0, ... }
      }
    }
  }
}
```

### Core Fields (All Vehicle Types)

| Field | Description |
|-------|-------------|
| `position` | Latitude, longitude, altitude MSL/AGL |
| `attitude` | Pitch, bank, heading (true/magnetic) |
| `speeds` | IAS, TAS, ground speed, mach, vertical speed |
| `environment` | Wind, visibility, temperature, barometer |

### Vehicle-Specific Extensions

Put vehicle-type-specific data in `extensions.<vehicle_type>`:

- **Aircraft**: `extensions.aircraft` — engines, autopilot, radios, fuel, surfaces
- **Car** (future): `extensions.car` — tire temps, lap data, gear position
- **Boat** (future): `extensions.boat` — rudder, sail trim, depth

### Tips

- Send telemetry at whatever rate makes sense for your sim (30 Hz for position, 1 Hz for systems)
- Handle reconnection with exponential backoff if the service goes down
- Set `connected: false` when the sim disconnects but the adapter is still running
- Use `adapter_id` to uniquely identify your adapter instance
