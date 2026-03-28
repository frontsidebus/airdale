# Technology Stack

**Analysis Date:** 2026-03-26

## Languages

**Primary:**
- Python 3.11+ (requires-python >=3.11) - Orchestrator, telemetry service, web server, tooling
- C# / .NET 8 - MSFS 2024 adapter (`adapters/msfs/`)

**Secondary:**
- JavaScript (vanilla) - Browser frontend (`web/static/app.js`)
- HTML/CSS - Cockpit-style web UI (`web/static/index.html`, `web/static/style.css`)

## Runtime

**Python Environment:**
- Python 3.11+ (specified in all `pyproject.toml` files)
- Docker images use Python 3.12-slim (orchestrator) and Python 3.11-slim (telemetry service)

**.NET Environment:**
- .NET 8.0 (`<TargetFramework>net8.0</TargetFramework>`)
- SimConnect SDK DLL (local reference, not NuGet): `C:\MSFS 2024 SDK\SimConnect SDK\lib\managed\Microsoft.FlightSimulator.SimConnect.dll`

**Package Managers:**
- pip with hatchling build backend (orchestrator, telemetry service)
- pip with requirements.txt (web server: `web/requirements.txt`)
- dotnet restore (MSFS adapter)
- No lockfiles detected for Python packages

## Frameworks

**Core:**
- FastAPI >= 0.104.0 - Web server (`web/server.py`) and telemetry service (`telemetry-service/telemetry/service.py`)
- uvicorn[standard] >= 0.24.0 - ASGI server for FastAPI services
- Pydantic >= 2.0 / pydantic-settings >= 2.0 - Data models and environment config across all Python components

**AI / ML:**
- anthropic >= 0.39.0 - Claude API client with streaming, tool use, and ephemeral caching (`orchestrator/orchestrator/claude_client.py`)
- chromadb >= 0.5.0 - Vector store client for RAG (`orchestrator/orchestrator/context_store.py`)
- sentence-transformers - Embedding model (used by ChromaDB internally)
- Silero VAD (via torch.hub) - Neural voice activity detection (`orchestrator/orchestrator/audio_processing.py`)

**Audio:**
- sounddevice >= 0.5.0 - Microphone input and PCM playback (`orchestrator/orchestrator/voice.py`)
- numpy >= 1.26 - Audio signal processing (high-pass filter, normalization, trim)
- ffmpeg (system binary) - MP3 decoding and webm-to-wav conversion

**Screen Capture:**
- mss >= 9.0 - Cross-platform screen capture (`orchestrator/orchestrator/screen_capture.py`)
- Pillow >= 10.0 - Image resizing and JPEG encoding for Claude Vision

**Testing:**
- pytest >= 8.0 + pytest-asyncio >= 0.24 - Python test runner (orchestrator)
- pytest-mock >= 3.14 - Mock utilities
- respx >= 0.21 - httpx request mocking
- xUnit 2.7.0 - C# test runner (`adapters/msfs/SimConnectBridge.Tests/`)
- FluentAssertions 6.12.0 - C# assertion library

**Build/Dev:**
- hatchling - Python build backend (orchestrator and telemetry service `pyproject.toml`)
- ruff >= 0.6 - Python linting and formatting
- Docker / Docker Compose - Service orchestration

## Key Dependencies

**Critical (hard to replace):**
- `anthropic` - Core AI inference; deeply integrated via streaming messages API with tool use, ephemeral prompt caching, and stop sequences (`orchestrator/orchestrator/claude_client.py`)
- `chromadb` - RAG vector store; document ingestion, cosine similarity search, collection management (`orchestrator/orchestrator/context_store.py`)
- `websockets >= 13.0` - All inter-component IPC: adapter-to-telemetry, telemetry-to-orchestrator, web-to-browser (`orchestrator/orchestrator/sim_client.py`)
- `Microsoft.FlightSimulator.SimConnect` - Native SDK binding for MSFS telemetry; no alternative for MSFS 2024

