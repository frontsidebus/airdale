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
- [ ] **Phase 2: Authority & Safety Layer** *(rescoped 2026-07-29, scope extended 2026-07-31)* — configurable authority levels (advisory/assisted/full), pilot override detection, watchdog timer (AUTH-01…08); plus the unreachable-enum fix and its resolution defect (CMD-07…08) and semantic turn detection on the web path (VARC-06)
- [ ] **Phase 3: Automated Maneuvers** — PID control loops for takeoff/landing/go-around, cancellable long-running maneuvers, server-side control at 20Hz (MNVR-01…04)
- [ ] **Phase 4: Vision Cockpit Reading** — lower-latency screen capture, Claude vision for instrument reading, third-party gauge interpretation (VIS-01…04)
- [ ] **Voice Architecture** *(sequenced after Phase 2; VARC-06 pulled into it)* — local-default hybrid, flight-phase-routed architecture (VARC-02…05, see `.planning/TECH-STACK-REVIEW.md`). VARC-01 shipped in PR #77 for the local path; VARC-06 extends it to the web path and is claimed by Phase 2.

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

### Phase 2: Authority & Safety Layer

**Goal**: MERLIN's authority to act on the aircraft is explicit, bounded, and never ambiguous — a configurable level decides whether it may act at all, a detected pilot override or a dead command path drops it automatically, and the current level and its reason are visible
**Depends on**: Phase 1
**Requirements**: AUTH-01 through AUTH-08, CMD-07, CMD-08, VARC-06 (CMD-09 deferred)
**Context**: `.planning/phases/02-authority-safety-layer/02-CONTEXT.md` (21 decisions)
**Plans**: 10 plans in 6 waves

Plans:
**Wave 1**

- [x] 02-01-PLAN.md — Authority state machine (`authority.py`) and the eight `authority_*` settings
- [x] 02-02-PLAN.md — MSFS adapter command coverage: 20 missing events plus cross-language parity guards (CMD-07)
- [x] 02-03-PLAN.md — Web-path semantic turn detection: decode helper, `/api/turn-probe`, browser probe loop (VARC-06)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-04-PLAN.md — Authority gate in `set_aircraft_control` and the `carb_heat`/`fuel_pump` refusal (AUTH-01…04, CMD-08)
- [x] 02-05-PLAN.md — Advisory floor, ack watchdog, `command_path` health and dispatch ledger in `TelemetryClient`

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 02-06-PLAN.md — Verification coverage and the override detector (AUTH-05, AUTH-06)
- [ ] 02-07-PLAN.md — Procedure re-route through the gate with abort-on-withheld (D-04, D-06)

**Wave 4** *(blocked on Wave 3 completion)*

- [ ] 02-08-PLAN.md — Orchestrator wiring: `ClaudeClient` thread-through, tool-timeout fix, CLI construction

**Wave 5** *(blocked on Wave 4 completion)*

- [ ] 02-09-PLAN.md — Web surfacing: `/api/status` authority fields and the advisory/withheld message types (AUTH-08)

**Wave 6** *(blocked on Wave 5 completion)*

- [ ] 02-10-PLAN.md — Browser authority indicator and advisory/withheld rendering, with a human verification checkpoint

Wave structure: wave 1 = 02-01, 02-02, 02-03 (independent); wave 2 = 02-04, 02-05;
wave 3 = 02-06, 02-07; wave 4 = 02-08; wave 5 = 02-09; wave 6 = 02-10.
VARC-06 (02-03) is its own lane and neither depends on, nor is depended on by, the
authority plans.

Distinct from SAFE-01…08, which decide whether a *specific command* is safe right
now. This phase decides whether MERLIN may act *at all*.

**Scope extended 2026-07-31** during context-gathering, with two additions:

- **CMD-07/08** *(both revised 2026-07-31 after research)* — CMD-07 is now the
  adapter command-coverage fix: `SimConnectManager.cs` registers 40 of the 67
  events `_resolve_command` emits, and `trim`, `deice`, `fuel_selector`, and
  `crossfeed` are **in the enum today with no adapter handler** — MERLIN reports
  those actions as taken and nothing happens. CMD-08 makes `carb_heat`/`fuel_pump`
  refuse `"on"`/`"off"` rather than blind-toggle, because no carb-heat or
  fuel-pump state exists in the telemetry chain to resolve against.
  Exposing the six unreachable systems moved to **CMD-09, deferred** — the
  adapter cannot execute them, so the enum change alone would deliver nothing.

- **VARC-06** — semantic turn detection on the web path. Orthogonal to authority;
  bundled by owner decision. Plan as an independent workstream, not as a
  dependency of the AUTH work.

**Known gap this phase closes incidentally:** `procedures.py` reaches SimConnect
via `_resolve_command` + `send_command` directly, with no safety check at all —
the check went into `tools.py` and was never added to `procedures.py`. Routing
procedures through `set_aircraft_control` closes it.

## Progress

| Phase | Milestone | Plans Complete | Status      | Completed  |
|-------|-----------|----------------|-------------|------------|
| 1. Housekeeping           | v1.2 | 3/3 | Complete    | 2026-03-28 |
| 2. TTS Integration        | v1.2 | 5/10 | In Progress|  |
| 3. Whisper Consolidation  | v1.2 | 2/2 | Complete    | 2026-03-28 |
| 4. Web Server Refactor    | v1.2 | 2/2 | Complete    | 2026-04-16 |
| 5. Web Server Tests       | v1.2 | 2/2 | Complete    | 2026-03-28 |
| 6. CI/CD Pipeline         | v1.2 | 2/2 | Complete    | 2026-03-28 |
| 1. Discrete Command Control | v1.3 | — | Complete (CMD-01…06) | — |
| Command Safety & Integrity  | v1.3 | — | Complete (SAFE-01…08), unplanned | 2026-07-29 |
| Proactive Co-Pilot          | v1.3 | — | Complete (PROA-01…06), unplanned | — |
| Voice Backend Abstraction   | v1.3 | — | Complete (VOIC-01…09, EVAL-01…04) | 2026-07-29 |
| 2. Authority & Safety Layer | v1.3 | 0/10 | Planned (AUTH-01…08, CMD-07…08, VARC-06) | — |
| 3. Automated Maneuvers    | v1.3 | 0/— | Not started (MNVR-01…04) | —      |
| 4. Vision Cockpit Reading | v1.3 | 0/— | Not started (VIS-01…04) | —       |
| Voice Architecture        | v1.3 | 0/— | VARC-01 complete; VARC-02…05 not started | — |

Requirement coverage: 42 of 66 complete. 35 of those 42 are retroactive — they
describe work that predated `.planning/REQUIREMENTS.md`. See that file's Coverage
table.
