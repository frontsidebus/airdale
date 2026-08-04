---
phase: 02-authority-safety-layer
plan: 13
subsystem: authority
tags: [asyncio, priority-queue, cli, tts, override-detection, announcements]

# Dependency graph
requires:
  - phase: 02-authority-safety-layer
    provides: "AuthorityState (level + reason + summary()), OverrideDetector with its ProactiveEvent announcements, VoiceOutput.speak"
provides:
  - "A bounded, non-raising publish path on OverrideDetector.events (MAX_PENDING_ANNOUNCEMENTS = 32)"
  - "orchestrator.main.drain_authority_events — the CLI consumer that prints and speaks every authority announcement"
  - "orchestrator.main.format_authority_status — pure renderer of AuthorityState.summary() into CLI lines"
  - "Authority in /status plus a dedicated /authority command (WR-07)"
affects: [02-15 browser announcement pump, 02-16 CLAUDE.md decision-26 update]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Announcement queue with exactly one named consumer per process"
    - "Bounded queue + non-raising publisher for anything written from a telemetry callback"
    - "Module-level functions for anything that must be unit-testable without the Orchestrator god-object"

key-files:
  created:
    - orchestrator/tests/test_main_authority.py
  modified:
    - orchestrator/orchestrator/override_detector.py
    - orchestrator/orchestrator/main.py
    - orchestrator/tests/test_override_detector.py

key-decisions:
  - "The announcement queue is bounded at 32 and the publisher discards-then-retries rather than raising: both call sites run inside the telemetry subscriber loop, which swallows exceptions, so a raising publish would fail invisibly"
  - "On overflow the newest event is what survives — 'is MERLIN advisory right now' is a question only the latest announcement answers"
  - "The drain is a background task, not a poll in _conversation_loop: that loop blocks on input() in an executor thread, so a poll there would deliver an override announcement only after the pilot's next keystroke"
  - "format_authority_status prints the raw reason value (config/override/watchdog/degraded) rather than friendly prose, per CLAUDE.md's tts_configured lesson that a plausible-looking unmapped branch hides for months"
  - "_publish uses a single enqueue call site (a two-iteration loop) rather than put/discard/put, so grepping the module for a second occurrence catches any future edit that publishes around it"
  - "AUTH-06 left unmarked in REQUIREMENTS.md: the CLI half now ships, the browser half is plan 02-15"

patterns-established:
  - "Consumer-naming docstrings: a queue's docstring names its consumers by symbol so it cannot ship unconsumed again"
  - "Per-event try/except in a forever-loop consumer, with CancelledError deliberately left to propagate"

requirements-completed: []  # AUTH-07 CLI half closed; AUTH-06/AUTH-07 marking deferred — see Decisions

# Metrics
duration: 8min
completed: 2026-08-02
---

# Phase 02 Plan 13: CLI Authority Announcements Summary

