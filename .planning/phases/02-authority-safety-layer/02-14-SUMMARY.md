---
phase: 02-authority-safety-layer
plan: 14
subsystem: safety
tags: [authority, command-safety, cmd-08, parking-brake, fuel-system, tdd, pytest, docs]

# Dependency graph
requires:
  - phase: 02-authority-safety-layer
    provides: "the authority gate and the safety short-circuit ahead of it (02-04, 02-05); `_was_transmitted` and the gated `safety_note` in tools.py (02-11)"
  - phase: 02-authority-safety-layer
    provides: "CMD-07's adapter registration of FUEL_SELECTOR_* and CROSS_FEED_*, which is what made these rules necessary (02-02)"
provides:
  - "`UNCONFIRMABLE_REFUSED_ACTIONS` — a per-system table of the actions that are refused rather than guessed, replacing a hardcoded on/off tuple"
  - "a `parking_brake` surface that resolves an explicit `toggle` and nothing else"
  - "the unconfirmable-position refusal running BEFORE the unknown-control return, so a refused action gets an explanation rather than a typo message"
  - "six `DEFAULT_RULES` entries covering the fuel selector, mixture, crossfeed and parking-brake commands CMD-07 made executable (DEFAULT_RULES 7 -> 13)"
  - "`PARKING_BRAKE_MAX_GROUND_SPEED_KT` — the 'stopped, or as good as' threshold the brake block is set against"
affects: [02-16 (writes the non-goal reconciliation into REQUIREMENTS.md), phase verification re-run, any consumer reading `command` off an unresolvable result]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A refusal table keyed identically to its label table, pinned together by a test, rather than a hardcoded action tuple at the call site"
    - "Refuse before resolving-to-error: the actionable message must outrank the generic one"
    - "Every new blocked/warning rule ships with an explicit negative test proving it does not fire during normal ground operations"
    - "A severity choice that deviates from the obvious one (crossfeed warns, not blocks) carries its rationale in a source comment next to the rule"

key-files:
  created: []
  modified:
    - orchestrator/orchestrator/tools.py
    - orchestrator/orchestrator/command_safety.py
    - orchestrator/orchestrator/claude_client.py
    - orchestrator/tests/test_tools.py
    - orchestrator/tests/test_command_safety.py
    - orchestrator/tests/test_command_coverage.py
    - docs/AIRCRAFT_CONTROLS.md
    - docs/SMART_CONTROLS.md
    - docs/API.md

key-decisions:
  - "The unconfirmable refusal moved above the `command is None` return. This is required, not cosmetic: once the resolver declines `parking_brake`/`off`, a refusal running after the None guard would report a well-formed request as 'Unknown control' (T-02-14-06). A regression test pins that a genuinely unknown system still gets the unknown-control error."
  - "`command` in the unresolvable result is now `None` for a refused parking-brake action and still the resolved toggle event for carb_heat / fuel_pump. Documented in a source comment and in docs/API.md — a consumer reading that key must tolerate null."
  - "The refusal message dropped its `{action_key}` interpolation ('...whenever it is already off'), which reads wrong for verbs like `release` and `set`. Reworded to '...whenever the parking brake is already where you want it'. Structure preserved, so the carb-heat wording tests pass unmodified."
  - "Crossfeed warns rather than blocks, deviating from 02-VERIFICATION.md's `missing:` wording. Blocking CROSS_FEED_OFF in flight would block the corrective close along with the unsafe one; a warning still makes `assisted` withhold and `full` report the concern. Rationale sits in a comment above the rule."
  - "`FUEL_SELECTOR_SET` non-zero indices are deliberately unruled: which tank an index selects is aircraft-dependent and this layer has no basis to judge it. Only index 0, the OFF position, is blocked."
  - "The parking-brake block reads ground speed but its message reports IAS, because `check()` formats with exactly five keys and `ground_speed` is not one of them. Noted at the rule so the mismatch is not read as a bug."
  - "Phase 2's 'no new envelope rules' non-goal is not breached. CMD-07 — Phase 2's own work — registered eight events that previously NACKed; these six rules restore the posture that change removed and add nothing beyond the surface this phase made reachable. MAGNETO_SET was held back for exactly this hazard."

patterns-established:
  - "Two tables that are read together (`UNCONFIRMABLE_REFUSED_ACTIONS` -> `UNCONFIRMABLE_POSITION_SYSTEMS`) get a test asserting identical keys, because drift between them is a KeyError inside the command path"
  - "A guard test formats every `message_template` in `DEFAULT_RULES` with the five keys `check()` supplies, so a placeholder typo fails at collection time instead of in flight"

