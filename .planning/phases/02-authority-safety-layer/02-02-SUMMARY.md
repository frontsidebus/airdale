---
phase: 02-authority-safety-layer
plan: 02
subsystem: msfs-adapter-command-surface
tags: [cmd-07, simconnect, command-map, parity-guard, csharp, docs]
requires:
  - "orchestrator/orchestrator/tools.py::_resolve_command (unchanged; source of truth for event names)"
  - "orchestrator/orchestrator/claude_client.py::TOOL_DEFINITIONS (unchanged; source of truth for exposed systems)"
provides:
  - "adapters/msfs CommandMap handlers for all 52 events the 14 enum-exposed systems can emit"
  - "SimEventId members for trim, de-ice, fuel selector and crossfeed events"
  - "Two independent cross-language parity guards, one per language"
  - "docs/AIRCRAFT_CONTROLS.md restated to the actually-reachable surface"
affects:
  - "02-04 (authority gate) — trim/deice/fuel_selector/crossfeed now actually execute, so they are live commands the gate must consider"
  - "02-07 (procedure re-route) — unblocked-by-nothing here; CMD-09 stays deferred as required"
tech-stack:
  added: []
  patterns:
    - "Source-text parsing as a stand-in for reflection when the SDK dependency cannot enter the test project"
    - "Hand-written branch table + literal-regex companion assertion to prove branch coverage"
key-files:
  created:
    - adapters/msfs/SimConnectBridge.Tests/CommandMapTests.cs
    - orchestrator/tests/test_command_coverage.py
    - .planning/phases/02-authority-safety-layer/02-02-deferred-items.md
  modified:
    - adapters/msfs/Models/SimDataStructs.cs
    - adapters/msfs/SimConnectManager.cs
    - docs/AIRCRAFT_CONTROLS.md
decisions:
  - "C# test parses SimConnectManager.cs and SimDataStructs.cs as source text rather than by reflection, because the test project must not take a SimConnect SDK reference (Phase 06 CI decision)"
  - "Deferred items recorded in a plan-scoped 02-02-deferred-items.md rather than the shared deferred-items.md, to avoid an add/add conflict between parallel worktrees"
  - "Corrected the flaps documentation table as part of the docs task: it claimed FLAPS_UP/FLAPS_FULL where the resolver has always emitted FLAPS_SET at the rail"
metrics:
  duration: ~25 min
  completed: 2026-07-31
requirements: [CMD-07]
---

# Phase 02 Plan 02: Adapter Command-Surface Parity Summary

Registered the 20 SimConnect events that four already-exposed systems resolved to but the MSFS
adapter had no handler for, and added a guard in each language so the resolver and the adapter
cannot drift apart silently again.

## What Changed

`_resolve_command` can emit 52 distinct SimConnect event names for the 14 systems the
`set_aircraft_control` tool enum exposes. `CommandMap` in the MSFS adapter registered 36 of
them. The 20-event gap fell entirely on `trim`, `deice`, `fuel_selector` and `crossfeed`, so
those four systems hit `ExecuteCommand`'s `Unknown command` branch and acked `success:false`
— while MERLIN, which does not read the ack before speaking, told the pilot the action was
taken. A pilot who believes de-ice is on when it is not is worse off than one told it failed.

The map now has 56 entries: the 52 the enum-exposed systems can reach, plus `FLAPS_UP`,
`FLAPS_FULL`, `THROTTLE1_SET` and `THROTTLE2_SET`, which were already registered and which the
resolver never emits (kept, documented, harmless).

The 11 CMD-09 event names remain absent from both the map and the `SimEventId` enum. That is
now asserted three times over, because the negative is the load-bearing part: `execute_procedure`
bypasses the `set_aircraft_control` enum entirely and `PROCEDURES["shutdown"]` contains a
`magnetos` step, so registering `MAGNETO_SET` before the authority gate (02-04) and the
procedure re-route (02-07) land would turn a named tool call into a working in-flight engine
shutdown with nothing in front of it.

## Tasks Completed

| Task | Name | Commit | Files |
|---|---|---|---|
| 1 | Register the 20 missing SimConnect events | `840e5c9` | `Models/SimDataStructs.cs`, `SimConnectManager.cs` |
| 2 | C# CommandMap table test | `acb5689` | `SimConnectBridge.Tests/CommandMapTests.cs` |
| 3 | Python parity guard + controls docs | `6f56227` | `orchestrator/tests/test_command_coverage.py`, `docs/AIRCRAFT_CONTROLS.md` |

## The Two Guards

**C# — `CommandMapTests.cs` (61 tests).** A `[Theory]` with 56 `[InlineData]` rows, one per
registered event, each because-string naming the system it serves. Five `[Fact]`s: entry count
pinned at 56; no CMD-09 event registered; every value a distinct `SimEventId`; every value a
declared `SimEventId` member; the enum itself declares no CMD-09 members.

