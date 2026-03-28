# External Integrations

**Analysis Date:** 2026-03-26

## APIs & External Services

### Anthropic Claude API
- **Purpose:** Core AI inference -- MERLIN persona, tool use, streaming responses, vision analysis
- **SDK/Client:** `anthropic` Python SDK (`AsyncAnthropic`)
- **Auth:** `ANTHROPIC_API_KEY` env var
- **Files:** `orchestrator/orchestrator/claude_client.py`
- **Usage pattern:** Streaming messages API with tool use loop, ephemeral prompt caching, stop sequences, dynamic token budgeting (256/1024/2048 tokens based on query classification)
- **Features used:**
  - `messages.stream()` with async iteration
  - Tool definitions and `tool_use` / `tool_result` message protocol
  - `cache_control: {"type": "ephemeral"}` on static system prompt blocks
  - `stop_sequences` for natural conversation breaks
  - Image content blocks (base64 JPEG) for screen capture vision
  - Model: `claude-sonnet-4-20250514` (configurable via `CLAUDE_MODEL`)

### ElevenLabs TTS API
- **Purpose:** Text-to-speech synthesis for MERLIN's voice output
- **SDK/Client:** Direct HTTP via `httpx` (REST) and `websockets` (streaming WebSocket)
- **Auth:** `ELEVENLABS_API_KEY` env var, voice selected via `ELEVENLABS_VOICE_ID`
- **Files:**
  - `orchestrator/orchestrator/voice.py` - CLI voice output (REST-based)
  - `web/server.py` - Web server TTS (WebSocket streaming with REST fallback)
- **Endpoints used:**
  - REST: `https://api.elevenlabs.io/v1/text-to-speech/{voice_id}` and `/stream` variant
  - WebSocket: `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input?model_id={model_id}&output_format=mp3_44100_128`
- **Model:** `eleven_multilingual_v2` (configurable via `ELEVENLABS_MODEL_ID`)
- **Voice settings:** `stability: 0.75, similarity_boost: 0.80, style: 0.15` (web) or `stability: 0.5, similarity_boost: 0.75, style: 0.3` (CLI)
- **Optimization:** Pre-populated TTS phrase cache at startup for common responses ("Roger.", "Copy that.", etc.) -- see `_CACHEABLE_PHRASES` in `web/server.py`

### Aviation API
- **Purpose:** Airport information lookup (name, location, elevation, facility data)
- **SDK/Client:** Direct HTTP via `httpx`
- **Auth:** None (public API)
- **Files:** `orchestrator/orchestrator/tools.py::lookup_airport()`
- **Endpoint:** `https://api.aviationapi.com/v1/airports?apt={identifier}`
- **Usage:** Called by Claude as a tool (`lookup_airport`) during conversations and flight plan creation

### Microsoft SimConnect SDK
- **Purpose:** Real-time telemetry extraction from MSFS 2024 (position, attitude, speeds, engines, autopilot, radios, fuel, weather, surfaces)
- **SDK/Client:** `Microsoft.FlightSimulator.SimConnect` managed DLL + native `SimConnect.dll` (P/Invoke)
- **Auth:** None (local SDK)
- **Files:**
  - `adapters/msfs/SimConnectManager.cs` - Event-driven message pump
  - `adapters/msfs/Models/SimDataStructs.cs` - SimConnect data structures
  - `adapters/msfs/Models/SimState.cs` - Internal telemetry model
  - `adapters/msfs/TelemetryServiceClient.cs` - WebSocket client pushing to telemetry service
- **Connection pattern:** EventWaitHandle-based message pump (not timer-based polling) to avoid COM errors

## Data Stores

### ChromaDB (Vector Store)
- **Purpose:** RAG storage for aircraft manuals, checklists, aviation procedures, and FAA data
- **Client:** `chromadb.HttpClient` via HTTP API
- **Files:**
  - `orchestrator/orchestrator/context_store.py` - Query interface with TTL cache and flight-phase-aware retrieval
  - `tools/ingest.py` - Document ingestion utility
  - `tools/download_faa_data.py` - FAA data fetcher
