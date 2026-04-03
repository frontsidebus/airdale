# Getting Started with MERLIN

This guide assumes you have completed the [installation](INSTALL.md) and configured your `.env` file with API keys. See the [Configuration Guide](CONFIGURATION.md) for all available settings.

---

## Your First Flight with MERLIN

### 1. Start MSFS 2024

Launch MSFS 2024 and load into a **Free Flight**. For your first session, pick something familiar:

- **Aircraft:** Cessna 172 Skyhawk (simple, well-modeled, single engine)
- **Airport:** Anywhere you know -- your home airport, or a big field like KLAX or KJFK
- **Weather:** Clear skies (to keep things simple)
- **Time:** Daytime

Wait until you are fully loaded into the cockpit before proceeding.

### 2. Start MERLIN

The easiest way to start everything is with the startup script (from WSL):

```bash
./scripts/start.sh
```

This validates your API keys, launches Docker services (ChromaDB, telemetry service), builds and starts the SimConnect bridge, and starts the web server. You'll see a status summary when everything is ready.

You can verify all systems with the health check:

```bash
./scripts/healthcheck.sh
```

To stop all components:

```bash
./scripts/stop.sh
```

<details>
<summary>Manual startup (step-by-step)</summary>

**Start the SimConnect Bridge** -- open a terminal on your Windows host (PowerShell or CMD):

```bash
cd simconnect-bridge
dotnet run
```

You should see:

```
=== MERLIN SimConnect Bridge ===

[Bridge] Attempting SimConnect connection as "MERLIN SimConnect Bridge"...
[SimConnect] Connection opened.
[SimConnect] Data definitions registered.
[WebSocket] Server started on ws://0.0.0.0:8080
[SimConnect] Polling started: high-freq=30Hz, low-freq=1Hz
[Bridge] SimConnect connected. Broadcasting telemetry.
[Bridge] Press Ctrl+C to shut down.
```

If you see `Retrying in 5000ms...`, make sure MSFS is fully loaded into a flight (not the main menu).

**Start Docker Services:**

```bash
docker compose up -d
```

**Start the Web Server:**

```bash
cd web
source ../orchestrator/.venv/bin/activate
python run.py
```

</details>

### 5. Verify Connection

When everything is connected, you will see:

```
=== MERLIN AI Co-Pilot ===
Type your message, or 'voice' to toggle voice input.
Commands: /voice, /vad, /ptt, /capture, /clear, /quit

Captain>
```

Run `/status` to confirm connectivity:

```
Captain> /status
SimConnect: Connected | Phase: PREFLIGHT | Alt: 433ft | IAS: 0kt | HDG: 270° | VS: +0fpm
Docs in store: 0
Screen capture: off
```

If SimConnect shows "Not connected", check that the bridge is running and the WebSocket URL in your `.env` is correct.

### 6. Talk to MERLIN

Type a message at the `Captain>` prompt:

```
Captain> MERLIN, what's our current altitude and airspeed?
```

MERLIN will call the `get_sim_state` tool, read your telemetry, and respond with your current flight parameters.

**Example prompts to try:**

| Prompt | What MERLIN does |
|---|---|
| `What's our current altitude and airspeed?` | Reads live telemetry and reports |
| `Run me through the before-takeoff checklist` | Retrieves the phase-appropriate checklist |
| `Brief me on the approach into KJFK` | Looks up airport data and builds an approach briefing |
| `What's the weather looking like?` | Reports ambient conditions from sim telemetry |
| `Tell me about the engine instruments` | Reads engine RPM, oil temp/pressure, fuel flow |
| `Create a flight plan from KLAX to KSFO at 8000 feet` | Builds a draft flight plan with airport lookups |
| `Search the manual for Vne` | Queries the RAG store for aircraft limitations |

### 7. Text Mode vs Voice Mode

**Text mode** (default): Type at the `Captain>` prompt. Best for testing or noisy environments.

**Voice mode**: Toggle with the `/voice` command. MERLIN listens through your microphone, transcribes via Deepgram streaming STT, processes with Claude, and responds through Cartesia TTS (~90ms latency).

```
Captain> /voice
Voice input toggled.
[Listening...]
```

The default voice input mode is push-to-talk. Switch between modes:

- `/ptt` -- Push-to-talk mode (press Enter to stop recording)
- `/vad` -- Voice activity detection (speaks, pauses, and MERLIN responds automatically)

### 8. Slash Commands Reference

| Command | Description |
|---|---|
| `/voice` | Toggle voice input on/off |
| `/vad` | Switch to voice-activity-detection mode |
| `/ptt` | Switch to push-to-talk mode |
| `/capture` | Toggle screen capture for Claude Vision analysis |
| `/status` | Show connection status, document count, and capture state |
| `/clear` | Clear conversation history (start fresh) |
| `/quit` | Shut down MERLIN |

---

## Ingesting Flight Manuals

MERLIN's RAG pipeline lets you load aircraft POHs and reference documents so it can answer aircraft-specific questions with real data instead of general knowledge.

### Supported Formats

The context store ingests **plain text files** (`.txt`). If you have a PDF manual, convert it to text first using a tool like `pdftotext`, Adobe Acrobat, or an online converter.

### How to Ingest a Document