`CommandMap` is `private static readonly`, so reflection would be the normal route. It is not
available: reflection needs `SimConnectManager.cs` compiled into the test assembly, and both it
and `SimDataStructs.cs` `using Microsoft.FlightSimulator.SimConnect`. The test project
deliberately omits that reference so CI runners without the MSFS SDK can build it (Phase 06
decision, recorded in STATE.md). The plan anticipated this and specified the fallback: locate
the sources relative to the test assembly's base directory and read them as text. That is what
was done, and the reasoning is in an XML doc comment on the test class.
`CommandMap_OnlyReferencesDeclaredSimEventIdMembers` exists specifically to substitute for the
compile check the project cannot perform.

**Python — `test_command_coverage.py` (3 tests).** Reads the exposed-system list from
`TOOL_DEFINITIONS` rather than hardcoding it, runs an explicit `(system, action, value)` branch
table through `_resolve_command`, regex-parses `CommandMap` out of the C# source, and asserts
every event an exposed system can reach has a handler. Plus the CMD-09 negative, plus
`test_resolver_branch_table_is_exhaustive`, which compares the table's output against the event
literals found by regexing `inspect.getsource(_resolve_command)` — so adding a resolver branch
without adding a table row fails loudly instead of quietly going unchecked.

The adapter is located by walking up from `__file__` to the directory containing both
`orchestrator/` and `adapters/`, not by fixed relative depth. When the adapter tree is absent
the two cross-language tests skip with an explanatory reason, so the orchestrator package
stays installable and testable standalone.

## Guards Were Mutation-Tested, Not Just Run Green

A guard that passes proves nothing about whether it can fail. Each was deliberately broken:

| Injected fault | Result |
|---|---|
| Rename `["PITOT_HEAT_TOGGLE"]` to `["MAGNETO_SET"]` in `SimConnectManager.cs` | C#: 2 failures (`CommandMap_ContainsHandlerFor(PITOT_HEAT_TOGGLE, deice)`, `CommandMap_DoesNotRegisterAnyCmd09Event`). Python: 2 failures (`test_every_enum_exposed_event_has_an_adapter_handler`, `test_cmd09_systems_are_not_registered`), both with messages naming the missing event and citing the consequence. |
| Drop the `("deice", "windshield", None)` branch-table row | `test_resolver_branch_table_is_exhaustive` fails naming `WINDSHIELD_DEICE_TOGGLE`. |

Both mutations were reverted with `git checkout -- <file>` and the restore verified before
committing.

## Verification

| Check | Result |
|---|---|
| `dotnet build adapters/msfs/SimConnectBridge.Tests/SimConnectBridge.Tests.csproj` | exit 0, 0 warnings |
| `dotnet build adapters/msfs/SimConnectBridge.csproj` (extra, see Deviations) | exit 0, 0 warnings — real compile check of the changed C# |
| `dotnet test` C# suite | 176 passed / 15 failed / 191 total. Baseline was 115 / 15 / 130 — **+61 passing, same 15 pre-existing failures** |
| `python3 -m pytest orchestrator/tests/test_command_coverage.py -q` | 3 passed, 0 skipped |
| `python3 -m pytest orchestrator/tests/ -q` | 1092 passed, 2 xfailed, 0 failed |
| `ruff check` (CI-parity form, from repo root) | All checks passed |
| `ruff format --check` (CI-parity form) | 103 files already formatted |
| `grep -cE '\["[A-Z0-9_]+"\] = SimEventId\.'` | 56 |
| CMD-09 grep over `SimConnectManager.cs` + `SimDataStructs.cs` | no output (exit 1) |
| `git diff --numstat` on both C# source files | `24 0` and `24 0` — zero deletions |
| `grep -c "SimConnect.dll\|Microsoft.FlightSimulator" SimConnectBridge.Tests.csproj` | 0 |
| `grep -c "72+" docs/AIRCRAFT_CONTROLS.md` | 0 |
| `grep -c "CMD-09" docs/AIRCRAFT_CONTROLS.md` | 1 |

Confirmed the Python guard reads the **worktree** adapter copy, not the main checkout: the
editable install resolves `orchestrator.tools` to the main repo (identical content, verified by
`diff`), but `REPO_ROOT` derives from `__file__` and resolved to the worktree. The main
checkout's `SimConnectManager.cs` has no `ELEV_TRIM_UP`, so a pass could only come from reading
the worktree copy.

## Deviations from Plan

### 1. [Rule 3 — Blocking] `dotnet` is not installed in WSL; used the Windows SDK via interop

