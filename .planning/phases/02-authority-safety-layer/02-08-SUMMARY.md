---
phase: 02-authority-safety-layer
plan: 08
subsystem: safety
tags: [authority, composition-root, wiring, fail-closed, timeout-ordering, b3, override-detection]

# Dependency graph
requires:
  - phase: 02-authority-safety-layer
    plan: 01
    provides: AuthorityState / parse_authority_level and the eight authority_* Settings fields
  - phase: 02-authority-safety-layer
    plan: 04
    provides: the authority gate in set_aircraft_control and undo_last_command
  - phase: 02-authority-safety-layer
    plan: 05
    provides: TelemetryClient(authority=, health=, command_timeout=), the floor and the ack watchdog
  - phase: 02-authority-safety-layer
    plan: 06
    provides: OverrideDetector, which had no composition root until now
  - phase: 02-authority-safety-layer
    plan: 07
    provides: ProcedureExecutor's four keyword collaborators, unpassed by production until now
provides:
  - "ClaudeClient(..., verify_timeout=, command_tool_timeout=, authority=) -- authority forwarded to every tool that can reach the sim"
  - "ClaudeClient.tool_timeout_for(name) -- the resolved outer deadline, instance override first"
  - "Command-path tool deadlines driven by authority_tool_timeout_s instead of a hardcoded 5.0 (RESEARCH B3 closed)"
  - "One AuthorityState per CLI process, shared by identity with TelemetryClient, ClaudeClient, ProcedureExecutor and OverrideDetector"
  - "Fail-closed CLI startup: a failure to build the authority state aborts the process"
  - "Override detection running on the live telemetry stream in the CLI"
  - "command_path registered as a HealthMonitor subsystem in the CLI (D-17)"
  - "CLAUDE.md decision 26, the two new modules in the directory map, refreshed test categories"
