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
  - "The Task 3 checkpoint is recorded as approved without narrative detail — the developer's blanket approval is not written up as observations they did not report"

patterns-established:
  - "A blocking queue consumer written as one literal, greppable expression so a competing drain is caught by grep -c"
  - "Announcement hues reuse the badge's level vocabulary; the distinguishing mark against command rows is form (filled banner + tag), not colour"

requirements-completed: []  # AUTH-06/AUTH-08 left for plan 02-16, which owns the ledger — see Decisions

# Metrics
duration: 12min implementation + human checkpoint
completed: 2026-08-02
---

# Phase 02 Plan 15: Browser Authority Announcements Summary

**The two `ProactiveEvent` objects `OverrideDetector` has been building since 02-06 now reach every open browser tab as words the moment they happen, and the authority badge moves off the announcement itself instead of waiting up to ten seconds for the next status poll.**

## Status: COMPLETE

All three tasks are closed. Tasks 1 and 2 are implemented, committed and merged;
Task 3 — the blocking `checkpoint:human-verify` — was returned to the developer and
came back **approved**. Read the "Human Verification (Task 3)" section below before
treating any individual step as observed: the approval was a bare `approved` with no
narrative, and this summary says exactly that rather than reconstructing answers.

## Performance

- **Duration:** 12 min implementation (Tasks 1-2), plus the human checkpoint
- **Started:** 2026-08-01T20:47Z (approx., worktree spawn)
- **Paused at checkpoint:** 2026-08-01T20:59Z
- **Checkpoint approved / plan closed:** 2026-08-02
- **Tasks:** 3 of 3 complete (Task 1 TDD; Task 3 a verification gate, no code)
- **Files modified:** 4 (1 created, 3 modified) — unchanged by Task 3

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

| Task | Name | Commit | Outcome |
|---|---|---|---|
| 1 (RED) | Failing tests for the browser authority-event pump | `d54111c` | 14 tests added, all failing |
| 1 (GREEN) | Pump draining the detector queue, fanning out to every chat socket | `1637683` | 14/14 passing |
| 2 | Render the announcement and refresh the badge from the frame | `9a31dd5` | `node --check` clean, web suite green |
| — | Summary written in paused-at-checkpoint state | `9aaf9df` | checkpoint returned to the orchestrator |
| 3 | Verify the announcement and the degraded probe path in a running browser | *(no code commit)* | **approved** — a verification gate, and no defect was reported that would require one |
| — | Summary closed out after approval | *(this commit)* | status COMPLETE, post-merge verification numbers |

Task 1 needed no REFACTOR commit. Task 3 is a `checkpoint:human-verify` whose
`<action>` writes code only "unless a step below surfaces a defect"; none was
reported, so the plan's own definition closes it with no code change. Inventing one
would have been scope, not execution.

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
- **REQUIREMENTS.md deliberately not edited, before or after approval.** AUTH-06's
  browser half now exists and Task 3 has since been approved, but the ledger is not
  this plan's to write: it is a shared artifact, sibling plan 02-14 was in flight this
  wave, and plan 02-16 owns the requirement ledger. Marking it from here would be the
  same over-reach the phase's own verification report criticised — a requirement
  ticked by the plan that would benefit from the tick. 02-16 marks AUTH-06 and
  AUTH-08, and should read the approval caveat below before it does.
- **The approval is recorded as given, not as hoped for.** The developer typed
  `approved` and nothing else. Steps 9 and 10 asked for narrative answers; none were
  supplied. Writing plausible answers into this summary would be exactly the failure
  mode this phase exists to correct — a system reporting outcomes it had not
  confirmed — so the caveat is stated explicitly rather than smoothed over. The plan's
  criterion "Step 10 is answered in the summary in the developer's own words" is
  therefore **not** satisfied on its own terms; the blanket approval stands in for it.

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

Re-run **after** the wave merge, so these are post-merge numbers rather than the
pre-merge ones this summary carried while it was paused.

| Check | Result |
|---|---|
| `cd web && python3 -m pytest -q` | **111 passed, 1 skipped** (baseline 97 / 1 — +14) |
| `cd orchestrator && python3 -m pytest -q` | **1389 passed, 2 xfailed** — up from the 1353 recorded pre-merge. The rise is sibling plan 02-14 landing after the first run, not anything this plan added; no orchestrator file is touched here |
| `node --check web/static/app.js` | exit 0 |
| `ruff check orchestrator/ telemetry-service/ web/ …` (CI form, repo root) | All checks passed |
| `ruff format --check orchestrator/ telemetry-service/ web/ …` (CI form, repo root) | 111 files already formatted |
| `grep -c "await state.override_detector.events.get()" web/server.py` | `1` — exactly one consumer per process |
| `grep -c "AUTHORITY_REASON_TEXT" web/static/app.js` | `2` — unchanged; no second reason mapping |
| `grep -n "case 'authority_event':" web/static/app.js` | line 1001 — the merged Task 2 case is present post-merge |
| `git diff -U0 -- web/static/app.js \| grep innerHTML` | no output — no new `innerHTML`, server strings attached as text nodes |
| Smoke: real `OverrideDetector._publish` × 40 with the real pump attached | published 40, delivered 40, queue backlog 0, **0** "No consumer appears to be draining it" WARNINGs *(run pre-merge; not repeated, no code changed since)* |
| Files changed vs. wave base | `web/server.py`, `web/static/app.js`, `web/static/style.css`, `web/tests/test_authority_events.py` — nothing else |
| Task 3 human checkpoint | **approved** — see the caveat below |

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

