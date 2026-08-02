---
phase: 02-authority-safety-layer
plan: 15
subsystem: ui
tags: [asyncio, websocket, fan-out, authority, announcements, browser]

# Dependency graph
requires:
  - phase: 02-authority-safety-layer
    provides: "OverrideDetector.events — the bounded announcement queue and its non-raising _publish (plan 02-13)"
  - phase: 02-authority-safety-layer
    provides: "renderAuthority / AUTHORITY_REASON_TEXT / applyAuthority and the authority badge (plan 02-10)"
  - phase: 02-authority-safety-layer
    provides: "AuthorityState.summary() and the fail-safe lifespan construction (plans 02-01, 02-09)"
provides:
  - "web.server._authority_event_pump — the browser consumer of OverrideDetector.events, closing Gap 3 / WR-06 on the web path"
  - "The authority_event wire frame: message + event + fields + the live authority summary"
  - "AppState.chat_clients — a fan-out registry of connected /ws/chat sockets for server-initiated frames"
  - "app.js authority_event case: chat-log announcement, toast, and a badge that moves at announcement time rather than poll time (IN-04)"
affects: [02-16 CLAUDE.md decision-26 update, phase-02-verification, web-ui]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One named lifespan-owned consumer per announcement queue, with the done-callback that logs its death"
    - "Server-initiated fan-out over a snapshot copy, discarding a socket whose send raised"
    - "Registry membership owned by accept() + finally, never by an except arm"

key-files:
  created:
    - web/tests/test_authority_events.py
  modified:
    - web/server.py
    - web/static/app.js
    - web/static/style.css

key-decisions:
  - "The pump starts unconditionally, not inside the sim-connected branch: with no detector it logs why announcements are not running and returns, so the absence is a line in the log instead of a silence"
  - "A dedicated _on_authority_pump_done rather than the inline _cache_task lambda — the lambda calls task.exception() with no cancelled() guard, which raises CancelledError on the shutdown cancel this task actually receives"
  - "The three authority keys are present-and-None when no AuthorityState exists; inventing full/config would report a crashed subsystem as an operator's own choice"
  - "The announcement row does not carry .command-status-msg and has no outcome icon: a change in what MERLIN may do is not a command outcome and must not be scanned as one"
  - "The pump is cancelled first in shutdown, before the telemetry disconnect that feeds the detector"

patterns-established:
  - "A blocking queue consumer written as one literal, greppable expression so a competing drain is caught by grep -c"
  - "Announcement hues reuse the badge's level vocabulary; the distinguishing mark against command rows is form (filled banner + tag), not colour"

requirements-completed: []  # AUTH-06/AUTH-08 deliberately left unmarked — see Decisions

# Metrics
duration: 12min
completed: 2026-08-01
---

# Phase 02 Plan 15: Browser Authority Announcements Summary

**The two `ProactiveEvent` objects `OverrideDetector` has been building since 02-06 now reach every open browser tab as words the moment they happen, and the authority badge moves off the announcement itself instead of waiting up to ten seconds for the next status poll.**

## Status: PAUSED AT CHECKPOINT

Tasks 1 and 2 are complete, committed and verified. **Task 3 is a blocking
`checkpoint:human-verify` and has NOT been performed** — it requires a live browser,
a running mock adapter and a judgement about legibility and perceived latency that no
assertion can make. It has not been self-approved and nothing below claims a human
observed anything. The two `human_verification:` items in `02-VERIFICATION.md` remain
open until it is walked.

## Performance

- **Duration:** 12 min (Tasks 1-2)
- **Started:** 2026-08-01T20:47Z (approx., worktree spawn)
- **Paused at checkpoint:** 2026-08-01T20:59Z
- **Tasks:** 2 of 3 complete (Task 1 TDD; Task 3 awaiting a human)
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- **Gap 3 / WR-06 closed on the browser path.** `_authority_event_pump` is a
  lifespan-owned task that drains `OverrideDetector.events` forever and fans each
  announcement out to every registered `/ws/chat` socket as an `authority_event`
  frame. The queue that shipped with a consumer named in its docstring and none in
  the code now has exactly one on this path — `grep -c "await
  state.override_detector.events.get()" web/server.py` reports `1`.
