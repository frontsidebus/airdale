# Architecture

**Analysis Date:** 2026-03-26

## Pattern Overview

**Overall:** Event-driven microservices with pluggable adapter pattern

**Key Characteristics:**
- Sim adapters are out-of-process executables that push telemetry via WebSocket to a central hub
- A universal telemetry service decouples sim-specific code from the orchestrator brain
- All IPC is WebSocket + JSON, making components language-agnostic and independently deployable
- The orchestrator coordinates AI inference, voice I/O, RAG retrieval, and flight phase detection
- Graceful degradation: subsystems (ChromaDB, Whisper, telemetry) can be unavailable without crashing

## Components

### 1. MSFS Adapter (C# / .NET 8)
- **Purpose:** Connects to MSFS 2024 via SimConnect SDK and pushes telemetry to the telemetry service
- **Location:** `adapters/msfs/`
- **Entry point:** `adapters/msfs/Program.cs` (top-level statements)
- **Key files:**
  - `adapters/msfs/SimConnectManager.cs` -- Event-driven SimConnect message pump using `EventWaitHandle`
  - `adapters/msfs/TelemetryServiceClient.cs` -- WebSocket client that pushes JSON to `/ws/ingest`
  - `adapters/msfs/Models/SimDataStructs.cs` -- SimConnect data structure definitions
  - `adapters/msfs/Models/SimState.cs` -- Internal telemetry data model
  - `adapters/msfs/appsettings.json` -- Configuration (SimConnect app name, frequency, service URL)
- **Communicates with:** Telemetry Service via WebSocket (`/ws/ingest`)
- **Protocol:** Sends `register` on connect, then streams `telemetry` and `status` messages
- **Runs on:** Windows host (native .exe, requires SimConnect SDK)

### 2. Telemetry Service (Python / FastAPI)
- **Purpose:** Universal telemetry hub that receives from adapters and broadcasts to consumers
- **Location:** `telemetry-service/telemetry/`
- **Entry point:** `telemetry-service/telemetry/service.py` (FastAPI app)
- **Key files:**
  - `telemetry-service/telemetry/service.py` -- FastAPI app with `/ws/ingest` and `/ws/telemetry` endpoints
  - `telemetry-service/telemetry/adapter_manager.py` -- `AdapterManager` tracks connections, broadcasts to consumers
  - `telemetry-service/telemetry/adapter_protocol.py` -- Pydantic message types for adapter/consumer protocol
  - `telemetry-service/telemetry/schema.py` -- `TelemetryEnvelope` universal data model with vehicle extensions
  - `telemetry-service/telemetry/config.py` -- `TelemetryServiceSettings` via pydantic-settings
- **Two WebSocket endpoints:**
  - `/ws/ingest` -- Adapters connect here, register, and stream telemetry
  - `/ws/telemetry` -- Consumers (orchestrator, web UI) subscribe here to receive broadcasts
- **REST endpoints:** `/api/health`, `/api/adapters`
- **Runs in:** Docker container (port 8080 for consumers, 8081 for adapter ingest)

### 3. Orchestrator (Python)
- **Purpose:** The brain -- coordinates Claude AI, voice pipeline, telemetry, RAG, and flight phase detection
- **Location:** `orchestrator/orchestrator/`
- **Entry point:** `orchestrator/orchestrator/main.py` -- `Orchestrator` class and `run()` CLI entry
- **Console script:** `merlin` (defined in `orchestrator/pyproject.toml`)
- **Key files:**
  - `orchestrator/orchestrator/main.py` -- Top-level `Orchestrator` wiring all subsystems, conversation loop
  - `orchestrator/orchestrator/claude_client.py` -- `ClaudeClient` with MERLIN persona, tool use loop, streaming, prompt caching
  - `orchestrator/orchestrator/sim_client.py` -- `TelemetryClient` WebSocket consumer with auto-reconnect, delta detection, `SimState` Pydantic models
  - `orchestrator/orchestrator/tools.py` -- Tool implementations: `get_sim_state`, `lookup_airport`, `search_manual`, `get_checklist`, `create_flight_plan`
  - `orchestrator/orchestrator/flight_phase.py` -- `FlightPhaseDetector` state machine with hysteresis
  - `orchestrator/orchestrator/context_store.py` -- `ContextStore` ChromaDB RAG with TTL query cache
  - `orchestrator/orchestrator/voice.py` -- `VoiceInput` (PTT/VAD + Whisper), `VoiceOutput` (ElevenLabs streaming)
  - `orchestrator/orchestrator/audio_processing.py` -- High-pass filter, silence trim, normalization, Silero VAD
  - `orchestrator/orchestrator/tts_preprocessor.py` -- ICAO-compliant aviation text preprocessing for TTS
  - `orchestrator/orchestrator/whisper_client.py` -- Whisper ASR HTTP client with retry logic
  - `orchestrator/orchestrator/screen_capture.py` -- Optional screen capture for Claude vision
  - `orchestrator/orchestrator/config.py` -- `Settings` via pydantic-settings, all env vars
  - `orchestrator/orchestrator/tts/` -- TTS client abstraction layer (protocol + ElevenLabs + Kokoro backends)
