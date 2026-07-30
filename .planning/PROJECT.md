# MERLIN — Airdale

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
- ✓ TTS abstraction wired into web server and CLI voice module with streaming — v1.2
- ✓ Single async Whisper client replacing three divergent implementations — v1.2
- ✓ Unified TTS voice settings from config across all consumers — v1.2
- ✓ Deprecated SimConnect config fields and backward-compat aliases removed — v1.2
- ✓ Telemetry consumer list asyncio.Lock race condition fixed — v1.2
- ✓ ChromaDB and Whisper Docker images pinned to patch versions — v1.2
- ✓ Python version standardized across all Dockerfiles — v1.2
- ✓ Web server globals refactored to `AppState` + FastAPI DI — v1.2
- ✓ Web server tests covering chat, barge-in, TTS, transcription, telemetry, status — v1.2
- ✓ GitHub Actions CI/CD (lint, test, Docker build, path-based filtering, merge gating) — v1.2
- ✓ Bidirectional command protocol and `set_aircraft_control` Claude tool (v1.3 Phase 1) — v1.3

### Active

- [ ] Authority & safety layer — configurable authority levels, pilot override detection, watchdog, phase-aware gating — v1.3 Phase 2
- [ ] Automated maneuvers with PID control loops (takeoff/landing/go-around) — v1.3 Phase 3
- [ ] Vision cockpit reading with DXcam and Claude vision — v1.3 Phase 4

### Out of Scope

- New sim adapters (X-Plane, DCS) — future milestone, architecture supports it
- Mobile app — web-first
- Multi-user / auth — local tool, single user
- Monitoring / Sentry integration — nice-to-have, not this milestone
- Structured logging migration — can follow CI/CD establishment
- Screen capture window targeting — low priority, works well enough

## Context

- Project at v1.2 (shipped 2026-04-18) across orchestrator, adapter, and web UI
- v1.3 active — Phase 1 (Discrete Command Control) complete; Phases 2-4 planned
- All Python tests pass under GitHub Actions CI; .NET tests and Docker build verified per PR
- TTS and Whisper consumers all route through shared async clients with persistent httpx connections
- `web/server.py` uses `AppState` dataclass + FastAPI DI; web tests mock dependencies and run in isolation
- Development happens in WSL2; MSFS adapter runs on Windows host
- Recent commits (`test: add Phase 4 integration tests`, `feat: proactive co-pilot`, checklist manager, callouts engine) reference proactive-copilot work not yet captured in ROADMAP — requires reconciliation before starting v1.3 Phase 2

## Constraints

- **Platform**: MSFS adapter must run on Windows host (SimConnect SDK requirement)
- **API keys**: Anthropic and ElevenLabs keys required; Kokoro is the local/free alternative for TTS
- **Python**: 3.11+ across all Python components
- **Docker**: Services deployed via Docker Compose; dev mode uses bind mounts and tiny Whisper model
- **Backward compat**: Telemetry service WebSocket protocol must remain stable (adapters are out-of-process)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Housekeeping as point releases before major phases | Clean foundation before building on it — avoids carrying tech debt through refactors | ✓ Good — shipped v1.2 with no regressions |
| TTS integration driven by latency + quality, not just architecture | Persistent connections reduce TTFB; consistent voice settings fix audible inconsistencies | ✓ Good — WebSocket streaming live |
| Web server refactor + tests as single phase | Refactoring globals into DI first makes the code testable; testing the old shape would mean rewriting tests after refactor | ✓ Good — DI + tests both shipped |
| CI/CD as final phase | Tests and code quality must exist before CI can enforce them | ✓ Good — CI gating on every PR since v1.2 |
| Bidirectional command protocol with ack tracking (v1.3 Phase 1) | Enable MERLIN to control aircraft systems while maintaining deterministic command/ack contract | ✓ Good — 30+ SimConnect events supported |

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
*Last updated: 2026-04-18 after v1.2 milestone close-out — archive written, REQUIREMENTS.md reset for next milestone*