## Human Verification (Task 3) — approved, with the shape of the approval stated

**Result: approved.** The developer's response to the checkpoint was the single word
`approved`.

**Approved without narrative detail.** No answers were supplied to step 9
(voice input surviving an absent `ffmpeg`) or step 10 (legibility of the announcement
and the perceived delay between moving a control and seeing it). Those two steps are
**accepted by the developer's blanket approval rather than by reported observation**,
and this summary does not assert otherwise. Nothing below reconstructs, paraphrases or
infers an observation the developer did not make.

That distinction is recorded deliberately. This entire phase exists because a system
reported outcomes it had not actually confirmed, and the same standard applies to the
phase's own paperwork. A blanket approval closes the gate; it does not manufacture
evidence, and the plan's criterion asking for step 10 "in the developer's own words"
is not met on its own terms.

What this does and does not license downstream:

- **Does:** close the blocking gate, so the plan and the wave may proceed, and so
  02-16 may act on the phase being executable end to end.
- **Does not:** stand as observed evidence for the two `human_verification:` items in
  `02-VERIFICATION.md`. Any later report should describe them as *approved* rather
  than as *observed*, and should say by whom. If a future phase needs the timing
  judgement specifically — for instance to decide whether the announcement path needs
  to beat the 10 s poll by a wider margin — it needs a fresh observation, not a
  citation of this line.

For reference, the two items the checkpoint covered:

1. **Authority badge live behaviour** — a pilot override induced through the mock
   adapter, both tabs receiving the announcement, the advisory command state during
   cooldown, the disconnect path, and the client-side unknown state. Every mechanism
   underneath is pinned by the 14 automated tests in
   `web/tests/test_authority_events.py`; what the human step added was the live-browser
   and perceived-latency judgement, which is the part left unnarrated.
2. **Turn-probe graceful degradation with no `ffmpeg` on `PATH`** — voice input still
   working via the fixed-silence fallback, no HTTP 500 on `/api/turn-probe`, and a
   logged decode failure rather than a traceback per probe. Plan 02-12 restored the
   never-raises contract and pinned it with two tests; the user-visible symptom in a
   live browser is the part left unnarrated.

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
- **No longer blocked.** The plan is `autonomous: false` and its checkpoint was
  `gate="blocking"`; that gate is now approved and the plan is closed. 02-16 should
  carry the approval caveat above into any phase-level sign-off rather than
  reporting the two `human_verification:` items as observed.
- **Deliberately still open, with reasons in the plan's `<notes>`:** WR-04 (no
  utterance token on the async turn probe), WR-03 (400 ms fixed-silence default),
  IN-03 (`undo_last_command` / `execute_procedure` emit no browser command frame),
  IN-05 (probe throttle keyed by IP), and pushing the watchdog latch and the degraded
  transition over this same channel — neither produces a `ProactiveEvent` today, so
  wiring them means adding an event source inside `AuthorityState` or
  `TelemetryClient`, which is a design change to the state machine.

## Self-Check: PASSED

Re-verified post-merge on `worktree-agent-ad3943baddaa1704b`, rebased onto the wave-8
tracking commit `04a8760`:

- Files present: `web/server.py`, `web/static/app.js`, `web/static/style.css`,
  `web/tests/test_authority_events.py`, this summary
- Commits present in this branch's ancestry: `d54111c`, `1637683`, `9a31dd5`, `9aaf9df`
- The merged Task 1/2 work is live in the working tree, not merely in history:
  `_authority_event_pump` in `web/server.py`, `case 'authority_event':` at
  `web/static/app.js:1001`, `authority-event-msg` in `web/static/style.css`
- Tasks 1 and 2 were **not** re-run or re-committed; only this summary changed in the
  closing commit
- No file deletions in any commit
- No untracked files left behind
- `.planning/STATE.md`, `.planning/ROADMAP.md` and `.planning/REQUIREMENTS.md`
  untouched — owned by the orchestrator and by plan 02-16 respectively

---
*Phase: 02-authority-safety-layer*
*Implemented: 2026-08-01 · Human checkpoint approved and plan closed: 2026-08-02*
