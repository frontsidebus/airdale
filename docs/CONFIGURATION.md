# Configuration Reference

All configuration flows through environment variables loaded by `pydantic-settings` from `.env` files. The `Settings` class in `orchestrator/orchestrator/config.py` defines every variable with its type, default, and description. Never hardcode API keys or magic numbers.

Copy `.env.example` to `.env` and fill in the required values. The `.env` file is git-ignored.

---

## API Keys

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | -- | Anthropic API key for Claude inference |
| `DEEPGRAM_API_KEY` | If STT=deepgram | `""` | Deepgram API key for streaming speech-to-text |
| `CARTESIA_API_KEY` | If TTS=cartesia | `""` | Cartesia API key for ultra-low-latency TTS |
| `ELEVENLABS_API_KEY` | If TTS=elevenlabs | `""` | ElevenLabs API key for TTS synthesis |

`ANTHROPIC_API_KEY` is the only strictly required key. The others are required only if their corresponding backend is selected.

---

## Speech-to-Text (STT)

### Backend Selection

| Variable | Default | Description |
|---|---|---|
| `STT_BACKEND` | `"deepgram"` | STT backend: `deepgram` (cloud streaming) or `whisper` (local batch) |

### Deepgram (recommended)

| Variable | Default | Description |
|---|---|---|
| `DEEPGRAM_API_KEY` | `""` | API key |
| `DEEPGRAM_MODEL` | `"nova-3"` | Model identifier. `nova-3` is recommended for aviation terminology |
| `DEEPGRAM_ENDPOINTING_MS` | `300` | Silence threshold in milliseconds before finalizing a transcript. Lower values feel snappier but may cut off mid-sentence |

### Whisper (legacy fallback)

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `"large-v3-turbo"` | Model size used by the Docker-hosted faster-whisper service |
| `WHISPER_URL` | `"http://localhost:9090"` | URL of the local Whisper ASR HTTP service |

Whisper runs as a Docker container via `docker-compose.yml`. The `large-v3-turbo` model provides the best balance of speed and aviation vocabulary recognition. Whisper is now the fallback backend; Deepgram streaming is preferred for lower latency.

---

## Text-to-Speech (TTS)

### Backend Selection

| Variable | Default | Description |
|---|---|---|
| `TTS_BACKEND` | `"cartesia"` | TTS backend: `cartesia` (low-latency), `elevenlabs` (high quality), or `local` (Kokoro, offline) |

### Cartesia (recommended for latency)

| Variable | Default | Description |
|---|---|---|
| `CARTESIA_API_KEY` | `""` | API key |
| `CARTESIA_VOICE_ID` | `""` | Voice identifier |
| `CARTESIA_MODEL_ID` | `"sonic-2"` | Model identifier |

Cartesia provides the lowest time-to-first-byte for TTS audio, making voice interactions feel more responsive.

### ElevenLabs

| Variable | Default | Description |
|---|---|---|
| `ELEVENLABS_API_KEY` | `""` | API key |
| `ELEVENLABS_VOICE_ID` | `""` | Voice identifier for TTS output |
| `ELEVENLABS_MODEL_ID` | `"eleven_multilingual_v2"` | Model identifier. V2 supports the `tts_style` parameter |
| `TTS_STABILITY` | `0.75` | Voice stability (0.0-1.0). Higher values produce more consistent but less expressive speech |
| `TTS_SIMILARITY_BOOST` | `0.80` | Voice clarity and similarity to the original voice (0.0-1.0) |
| `TTS_STYLE` | `0.15` | Expressiveness (0.0-1.0). Only works with V2+ models. Keep low for professional aviation tone |

### Local (Kokoro)

| Variable | Default | Description |
|---|---|---|
| `TTS_LOCAL_URL` | `"http://localhost:8880"` | URL of the local Kokoro TTS server |
| `TTS_VOICE_ID_LOCAL` | `"af_heart"` | Kokoro voice identifier |

The local backend requires no API key and works offline, but quality is lower than the cloud options.

---

## LLM Settings

