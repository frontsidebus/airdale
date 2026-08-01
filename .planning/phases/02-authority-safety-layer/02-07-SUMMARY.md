---
phase: 02-authority-safety-layer
plan: 07
subsystem: safety
tags: [authority, procedures, command-safety, bypass, d-04, d-06, structural-guard]

# Dependency graph
requires:
  - phase: 02-authority-safety-layer
    plan: 04
    provides: set_aircraft_control's authority gate and its frozen advisory/withheld result shapes, consumed here unmodified
  - phase: 02-authority-safety-layer
    plan: 01
    provides: AuthorityLevel / AuthorityState, forwarded per step
provides:
  - "Collaborator-injected ProcedureExecutor (verifier / safety_check / command_history / authority), all keyword-only and optional"
  - "Every procedure step is safety-checked, authority-gated, verified and recorded -- the second write path to SimConnect is closed"
  - "A third step outcome: withheld, distinct from success and failure, which aborts the procedure (D-06)"
  - "ProcedureResult.aborted / abort_reason and per-step withheld / withheld_reason in to_dict()"
  - "Structural guards that fail if procedures.py ever resolves commands or talks to the transport again"
affects: [02-08, 02-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Closing a bypass by routing to the existing chokepoint rather than duplicating the check"
    - "Structural regression guard reading module source, following test_voice.py's precedent"
    - "A third outcome added rather than overloading an existing boolean, so the two abort rationales stay separable"

key-files:
  created: []
  modified:
    - orchestrator/orchestrator/procedures.py
    - orchestrator/tests/test_procedures.py

key-decisions:
  - "Withheld steps carry the reason in withheld_reason and leave error empty, so a withhold is never mistaken for a failure by a consumer reading error"
  - "blocked stays an ordinary failure (continue-on-failure), because it is a safety verdict rather than an authority decision"
  - "Test doubles inject CommandSafetyCheck(rules=[]) rather than a duck-typed stub, keeping the safety_check parameter type-honest"
  - "REQUIREMENTS.md deliberately not modified, following the 02-01 / 02-04 precedent"

requirements-completed: []

# Metrics
duration: ~2h05m wall clock
completed: 2026-08-01
---

# Phase 02 Plan 07: Procedure Re-Route & Abort-on-Withheld Summary

**`ProcedureExecutor` no longer has a path to the sim of its own — every step now goes through `set_aircraft_control`, so the `command_safety` rules that any compound procedure silently bypassed for months are finally applied, and a step the authority gate withholds stops the procedure instead of quietly continuing without the pilot.**

## Performance

- **Duration:** ~2h05m wall clock (2026-08-01T17:32:03Z → 2026-08-01T19:37:08Z)
- **Tasks:** 3
- **Files modified:** 2 (0 created, 2 modified)
- **Tests:** 25 → 38 in `test_procedures.py` (+13), zero assertions deleted

## Accomplishments

- **The second write path is gone.** `_execute_step` previously called `_resolve_command` and handed the result straight to the transport. It now calls `set_aircraft_control` with the four injected collaborators and only translates the returned dict into a `StepResult`. Both the direct transport call and the `_resolve_command` import were removed — `grep -c` reports 0 for each.
- **Every procedure step is now safety-checked**, which is the live defect this plan existed to close. `PROCEDURES["cleanup_after_takeoff"]` starts with gear up; on the ground its first step is now blocked by `gear_up_on_ground` and never reaches the sim. A test asserts `GEAR_UP` is absent from the transmitted commands.
- **`ProcedureExecutor.__init__` takes `verifier`, `safety_check`, `command_history` and `authority`** as keyword-only optionals, mirroring `set_aircraft_control`'s injection list. `claude_client.py:495` constructs it with `sim_client` alone and is unaffected (the thread-through is 02-08's work).
- **A withheld step is a third outcome.** `StepResult` gained `withheld` / `withheld_reason`; both the assisted withhold and the advisory dry run map to it, since neither transmitted anything and neither carries an `error` key. That branch is ordered first in the mapping precisely because testing for `error` would misread both.
- **A withheld step aborts (D-06).** `execute` breaks before the inter-step `asyncio.sleep`, without incrementing `steps_completed`, and logs the procedure, step index, description and reason at WARNING. `ProcedureResult` gained `aborted` / `abort_reason`, and `to_dict()` — the surface Claude reads — reports the abort, the reason, the per-step withheld state and the completed-vs-total counts.
- **Continue-on-failure is untouched.** A failed step still records its error and lets the remaining steps run. Both rationales are now written side by side in the `execute` docstring, naming why they must not be unified.
- **Structural guards added**, following `test_voice.py`'s precedent: `procedures.py` source must contain no transport call and no command resolution of its own, the constructor must keep `authority` (dropping it would silently ungate every procedure), and all four collaborators must stay optional.