requirements-completed: [AUTH-03, AUTH-04, CMD-07, CMD-08]

# Metrics
duration: 34min
completed: 2026-08-01
---

# Phase 02 Plan 14: Bounded Authority for the Commands This Phase Made Reachable Summary

**The one blind toggle a pilot could actually reach is gone — `parking_brake` now resolves an explicit `toggle` and refuses every absolute position with an explanation rather than a guess — and the fuel, mixture and brake commands CMD-07 turned from NACKs into real `TransmitClientEvent` calls now have six rules behind them, so `assisted` is no longer identical to `full` for the surface that can shut an engine down in flight.**

## Performance

- **Duration:** ~34 min
- **Tasks:** 2 (both TDD: RED -> GREEN)
- **Files modified:** 9 (3 source, 3 test, 3 docs)
- **Suite:** orchestrator 1353 -> 1389 passing, 2 xfailed (36 new test cases counting parametrisation)

## Accomplishments

### Task 1 — `parking_brake` stops being a reachable blind toggle (CR-04, CMD-08)

- **`UNCONFIRMABLE_POSITION_SYSTEMS` gains `"parking_brake": "parking brake"`**, with the comment extended to record what makes this entry different from the other two: `carb_heat` and `fuel_pump` are deferred under CMD-09 — absent from the tool enum, absent from the adapter's `CommandMap` — so their defect is latent. The parking brake is in the enum, in `CRITICAL_COMMANDS` and registered in the adapter. "Parking brake off" on landing rollout, with the brake already off, *set* the brake.
- **`UNCONFIRMABLE_REFUSED_ACTIONS: dict[str, frozenset[str]]`** replaces the hardcoded `action_key in ("on", "off")` test. `carb_heat` / `fuel_pump` keep `{on, off}`; `parking_brake` refuses `{on, off, release, set, apply, engage}` — the extra verbs are what a pilot actually says, and a verb that reaches the resolver and finds no branch must still get the actionable refusal.
- **The `parking_brake` resolver branch is restricted to `if action == "toggle"`.** Everything else falls through to the terminal `return None, 0`, so the resolver is now structurally incapable of emitting a blind parking-brake toggle. That is defence in depth under the refusal, not a substitute: `set_aircraft_control` is the only caller today and this branch is what holds the guarantee if a second appears.
- **The refusal block moved above the `command is None` early return.** Required, not cosmetic — see key-decisions. Consequences handled: the returned dict keeps its five keys with `command` now possibly `None`; the `logger.warning` no longer interpolates a command that would print as `None`; the message keeps its structure (cannot confirm the position / a blind toggle does the opposite / use `action='toggle'` / tell me what the panel shows) so the carb-heat wording tests pass untouched.
- **`claude_client.py`** documents the toggle-only action in the `set_aircraft_control` schema, with a comment noting this is a static, deploy-time edit — a one-off prompt-cache invalidation, which is not what D-07 rules out (D-07 rejects varying the tool list *per request*).
- **`RESOLVER_BRANCH_TABLE`** keeps its single `("parking_brake", "toggle", None)` row, now with a comment recording that a reader adding a row for `off` would be re-asserting the defect — and would fail, because `_events_by_system()` asserts every row resolves.

### Task 2 — Six rules for the surface CMD-07 made live (CR-05, AUTH-03, AUTH-04)

`DEFAULT_RULES` goes 7 -> 13, appended so the original seven keep their order and evaluation semantics:

| Rule | Commands | Condition | Severity |
|---|---|---|---|
| `fuel_selector_off_in_flight` | `FUEL_SELECTOR_OFF` | airborne | **blocked** |
| `fuel_selector_set_to_off_in_flight` | `FUEL_SELECTOR_SET` | value `0` and airborne | **blocked** |
| `mixture_cutoff_in_flight` | `MIXTURE_SET` | value `<= 0` and airborne | **blocked** |
| `crossfeed_change_in_flight` | `CROSS_FEED_OPEN/OFF/TOGGLE` | airborne | warning |
| `parking_brake_on_the_roll` | `PARKING_BRAKES` | on ground, GS > 5 kt | **blocked** |
| `parking_brake_in_flight` | `PARKING_BRAKES` | airborne | warning |

