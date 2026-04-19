# Roadmap: MERLIN

## Milestones

- ✅ **v1.2 — Consolidation & Quality** — Phases 1-6 (shipped 2026-04-18)
- 🚧 **v1.3 — Agent Copilot Control** — Phases 1-4 (Phase 1 complete, 2-4 planned)

## Phases

<details>
<summary>✅ v1.2 — Consolidation & Quality (Phases 1-6) — SHIPPED 2026-04-18</summary>

- [x] Phase 1: Housekeeping (3/3 plans)
- [x] Phase 2: TTS Integration (3/3 plans)
- [x] Phase 3: Whisper Consolidation (2/2 plans)
- [x] Phase 4: Web Server Refactor (2/2 plans)
- [x] Phase 5: Web Server Tests (2/2 plans)
- [x] Phase 6: CI/CD Pipeline (2/2 plans)

See `.planning/milestones/v1.2-ROADMAP.md` for full phase details.

</details>

### 🚧 v1.3 — Agent Copilot Control (In Progress)

v1.3 adds bidirectional sim control — MERLIN executes aircraft commands (flaps, gear, autopilot, radios, throttle, etc.) via voice or text. The foundation is built: SimConnect write path through the adapter, command routing through the telemetry service, and a Claude tool that translates natural language intent to SimConnect events. Future phases add PID-based automated maneuvers, authority levels, and vision-based cockpit reading.

- [x] **Phase 1: Discrete Command Control** — SimConnect event mapping, command protocol, bidirectional routing, Claude tool (COMPLETE — `feat/agent-copilot-control` branch)
- [ ] **Phase 2: Authority & Safety Layer** — Configurable authority levels (advisory/assisted/full), pilot override detection, watchdog timer, phase-aware command gating
- [ ] **Phase 3: Automated Maneuvers** — PID control loops for takeoff/landing/go-around, MCP Task pattern for long-running maneuvers, server-side control at 20Hz
- [ ] **Phase 4: Vision Cockpit Reading** — DXcam screen capture upgrade, Claude vision for instrument reading, third-party aircraft gauge interpretation

#### Phase 1 Details (Complete)

**Goal**: MERLIN can execute discrete aircraft control commands via natural language
**Branch**: `feat/agent-copilot-control`
**Files modified**: 10 files across adapter (C#), telemetry service (Python), orchestrator (Python)

**What was built:**
1. Command protocol: `ConsumerCommand` → `ServiceCommand` → `AdapterCommandAck` → `ServiceCommandAck`
2. Telemetry service routing: bidirectional command forwarding with ack tracking
3. MSFS adapter: 30+ SimConnect events registered, `ExecuteCommand()` via `TransmitClientEvent`
4. Orchestrator: `send_command()` with Future-based ack, `set_aircraft_control` Claude tool
5. Command translation: `_resolve_command()` maps human-friendly params to SimConnect events

**Supported systems**: flaps, gear, autopilot, throttle, radio, barometer, trim, parking brake, spoilers, mixture, propeller

## Progress

| Phase | Milestone | Plans Complete | Status      | Completed  |
|-------|-----------|----------------|-------------|------------|
| 1. Housekeeping           | v1.2 | 3/3 | Complete    | 2026-03-28 |
| 2. TTS Integration        | v1.2 | 3/3 | Complete    | 2026-03-28 |
| 3. Whisper Consolidation  | v1.2 | 2/2 | Complete    | 2026-03-28 |
| 4. Web Server Refactor    | v1.2 | 2/2 | Complete    | 2026-04-16 |
| 5. Web Server Tests       | v1.2 | 2/2 | Complete    | 2026-03-28 |
| 6. CI/CD Pipeline         | v1.2 | 2/2 | Complete    | 2026-03-28 |
| 1. Discrete Command Control | v1.3 | — | Complete  | —          |
| 2. Authority & Safety Layer | v1.3 | 0/— | Not started | —         |
| 3. Automated Maneuvers    | v1.3 | 0/— | Not started | —          |
| 4. Vision Cockpit Reading | v1.3 | 0/— | Not started | —          |
