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

Requirements are tracked in `.planning/REQUIREMENTS.md` (added 2026-07-29 — v1.3
previously had none, which is how substantial work landed outside this roadmap).

- [x] **Phase 1: Discrete Command Control** — SimConnect event mapping, command protocol, bidirectional routing, Claude tool (CMD-01…06, merged to `main`)
- [x] **Command Safety & Integrity** — pre-execution safety rules, post-execution verification, undo history, multi-step procedures (SAFE-01…08, merged; **was not a planned phase** — see reconciliation note below)
- [x] **Proactive Co-Pilot** — callout engine, deviation monitor, checklist automation, emergency fast paths (PROA-01…06, merged; **was not a planned phase**)
- [x] **Voice Backend Abstraction** — STT/TTS protocols and factories, aviation-WER gate (VOIC-01…09, EVAL-01…04, PR #75)
- [ ] **Phase 2: Authority & Safety Layer** *(rescoped 2026-07-29)* — configurable authority levels (advisory/assisted/full), pilot override detection, watchdog timer (AUTH-01…08)
- [ ] **Phase 3: Automated Maneuvers** — PID control loops for takeoff/landing/go-around, cancellable long-running maneuvers, server-side control at 20Hz (MNVR-01…04)
- [ ] **Phase 4: Vision Cockpit Reading** — lower-latency screen capture, Claude vision for instrument reading, third-party gauge interpretation (VIS-01…04)
- [ ] **Voice Architecture** *(sequenced after Phase 2)* — semantic turn detection, local-default hybrid, flight-phase-routed architecture (VARC-01…05, see `.planning/TECH-STACK-REVIEW.md`)

#### Reconciliation note (2026-07-29)

An audit found this roadmap materially out of date. Corrections applied:

- **Phase 2 was rescoped.** Its original scope listed "phase-aware command gating"
  as a deliverable, but that shipped with Phase 1 as `command_safety.py`, along
  with seven envelope rules and a two-tier severity model that were never
  specified. What remains is the part that decides *whether MERLIN may act at
  all* — authority levels, override detection, watchdog. The delivered items are
  now recorded as SAFE-01…07.
- **Phase 1's branch reference was removed.** `feat/agent-copilot-control` is
  merged; citing it implied the work was parked awaiting integration.
- **Two unplanned bodies of work were added above** (Command Safety, Proactive
  Co-Pilot) — roughly 2,300 lines that existed on `main` with documentation in
  `docs/` but no roadmap entry.
- **Phase 3 note:** `procedures.py` already sequences multi-step commands. MNVR-03
  should build on it rather than reimplement the "long-running task" pattern.

Full analysis: `.planning/v1.3-RECONCILIATION.md`.

#### Phase 1 Details (Complete)

**Goal**: MERLIN can execute discrete aircraft control commands via natural language
**Requirements**: CMD-01 through CMD-06
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
| 1. Discrete Command Control | v1.3 | — | Complete (CMD-01…06) | — |
| Command Safety & Integrity  | v1.3 | — | Complete (SAFE-01…08), unplanned | 2026-07-29 |
| Proactive Co-Pilot          | v1.3 | — | Complete (PROA-01…06), unplanned | — |
| Voice Backend Abstraction   | v1.3 | — | Complete (VOIC-01…09, EVAL-01…04) | 2026-07-29 |
| 2. Authority & Safety Layer | v1.3 | 0/— | Not started (AUTH-01…08, rescoped) | — |
| 3. Automated Maneuvers    | v1.3 | 0/— | Not started (MNVR-01…04) | —      |
| 4. Vision Cockpit Reading | v1.3 | 0/— | Not started (VIS-01…04) | —       |
| Voice Architecture        | v1.3 | 0/— | Not started (VARC-01…05) | —      |

Requirement coverage: 39 of 61 complete. 35 of those 39 are retroactive — they
describe work that predated `.planning/REQUIREMENTS.md`. See that file's Coverage
table.
