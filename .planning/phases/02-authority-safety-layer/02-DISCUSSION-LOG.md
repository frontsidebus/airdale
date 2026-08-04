# Phase 2: Authority & Safety Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-31
**Phase:** 02-authority-safety-layer
**Areas discussed:** Phase layout (blocker), Scope of the unreachable enum entries, Enforcement chokepoint + advisory semantics, Override detection + cooldown, Watchdog latch behavior, Web-path turn detection architecture

---

## Phase directory layout (resolved blocker, pre-discussion)

`gsd-sdk query init.phase-op 2` resolved to `.planning/phases/02-tts-integration`
— v1.2's completed TTS phase — reporting `has_context: true`, `has_plans: true`,
`plan_count: 3` for the wrong milestone. Cause: `.planning/phases/` still held
v1.2 directories 01–05 alongside `.planning/milestones/v1.2-phases/`.

The leftovers were **not** safe to delete: `.planning/phases/` was the fuller
record. Every `LEARNINGS.md` (the 192 attributed items from PR #73), most
`PLAN.md` / `CONTEXT.md` / `DISCUSSION-LOG.md` files, `04-SECURITY.md`, and
`04-UAT.md` existed only there. `05-02-SUMMARY.md` differed between the two.

| Option | Description | Selected |
|--------|-------------|----------|
| Finish archive, clear phases/ | Sync the fuller content into the archive, then remove v1.2 dirs from `phases/`. Restores the convention that `phases/` holds only the current milestone. | ✓ |
| Milestone-prefixed dirs | Leave leftovers, create `v1.3-02-authority-safety-layer/`. Zero risk, but `/gsd:plan-phase 2` stays broken. | |
| Continue numbering (07) | Give v1.3 Phase 2 the next free number. Tooling works, but the directory number stops matching the ROADMAP label. | |

**User's choice:** Finish archive, clear phases/
**Notes:** Archive verified as a complete superset before any deletion. The
archive's `05-02-SUMMARY.md` (2026-03-29, describing `test_websocket.py` /
`test_helpers.py`, commits `241c8c2`/`ae3454b`) turned out to be a *superseded*
record; the `phases/` copy (2026-04-14, `test_chat_ws.py`/`test_telemetry_ws.py`,
commits `2766f1a`/`78d4097`) matched the files on disk. Both preserved — the old
one as `05-02-SUMMARY.superseded-2026-03-29.md`. Clearing `phases/` alone was
insufficient: `cmdFindPhase` falls back to milestone archives by design, so the
fix was creating `.planning/phases/02-authority-safety-layer/`, which makes the
flat layout win.

---

## Scope: the unreachable control systems

Investigation of the two "stale controls branches" found they add nothing —
their `_resolve_command` content is already on `main`, and both predate the
`command_safety` / `command_verifier` / `command_history` wiring, so merging
either would regress the safety layer. But it surfaced that `_resolve_command`
handles 20 systems while the tool enum exposes 14.

| Option | Description | Selected |
|--------|-------------|----------|
| In scope — gate, fix, then expose | Build AUTH gating, fix the on/off/toggle defect, then add the six to the enum behind the gate. | ✓ |
| Out of scope — leave dead, note it | Strictly honor "no new command types"; leave the dead code and latent bug for a follow-up phase. | |
| Delete the dead arms | Remove the six handler arms so `_resolve_command` matches the enum. | |

**User's choice:** In scope — gate, fix, then expose
**Notes:** The six are `magnetos`, `carb_heat`, `fuel_pump`, `starter`, `primer`,
`lights`. Decisive argument: `magnetos: off` is an in-flight engine shutdown and
`starter: engage` in flight is nearly as bad — these are precisely what an
authority layer exists to gate, so treating them as out of scope for the
authority phase is backwards. The `carb_heat`/`fuel_pump` defect (on/off/toggle
all mapping to the same toggle event) is latent only because the systems are
unreachable.

---

## Enforcement chokepoint + advisory semantics

Four questions. The first was re-asked after the user said the trade-offs weren't
clear; the second framing also corrected an error in the first — I had claimed
`send_command` has no `SimState` access, but it is a method on `TelemetryClient`,
which holds `self._state` and exposes `get_state()`.

### Q1 — where the gate lives

| Option | Description | Selected |
|--------|-------------|----------|
| C + A: route procedures, floor in send_command | Policy in `set_aircraft_control`; procedures routed through it; thin level-only floor in `send_command`. | ✓ |
| A only: everything in send_command | One gate, maximum structural guarantee; `TelemetryClient` takes on the safety checker and authority state. | |
| C only: route procedures, no floor | Single gate with full context; relies on convention for future callers. | |
| B: gate both call sites | Smallest diff; accepts the sync burden that already caused the current gap. | |

**User's choice:** C + A hybrid
**Notes:** The deciding fact was that `procedures.py:269` reaches SimConnect with
no safety check at all today — the check went into `tools.py` and never into
`procedures.py`. Option B reproduces the exact structure that produced that bug.