**Infrastructure:**
- `httpx >= 0.27.0` - Async HTTP client for Whisper STT, ElevenLabs TTS, Aviation API, and health checks (used throughout)
- `pydantic >= 2.0` / `pydantic-settings >= 2.0` - All data models and config management across every Python component
- `fastapi >= 0.104.0` - HTTP/WebSocket API layer for telemetry service and web server
- `sounddevice >= 0.5.0` - Audio I/O for CLI voice mode

**Optional (graceful degradation):**
- `torch >= 2.0` / `onnxruntime >= 1.16` - Silero VAD (falls back to RMS-based detection if missing); declared as `[vad]` extra in `orchestrator/pyproject.toml`
- `mss >= 9.0` / `Pillow >= 10.0` - Screen capture for Claude Vision (disabled by default via `SCREEN_CAPTURE_ENABLED=false`)

## Configuration

**Environment:**
- All config via `.env` files loaded by `pydantic-settings` (`orchestrator/orchestrator/config.py`)
- `.env.example` documents all variables; `.env` is gitignored
- Settings class: `orchestrator/orchestrator/config.py::Settings` (with `model_validator` for derived URLs)
- Telemetry service config: `telemetry-service/telemetry/config.py::TelemetryServiceSettings`

**Required API Keys:**
- `ANTHROPIC_API_KEY` - Claude inference (required)
- `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` - TTS (required for voice output)

**Key Config Files:**
- `orchestrator/pyproject.toml` - Build config, dependencies, ruff settings, pytest markers
- `telemetry-service/pyproject.toml` - Telemetry service build/deps
- `adapters/msfs/SimConnectBridge.csproj` - .NET project file with SimConnect SDK paths
- `adapters/msfs/appsettings.json` - MSFS adapter settings
- `docker-compose.yml` - Production service stack (Whisper, ChromaDB, telemetry, orchestrator)
- `docker-compose.dev.yml` - Dev overrides (hot-reload, tiny Whisper model, debug logging)

**Build:**
- Orchestrator Dockerfile: Multi-stage build (`python:3.12-slim`), non-root user, exposes port 3838 (`orchestrator/Dockerfile`)
- Telemetry service Dockerfile: Single-stage (`python:3.11-slim`), exposes ports 8080/8081 (`telemetry-service/Dockerfile`)
- Whisper: Pre-built Docker image `fedirz/faster-whisper-server:latest-cpu` (GPU variant available)
- ChromaDB: Official `chromadb/chroma:latest` Docker image

## Platform Requirements

**Development:**
- Python 3.11+ with pip
- .NET 8.0 SDK (for MSFS adapter)
- Docker + Docker Compose (for Whisper, ChromaDB, telemetry service)
- MSFS 2024 SDK installed at `C:\MSFS 2024 SDK\` (for adapter development)
- ffmpeg system binary (MP3 decode, webm conversion)
- WSL2 supported -- adapters run on Windows host, services in Docker or WSL2

**Production:**
- Docker Compose stack with 4 services: Whisper (port 9090), ChromaDB (port 8000), telemetry-service (ports 8080/8081), orchestrator (port 3838)
- MSFS adapter runs natively on Windows host
- NVIDIA GPU optional (faster Whisper inference with `latest-cuda` image + nvidia-container-toolkit)

## Service Ports

| Service | Port | Purpose |
|---------|------|---------|
| Orchestrator / Web UI | 3838 | FastAPI web server with browser UI |
| Telemetry Service (consumer) | 8080 | WebSocket for orchestrator/web consumers |
| Telemetry Service (ingest) | 8081 | WebSocket for adapter telemetry push |
| Whisper STT | 9090 (external) / 8000 (internal) | OpenAI-compatible transcription API |
| ChromaDB | 8000 | Vector store HTTP API |

## Version Info

| Component | Version |
|-----------|---------|
| merlin-orchestrator | 1.1.0 |
| airdale-telemetry-service | 1.0.0 |
| SimConnectBridge | 1.1.0 |
| Web UI | 1.1.0 |
| Default Claude model | claude-sonnet-4-20250514 |
| Default Whisper model | medium |
| ElevenLabs model | eleven_multilingual_v2 |

---

*Stack analysis: 2026-03-26*
