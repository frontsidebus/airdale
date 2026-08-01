---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: Agent Copilot Control
status: in_progress
stopped_at: Phase 2 context gathered
last_updated: "2026-08-01T01:04:30.607Z"
last_activity: 2026-07-31
progress:
  total_phases: 4
  completed_phases: 1
  total_plans: 0
  completed_plans: 0
  percent: 25
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-18)

**Core value:** MERLIN's voice and text responses must be fast, high-quality, and contextually accurate during flight
**Current focus:** v1.3 Agent Copilot Control — roadmap reconciled 2026-07-29; Phase 2 rescoped and ready to plan

## Current Position

Milestone: v1.3 (in progress; v1.2 shipped 2026-04-18)
Status: PR series #73–#78 all merged; `main` at `80f22bf`
Last activity: 2026-07-31
Requirement coverage: 42 of 63 (67%)

Shipped in the 2026-07-31 session: learnings extraction (#73), stale-record
reconciliation (#74), voice protocol + STT factory + aviation-WER gate (#75),
REQUIREMENTS.md + Phase 2 rescope (#76), semantic turn detection VARC-01 (#77),
synthetic + external corpus ingest EVAL-05/06 (#78).

Next, unblocked: plan v1.3 Phase 2 (AUTH-01…08) — but see Open Decisions, the
stale controls branches change what Phase 2 must gate. Also unblocked: Step 1b
(semantic turn detection on the web/Deepgram path).

Blocked on real audio: EVAL-07 threshold calibration needs ATCOSIM (licence
check required — it publishes no licence text) plus ~8 own-voice recordings.
Synthetic audio covers CI regression and SNR curves only, never thresholds.

## Deferred Items

Items acknowledged and deferred at v1.2 milestone close on 2026-04-18:

| Category | Item | Status |
|----------|------|--------|
| verification | Phase 03 — 6 call-site defects (4 logged + 2 `is_available`) in Whisper consumer wiring | **CLOSED 2026-07-29** — all 6 re-verified against current code; 03-VERIFICATION.md frontmatter now `status: passed`, 9/9 |
| testing | Phase 05 — 4 pre-existing web test failures logged in `deferred-items.md` | **CLOSED 2026-07-29** — fixed in `8587ba5` before v1.2 shipped; `web/tests/` now 38 passed, 1 skipped |
| refactor | `web/server.py` early-boot module state — tests monkeypatch globals rather than use DI overrides | acknowledged (acceptable for v1.2; revisit if logging infra changes) |

## Scope Divergence Note — RESOLVED 2026-07-29

> Original: "Recent commits (Phase 4 integration tests, proactive copilot,
> checklist manager, callouts engine) reference work not captured in the current
> ROADMAP for either v1.2 or v1.3. Before starting v1.3 Phase 2, reconcile: is
> this v1.3 Phase 1 expansion, a new Phase 1.5, or its own milestone?"

**Answer: v1.3 Phase 1 expansion.** The undocumented work is all command-control
and proactive-output infrastructure that belongs to the Agent Copilot Control
theme, not a separate milestone. It is now recorded as two completed unplanned
workstreams in ROADMAP.md (Command Safety & Integrity, Proactive Co-Pilot) with
retroactive requirement IDs SAFE-01…08 and PROA-01…06.

**Root cause identified and fixed:** v1.3 had no `REQUIREMENTS.md`. v1.2 had 36
requirement IDs that every plan declared and every verifier traced; with no IDs
there was nothing for a phase to claim and nothing for verification to check
coverage against, so ~3,900 lines landed silently. `.planning/REQUIREMENTS.md`
now exists with 61 requirements.

**Also corrected:** Phase 2 was rescoped — two of its four deliverables had
already shipped with Phase 1. `CLAUDE.md` was updated for 13 missing modules and
10 missing docs. See `.planning/v1.3-RECONCILIATION.md` for the full audit.

## Open Decisions

These need a call before or during Phase 2 planning:

| Decision | Context |
|---|---|
| ~~`docs/phase2-controls` + `feat/fuel-controls`~~ | **RESOLVED 2026-07-31 — abandon both.** Their `_resolve_command` content is already on `main`; `main` is strictly *ahead* (both branches predate the `command_safety` / `command_verifier` / `command_history` wiring and would strip it). Nothing to rebase or reimplement. Investigation instead surfaced two real gaps, now Phase 2 inputs — see "Phase 2 scope inputs" below. |
| RIO / v2 direction | `rio/phase-1`, `feature/claude-perf-tuning`, `feature/local-inference-architecture` (all 210 commits behind) plus `docs/MIGRATION_V1_V2.md` and `chore/v2-ci-updates` describe an LLM-abstraction / local-inference direction against a separate `rio` remote. Needs an explicit accept-or-abandon. |
| 11 `worktree-agent-*` branches | ~30 commits of leftover agent worktrees. Triage or delete. |
| Speech-to-speech | Requires replacing Claude, `validation.py`, and failure attribution. Should be an ADR if ever pursued, not an incremental slide. See `TECH-STACK-REVIEW.md` §2. |

## Phase 2 scope inputs (found 2026-07-31)

Discovered while resolving the controls-branches decision. All three belong in
Phase 2 because they concern *whether MERLIN may act*, not what it can address.

**1. Six control systems are dead code.** `_resolve_command` in
`orchestrator/orchestrator/tools.py` handles 20 systems, but the
`set_aircraft_control` tool-definition enum in `claude_client.py` lists only 14.
Missing: `magnetos`, `carb_heat`, `fuel_pump`, `starter`, `primer`, `lights`.
Claude cannot emit them, so the handler arms are unreachable.

**2. Safety coverage stops well short of the command surface.** `DEFAULT_RULES`
has 7 rules covering only gear, flaps, autopilot, and throttle; `CRITICAL_COMMANDS`
has 5 entries (gear ×3, `AP_MASTER`, `PARKING_BRAKES`). Nothing gates the
highest-severity commands that already resolve today — `mixture` idle-cutoff,
`fuel_selector: off` (fuel starvation), `crossfeed`, `deice` — nor the six dead
ones, of which `magnetos: off` (in-flight shutdown) and `starter: engage`
(in-flight) are the worst. Enabling gap 1 without closing gap 2 would expose the
most dangerous commands in the surface with no rule behind them. **Sequence
AUTH gating before the enum fix.**

**3. Latent defect, becomes live with the enum fix.** `carb_heat` and `fuel_pump`
map `"on"`, `"off"`, and `"toggle"` to the *same* toggle event
(`ANTI_ICE_CARB_HEAT_TOGGLE` / `FUEL_PUMP_TOGGLE`), so "carb heat off" turns it
**on** when it was already off. Harmless while unreachable; a real defect the
moment the enum lists them. Needs state-aware resolution against telemetry.

Progress (v1.3 requirements): [███████░░░] 67% — 42 of 63

## Performance Metrics

**Velocity:**

- Total plans completed: 0
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
| Phase 01-housekeeping P01 | 3min | 2 tasks | 9 files |
| Phase 01 P03 | 3min | 2 tasks | 4 files |
| Phase 01-housekeeping P02 | 1min | 1 tasks | 2 files |
| Phase 02 P01 | 4min | 2 tasks | 7 files |
| Phase 02 P02 | 4min | 2 tasks | 3 files |
| Phase 02 P03 | 4min | 2 tasks | 4 files |
| Phase 03 P01 | 2min | 1 tasks | 2 files |
| Phase 03 P02 | 4min | 3 tasks | 8 files |
| Phase 04 P01 | 5min | 2 tasks | 1 files |
| Phase 05 P01 | 2min | 2 tasks | 5 files |
| Phase 06-ci-cd-pipeline P01 | 1min | 1 tasks | 1 files |
| Phase 06 P02 | 1min | 2 tasks | 2 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Housekeeping structured as point releases -- independent, parallel fixes
- TTS protocol needs streaming extension before web server integration
- Barge-in characterization tests should precede web server refactor
- CI/CD is final phase because tests must exist before CI can enforce them
- [Phase 01-housekeeping]: Removed only targeted deprecated SimConnect config fields; left legitimate adapter references intact
- [Phase 01]: Separate consumer lock from adapter lock to prevent deadlock
- [Phase 01]: Direct list mutation under held lock to avoid reentrant asyncio.Lock deadlock
- [Phase 01-housekeeping]: Pinned Docker images to full patch versions (1.5.5, 0.8.3) for reproducible builds
- [Phase 02]: Persistent httpx.AsyncClient per TTS backend eliminates per-call TCP overhead
- [Phase 02]: Voice settings flow from config through factory to ElevenLabsClient constructor
- [Phase 02]: Consumer delegation pattern: VoiceOutput and web server REST TTS delegate to TTSClient.synthesize() instead of inline httpx
- [Phase 02]: ElevenLabs WS streaming uses asyncio.Queue for concurrent send/receive in synthesize_ws_stream
- [Phase 02]: Phrase cache stays in web server layer, checked before uncached text reaches TTSClient
- [Phase 03]: Followed TTS client lifecycle pattern: persistent httpx.AsyncClient + aclose()
- [Phase 03]: Kept identical confidence formula: exp(avg_logprob) averaged across segments, 0.5 fallback
- [Phase 03]: Sync WhisperClient bridged to async via asyncio.to_thread() for both VoiceInput and web server consumers
- [Phase 03]: Whisper model default upgraded from medium to large-v3-turbo for better accuracy and speed
- [Phase 04]: AppState dataclass with 11 fields replaces all module-level mutable state in web/server.py
- [Phase 04]: settings included in AppState for Phase 5 testability; module-level kept for early logging
- [Phase 05]: Monkeypatch module globals instead of DI overrides since web/server.py uses module-level state
- [Phase 06-ci-cd-pipeline]: Skipped web pip install -e .[dev] since web has no pyproject.toml; requirements.txt only
- [Phase 06]: Build only SimConnectBridge.Tests.csproj to avoid SimConnect SDK dependency on CI runners

### Pending Todos

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-08-01T01:04:30.579Z
Stopped at: Phase 2 context gathered — 21 decisions captured across four areas;
ready for planning.
Resume file: .planning/phases/02-authority-safety-layer/02-CONTEXT.md