- **`PARKING_BRAKE_MAX_GROUND_SPEED_KT = 5.0`** with a comment stating it is a "stopped, or as good as" threshold rather than a taxi speed — a rule set at normal taxi speed would let the rollout case through, which is the case it exists for.
- **A block comment above the six** records the Gap 2 reconciliation in the source, so the reasoning survives where it will be read.
- **Every new rule is gated on being airborne** (or on ground speed), with an explicit negative test for each. Mixture to cut-off on the ground *is* the normal shutdown; fuel selector OFF on the ground is how you secure the aircraft. A rule that refused those would be worse than no rule (T-02-14-05).
- **A guard test formats every `message_template` in `DEFAULT_RULES`** with the five keys `check()` supplies, asserting no `KeyError`. Without it the placeholder contract is discovered only when a rule fires, which is in flight (T-02-14-07).

### Documentation

- **`docs/AIRCRAFT_CONTROLS.md`** — Parking Brake table `*(any)*` -> `toggle`, with the refused verbs, the reason and the workaround; the "closing that gap is Phase 2 authority work" block quote under Critical Commands replaced with the shipped rule table, naming `deice` as the one reachable system still unruled.
- **`docs/API.md`** — `| parking_brake | (any) | -- |` -> `| parking_brake | toggle | -- |`; a new "Returns (unresolvable position)" example documenting the shape and the nullable `command`; the `system` enum list and the actions table brought up to date with `fuel_selector`, `crossfeed` and `deice`, which were missing entirely.
- **`docs/SMART_CONTROLS.md`** — six rows added to the Safety Rules Reference with the crossfeed severity rationale and the ground-operations guarantee; the "Commands MERLIN Refuses Outright" section retitled and extended to all three systems, stating plainly which one was reachable; the Coverage Caveat rewritten from "**7 rules, covering 4 systems**" to "**13 rules, covering 8 systems**", keeping the honest caveat and naming the 12 systems that remain unruled.

## Task Commits

| # | Task | Commit | Type |
|---|---|---|---|
| 1 | Task 1 RED — failing tests for the parking_brake blind toggle | `12388b9` | test |
| 2 | Task 1 GREEN — refusal table, restricted resolver, reorder, schema, docs | `748fcda` | fix |
| 3 | Task 2 RED — failing tests for the six rules | `b8127b5` | test |
| 4 | Task 2 GREEN — the six rules, the threshold constant, docs | `e216e40` | feat |

No REFACTOR commit was needed; both implementations landed at their final shape.

## Files Created/Modified

- `orchestrator/orchestrator/tools.py` — third entry in `UNCONFIRMABLE_POSITION_SYSTEMS` with an extended rationale comment; new `UNCONFIRMABLE_REFUSED_ACTIONS`; `parking_brake` resolver branch restricted to `toggle`; refusal block moved above the unknown-control return, reworded message, reworded log line, comment on the nullable `command` key.
- `orchestrator/orchestrator/command_safety.py` — `PARKING_BRAKE_MAX_GROUND_SPEED_KT`; six condition functions; six `SafetyRule` entries appended to `DEFAULT_RULES`; the Gap 2 / CR-05 block comment.
- `orchestrator/orchestrator/claude_client.py` — one action-description string in the `set_aircraft_control` schema, plus the D-07 comment.
- `orchestrator/tests/test_tools.py` — `TestParkingBrakeRefusal` (7 resolver cases, 8 refusal cases, toggle-still-executes, the unknown-control regression, the two-table sync test) and `_CR04_REGRESSION`.
- `orchestrator/tests/test_command_safety.py` — `TestFuelSelectorSafety`, `TestMixtureSafety`, `TestCrossfeedSafety`, `TestParkingBrakeSafety`, `TestRuleSetShape`; `_CR05_REGRESSION` / `_GROUND_REGRESSION` assertion messages; `_make_state` gains a `ground_speed` override (default `0.0`, so no existing test changes behaviour).
- `orchestrator/tests/test_command_coverage.py` — comment above the single parking-brake row.
- `docs/AIRCRAFT_CONTROLS.md`, `docs/API.md`, `docs/SMART_CONTROLS.md` — as described above.

## Decisions Made

Captured in the frontmatter `key-decisions`. The two load-bearing ones:

**The reorder is the whole reason the fix is usable.** Restricting the resolver without moving the refusal would have swapped one bad outcome for another: instead of setting the brake, MERLIN would tell the pilot "Unknown control: system=parking_brake, action=off" — a typo message for a perfectly well-formed request, with no hint that the refusal was deliberate or that `toggle` exists. `TestParkingBrakeRefusal::test_unknown_system_still_reports_unknown_control` pins the other half so the reorder cannot start swallowing real typos.

