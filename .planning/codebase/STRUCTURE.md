# Project Structure

**Analysis Date:** 2026-03-26

## Directory Layout

```
airdale/
├── adapters/                    # Per-sim adapter applications
│   ├── msfs/                    # MSFS 2024 adapter (C# .NET 8)
│   │   ├── Models/              # Data models for SimConnect
│   │   │   ├── SimDataStructs.cs    # SimConnect struct definitions
│   │   │   └── SimState.cs          # Internal telemetry model
│   │   ├── SimConnectBridge.Tests/  # xUnit test project
│   │   ├── Program.cs               # Entry point (top-level statements)
│   │   ├── SimConnectManager.cs     # Event-driven SimConnect message pump
│   │   ├── TelemetryServiceClient.cs # WS client pushing to telemetry service
│   │   ├── SimConnectBridge.csproj   # .NET project file
│   │   └── appsettings.json          # Adapter configuration
│   └── README.md                # How to write a new adapter
├── orchestrator/                # Python package -- MERLIN's brain
│   ├── orchestrator/            # Source package
│   │   ├── __init__.py
│   │   ├── audio_processing.py  # Audio preprocessing (high-pass, trim, normalize, Silero VAD)
│   │   ├── claude_client.py     # Claude API wrapper with MERLIN persona + tool use
│   │   ├── config.py            # Pydantic settings from .env
│   │   ├── context_store.py     # ChromaDB RAG store with query cache
│   │   ├── flight_phase.py      # State-machine flight phase detector
│   │   ├── llm/                 # LLM abstraction (currently empty/placeholder)
│   │   ├── main.py              # CLI entry point, Orchestrator class
│   │   ├── screen_capture.py    # Optional screen capture for vision
│   │   ├── sim_client.py        # Telemetry client, SimState models, HealthMonitor
│   │   ├── tools.py             # Claude tool implementations
│   │   ├── tts/                 # TTS client abstraction layer
│   │   │   ├── __init__.py      # Factory: create_tts_client()
│   │   │   ├── base.py          # TTSClient Protocol definition
│   │   │   ├── elevenlabs.py    # ElevenLabs cloud TTS client
│   │   │   └── kokoro.py        # Kokoro local TTS client
│   │   ├── tts_preprocessor.py  # ICAO-compliant aviation text preprocessing
│   │   ├── voice.py             # Voice I/O (PTT, VAD, streaming TTS)
│   │   └── whisper_client.py    # Whisper ASR HTTP client with retry
│   ├── tests/                   # Unit tests (pytest + pytest-asyncio)
│   │   ├── conftest.py          # Shared fixtures (mock settings, sim states, etc.)
│   │   ├── test_claude_client.py
│   │   ├── test_config.py
│   │   ├── test_context_store.py
│   │   ├── test_flight_phase.py
│   │   ├── test_screen_capture.py
│   │   ├── test_sim_client.py
│   │   ├── test_tools.py
│   │   ├── test_tts_client.py
│   │   ├── test_tts_preprocessor.py
│   │   └── test_whisper_client.py
│   ├── Dockerfile
│   └── pyproject.toml           # Build config (hatch), deps, ruff, pytest settings
├── telemetry-service/           # Universal telemetry hub
│   ├── telemetry/               # Python package
│   │   ├── __init__.py
│   │   ├── adapter_manager.py   # AdapterManager: tracking + consumer broadcast
│   │   ├── adapter_protocol.py  # Adapter/consumer message types (Pydantic)
│   │   ├── config.py            # TelemetryServiceSettings
│   │   ├── schema.py            # TelemetryEnvelope universal data model
│   │   └── service.py           # FastAPI app (/ws/ingest, /ws/telemetry, REST)
│   ├── tests/                   # Service tests
│   ├── Dockerfile
│   └── pyproject.toml
├── web/                         # FastAPI web UI server
│   ├── server.py                # Backend: telemetry WS proxy, chat, STT/TTS
│   ├── run.py                   # Dev server launcher (uvicorn)
│   ├── requirements.txt
│   └── static/                  # Browser frontend
│       ├── index.html           # TARS-style cockpit display
│       ├── app.js               # WebSocket client, audio capture, UI logic
│       └── style.css
├── services/                    # Standalone service containers
│   └── tts/                     # Local Kokoro TTS inference server
│       ├── server.py            # FastAPI TTS service
│       ├── Dockerfile
│       └── requirements.txt
├── data/
│   ├── checklists/              # YAML checklist files
│   │   ├── generic_single_engine.yaml
│   │   └── generic_jet.yaml
│   ├── chroma_db/               # Persistent ChromaDB data (git-ignored volume)
│   ├── finetune/                # Fine-tuning datasets
│   └── prompts/                 # System prompt templates
│       ├── merlin_system.md     # MERLIN persona definition
│       └── merlin_emergency.md  # Emergency procedure prompt overlay
├── tests/                       # Integration tests (root level)
│   ├── integration/
│   │   ├── conftest.py          # Integration test fixtures
│   │   ├── test_context_store.py
│   │   ├── test_orchestrator_e2e.py
│   │   ├── test_simconnect_websocket.py
│   │   ├── test_tool_chain.py
│   │   └── test_whisper_pipeline.py
│   ├── tool_calling/            # Tool calling tests (appears empty/in-progress)
│   └── pytest.ini               # Test config for root-level tests
├── tools/                       # Developer utilities
│   ├── download_faa_data.py     # FAA data fetcher for RAG ingestion
│   ├── generate_dataset/        # Dataset generation for fine-tuning
│   ├── ingest.py                # Document ingestion into ChromaDB
│   └── test_tts.py              # ElevenLabs TTS smoke test
├── scripts/                     # Startup/shutdown scripts
│   ├── start.sh                 # Linux: launch the full stack
│   ├── stop.sh                  # Linux: stop all services
│   └── merlin.bat               # Windows launcher
├── docs/                        # Project documentation
├── docker-compose.yml           # Production service stack
├── docker-compose.dev.yml       # Dev overrides (hot-reload, tiny whisper)
├── .env.example                 # Environment variable template
├── .env                         # Local config (git-ignored)
├── CLAUDE.md                    # Project conventions for Claude
├── CHANGELOG.md
└── README.md
```

