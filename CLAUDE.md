# CLAUDE.md -- Project Conventions for Airdale (MERLIN)

## Project Overview

**Airdale** (codename) is an AI co-pilot called **MERLIN** for flight simulators and vehicle sims. It uses a pluggable adapter architecture: per-sim adapters connect to game SDKs and push telemetry to a universal telemetry service, which feeds the orchestrator. Currently supports MSFS 2024, with an architecture designed for X-Plane, DCS, and other sims. The MERLIN persona is a Navy Test Pilot with encyclopedic aviation knowledge and dry humor.

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestrator | Python 3.11+ (async, hatch build system) |
| Web Server | FastAPI with WebSocket support (browser UI) |
| Telemetry Service | Python / FastAPI (universal hub for sim adapters) |
| MSFS Adapter | C# / .NET 8 (out-of-process exe, event-driven message pump) |
| AI Inference | Anthropic Claude API with tool use |
| Vector Store / RAG | ChromaDB with sentence-transformers embeddings, cross-encoder re-ranking, semantic chunking |
| Speech-to-Text | Pluggable via `stt_backend`: Deepgram (cloud streaming, **default**) or faster-whisper `large-v3-turbo` (local batch, via Docker) |
| Text-to-Speech | Pluggable via `tts_backend`: Cartesia (**default**), ElevenLabs, or local Kokoro |
| Voice Activity Detection | Silero VAD (neural), with RMS-threshold fallback when torch is absent |
| IPC | WebSocket (JSON) between adapters, telemetry service, and consumers |
| Config | pydantic-settings with .env files |

Both STT and TTS are selected by config behind protocols (`stt/base.py`,
`tts/base.py`) with factories (`create_stt_client`, `create_tts_client`). Adding
a backend means adding a module and a factory branch — never touching consumers.
See "Voice backends" under Architectural Decisions.

## Directory Structure