**Crossfeed warns rather than blocks, and this deviates from 02-VERIFICATION.md's wording on purpose.** The verification report lists crossfeed among the `missing:` protections without distinguishing severity. Blocking `CROSS_FEED_OFF` in flight would prevent the corrective close — a pilot closing crossfeed to stop cross-feeding from a tank that is running dry gets refused by the safety layer. A warning is sufficient: `assisted` withholds on it (which is the AUTH-03 requirement) and `full` executes with the concern attached. The rationale is in a comment directly above the rule and repeated in `SMART_CONTROLS.md`.

## Deviations from Plan

**Behaviourally, plan executed as written.** Four adjustments worth recording, all inside `files_modified`:

**1. [Rule 1 - Bug] The refusal message's `{action_key}` interpolation was wrong for the new verbs**
- **Found during:** Task 1 (GREEN)
- **Issue:** The existing message ends "...turns the {label} the wrong way whenever it is already {action_key}", which reads correctly for `on`/`off` and nonsensically for `release`, `set`, `apply` and `engage` ("whenever it is already release").
- **Fix:** Reworded that clause to "...does the opposite of what you asked whenever the {label} is already where you want it" — action-agnostic and correct for every verb. The plan's constraint was to keep the message *structure* (cannot confirm the position / blind toggle does the opposite / use `action='toggle'` / tell me what the panel shows), which is preserved.
- **Verification:** The pre-existing carb-heat wording tests (`"current position" in error`, `"toggle" in error`) pass unmodified.
- **Committed in:** `748fcda`

**2. [Rule 2 - Missing critical functionality] Added a test pinning the two unconfirmable tables together**
- **Found during:** Task 1 (RED)
- **Issue:** `set_aircraft_control` looks the action up in `UNCONFIRMABLE_REFUSED_ACTIONS` and then reads the label out of `UNCONFIRMABLE_POSITION_SYSTEMS`. A system present in the first and absent from the second is a `KeyError` raised inside the command path, at the moment a pilot asks for something.
- **Fix:** `test_refused_action_table_covers_every_unconfirmable_system` asserts the two key sets are identical.
- **Committed in:** `12388b9` (test) / `748fcda` (implementation)

**3. [Rule 2 - Missing critical functionality] `docs/API.md` system enum and actions table were missing three live systems**
- **Found during:** Task 1 (docs)
- **Issue:** The `system` parameter description and the "Actions by system" table both stopped at `propeller`, omitting `fuel_selector`, `crossfeed` and `deice` — all three in the tool enum, all three registered in the adapter since CMD-07. Correcting the parking-brake row while leaving a stale enum list beside it would have left the file half-true, against the plan's success criterion that these docs describe the shipped behaviour.
- **Fix:** Added the three to the `system` list and three rows to the actions table.
- **Committed in:** `748fcda`

**4. [Rule 3 - Blocking] `ruff format` reflowed the new test block**
- **Found during:** Task 2 (RED)
- **Issue:** The new assertion messages and multi-line asserts did not match ruff's preferred layout, so the CI-parity `ruff format --check` failed.
- **Fix:** Ran `ruff format` on `orchestrator/tests/test_command_safety.py` before committing.
- **Committed in:** `b8127b5`

---

**Total deviations:** 4 auto-fixed (1 x Rule 1, 2 x Rule 2, 1 x Rule 3). No Rule 4 situations arose.
**Impact on plan:** None. No scope creep beyond the API.md accuracy fix noted above; no file outside `files_modified` was touched; no sibling-owned file (02-15 owns `web/server.py`, `web/static/*`, `web/tests/test_authority_events.py`) was opened.

## Verification

