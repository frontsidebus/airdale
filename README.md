# MERLIN

**AI Co-Pilot for Microsoft Flight Simulator 2024**

MERLIN is a voice-interactive AI co-pilot powered by [Claude](https://www.anthropic.com/claude) that connects to MSFS 2024 via SimConnect. Talk naturally to control your aircraft, get real-time flight guidance, and manage procedures -- delivered with the personality of a Navy Test Pilot who has seen it all.

> *"Airdale" is Navy slang for a naval aviator. Fitting, because MERLIN flies right seat.*

---

## What MERLIN Can Do

**Voice-Commanded Aircraft Control** -- Say "gear down" or "give me full flaps" and MERLIN executes immediately. 20 controllable systems, 72+ actions including flaps, gear, autopilot, throttle, lights, magnetos, fuel selector, trim, deice, and more. See [Aircraft Controls Reference](docs/AIRCRAFT_CONTROLS.md).

**Real-Time Flight Awareness** -- Automatic flight phase detection (preflight through rollout) drives checklists, response style, and proactive callouts. MERLIN adapts: terse during takeoff, conversational during cruise.

**Aviation Intelligence** -- 6 built-in tools for NOTAMs, METAR/TAF weather, ADS-B traffic, approach charts, performance calculations, and airspace info. RAG-powered manual lookup with aviation-aware semantic chunking.

**Safety Layer** -- Emergency fast-path detection bypasses the LLM for engine failures, fires, and decompression. V-speed cross-referencing catches hallucinated numbers. Telemetry sanity checks protect against bad data.

**Low-Latency Voice** -- Deepgram Nova-3 streaming STT (~300ms) with aviation keyword boosting. Cartesia Sonic-3 TTS (~90ms time-to-first-byte). Barge-in interruption support.

---

## Architecture

```
 MSFS 2024 ──SimConnect──> MSFS Adapter (C#) ──WebSocket──> Telemetry Service
                                                                    |
 Browser UI <──WebSocket──> Web Server (FastAPI) <──────────────────┘
      |                         |        |
      |                    Claude API    ChromaDB
      |                   (tool use)    (RAG store)
      |                         |
      └── Deepgram STT    Cartesia TTS
          (streaming)      (~90ms TTFB)
```

Commands flow bidirectionally: voice in through Deepgram, Claude decides and calls tools, aircraft control commands route through the telemetry service to the SimConnect bridge, and confirmations stream back through Cartesia TTS.

---

## Quick Start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) with WSL2 backend
- [.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0) (Windows, for the SimConnect bridge)
- Microsoft Flight Simulator 2024 with the SDK installed
- Python 3.11+
- API keys: [Anthropic](https://console.anthropic.com/) (required), [Deepgram](https://console.deepgram.com/) (STT), [Cartesia](https://play.cartesia.ai/) (TTS)

### 1. Clone and configure

```bash
git clone https://github.com/frontsidebus/airdale.git
cd airdale
cp .env.example .env
# Edit .env with your API keys (ANTHROPIC_API_KEY, DEEPGRAM_API_KEY, CARTESIA_API_KEY)
# Also set CARTESIA_VOICE_ID (browse voices at play.cartesia.ai)
```

### 2. Start everything

```bash
./scripts/start.sh
```

Or test without MSFS running:

```bash
./scripts/start.sh --mock
```

### 3. Open the cockpit UI

Navigate to [http://localhost:3838](http://localhost:3838). MERLIN is ready.

### 4. Verify

```bash
./scripts/healthcheck.sh
```

To stop:

```bash
./scripts/stop.sh
```

<details>
<summary>Manual startup (without script)</summary>

```bash
# Docker services (ChromaDB + telemetry service)
docker compose up -d chromadb telemetry-service

# SimConnect bridge (Windows terminal)
cd adapters/msfs
dotnet run

# Web server (WSL)
cd web
source ../orchestrator/.venv/bin/activate
python run.py
```

</details>

---

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestrator | Python 3.11+ / FastAPI (async) |
| SimConnect Bridge | C# / .NET 8 (out-of-process, event-driven) |
| AI Inference | Anthropic Claude API with tool use |
| Speech-to-Text | Deepgram Nova-3 (streaming WebSocket) |
| Text-to-Speech | Cartesia Sonic-3 (~90ms TTFB) |
| Vector Store / RAG | ChromaDB with semantic chunking + cross-encoder re-ranking |
| Telemetry Hub | Python / FastAPI (adapter ↔ consumer routing) |
| IPC | WebSocket (JSON) throughout |
| Frontend | HTML/JS cockpit display |
| Config | pydantic-settings with .env |

**Fallback options:** Whisper (local STT), ElevenLabs (cloud TTS), Kokoro (local TTS)

---

## Project Structure

```
airdale/
├── orchestrator/               # Python orchestration package (the brain)
│   ├── orchestrator/
│   │   ├── claude_client.py    # Claude API with MERLIN persona + tool use
│   │   ├── tools.py            # Tool implementations (sim control, airport lookup, etc.)
│   │   ├── aviation_tools.py   # NOTAM, METAR, ADS-B, charts, performance, airspace
│   │   ├── emergency.py        # Emergency fast-path detection and response
│   │   ├── validation.py       # V-speed cross-referencing, telemetry sanity checks
│   │   ├── chunking.py         # Aviation-aware semantic document chunking
│   │   ├── reranker.py         # Cross-encoder re-ranking for RAG
│   │   ├── stt/                # STT backends (Deepgram, Whisper)
│   │   ├── tts/                # TTS backends (Cartesia, ElevenLabs, Kokoro)
│   │   └── ...
│   └── tests/                  # 619 tests
├── web/                        # FastAPI web server + browser cockpit UI
├── telemetry-service/          # Universal telemetry hub (adapter ↔ consumer)
├── adapters/msfs/              # C# SimConnect bridge (.NET 8)
├── data/
│   ├── checklists/             # YAML checklists (single-engine, jet)
│   └── prompts/                # MERLIN persona and emergency prompts
├── tools/
│   ├── mock_adapter.py         # Mock MSFS adapter for testing without sim
│   └── ingest.py               # Document ingestion into ChromaDB
├── scripts/
│   ├── start.sh                # Start all components (supports --mock)
│   ├── stop.sh                 # Graceful shutdown
│   └── healthcheck.sh          # Verify all subsystems
├── docs/                       # Documentation
│   ├── ARCHITECTURE.md         # System design and data flows
│   ├── AIRCRAFT_CONTROLS.md    # Complete control reference (20 systems, 72+ actions)
│   ├── VOICE_PIPELINE.md       # STT/TTS streaming architecture
│   ├── SAFETY.md               # Emergency detection, validation, timeouts
│   ├── AVIATION_TOOLS.md       # NOTAM, METAR, ADS-B, charts, performance
│   ├── RAG_SYSTEM.md           # Semantic chunking, re-ranking, metadata
│   ├── CONFIGURATION.md        # Complete env var reference
│   ├── TESTING.md              # Mock adapter, test suite, command testing
│   ├── MIGRATION_V1_V2.md      # v1 → v2 migration guide
│   ├── GETTING_STARTED.md      # First flight walkthrough
│   └── INSTALL.md              # Installation guide
├── .env.example                # Environment variable template
├── docker-compose.yml          # Production services
└── CLAUDE.md                   # Project conventions for AI assistants
```

---

## Documentation

| Document | Description |
|---|---|
| [Getting Started](docs/GETTING_STARTED.md) | First flight walkthrough |
| [Installation](docs/INSTALL.md) | Full setup with troubleshooting |
| [Architecture](docs/ARCHITECTURE.md) | System design and data flows |
| [Aircraft Controls](docs/AIRCRAFT_CONTROLS.md) | Every system and action MERLIN can control |
| [Voice Pipeline](docs/VOICE_PIPELINE.md) | STT/TTS streaming, barge-in, latency |
| [Safety](docs/SAFETY.md) | Emergency detection, validation, timeouts |
| [Aviation Tools](docs/AVIATION_TOOLS.md) | NOTAM, weather, traffic, charts, performance |
| [RAG System](docs/RAG_SYSTEM.md) | Semantic chunking, re-ranking, ingestion |
| [Configuration](docs/CONFIGURATION.md) | Complete env var reference |
| [Testing](docs/TESTING.md) | Mock adapter, test suite, command testing |
| [Migration v1→v2](docs/MIGRATION_V1_V2.md) | Breaking changes and upgrade guide |
| [Project Conventions](CLAUDE.md) | Code style, architecture decisions |

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Ensure `ruff check` passes for Python code
4. Run tests: `cd orchestrator && pytest`
5. Submit a pull request with a clear description

---

## License

[MIT](LICENSE) -- Copyright 2026 frontsidebus