- **Connection:** `CHROMADB_URL` env var (default `http://localhost:8000`)
- **Collection:** `merlin_docs` with `hnsw:space: cosine`
- **Docker:** `chromadb/chroma:latest` with persistent volume at `./data/chroma_db`
- **Embedding:** sentence-transformers (ChromaDB default embedding function)
- **Caching:** In-memory `_QueryCache` with 60s TTL, auto-invalidated on flight phase change

### YAML Checklists (File-based)
- **Purpose:** Aircraft checklists organized by flight phase
- **Location:** `data/checklists/` (e.g., `generic_single_engine`)
- **Format:** YAML files loaded at runtime
- **Fallback:** `DEFAULT_CHECKLISTS` dict in `orchestrator/orchestrator/tools.py` if ChromaDB unavailable

### Prompt Templates (File-based)
- **Purpose:** MERLIN persona definition and emergency overlays
- **Location:** `data/prompts/merlin_system.md`, `data/prompts/merlin_emergency.md`
- **Usage:** Loaded at import time in `orchestrator/orchestrator/claude_client.py` with inline fallback

## Message/Event Systems

### WebSocket IPC (Internal)
All inter-component communication uses JSON-over-WebSocket:

**Adapter Ingest Channel:**
- **Endpoint:** `ws://telemetry-service:8080/ws/ingest` (mapped to external port 8081)
- **Direction:** Adapter -> Telemetry Service
- **Protocol:** Register (with adapter_id, sim_name, vehicle_type, version) -> telemetry/status streaming
- **Files:** `telemetry-service/telemetry/service.py::ws_ingest()`, `adapters/msfs/TelemetryServiceClient.cs`

**Consumer Broadcast Channel:**
- **Endpoint:** `ws://telemetry-service:8080/ws/telemetry`
- **Direction:** Telemetry Service -> Orchestrator/Web
- **Protocol:** Subscribe (with optional field filters), get_state, heartbeat; continuous state broadcasts
- **Files:** `telemetry-service/telemetry/service.py::ws_telemetry()`, `orchestrator/orchestrator/sim_client.py::TelemetryClient`

**Browser Telemetry Proxy:**
- **Endpoint:** `ws://localhost:3838/ws/telemetry`
- **Direction:** Web Server -> Browser
- **Pattern:** Proxy that connects to telemetry service and forwards to browser clients
- **Files:** `web/server.py::ws_telemetry()`

**Browser Chat Channel:**
- **Endpoint:** `ws://localhost:3838/ws/chat`
- **Direction:** Browser <-> Web Server
- **Protocol:** Text messages, audio binary frames, interrupt signals, streamed response chunks, TTS audio
- **Barge-in:** Supports mid-response cancellation via interrupt events and cancellable asyncio tasks
- **Files:** `web/server.py::ws_chat()`

**ElevenLabs TTS WebSocket:**
- **Endpoint:** `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input`
- **Direction:** Web Server -> ElevenLabs (external)
- **Pattern:** Single persistent connection per response; text chunks in, audio chunks out
- **Files:** `web/server.py::_tts_websocket_stream()`

### Connection Resilience
- **Auto-reconnect:** `TelemetryClient` implements exponential backoff (1s base, 30s max, 2x factor) in `orchestrator/orchestrator/sim_client.py`
- **Heartbeat:** 5s interval, 15s timeout; ping/pong verification before triggering reconnect
- **Delta detection:** String comparison of full state JSON to skip duplicate processing
- **Stale adapter cleanup:** Telemetry service periodically removes disconnected adapters

## Speech-to-Text (Local Service)