### Q2 — withheld step mid-procedure

| Option | Description | Selected |
|--------|-------------|----------|
| Continue, report what was skipped | Matches `ProcedureExecutor`'s existing continue-on-failure design. | |
| Abort, hand back to pilot | Stop at the withheld step and say so. | ✓ |
| Pre-check what's checkable, then continue | Reject up front on authority level; fall back to continue for state-dependent warnings. | |

**User's choice:** Abort, hand back to pilot
**Notes:** Deliberately overrides the documented continue-on-failure rationale
("aborting mid-procedure could leave the aircraft in a worse configuration").
The distinction that settled it: a *failed* step means the sim didn't take it; a
*withheld* step means MERLIN decided it shouldn't act unsupervised — and
continuing past that point is acting unsupervised. Noted during the question that
`assisted` withholding depends on the live safety verdict, so all six steps
cannot be reliably pre-computed before the procedure starts.

### Q3 — advisory output

| Option | Description | Selected |
|--------|-------------|----------|
| Tool stays available, returns a dry-run result | Resolve + safety-check, return `{advisory, would_execute, safety}` without transmitting. | ✓ |
| Withhold the tool entirely in advisory | Rebuild `TOOL_DEFINITIONS` per level so Claude cannot emit the call. | |
| Both — dry-run result, plus prompt guidance | Dry-run enforcement plus system-prompt tone shaping. | |

**User's choice:** Tool stays available, returns a dry-run result
**Notes:** Verified rather than assumed the caching claim (loaded the `claude-api`
reference rather than answering from memory): caching is a prefix match rendered
`tools` → `system` → `messages`, and a tool-definition change invalidates all
three tiers — so a dynamic tool list would invalidate the cached persona block at
`claude_client.py:509` on every request. The cache-preserving escape hatch
(mid-conversation tool changes) requires Opus 5+; this project runs Sonnet 4.

### Q4 — where authority state lives

| Option | Description | Selected |
|--------|-------------|----------|
| Injected AuthorityState object | Seeded from settings, passed alongside the existing injected collaborators. | ✓ |
| Module-level singleton in tools.py | Mirrors `_safety_check`; smallest diff, global mutable state. | |
| On TelemetryClient | No plumbing for the floor; transport owns command policy. | |

**User's choice:** Injected AuthorityState object
**Notes:** The singleton option was annotated with the v1.2 Phase 4 history —
that is the shape a whole plan was spent removing from `web/server.py`, and
STATE.md still lists the residue as an open concern.

---

## Override detection + cooldown

Scouting established that everything needed already exists:
`ProactiveMonitor.on_telemetry_update()` runs prev/curr comparisons per update,
`CommandHistory` records commands with monotonic timestamps, and
`_extract_relevant_state()` already maps a command to its affected fields.

### Q1 — signal source

| Option | Description | Selected |
|--------|-------------|----------|
| Continuous watch in ProactiveMonitor | Fourth check in the existing per-update loop. | ✓ |
| Extend the verifier's window | Treat "reached then reverted" within the 3s poll as the signal. | |
| Both — verifier catches the fight, monitor watches the decay | Two detectors, fullest coverage. | |

**User's choice:** Continuous watch in ProactiveMonitor

### Q2 — what counts as an override

| Option | Description | Selected |
|--------|-------------|----------|
| Any unattributed change on a watched field | Direction-agnostic; field moved with no matching CommandRecord. | ✓ |
| Reversal only | Fires only when state returns toward its pre-command value. | |
| Any manual input on a commanded system | Widest net, no attribution logic. | |

**User's choice:** Any unattributed change on a watched field
**Notes:** Flagged before the question that telemetry reports state, not
provenance — SimConnect never says who moved the lever — so "the pilot did it"
can only mean "no matching recent CommandRecord", and MERLIN's own commands take
up to 3s to appear. Get that correlation wrong and MERLIN detects itself.
Sensitivity was chosen deliberately: a false positive costs one advisory window,
a false negative leaves MERLIN commanding an aircraft the pilot is flying.

### Q3 — watch window

| Option | Description | Selected |
|--------|-------------|----------|
| Verified, then a fixed grace window | Watch opens on verifier confirmation, runs ~30s. | ✓ |
| Fixed window from command dispatch | One timer from send; reopens the attribution race. | |
| Phase-scaled window | Per-FlightPhase durations. | |

**User's choice:** Verified, then a fixed grace window
**Notes:** Chosen partly because it dissolves the D-12 attribution race by
construction — MERLIN's own change is what closes verification.

### Q4 — cooldown

| Option | Description | Selected |
|--------|-------------|----------|
| Rolling timer — auto-restore, reset on each override | Each override pushes expiry out; auto-restores when it lapses. | ✓ |
| Explicit restore only | Stays advisory until the pilot restores it by voice or UI. | |
| Fixed timer, no reset | One window from the first override. | |