**Found during:** Task 1 verification.
**Issue:** `dotnet` is not on `PATH` in this WSL2 environment, so the plan's `<automated>`
verify commands could not run as written.
**Fix:** Used `/mnt/c/Program Files/dotnet/dotnet.exe` (SDK 8.0.419) with Windows-form paths.
The worktree lives under `/mnt/c`, so it is directly addressable from the Windows side. No
files changed.

### 2. [Rule 2 — Missing verification] Also built the full adapter project

**Found during:** Task 1 verification.
**Issue:** The plan's verify step builds `SimConnectBridge.Tests.csproj`, which compiles neither
`SimConnectManager.cs` nor `SimDataStructs.cs` — the two files Task 1 changed. It would have
passed identically had the edits been syntactically invalid.
**Fix:** Additionally built `SimConnectBridge.csproj`, which does compile them. This machine has
the MSFS SDK, so it succeeded (0 warnings, 0 errors), giving a genuine compile check. CI cannot
do this; see Deferred Issues.
**Files modified:** none.

### 3. [Rule 1 — Bug] Corrected the flaps table in `AIRCRAFT_CONTROLS.md`

**Found during:** Task 3.
**Issue:** The doc listed `up`/`retract` → `FLAPS_UP` and `full`/`down` → `FLAPS_FULL`.
`_resolve_command` returns `FLAPS_SET, 0` and `FLAPS_SET, 16383`, with in-code comments saying
`FLAPS_SET` is more reliable and `FLAPS_FULL` does not work on all aircraft.
**Fix:** Corrected both rows and added a note explaining why the discrete events stay registered
but unused. Squarely within the task's "restate it accurately" remit and threat T-02-02-04.
**Files modified:** `docs/AIRCRAFT_CONTROLS.md`. **Commit:** `6f56227`.

### 4. [Process] Deferred items filed under a plan-scoped name

`.planning/phases/02-authority-safety-layer/02-02-deferred-items.md` rather than the shared
`deferred-items.md`, because plans in this phase run in parallel worktrees and a shared new file
is an add/add merge conflict waiting to happen. Trivially foldable at merge.

## Deferred Issues

Full detail in `02-02-deferred-items.md`. Summary:

**15 pre-existing C# test failures, unchanged by this plan.** Present on the base commit
(`d7e6fef`); the same 15 fail before and after. Twelve are `SimDataStructTests` asserting
`StructLayout` properties via `Type.GetCustomAttributes`, which cannot work —
`StructLayoutAttribute` is a pseudo-custom attribute folded into metadata flags. Two are
`LowFrequencyData` size/field-count assertions that no longer match the mirror struct. One is an
unrelated serialization test. Out of scope per the executor scope boundary: logged, not fixed.
**Consequence: `dotnet test` does not exit 0**, so that acceptance criterion is not met on its
literal terms. The substantive intent — all new tests pass, strictly more tests pass than
before, no regressions — is met.

Worth flagging for whoever owns Phase 2's remaining plans: the plan told this executor not to
touch `LowFrequencyData` because `SimDataStructTests.cs` hard-codes the field count. That
hard-coded count is **already wrong** (asserts 18, struct has 19) and already failing, so the
guard the instruction was protecting is not currently guarding anything.

**The test project does not compile the files it tests.** `SimConnectBridge.Tests.csproj`
excludes `SimConnectManager.cs` and `SimDataStructs.cs` to avoid the SDK dependency, so CI has
no compile check on them at all. `CommandMapTests` mitigates this for `CommandMap` specifically
via source-text assertions. A durable fix — extracting `CommandMap` and `SimEventId` into an
SDK-free file compiled into the test project — touches adapter file layout and is more than
CMD-07 warrants.

## Success Criteria

- [x] `CommandMap` has 56 entries covering every event the 14 enum-exposed systems can resolve to
- [x] Zero CMD-09 events registered, in either the enum or the map
- [x] Two independent parity guards exist, one per language, and both fail on drift (mutation-tested)
- [x] `docs/AIRCRAFT_CONTROLS.md` describes what is actually reachable

## Known Stubs

None. No placeholder values, empty collections, or unwired data paths were introduced.

## Threat Flags

None. This plan adds no network endpoint, auth path, file-access pattern, or schema change. It
widens an existing trust boundary (`CommandMap` → SimConnect) by exactly the 20 events the plan
enumerated, all of which were already reachable from the tool enum and already passing through
`command_safety.py`; the threats are the ones already registered as T-02-02-01 through
T-02-02-05, all dispositioned `mitigate` and all mitigated.

## Self-Check: PASSED

All five claimed files exist on disk. All three commit hashes (`840e5c9`, `acb5689`, `6f56227`)
found in `git log`. Artifact minimums met: `CommandMapTests.cs` 297 lines (min 60),
`test_command_coverage.py` 316 lines (min 80). Required `contains` markers present:
`RudderTrimLeft` in `SimDataStructs.cs`, `PITOT_HEAT_TOGGLE` in `SimConnectManager.cs`.