### faster-whisper
- **Purpose:** Local speech-to-text transcription (no external API calls)
- **Docker image:** `fedirz/faster-whisper-server:latest-cpu`
- **API:** OpenAI-compatible `/v1/audio/transcriptions` endpoint
- **Connection:** `WHISPER_URL` env var (default `http://localhost:9090`)
- **Model:** `medium` (configurable via `WHISPER_MODEL`; `tiny` in dev mode)
- **Files:**
  - `orchestrator/orchestrator/whisper_client.py` - Standalone HTTP client with retry logic (3 retries, 1.5s backoff)
  - `orchestrator/orchestrator/voice.py::VoiceInput.transcribe()` - CLI transcription path
  - `web/server.py::_transcribe_with_confidence()` - Web server transcription path
- **Audio preprocessing:** High-pass filter (80Hz cutoff), silence trimming (-40dB threshold), peak normalization in `orchestrator/orchestrator/audio_processing.py`
- **Aviation bias:** `AVIATION_PROMPT` initial_prompt with NATO phonetic alphabet, aviation terms, and MERLIN-specific vocabulary
- **Confidence scoring:** Extracted from verbose_json `avg_logprob` segments, mapped via `exp()` to 0.0-1.0 range

## File I/O

**Config Files:**
- `.env` - All environment configuration (gitignored)
- `.env.example` - Template with documentation
- `adapters/msfs/appsettings.json` - MSFS adapter config (telemetry service URL, polling interval)

**Data Files:**
- `data/checklists/*.yaml` - Flight checklists by aircraft type
- `data/prompts/merlin_system.md` - MERLIN persona system prompt
- `data/prompts/merlin_emergency.md` - Emergency procedure prompt overlay
- `data/chroma_db/` - ChromaDB persistent storage (Docker volume mount)

**Generated/Runtime:**
- `whisper_cache` Docker volume - Cached Hugging Face model files for faster-whisper

**Static Assets:**
- `web/static/index.html` - TARS-style cockpit display
- `web/static/app.js` - WebSocket client, audio capture, UI logic
- `web/static/style.css` - Cockpit UI styling

## Environment Dependencies

**Required Environment Variables:**
- `ANTHROPIC_API_KEY` - Claude API key (required for any functionality)
- `ELEVENLABS_API_KEY` - ElevenLabs API key (required for voice output)
- `ELEVENLABS_VOICE_ID` - ElevenLabs voice selection (required for voice output)

**Optional Environment Variables:**
- `CLAUDE_MODEL` - Model identifier (default: `claude-sonnet-4-20250514`)
- `CLAUDE_MAX_TOKENS` - Response token budget (default: 1024)
- `CLAUDE_MAX_TOKENS_BRIEFING` - Briefing token budget (default: 2048)
- `CLAUDE_MAX_HISTORY` - Conversation history limit (default: 20 message pairs)
- `CLAUDE_TEMPERATURE` - Response temperature (default: 0.7)
- `TELEMETRY_SERVICE_HOST` / `TELEMETRY_SERVICE_PORT` - Telemetry service location (default: localhost:8080)
- `WHISPER_MODEL` - Whisper model size (default: medium)
- `WHISPER_URL` - Whisper service URL (default: http://localhost:9090)
- `ELEVENLABS_MODEL_ID` - TTS model (default: eleven_multilingual_v2)
- `CHROMADB_URL` - ChromaDB URL (default: http://localhost:8000)
- `SCREEN_CAPTURE_ENABLED` - Enable vision analysis (default: false)
- `LOG_LEVEL` - Logging verbosity (default: INFO)

**External Tools Required:**
- `ffmpeg` - System binary for MP3 decoding and audio format conversion (required at runtime)
- Docker + Docker Compose - For running Whisper, ChromaDB, and optionally the telemetry service and orchestrator
- MSFS 2024 SDK - For building/running the MSFS adapter on Windows
- SimConnect MSI - Must be installed/re-run after MSFS restarts to fix COM registration

**System Libraries (Docker runtime):**
- `libportaudio2` - PortAudio for sounddevice
- `libsndfile1` - Audio file I/O
- `curl` - Health checks

---

*Integration audit: 2026-03-26*