| Check | Command | Result |
|---|---|---|
| Full orchestrator suite | `cd orchestrator && python3 -m pytest -q` | `1389 passed, 2 xfailed` (baseline 1353 + 2 xfailed — count only went up) |
| Cross-language parity guards | `cd orchestrator && python3 -m pytest tests/test_command_coverage.py -v` | 3 passed, none skipped — both `requires_adapter` guards ran against the real `SimConnectManager.cs`, so the CMD-07 fix and the CMD-09 deferral are both intact |
| End-to-end authority chain | `python3 -m pytest tests/integration/test_tool_chain.py -k TestAuthorityEndToEnd --override-ini="addopts=" -q` | `5 passed, 20 deselected` |
| CI-parity lint | `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore ...` | `All checks passed!` |
| CI-parity format | `ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml` | `110 files already formatted` |
| CMD-09 deferral untouched | `grep -rn "MAGNETO_SET\|TOGGLE_STARTER1" adapters/msfs/SimConnectManager.cs` | no output |
| Cross-check (not required) | `cd web && python3 -m pytest -q` | `97 passed, 1 skipped` — unchanged; no browser-visible result shape changed |
| C# adapter suite | `cd adapters/msfs && dotnet test` | **NOT RUN** — `dotnet` is not installed in this execution environment. No C# was changed by this plan, and the Python-side guards that read the adapter source (`test_command_coverage.py`) all pass, so the C#-side parity assertions are unaffected by construction. Flagged for the phase verifier. |

Structural acceptance criteria, all confirmed:

- `UNCONFIRMABLE_REFUSED_ACTIONS` and `"parking_brake": "parking brake"` present in `tools.py`
- `grep -n 'action_key in ("on", "off")' orchestrator/orchestrator/tools.py` -> no output
- the `UNCONFIRMABLE_REFUSED_ACTIONS` lookup is at `tools.py:412`; the `Unknown control:` return is at `:441`
- `python3 -c "... _resolve_command('parking_brake','off',None) == (None, 0) ... ('parking_brake','toggle',None) == ('PARKING_BRAKES', 0)"` exits 0
- `python3 -c "... len(DEFAULT_RULES) == 13"` exits 0
- `grep -n "(any)" docs/API.md docs/AIRCRAFT_CONTROLS.md` -> no output; `docs/API.md` now shows `| parking_brake | toggle | -- |`
- `grep -c "7 rules, covering 4 systems" docs/SMART_CONTROLS.md` -> 0; the section now reads "13 rules, covering 8 systems"

## Reconciling With the Phase Non-Goal

`.planning/REQUIREMENTS.md` records an explicit Phase 2 non-goal: *"no new envelope rules. Those are SAFE-\* territory and already exist."* This plan adds six. That is not a breach, and the reasoning is recorded in three places — a block comment in `command_safety.py`, a paragraph in `docs/SMART_CONTROLS.md`, and here:

CMD-07 — **Phase 2's own work**, in plan 02-02 — registered `FUEL_SELECTOR_OFF`, `FUEL_SELECTOR_ALL/LEFT/RIGHT/SET` and `CROSS_FEED_OPEN/OFF/TOGGLE` in the MSFS adapter's `CommandMap`. Before that change those events NACKed. After it, `TransmitClientEvent` fires for real, and both systems were already in the `set_aircraft_control` enum. The change widened what a named tool call can do to the aircraft.

`MAGNETO_SET` was deliberately held back from exactly that treatment, on the stated grounds that registering it "turns a named tool call into a working in-flight engine shutdown with nothing in front of it". Fuel selector OFF in flight is that same shutdown by another route, and it had *less* in front of it than magnetos would have had: no `DEFAULT_RULES` entry, a default `AUTHORITY_LEVEL` of `full`, and an `assisted` level that cannot withhold what no rule flagged. The reachable set and the deferred set have to follow one severity rationale; before this plan they followed two.

These rules therefore add **no coverage beyond the surface this phase itself made reachable** — they restore the posture this phase's own change removed. A phase that widens the write surface owns the rules for what it widened. **Plan 02-16 writes this qualification into `REQUIREMENTS.md`** so the contradiction is settled on the page rather than rediscovered at the next review.

## Issues Encountered

None beyond the four deviations above. Both RED phases behaved as intended: Task 1's RED produced 15 genuine failures (an `AttributeError` on the not-yet-existing table plus 14 assertion failures) with the 3 already-true cases passing; Task 2's RED produced 8 failures with every negative case already green, which is itself evidence the new rules do not over-fire.

## Known Stubs

None. No placeholder values, no unwired data paths, no `TODO` / `FIXME` markers introduced.

## Threat Flags

None. No new network endpoint, auth path, file access pattern or schema change at a trust boundary. Every threat in the plan's register with disposition `mitigate` has a corresponding test:

