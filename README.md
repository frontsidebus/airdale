# Airdale

**MERLIN** -- Your AI Co-Pilot for Microsoft Flight Simulator 2024

> *"Airdale" is Navy slang for a naval aviator. Fitting, because MERLIN flies right seat.*

MERLIN is a voice-interactive AI co-pilot powered by [Claude](https://www.anthropic.com/claude) that connects to Microsoft Flight Simulator 2024 via SimConnect. It provides real-time flight guidance, checklist management, and situational awareness -- delivered with the personality of a Navy Test Pilot who has seen it all and isn't impressed.

---

## Architecture

```
+------------------+        SimConnect         +---------------------+
|                  | <-----------------------> |                     |
|   MSFS 2024      |     (Telemetry + Events)  |  SimConnect Bridge  |
|                  |                           |       (C# .NET 8)   |
+------------------+                           +----------+----------+
                                                          |
                                                     WebSocket
                                                     (JSON/live)
                                                          |
                                               +----------+----------+
                                               |                     |
                                               |    Orchestrator     |
                                               |      (Python)       |
                                               |                     |
                                               +--+-----+-----+--+--+
                                                  |     |     |  |
                                     +------------+  +--+--+  |  +------------+
                                     |               |     |  |               |
                                +----+----+    +-----+--+  |  |   +----------+--+
                                |  Claude |    |  Voice  |  |  |   |   Context   |
                                |   API   |    | Pipeline|  |  |   |    Store    |
                                | (Tools) |    | STT/TTS |  |  |   | (ChromaDB)  |
                                +---------+    +--------+   |  |   +-------------+
                                                            |  |
                                                     +------+  +-------+
                                                     |                 |
                                                +----+-----+   +------+------+
                                                | FAA Data |   |   Screen    |
                                                | Service  |   |   Capture   |
                                                +----------+   +-------------+
```

---

## Key Features

- **Real-time telemetry awareness** -- MERLIN sees your airspeed, altitude, attitude, engine params, and control surfaces as they change
- **Voice interaction** -- Talk to your co-pilot naturally using Whisper STT and ElevenLabs TTS
- **Claude-powered situational analysis** -- Tool-using AI that reasons about your flight state and provides contextual guidance
- **RAG-based flight manual lookup** -- Aircraft POH and flight manuals chunked and embedded for instant retrieval
- **FAA airport data integration** -- Live airport frequencies, runway info, and procedures pulled by ICAO code
- **Phase-aware checklists** -- Automatic flight phase detection (taxi, takeoff, cruise, approach, landing) with appropriate checklists
- **Optional screen capture** -- Send the sim's visual output to Claude Vision for instrument and situational reads
- **Flight plan creation** -- Route planning with fuel calculations and weather integration

---

## Components

| Component | Language | Purpose |
|---|---|---|
| **SimConnect Bridge** | C# / .NET 8 | Out-of-process bridge that maintains a persistent SimConnect session and streams telemetry over WebSocket |
| **Orchestrator** | Python 3.11+ | Core brain -- manages conversation, assembles context, dispatches Claude tool calls, coordinates all subsystems |
| **Voice Pipeline** | Python | Whisper for speech-to-text, ElevenLabs for text-to-speech with streaming playback |
| **Context Store** | Python + ChromaDB | Vector store for aircraft manuals, procedures, and reference documents |
| **FAA Data Service** | Python | Thin service for airport lookups via NASR dataset and aviation APIs |

---

## Prerequisites

- **Microsoft Flight Simulator 2024** with the SDK installed
- **.NET 8 SDK** ([download](https://dotnet.microsoft.com/download/dotnet/8.0))
- **Python 3.11+** ([download](https://www.python.org/downloads/))
- **API Keys:**
  - [Anthropic API key](https://console.anthropic.com/) (Claude)
  - [ElevenLabs API key](https://elevenlabs.io/) (TTS)
- **Audio hardware** -- Microphone for voice input, speakers/headset for MERLIN's responses

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/frontsidebus/airdale.git
cd airdale
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys and preferences
```

### 3. Start the SimConnect Bridge

```bash
cd simconnect-bridge
dotnet restore
dotnet run
```

The bridge will connect to MSFS 2024 and begin serving telemetry on `ws://localhost:8765`.

### 4. Start the Orchestrator

```bash
cd orchestrator
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
merlin
```

### 5. Start talking

Once both components are running and MSFS is active, MERLIN is listening. Say something like:

> "MERLIN, what's our current altitude and airspeed?"

---

## Configuration

All configuration is managed through environment variables. Copy `.env.example` to `.env` and fill in your values:

```bash
# Core API keys
ANTHROPIC_API_KEY=sk-ant-...
ELEVENLABS_API_KEY=...

# SimConnect bridge
SIMCONNECT_WS_HOST=localhost
SIMCONNECT_WS_PORT=8765

# Voice settings
ELEVENLABS_VOICE_ID=...
WHISPER_MODEL=base.en

# See .env.example for all options
```

---

## Roadmap

### Phase 1 -- Proof of Concept
SimConnect bridge reading basic telemetry, hardcoded context with Claude API, text responses to console. Prove the sim-to-Claude pipeline works end to end.

### Phase 2 -- Voice Loop
Add Whisper STT and ElevenLabs TTS. Conversational interaction with MERLIN via voice. Basic context injection from telemetry.

### Phase 3 -- Tool Use + RAG
Implement Claude tool calling (`get_sim_state`, `lookup_airport`, `search_manual`). Stand up ChromaDB with the first aircraft manual. Add FAA airport lookups.

### Phase 4 -- Situational Awareness
Flight phase detection derived from telemetry. Proactive callouts for altitude, speed, and configuration. Checklist integration tied to flight phase.

### Phase 5 -- Vision
Screen capture pipeline sending frames to Claude Vision. MERLIN can read instruments and observe the outside environment. Selective activation during critical phases.

### Phase 6 -- Flight Planning
Full flight plan creation with route building, fuel calculations, and weather integration. End-to-end mission support from preflight to shutdown.

---

## Meet MERLIN

A sample interaction during approach into KJFK:

```
You:     MERLIN, we're about 30 miles out from Kennedy. What do I need to know?

MERLIN:  Alright Captain, let me pull up the picture. KJFK is currently running
         ILS 22L approaches. Winds are 210 at 14 gusting 22, so expect some
         chop on short final -- nothing that'll ruin your day, but keep your
         speed up. Altimeter 29.82.

         Your approach checklist: flaps need to come to 15, gear stays up until
         we're established on the localizer, and I'd like to see you slowing
         through 180 knots by the outer marker. Right now we're at 4,200 feet
         doing 240 -- so we've got some work to do.

         Also, I notice you still haven't tuned the ILS frequency. It's 111.5
         for 22L. I'd handle it myself, but they only gave me read access.
         Something about "trust issues."

You:     Okay, ILS is tuned. Starting to configure.

MERLIN:  111.5 on NAV1, confirmed. There we go. Flaps to 15... I see them
         moving. Gear is still up, that's correct for now. Speed is coming
         back through 210.

         One more thing -- tower frequency for JFK is 119.1, and you'll want
         that dialed in before we hit the marker. I'd hate for us to arrive
         unannounced. That's more of a surprise party move than a landing move.
```

---

## Project Structure

```
airdale/
├── orchestrator/           # Python orchestration layer
│   ├── orchestrator/       # Package source
│   │   ├── config.py       # Settings and environment config
│   │   ├── sim_client.py   # WebSocket client for SimConnect bridge
│   │   └── ...
│   └── pyproject.toml      # Python project config (hatch + ruff)
├── simconnect-bridge/      # C# .NET SimConnect bridge
│   ├── Models/
│   │   └── SimState.cs     # Telemetry data model
│   └── SimConnectBridge.csproj
├── .env.example            # Environment variable template
├── CLAUDE.md               # Project conventions for Claude Code
└── README.md               # This file
```

---

## Contributing

Contributions are welcome. Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes with tests where applicable
4. Ensure `ruff check` passes for Python code
5. Submit a pull request with a clear description

For large changes, open an issue first to discuss the approach.

---

## License

[MIT](LICENSE) -- Copyright 2026 frontsidebus