## Task Commits

1. **Task 1: Route every procedure step through set_aircraft_control** — `06d9fb3` (fix)
2. **Task 2: Withheld step outcome and abort** — `641c2fb` (feat)
3. **Task 3: Abort path, preserved failure path, structural guard** — `ffcde14` (test)

## Files Created/Modified

- `orchestrator/orchestrator/procedures.py` — imports `AuthorityState` / `CommandHistory` / `CommandSafetyCheck` / `CommandVerifier` and `set_aircraft_control` in place of `_resolve_command`; `StepResult` gains `withheld` / `withheld_reason`; `ProcedureResult` gains `aborted` / `abort_reason` and reports both plus per-step withheld state in `to_dict()`; `ProcedureExecutor.__init__` takes the four keyword collaborators; `execute` gains the abort branch and a rewritten docstring carrying both rationales; `_execute_step` rewritten as a call to the shared tool plus result-dict translation.
- `orchestrator/tests/test_procedures.py` — `_NO_RULES` and `_WarnOnCommand` helpers, `PROCEDURES_SOURCE` for the structural guards, `get_state` wired on the client doubles, and four new classes: `TestAbortOnWithheld` (5), `TestFailureStillContinues` (1), `TestReRouteThroughSafetyCheck` (2), `TestNoDirectTransportRegression` (5).

## Decisions Made

- **A withheld `StepResult` leaves `error` empty** and puts the text in `withheld_reason`. Setting both would let any consumer that branches on `error` treat a restrained step as a failed one, which is the same class of bug 02-04 flagged for `web/server.py`'s `"error" not in tool_result` heuristic.
- **The withheld/advisory branch is checked before the `error` branch.** The advisory and withhold dicts deliberately carry no `error` key, so ordering is what makes the distinction work; the comment in place says so.
- **`blocked` remains an ordinary failure**, so a blocked step keeps the continue-on-failure path. `blocked` is a safety verdict about one command, not a decision that MERLIN should stop acting — conflating it with a withhold would abort procedures for reasons D-06 never intended. A test pins this (`test_blocked_step_is_a_failure_not_a_withhold`).
- **Test doubles inject `CommandSafetyCheck(rules=[])`** rather than a duck-typed stub. The real class already takes its rules by injection, so an empty rule set is a clean, type-honest "no safety rules" without subclassing. `_WarnOnCommand` does subclass, for the same type-honesty reason 02-04 gave.
- **`test_go_around_sends_throttle_value` now injects the empty rule set.** Go-around retracts the gear and the default `SimState()` is on the ground, so the real checker blocks step 3 — correct product behaviour, but it would make that test assert the wrong thing. The gear/ground interaction is covered by the dedicated re-route regression test instead.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Test doubles could not satisfy the re-routed safety check**