- **Depends on:** Telemetry Service, ChromaDB, Whisper, Anthropic Claude API, ElevenLabs API

### 4. Web Server (Python / FastAPI)
- **Purpose:** Browser-facing backend that proxies telemetry, chat, STT, and TTS to the frontend
- **Location:** `web/`
- **Entry point:** `web/run.py` (launches uvicorn), main app in `web/server.py`
- **Key files:**
  - `web/server.py` -- FastAPI app with REST + WebSocket endpoints, barge-in support, TTS phrase caching
  - `web/static/index.html` -- TARS-style cockpit display UI
  - `web/static/app.js` -- Browser WebSocket client, audio capture, UI logic
  - `web/static/style.css` -- Frontend styling
- **Endpoints:**
  - `GET /` -- Serves the frontend SPA
  - `GET /api/status` -- Health status of all subsystems
  - `POST /api/transcribe` -- Whisper STT proxy (webm/wav upload)
  - `POST /api/tts` -- ElevenLabs TTS proxy with phrase caching
  - `WS /ws/telemetry` -- Proxies telemetry service broadcasts to browser
  - `WS /ws/chat` -- Streams Claude responses to browser with barge-in support
- **Imports orchestrator package directly** (not a separate service -- shares Python environment)
- **Runs on:** Port 3838

### 5. TTS Service (Python / FastAPI) -- Local Alternative
- **Purpose:** Local Kokoro TTS inference server as alternative to ElevenLabs cloud
- **Location:** `services/tts/`
- **Entry point:** `services/tts/server.py`
- **Endpoints:** `POST /tts`, `POST /tts/cache`, `GET /voices`, `GET /health`
- **Status:** New/in development (not yet in docker-compose.yml)

### 6. Data & Prompts
- **Location:** `data/`
- **Key files:**
  - `data/prompts/merlin_system.md` -- Full MERLIN persona definition (loaded by ClaudeClient)
  - `data/prompts/merlin_emergency.md` -- Emergency procedure prompt overlay
  - `data/checklists/generic_single_engine.yaml` -- Generic single-engine checklist
  - `data/checklists/generic_jet.yaml` -- Generic jet checklist
  - `data/chroma_db/` -- Persistent ChromaDB vector store data

## Data Flow

### Primary Telemetry Pipeline

```
MSFS 2024 (SimConnect SDK)
    |
    v  [EventWaitHandle message pump]
MSFS Adapter (C# .exe on Windows)
    |
    v  [WebSocket JSON: register -> telemetry/status stream]
Telemetry Service (/ws/ingest)
    |
    v  [AdapterManager broadcasts to consumers]
Telemetry Service (/ws/telemetry)
    |
    +---> Orchestrator (TelemetryClient with delta detection)
    |         |
    |         v  [FlightPhaseDetector state machine]
    |         SimState + FlightPhase enrichment
    |
    +---> Web Server (proxies to browser WebSocket)
              |
              v
          Browser UI (cockpit display)
```

### Conversation Pipeline (CLI Mode)

```
User Input (text or voice)
    |
    v  [If voice: audio -> Whisper STT -> text]
Orchestrator._conversation_loop()
    |
    v  [Get current SimState + detect flight phase]
    v  [Query ChromaDB for relevant context]
    v  [Optional: grab screen capture for vision]
    |
ClaudeClient.chat() [streaming]
    |
    +---> Build system prompt: MERLIN persona (cached) + dynamic flight context
    +---> Classify query -> set token budget (short/normal/briefing)
    +---> Stream response, handle tool use loops internally
    |         |
    |         v  [Tool calls: get_sim_state, lookup_airport, search_manual, get_checklist, create_flight_plan]
    |
    v  [Yield text chunks as they arrive]
Print response + optional TTS playback (fire-and-forget async task)
```

