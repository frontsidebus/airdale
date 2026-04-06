# Testing MERLIN

This guide covers testing MERLIN without a running flight simulator, verifying the command pipeline, running the automated test suite, and using the health check script.

---

## Mock Adapter

The mock adapter (`tools/mock_adapter.py`) simulates the MSFS SimConnect bridge. It connects to the telemetry service, streams fake telemetry, and executes any commands it receives by updating its internal state. No MSFS, no .NET, no Windows required.

### Quick Start

The simplest way to run in mock mode is through the startup script:

```bash
./scripts/start.sh --mock
```

This starts all services (ChromaDB, telemetry service, mock adapter, web server) and displays a **MOCK MODE** banner when ready.

### Running the Mock Adapter Standalone

If you prefer to manage services individually, start the mock adapter directly:

```bash
python tools/mock_adapter.py
```

Prerequisites: the telemetry service must be running on `ws://localhost:8080/ws/ingest`.

### Command-Line Flags

```
python tools/mock_adapter.py --help
```

| Flag | Default | Description |
|---|---|---|
| `--url` | `ws://localhost:8080/ws/ingest` | Telemetry service ingest WebSocket URL |
| `--adapter-id` | `msfs-adapter` | Adapter ID to register as |
| `--aircraft` | `Cessna 172 Skyhawk` | Simulated aircraft name |
| `--altitude` | `3000.0` | Starting altitude MSL in feet |
| `--airspeed` | `110.0` | Starting indicated airspeed in knots |
| `--hz` | `2.0` | Telemetry update frequency in Hz |

Examples:

```bash
# Simulate a 747 at cruise
python tools/mock_adapter.py --aircraft "Boeing 747-8" --altitude 35000 --airspeed 250

# High-frequency telemetry updates for stress testing
python tools/mock_adapter.py --hz 10

# Custom telemetry service URL (e.g., remote host)
python tools/mock_adapter.py --url ws://192.168.1.50:8080/ws/ingest
```

### What the Mock Adapter Simulates

The mock adapter maintains a `MockAircraftState` that starts with realistic default values:

- **Position:** 40.6413N, -73.7781W (near JFK)
- **Altitude:** 3,000 ft MSL, 2,500 ft AGL
- **Airspeed:** 110 kt indicated
- **Heading:** 270 magnetic
- **Engine:** 2,300 RPM, 24.0 manifold pressure
- **Gear:** DOWN, Flaps: 0%

Telemetry values drift subtly over time (heading wobble, airspeed oscillation) to simulate a live flight. The altitude changes based on vertical speed, so the data looks realistic to the orchestrator's flight phase detector.

When commands arrive, the mock adapter applies them to its state. For example, a `GEAR_UP` command sets `gear_handle` to `False`, and the next telemetry frame reflects the change.

---

## Testing the Command Pipeline

The full command pipeline without MSFS is:

```
Voice/Text -> STT -> Claude -> set_aircraft_control tool -> telemetry service -> mock adapter
```

### Through the Web UI

1. Start in mock mode: `./scripts/start.sh --mock`
2. Open `http://localhost:3838`
3. Type or speak a command: "Lower the gear" or "Set heading to one eight zero"
4. Watch Claude call the `set_aircraft_control` tool in the chat response
5. Check the mock adapter log for the executed command:

```bash
tail -f logs/mock_adapter.log
```

### Controllable Systems

The `set_aircraft_control` tool supports 11 aircraft systems:

| System | Example Voice Commands | Actions |
|---|---|---|
| **flaps** | "Give me full flaps", "Flaps up", "Set flaps to 20" | up, full, 1, 2, 3, set, incr, decr |
| **gear** | "Gear down", "Retract the gear" | up, down, toggle |
| **autopilot** | "Engage autopilot", "Set heading to 270", "Set altitude 5000" | on, off, heading, heading_hold, altitude, altitude_hold, vertical_speed, vs_hold, speed, speed_hold, nav, approach |
| **throttle** | "Set throttle to 75 percent" | set (0-100%) |
| **radio** | "Tune COM1 to 121.5" | com1, com2, nav1, nav2 |
| **barometer** | "Set altimeter to 29.92" | set |
| **trim** | "Set trim to nose up" | set |
| **parking_brake** | "Set the parking brake" | toggle |
| **spoilers** | "Deploy spoilers", "Spoilers to 50 percent" | toggle, set |
| **mixture** | "Set mixture to full rich" | set (0-100%) |
| **propeller** | "Set prop to 2500 RPM" | set (0-100%) |

### How Confirmations Work

When Claude executes a command, it responds with a brief, aviation-style confirmation. The tool description instructs Claude to confirm without unnecessary verbosity:

- "Gear down" -> Claude executes `set_aircraft_control(system="gear", action="down")` -> "Gear down, three green."
- "Give me full flaps" -> Claude executes `set_aircraft_control(system="flaps", action="full")` -> "Flaps full."
- "Set heading to 270" -> Claude executes `set_aircraft_control(system="autopilot", action="heading", value=270)` -> "Heading bug two seven zero."

### Direct Command Testing via WebSocket

You can send a command directly to the telemetry service without going through Claude, using a Python one-liner. This is useful for verifying the telemetry service to adapter pipeline in isolation.

```bash
python3 -c "
import asyncio, json, websockets
async def send():
    async with websockets.connect('ws://localhost:8080/ws/telemetry') as ws:
        cmd = {
            'type': 'command',
            'command': 'GEAR_DOWN',
            'value': 0
        }
        await ws.send(json.dumps(cmd))
        print('Sent:', json.dumps(cmd))
        ack = await asyncio.wait_for(ws.recv(), timeout=5.0)
        print('Ack:', ack)
asyncio.run(send())
"
```

If the mock adapter is running, you will see the command logged in `logs/mock_adapter.log` and receive an acknowledgment JSON message with `"success": true`.

### Verifying Commands in the Mock Adapter Log

The mock adapter prints every received command with a colored prefix:

```
  >>> COMMAND RECEIVED: Gear DOWN  (id: a3b2c1d4)
  >>> COMMAND RECEIVED: Flaps FULL (100%)  (id: e5f6a7b8)
  >>> COMMAND RECEIVED: HDG Bug -> 270  (id: c9d0e1f2)
  >>> COMMAND RECEIVED: AP Master -> ON  (id: 34a5b6c7)
```

Each entry includes the human-readable description and the first 8 characters of the command ID. Commands also update the mock state, so the next telemetry frame will reflect the change (e.g., after `GEAR_DOWN`, telemetry reports `gear_handle: true`).

The full command history is stored in `MockAircraftState.command_log` as a list of dictionaries with `time`, `command`, `value`, and `description` fields.

---

## Running the Test Suite

### Python Tests (Orchestrator)

The orchestrator has a comprehensive test suite using pytest and pytest-asyncio.

```bash
cd orchestrator
python3 -m pytest tests/ -v
```

Key test categories:

- **Unit tests:** config, flight phase state machine, tools, Claude client, Whisper client, context store, TTS preprocessor, screen capture
- **Integration tests:** WebSocket reconnection, health monitor, delta detection, query classification, orchestrator end-to-end, tool chain, Whisper pipeline

Run a specific test file:

```bash
python3 -m pytest tests/test_tools.py -v
```

Run tests matching a keyword:

```bash
python3 -m pytest tests/ -v -k "flight_phase"
```

### C# Tests (MSFS Adapter)

The SimConnect bridge has xUnit tests. Run from Windows or from WSL using the Windows dotnet:

```bash
cd adapters/msfs
dotnet test
```

### Telemetry Service Tests

```bash
cd telemetry-service
python3 -m pytest tests/ -v
```

---

## Health Check

The health check script verifies all subsystems are operational. It checks API keys, service connectivity, the test suite, and v2 module imports.

```bash
./scripts/healthcheck.sh
```

Sample output:

```
MERLIN v2 Health Check
===================================================

API Keys:
  PASS  Anthropic API key
  PASS  Deepgram API key
  PASS  Cartesia API key

Services:
  PASS  Web server (port 3838)
  PASS  ChromaDB (port 8000)
  PASS  Telemetry service (port 8080)

Test Suite:
  PASS  Python tests (247 passed)

v2 Modules:
  PASS  Deepgram STT client
  PASS  Cartesia TTS client
  PASS  Emergency detector
  PASS  Response validator
  PASS  Aviation chunker
  PASS  Cross-encoder reranker
  PASS  Aviation tools

===================================================
  13 passed  0 failed  0 warnings  (13 total)
===================================================
```

The script exits with code 0 if all required checks pass, or code 1 if any required check fails. Use it as an acceptance test after deployment or configuration changes.

### What It Checks

| Category | Checks |
|---|---|
| API Keys | ANTHROPIC_API_KEY, DEEPGRAM_API_KEY (if STT=deepgram), CARTESIA_API_KEY (if TTS=cartesia) |
| Services | Web server (3838), ChromaDB (8000), Telemetry service (8080), Whisper (9090, if STT=whisper) |
| Test Suite | Runs `pytest tests/ -q` in the orchestrator directory |
| v2 Modules | Import checks for Deepgram, Cartesia, emergency detector, validator, chunker, reranker, aviation tools |