- **The 02-13 warning is silenced.** Since 02-13 merged, `web/server.py` built the
  detector with no `event_queue`, inheriting the 32-slot bound with nothing draining
  it; every announcement past the bound logged *"No consumer appears to be draining
  it — the pilot is not being told about authority changes"* at WARNING. Confirmed
  gone: a smoke run publishing 40 announcements through the real
  `OverrideDetector._publish` with the real pump attached delivered 40/40, left a
  backlog of 0 and logged zero such warnings (see Verification).
- **The badge no longer lags the gate (IN-04).** The frame carries
  `authority_level`, `authority_reason` and the whole `summary()` dict under
  `authority` — precisely the three keys `renderAuthority` reads — so the browser
  re-renders the badge in the same tick as the announcement. A watchdog latch or a
  pilot override can no longer leave `FULL (configured)` on screen while the gate is
  already refusing.
- **Every tab hears it.** `_broadcast_chat` iterates a snapshot copy and discards a
  socket whose send raises, so one dead tab cannot end the broadcast for a live one
  and the registry cannot grow for the life of the process (T-02-15-02 / T-02-15-03).
- **14 new tests** (web suite 97 → 111 passing, 1 skipped unchanged).

## Task Commits

1. **Task 1: A single pump draining the detector queue and fanning out to every chat socket** — `d54111c` (test, RED) → `1637683` (feat, GREEN)
2. **Task 2: Render the announcement and refresh the badge from the frame** — `9a31dd5` (feat)
3. **Task 3: Human verification in a running browser** — NOT RUN, checkpoint returned to the orchestrator

Task 1 needed no REFACTOR commit.

## Files Created/Modified

- `web/server.py` — `AppState.chat_clients` and `AppState.authority_event_task`;
  `_authority_event_frame`, `_broadcast_chat`, `_authority_event_pump` and
  `_on_authority_pump_done`; the pump created and its done-callback attached in
  `lifespan` after the `OverrideDetector` block; cancel-and-await under
  `suppress(asyncio.CancelledError)` first in the shutdown half; `state.chat_clients.add(ws)`
  after `ws.accept()` and a new `finally:` arm in `ws_chat` doing the `discard`.
  Imports gained `contextlib.suppress` and `orchestrator.proactive_monitor.ProactiveEvent`.
- `web/static/app.js` — `authorityEventKind` and `showAuthorityEvent` beside the
  command-outcome renderers, plus the `case 'authority_event':` arm in
  `handleChatMessage`. The row is built from `spanWithText` text nodes; the toast goes
  through the existing `showCommandToast` with the `AUTHORITY:` prefix `applyAuthority`
  already uses; `renderAuthority(msg)` is called when the frame reports a level.
- `web/static/style.css` — `.authority-event-msg` with `.auth-event-tag` /
  `.auth-event-text` and the `override` / `restore` / `other` variants.
- `web/tests/test_authority_events.py` *(new)* — 14 tests: four over the frame shape
  (override, restore, live summary, absent authority), three over the fan-out
  (two sockets, one raising socket discarded, all-dead is not an error), five over the
  pump (broadcast, no detector, survives a failing broadcast, clean cancel, and the
  end-to-end socket path), and two over `ws_chat` registry membership including both
  tabs receiving the same frame.

## Decisions Made

- **The pump starts unconditionally.** The plan said "immediately after the
  `OverrideDetector` try/except block"; that block sits inside
  `if state.sim_connected and state.sim_client is not None:`. Starting the pump at
  function level instead means a server that never reached telemetry also gets the
  INFO line naming what is not running — and, more usefully, naming that with no
  detector MERLIN *also* never drops to advisory when the pilot takes the controls.
  The missing announcements are the symptom; the missing detector is the disease.
- **A named done-callback rather than the `_cache_task` lambda.** See Deviations.
- **`None` authority stays `None` on the wire.** `renderAuthority` already renders an
  unreported level verbatim, and `_on_tool_result` already refuses to substitute
  `config` for an absent reason on `command_advisory`. A third opinion on that
  question in a third place is how the two drift apart.
- **The announcement row is not a `.command-status-msg`.** The four command outcomes
  have already used up the green/red/cyan/amber icon vocabulary. Rather than invent a
  fifth colour, the announcement is distinguished by *form* — a filled banner with an
  `AUTHORITY` tag and no ✓/✗/○/⊘ — and takes its hue from the badge of the level it
  announces (cyan for the drop to advisory, green for the restore to full). Nothing
  else in the chat log carries a background fill.