## Key File Locations

### Entry Points
- `orchestrator/orchestrator/main.py`: CLI orchestrator entry point. Console script `merlin` calls `run()`.
- `web/server.py`: Web UI FastAPI app. Run via `web/run.py` or `uvicorn`.
- `web/run.py`: Dev launcher that starts uvicorn on port 3838.
- `telemetry-service/telemetry/service.py`: Telemetry service FastAPI app. Run via `uvicorn telemetry.service:app`.
- `adapters/msfs/Program.cs`: MSFS adapter entry point. Run via `dotnet run`.
- `services/tts/server.py`: Local TTS service FastAPI app.

### Configuration
- `orchestrator/orchestrator/config.py`: All orchestrator settings via `pydantic-settings`. Reads from `.env`.
- `telemetry-service/telemetry/config.py`: Telemetry service settings (env prefix: `TELEMETRY_`).
- `adapters/msfs/appsettings.json`: MSFS adapter config (SimConnect settings, telemetry service URL).
- `.env`: Root-level environment variables (git-ignored). All config flows through here.
- `.env.example`: Template showing all available env vars with documentation.
- `docker-compose.yml`: Production Docker service definitions.
- `docker-compose.dev.yml`: Development overrides.
- `orchestrator/pyproject.toml`: Python build config, dependencies, ruff settings, pytest config.

### Core Logic
- `orchestrator/orchestrator/claude_client.py`: MERLIN persona, Claude API streaming, tool use loop, query classification, token budgeting, prompt caching.
- `orchestrator/orchestrator/sim_client.py`: `TelemetryClient` (WebSocket consumer), `SimState` (Pydantic model), `HealthMonitor`, auto-reconnect.
- `orchestrator/orchestrator/flight_phase.py`: `FlightPhaseDetector` state machine with hysteresis.
- `orchestrator/orchestrator/tools.py`: All 5 Claude tool implementations.
- `orchestrator/orchestrator/context_store.py`: ChromaDB RAG store with TTL query cache.
- `telemetry-service/telemetry/adapter_manager.py`: Adapter tracking, consumer broadcasting, stale cleanup.
- `telemetry-service/telemetry/schema.py`: `TelemetryEnvelope` universal data model.

### Voice Pipeline
- `orchestrator/orchestrator/voice.py`: `VoiceInput` (PTT/VAD modes), `VoiceOutput` (ElevenLabs streaming).
- `orchestrator/orchestrator/audio_processing.py`: High-pass filter, silence trim, normalization, Silero VAD, aviation vocabulary prompt.
- `orchestrator/orchestrator/whisper_client.py`: Whisper HTTP client with retry and error handling.
- `orchestrator/orchestrator/tts_preprocessor.py`: ICAO-compliant text preprocessing (digit-by-digit for flight levels, headings, frequencies, etc.).
- `orchestrator/orchestrator/tts/`: TTS backend abstraction (`TTSClient` protocol, ElevenLabs, Kokoro).

### Data Files
- `data/prompts/merlin_system.md`: Full MERLIN persona (loaded at startup by `ClaudeClient`).
- `data/prompts/merlin_emergency.md`: Emergency procedure overlay prompt.
- `data/checklists/generic_single_engine.yaml`: Default checklist for single-engine aircraft.
- `data/checklists/generic_jet.yaml`: Default checklist for jets.

### Testing
- `orchestrator/tests/`: Unit tests for all orchestrator modules.
- `orchestrator/tests/conftest.py`: Shared fixtures (mock settings, sim states, mock APIs).
- `tests/integration/`: End-to-end and integration tests.
- `tests/integration/conftest.py`: Integration test fixtures.
- `adapters/msfs/SimConnectBridge.Tests/`: C# xUnit tests for the MSFS adapter.