### Core Model

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_MODEL` | `"claude-sonnet-4-20250514"` | Primary Claude model for all responses |
| `CLAUDE_MAX_TOKENS` | `1024` | Default max tokens. Keeps cockpit comms tactical and concise |
| `CLAUDE_MAX_TOKENS_BRIEFING` | `2048` | Max tokens for briefings, checklists, and flight plans |
| `CLAUDE_MAX_HISTORY` | `20` | Max message pairs retained in conversation history |

### Model Routing

The LLM optimization branch introduces a fast model for short acknowledgments:

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_MODEL_FAST` | `"claude-haiku-4-5-20251001"` | Fast/cheap model for short acknowledgments and simple queries |

### Temperature Tiers

Temperature is dynamically adjusted based on flight phase criticality:

| Variable | Default | Flight Phases | Description |
|---|---|---|---|
| `CLAUDE_TEMPERATURE` | `0.3` | -- | Base temperature (overridden by phase-specific values) |
| `CLAUDE_TEMP_CRITICAL` | `0.1` | Takeoff, Approach, Landing | Low temperature for maximum determinism during critical phases |
| `CLAUDE_TEMP_NORMAL` | `0.3` | Climb, Descent, Taxi | Moderate temperature for routine operations |
| `CLAUDE_TEMP_RELAXED` | `0.5` | Preflight, Cruise, Landed | Higher temperature allows more personality and banter |

### Conversation Summary

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_SUMMARY_INTERVAL` | `10` | Summarize conversation history every N message turns |
| `CLAUDE_SUMMARY_MAX_TOKENS` | `256` | Max tokens for the generated conversation summary |

When the conversation exceeds `CLAUDE_SUMMARY_INTERVAL` turns, older messages are condensed into a summary to manage context window usage while preserving important flight context.

---

## Telemetry Service

| Variable | Default | Description |
|---|---|---|
| `TELEMETRY_SERVICE_HOST` | `"localhost"` | Telemetry service hostname |
| `TELEMETRY_SERVICE_PORT` | `8080` | Telemetry service WebSocket port |
| `TELEMETRY_SERVICE_URL` | `""` | Full WebSocket URL. If empty, constructed as `ws://{host}:{port}/ws/telemetry` |

### WSL2 Configuration

When the orchestrator runs in Docker but the sim adapter runs on the Windows host:

```bash
TELEMETRY_SERVICE_HOST=host.docker.internal
```

When running natively in WSL2 without Docker:

```bash
TELEMETRY_SERVICE_HOST=$(hostname).local
```

---

## ChromaDB (Vector Store)

| Variable | Default | Description |
|---|---|---|
| `CHROMADB_URL` | `"http://localhost:8000"` | URL of the ChromaDB HTTP server running in Docker |

ChromaDB stores the `merlin_docs` collection using cosine similarity with HNSW indexing. The context store degrades gracefully if ChromaDB is unavailable -- queries return empty results and the orchestrator continues without RAG context.

---

## Screen Capture

| Variable | Default | Description |
|---|---|---|
| `SCREEN_CAPTURE_ENABLED` | `false` | Enable screen capture for vision-based cockpit analysis |
| `SCREEN_CAPTURE_FPS` | `1` | Capture rate in frames per second. Keep low to minimize CPU usage |

When enabled, MERLIN can analyze the sim's visual display for instrument readings, warning lights, and other visual cues that are not available through telemetry.

---

## Logging

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `"INFO"` | Python logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

Set to `DEBUG` for full telemetry dumps, WebSocket frame logging, and Claude API request/response details. Use `WARNING` in production to reduce log volume.

---

## Derived Settings

These properties are computed from other settings and are not set directly:

| Property | Logic |
|---|---|
| `telemetry_service_url` | If empty, built from `ws://{host}:{port}/ws/telemetry` |
| `tts_configured` | `True` if the selected backend has the required API key and voice ID |
| `voice_id` | Returns the voice ID for the active TTS backend |

---

## Quick Start Example

Minimal `.env` for voice interaction with Deepgram + Cartesia:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# STT
STT_BACKEND=deepgram
DEEPGRAM_API_KEY=dg-...

# TTS
TTS_BACKEND=cartesia
CARTESIA_API_KEY=sk-cart-...
CARTESIA_VOICE_ID=your-voice-id

# Telemetry
TELEMETRY_SERVICE_HOST=localhost
TELEMETRY_SERVICE_PORT=8080
```

Minimal `.env` for text-only interaction (no voice):

```bash
ANTHROPIC_API_KEY=sk-ant-...
TELEMETRY_SERVICE_HOST=localhost
```
