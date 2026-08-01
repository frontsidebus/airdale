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

## Turn Detection (end of utterance)

| Variable | Default | Description |
|---|---|---|
| `TURN_DETECTOR` | `"smart"` | End-of-turn detector: `smart` (semantic, Smart Turn v3 ONNX) or `silence` (fixed silence threshold) |
| `TURN_THRESHOLD` | `0.5` | Probability above which the semantic detector calls the turn complete. Raise it to make MERLIN more willing to wait through a pause |
| `TURN_PROBE_SILENCE_MS` | `150` | Silence observed before consulting the semantic detector. Lower than `VAD_SILENCE_MS` because the model decides on content, not duration |
| `VAD_SILENCE_MS` | `400` | Silence threshold for the fixed-silence detector and the RMS fallback |

Silero VAD finds candidate endpoints cheaply and decides *when* to ask; the turn detector decides *whether* the turn is actually over. `smart` resolves its fallback to `silence` at startup -- not mid-flight -- when onnxruntime or the model file is missing; run `python3 tools/fetch_turn_model.py` to enable it. Fixed-silence detection stays available because a threshold short enough to feel responsive cuts off mid-sentence pauses, and aviation phraseology is full of them ("descend and maintain... one zero thousand").

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

## Authority & Safety

These settings decide whether MERLIN may command the aircraft at all, when it must defer to the pilot, and how long it waits before concluding the command path is dead. They gate the write path; they do not change what MERLIN can talk about.

| Variable | Default | Description |
|---|---|---|
| `AUTHORITY_LEVEL` | `"full"` | How far MERLIN may go: `advisory`, `assisted`, or `full`. An unknown value fails at startup |
| `AUTHORITY_OVERRIDE_GRACE_S` | `30.0` | Seconds after MERLIN issues a command during which a change to that command's own telemetry fields is credited to MERLIN rather than read as a pilot override |
| `AUTHORITY_OVERRIDE_SETTLE_S` | `2.0` | Seconds to wait before re-scrutinising the fields of a command that has no verification rule. Surfaces, autopilot and radios broadcast at 1 Hz |
| `AUTHORITY_OVERRIDE_COOLDOWN_S` | `120.0` | Seconds MERLIN stays advisory after a pilot override. Rolling -- each new override pushes the expiry out |
| `AUTHORITY_WATCHDOG_MAX_TIMEOUTS` | `3` | Consecutive command-path timeouts before MERLIN latches to advisory |
| `AUTHORITY_COMMAND_TIMEOUT_S` | `5.0` | Seconds to wait for a command acknowledgment from the sim adapter |
| `AUTHORITY_VERIFY_TIMEOUT_S` | `3.0` | Seconds spent polling telemetry to confirm a command actually took effect |
| `AUTHORITY_TOOL_TIMEOUT_S` | `12.0` | Outer deadline on the `set_aircraft_control` tool call. Must exceed `AUTHORITY_COMMAND_TIMEOUT_S` + `AUTHORITY_VERIFY_TIMEOUT_S`, checked at startup |

### Authority levels

| Level | Behaviour |
|---|---|
| `advisory` | Never commands. Reports what it would have done, with the safety verdict |
| `assisted` | Executes, but withholds anything `command_safety` flags as `warning` |
| `full` | Executes unless `command_safety` blocks it outright |

`full` is the default because it is exactly the pre-authority behaviour -- upgrading changes nothing, and restriction is opt-in. The `authority_level` setting is read once at startup and seeds the runtime authority state.

**Know what `assisted` does not cover.** `assisted` withholds only on `warning` severity, and only 7 safety rules exist today, covering gear, flaps, autopilot and throttle. For the other 16 of the 20 commandable systems there is no `warning` rule at all, so `assisted` behaves identically to `full` for them. Treat `assisted` as "extra care around the four systems that have rules", not as a general-purpose restraint. `advisory` is the only level that withholds everything.

### Why MERLIN is at the level it reports

The authority level always travels with a reason, shown in `/api/status` and in the CLI:

- **`config`** -- this is how you set it up. Nothing has overridden your `AUTHORITY_LEVEL`.
- **`override`** -- MERLIN saw you take over. It drops to `advisory` for `AUTHORITY_OVERRIDE_COOLDOWN_S`, extending that window each time you move a control, and restores itself automatically once you stop.
- **`watchdog`** -- MERLIN cannot reach the sim. After `AUTHORITY_WATCHDOG_MAX_TIMEOUTS` consecutive unacknowledged commands it latches to `advisory`. A later success does not clear the latch (a latch that stops command issuance can never produce the ack that would clear it); reconnecting does.
- **`degraded`** -- the authority subsystem itself failed to start, so MERLIN restricted itself to `advisory` rather than assume it may act. This is not a setting you chose. Restart and check the log for the reason, which is reported alongside the badge.

### Timeout budget

`AUTHORITY_TOOL_TIMEOUT_S` must be strictly greater than `AUTHORITY_COMMAND_TIMEOUT_S` + `AUTHORITY_VERIFY_TIMEOUT_S`. The tool's outer deadline starts first, so an equal budget fires before the acknowledgment timeout does: the command path looks like a slow tool rather than a dead adapter, and the watchdog never counts the timeout it exists to catch. Startup validation rejects a configuration that violates this, naming all three fields.

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