| Threat | Mitigation landed | Pinned by |
|---|---|---|
| T-02-14-01 | resolver restricted + refusal + blocked rule above 5 kt GS | `TestParkingBrakeRefusal`, `TestParkingBrakeSafety::test_parking_brake_while_rolling_is_blocked` |
| T-02-14-02 | blocked on `FUEL_SELECTOR_OFF` and `FUEL_SELECTOR_SET` 0 airborne | `TestFuelSelectorSafety` |
| T-02-14-03 | blocked on `MIXTURE_SET <= 0` airborne | `TestMixtureSafety` |
| T-02-14-04 | warning (not blocked) on all three `CROSS_FEED_*` | `TestCrossfeedSafety` |
| T-02-14-05 | every rule gated on airborne / ground speed | one negative test per rule group; `test_selecting_a_named_tank_is_never_flagged` |
| T-02-14-06 | refusal moved above the unknown-control return | `test_unknown_system_still_reports_unknown_control` |
| T-02-14-07 | every template formatted with the five supported keys | `TestRuleSetShape::test_every_message_template_formats_with_the_supported_keys` |
| T-02-14-08 (WR-11) | **accepted, not fixed** — see below |
| T-02-14-SC | no package-manager command was run by this plan | — |

## User Setup Required

None — no external service configuration, no new dependency.

## Next Phase Readiness

**Ready.** What downstream work should know:

- **Plan 02-16 must write the non-goal reconciliation into `REQUIREMENTS.md`.** The text is in the section above and in the `command_safety.py` block comment. Without it, the next reviewer reads six new envelope rules against a written non-goal that forbids them.
- **`command` on an unresolvable result is now nullable.** Any consumer that reads `result["command"]` off a `{"unresolvable": true}` dict must tolerate `None`. Documented in `docs/API.md` and in a source comment. Nothing in the current codebase reads it — `web/server.py` classifies on `error` / `withheld` / `advisory` — but a future renderer might.
- **`deice` is now the one reachable enum system with real consequences and no rule of either severity**, so `assisted` still behaves identically to `full` for it. Named explicitly in both `docs/SMART_CONTROLS.md` and `docs/AIRCRAFT_CONTROLS.md` rather than left implicit. A natural follow-on.
- **`REQUIREMENTS.md`, `STATE.md` and `ROADMAP.md` were deliberately not edited** — worktree mode; the orchestrator owns those writes after the wave merges.
- **Documentation drift I could not reach (reported, not edited):** plan 02-11's executor flagged four `docs/` files describing `safety_note` as unconditional. Two are in my `files_modified` and are corrected — `docs/AIRCRAFT_CONTROLS.md` (line 72) and `docs/API.md` (the "Returns (critical command)" example). **The other two are outside my file scope and remain stale:** `docs/ARCHITECTURE.md:142` ("Critical commands (gear, AP master) trigger a `safety_note` in the tool result") and `docs/VOICE_PIPELINE.md:416` ("Critical system commands (gear, autopilot master, parking brake) are flagged with a `safety_note`"). Both need the same qualifier: the note is attached only when the command was actually transmitted (CR-02). Two one-sentence edits.
- **Deferred, unchanged, with reasons** (per the plan's `<notes>`): **WR-11** — unclamped `*_TRIM_SET` / `FUEL_SELECTOR_SET` values, and the adapter's unchecked `(uint)valEl.GetInt32()` cast in `TelemetryServiceClient.cs`. The orchestrator-side clamp needs per-event SimConnect ranges no artefact in this phase supplies, and the `FUEL_SELECTOR_SET` index range is aircraft-dependent; the more serious half is the C# cast, which turns a negative into its two's-complement `uint`, lives in a file CI never compiles, and cannot be fixed from Python. Needs its own research pass. **WR-02** (`execute_procedure`'s hardcoded 30s deadline) and **WR-12** (a stale comment in `tests/integration/test_tool_chain.py`, which 02-12 will collide with) are likewise untouched. **The longer-term `parking_brake` fix** — adding brake position through the C# struct, the adapter model, the service schema and the mock adapter, then using `PARKING_BRAKE_SET` which takes an absolute value — is the same four-layer change D-02 deferred for carb heat and fuel pump, and should be taken once for all three.

## Self-Check: PASSED

All 9 modified files exist on disk. All 5 commits (`12388b9`, `748fcda`, `b8127b5`, `e216e40`, `fee3711`) exist in `git log`. No files were deleted by any commit (`git diff --diff-filter=D` empty for each). No untracked files remain. No shared orchestrator artefact (`STATE.md`, `ROADMAP.md`, `REQUIREMENTS.md`) was modified, and no file owned by sibling plan 02-15 (`web/server.py`, `web/static/app.js`, `web/static/style.css`, `web/tests/test_authority_events.py`) was opened.

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-08-01*