**The two `ProactiveEvent` objects `OverrideDetector` has been building and orphaning since 02-06 now reach the pilot on the CLI — printed and spoken through `VoiceOutput` by a background drain task — and `/status` plus a new `/authority` command answer "what level am I at and why" without a log dive.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-08-02T00:24:35Z
- **Completed:** 2026-08-02T00:32:52Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- **Gap 3 / WR-06 closed on the CLI.** `drain_authority_events` consumes `OverrideDetector.events` in a task created alongside the detector's telemetry subscription. A pilot override prints `[AUTHORITY] You've taken the flaps. I'm advisory only until you're done.` and speaks it; the auto-restore at cooldown lapse does the same (D-14).
- **The queue can no longer grow without bound.** `MAX_PENDING_ANNOUNCEMENTS = 32` with a `_publish` that never raises and never awaits. A full queue is now a logged WARNING naming the likely cause (no consumer draining) instead of an invisible leak.
- **WR-07 closed.** `/status` now ends with the authority lines, and `/authority` prints them alone under a header. Level, reason, configured level, override cooldown, watchdog latch + timeout count, and degraded detail are all visible.
- **The `events` docstring no longer excuses the missing consumer.** It named no one ("a later consumer can drain it without this module knowing who that is"), which is how the queue shipped dead. It now names `orchestrator.main.drain_authority_events` and `web.server._authority_event_pump` and states that exactly one drains per process.
- **19 new tests** (1302 → 1321 passing, 2 xfailed unchanged).

## Task Commits

1. **Task 1: Bound the announcement queue and make publishing incapable of raising** — `b2d9298` (test, RED) → `4b4321b` (feat, GREEN)
2. **Task 2: Speak and print authority announcements on the CLI, and put authority in /status** — `8d513d0` (test, RED) → `930d6b1` (feat, GREEN)

Neither task needed a REFACTOR commit.

## Files Created/Modified

- `orchestrator/orchestrator/override_detector.py` — `MAX_PENDING_ANNOUNCEMENTS`, bounded default queue, `_publish` (single enqueue site, discard-and-retry on full, WARNING log), both announcement sites routed through it, rewritten `events` docstring naming both consumers.
- `orchestrator/orchestrator/main.py` — `format_authority_status` and `drain_authority_events` as module-level functions; `_announce_task` attribute; `_start_announcements` called after the detector subscribe; cancel-and-await in `stop()`; `_on_announce_task_done` done-callback; authority lines in `/status`; new `/authority` arm; `/authority` added to the `Commands:` help line.
- `orchestrator/tests/test_main_authority.py` *(new)* — 13 tests over the drain (print+speak, `speak=None`, raising `announce`, raising `speak`, clean cancel, priority order) and the formatter (each conditional line present/absent, raw reason values). Constructs no `Orchestrator`.
- `orchestrator/tests/test_override_detector.py` — `TestAnnouncementQueueIsBounded`: 6 tests over the bound, overflow behaviour, newest-survives, the WARNING, caller-supplied queues, and that a full queue still cannot stop the authority drop.

## Decisions Made

- **Discard-one-then-retry, newest wins.** An `asyncio.PriorityQueue` has no "oldest" accessor, so the discarded item is whichever the heap yields (for this queue, the highest-priority pending event). Documented in `_publish`: which one goes matters less than that the newest gets in, and an announcement nobody has drained in 32 events is stale by definition.
- **`_on_announce_task_done` rather than reusing `_on_tts_done`.** The plan allowed "an equivalently-named handler". Reusing `_on_tts_done` verbatim would log "TTS playback task failed" when the announcement drain dies — a misleading line for the single most important failure in this plan. The new handler is the same shape and says what actually broke.
- **The drain starts only when telemetry connects.** It is created inside `start()`'s successful-connect branch, immediately after `self._sim_client.subscribe(self._override_detector.on_telemetry_update)`. In text-only mode the detector receives no frames and can produce no announcements, so a task there would idle forever with nothing to consume.
- **REQUIREMENTS.md deliberately not edited.** AUTH-06 spans two plans — this one delivers the CLI half, 02-15 delivers the browser pump — and marking it complete now would repeat exactly the premature-completion pattern that 02-VERIFICATION caught (three executors correctly declined to mark it). AUTH-07's CLI "says so" gap is genuinely closed here, but REQUIREMENTS.md is a shared artifact and two sibling executors (02-11, 02-12) are writing in this same wave; the orchestrator should mark both after the merge.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Restructured `_publish` to a single enqueue call site**

- **Found during:** Task 1
- **Issue:** The plan's `<action>` described a try / discard-and-log / retry sequence, which is two `put_nowait` lines. Its own `<acceptance_criteria>` and `<verification>` both require `grep -c "put_nowait" override_detector.py` to report `1`. The two are not simultaneously satisfiable as literally written, and the grep is the machine-checkable gate a verifier will run.
- **Fix:** Kept the exact described semantics (try; on full discard one under `suppress(QueueEmpty)`, log WARNING, retry; never raise) inside a two-iteration `for` loop, giving one enqueue call site. A comment at the loop records that the single site is deliberate and is what catches a future edit publishing around it.
- **Files modified:** `orchestrator/orchestrator/override_detector.py`
- **Verification:** `grep -c "put_nowait" orchestrator/orchestrator/override_detector.py` → `1`; all 32 `test_override_detector.py` tests pass, including the never-raises and newest-survives cases.
- **Committed in:** `4b4321b` (Task 1 commit)

**2. [Rule 1 - Bug] Dedicated done-callback instead of the TTS one**

- **Found during:** Task 2
- **Issue:** Attaching `_on_tts_done` (which the plan offered as the default) would report an announcement-drain death as `"TTS playback task failed"`. The whole point of the done-callback here is that an unexpected death must be *legible*, and a wrong subsystem name in the one log line that matters is a defect.
- **Fix:** Added `_on_announce_task_done`, same shape and same cancellation handling, logging that the pilot is no longer being told about authority changes. The plan explicitly permitted "an equivalently-named handler".
- **Files modified:** `orchestrator/orchestrator/main.py`
- **Verification:** Full suite green; the drain's forever-loop and cancellation semantics are covered by `test_cancelling_the_drain_exits_cleanly`.
- **Committed in:** `930d6b1` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking contradiction in the plan's own gates, 1 correctness fix on an observability path)
**Impact on plan:** Both preserve the plan's stated intent exactly; neither changes behaviour the plan specified nor adds scope.

## Issues Encountered

- **Verifying which copy of the package the tests import.** The editable install resolves `orchestrator` to the *main* repo, not this worktree. `pytest` run from the worktree's `orchestrator/` directory imports the worktree copy (confirmed by the RED failures naming the worktree path, and by those same tests going green after only worktree edits), but a standalone script run by absolute path does not. The end-to-end smoke check was re-run with `PYTHONPATH` pinned to the worktree. Worth knowing for anyone verifying this branch by hand.

## Verification Results

| Check | Result |
|---|---|
| `cd orchestrator && python3 -m pytest -q` | **1321 passed, 2 xfailed** (baseline 1302 / 2 — count only went up) |
| `pytest tests/integration/test_tool_chain.py -k TestAuthorityEndToEnd --override-ini="addopts=" -q` | 5 passed, 20 deselected |
| `ruff check orchestrator/ telemetry-service/ web/ …` (CI form, repo root) | All checks passed |
| `ruff format --check orchestrator/ telemetry-service/ web/ …` (CI form, repo root) | 110 files already formatted |
| `grep -c "put_nowait" orchestrator/orchestrator/override_detector.py` | 1 |
| `orchestrator/orchestrator/authority.py` unmodified | Confirmed — empty diff |
| `web/` suite (untouched, regression check) | 91 passed, 1 skipped |
| End-to-end smoke: detector → queue → drain | Override and restore both printed **and** spoken; task cancels cleanly |

## Known Stubs

None. Every code path added here is wired to a live consumer or a live caller.

## Threat Flags

None. This plan adds no network endpoint, no auth path, no file access and no schema change. The drain is read-only with respect to `AuthorityState` (T-02-13-06 holds: no mutator is reachable from the new `main.py` code, and `format_authority_status` takes a plain dict).

## Scope Boundaries Respected

- No edits to `orchestrator/orchestrator/tools.py` or `orchestrator/tests/test_tools.py` (sibling plan 02-11).
- No edits to `web/server.py`, `web/tests/test_chat_ws.py` or `web/tests/test_turn_probe.py` (sibling plan 02-12; the `_authority_event_pump` half belongs to later plan 02-15).
- No edits to `.planning/STATE.md` or `.planning/ROADMAP.md` (orchestrator-owned).
- `orchestrator/orchestrator/authority.py` untouched — the announcement layer sits over the state machine, never inside it.

## Next Phase Readiness

- **Ready for 02-15.** The `ProactiveEvent` payloads (`type`, `priority`, `message`, `data`) are unchanged, so the browser pump can consume the same queue shape. Note for that plan: `web/server.py` currently builds `OverrideDetector` with no `event_queue`, so it now gets the 32-slot bound — until the pump lands, that queue will fill and log the "no consumer appears to be draining it" WARNING. That is the designed signal, not a regression.
- **Ready for 02-16.** Both consumer names now exist in code (`drain_authority_events`, and `_authority_event_pump` referenced in the `events` docstring), which is what decision 26's update needs to record.
- **Open:** AUTH-06 is half-delivered until 02-15 merges. WR-05 (no reconnect suppression) and IN-02 (AP `*_HOLD` suppression windows) remain deferred to a detector-tuning pass, as the plan's `<notes>` specify.

## Self-Check: PASSED

All claimed artifacts and commits verified on `worktree-agent-a35e6ef9a42674379`:

- Files present: `orchestrator/orchestrator/override_detector.py`, `orchestrator/orchestrator/main.py`, `orchestrator/tests/test_main_authority.py`, `orchestrator/tests/test_override_detector.py`, `.planning/phases/02-authority-safety-layer/02-13-SUMMARY.md`
- Commits present: `b2d9298`, `4b4321b`, `8d513d0`, `930d6b1`
- No file deletions in any commit (`git diff --diff-filter=D` empty for each)
- No untracked files left behind

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-08-02*