```python
import asyncio
from orchestrator.context_store import ContextStore

async def main():
    store = ContextStore()
    count = await store.ingest_document(
        "data/manuals/c172s_poh.txt",
        metadata={
            "aircraft_type": "Cessna 172 Skyhawk",
            "document_type": "poh",
            "section": "general",
        },
    )
    print(f"Ingested {count} chunks")

asyncio.run(main())
```

The v2 ingestion pipeline uses **aviation-aware semantic chunking** that preserves checklist items, procedure steps, and limitation entries as atomic units. See [RAG System](RAG_SYSTEM.md) for details.

Metadata fields (`aircraft_type`, `document_type`, `section`) are important — they enable filtered retrieval so MERLIN searches the right documents for the aircraft you're flying.

### Verifying Ingestion

Use `/status` in the orchestrator to check the document count:

```
Captain> /status
Docs in store: 47
```

Or query the store directly:

```python
results = await store.query("Vne limitations", n_results=3)
for r in results:
    print(r["metadata"]["source"], "-", r["content"][:100])
```

### Tips for Good Results

- **One document per file.** Don't merge multiple manuals into one text file.
- **Include section headers.** The chunking algorithm works better when text has clear structure.
- **Set the `aircraft_type` metadata** to match how MSFS reports the aircraft title (e.g., `"Cessna 172 Skyhawk G1000"`).
- **Chunk size of 1000 characters** (the default) works well for most manuals. Increase to 1500-2000 for dense technical content.

---

## Customizing MERLIN

### Adjusting the Persona

MERLIN's system prompt is defined in two places:

- **Full prompt:** `data/prompts/merlin_system.md` -- the complete persona definition with behavioral guidelines, knowledge scope, and tool usage rules. This is the reference document.
- **Runtime prompt:** `orchestrator/orchestrator/claude_client.py` -- the `MERLIN_PERSONA` constant that is actually sent to Claude on each request. Edit this to change MERLIN's personality, tone, or behavioral rules.

For example, to make MERLIN more formal and less humorous, adjust the personality bullet points in the persona string.

### Adding Custom Checklists

Checklists are YAML files stored in `data/checklists/`. Two generic checklists are included:

- `generic_single_engine.yaml` -- for Cessna 172, PA-28, SR22, and similar
- `generic_jet.yaml` -- for 747, 787, A320, CJ4, and similar

**YAML format:**

```yaml
aircraft_class: single_engine_piston
version: "1.0"
author: MERLIN

phases:
  preflight:
    name: "Preflight Inspection"
    items:
      - item: "Weather briefing"
        setting: "Obtained"
        remark: "Optional MERLIN commentary."
      - item: "Fuel quantity"
        setting: "Sufficient for flight + reserves"
        remark: ~   # tilde means no remark
```

Each phase contains a list of items with:
- `item` -- the checklist action
- `setting` -- the expected position or value
- `remark` -- optional MERLIN commentary (set to `~` for none)

**Phase names used in the checklists:**

`preflight`, `before_start`, `engine_start`, `before_taxi`, `before_takeoff`, `takeoff`, `climb`, `cruise`, `descent`, `approach`, `before_landing`, `after_landing`, `shutdown`

To add a checklist for a new aircraft, create a new YAML file following the same format and ingest it into the context store.

### Configuring Voice

**v2 uses cloud-based STT and TTS by default** for the lowest latency. See [Voice Pipeline](VOICE_PIPELINE.md) for the full architecture.

**STT (Speech-to-Text):** Deepgram Nova-3 (default). Streaming with aviation keyword boosting. Set `DEEPGRAM_API_KEY` in `.env`. For local/offline use, set `STT_BACKEND=whisper`.

**TTS (Text-to-Speech):** Cartesia Sonic-3 (default, ~90ms latency). Set `CARTESIA_API_KEY` and `CARTESIA_VOICE_ID` in `.env`. Alternatives: `TTS_BACKEND=elevenlabs` or `TTS_BACKEND=local` (Kokoro, free/offline).

### Enabling Screen Capture

Screen capture sends MSFS screenshots to Claude Vision for instrument and environment reads. It is disabled by default.

```bash
# In .env
SCREEN_CAPTURE_ENABLED=true
SCREEN_CAPTURE_INTERVAL=2.0   # seconds between captures
```

Or toggle it at runtime:

```
Captain> /capture
Screen capture enabled.
```

Screen capture works best when running the orchestrator natively on Windows (not inside Docker or WSL), since it uses `mss` to grab the primary monitor.

---

## What's New in v2

- **Streaming voice pipeline** — Deepgram Nova-3 STT + Cartesia Sonic-3 TTS (~90ms TTFB), replacing batch Whisper + ElevenLabs
- **6 new aviation tools** — NOTAM, METAR/TAF, ADS-B traffic, charts, performance calculator, airspace info
- **Safety layer** — Emergency fast paths that bypass the LLM, V-speed validation, telemetry sanity checks
- **Smart LLM** — Dynamic temperature by flight phase, Haiku/Sonnet model routing, rolling conversation summary
- **Upgraded RAG** — Aviation-aware semantic chunking, cross-encoder re-ranking, enhanced metadata
- **TTS preprocessor** — 6 new ICAO transformations (millibars, ATIS letters, transponder modes, bearings, Zulu time, temperature)

See [Migration Guide](MIGRATION_V1_V2.md) for details on what changed from v1.