## Module Organization

### Orchestrator Package (`orchestrator/orchestrator/`)
Flat module layout with specialized subpackages emerging:
- **Root modules:** One file per subsystem (`sim_client.py`, `claude_client.py`, `voice.py`, etc.)
- **`tts/` subpackage:** Backend abstraction layer with Protocol + implementations
- **`llm/` subpackage:** Placeholder for future LLM abstraction (currently empty)
- **No barrel files.** Import directly from modules: `from orchestrator.claude_client import ClaudeClient`

### Telemetry Service (`telemetry-service/telemetry/`)
Small, focused package:
- `schema.py` -- Data models (no business logic)
- `adapter_protocol.py` -- Message types and parsers
- `adapter_manager.py` -- Core business logic
- `service.py` -- HTTP/WebSocket layer
- `config.py` -- Settings

### MSFS Adapter (`adapters/msfs/`)
C# project with standard .NET layout:
- `Models/` -- Data transfer objects
- Root `.cs` files -- Core logic (SimConnectManager, TelemetryServiceClient, Program)
- `SimConnectBridge.Tests/` -- Test project (sibling of main source)

## Naming Conventions

### Files
- **Python:** `snake_case.py` (e.g., `claude_client.py`, `sim_client.py`, `flight_phase.py`)
- **C#:** `PascalCase.cs` (e.g., `SimConnectManager.cs`, `TelemetryServiceClient.cs`)
- **Tests (Python):** `test_{module_name}.py` (e.g., `test_claude_client.py`)
- **Tests (C#):** `{Module}Tests.cs` (e.g., `TelemetryServiceClientTests.cs`)
- **Config files:** lowercase with dots (e.g., `pyproject.toml`, `appsettings.json`)

### Directories
- **Python packages:** `snake_case` (e.g., `telemetry-service/telemetry/`, `orchestrator/orchestrator/`)
- **C# namespaces:** `PascalCase` (e.g., `Models/`, `SimConnectBridge.Tests/`)
- **Top-level dirs:** Hyphenated for services (`telemetry-service`), plural for collections (`adapters`, `scripts`, `tools`, `tests`)

## Where to Add New Code

### New Sim Adapter
- Create directory: `adapters/{sim_name}/`
- Implement WebSocket client that connects to `ws://{host}:8081/ws/ingest`
- Send `register` message, then stream `telemetry` and `status` messages
- Reference protocol: `telemetry-service/telemetry/adapter_protocol.py`
- Reference implementation: `adapters/msfs/` (C#) or write in any language

### New Claude Tool
- Add tool definition to `TOOL_DEFINITIONS` list in `orchestrator/orchestrator/claude_client.py`
- Add implementation function in `orchestrator/orchestrator/tools.py`
- Add dispatch case in `ClaudeClient._execute_tool()` in `claude_client.py`
- Add tests in `orchestrator/tests/test_tools.py`

### New Orchestrator Module
- Add file: `orchestrator/orchestrator/{module_name}.py`
- Wire into `Orchestrator.__init__()` in `orchestrator/orchestrator/main.py`
- Add tests: `orchestrator/tests/test_{module_name}.py`
- Add fixtures to `orchestrator/tests/conftest.py` if needed

### New Web API Endpoint
- Add endpoint in `web/server.py`
- Add corresponding frontend code in `web/static/app.js`

### New TTS Backend
- Add implementation: `orchestrator/orchestrator/tts/{backend_name}.py`
- Implement `TTSClient` protocol from `orchestrator/orchestrator/tts/base.py`
- Register in factory: `orchestrator/orchestrator/tts/__init__.py`

### New Checklist
- Add YAML file: `data/checklists/{aircraft_type}.yaml`
- Ingest into ChromaDB via `tools/ingest.py`

### New Integration Test
- Add test file: `tests/integration/test_{feature}.py`
- Use fixtures from `tests/integration/conftest.py`
- Mark with `@pytest.mark.integration`

### New Data for RAG
- Place source documents in appropriate location
- Run `tools/ingest.py` to index into ChromaDB
- For FAA data specifically, use `tools/download_faa_data.py` first

## Special Directories

### `data/chroma_db/`
- Purpose: Persistent ChromaDB vector store data
- Generated: Yes (by ChromaDB Docker container)
- Committed: No (volume mount, data persists locally)

### `orchestrator/orchestrator/llm/`
- Purpose: Planned LLM abstraction layer (similar to tts/ pattern)
- Generated: No
- Committed: Yes (but currently contains only `__pycache__`)
- Status: Empty placeholder for future multi-LLM support

### `data/finetune/`
- Purpose: Fine-tuning training data
- Generated: Partially (by `tools/generate_dataset/`)
- Committed: Varies

### `logs/`
- Purpose: Runtime log output
- Generated: Yes
- Committed: No

---

*Structure analysis: 2026-03-26*