### Conversation Pipeline (Web Mode)

```
Browser (audio capture / text input)
    |
    v  [POST /api/transcribe or WS /ws/chat]
Web Server
    |
    +---> STT: forwards to Whisper Docker service
    +---> Chat: ClaudeClient.chat() streaming via WebSocket
    +---> TTS: ElevenLabs API proxy with phrase cache
    |
    v  [WebSocket frames: text chunks, audio, status]
Browser (renders text, plays audio)
```

### Tool Execution Flow

```
ClaudeClient receives tool_use stop_reason
    |
    v
_execute_tool() dispatches by name:
    |
    +-- get_sim_state     -> TelemetryClient.get_state() -> formatted dict
    +-- lookup_airport    -> httpx GET to aviationapi.com -> airport info
    +-- search_manual     -> ContextStore.query() -> ChromaDB vector search
    +-- get_checklist     -> ContextStore.query() or DEFAULT_CHECKLISTS fallback
    +-- create_flight_plan -> lookup both airports + build route structure
    |
    v
Results JSON injected as tool_result -> Claude continues generating
```

### State Management

- **SimState:** Pydantic `BaseModel` in `orchestrator/orchestrator/sim_client.py`. Continuously updated from telemetry WebSocket broadcasts. Delta detection skips processing when JSON is identical.
- **FlightPhase:** Enum (`PREFLIGHT` through `LANDED`) derived from SimState by `FlightPhaseDetector`. State machine with hysteresis (3 consecutive detections before transition).
- **Conversation History:** Maintained as a list of message dicts in `ClaudeClient._conversation`. Trimmed to `max_history * 2` entries.
- **RAG Cache:** `_QueryCache` in `ContextStore` with 60s TTL, keyed by (query, n_results, filters). Invalidated on flight phase change.

## Key Patterns

### Pluggable Adapter Architecture
New sims require only a new adapter that connects to `/ws/ingest` and sends the standard protocol messages (`register`, `telemetry`, `status`). The adapter can be written in any language. See `adapters/README.md`.

### Event-Driven SimConnect Message Pump
The MSFS adapter uses `EventWaitHandle` instead of timer-based polling. SimConnect signals when data is ready. This eliminates COM threading errors (`0x80004005`). Implemented in `adapters/msfs/SimConnectManager.cs`.

### Universal Telemetry Envelope
`telemetry-service/telemetry/schema.py` defines `TelemetryEnvelope` with core fields (position, attitude, speeds, environment) universal across vehicle types. Vehicle-specific data goes in `extensions` dict. The `to_legacy_simstate()` method provides backward compatibility.

### Dynamic Token Budgeting
`orchestrator/orchestrator/claude_client.py` classifies queries as `short` (256 tokens), `normal` (1024), or `briefing` (2048) using regex patterns. This keeps cockpit comms tactical during high-workload phases.

### Flight-Phase-Aware Response Style
Each `FlightPhase` has a style directive injected into the system prompt. `TAKEOFF` and `APPROACH` demand ultra-brief callouts. `PREFLIGHT` and `CRUISE` allow banter. Defined in `_PHASE_STYLE` dict in `orchestrator/orchestrator/claude_client.py`.

### Graceful Degradation
The `Orchestrator` in `orchestrator/orchestrator/main.py` uses `HealthMonitor` to track subsystem health. If ChromaDB is down, RAG returns empty. If Whisper is down, voice falls back to text. If telemetry service is down, runs in text-only mode.

### Auto-Reconnection with Exponential Backoff
`TelemetryClient` in `orchestrator/orchestrator/sim_client.py` implements automatic reconnection with configurable base delay (1s), max delay (30s), and backoff factor (2x). Heartbeat loop detects stale connections via ping/pong.

### Prompt Caching
The static MERLIN persona block in the system prompt is marked with `cache_control: {"type": "ephemeral"}` in `orchestrator/orchestrator/claude_client.py`. This reduces time-to-first-token and API cost since the persona never changes.

### TTS Client Abstraction
`orchestrator/orchestrator/tts/base.py` defines a `TTSClient` Protocol with `synthesize()` and `synthesize_stream()`. Factory in `orchestrator/orchestrator/tts/__init__.py` selects between ElevenLabs (cloud) and Kokoro (local) based on `settings.tts_backend`.