- **Found during:** Task 1
- **Issue:** `set_aircraft_control` reads live telemetry via `sim_client.get_state()` to run the safety check. The existing doubles were bare `AsyncMock()`s, so `get_state()` returned a mock rather than a `SimState`, and every step failed with `'coroutine' object has no attribute 'strip'` inside `resolve_aircraft_type`. Six pre-existing tests failed. Task 1's own `<verify>` block could not pass without fixing this.
- **Fix:** Set `client.get_state.return_value = SimState()` on the shared `_make_client` helper and on the one test that builds its own client; injected an empty rule set into the go-around test, whose gear-up step the real checker correctly blocks on the ground.
- **Files modified:** `orchestrator/tests/test_procedures.py`
- **Commit:** `06d9fb3`
- **Note:** The plan assigned `test_procedures.py` to Task 3, so Task 1 touched a file outside its declared `<files>`. Unavoidable — the re-route cannot be verified green without it, and deferring would have left Task 1's commit red.

**Total deviations:** 1 (Rule 3). No bugs found in prior-wave code; no architectural changes; nothing required a checkpoint.

## Issues Encountered

- **`httpx_ws` is absent from the orchestrator venv**, so `web/tests` errors on collection when run with `orchestrator/.venv/bin/python3`. The web suite runs on the **system** `python3`, which has it. Verified 55 passed / 1 skipped there — unchanged from the wave-2 baseline. Unrelated to this plan; worth knowing for the next worktree agent that runs all three suites with one interpreter.
- **The worktree has no `.venv` of its own** (`orchestrator/.venv` exists only in the main repo). Used the main repo's interpreter with the worktree as cwd; pytest's prepend import mode puts the worktree's `orchestrator/` first, confirmed by `inspect.getfile` resolving to the worktree path.
- **Plan `<verify>` blocks `cd` to the main repo path**, same as noted in 02-01 and 02-04. Ran from the worktree root instead; commands otherwise unchanged.
- **The base commit given in the spawn prompt (`cfcf1d5`) was ahead of the worktree's initial HEAD** (`80f22bf`), so the documented `git reset --hard` in the branch check applied. HEAD was on `worktree-agent-aa847648caf2d3d03` and the working tree was clean, so the reset was safe.

## Verification

- `pytest tests/test_procedures.py -q` — **38 passed** (baseline 25; +13, criterion was ≥7)
- `pytest tests/ -q` (orchestrator) — **1232 passed, 2 xfailed** (wave-2 baseline 1219 + 13 new; nothing decreased)
- `pytest web/tests -q -c web/pyproject.toml --rootdir web` — **55 passed, 1 skipped** (unchanged; system python3)
- `pytest telemetry-service/tests -q --rootdir telemetry-service` — **38 passed** (unchanged)
- `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore SIM105,SIM117,F841,B008,B017,B007,UP041` — All checks passed
- `ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml` — 107 files already formatted
- `grep -c "self._sim_client.send_command" orchestrator/orchestrator/procedures.py` — **0**
- `grep -c "_resolve_command" orchestrator/orchestrator/procedures.py` — **0**
- `grep -c "set_aircraft_control" orchestrator/orchestrator/procedures.py` — **4**
- `inspect.signature(ProcedureExecutor.__init__).parameters` — `['self', 'sim_client', 'verifier', 'safety_check', 'command_history', 'authority']`
- `dataclasses.fields(StepResult)` — includes `withheld`, `withheld_reason`; `ProcedureResult` — includes `aborted`, `abort_reason`
- Advisory + 3-step procedure — `steps_completed == 0`, `success is False`, `aborted is True`, `len(step_results) == 1`, transport never called
- `git diff cfcf1d5 -- orchestrator/tests/test_procedures.py | grep "^-"` — 2 deleted lines, both replaced in place (a docstring expanded, one constructor gaining a keyword); **no assertion deleted**

### `send_command` grep, as required by the success criteria

`grep -rn "send_command" orchestrator/orchestrator/` now returns:

| File | Nature |
|---|---|
| `sim_client.py` | The real definition and its docstrings — legitimate |
| `tools.py` | The single call site (line 450) plus docstrings — legitimate |
| `config.py` | One **docstring** mention added by 02-01, not a call site |