affects: [02-09, 02-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composition root owns construction; collaborators accept, never build (D-09) -- ClaudeClient stores an AuthorityState it was handed and holds None when handed nothing"
    - "Per-instance timeout override table consulted ahead of the class table, so a config-driven deadline coexists with static ones"
    - "Deliberate absence of a try/except, documented in place with the three reasons, so 'hardening' it is recognisably a regression"
    - "Detector subscribed as its own StateCallback rather than called from inside another, so one failure cannot suppress the other (D-11)"

key-files:
  created: []
  modified:
    - orchestrator/orchestrator/claude_client.py
    - orchestrator/orchestrator/main.py
    - orchestrator/tests/test_claude_client.py
    - tests/integration/test_tool_chain.py
    - CLAUDE.md

key-decisions:
  - "Command-path tools were REMOVED from the _TOOL_TIMEOUTS class table rather than given a literal 12.0, so there is exactly one source for that deadline and the acceptance grep cannot pass while a stale constant lingers"
  - "tool_timeout_for() is public: the structural guard is a first-class consumer of the resolved value, and a public accessor documents the override order better than a private one"
  - "ProcedureExecutor receives verifier / command_history / authority but NOT safety_check, matching the set_aircraft_control dispatch site, so both paths run the same module-level rule set"
  - "The startup INFO log lives in __init__, which runs after logging.basicConfig in async_main -- so a restricting .env is visible in the very first lines of the log"
  - "execute_procedure's 30 s deadline left alone and annotated rather than changed; no Settings field covers it and a literal would be the magic number CLAUDE.md forbids"
  - "REQUIREMENTS.md deliberately not modified, following the 02-01 / 02-04 / 02-05 / 02-06 / 02-07 precedent"

patterns-established:
  - "Failure-message-carries-the-argument: the B3 guard's assertion text states why an equal budget is silent rather than loud, so the next reader gets the reasoning and not just a number"
  - "Identity assertions (`is`, not `==`) for shared mutable state crossing a composition boundary"

requirements-completed: []

# Metrics
duration: 24min
completed: 2026-08-01
---

# Phase 02 Plan 08: CLI Composition Root & Tool-Timeout Ordering Summary

**Everything the previous five plans built now exists in a running CLI process: one `AuthorityState` constructed from settings and shared by identity with the transport, the LLM client, the procedure executor and the override detector — or, if it cannot be built, no CLI at all — and the tool-layer deadline is finally wide enough that a genuine ack timeout reaches the watchdog instead of being cancelled as a tool timeout.**

## Performance

- **Duration:** ~24 min (2026-08-01T14:58Z base → 15:22 final task commit, local time)
- **Tasks:** 3
- **Files modified:** 5 (0 created, 5 modified)
- **Tests added:** 16 (11 orchestrator, 5 integration)

## Accomplishments

- **The layer is live.** Before this plan `main.py` built a `TelemetryClient` with `authority=None` (floor inert), `claude_client.py:495` built `ProcedureExecutor(sim_client)` with no authority (every procedure at `full`), and `OverrideDetector` was never constructed by anything. All three are now wired to the same object; four prior executors declined to mark their requirements complete for exactly this reason.
- **One state, proven by identity.** `Orchestrator.__init__` constructs exactly one `AuthorityState` and hands it to `TelemetryClient`, `ClaudeClient`, `ProcedureExecutor` and `OverrideDetector`. Verified at runtime — all four `is` the same object — and pinned by tests that assert identity rather than equality, because a copy would let the gate and the floor disagree about the current level.
- **RESEARCH B3 closed.** `_TOOL_TIMEOUTS["set_aircraft_control"]` was `5.0`, identical to `send_command`'s own deadline, and the outer `asyncio.wait_for` starts first — so on a genuine ack timeout the tool layer cancelled the dispatch, `send_command`'s `except TimeoutError` never ran, and `record_command_timeout()` was never called. The command-path deadline now comes from `authority_tool_timeout_s` (12.0 > 5.0 + 3.0). A slow *success* was the other half of the bug: a verified command polls for up to the verifier timeout on top of the ack round trip, which also blew a 5-second budget.
- **Fail-closed, and legibly so.** The `AuthorityState` construction carries no `try`/`except`. A verification run confirms a construction failure propagates out of `__init__` and aborts startup. The reasoning is written at the construction site in three bullets, because the failure mode of "hardening" it is silent: `authority = None` reads as `FULL` to the gate and skips the floor entirely, so a swallowed exception grants unrestricted control regardless of `AUTHORITY_LEVEL`.
- **`command_path` is a CLI health subsystem.** `HealthMonitor` moved ahead of `TelemetryClient` (the client registers the subsystem on whatever monitor it is handed), with a belt-and-braces registration in `main.py` so the CLI and web paths report the same subsystem set (D-17).
- **No dormant subsystem commissioned.** `ProactiveMonitor(` count in `main.py` is 0. The detector reuses only the `ProactiveEvent` type; callouts, deviation alerts, emergency detection and checklist automation stay switched off.
- **Restricted authority is visible at startup.** One INFO line names the effective level, the reason and the configured level. Confirmed by the smoke check below.
- **The whole chain is exercised together for the first time** — tool_use block → `_execute_tool` → `_dispatch_tool` → `set_aircraft_control` → the gate → `send_command` — at `full`, `advisory`, `assisted` and via `degraded_fallback`, plus a case proving that mutating the shared state between two dispatches changes the second one's outcome.
- Orchestrator suite 1291 → **1302 passed, 2 xfailed**. Web 55 passed / 1 skipped and telemetry-service 38 passed, both unchanged. Both CI-parity ruff commands clean.

## Task Commits

1. **Task 1: Thread authority through ClaudeClient and fix the tool-timeout arithmetic** — `f8b987f` (feat)
2. **Task 2: Construct and subscribe the authority layer in the CLI entry point** — `ee3e6f2` (feat)
3. **Task 3: Timeout structural guard, end-to-end tool-chain test, CLAUDE.md updates** — `0ce34dc` (test)

## Files Created/Modified

- `orchestrator/orchestrator/claude_client.py` — imports `AuthorityState`; `__init__` gains `verify_timeout`, `command_tool_timeout` and a trailing `authority`, plus an Args docstring stating why authority is accepted rather than constructed; `CommandVerifier(sim_client, timeout=verify_timeout)`; `ProcedureExecutor` now receives `verifier` / `command_history` / `authority`; new `_COMMAND_PATH_TOOLS` tuple, `self._tool_timeouts` instance override and the public `tool_timeout_for()`; the two command-path entries removed from `_TOOL_TIMEOUTS` and the B3 ordering constraint documented above the table; `authority=self._authority` at both dispatch sites.
- `orchestrator/orchestrator/main.py` — imports `AuthorityState` / `parse_authority_level` / `OverrideDetector`; `HealthMonitor` construction and its four registrations moved to the top of `__init__` with `command_path` added; the fail-closed `AuthorityState` construction with its three-bullet rationale; startup INFO log; `TelemetryClient(..., authority=, health=, command_timeout=)`; `OverrideDetector(...)`; `ClaudeClient(..., verify_timeout=, command_tool_timeout=, authority=)`; a second `subscribe()` for the detector beside `_on_state_update`.
- `orchestrator/tests/test_claude_client.py` — `_authority_settings()` / `_client_from()` helpers and the shared `_B3_RATIONALE` failure text; `TestCommandPathToolTimeoutOrdering` (6 tests incl. two parametrized pairs) and `TestAuthorityThreadThrough` (5 tests). 78 → **89**.
- `tests/integration/test_tool_chain.py` — `_WarningSafetyCheck` (subclasses `CommandSafetyCheck`), `_command_sim_client()`, `_claude_with()`, `_dispatch_gear_down()` and `TestAuthorityEndToEnd` (5 tests). Also consumes the previously-unused `typing.Any` import, removing a pre-existing F401.
- `CLAUDE.md` — `authority.py` and `override_detector.py` in the directory map; architectural decision **26** naming the three levels, the gate location, the floor, the watchdog placement, the reason field and the fail-toward-less-authority behaviour of both entry points, cross-referencing decision 22 rather than restating it; test count refreshed to ~1,395 (1,302 / 55 / 38) with a note that root-level integration tests are deselected by default; authority, override detection, the watchdog and turn detection added to the category list.

## Decisions Made

- **Command-path tools were removed from the class timeout table, not re-valued.** Keeping `"set_aircraft_control"` in `_TOOL_TIMEOUTS` at a literal `12.0` would have satisfied the letter of the acceptance grep while re-introducing the magic number the plan and CLAUDE.md both forbid, and would have left two places to change when the budget moves. `_COMMAND_PATH_TOOLS` names the membership and `tool_timeout_for()` documents the precedence, so the resolution order is explicit rather than implied.
- **`tool_timeout_for()` is public.** The structural guard's whole job is to assert the *resolved* value; reaching through a private for that is how a guard ends up testing the wrong thing. A public accessor also puts the override order in a docstring where the next contributor will read it.
- **`ProcedureExecutor` gets three of the four collaborators, not four.** `safety_check` is omitted for the same reason the plan gives for the direct dispatch site: `tools.py` falls back to its module-level checker, which is the rule set production has always run. Passing a different one from one of the two call sites would silently change which rules apply to procedures only.
- **The startup log lives in `__init__` rather than `start()`.** `async_main()` calls `logging.basicConfig` before constructing the `Orchestrator`, so the line is emitted and visible; putting it in `start()` would delay it past the telemetry connection attempt, which is exactly when a restricted level matters.
- **`execute_procedure`'s 30 s deadline was annotated, not changed.** See Deferred Issues.
- **The withhold case patches `orchestrator.tools._safety_check` by string target** rather than importing the module under an alias. Functionally identical, and it avoids the isort first-party/third-party split that plan 02-04 hit with `from orchestrator import tools as tools_module`.

## Deviations from Plan

No deviation rule was triggered — no bugs, no missing critical functionality, no blocking issues, nothing auto-fixed. Three points where the plan's text and the repository disagreed, resolved by following the repository:

**1. The class is `Orchestrator`, not `MerlinOrchestrator`.** The plan's Task 2 names `MerlinOrchestrator.__init__` throughout. `orchestrator/orchestrator/main.py` defines `class Orchestrator`. Implemented against the real name; no rename attempted, since `tests/integration/test_orchestrator_e2e.py` imports it and a rename is not this plan's business.

**2. The line numbers in `<read_first>` had drifted.** `ProcedureExecutor(sim_client)` was at line 495, not 493-495; `subscribe(self._on_state_update)` was at 102 but inside `start()`, not `__init__` as the plan's phrasing implies; `HealthMonitor()` was constructed *after* `TelemetryClient`, at line 84. The plan's instruction to construct the monitor first was therefore a genuine reordering rather than a no-op, and it is why `command_path` now appears in the CLI's `summary()`.

**3. The plan's `<verify>` command cannot be run as one invocation.** `python3 -m pytest orchestrator/tests/ tests/integration/ -q` fails at conftest import (`ModuleNotFoundError: No module named 'tests.integration'`) because the two trees carry separate pytest configs and rootdirs. Reproduced with two files this plan never touched, so it is pre-existing and structural. Ran the two trees separately; both exit 0.

**Total deviations:** 0
**Impact on plan:** None. Every acceptance criterion in all three tasks was verified as written.

## Issues Encountered

- **The worktree has no `.venv`.** `orchestrator/.venv/` is git-ignored and exists only in the main checkout, as plans 02-05 through 02-07 all recorded. Used the system `python3` (3.12.3, pytest 9.0.2) with the worktree as cwd.
- **Root-level `tests/` do not resolve to the worktree without help.** pytest's prepend mode inserts `orchestrator/` for `orchestrator/tests/*` (so that tree is fine), but for `tests/integration/*` it inserts the repo root, and `import orchestrator` then falls through to the editable install pointing at the **main** checkout. The first run of the new integration tests failed with `unexpected keyword argument 'authority'` against main's `ClaudeClient`. `PYTHONPATH=orchestrator` is required for any root-level `tests/` run in a worktree.
- **Plan `<verify>` blocks `cd` to the main repo path**, as every prior plan in this phase noted. Run from the worktree root instead.
- **`tests/` is outside CI's lint scope.** The CI-parity command covers `orchestrator/ telemetry-service/ web/` only, so `tests/integration/test_tool_chain.py` is neither checked nor formatted by CI. It carries three pre-existing findings (I001 from a blank line in the import block, one E501, one N806); the file now has one fewer than before this plan, since the new code consumes the previously-unused `typing.Any`. Left the pre-existing three alone rather than reformatting a file CI does not police.
- **The base commit was ahead of the spawned worktree HEAD** (`80f22bf` vs `8e0d6b5`), so the sanctioned `git reset --hard` in the startup check applied, after the branch-namespace assertion passed.

## Verification

- `pytest orchestrator/tests/ -q` — **1302 passed, 2 xfailed** (wave-3 baseline 1291 + 11 new; nothing decreased)
- `pytest orchestrator/tests/test_claude_client.py -q` — **89 passed** (baseline 78; +11)
- `pytest tests/integration/ -q -m integration` — **20 failed / 21 passed / 31 errors**, against the documented pre-existing baseline of 20 / 16 / 31: all five new tests pass and nothing regressed. Deselected by default, so the default run exits 0 (72 deselected)
- `pytest web/tests -q -c web/pyproject.toml --rootdir web` — 55 passed, 1 skipped (unchanged)
- `pytest telemetry-service/tests -q --rootdir telemetry-service` — 38 passed (unchanged)
- `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore SIM105,SIM117,F841,B008,B017,B007,UP041` — All checks passed
- `ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml` — 109 files already formatted
- `python3 -c "import orchestrator.main"` — exits 0
- `inspect.signature(ClaudeClient.__init__)` — `authority` present and **last**
- `grep -c "authority=self._authority" claude_client.py` — **3** (required ≥ 3)
- `grep -vE '^\s*#' claude_client.py | grep -c '"set_aircraft_control": 5.0'` — **0**
- `tool_timeout_for` on a default client — `set_aircraft_control` 12.0, `undo_last_command` 12.0, `get_sim_state` 2.0, unknown 5.0
- `git diff claude_client.py` — no line touching `TOOL_DEFINITIONS`, the system enum, or the `static_block` / `cache_control` region
- `main.py` greps — `AuthorityState(` **1**, `OverrideDetector(` **1**, `ProactiveMonitor(` **0**, `register("command_path")` **1**, `subscribe(` **2**, `degraded_fallback` **0**
- `HealthMonitor()` at line 53 and `AuthorityState(` at line 85 both precede the first `try:` in the file (line 159, inside `start()`) — neither is inside a handler
- Runtime identity check — `sim_client._authority`, `claude._authority`, `override_detector._authority` and `claude._procedure_executor._authority` are all `is` the same object; `"command_path" in health.summary()` is True
- Fail-closed check — with `AuthorityState` patched to raise, `Orchestrator(settings)` propagates the exception out of `__init__` rather than continuing
- Inverted-arithmetic check — a client built with `command_tool_timeout=8.0` resolves 8.0, which the guard's `>` assertion rejects against the 5.0 + 3.0 inner budget
- `grep -c` on CLAUDE.md — `authority.py` 2, `override_detector.py` 2, `degraded` 1 (three occurrences on decision 26's line)

### Manual smoke check (the plan's last verification item)

`AUTHORITY_LEVEL=advisory`, real `Settings` → real `Orchestrator` → real `ClaudeClient._execute_tool` with only the transport doubled:

```
INFO orchestrator.main: Authority: advisory (reason: config, configured: advisory)
INFO orchestrator.claude_client: Executing tool: set_aircraft_control({'system': 'gear', 'action': 'down'})
INFO orchestrator.tools: Authority advisory (config): describing GEAR_DOWN instead of executing it

send_command called: False
advisory: True | level: advisory | reason: config
message: Advisory authority -- I would set gear down (GEAR_DOWN), but nothing was sent. The aircraft is yours.
```

The advisory level is logged at startup and an aircraft control request returns a dry run rather than a command, exactly as specified.

## Deferred Issues

**`execute_procedure`'s 30 s tool deadline is now the same class of problem B3 named, one level up.** A procedure runs N command-path steps sequentially, each of which may now take up to `authority_command_timeout_s + authority_verify_timeout_s` (8 s by default), so a four-step procedure can exceed 30 s and be cancelled at the tool layer — cancelling an in-flight `send_command` mid-procedure and losing its timeout accounting. Not fixed here: no `Settings` field covers it, and a literal would be the magic number CLAUDE.md forbids. Annotated in place at the timeout table so the next reader finds the argument. A proper fix is a `authority_procedure_timeout_s` field derived from the per-step budget and the longest procedure's step count, which is a config change and belongs with whoever owns the procedure budget. Recorded here rather than in a phase-level `deferred-items.md` to avoid a shared-file write from a worktree agent.

## Known Stubs

None. Every contract in the plan's `<interfaces>` block is implemented and exercised.

Two deliberate scope boundaries worth naming so the verifier does not read them as stubs:

- **`OverrideDetector.events` still has no consumer.** The detector now *runs* in the CLI and its queue fills on a detection, but nothing drains it — the pilot-facing channel for the drop/restore announcement is `/api/status` (02-09) and the browser badge (02-10). The authority *drop* itself is fully effective today, because it mutates the shared state the gate and floor read; it is only the spoken/rendered announcement that awaits a consumer.
- **The web entry point is untouched.** `web/server.py` still builds its `TelemetryClient` and `ClaudeClient` without authority, so the browser path runs at `full` until 02-09 lands. That asymmetry is intentional for one plan's duration and is the reason CLAUDE.md decision 26 describes both mechanisms.

## Threat Flags

None. This plan adds no network endpoint, auth path, file access or schema at a trust boundary — it wires existing components together. All seven `mitigate` dispositions in the plan's register are implemented and verified:

| Threat ID | Where it is closed |
|-----------|--------------------|
| T-02-08-01 | One `AuthorityState` in `main.py`, passed to all four consumers; identity asserted at runtime and by test (`is`, not `==`) |
| T-02-08-02 | No `try`/`except` around the construction; failure propagates and aborts startup, proven by a patched-to-raise run. `grep -c degraded_fallback main.py` → 0 |
| T-02-08-03 | Command-path deadline from `authority_tool_timeout_s`, entries removed from the class table, structural test asserts `>` and would fail on equality |
| T-02-08-04 | Detector subscribed directly to `TelemetryClient` in `main.py`; `ProactiveMonitor(` count 0 |
| T-02-08-05 | `ProactiveMonitor` not constructed; only `ProactiveEvent` reused |
| T-02-08-06 | `TOOL_DEFINITIONS`, the system enum and the `cache_control` static block untouched; confirmed by reading the diff |
| T-02-08-07 | Resolved level, reason and configured level logged once at INFO in `__init__`, after `logging.basicConfig` |
| T-02-08-SC | No packages installed; zero new dependencies |

## Notes for the Orchestrator

- STATE.md and ROADMAP.md were **not** modified (worktree mode; the orchestrator owns those writes post-wave).
- **REQUIREMENTS.md was not modified either**, following the precedent every prior plan in this phase set. The status is now genuinely different from wave 1–3, so here is the honest read rather than a blanket defer:
  - **AUTH-01** — *fully delivered.* `authority_level` flows from config to a single enforced gate in a running CLI process, backed by the `send_command` floor. Safe to mark.
  - **AUTH-05** — *fully delivered for the CLI*, with 02-06's coverage bound attached: six systems observable, throttle deliberately excluded, 13 structurally undetectable. The bound should travel with the requirement.
  - **AUTH-07** — *fully delivered.* The watchdog now latches in a running process, the floor then refuses, and the tool returns an advisory dict carrying `authority_reason: watchdog` for Claude to relay. The B3 fix in this plan is what makes the counter reachable at all.
  - **AUTH-06** — *partial.* The drop and the rolling cooldown are live, but the requirement says "and informs the pilot", and nothing drains `OverrideDetector.events` yet. That consumer is 02-09 / 02-10. Recommend holding this one until then.
- Wave 4 contains only this plan, so no concurrent agent is competing for these files.
- `verify.key-links` should now resolve all three of this plan's links: `main.py` → `authority.py` (`AuthorityState\(`), `claude_client.py` → `tools.py` (`authority=self._authority`, 3 occurrences), `main.py` → `override_detector.py` (`subscribe`, 2 occurrences).

## Next Phase Readiness

Ready. Downstream plans can now rely on:

- **02-09:** `ClaudeClient(..., verify_timeout=settings.authority_verify_timeout_s, command_tool_timeout=settings.authority_tool_timeout_s, authority=<AuthorityState>)`. The web `lifespan` should mirror `main.py`'s construction and ordering — `HealthMonitor` first, then the authority state, then `TelemetryClient(..., authority=, health=, command_timeout=)`, then the detector and its `subscribe` — differing only in the failure branch, where it substitutes `AuthorityState.degraded_fallback(str(exc))` instead of letting the exception abort the process. `main.py` is the reference implementation for everything except that branch.
- **02-09 / 02-10:** the CLI already populates `OverrideDetector.events`; a consumer added on the web side completes AUTH-06. Remember `AuthorityReason` has **four** members — a missing `degraded` arm renders a failed subsystem as a deliberate `advisory` configuration.
- **Anyone touching the timeouts:** `ClaudeClient.tool_timeout_for(name)` is the single resolution point, the two command-path tools are named in `_COMMAND_PATH_TOOLS`, and `test_claude_client.py::TestCommandPathToolTimeoutOrdering` fails loudly with the B3 argument if the arithmetic is inverted.

## Self-Check: PASSED

- Files claimed modified: all 5 present on disk with the described changes (`orchestrator/orchestrator/claude_client.py`, `orchestrator/orchestrator/main.py`, `orchestrator/tests/test_claude_client.py`, `tests/integration/test_tool_chain.py`, `CLAUDE.md`).
- Commits claimed: `f8b987f`, `ee3e6f2`, `0ce34dc` — all three present in `git log`.
- No files created, none deleted (`git diff --diff-filter=D` empty for all three commits); no untracked files left behind.

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-08-01*