**User's choice:** Rolling timer
**Notes:** The interaction with Q2 drove this: with a deliberately sensitive
detection rule, explicit-restore-only means one false positive costs the rest of
the flight unless the pilot notices the status display.

---

## Watchdog latch behavior

### Q1 — what trips the latch

| Option | Description | Selected |
|--------|-------------|----------|
| N consecutive timeouts | Circuit-breaker; 3 by default, reset on any ack. | ✓ |
| A single timeout | Strictest reading of AUTH-07; fastest detection. | |
| Failure ratio over a window | 3-of-last-5; catches a flapping path. | |

**User's choice:** N consecutive timeouts
**Notes:** The adapter is out-of-process over WebSocket from WSL2 to a Windows
host, so single dropped frames are routine — a one-strike latch would take MERLIN
out of service on transient loss.

### Q2 — what the latched state is

| Option | Description | Selected |
|--------|-------------|----------|
| Advisory, with a distinct reason surfaced | Reuse advisory behavior; record reason for AUTH-08. | ✓ |
| Refuse outright, distinct from advisory | Fourth authority state. | |
| Advisory only, no distinct reason | Simplest; pilot can't tell fault from policy. | |

**User's choice:** Advisory with a distinct reason
**Notes:** `HealthMonitor` already registers named subsystems, so command-path
health needs no new infrastructure.

### Q3 — what clears it

| Option | Description | Selected |
|--------|-------------|----------|
| Telemetry reconnect / heartbeat recovery | Transport reports its own recovery; no probe traffic. | ✓ |
| Periodic probe command | Tests the command path directly; needs a universally safe no-op. | |
| Manual clear only | Guarantees a human notices; strands MERLIN on transient faults. | |

**User's choice:** Telemetry reconnect / heartbeat recovery
**Notes:** Flagged the deadlock before asking — a latch that stops command
issuance leaves nothing to generate the successful ack that would clear it. The
same WebSocket carries telemetry and commands, so telemetry flowing again is
direct evidence.

---

## Web-path turn detection architecture

Scouting corrected a premise: the web path is **not** Deepgram-endpointed.
`deepgram_client.transcribe()` is batch, and the turn decision is made in the
browser by RMS energy with `VAD_SILENCE_MS = 1200` — 3× the local fixed fallback
(400ms) and 8× the semantic probe point (150ms).

### Q1 — architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Browser probes, server decides | Lower the JS threshold, POST trailing 8s on each candidate, server runs SmartTurnDetector. | ✓ |
| Stream audio to the server continuously | WS audio stream, server-side VAD + Smart Turn; matches the local path exactly. | |
| Run the model in the browser | ONNX Runtime Web client-side; no round trip. | |

**User's choice:** Browser probes, server decides
**Notes:** Matches the recorded architectural principle verbatim (cheap acoustic
gate finds candidates and decides *when* to ask; `TurnDetector` decides
*whether*), just with the gate in JS. The in-browser option was argued against on
a concrete basis: `features.py` reimplements `WhisperFeatureExtractor` in numpy,
pinned to golden vectors at <1e-4, and its docstring warns a divergence "would
not raise — it would just make turn predictions quietly wrong." A JS reimpl would
have to stay bit-compatible. Continuous streaming was acknowledged as the
eventual target (and a VARC-02 prerequisite) but deferred as too large to carry
alongside AUTH.

### Q2 — fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Fall back to 400ms, matching vad_silence_ms | Degrade to the same threshold the local fallback uses. | ✓ |
| Fall back to today's 1200ms | Zero regression risk; keeps the sluggish fallback. | |
| Fail loudly — disable voice input | Impossible to miss; conflicts with graceful degradation. | |

**User's choice:** Fall back to 400ms

---

## Claude's Discretion

- Default values for new config fields (grace window, cooldown period,
  consecutive-timeout count) — starting points suggested, tune during planning.
- Naming of new config fields, the `AuthorityState` API surface, and the
  turn-probe endpoint route.
- Whether the web-path turn work gets its own requirement ID (VARC-01b) or
  extends the already-complete VARC-01.

## Deferred Ideas

- Continuous browser→server audio streaming (eventual target; VARC-02
  prerequisite; reworks barge-in).
- `claude_model` defaults to `claude-sonnet-4-20250514`, whose published
  retirement date of 2026-06-15 has passed — verify whether it still resolves.
- `claude_temperature: 0.3` blocks any model upgrade; sampling params are
  rejected on Sonnet 5 and Opus 4.7+.
- Delete `docs/phase2-controls` and `feat/fuel-controls` — both strictly behind
  `main` and would regress the safety layer if merged.
- Regenerate `.planning/codebase/*.md` — dated 2026-03-26, predates all of v1.3.
- Triage or delete the 11 `worktree-agent-*` branches.
