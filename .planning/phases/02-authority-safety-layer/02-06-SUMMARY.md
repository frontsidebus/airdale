---
phase: 02-authority-safety-layer
plan: 06
subsystem: safety
tags: [authority, override-detection, attribution, verification, telemetry, cooldown]

# Dependency graph
requires:
  - phase: 02-authority-safety-layer
    plan: 01
    provides: AuthorityState.record_override / take_restore_event / configured_level
  - phase: 02-authority-safety-layer
    plan: 05
    provides: TelemetryClient.recent_dispatches() monotonic dispatch ledger
provides:
  - VERIFICATION_CHECKS covering every observable command (7 -> 22 entries)
  - has_verification_rule() + NO_RULE_EXPECTED, closing the D-13 hole RESEARCH F2 found
  - COMMAND_WATCHED_FIELDS / WATCHED_FIELD_EPSILON / WATCHED_FIELDS tables
  - OverrideDetector -- a plain StateCallback that drops authority on unattributed movement
  - FIELD_LABELS for pilot-facing system naming in announcements
affects: [02-08, 02-09, 02-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two suppression leads keyed on has_verification_rule -- a rule-less verified=True is never treated as evidence the aircraft moved"
    - "Directional (not absolute) verification for detent commands whose real percentages are aircraft-specific"
    - "Shared check body plus thin named wrappers, so VERIFICATION_CHECKS still maps to importable per-command functions"
    - "Detector hosts on TelemetryClient.subscribe, reusing ProactiveEvent without constructing ProactiveMonitor"

key-files:
  created:
    - orchestrator/orchestrator/override_detector.py
    - orchestrator/tests/test_override_detector.py
  modified:
    - orchestrator/orchestrator/command_verifier.py
    - orchestrator/tests/test_command_verifier.py

key-decisions:
  - "The plan gives two barometer tolerances (verify ±0.02 inHg, detect 0.005); both were implemented as written because they serve opposite purposes"
  - "Flaps detent checks compare direction of travel, not an absolute target -- detent percentages differ per aircraft, so an absolute target would produce false negatives"
  - "SPOILERS_TOGGLE uses a ±5 % movement floor rather than !=, because the field is a float on a jittery 1 Hz feed"
  - "FLAPS_SET vs FLAPS_INCR is the lead-difference test pair: same field, same movement, only the verification rule differs"
  - "put_nowait on the unbounded PriorityQueue, so a detection can never block the telemetry callback"

patterns-established:
  - "Announcement fires on record_override() returning True only; an extension logs at INFO and stays silent, so sustained pilot activity cannot spam"
  - "WATCHED_FIELDS is a sorted tuple derived from the command table, giving deterministic iteration and announcement order"

requirements-completed: []

# Metrics
duration: 20min
completed: 2026-08-01
---

# Phase 02 Plan 06: Pilot Override Detection Summary

**Any watched telemetry field that moves without a recent MERLIN dispatch accounting for it drops authority to advisory on a rolling cooldown — attributed on one monotonic clock, with a suppression window whose length depends on whether the command had a verification rule worth trusting.**

## Performance

- **Duration:** ~20 min of active work (wall clock spans 12:26–14:30 with one idle gap)
- **Tasks:** 3
- **Files modified:** 4 (2 created, 2 modified)
- **Tests added:** 59 (33 in `test_command_verifier.py`, 26 in `test_override_detector.py`)

## Accomplishments

- `VERIFICATION_CHECKS` goes from 7 entries to 22. Every command whose effect is visible in `SimState` now has a real rule: gear toggle, all five flaps detents, both spoilers commands, AP speed and vertical speed, the altimeter setting, and all four radios. `verified=True` means something for them now.
- `has_verification_rule()` plus a named `NO_RULE_EXPECTED` constant close the hole RESEARCH F2 identified in D-13. Before this, 60 of 67 commands "confirmed" in roughly zero milliseconds via the rule-less early return — long before the next 1 Hz frame — so anchoring a watch window on verification success would have scored MERLIN's own change as a pilot override on the very next frame.
- The detector uses **two** suppression leads rather than one, which is the D-13 amendment made concrete: `verify_timeout_s` for a command with a real rule (it may still be polling when its change lands) and `settle_s` for one without. Two tests pin this against each other — `FLAPS_SET` and `FLAPS_INCR`, same field, same movement, same 32.5 s elapsed, opposite outcomes.
- `COMMAND_WATCHED_FIELDS` is a **new** table, not an extension of `_extract_relevant_state`. `command_history.py` is byte-identical (`git diff --numstat` empty), so undo is untouched — that map answers "what value do I restore?" and this one answers "which fields do I watch?", and they coincide only for value-restore commands.
- Attribution runs on exactly one clock. `recent_dispatches()` stamps `time.monotonic()` client-side; the detector's injected clock is the same source. The adapter's ISO `SimState.timestamp` is never read, so F5's cross-clock correlation cannot arise.
- The detector is a plain `TelemetryClient.subscribe` callback. `ProactiveMonitor` — which is never constructed in production — stays dormant; only its `ProactiveEvent` type is reused, so callouts, deviation alerts, emergency detection and checklist automation are not silently commissioned as a side effect.
- Throttle is excluded with the reason in a comment beside the table. `grep -v '^\s*#' | grep -c THROTTLE_SET` reports 0, and a test asserts the absence with RESEARCH B6 cited in the failure message, so a future contributor gets the argument rather than a blank.
- Every failure mode research named has a test proving it does not fire: startup burst (F6), aircraft change and its settle window (F4), disconnect and reconnect (F4), sub-epsilon float jitter (F3), and self-detection through both lead paths (F1, F2).
- The rolling cooldown announces once per window in each direction: two overrides 60 s apart produce one drop event, the rolled expiry holds authority down past the original one, and exactly one restore event fires after it lapses.

## Task Commits

1. **Task 1: Give every observable command a real verification rule** — `05aac74` (feat)
2. **Task 2: Watched-fields table and the override detector** — `a61f70e` (feat)
3. **Task 3: Attribution, suppression, epsilon and cooldown tests** — `c2b1da2` (test)

## Files Created/Modified

- `orchestrator/orchestrator/override_detector.py` (new, 318 lines) — `COMMAND_WATCHED_FIELDS` (27 commands → 13 dotted paths), `WATCHED_FIELD_EPSILON` (11 float tolerances), `WATCHED_FIELDS` (sorted union), `FIELD_LABELS`, and `OverrideDetector` with `events`, `on_telemetry_update`, `_field_moved`, `_is_attributed`, `_record_override`, `_announce_restore`. Module docstring states the coverage bound (6 systems observable, throttle excluded, 13 structurally undetectable) and records why the dispatch ledger rather than `CommandHistory` is the attribution basis.
- `orchestrator/orchestrator/command_verifier.py` — 15 new checks plus two shared bodies (`_check_flaps_detent`, `_check_radio`), `_FLAPS_DETENT_PCT`, `_RADIO_FIELDS`, `NO_RULE_EXPECTED`, `has_verification_rule`, an expanded `VERIFICATION_CHECKS`, and an `__init__` docstring stating the timeout tunables are caller-overridable and that the module reads no `Settings`.
- `orchestrator/tests/test_command_verifier.py` — nine new classes covering both branches of each new check, `has_verification_rule` for registered and rule-less commands, a loop asserting every registered check survives a default `SimState()`, and two `CommandVerifier` tests pinning that `MIXTURE_SET` still short-circuits while `SPOILERS_SET` now polls.
- `orchestrator/tests/test_override_detector.py` (new, 484 lines) — `_FakeClock`, `_make_state`, `_client`, `_detector`, `_feed`, `_drain` helpers plus four classes: table integrity (3), detection and attribution (10), suppression (8), cooldown and announcements (5).

## Decisions Made

- **The plan's two barometer tolerances were both implemented as written.** Task 1 specifies ±0.02 inHg for `KOHLSMAN_SET` verification; Task 2's epsilon table specifies 0.005 for `environment.barometer_inhg` detection. That looks like an inconsistency against Task 2's instruction to reuse the verifier's numbers "verbatim", but the two serve opposite purposes — verification should confirm generously, detection should be sensitive (D-12) — so following each table literally is the coherent reading. Flagging it because a future reader will notice the mismatch and may try to "align" them; aligning them would make override detection on the altimeter four times less sensitive.
- **Flaps detent checks are directional, not absolute.** `FLAPS_1/2/3` target a detent whose real percentage is aircraft-specific (a C172 has three notches, an airliner five), so an absolute target would fail on most aircraft. `_FLAPS_DETENT_PCT` supplies nominal values used *only* to derive the commanded direction of travel, with a comment saying so. Re-selecting the current detent verifies with no movement, which is the correct outcome and would otherwise always read as a failure.
- **Two shared check bodies rather than nine copy-pasted functions.** `_check_flaps_detent` and `_check_radio` hold the logic; thin named wrappers (`_check_flaps_1`, `_check_com1`, …) are what `VERIFICATION_CHECKS` maps to, so the registry still points at importable per-command functions and the tests can exercise each individually. The plan described "~12 lines each following the `_check_alt_set` template"; nine near-identical copies would have been the literal reading and the worse code.
- **`SPOILERS_TOGGLE` uses a ±5 % movement floor, not `!=`.** `_check_ap_master` can use `!=` because `autopilot.master` is a bool. `spoilers_percent` is a float on a 1 Hz feed whose delta detection compares raw JSON, so `!=` would verify on jitter. The floor is the same tolerance `_check_flaps_set` uses.
- **`put_nowait` rather than `await queue.put`.** The queue is unbounded, so `put_nowait` cannot fail, and it keeps `on_telemetry_update` from ever yielding mid-detection.
- **`WATCHED_FIELDS` is a sorted tuple.** Derived from the command table as the plan asks, but sorted rather than left as set-iteration order, so the fields named in an announcement are stable across runs and the test asserting `data["fields"]` is deterministic.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `test_all_expected_commands_registered` asserted the exact pre-existing 7-command set**

- **Found during:** Task 1
- **Issue:** The plan directs that `test_command_verifier.py` be extended "additively", but the existing `TestVerificationChecksRegistry.test_all_expected_commands_registered` asserts set *equality* against the seven original commands. Registering 15 new checks — the whole point of the task — makes it fail, which blocked the task's own verification step.
- **Fix:** Updated the expected set to the full 22 commands rather than loosening the assertion to a subset check. Exact equality is a real guard: it catches an accidental registration as well as a missing one, and it is the file's existing style. Added a companion `test_every_observable_command_has_a_rule` naming the commands RESEARCH F2 called out, so the intent survives the next edit.
- **Files modified:** `orchestrator/tests/test_command_verifier.py`
- **Commit:** `05aac74`

**Total deviations:** 1
**Impact on plan:** None on scope or behaviour. Every acceptance criterion in all three tasks was verified as written.

## Issues Encountered

- **No venv in the worktree.** `orchestrator/.venv/` is git-ignored and lives only in the main checkout, so `cd orchestrator && .venv/bin/python3 -m pytest` fails here. Same workaround as plan 02-05: system `python3` (pytest 9.0.2) with `PYTHONPATH` pointed at the worktree `orchestrator/`, which takes precedence over the editable install's `.pth` file. Verified explicitly (`orchestrator.sim_client.__file__` resolves inside the worktree) before relying on it.
- **Plan `<verify>` blocks `cd` to the main repo path** (`/mnt/c/Users/bould/source/airdale`), as plans 02-01 and 02-05 both noted. Run from the worktree root instead; the commands are otherwise unchanged.
- **The base commit was ahead of the spawned worktree HEAD.** `git merge-base HEAD cfcf1d5` returned HEAD itself, meaning the worktree was created before the wave-2 merge landed. Corrected with the sanctioned `git reset --hard cfcf1d5` from the startup check, after the branch-namespace assertion passed.
- **`ruff format` needed no fixes on either new file** — both were written to the 100-char/format conventions and passed the CI-parity check first time.

## Verification

- `pytest tests/test_override_detector.py tests/test_command_verifier.py -q` — **87 passed** (26 + 61)
- `pytest tests/test_override_detector.py -q` — **26 passed** (required floor: 18)
- `pytest tests/test_command_verifier.py -q` — **61 passed** (baseline 28; +33, against a required floor of +12)
- `pytest tests/ -q` (orchestrator) — **1278 passed, 2 xfailed** (baseline 1219 + 33 + 26 = 1278 exactly, no regressions)
- `pytest tests/ -q` (web) — 55 passed, 1 skipped — unchanged from baseline
- `pytest tests/ -q` (telemetry-service) — 38 passed — unchanged from baseline
- `pytest tests/test_command_history.py -q` — 34 passed; `git diff --numstat orchestrator/orchestrator/command_history.py` — **empty**
- `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore SIM105,SIM117,F841,B008,B017,B007,UP041` — All checks passed
- `ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml` — 109 files already formatted
- `len(VERIFICATION_CHECKS)` → **22** (required ≥ 20, was 7)
- `has_verification_rule('SPOILERS_SET'), ('KOHLSMAN_SET'), ('MIXTURE_SET')` → `True True False`
- Every path in `COMMAND_WATCHED_FIELDS` resolves via `_get_nested_attr` on a default `SimState()` — 27 commands, 13 distinct paths
- `grep -v '^\s*#' override_detector.py | grep -c THROTTLE_SET` → **0**
- `grep -c recent_dispatches override_detector.py` → 3; `grep -c has_verification_rule` → 2; `grep -c record_override` → 3; `grep -c CommandHistory` → **0**
- `grep -c "asyncio.sleep" tests/test_override_detector.py` → **0**
- `inspect.iscoroutinefunction(OverrideDetector.on_telemetry_update)` → `True`; parameters → `['self', 'state']` (matches `StateCallback`)
- Line counts: `override_detector.py` 318 (floor 160), `test_override_detector.py` 484 (floor 200)
- `git diff --numstat cfcf1d5 HEAD` → exactly the four files in `files_modified`, no deletions in any commit

## Known Stubs

None. Every symbol in the plan's `<interfaces>` block is implemented and exercised by a test.

One deliberate non-stub worth naming so the verifier does not read it as one: `OverrideDetector.events` has **no consumer in this plan**. That is by design — the plan states this phase's pilot-facing channel is `/api/status` plus the browser badge (02-09 and 02-10), and the queue exists so a later consumer can drain it without this module knowing who that is. Likewise, nothing constructs an `OverrideDetector` yet; the composition roots that call `sim_client.subscribe(detector.on_telemetry_update)` are 02-08 (CLI) and 02-09 (web). Until those land, override detection is implemented and tested but not running in any process.

## Threat Flags

None. This plan adds no network endpoint, auth path, file access or schema at a trust boundary. All seven `mitigate` dispositions in the plan's register are implemented and tested:

| Threat ID | Where it is closed |
|-----------|--------------------|
| T-02-06-01 | Attribution walks `recent_dispatches()`; per-command suppression window with a rule-dependent lead. Pinned by the `FLAPS_SET` / `FLAPS_INCR` pair |
| T-02-06-02 | `has_verification_rule` distinguishes a real confirmation from the rule-less early return; Task 1 gave every observable command a rule |
| T-02-06-03 | Direction-agnostic detection on any unattributed movement; both flaps directions tested. Coverage bound stated in the module docstring |
| T-02-06-04 | Per-field epsilons reused from the verifier, `prev is None` guard, aircraft/connection settle window — each with a test |
| T-02-06-05 | `record_override()` returning False logs at INFO and enqueues nothing; `test_two_overrides_inside_one_cooldown_announce_once` |
| T-02-06-06 | `command_history.py` byte-identical, pinned by the empty `git diff --numstat` |
| T-02-06-07 | One clock throughout: ledger timestamps and the detector clock are both `time.monotonic()`; the adapter's ISO timestamp is never read |
| T-02-06-SC | No packages installed. Zero new dependencies |

## Notes for the Orchestrator

- STATE.md, ROADMAP.md and REQUIREMENTS.md were **not** modified (worktree mode; the orchestrator owns those writes post-wave).
- **AUTH-05 and AUTH-06 should not be marked complete on this plan alone.** The detector and the drop/restore announcements exist and are tested, but nothing subscribes them yet — that is 02-08 (CLI) and 02-09 (web). Marking them now would over-claim, and every wave plan touching REQUIREMENTS.md would conflict. Recommend deferring until the wave merges and a composition root is wired.
- **AUTH-05's acceptance must not be read as universal coverage.** Six systems are observable, throttle is deliberately excluded, and 13 are structurally undetectable because no `SimState` field exists for them. That bound is in the module docstring and pinned by test; it should travel with the requirement rather than being discovered later.
- `verify.key-links` should now resolve this plan's three links — `override_detector.py` was the "Source file not found" in the pre-merge report.

## Next Phase Readiness

Ready. Downstream plans can now:

- **02-08 / 02-09:** construct `OverrideDetector(authority, sim_client, grace_s=settings.authority_override_grace_s, settle_s=settings.authority_override_settle_s, verify_timeout_s=settings.authority_verify_timeout_s)` and wire it with `sim_client.subscribe(detector.on_telemetry_update)`. Everything after `sim_client` is **keyword-only**. Pass the same `AuthorityState` the floor and the gate hold, or the drop will not be visible to them.
- **02-09 / 02-10:** drain `detector.events` for `ProactiveEvent`s with `type == "authority"`; `data["event"]` is `"override"` or `"restore"`, and the override event carries `data["fields"]` with the dotted paths that moved. Priorities are 1 (caution) for the drop and 0 (info) for the restore, so the drop sorts first out of a shared `PriorityQueue`.
- **02-08:** pass `settings.authority_verify_timeout_s` into `CommandVerifier(sim_client, timeout=...)` — it is a plain parameter and this module still reads no `Settings`.

One caution: the detector and the `AuthorityState` **must share a clock**. Both default to `time.monotonic`, so passing neither is correct in production; injecting one without the other would make the cooldown arithmetic incoherent.

## Self-Check: PASSED

- Files claimed created/modified: all 4 present on disk with the described contents.
- Commits claimed: `05aac74`, `a61f70e`, `c2b1da2` — all three present in `git log`.
- No files deleted (`git diff --diff-filter=D` empty for all three commits).

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-08-01*