`procedures.py` no longer appears. The criterion's literal wording ("only `sim_client.py` and `tools.py`") is met in substance; `config.py`'s prose reference predates this plan and lies outside its `files_modified` scope, so it was deliberately left alone. It was already recorded as a known artefact in the 02-04 summary.

## Known Stubs

None. The re-route, the withheld outcome and the abort are fully implemented and exercised.

One deliberate scope boundary worth naming: `ProcedureExecutor` accepts `authority` but no production caller passes it yet — `claude_client.py:495` still constructs it with `sim_client` alone, so procedures run at `full` in a wired process today. That is 02-08's thread-through, exactly as `set_aircraft_control`'s own gate awaited it in 02-04. The plumbing here is complete and tested; only the composition root is outstanding.

## Threat Flags

None. This plan adds no network endpoint, auth path, file access or schema at a trust boundary — it removes a path. All five `mitigate` dispositions in the plan's register are implemented and tested:

- **T-02-07-01** (procedures reaching SimConnect unchecked) — routed through the tool; structural guard pins it closed.
- **T-02-07-02** (continuing past a withheld step) — the loop breaks; `len(step_results) == 1` asserted for a 3-step abort.
- **T-02-07-03** (bypassing the system enum via a named procedure) — the gate now applies per step regardless of how the step was reached.
- **T-02-07-04** (abort leaving a worse configuration) — accepted as planned; continue-on-failure preserved for genuine failures and pinned by test.
- **T-02-07-05** (reporting an aborted procedure as complete) — `to_dict()` carries `aborted`, `abort_reason`, per-step `withheld`, and both counts.

## Notes for the Orchestrator

- STATE.md and ROADMAP.md were **not** modified (worktree mode; the orchestrator owns those writes post-wave).
- REQUIREMENTS.md was **not** modified either, following the 02-01 / 02-04 precedent. This plan's frontmatter names **AUTH-01** and **AUTH-03**, and both are now enforced on the procedure path as well as the direct tool path — but neither is observable in flight until a composition root injects a real `AuthorityState` (02-08 / 02-09). Today `claude_client.py` still constructs `ProcedureExecutor(sim_client)` with no authority, so every procedure runs at `full`. Marking them complete now would over-claim, and every wave-3 plan touching the same file would conflict. **Recommend marking after the wave merges and 02-08 lands.**
- Cross-plan note for **02-08**: `ProcedureExecutor` is constructed at `claude_client.py:495`. Passing `authority=` (and ideally the other three collaborators) there is what makes this plan's gate live in a wired process. The constructor's keywords are optional, so the change is additive.
- Cross-plan note for **02-09**: `ProcedureResult.to_dict()` now emits `aborted`, `abort_reason` and per-step `withheld` / `withheld_reason`. The web layer's `success = "error" not in tool_result` heuristic has the same blind spot for procedures as it does for single commands — an aborted procedure carries no `error` key at the top level, and `success` is already `False`, but the *reason* only appears in `abort_reason`.

## Next Phase Readiness

Ready. Downstream plans can rely on:

- `ProcedureExecutor(sim_client, *, verifier=, safety_check=, command_history=, authority=)`, all keyword-only and defaulting to `None`.
- Procedure steps behaving exactly as direct `set_aircraft_control` calls, including the CMD-08 refusal (`PROCEDURES["takeoff_config"]` contains a `fuel_pump on` step, which now returns the refusal rather than a blind toggle).
- `ProcedureResult.to_dict()` keys: `procedure`, `success`, `steps_completed`, `steps_total`, `aborted`, `abort_reason`, and per-step `description` / `command` / `success` / `error` / `withheld` / `withheld_reason`.

## Self-Check: PASSED

- Files claimed modified: both present on disk (`orchestrator/orchestrator/procedures.py`, `orchestrator/tests/test_procedures.py`).
- Commits claimed: `06d9fb3`, `641c2fb`, `ffcde14` all present in `git log`.
- No file deletions in any of the three commits; no untracked files left behind.

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-08-01*
</content>
</invoke>
