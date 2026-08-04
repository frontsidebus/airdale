---
phase: 02-authority-safety-layer
plan: 11
subsystem: safety
tags: [authority, command-safety, undo, false-confirmation, tdd, pytest]

# Dependency graph
requires:
  - phase: 02-authority-safety-layer
    provides: "the authority gate in set_aircraft_control, the level floor in TelemetryClient.send_command, and the advisory/withheld result shapes (02-04, 02-05)"
provides:
  - "`_was_transmitted(result)` — the single 'did this reach the aircraft' predicate for the orchestrator half of the command path"
  - "`safety_note` attached only to a command the adapter acknowledged (CR-02 closed)"
  - "an undo that pops the history record only after a confirmed transmission, and describes an untransmitted reversal in the conditional (CR-03 closed)"
  - "`assisted` withholds on an absent safety verdict, with its own `no_verdict` marker (WR-10 part 1 closed)"
affects: [02-12 (web/server.py mirrors _was_transmitted for the browser), phase verification re-run, any future caller that reports a command outcome]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One named predicate for 'was it transmitted', consumed by every reporting site rather than restated inline"
    - "Discriminate an absent safety verdict on `safety_result is None`, never on the severity string"
    - "Mutate the undo stack only after the reversal is confirmed on the wire"

key-files:
  created: []
  modified:
    - orchestrator/orchestrator/tools.py
    - orchestrator/tests/test_tools.py

key-decisions:
  - "Rejected 02-REVIEW.md's proposed WR-10 fix (`safety_severity in (\"warning\", \"\")`): a clean SafetyResult also carries severity == \"\", so that form withholds every command at assisted. Discriminated on `safety_result is None` instead, and added a structural test that keeps the broken form out of the file."
  - "`_was_transmitted` requires both `success` truthy AND no `error` key. Either half alone misses a real shape: `success` alone misses the floor refusal and the ack timeout; `error`-absence alone misses the negative adapter ack, which sim_client.py documents as routine."
  - "A dict carrying neither key — and a contradictory dict carrying both — fails closed."
  - "The no-verdict withhold gets its own `no_verdict` marker and its own wording rather than reusing the warning branch, so 'a rule fired' and 'I cannot see the aircraft' stay distinguishable in the dict Claude relays."
  - "The absence of `undone_command` is the signal that a reversal did not happen; the not-transmitted branch sets `undo_target` plus a 'Would reverse ...' description instead."
  - "`full` deliberately still executes when telemetry is unavailable (AUTH-04 unchanged); the blast radius of the new withhold is the level that opted into caution."

patterns-established:
  - "Reporting predicates are named and shared, not restated: `undo_last_command` consumes `_was_transmitted` rather than re-deriving the condition"
  - "Regression assertion messages name the finding they pin (CR-02 / CR-03 / WR-10) and state the operational consequence, matching web/tests/test_chat_ws.py's `_B8_REGRESSION` house style"

requirements-completed: [AUTH-02, AUTH-03]

# Metrics
duration: 13min
completed: 2026-08-01
---

# Phase 02 Plan 11: Stop Reporting Things That Did Not Happen Summary

**One shared `_was_transmitted` predicate now gates every "it happened" claim in `tools.py`: a refused, NACKed or untransmitted critical command carries no "executed" note, an untransmitted undo leaves the command undoable and says so in the conditional, and `assisted` withholds when telemetry gave it no verdict at all.**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-08-02T00:22Z
- **Completed:** 2026-08-02T00:35Z
- **Tasks:** 2 (both TDD: RED → GREEN)
- **Files modified:** 2

## Accomplishments