- **REQUIREMENTS.md deliberately not edited.** AUTH-06's browser half now exists, but
  Task 3 is a *blocking* checkpoint and the phase's own verification report criticised
  exactly the pattern of marking a requirement complete ahead of the evidence. AUTH-08
  is likewise gated on the human confirming the badge moves on the announcement.
  REQUIREMENTS.md is also a shared artifact with sibling plan 02-14 in flight this
  wave. The orchestrator should mark both after the checkpoint is approved and the
  wave merges.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] A named done-callback instead of copying the `_cache_task` lambda**

- **Found during:** Task 1
- **Issue:** The plan said to "copy the shape used for `_cache_task` rather than
  inventing a second one". That shape is
  `lambda t: logger.error(...) if t.exception() else None`, with no `t.cancelled()`
  guard — correct for `_cache_task`, which is never cancelled, and a defect here:
  the same plan requires this task to be cancelled on shutdown, and
  `Task.exception()` **re-raises `CancelledError`** on a cancelled task. Copying it
  verbatim would have logged an "Exception in callback" traceback on every clean
  shutdown.
- **Fix:** `_on_authority_pump_done`, a module-level function with the
  `if task.cancelled(): return` guard — the same shape the CLI sibling
  `Orchestrator._on_announce_task_done` already carries for the identical reason.
  Same purpose, same log level, same "the pilot is no longer being told" wording.
- **Files modified:** `web/server.py`
- **Verification:** `test_cancelling_the_pump_raises_nothing` cancels the task and
  asserts `CancelledError` propagates; the full web suite emits no callback
  tracebacks.
- **Committed in:** `1637683` (Task 1 GREEN commit)

**2. [Rule 3 - Blocking] Reworded a comment so the plan's own grep gate still passes**

- **Found during:** Task 2
- **Issue:** The plan's `<action>` asks for a comment saying "Do not write a second
  reason-to-text mapping — plan 02-10 deliberately defined `AUTHORITY_REASON_TEXT`
  once…", while its `<acceptance_criteria>` requires
  `grep -c "AUTHORITY_REASON_TEXT" web/static/app.js` to be *unchanged* (2). Naming
  the symbol in the comment takes it to 3, failing the machine-checkable gate a
  verifier will run, with no second mapping actually introduced.
- **Fix:** Kept the comment and its full meaning, referring to "the badge's reason
  map … declared exactly once (see the authority rendering section below)" instead of
  the literal identifier. Count is back to 2, and the intent the criterion protects
  is unchanged: no second reason-to-text mapping exists.
- **Files modified:** `web/static/app.js`
- **Verification:** `grep -c "AUTHORITY_REASON_TEXT" web/static/app.js` → `2`, equal
  to the pre-task count; `node --check` clean.
- **Committed in:** `9a31dd5` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 correctness fix on a shutdown path, 1 blocking
contradiction between the plan's action text and its own gate)
**Impact on plan:** Both preserve the plan's stated intent exactly; neither changes
specified behaviour nor adds scope.

## Issues Encountered

- **Which copy of `orchestrator` a standalone script imports.** As 02-13 recorded,
  the editable install resolves `orchestrator` to the *main* repo, not the worktree.
  `pytest` from `web/` imports the worktree copy, but the ad-hoc smoke script did not
  until `PYTHONPATH` was pinned to the worktree root and its `orchestrator/`. The
  smoke output below prints the resolved paths so the result is checkable.

## Verification Results

| Check | Result |
|---|---|
| `cd web && python3 -m pytest -q` | **111 passed, 1 skipped** (baseline 97 / 1 — +14) |
| `cd orchestrator && python3 -m pytest -q` | **1353 passed, 2 xfailed** (baseline unchanged — no orchestrator file touched) |
| `node --check web/static/app.js` | exit 0 |
| `ruff check orchestrator/ telemetry-service/ web/ …` (CI form, repo root) | All checks passed |
| `ruff format --check orchestrator/ telemetry-service/ web/ …` (CI form, repo root) | 111 files already formatted |
| `grep -c "await state.override_detector.events.get()" web/server.py` | `1` — exactly one consumer per process |
| `grep -c "AUTHORITY_REASON_TEXT" web/static/app.js` | `2` — unchanged; no second reason mapping |
| `git diff -U0 -- web/static/app.js \| grep innerHTML` | no output — no new `innerHTML`, server strings attached as text nodes |
| Smoke: real `OverrideDetector._publish` × 40 with the real pump attached | published 40, delivered 40, queue backlog 0, **0** "No consumer appears to be draining it" WARNINGs |
| Files changed vs. wave base | `web/server.py`, `web/static/app.js`, `web/static/style.css`, `web/tests/test_authority_events.py` — nothing else |

