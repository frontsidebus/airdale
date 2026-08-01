---
phase: 02-authority-safety-layer
plan: 09
subsystem: safety
tags: [authority, web, composition-root, fail-safe, api-status, b8, auth-08, degraded]

# Dependency graph
requires:
  - phase: 02-authority-safety-layer
    plan: 01
    provides: AuthorityState / parse_authority_level / degraded_fallback / summary()
  - phase: 02-authority-safety-layer
    plan: 04
    provides: the frozen advisory and withheld result dicts, both carrying no `error` key
  - phase: 02-authority-safety-layer
    plan: 05
    provides: TelemetryClient(authority=, health=, command_timeout=), the floor, the ack watchdog
  - phase: 02-authority-safety-layer
    plan: 06
    provides: OverrideDetector, whose second composition root this is
  - phase: 02-authority-safety-layer
    plan: 08
    provides: ClaudeClient(verify_timeout=, command_tool_timeout=, authority=) and main.py as the reference wiring
provides:
  - "One AuthorityState per web process, shared by identity with TelemetryClient, ClaudeClient and OverrideDetector"
  - "Fail-SAFE web startup: a construction failure substitutes degraded_fallback(), never None; a fallback failure aborts startup"
  - "AppState.authority / .health / .override_detector, each defaulted to None for test construction only"
  - "/api/status authority_level, authority_reason, authority (full summary) and subsystems (HealthMonitor)"
  - "command_advisory and command_withheld chat-WebSocket message types (rendered by 02-10)"
  - "Override detection running on the browser telemetry stream"
  - "JSON-safe subsystem ages: an unseen subsystem renders null, not Infinity"