- **`_was_transmitted(result)`** added next to `_resolve_authority`, with a docstring explaining why both halves of `bool(result.get("success")) and "error" not in result` are load-bearing and naming `web/server.py::_on_tool_result` as the mirror site that must not drift (threat T-02-11-05, plan 02-12 lands that half).
- **CR-02 closed:** `safety_note = "Critical system change executed"` is now attached only when `command in CRITICAL_COMMANDS and _was_transmitted(result)`. A gear command the adapter NACKed, or one the authority floor refused, no longer reports a critical system change in the same dict whose `error` says nothing was sent.
- **CR-03 closed:** `undo_last_command` peeks with `last_command`, attempts the reversal, and calls `pop_last()` only on a confirmed transmission. At advisory, on an assisted withhold, on a safety block, on an adapter NACK and on a floor refusal, the record survives and the result carries `undo_target` + `"Would reverse ..."` with **no** `undone_command` key.
- **WR-10 part 1 closed:** `assisted` now withholds when `safety_result is None`, returning `no_verdict: True`, an empty severity with reason `"telemetry unavailable -- no safety verdict"`, and a message that says MERLIN cannot see the aircraft's state, has no verdict, sent nothing, and can be told to go ahead — without ever claiming a safety warning fired.
- **24 new tests** covering the predicate (11 parametrised shapes), the three false-confirmation paths, the no-verdict path, and the "clean verdict still executes" / "`full` unchanged" counter-cases. Suite went 1302 → 1334 passing (32 new test cases counting parametrisation), 2 xfailed, unchanged.

## Task Commits

Each task was committed atomically (TDD: test → fix):

1. **Task 1 (RED): failing tests for the predicate and the assisted no-verdict path** — `c8c3c10` (test)
2. **Task 1 (GREEN): `_was_transmitted`, gated `safety_note`, assisted no-verdict withhold** — `8fa840a` (fix)
3. **Task 2 (RED): failing tests for the undo record surviving an untransmitted reversal** — `bb7760e` (test)
4. **Task 2 (GREEN): pop the undo record only once the reversal is on the wire** — `ce87653` (fix)

No REFACTOR commit was needed: both implementations landed at their final shape.

## Files Created/Modified

- `orchestrator/orchestrator/tools.py` — added `_was_transmitted`; gated the `safety_note` attach on it; added the `has_safety_verdict` local and the assisted no-verdict withhold branch; rewrote the tail of `undo_last_command` so the history mutation follows the transmission; updated both docstrings.
- `orchestrator/tests/test_tools.py` — added `TestWasTransmitted`, `TestCriticalSafetyNoteRequiresTransmission`, `TestAssistedWithholdsWithoutAVerdict`, and eight new cases in `TestUndoThreadsAuthority`; added `_CR02_REGRESSION` / `_WR10_REGRESSION` / `_CR03_REGRESSION` assertion messages and the `_history_with_gear_down` / `_blind_client` helpers; corrected `test_undo_at_advisory_sends_nothing`, which previously asserted `undone_command == "GEAR_DOWN"` and thereby pinned the defect.

## Decisions Made

Captured in the frontmatter `key-decisions`. The load-bearing one: the plan's instruction to **reject** `02-REVIEW.md`'s WR-10 fix was correct and is now enforced mechanically. `TestAssistedWithholdsWithoutAVerdict::test_the_broken_review_fix_is_not_present` reads `tools.py` and fails if the string `safety_severity in ("warning", "")` ever appears, because a clean verdict also renders as `""` and that form would withhold every assisted command including the ones that checked out.

## Deviations from Plan

**None affecting behaviour — plan executed as written.** Two mechanical adjustments worth recording:

**1. [Rule 3 - Blocking] Reworded an explanatory comment that tripped my own structural guard**
- **Found during:** Task 1 (GREEN)
- **Issue:** The comment explaining *why* the review's form is wrong quoted it literally, so `test_the_broken_review_fix_is_not_present` (and the plan's `grep` acceptance criterion) failed on the comment rather than on real code.
- **Fix:** Reworded the comment to describe the broken form without quoting it.
- **Files modified:** `orchestrator/orchestrator/tools.py`
- **Verification:** `grep -c 'safety_severity in ("warning", "")' orchestrator/orchestrator/tools.py` → 0 matches; the guard test passes.
- **Committed in:** `8fa840a`

**2. [Rule 3 - Blocking] `AutopilotState` added to the test module's imports**
- **Found during:** Task 2 (RED)
- **Issue:** The value-suffix test needs a `HEADING_BUG_SET` record with a prior heading, and `AutopilotState` was not among `test_tools.py`'s existing `sim_client` imports.
- **Fix:** Added it to the existing import block.
- **Files modified:** `orchestrator/tests/test_tools.py`
- **Verification:** Module collects; test passes.
- **Committed in:** `bb7760e`

