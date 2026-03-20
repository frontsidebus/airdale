# CLAUDE.md -- Project Conventions for Airdale (MERLIN)

## Project Overview

**Airdale** (codename) is an AI co-pilot called **MERLIN** for Microsoft Flight Simulator 2024. It connects to the sim via SimConnect, processes real-time telemetry, and provides voice-interactive flight guidance powered by Claude. The persona is a Navy Test Pilot with encyclopedic aviation knowledge and dry humor.

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestrator | Python 3.11+ (async, hatch build system) |
| SimConnect Bridge | C# / .NET 8 (out-of-process executable) |
| AI Inference | Anthropic Claude API with tool use |
| Vector Store / RAG | ChromaDB with sentence-transformers embeddings |
| Speech-to-Text | Whisper (local via whisper.cpp or OpenAI API) |
| Text-to-Speech | ElevenLabs streaming API |
| IPC | WebSocket (JSON) between bridge and orchestrator |
| Config | pydantic-settings with .env files |

## Directory Structure

```
airdale/
├── orchestrator/           # Python package -- the brain
│   ├── orchestrator/       # Source package
│   │   ├── __init__.py
│   │   ├── config.py       # Pydantic settings from .env
│   │   ├── sim_client.py   # WebSocket client for bridge
│   │   ├── main.py         # Entry point
│   │   └── ...
│   └── pyproject.toml      # Build config, dependencies, ruff settings
├── simconnect-bridge/      # C# .NET project -- the sensor layer
│   ├── Models/
│   │   └── SimState.cs     # Telemetry data model
│   ├── SimConnectBridge.csproj
│   └── appsettings.json
├── .env.example            # Environment variable template
├── .env                    # Local config (git-ignored)
└── CLAUDE.md               # This file
```

## Development Commands

### Python Orchestrator

```bash
cd orchestrator

# Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\activate           # Windows

# Install with dev dependencies
pip install -e ".[dev]"

# Run the orchestrator
merlin

# Lint
ruff check .

# Format
ruff format .

# Run tests
pytest
```

### C# SimConnect Bridge

```bash
cd simconnect-bridge

# Restore and build
dotnet restore
dotnet build

# Run (MSFS must be running)
dotnet run

# Run tests
dotnet test
```

## Code Style

### Python

- **Linter/Formatter:** ruff (config in `pyproject.toml`)
- **Line length:** 100 characters
- **Type hints:** Required on all function signatures
- **Async:** Use `async`/`await` throughout the orchestrator -- the event loop is the heartbeat
- **Imports:** Sorted by ruff (isort-compatible)
- **Naming:** `snake_case` for functions and variables, `PascalCase` for classes
- **Models:** Use Pydantic `BaseModel` for all data structures crossing boundaries
- **Config:** Use `pydantic-settings` `BaseSettings` -- never hardcode keys or magic numbers
- **ruff rules enabled:** E (pycodestyle), F (pyflakes), I (isort), N (pep8-naming), UP (pyupgrade), B (bugbear), SIM (simplify)

### C#

- Standard .NET conventions
- `PascalCase` for public members, `_camelCase` for private fields
- Nullable reference types enabled
- Models in the `Models/` directory
- XML doc comments on public APIs

## Important Architectural Decisions

1. **SimConnect bridge MUST be out-of-process** -- It runs as a separate .exe, not a WASM module. This is Microsoft's recommendation for stability. If the bridge crashes, MSFS keeps running.

2. **WebSocket for IPC** -- The bridge and orchestrator communicate over WebSocket with JSON payloads. This keeps the components language-agnostic and independently deployable.

3. **Claude tool use for actions** -- The orchestrator defines tools (`get_sim_state`, `lookup_airport`, `search_manual`, `get_checklist`, `create_flight_plan`) that Claude calls mid-response. Do not pre-fetch everything into the context window.

4. **Flight phase is derived from telemetry** -- The orchestrator infers the current phase (preflight, taxi, takeoff, climb, cruise, descent, approach, landing, rollout) from sim state. This drives checklist selection and proactive callouts.

5. **Voice is streaming** -- TTS begins playing as Claude's response streams in. Do not wait for the full response before starting audio playback.

## Testing Approach

- **Python:** pytest + pytest-asyncio for async tests. Mock the WebSocket connection and Claude API in unit tests.
- **C#:** xUnit or NUnit. Mock SimConnect for unit tests. Integration tests require MSFS running.
- **No sim required for most tests** -- Record telemetry snapshots as JSON fixtures and replay them through the orchestrator.

## Environment Variables

All config flows through `.env` files loaded by `pydantic-settings`. See `.env.example` for the complete list with documentation. Never commit `.env` to version control.