affects: [02-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fail-safe carve-out: the authority objects are excluded from the surrounding degrade-and-continue idiom, with the reason written at the site so 'making it consistent' is recognisably a regression"
    - "Absence-direction test for degradation policy: a component whose absence REDUCES what MERLIN may do may degrade; one whose absence INCREASES it may not"
    - "Render from summary() rather than branching per enum member, so a new member cannot silently lose its arm"
    - "Parametrisation driven off the enum members themselves, so adding a member extends coverage without editing the test"

key-files:
  created: []
  modified:
    - web/server.py
    - web/tests/test_rest.py
    - web/tests/test_chat_ws.py

key-decisions:
  - "The /api/status authority fields landed in the Task 1 commit, not Task 2: Task 1's own acceptance criteria assert the endpoint reports advisory/degraded on a construction failure, so the route change is what makes Task 1 verifiable"
  - "ClaudeClient also receives verify_timeout and command_tool_timeout from settings, mirroring main.py -- without them a configured authority_tool_timeout_s would not apply on the web path and RESEARCH B3 would be reopened for the browser"
  - "Advisory/withheld message text is short badge prose, not the tool's sentence: the tool's prose already reaches the pilot through Claude's spoken response, and the WebSocket frame is the visual badge"
  - "authority_level and authority_reason are copied through with .get() and no default, so a missing value arrives as null rather than being laundered into `config`"

patterns-established:
  - "Real-lifespan test harness for the web server: enter the lifespan context directly against a stand-in app (ASGITransport does not run lifespan events), then point routes at the produced state via dependency_overrides"
  - "Contract smoke check against the real producer: the frozen dict shapes the tests assert were re-derived by calling set_aircraft_control itself, not copied from prose"

requirements-completed: []

# Metrics
duration: 22min
completed: 2026-08-01
---

# Phase 02 Plan 09: Web Composition Root & Authority Visibility Summary

**The browser path now builds the same authority object graph the CLI does — one `AuthorityState` shared by the telemetry client, the Claude client and the override detector — except that where the CLI refuses to start, the web server starts *restricted*; and a command MERLIN deliberately never transmitted no longer reaches the pilot as a command that executed.**

## Performance

- **Duration:** ~22 min (base `935e250` → final task commit 15:59 local)
- **Tasks:** 3 planned, plus one Rule 1 fix found by a real-lifespan smoke run
- **Files modified:** 3 (0 created, 3 modified)
- **Tests added:** 36 (27 in `test_rest.py`, 9 in `test_chat_ws.py`)

## Accomplishments

- **The authority layer is live on the browser path.** Before this plan `web/server.py` built its `TelemetryClient` and `ClaudeClient` with no authority at all, so the gate read `full` and the floor, the ack watchdog and the override cooldown were inert no matter what `AUTHORITY_LEVEL` said. One `AuthorityState` is now constructed in `lifespan` and passed by identity to both, plus the `OverrideDetector` — asserted with `is`, not `==`, because a copy would let the gate and the floor disagree.
- **The blocker this plan was revised to fix is closed and pinned.** The authority objects are carved out of the surrounding degrade-and-continue idiom. A construction failure substitutes `AuthorityState.degraded_fallback(...)` — advisory, reason `degraded`, terminal — and if *that* raises, startup aborts. `state.authority` is assigned in exactly two places (`grep -n "state.authority = "` → lines 307 and 325) and neither is `None`, so there is no path out of `lifespan` on which it is `None`. Both failure paths have a named test whose failure message carries the whole argument.
- **The fail-open direction is now impossible to reach quietly.** The reasoning lives at the construction site in a comment naming what `None` means to each consumer, so a future contributor "making it consistent with its neighbours" is doing something visibly different from tidying.
- **The two entry points' asymmetry is preserved, not harmonised.** The CLI fails CLOSED (`grep -c degraded_fallback main.py` → 0, untouched by this plan); the web fails SAFE (`grep -c degraded_fallback server.py` → 1). Same guarantee — a wiring failure never *grants* authority — by two mechanisms suited to a foreground CLI and a browser server respectively.
- **RESEARCH B8 closed, and verified against the real producer.** `_on_tool_result` classified on the absence of an `"error"` key; the advisory and withheld dicts carry none by design. A smoke run calling the actual `set_aircraft_control` at advisory confirms it: `has 'error' key: False`, `OLD heuristic would report success: True`, `send_command called: False`. The pilot was being shown `GEAR DOWN` for a gear that never moved. Classification is now explicit on the `advisory` / `withheld` markers.
- **AUTH-08 is answerable in one call.** `/api/status` reports the level, the reason, the cooldown remaining, whether the watchdog is latched, the degraded detail, and the health of the command path. An absent authority state reports `advisory` / `degraded`, never `full` / `config`.
- **The missing-branch hazard is designed out, not just tested for.** The route reads `AuthorityState.summary()` rather than branching per enum member, so there is no arm to forget; a 12-case parametrised test driven off `AuthorityLevel` and `AuthorityReason` themselves means adding a member extends coverage without anyone remembering to.
- **Override detection runs in the browser too**, subscribed as its own callback beside the phase detector (D-11), without commissioning `ProactiveMonitor` (`grep -c "ProactiveMonitor("` → 0).
- Web suite 55 → **91 passed, 1 skipped**. Orchestrator 1302 / 2 xfailed, telemetry-service 38, integration at its documented baseline — all unchanged. Both CI-parity ruff commands clean.

## Task Commits

1. **Task 1: Wire authority, health and override detection into the web lifespan, fail-safe** — `0dba985` (feat)
2. **Task 2: Surface authority level, reason and subsystem health through /api/status** — `b35347d` (test)
3. **Task 3: Stop rendering advisory dry runs as successful commands** — `12a4f59` (fix)
4. **Rule 1 fix: /api/status no longer contradicts itself** — `4d53192` (fix)

## Files Created/Modified

- `web/server.py` — imports `AuthorityLevel` / `AuthorityReason` / `AuthorityState` / `parse_authority_level`, `OverrideDetector` and `HealthMonitor`, plus stdlib `math`; `AppState` gains `authority` / `health` / `override_detector`; new `_build_health_monitor()` (the CLI's five subsystem names) and `_json_safe_subsystems()`; the fail-safe authority block in `lifespan` with its rationale comment and the startup INFO line; `TelemetryClient(..., authority=, health=, command_timeout=)`; the `OverrideDetector` construction and its own `subscribe()`; `ClaudeClient(..., verify_timeout=, command_tool_timeout=, authority=)`; four new `/api/status` keys plus the health write-back; the three-way classification in `_on_tool_result`.
- `web/tests/test_rest.py` — `_RaisingAuthorityState` / `_TotallyBrokenAuthorityState`, the `_started_web_app` real-lifespan harness, `_StubAuthorityState`, `_get_status`, the `_FAIL_OPEN_REGRESSION` and `_MISSING_BRANCH` failure texts, and `_LEGACY_STATUS_KEYS`. 8 → **35** tests.
- `web/tests/test_chat_ws.py` — the four frozen result dicts copied from `tools.py`, `_chat_emitting` and `_outcome_messages` built on the existing `fake_chat` harness, and the `_B8_REGRESSION` failure text. 4 → **13** tests.

## Decisions Made

- **The `/api/status` authority fields shipped in the Task 1 commit.** Task 1's acceptance criteria assert that a construction failure is *visible at the endpoint* as `advisory` / `degraded` with `command_path` unhealthy — which cannot be true before the endpoint reports those keys. Splitting them would have left Task 1's own `<verify>` red. Task 2 then does what its action text is actually about: the 12-case matrix, the preserved-key assertion, the `None` case and the subsystem-health assertions.
- **`ClaudeClient` gets the two timeouts as well as the authority.** The plan's action text mentions only the authority, but its `<read_first>` says the web wiring must produce the same object graph as `main.py`, and 02-08's handover names all three. Without `command_tool_timeout`, a deployment that widens `authority_tool_timeout_s` would see it apply to the CLI and not the browser, and a genuine ack timeout on the web path could still be cancelled at the tool layer before the watchdog counted it — RESEARCH B3, reopened for one entry point.
- **Advisory/withheld badge text is short.** The gate's own prose ("Advisory authority -- I would lower the gear...") is returned to Claude and reaches the pilot spoken; the WebSocket frame is what the badge renders. Duplicating the sentence there would say the same thing twice in two registers. The frame carries `would_execute` so 02-10 can name the command precisely, and `safety_reason` so a withhold explains itself.
- **`authority_level` / `authority_reason` are forwarded with no default.** A missing value arrives as `null` and 02-10 renders it verbatim. Defaulting to `config` would have been the same class of lie as reporting a degraded state as `full`.
- **The override detector is constructed inside the already-connected branch**, mirroring both the phase detector beside it and `main.py`. See Deferred Issues for the consequence.
- **`claude_api` is deliberately left un-updated in the health write-back.** `/api/status` has no signal for it, and "registered, never observed" is honest where a fabricated `healthy: true` would not be.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `subsystems` would have made `/api/status` return 500**

- **Found during:** Task 1
- **Issue:** `HealthMonitor.summary()` reports `age_seconds` as `float("inf")` for any subsystem that has never been seen — which is every subsystem at startup, including `command_path`. Starlette's `JSONResponse` renders with `allow_nan=False`, so emitting the summary verbatim raises `ValueError: Out of range float values are not JSON compliant` and the endpoint 500s. Even with `allow_nan=True` the payload would be `Infinity`, which `JSON.parse` in the browser rejects. Confirmed directly against `JSONResponse.render` before fixing.
- **Fix:** `_json_safe_subsystems()` replaces a non-finite `age_seconds` with `None`. `null` is the honest wire value for "never seen"; a sentinel number would be one the browser could not tell from a real age.
- **Files modified:** `web/server.py`, `web/tests/test_rest.py`
- **Commit:** `0dba985`

**2. [Rule 1 - Bug] `/api/status` contradicted itself between `subsystems` and the top-level fields**

- **Found during:** final verification (the plan's real-dev-server `curl` item)
- **Issue:** Nothing on the web path had ever fed the `HealthMonitor` — the CLI does this in `start()` and `_update_bridge_health()`, the web server had no monitor at all until this plan. So the new `subsystems` block reported `chromadb.healthy: false` with an empty message in the same payload that said `chromadb_available: true`, and likewise for whisper and the bridge. A browser rendering both would show a working subsystem as down.
- **Fix:** the route feeds the three values it already measures back into the monitor before summarising, mirroring the CLI's `_update_bridge_health()` ahead of `get_health_summary()`. No authority value is written — a new test asserts two consecutive `GET`s leave `AuthorityState.summary()` byte-identical (T-02-09-03).
- **Files modified:** `web/server.py`, `web/tests/test_rest.py`
- **Commit:** `4d53192`

**Total deviations:** 2 (both Rule 1, both introduced by this plan's own new key)
**Impact on plan:** None on scope. Every acceptance criterion in all three tasks was verified as written.

## Issues Encountered

- **`httpx.ASGITransport` does not run lifespan events.** The plan's Task 1 says to run the app through its `lifespan` using "the existing `test_app` / `ASGITransport` harness", but that harness cannot start a lifespan. Resolved by entering `srv.lifespan(...)` directly against a stand-in app object and pointing the route at the produced state through `dependency_overrides` — which also keeps the module-level `app.state` untouched, so the real-lifespan tests cannot leak into the mock-state ones.
- **`test_chat_ws.py`'s commit message says "10 tests" and "4 -> 14"; the real numbers are 9 and 4 → 13.** An off-by-one in prose written before the final count; the code and the criteria (≥ 6 more tests) are unaffected. Recorded here rather than rewriting a pushed commit.
- **The worktree HEAD was behind the assigned base** (`80f22bf` vs `935e250`), so the sanctioned `git reset --hard` in the startup check applied, after the branch-namespace assertion passed. Same as 02-06 and 02-08.
- **The editable install points at the main checkout,** so a bare `python3 -m pytest web/tests/` resolves `orchestrator.*` from `/mnt/c/Users/bould/source/airdale/orchestrator`. Both trees are identical for this plan (no orchestrator file was touched), and the suite was run both ways — plain and with `PYTHONPATH=orchestrator` — with identical results.
- **Plan `<verify>` blocks `cd` to the main repo path,** as every prior plan in this phase noted. Run from the worktree root instead.

## Verification

- `python3 -m pytest web/tests/ -q` — **91 passed, 1 skipped** (baseline 55 / 1; +36, no pre-existing test modified)
- `PYTHONPATH=orchestrator python3 -m pytest web/tests/ -q` — same result, confirming the worktree orchestrator agrees with the installed one
- `python3 -m pytest web/tests/test_rest.py -q` — **35 passed** (baseline 8; +27, criterion ≥ +17)
- `python3 -m pytest web/tests/test_chat_ws.py -q` — **13 passed** (baseline 4; +9, criterion ≥ +6)
- `python3 -m pytest orchestrator/tests/ -q` — **1302 passed, 2 xfailed** (unchanged)
- `python3 -m pytest telemetry-service/tests -q --rootdir telemetry-service` — **38 passed** (unchanged)
- `PYTHONPATH=orchestrator python3 -m pytest tests/integration/ -q -m integration` — 20 failed / 21 passed / 31 errors, exactly the pre-existing baseline recorded by 02-08; deselected by default
- `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore SIM105,SIM117,F841,B008,B017,B007,UP041` — All checks passed
- `ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml` — 109 files already formatted
- `server.py` greps — `AuthorityState(` **1**, `degraded_fallback` **1**, `OverrideDetector(` **1**, `ProactiveMonitor(` **0**, `register("command_path")` **1**, `subscribe(` **2**, `command_advisory` **1**, `command_withheld` **1**
- `grep -vE '^\s*#' web/server.py | grep -c 'if.*authority_level ==\|elif.*authority_level =='` — **0**
- `grep -n "state.authority = " web/server.py` — exactly two sites (307 real, 325 degraded fallback); neither assigns `None`
- `grep -c "record_override\|clear_watchdog\|record_command_timeout" web/server.py` — **0** (no authority setter reachable from an endpoint, T-02-09-03)
- `git diff --numstat 935e250 HEAD` — exactly the three files in `files_modified`; no deletions in any of the four commits

### Real-lifespan smoke check (the plan's `curl localhost:3838/api/status` item)

Run in-process against the real `Settings`, the real `ContextStore`, the real turn detector and the real telemetry client, with `AUTHORITY_LEVEL=assisted`:

```
INFO merlin.web: Authority: assisted (reason: config, configured: assisted)
status: 200
authority_level: "assisted"
authority_reason: "config"
authority: {"level":"assisted","reason":"config","configured_level":"assisted",
            "cooldown_remaining_s":0.0,"watchdog_latched":false,
            "consecutive_timeouts":0,"degraded_detail":""}
subsystems: {"simconnect_bridge":{"healthy":false,"age_seconds":null,"message":"Disconnected"},
             "chromadb":{...,"message":"Unavailable; RAG disabled"},
             "whisper":{...},"claude_api":{...},"command_path":{...}}
turn keys: True 150 400
state.authority is None: False
```

The configured level is honoured end to end, all four new keys are present beside the pre-existing ones, and `age_seconds` renders as `null` — the deviation-1 fix is load-bearing, not defensive.

### B8 smoke check, against the real gate rather than a copied literal

```
gate keys: ['action','advisory','authority_level','authority_reason','command',
            'message','safety','sim_value','system','would_execute']
has 'error' key: False
OLD heuristic would report success: True
NEW classification: command_advisory
send_command called: False
authority fields: advisory / config
executed classification: command_status(success=True) | sent: [('GEAR_DOWN', 0)]
```

The dict shapes asserted in `test_chat_ws.py` were re-derived from `set_aircraft_control` itself, so the tests pin the real contract rather than the plan's description of it.

## Known Stubs

None. Every contract in the plan's `<interfaces>` block is implemented and exercised.

Two deliberate scope boundaries, named so the verifier does not read them as stubs:

- **`OverrideDetector.events` still has no drain.** The detector now *runs* on the browser path and its queue fills on a detection, but the pilot-facing announcement is rendered by 02-10. The authority *drop* is fully effective today — it mutates the shared state the gate and the floor read, and `/api/status` reports `authority_reason: "override"` the moment it happens — so AUTH-06's "and informs the pilot" is served by the status endpoint already; the badge and the spoken restore are 02-10's.
- **`ProactiveMonitor` is still not constructed anywhere.** Wiring it would switch on callouts, deviation alerts, emergency detection and checklist automation in the browser — deferred to its own phase.

## Threat Flags

None. This plan adds no new endpoint, auth path, file access or schema at a trust boundary — it extends one existing read-only `GET` and adds two message types to an existing WebSocket. All six `mitigate` dispositions in the plan's register are implemented and verified:

| Threat ID | Where it is closed |
|-----------|--------------------|
| T-02-09-01 | Explicit three-way classification on the `advisory` / `withheld` markers; regression test citing RESEARCH B8, plus a smoke check against the real gate output |
| T-02-09-03 | `/api/status` is `GET` and writes no authority value; `grep -c "record_override\|clear_watchdog\|record_command_timeout"` → 0, and a test asserts two calls leave `summary()` identical |
| T-02-09-04 | Values read from `AuthorityState.summary()`, not a branch; grep criterion at 0; 12-case matrix driven off the enum members themselves |
| T-02-09-05 | `subsystems.command_path` emitted from `HealthMonitor.summary()`, with a test pinning latched-watchdog-plus-cause |
| T-02-09-06 | Authority objects carved out of degrade-and-continue; `degraded_fallback` on failure, abort if that fails; two named tests, one per failure path |
| T-02-09-07 | The `None` branch emits `advisory` / `degraded` only; no `full` / `config` literal anywhere in that fallback |

T-02-09-02 (unauthenticated status disclosure) and T-02-09-08 (detector construction failure) were `accept` and remain accepted as written; T-02-09-SC holds — no package was installed.

## Notes for the Orchestrator

- STATE.md and ROADMAP.md were **not** modified (worktree mode; the orchestrator owns those writes post-wave).
- **REQUIREMENTS.md was not modified either**, following the precedent every plan in this phase set. The honest read now that both composition roots are wired:
  - **AUTH-02** — *fully delivered.* Advisory, withheld, blocked and executed are four distinguishable outcomes on both entry points, and the browser can no longer report a dry run as done. Safe to mark.
  - **AUTH-08** — *fully delivered for the data.* One `/api/status` call carries the level, the reason, the cooldown, the latch and the command-path health. The *rendering* is 02-10; if the requirement's acceptance is written in terms of what the pilot sees, hold it until then.
  - **AUTH-06** — the drop, the rolling cooldown and the reason are now live and visible on both paths. The spoken/badge announcement (draining `OverrideDetector.events`) is still 02-10's.
- Wave 5 — check whether any sibling agent also touches `web/server.py`; this plan rewrote `_on_tool_result` and the `/api/status` return dict.
- `verify.key-links` should resolve all three of this plan's links: `server.py` → `authority.py` (`AuthorityState`), `server.py` → `sim_client.py` (`HealthMonitor`), `server.py` → `app.js` (`command_advisory`, which `app.js` does not yet handle — that is 02-10's work and the link is forward-looking by design).

## Deferred Issues

**Override detection and phase detection are both skipped when telemetry is offline at startup.** Both are constructed inside `if state.sim_connected`, mirroring `main.py`. `TelemetryClient` auto-reconnects, so a web server started before the telemetry service (the normal docker-compose ordering) will later receive telemetry with neither subscriber attached — override detection would never fire for that process. The plan's threat register classifies a missing detector as an accepted capability loss (T-02-09-08) and it does not grant authority beyond the configured level, so this is not a fail-open. But the *cause* here is startup ordering rather than a construction failure, which the register did not consider. A fix is to subscribe unconditionally (`subscribe()` does not require a live connection) or to re-subscribe on reconnect; it applies equally to `main.py` and to the phase detector, so it belongs with whoever owns the reconnect path rather than in a web-only patch. Recorded here rather than in a shared `deferred-items.md` to avoid a shared-file write from a worktree agent.

**`web/requirements.txt` remains incomplete.** The web server imports `orchestrator.authority`, `orchestrator.override_detector` and `orchestrator.sim_client` and runs on the orchestrator venv, as RESEARCH records. This plan changes nothing there and adds no dependency, but the import surface grew.

## Next Phase Readiness

Ready. 02-10 can now rely on:

- `GET /api/status` returning `authority_level`, `authority_reason`, the full `authority` summary (7 keys) and `subsystems` (5 entries, `age_seconds` nullable), alongside every pre-existing field.
- Chat WebSocket frames `{"type": "command_advisory", system, action, message, would_execute, authority_level, authority_reason}` and `{"type": "command_withheld", system, action, message, authority_level, authority_reason, safety_reason}`, with `command_status` unchanged for executed and failed commands.
- `state.override_detector.events` populated on the browser path, ready to drain — a `PriorityQueue` of `ProactiveEvent` with `type == "authority"`, `data["event"]` of `"override"` or `"restore"`, and `data["fields"]` on the drop.

One caution for 02-10, inherited from 02-01 and worth restating: **`AuthorityReason` has four members.** A badge colour, status string or TTS phrasing that branches over it needs a `degraded` arm, or the one state that means "the safety subsystem failed to start" renders as a deliberate `advisory` configuration. The server side avoided the branch entirely by rendering from `summary()`; the browser cannot, so render an unrecognised reason verbatim rather than falling through to a default.

## Self-Check: PASSED

- Files claimed modified: all 3 present on disk with the described changes (`web/server.py`, `web/tests/test_rest.py`, `web/tests/test_chat_ws.py`).
- Commits claimed: `0dba985`, `b35347d`, `12a4f59`, `4d53192` — all four present in `git log`.
- No files created, none deleted (`git diff --diff-filter=D` empty for all four commits); no untracked files left behind.

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-08-01*
