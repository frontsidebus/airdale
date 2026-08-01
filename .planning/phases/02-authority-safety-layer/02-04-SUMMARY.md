---
phase: 02-authority-safety-layer
plan: 04
subsystem: safety
tags: [authority, gate, command-safety, tools, cmd-08, dry-run, fail-safe]

# Dependency graph
requires:
  - phase: 02-authority-safety-layer
    plan: 01
    provides: AuthorityLevel / AuthorityReason / AuthorityState, consumed here without modification
provides:
  - "`authority` keyword parameter on set_aircraft_control and undo_last_command"
  - "The three-level authority gate at the single pre-transmit chokepoint (D-03)"
  - "Frozen result-dict shapes for the advisory dry run and the assisted withhold (consumed by 02-07 and 02-09)"
  - "CMD-08 refusal: carb_heat / fuel_pump absolute on/off can no longer emit a blind toggle"
  - "docs/SMART_CONTROLS.md Authority reference incl. the D-08a assisted coverage caveat"
affects: [02-05, 02-07, 02-08, 02-09, 02-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Policy decision placed where its inputs already exist, rather than at the call site"
    - "Backward-compatible default made loud: authority=None behaves as full but emits a deduped WARNING"
    - "Log-dedupe bool is explicitly not a singleton -- documented in-place so it is not mistaken for one"

key-files:
  created: []
  modified:
    - orchestrator/orchestrator/tools.py
    - orchestrator/tests/test_tools.py
    - docs/SMART_CONTROLS.md

key-decisions:
  - "The gate returns level and reason from a helper read once at the decision point; nothing is cached, so the send_command floor's independent re-read stays meaningful (T-02-04-07)"
  - "CMD-08 refusal keyed off a module-level dict rather than an inline tuple, so the two systems and their labels have one definition"
  - "The undo authority test injects a clean stub safety check -- the default SimState is on-ground, so a real GEAR_UP undo is blocked before the gate is reached"
  - "Documented the authority gate as step 2 of the command pipeline and renumbered the rest, rather than appending an isolated section"

requirements-completed: []

# Metrics
duration: 21min
completed: 2026-08-01
---

# Phase 02 Plan 04: Authority Gate & CMD-08 Refusal Summary

**The authority policy decision now sits at the one point where the resolved command, live telemetry and the safety verdict all exist and nothing has been transmitted — advisory describes, assisted withholds on a flagged verdict, full executes, `blocked` wins everywhere — and `carb_heat` / `fuel_pump` refuse an absolute on/off instead of emitting a toggle that does the opposite of what was asked.**

## Performance

- **Duration:** ~21 min
- **Started:** 2026-08-01T16:55:00Z
- **Completed:** 2026-08-01T17:16:00Z
- **Tasks:** 3
- **Files modified:** 3 (0 created, 3 modified)

## Accomplishments

- `set_aircraft_control` gained `authority: AuthorityState | None = None` as a trailing keyword, matching the existing `verifier` / `safety_check` / `command_history` injection style, and `undo_last_command` threads it through (an undo is a command; at advisory it is described, not sent).
- The gate sits between the safety `blocked` short-circuit and `send_command`. All three levels behave as specified, and **`blocked` still wins at every level** — the short-circuit was neither moved nor duplicated, and three of the nine matrix cells assert it.
- The advisory dry run and the assisted withhold both return flat dicts carrying **no `error` key**, so `web/server.py`'s `success = "error" not in tool_result` heuristic will not render a restrained command as a failure once 02-09 branches on the markers.
- `authority=None` is byte-identical to explicit `FULL` — proven by a test comparing both returned dicts and both `send_command` await args — but is no longer silent: one deduped WARNING names the missing injection and points at the `send_command` floor as the remaining guard. No module-level authority singleton was introduced (D-09), and a structural test asserts the rejected `_authority = AuthorityState` / `authority or _authority` shapes are absent.
- `AuthorityState.degraded_fallback(...)` reaches the gate as **advisory with reason `degraded`**, proving the phase's fail-safe path lands restrained rather than reading as `full`.
- CMD-08 closed by refusal: `carb_heat` / `fuel_pump` with `on` or `off` return an explicit cannot-confirm-position error with `unresolvable: True` and no transmission; `toggle` is untouched. `_resolve_command` remains a pure lookup with its original `tuple[str | None, int]` signature and single failure channel.
- 25 new tests (84 → 109 in `test_tools.py`), with **zero deletions** in the file — the 8 pre-existing `TestSetAircraftControl` tests are unmodified and still pass.
- The `assisted` coverage gap is written down rather than shipped silently: `DEFAULT_RULES` has 7 rules covering 4 of the 20 commandable systems, so `assisted` is a no-op for the other 16 including `mixture`, `fuel_selector`, `crossfeed` and `deice`.

## Task Commits

1. **Task 1: Authority parameter and three-level gate** — `41d53bf` (feat)
2. **Task 2: carb_heat / fuel_pump on-off refusal** — `7010020` (fix)
3. **Task 3: Level-by-severity matrix and the assisted coverage gap** — `d0b7b23` (test)

## Files Created/Modified

- `orchestrator/orchestrator/tools.py` — imports `AuthorityLevel` / `AuthorityReason` / `AuthorityState`; adds `_warned_missing_authority` (log-dedupe bool, commented in place as explicitly *not* a stand-in for authority), `UNCONFIRMABLE_POSITION_SYSTEMS`, `_resolve_authority()`, `_describe_intent()`; adds the `authority` parameter and gate to `set_aircraft_control` and the CMD-08 refusal; threads `authority` through `undo_last_command`.
- `orchestrator/tests/test_tools.py` — `_control_client()` helper, `_StubSafetyCheck` (subclasses `CommandSafetyCheck` so the injection stays type-honest), and five new classes: `TestUnconfirmablePositionRefusal` (7), `TestAuthorityGateMatrix` (9), `TestAuthorityAdvisoryDryRun` (4), `TestAuthorityWithhold` (1), `TestAuthorityNoneEquivalentToFull` (3), `TestUndoThreadsAuthority` (1).
- `docs/SMART_CONTROLS.md` — new `## Authority` section (levels table keyed to the blocked/warning severity model, the four reasons and how each clears, why `degraded` is a reason and not a fourth level, the D-08a coverage caveat with concrete numbers, and the CMD-08 refusal with its workaround); authority added to the source-file list and inserted as step 2 of the Command Pipeline Overview with the remaining steps renumbered.

## Decisions Made

- **The undo advisory test injects a clean stub safety check.** The first draft used the real checker, and the default `SimState()` is on-ground, so the `GEAR_UP` undo was `blocked` before the gate was ever reached. That is correct product behaviour (blocked wins), but it made the test assert the wrong thing. Injecting a clean verdict isolates the authority thread-through, which is what the test is for.
- **`_StubSafetyCheck` subclasses `CommandSafetyCheck`** rather than duck-typing, so the `safety_check=` parameter's declared type stays honest and the stub cannot drift from the real `check()` signature.
- **The CMD-08 refusal reads its systems from a module-level dict** (`UNCONFIRMABLE_POSITION_SYSTEMS`) mapping system to the human label used in the error, so the two systems and their phrasing have exactly one definition. The rationale comment names CMD-08 and D-02 and says plainly not to "fix" it back into a toggle.
- **The gate helper returns `(level, reason)` rather than storing them.** Reading through a helper keeps the single-read property the threat model depends on (T-02-04-07) while keeping the gate body readable.
- **Documented the gate inside the existing pipeline diagram** rather than as a standalone section, so a reader following the command flow cannot miss it. This required renumbering steps 4–6 to 5–7.

## Deviations from Plan

None requiring a deviation rule. No bugs, missing critical functionality, or blocking issues were encountered; nothing was auto-fixed. Every acceptance criterion in all three tasks was verified as written.

**Total deviations:** 0
**Impact on plan:** None.

## Issues Encountered

- **Ruff I001 + a format diff on `test_tools.py`,** caught by the CI-parity commands before commit. isort classifies `from orchestrator import tools as tools_module` as *first-party* while the pre-existing `from orchestrator.command_verifier import ...` lines sit in the third-party block, so the new import is placed in its own trailing block. Accepted ruff's fix — that is what CI wants. This is precisely the CLAUDE.md hazard: `ruff check .` from inside `orchestrator/` resolves isort's `src` differently and would have disagreed.
- **Plan `<verify>` blocks `cd` to the main repo path** (`/mnt/c/Users/bould/source/airdale`), same as noted in 02-01. Run from the worktree root instead; the commands are otherwise unchanged.
- **The editable install points at the main repo,** so a bare `python3 -c "import orchestrator.tools"` from the worktree resolves to `/mnt/c/Users/bould/source/airdale/orchestrator/...`, not the worktree copy. pytest is unaffected (prepend import mode inserts the worktree's `orchestrator/` at `sys.path[0]`, verified explicitly), but ad-hoc acceptance-criteria one-liners need `PYTHONPATH=orchestrator`. Worth knowing for any later worktree agent that verifies by one-liner rather than by test.

## Verification

- `python3 -m pytest orchestrator/tests/test_tools.py -q` — **109 passed** (pre-plan baseline 84; +25, criterion was ≥16)
- `python3 -m pytest orchestrator/tests/test_tools.py -q -k "matrix or authority"` — **18 collected and passed** (criterion was ≥9)
- `python3 -m pytest orchestrator/tests/ -q` — **1186 passed, 2 xfailed** (wave-1 baseline 1161 + 25 new; nothing decreased)
- `python3 -m pytest orchestrator/tests/test_procedures.py -q` — passes unchanged (procedures are re-routed in 02-07, not here)
- `python3 -m pytest web/tests -q -c web/pyproject.toml --rootdir web` — **55 passed, 1 skipped** (unchanged)
- `python3 -m pytest telemetry-service/tests -q --rootdir telemetry-service` — **38 passed** (unchanged)
- `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore SIM105,SIM117,F841,B008,B017,B007,UP041` — All checks passed
- `ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml` — 107 files already formatted
- `inspect.signature(set_aircraft_control).parameters` ends with `authority`
- `grep -c "_authority = AuthorityState\|authority or _authority" orchestrator/orchestrator/tools.py` — **0**
- `grep -c "authority" orchestrator/orchestrator/claude_client.py` — **0**, unchanged by this plan (thread-through is 02-08's work)
- `git diff --numstat orchestrator/tests/test_tools.py` — **371 insertions, 0 deletions**; the 8 pre-existing `TestSetAircraftControl` tests are untouched
- `grep -ci "assisted" docs/SMART_CONTROLS.md` — 7; `grep -ci "degraded"` — 3; `grep -c "carb_heat"` — 3
- `grep -rln "send_command" orchestrator/orchestrator/` — `sim_client.py`, `tools.py`, `procedures.py` (as expected; procedures closes in 02-07) plus `config.py`, which is a **docstring mention** in the `authority_command_timeout_s` description added by 02-01, not a call site

### The nine matrix cells, as pinned by test

| Level | Severity | Sent? | Result marker |
|---|---|---|---|
| full | `""` | yes | — |
| full | `warning` | yes | `safety_warning` |
| full | `blocked` | no | `blocked` |
| assisted | `""` | yes | — |
| assisted | `warning` | **no** | `withheld` |
| assisted | `blocked` | no | `blocked` |
| advisory | `""` | **no** | `advisory` |
| advisory | `warning` | **no** | `advisory` (warning in `safety`) |
| advisory | `blocked` | no | `blocked` |

## Known Stubs

None. The gate is fully implemented and exercised. The remaining authority surface is out of scope for this plan by design and lands downstream: the level floor in `TelemetryClient.send_command` (02-05), the `ProcedureExecutor` re-route (02-07), the `ClaudeClient` / `main.py` thread-through (02-08), the web `lifespan` + `_on_tool_result` branch (02-09), and the UI badge (02-10).

## Threat Flags

None. This plan adds no network endpoint, auth path, file access or schema at a trust boundary. Both boundaries it touches are already in the plan's register, and all seven `mitigate` dispositions are implemented and tested: T-02-04-01 (loud `None` default + no singleton, structural test), -02 (code-only enforcement; `TOOL_DEFINITIONS` and the `cache_control` prefix untouched), -03 (`blocked` wins — three matrix cells), -04 (explicit `advisory` / `withheld` markers, no `error` key), -05 (CMD-08 refusal), -06 (no per-level tool list), -07 (single uncached read at the gate).

## Notes for the Orchestrator

- STATE.md and ROADMAP.md were **not** modified (worktree mode; the orchestrator owns those writes post-wave).
- REQUIREMENTS.md was **not** modified either, following 02-01's precedent. AUTH-02, AUTH-03, AUTH-04 and CMD-08 are delivered *in the gate* here, but none is observable in flight until the composition roots inject a real `AuthorityState` (02-08 / 02-09) — today every production caller still passes `None` and gets `full`. AUTH-01 is likewise partial. Marking them complete now would over-claim, and every wave-2 plan touching the same file would conflict. **Recommend deferring the mark-complete until the wave merges.**
- One cross-plan note for 02-05: the gate deliberately does **not** cache `authority.level`. The floor in `send_command` must perform its own independent read, or the two-layer time-of-check/time-of-use argument in T-02-04-07 collapses to a single read.
- One cross-plan note for 02-09: the advisory and withhold dicts carry **no `error` key** by design. `_on_tool_result` currently computes `success = "error" not in tool_result`, so without an explicit `tool_result.get("advisory")` / `.get("withheld")` branch a restrained command will render to the pilot as if it executed — which is threat T-02-04-04.

## Next Phase Readiness

Ready. Downstream plans can rely on:

- `set_aircraft_control(..., authority=<AuthorityState>)` and `undo_last_command(..., authority=<AuthorityState>)` both accepting the state as a trailing keyword.
- The frozen result keys: `advisory` / `would_execute` / `withheld` / `authority_level` / `authority_reason` / `safety.{severity,reason}` / `message`, plus the CMD-08 `unresolvable`.
- `blocked` continuing to short-circuit ahead of the gate, so no downstream layer needs to re-establish that precedence.

## Self-Check: PASSED

- Files claimed modified: all 3 present on disk (`orchestrator/orchestrator/tools.py`, `orchestrator/tests/test_tools.py`, `docs/SMART_CONTROLS.md`).
- Commits claimed: `41d53bf`, `7010020`, `d0b7b23` all present in `git log`.
- No file deletions in any of the three commits; no untracked files left behind.

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-08-01*