```
airdale/
├── telemetry-service/           # Universal telemetry hub
│   ├── telemetry/               # Python package
│   │   ├── schema.py            # Universal data models (TelemetryEnvelope)
│   │   ├── adapter_protocol.py  # Adapter ↔ service message types
│   │   ├── adapter_manager.py   # Adapter tracking and consumer broadcast
│   │   ├── service.py           # FastAPI app (/ws/ingest + /ws/telemetry)
│   │   └── config.py            # Service configuration
│   ├── tests/                   # Service tests
│   ├── pyproject.toml
│   └── Dockerfile
├── adapters/                    # Per-sim adapter apps
│   ├── msfs/                    # MSFS 2024 adapter (C# .NET 8)
│   │   ├── Models/
│   │   │   ├── SimDataStructs.cs    # SimConnect data structure definitions
│   │   │   └── SimState.cs          # Internal telemetry data model
│   │   ├── SimConnectBridge.Tests/  # xUnit tests
│   │   ├── SimConnectManager.cs     # Event-driven SimConnect message pump
│   │   ├── TelemetryServiceClient.cs # WS client pushing to telemetry service
│   │   ├── Program.cs               # Entry point
│   │   ├── SimConnectBridge.csproj
│   │   └── appsettings.json
│   └── README.md                # How to write a new adapter
├── orchestrator/                # Python package -- the brain
│   ├── orchestrator/            # Source package
│   │   ├── __init__.py
│   │   ├── main.py              # CLI entry point
│   │   ├── config.py            # Pydantic settings from .env
│   │   ├── claude_client.py     # Anthropic API wrapper with MERLIN persona + tools
│   │   ├── sim_client.py        # Telemetry client, models, health monitor
│   │   ├── flight_phase.py      # State-machine flight phase detector
│   │   │
│   │   ├── tools.py             # Claude tool implementations (incl. set_aircraft_control)
│   │   ├── aviation_tools.py    # NOTAM, METAR/TAF, ADS-B, charts, performance, airspace
│   │   │
│   │   ├── authority.py         # Authority level + reason; the state every guard reads
│   │   ├── command_safety.py    # PRE-execution safety rules; gates the write path
│   │   ├── command_verifier.py  # POST-execution telemetry confirmation
│   │   ├── command_history.py   # Recent commands + generated undo actions
│   │   ├── override_detector.py # Drops authority on unattributed telemetry movement
│   │   ├── procedures.py        # Multi-step compound command execution
│   │   │
│   │   ├── proactive_monitor.py # Unified telemetry evaluation (callouts+deviations+emergency)
│   │   ├── callouts.py          # Aviation callout engine (V1, rotate, minimums)
│   │   ├── deviation_monitor.py # Phase-aware deviation rules and alerts
│   │   ├── checklist_manager.py # Interactive checklists driven by phase transitions
│   │   ├── emergency.py         # Emergency detection; pre-validated LLM-bypass responses
│   │   ├── validation.py        # Validates Claude's V-speeds/altitudes/frequencies
│   │   │
│   │   ├── context_store.py     # ChromaDB RAG store with query cache
│   │   ├── chunking.py          # Structure-aware semantic chunking
│   │   ├── reranker.py          # Cross-encoder two-stage retrieval
│   │   │
│   │   ├── voice.py             # Voice I/O (PTT, VAD, barge-in, playback)
│   │   ├── audio_processing.py  # Preprocessing (high-pass, trim, normalize) + AVIATION_PROMPT
│   │   ├── whisper_client.py    # Whisper ASR HTTP client with retry logic
│   │   ├── tts_preprocessor.py  # ICAO-compliant aviation text preprocessing for TTS
│   │   ├── screen_capture.py    # Optional screen capture for vision analysis
│   │   │
│   │   ├── stt/                 # Speech-to-text backends behind STTClient
│   │   │   ├── base.py          # STTClient protocol + TranscriptionResult
│   │   │   ├── __init__.py      # create_stt_client factory + aviation_keywords()
│   │   │   ├── deepgram.py      # Cloud streaming backend
│   │   │   └── whisper_adapter.py # Adapts batch WhisperClient onto the protocol
│   │   ├── tts/                 # Text-to-speech backends behind TTSClient
│   │   │   ├── base.py          # TTSClient protocol
│   │   │   ├── __init__.py      # create_tts_client factory
│   │   │   ├── cartesia.py      # Low-latency cloud backend
│   │   │   ├── elevenlabs.py    # Cloud backend with native WS streaming
│   │   │   └── kokoro.py        # Local backend
│   │   ├── turn/                # End-of-turn detection behind TurnDetector
│   │   │   ├── base.py          # TurnDetector protocol + TurnDecision
│   │   │   ├── __init__.py      # create_turn_detector factory
│   │   │   ├── silence.py       # Fixed-silence threshold (fallback, no deps)
│   │   │   ├── smart_turn.py    # Semantic detection via Smart Turn v3 ONNX
│   │   │   └── features.py      # Whisper log-mel in numpy (pinned to golden values)
│   │   └── eval/                # Offline evaluation; NOT imported by runtime code
│   │       ├── aviation_wer.py  # Aviation-weighted ASR scoring (WER/CTER/value-recall)
│   │       ├── audio_augment.py # Cockpit/VHF channel simulation + SNR mixing
│   │       └── corpus.py        # Corpus loading (manifest, paired-dir) + WAV I/O
│   ├── tests/                   # Unit tests (pytest + pytest-asyncio)
│   ├── Dockerfile
│   └── pyproject.toml           # Build config, dependencies, ruff settings
├── web/                         # FastAPI web UI server
│   ├── server.py                # Backend: telemetry WS, chat, STT/TTS proxy
│   ├── run.py                   # Dev server launcher
│   ├── requirements.txt
│   └── static/                  # Browser frontend
│       ├── index.html           # TARS-style cockpit display
│       ├── app.js               # WebSocket client, audio capture, UI logic
│       └── style.css
├── data/
│   ├── checklists/              # YAML checklist files (generic_single_engine, etc.)
│   ├── eval/                    # Evaluation fixtures
│   │   └── aviation_stt_corpus.yaml  # Reference phrases for STT backend gating
│   └── prompts/                 # System prompt templates
│       ├── merlin_system.md     # MERLIN persona definition
│       └── merlin_emergency.md  # Emergency procedure prompt overlay
├── tests/                       # Integration tests (root level)
│   └── integration/             # End-to-end, WebSocket, tool chain, Whisper pipeline
├── tools/                       # Developer utilities
│   ├── download_faa_data.py     # FAA data fetcher for RAG ingestion
│   ├── ingest.py                # Document ingestion into ChromaDB
│   ├── mock_adapter.py          # Simulates the MSFS adapter; test without the sim
│   ├── fetch_turn_model.py      # Download the Smart Turn model (enables semantic turns)
│   ├── gen_stt_corpus.py        # Synthesize + degrade an STT eval corpus via TTS
│   ├── stt_bench.py             # Gate STT backend swaps on aviation-term WER
│   └── test_tts.py              # TTS smoke test
├── docs/                        # Project documentation
│   ├── ARCHITECTURE.md          # System design and data flows
│   ├── API.md                   # WebSocket protocol reference
│   ├── AIRCRAFT_CONTROLS.md     # Supported control systems and SimConnect mapping
│   ├── SMART_CONTROLS.md        # Command safety severity model and rule reference
│   ├── SAFETY.md                # Emergency fast paths and numerical validation
│   ├── PROACTIVE_COPILOT.md     # Callouts, deviation alerts, checklist automation
│   ├── AVIATION_TOOLS.md        # NOTAM/METAR/ADS-B tool reference
│   ├── RAG_SYSTEM.md            # Retrieval, chunking, re-ranking
│   ├── VOICE_PIPELINE.md        # STT/TTS backends, VAD, barge-in
│   ├── CONFIGURATION.md         # Full config field reference
│   ├── TESTING.md               # Test layout and conventions
│   ├── MIGRATION_V1_V2.md       # v1 -> v2 architecture migration notes
│   ├── GETTING_STARTED.md
│   └── INSTALL.md
├── docker-compose.yml           # Production service stack
├── docker-compose.dev.yml       # Dev overrides (hot-reload, bind mounts)
├── .env.example                 # Environment variable template
├── .env                         # Local config (git-ignored)
└── CLAUDE.md                    # This file
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

# Run the orchestrator (CLI mode)
merlin

# Lint
ruff check .

# Format
ruff format .

# Run tests
pytest
```