## Boundaries & Interfaces

### Adapter <-> Telemetry Service Protocol
- **Transport:** WebSocket JSON
- **Endpoint:** `/ws/ingest`
- **Messages (Adapter -> Service):** `register`, `telemetry`, `status`
- **Messages (Service -> Adapter):** `register_ack`, `error`
- **Defined in:** `telemetry-service/telemetry/adapter_protocol.py`

### Consumer <-> Telemetry Service Protocol
- **Transport:** WebSocket JSON
- **Endpoint:** `/ws/telemetry`
- **Messages (Consumer -> Service):** `subscribe`, `get_state`, `heartbeat`
- **Messages (Service -> Consumer):** `subscribe_ack`, `heartbeat_ack`, `state_response`, and raw telemetry broadcasts
- **Broadcast format:** Legacy SimState JSON (flat dict with `position`, `attitude`, `speeds`, etc.) plus envelope metadata (`adapter_id`, `sim_name`, `vehicle_type`)
- **Defined in:** `telemetry-service/telemetry/adapter_protocol.py`

### Orchestrator <-> Claude API
- **Client:** `anthropic.AsyncAnthropic` in `orchestrator/orchestrator/claude_client.py`
- **Model:** Configurable via `CLAUDE_MODEL` env var (default: `claude-sonnet-4-20250514`)
- **Features:** Streaming, tool use, prompt caching, stop sequences
- **Tools:** 5 defined in `TOOL_DEFINITIONS` list in `claude_client.py`

### Web Server <-> Browser
- **REST:** `/api/status`, `/api/transcribe`, `/api/tts`
- **WebSocket:** `/ws/telemetry` (telemetry proxy), `/ws/chat` (Claude streaming)
- **Frontend:** Static HTML/JS/CSS served from `web/static/`

### Orchestrator <-> Whisper
- **Transport:** HTTP POST multipart
- **Endpoint:** `{WHISPER_URL}/v1/audio/transcriptions` (OpenAI-compatible)
- **Client:** `orchestrator/orchestrator/whisper_client.py`

### Orchestrator <-> ChromaDB
- **Transport:** HTTP (ChromaDB client library)
- **Client:** `orchestrator/orchestrator/context_store.py`
- **Collections:** Managed by `tools/ingest.py`

## Deployment Model

### Docker Compose (Production)
Defined in `docker-compose.yml`. Four services on the `merlin` bridge network:

| Service | Container | Port(s) | Image/Build |
|---------|-----------|---------|-------------|
| Whisper | merlin-whisper | 9090 | `fedirz/faster-whisper-server:latest-cpu` |
| ChromaDB | merlin-chromadb | 8000 | `chromadb/chroma:latest` |
| Telemetry Service | merlin-telemetry | 8080, 8081 | Built from `telemetry-service/Dockerfile` |
| Orchestrator | merlin-orchestrator | 3838 | Built from `orchestrator/Dockerfile` |

**Dependency chain:** Orchestrator depends on Whisper, ChromaDB, and Telemetry Service (all must be healthy).

### Native (Windows Host)
- MSFS Adapter runs as a native .exe on the Windows host (`dotnet run` in `adapters/msfs/`)
- Pushes telemetry to the Telemetry Service at `ws://localhost:8081/ws/ingest`

### Development Mode
`docker-compose.dev.yml` overrides:
- Whisper uses `tiny` model for faster startup
- Source code bind-mounted for hot-reload
- Debug logging enabled

### Startup Scripts
- `scripts/start.sh` -- Launches the full stack
- `scripts/stop.sh` -- Stops all services
- `scripts/merlin.bat` -- Windows launcher

## Error Handling

**Strategy:** Fail gracefully, degrade instead of crash.

**Patterns:**
- `HealthMonitor` in `orchestrator/orchestrator/sim_client.py` tracks subsystem health with last-seen timestamps
- WebSocket reconnection with exponential backoff in `TelemetryClient`
- Tool execution errors caught and returned as `{"error": ...}` to Claude (it interprets and reports to user)
- TTS failures are logged but non-fatal (fire-and-forget tasks with `_on_tts_done` callback)
- Whisper failures trigger automatic fallback to text-only input mode
- Stale adapter cleanup runs every 5s in telemetry service background task

---

*Architecture analysis: 2026-03-26*