Also ran `ruff format` on `orchestrator/tests/test_tools.py` (it preferred single-quoted outer strings for one regression message containing escaped double quotes) — committed with Task 2.

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking, both mechanical).
**Impact on plan:** None. No scope creep; no file outside `files_modified` was touched.

## Verification

All of the plan's `<verification>` items were run and pass:

| Check | Command | Result |
|---|---|---|
| Full orchestrator suite | `cd orchestrator && python3 -m pytest -q` | `1334 passed, 2 xfailed` (baseline 1302 + 2 xfailed — count only went up) |
| End-to-end authority chain | `python3 -m pytest tests/integration/test_tool_chain.py -k TestAuthorityEndToEnd --override-ini="addopts=" -q` | `5 passed, 20 deselected` |
| CI-parity lint | `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore ...` | `All checks passed!` |
| CI-parity format | `ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml` | `109 files already formatted` |
| No new `send_command` call site | `grep -rn "send_command" orchestrator/orchestrator/ \| grep -v sim_client.py` | one call, still at `tools.py:522` inside `set_aircraft_control`; every other hit is prose |
| Cross-check (not required) | `cd web && python3 -m pytest -q` | `91 passed, 1 skipped` — the new `no_verdict` key rides along on the existing `withheld` marker and changes no browser classification |

Structural acceptance criteria: `def _was_transmitted(` at `tools.py:275`; `_was_transmitted(result)` inside the `CRITICAL_COMMANDS` condition at `:545` and in `undo_last_command` at `:911`; `has_safety_verdict` at `:429`; `"no_verdict"` at `:513`; `pop_last()` at `:923` is after the `set_aircraft_control(` call at `:898`; the review's broken form appears nowhere in the file.

## Issues Encountered

None beyond the two mechanical blockers above. The RED phase behaved as intended in both tasks — Task 1's RED was an `ImportError` on the not-yet-existing predicate, Task 2's RED was six genuine assertion failures each printing the CR-03 consequence.

## Known Stubs

None. No placeholder values, no unwired data paths, no TODO/FIXME markers introduced.

## Threat Flags

None. No new network endpoint, auth path, file access pattern or schema change; the only new key on an existing result shape (`no_verdict`) narrows what the process claims rather than widening what it does. Every threat in the plan's register with disposition `mitigate` (T-02-11-01 through T-02-11-05) has a corresponding test.

## User Setup Required

None — no external service configuration, no new dependency (T-02-11-SC: this plan ran no package-manager command).

## Next Phase Readiness

**Ready.** What downstream work should know:

- **Plan 02-12 must mirror the predicate exactly.** `web/server.py::_on_tool_result`'s fall-through arm still computes `success = "error" not in result` (CR-01). The orchestrator-side expression it should mirror is `bool(result.get("success")) and "error" not in result`; `_was_transmitted`'s docstring names the mirror site so the pair is discoverable from either end.
- **`no_verdict` is available to the browser but not yet rendered.** The withheld frame already reaches `app.js` via the existing `withheld` marker and `message`; a future UI pass could label "no verdict" distinctly from "flagged", but nothing is broken without it.
- **REQUIREMENTS.md was deliberately not edited.** AUTH-02's Gap-1 blocker has two halves and this plan closed the orchestrator one; the browser half is 02-12, running in parallel in this same wave. AUTH-03's WR-10 part 2 (stale-telemetry liveness) is explicitly deferred by this plan's `<notes>`. Checking either box is the orchestrator's or the re-verifier's call once the wave merges — and editing that shared file from a worktree would have raced the sibling agents.
- **Deferred and unchanged, per the plan's `<notes>`:** WR-10 part 2, WR-02, WR-08, WR-11, and CR-01. Gap 2 (`parking_brake` / `FUEL_SELECTOR_OFF` protection) and Gap 3 (the orphaned `OverrideDetector.events` queue) are owned by other plans and were not touched.
- **Documentation nit for a later pass (not actioned, outside `files_modified`):** `docs/AIRCRAFT_CONTROLS.md`, `docs/ARCHITECTURE.md`, `docs/API.md` and `docs/VOICE_PIPELINE.md` say critical commands "trigger a `safety_note` in the tool result" without noting that it is now conditional on the adapter acknowledging the command. Accurate enough to be non-blocking, imprecise enough to be worth a sentence.

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-08-01*