### Web UI Server

```bash
cd web

# Install dependencies (or use the orchestrator venv)
pip install -r requirements.txt

# Run the FastAPI dev server (defaults to http://localhost:3838)
python run.py
```

### Telemetry Service

```bash
cd telemetry-service

# Install
pip install -e ".[dev]"

# Run the service
uvicorn telemetry.service:app --host 0.0.0.0 --port 8080

# Run tests
pytest
```

### MSFS Adapter (C#)

```bash
cd adapters/msfs

# Restore and build
dotnet restore
dotnet build

# Run (MSFS must be running, telemetry service must be up)
dotnet run

# Run tests
dotnet test
```

### Docker Services

```bash
# Start all services (Whisper, ChromaDB, orchestrator)
docker compose up -d

# Dev mode with hot-reload and bind mounts
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# View logs
docker compose logs -f orchestrator

# Rebuild after dependency changes
docker compose build --no-cache orchestrator
```

### WSL2 Note

When running in WSL2, sim adapters run on the Windows host. Set the telemetry service URL accordingly:

```bash
# In .env
TELEMETRY_SERVICE_HOST=host.docker.internal   # Docker
TELEMETRY_SERVICE_HOST=$(hostname).local       # WSL2 native
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

1. **Pluggable adapter architecture** -- Each sim has its own small adapter app that connects to the game's SDK and pushes telemetry to a universal telemetry service. This decouples sim-specific code from the orchestrator and makes it easy to add new sims.

2. **Universal telemetry service** -- The `telemetry-service/` is a Python/FastAPI hub with two WebSocket endpoints: `/ws/ingest` (adapters push here) and `/ws/telemetry` (consumers subscribe here). It handles adapter registration, state broadcasting, and consumer field subscriptions.

3. **Sim adapters are out-of-process** -- The MSFS adapter runs as a separate .exe (Microsoft's recommendation for SimConnect stability). Future adapters can be in any language — they just need to push JSON to the ingest WebSocket.

4. **Event-driven SimConnect message pump** -- The MSFS adapter uses an `EventWaitHandle`-based message pump instead of timer-based polling. SimConnect signals the event when data is ready; the pump thread calls `ReceiveMessage()` in response. This eliminates the 0x80004005 COM errors caused by unsynchronized timer polling.

5. **WebSocket for IPC** -- All components communicate over WebSocket with JSON payloads. This keeps everything language-agnostic and independently deployable.

5. **Bidirectional command protocol** -- The telemetry service routes commands from consumers (orchestrator) to adapters, with acknowledgment tracking. Commands flow: `ConsumerCommand` → `ServiceCommand` → adapter executes → `AdapterCommandAck` → `ServiceCommandAck`. This enables MERLIN to control aircraft systems via SimConnect's `TransmitClientEvent`.

6. **Claude tool use for actions** -- The orchestrator defines tools (`get_sim_state`, `lookup_airport`, `search_manual`, `get_checklist`, `create_flight_plan`, `set_aircraft_control`) that Claude calls mid-response. The `set_aircraft_control` tool translates human-friendly system/action/value parameters to SimConnect events. Do not pre-fetch everything into the context window.

6. **Dynamic token budgeting** -- Three tiers: 256 tokens for short acknowledgments (roger, thanks, simple questions); `claude_max_tokens` (1024) for routine cockpit comms; `claude_max_tokens_briefing` (2048) for briefings, checklists, and flight plans. This keeps responses tactical during high-workload phases.

7. **Flight-phase-aware response styles** -- Each flight phase injects a style directive into the system prompt (e.g., PREFLIGHT allows banter; TAKEOFF demands brevity). The `FlightPhaseDetector` uses a state machine with hysteresis (3 consecutive detections before transition) to prevent oscillation.

8. **Flight phase is derived from telemetry** -- The orchestrator infers the current phase (preflight, taxi, takeoff, climb, cruise, descent, approach, landing, landed) from sim state. This drives checklist selection and proactive callouts.

9. **Voice is streaming** -- TTS begins playing as Claude's response streams in. Do not wait for the full response before starting audio playback.

10. **TTS text sanitizer** -- Claude responses are sanitized before TTS synthesis to strip markdown formatting, special characters, and other tokens that produce garbled speech output.

11. **Audio preprocessing pipeline** -- Incoming microphone audio passes through a high-pass filter, silence trimming, and normalization before being sent to Whisper. This improves transcription accuracy in noisy cockpit environments.

12. **Aviation vocabulary prompting for Whisper** -- An `initial_prompt` containing aviation terms (ATIS, METAR, squawk, NATO phonetic alphabet, etc.) biases Whisper toward recognizing aviation terminology without restricting its output.

13. **Barge-in / interruption support** -- If the user sends new audio or text while MERLIN is responding, the current Claude stream and TTS pipeline are cancelled immediately. The web server manages cancellation tokens per-client.

14. **Delta detection for telemetry deduplication** -- The `TelemetryClient` tracks previous state and only fires update callbacks when telemetry values actually change, reducing unnecessary processing.

15. **Query cache for ChromaDB** -- The `ContextStore` uses a TTL-based cache (60s default) keyed by query text, result count, and filter hash. Within a single flight phase, relevant documents rarely change, so this avoids redundant round-trips to ChromaDB.

16. **faster-whisper over stock Whisper** -- CTranslate2 backend is 3-4x faster with identical accuracy. Uses `large-v3-turbo`, which is both more accurate and roughly 3x faster than `medium`. Dev compose overrides to `tiny` for startup time.

17. **Silero VAD over RMS threshold** -- Neural voice activity detection reduces silence timeout from 1.5s to 400ms, making voice interaction feel snappy without cutting off speech.

18. **ElevenLabs WebSocket streaming** -- Single persistent WebSocket connection per response instead of per-sentence REST calls. Eliminates connection overhead and enables lower time-to-first-byte for TTS audio.

19. **TTS phrase caching** -- Common responses (e.g., "Roger.", "Copy that.") are pre-generated at startup and served from an in-memory cache for zero-latency playback.

20. **Aviation TTS preprocessor** -- Converts LLM output into speakable text following ICAO phraseology: digit-by-digit pronunciation for flight levels, headings, frequencies, runway designators, and squawk codes.

21. **Voice backends behind protocols** -- STT and TTS are selected by `stt_backend` / `tts_backend` config. Each has a protocol (`stt/base.py`, `tts/base.py`), one module per backend, and a factory. Consumers hold the protocol, never a provider: `VoiceOutput` takes a `TTSClient` and contains no URLs, credentials, or voice settings. Adding a backend means a module plus a factory branch, and requires adding a branch to `Settings.tts_configured` / `voice_id` too — `SUPPORTED_BACKENDS` exists to keep those in sync. This abstraction was silently reverted once (`a1b508a`) and went undetected for four months; `test_voice.py` now carries structural guards against a repeat.

22. **Safety layers are independent of the LLM** -- Three separate guards, none of which depend on Claude behaving well. `command_safety.py` validates proposed commands against live telemetry *before* execution (`blocked` stops it, `warning` proceeds with an advisory). `command_verifier.py` polls telemetry *after* to confirm the aircraft actually changed. `validation.py` scans Claude's response text for V-speeds, altitudes, and frequencies against per-aircraft limits. `emergency.py` bypasses the LLM entirely for time-critical conditions. **The pre-execution guard now covers the fuel selector, mixture, crossfeed, parking brake and spoilers in addition to gear, flaps, autopilot master and throttle** — `DEFAULT_RULES` went 7 to 13 to 15. It grew because CMD-07 registered eight previously-NACKing events in the adapter's `CommandMap`, turning a refusal into a real `TransmitClientEvent`: a rule set that does not track the reachable surface is a guard in name only, and `assisted` cannot withhold what no rule ever flagged. **That failure mode is now structural rather than remembered** — `test_every_reachable_command_is_ruled_or_classified` requires every enum-reachable event to be ruled, exempt with a stated reason, or declared as debt, so widening the command surface without a safety decision fails CI. It found `GEAR_TOGGLE` reachable with no rule at all while `GEAR_UP` was blocked on the ground, which is the same blind-toggle shape as `parking_brake`. This is the primary reason the cascade architecture is retained over speech-to-speech — see `.planning/TECH-STACK-REVIEW.md`.

23. **Semantic turn detection gated by acoustic VAD** -- Silero VAD finds *candidate* endpoints cheaply and decides *when* to ask; the `TurnDetector` decides *whether* the turn is actually over. Without that gate a semantic model would run on every 1024-sample chunk. Smart Turn v3 reads the waveform (not a transcript), so it works identically on the local and streaming paths. Fixed-silence detection remains as the always-available fallback: a threshold short enough to feel responsive cuts off mid-sentence pauses, and aviation phraseology is full of them ("descend and maintain... one zero thousand").

24. **Synthetic eval audio is for regression and curves, never for thresholds** -- `tools/gen_stt_corpus.py` can generate the whole STT corpus via TTS, which is reproducible and free. But clean TTS is studio-quality, so every backend scores near-perfect and the gate stops discriminating; and synthetic speech is widely used as ASR training augmentation, which can flatter cloud backends over local ones. Use it for CI regression and for SNR *degradation curves* (relative shape is robust even when absolute numbers are not). Set thresholds from real speech: a public ATC corpus via `--paired-dir`, or your own recordings.

25. **Aviation-term WER over published WER** -- STT backend swaps are gated on `orchestrator/eval/aviation_wer.py`, which reports critical-token error rate and value recall alongside standard WER. Published leaderboard WER is dominated by conversational filler and cannot distinguish a backend that drops "uh" from one that hears "one zero thousand" as "one thousand". Run `tools/stt_bench.py` before changing STT.

26. **Authority layer -- how much MERLIN may do, and why** -- `authority.py` holds one `AuthorityState` per process, selected by `AUTHORITY_LEVEL`. Three levels: `advisory` transmits nothing and describes what it would have done, `assisted` executes unless `command_safety` flags the command `warning`, `full` executes unless `command_safety` blocks it outright. **The policy gate lives inside `set_aircraft_control`** -- the single point where the resolved SimConnect event, live telemetry and the safety verdict all exist and nothing has been transmitted yet. **A second, level-only floor sits in `TelemetryClient.send_command`**, re-reading the level at the instant of dispatch and refusing everything at `advisory`; it exists because "remember to add the check at each call site" already failed once in this exact code path, and `procedures.py` bypassed `command_safety` for months as a result. **The consecutive-ack-timeout watchdog counter must increment inside `send_command`**, not be inferred from a return value: the tool layer's own `asyncio.wait_for` starts first, so `authority_tool_timeout_s` must exceed `authority_command_timeout_s + authority_verify_timeout_s` or a genuine ack timeout is cancelled as a tool timeout and the watchdog never sees it (enforced by a `Settings` validator at startup and pinned by a structural test). **Authority carries a reason as well as a level** -- `config`, `override`, `watchdog`, `degraded` -- so "deferring to the pilot", "cannot reach the sim" and "the authority subsystem failed to start" stay distinguishable instead of all rendering as a deliberate `advisory`. **Both entry points fail toward less authority**: the CLI lets a construction failure propagate and refuses to start, because a swallowed exception would leave `authority = None`, which every gate reads as `full`; the web `lifespan` substitutes a degraded, advisory-only state instead, since a browser server cannot usefully abort. Different mechanism, same guarantee -- a wiring or construction failure can never *grant* authority.

**One predicate decides whether a command was transmitted.** `tools.py::_was_transmitted` is `bool(result.get("success")) and "error" not in result`, and `web/server.py::_on_tool_result` uses the identical expression because the same tool result crosses both surfaces. Both halves are load-bearing: a negative adapter ack is `{"success": False, "message": ...}` with **no** `error` key, which `sim_client.send_command` documents as routine, while the authority-floor refusal and the ack timeout carry `success: False` *and* an `error`. Every earlier attempt at this used one half or the other, and each time the pilot was told a command executed that had not — a green `GEAR DOWN` in the browser for a gear the adapter refused to move, and a "Critical system change executed" note in the same dict whose `error` said nothing was sent. A result carrying neither key fails closed.

**The undo path pops only after the reversal is on the wire.** `undo_last_command` peeks with `last_command`, attempts the reversal, and calls `pop_last()` only once `_was_transmitted` confirms it. The failure this replaces: `pop_last()` ran *before* the gate, so at advisory the record was destroyed and the result still read `Reversed GEAR_DOWN` in the past tense — the command was neither reversed nor still available to reverse later. An untransmitted reversal now leaves the record intact and describes itself in the conditional ("Would reverse ..."), with the absence of `undone_command` as the signal.

**An absolute position MERLIN cannot read is refused, never toggled.** `UNCONFIRMABLE_POSITION_SYSTEMS` covers `carb_heat`, `fuel_pump` and `parking_brake`, with `UNCONFIRMABLE_REFUSED_ACTIONS` naming the refused verbs per system (the parking brake carries `release`/`set`/`apply`/`engage` as well as `on`/`off`, because those are what a pilot actually says). The refusal runs **before** the unknown-control return, so a refused verb gets the explanation and the `action='toggle'` workaround rather than a dead-end "Unknown control" typo message. `parking_brake` was the only one of the three that was reachable — `carb_heat` and `fuel_pump` are deferred under CMD-09, absent from both the tool enum and the adapter — which is why it was the one that mattered: "parking brake off" on landing rollout, with the brake already off, *set* the brake.

**The announcement queue has exactly one consumer per process.** `OverrideDetector.events` is bounded at `MAX_PENDING_ANNOUNCEMENTS` (32), publishing is incapable of raising because both call sites run inside the telemetry subscriber loop that swallows exceptions, and on overflow the newest event survives. It is drained by `orchestrator.main.drain_authority_events` on the CLI — which prints and speaks each announcement — and by `web.server._authority_event_pump` on the browser path, which fans an `authority_event` frame out to every open chat socket. This is called out because the queue shipped with **no** consumer at all: the two `ProactiveEvent` objects were constructed and immediately orphaned, three separate executors noticed and each correctly declined to mark AUTH-06 complete for it, and a dead queue behind a plausible-looking property accessor is exactly the shape that survives review. The `events` docstring now names both consumers by symbol so it cannot ship unconsumed again.

`override_detector.py` drops authority to advisory on a rolling cooldown when watched telemetry moves with no recent MERLIN dispatch to account for it. This is a policy layer *over* the guards in decision 22, not a replacement for them.

## Testing Approach

- **1,538 Python tests passing** across the three suites: 1,302 orchestrator → **1,389** (plus 2 xfailed), **111** web (plus 1 skipped), **38** telemetry-service. Measured 2026-08-02 at the close of Phase 2. Root-level integration tests are deselected by default (`addopts = -m "not integration"`) and are not part of that count. **The C# adapter test project is deliberately excluded from the total rather than estimated**: `dotnet` is not installed in the WSL2 development environment these figures were measured in, so `cd adapters/msfs && dotnet test` could not be run and no count for it is asserted here. Run it on a machine with the .NET 8 SDK before trusting any claim about C# coverage.
- **Python:** pytest + pytest-asyncio for async tests. Mock the WebSocket connection and Claude API in unit tests.
- **C#:** xUnit. Mock SimConnect for unit tests. Integration tests require MSFS running.
- **No sim required for most tests** -- Record telemetry snapshots as JSON fixtures and replay them through the orchestrator.
- **Web tests** live in `web/tests/` with their own `web/pyproject.toml`; they use `httpx` + `ASGITransport` for REST and `httpx-ws` + `ASGIWebSocketTransport` for WebSocket, all in-process with no live server.
- **Test categories:** config, flight phase, tools, Claude client, STT/TTS backends and factories, turn detection and the turn-probe feature extractor, voice pipeline, command safety/verifier/history, authority state machine, the authority gate and the `send_command` floor, the `_was_transmitted` transmission predicate and the false-confirmation regressions it pins (a NACKed critical command, an untransmitted undo, a refused command rendered in the browser), pilot-override detection, the bounded announcement queue and both of its consumers, the CLI authority status formatter, the parking-brake refusal, the fuel / mixture / crossfeed / parking-brake safety rules, the command-path watchdog, procedures, callouts, deviation monitor, proactive monitor, checklist manager, emergency, validation, aviation tools, context store, chunking, re-ranker, screen capture, aviation-WER scoring; plus root-level integration tests (WebSocket reconnection, health monitor, delta detection, orchestrator end-to-end, tool chain including an end-to-end authority dispatch at every level, Whisper pipeline).

### Running lint the way CI does

CI runs ruff from the **repo root** with the orchestrator config:

```bash
ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml \
  --extend-ignore SIM105,SIM117,F841,B008,B017,B007,UP041
ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml
```

Use these exact commands. `ruff check .` from inside `orchestrator/` **disagrees
with CI**: isort's `src` setting is unset, so it defaults to `["."]` resolved
against the current working directory, which flips whether `orchestrator` counts
as first-party and therefore whether a blank line is wanted before
`from orchestrator...` imports. Running the local form and pushing has broken CI
before.

## Environment Variables

All config flows through `.env` files loaded by `pydantic-settings`. See `.env.example` for the complete list with documentation. Never commit `.env` to version control.

Config properties that branch on a backend selector (`tts_configured`,
`voice_id`, `stt_configured`) must have a branch for **every** supported backend.
A missing branch does not error — it silently reports the feature unconfigured,
which is how a Cartesia-only setup reported `tts_configured: False` for months.
