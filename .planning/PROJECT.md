# MERLIN v1.2 — Consolidation & Quality

## What This Is

MERLIN is an AI co-pilot for flight simulators (currently MSFS 2024) that provides contextual aviation assistance through voice and text. It uses a pluggable adapter architecture with a universal telemetry service, Claude for inference, ChromaDB for RAG, and ElevenLabs/Kokoro for TTS. The core loop — fly the sim, talk to MERLIN, get flight-phase-aware responses — is functional at v1.1.

## Core Value

MERLIN's voice and text responses must be fast, high-quality, and contextually accurate during flight — latency and speech quality are the user experience.

## Requirements

### Validated

- ✓ SimConnect telemetry pipeline (adapter → telemetry service → orchestrator) — existing
- ✓ Claude inference with tool use and streaming — existing
- ✓ Flight phase detection with hysteresis state machine — existing
- ✓ Dynamic token budgeting (short/normal/briefing) — existing
- ✓ ChromaDB RAG with query cache and aviation data ingestion — existing
- ✓ Voice I/O: PTT, VAD (Silero), Whisper STT, ElevenLabs TTS streaming — existing
- ✓ Web UI with cockpit display, chat WebSocket, telemetry proxy — existing
- ✓ TTS text sanitizer and ICAO aviation preprocessor — existing
- ✓ Audio preprocessing (high-pass filter, trim, normalize) — existing
- ✓ Barge-in / interruption support — existing
- ✓ Graceful degradation (subsystems can be unavailable) — existing
- ✓ Auto-reconnection with exponential backoff — existing
- ✓ Docker Compose deployment stack — existing
- ✓ Event-driven SimConnect message pump — existing

### Active

- [x] Integrate TTS abstraction layer into web server and CLI voice module — Phase 2
- [x] Consolidate duplicated Whisper transcription logic into single async client — Phase 3
- [x] Consolidate duplicated TTS voice settings into shared config — Phase 2
- [x] Remove deprecated SimConnect config fields and backward-compat aliases — Phase 1
- [x] Fix race condition in telemetry consumer list (asyncio.Lock) — Phase 1
- [x] Pin ChromaDB and Whisper Docker image versions — Phase 1
- [x] Standardize Python version across Dockerfiles — Phase 1
- [x] Refactor web server global state into proper DI / app.state — Phase 4
- [x] Add web server test coverage (chat flow, barge-in, TTS, transcription) — Phase 5
- [x] Create GitHub Actions CI/CD pipeline (lint, test, build, Docker) — Phase 6

### Out of Scope

- New sim adapters (X-Plane, DCS) — future milestone, architecture supports it
- Mobile app — web-first
- Multi-user / auth — local tool, single user
- Monitoring / Sentry integration — nice-to-have, not this milestone
- Structured logging migration — can follow CI/CD establishment
- Screen capture window targeting — low priority, works well enough

## Context

- Project is at v1.1.0 across orchestrator, adapter, and web UI
- Codebase has 361+ tests passing but no CI — regressions only caught manually
- A TTS abstraction layer (`orchestrator/orchestrator/tts/`) with ElevenLabs and Kokoro backends exists but is not wired into the web server or CLI voice module. Both still use inline httpx calls with hardcoded, inconsistent voice settings
- Web server (`web/server.py`) is 1,057 lines with module-level global state and zero test coverage — it's the primary user-facing component
- Whisper transcription + confidence scoring is implemented in 3 separate places with subtle differences
- Development happens in WSL2; MSFS adapter runs on Windows host
- TTS integration is motivated by code cleanliness, lower latency (persistent HTTP clients), and consistent speech quality

## Constraints

- **Platform**: MSFS adapter must run on Windows host (SimConnect SDK requirement)
- **API keys**: Anthropic and ElevenLabs keys required; Kokoro is the local/free alternative for TTS
- **Python**: 3.11+ across all Python components
- **Docker**: Services deployed via Docker Compose; dev mode uses bind mounts and tiny Whisper model
- **Backward compat**: Telemetry service WebSocket protocol must remain stable (adapters are out-of-process)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Housekeeping as point releases before major phases | Clean foundation before building on it — avoids carrying tech debt through refactors | — Pending |
| TTS integration driven by latency + quality, not just architecture | Persistent connections reduce TTFB; consistent voice settings fix audible inconsistencies | — Pending |
| Web server refactor + tests as single phase | Refactoring globals into DI first makes the code testable; testing the old shape would mean rewriting tests after refactor | — Pending |
| CI/CD as final phase | Tests and code quality must exist before CI can enforce them | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-28 after Phase 6 (CI/CD Pipeline) — v1.2 milestone complete*