## Known Stubs

None. Every value on the new wire frame is computed from a live `ProactiveEvent` and
a live `AuthorityState`, and the browser case renders from the frame it is handed.
The one deliberate empty value — `authority_level`/`authority_reason`/`authority`
being `None` — is the documented honest report of an absent authority subsystem, not
a placeholder.

## Threat Flags

None. No new route, no new client-sendable WebSocket message, no file access and no
schema change. T-02-15-07 holds: the `authority_event` frame is server-to-client only
and nothing on this path reaches an `AuthorityState` mutator — the pump reads
`summary()` and sends. T-02-15-08 (announcements broadcast to every client on an
unauthenticated, CORS-open server) is accepted as planned and unchanged: the same
sockets already carry strictly more sensitive content to the same audience.

## Scope Boundaries Respected

- No edits to `orchestrator/orchestrator/tools.py`, `command_safety.py`,
  `claude_client.py`, the three `orchestrator/tests/` files or anything under `docs/`
  (sibling plan 02-14).
- No edits to `orchestrator/orchestrator/override_detector.py` — plan 02-13 delivered
  the bounded queue and this plan only consumes it.
- No edits to `.planning/STATE.md` or `.planning/ROADMAP.md` (orchestrator-owned).
- No edits to `.planning/REQUIREMENTS.md` — see Decisions.

## Awaiting Human Verification (Task 3)

The checkpoint covers the two items `02-VERIFICATION.md` records as unverifiable by
static analysis. Both are **unanswered**; neither is claimed here:

1. **Authority badge live behaviour** — a pilot override induced through the mock
   adapter, a watchdog latch, both tabs, the advisory command state during cooldown,
   the disconnect path, and the client-side unknown state. Plus the judgement the
   plan asks for in the developer's own words: at a glance, is it obvious MERLIN has
   stood down and why, and is the delay short enough to be useful?
2. **Turn-probe graceful degradation with no ffmpeg on `PATH`** — voice input still
   working via the fixed-silence fallback, no HTTP 500 on `/api/turn-probe`, and a
   logged decode failure rather than a traceback per probe. Plan 02-12 restored the
   never-raises contract and pinned it with two tests; what remains is the
   user-visible symptom in a live browser.

**The `degraded` authority reason is deliberately not a manual step**, for the reason
plan 02-10 recorded: `AUTHORITY_LEVEL` is validated at `Settings` construction, so a
degraded state cannot be induced from configuration without editing code. It is
covered by 02-09's server-side construction-failure test and 02-10's client-side grep
criteria, and is not left unverified by omission.

## Next Phase Readiness

- **AUTH-06 is now delivered on both paths** — `drain_authority_events` on the CLI
  (02-13) and `_authority_event_pump` in the browser (here). Both names now exist in
  code, which is what `override_detector.py`'s `events` docstring already claims and
  what 02-16's decision-26 update needs to record.
- **Blocked on Task 3.** The plan is `autonomous: false` and the checkpoint is
  `gate="blocking"`; the phase should not be signed off until it is walked.
- **Deliberately still open, with reasons in the plan's `<notes>`:** WR-04 (no
  utterance token on the async turn probe), WR-03 (400 ms fixed-silence default),
  IN-03 (`undo_last_command` / `execute_procedure` emit no browser command frame),
  IN-05 (probe throttle keyed by IP), and pushing the watchdog latch and the degraded
  transition over this same channel — neither produces a `ProactiveEvent` today, so
  wiring them means adding an event source inside `AuthorityState` or
  `TelemetryClient`, which is a design change to the state machine.

## Self-Check: PASSED

All claimed artifacts and commits verified on `worktree-agent-a9680f7a13cc32794`:

- Files present: `web/server.py`, `web/static/app.js`, `web/static/style.css`,
  `web/tests/test_authority_events.py`, this summary
- Commits present: `d54111c`, `1637683`, `9a31dd5`
- No file deletions in any commit (`git diff --diff-filter=D` empty for each)
- No untracked files left behind

---
*Phase: 02-authority-safety-layer*
*Paused at human checkpoint: 2026-08-01*
