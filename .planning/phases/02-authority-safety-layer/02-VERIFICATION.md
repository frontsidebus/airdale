---
phase: 02-authority-safety-layer
verified: 2026-08-03T00:23:14Z
status: human_needed
score: 12/12 must-haves verified (code-level); 1 residual human-verification item outstanding
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 8/12
  gaps_closed:
    - "Command outcomes are reported to the pilot without false confirmation (Gap 1 / CR-01, CR-02, CR-03) — closed by plans 02-11 and 02-12"
    - "Authority is bounded for commands this phase made reachable (Gap 2 / CR-04, CR-05) — closed by plan 02-14, and independently hardened further by two post-phase commits (4311487, f062bb4) that added a structural coverage guard and fixed a previously-unnoticed GEAR_TOGGLE gap"
    - "A detected pilot override informs the pilot, on both the CLI and the browser (Gap 3 / WR-06) — closed by plans 02-13 and 02-15"
  gaps_remaining: []
  regressions: []
deferred: []
human_verification:
  - test: "Induce a watchdog latch (e.g. stop the mock adapter mid-session or force three consecutive command timeouts) and watch the authority badge in the browser."
    expected: "Badge changes to ADVISORY with reason 'command path down' promptly, distinct from the pilot-override and configured-advisory states."
    why_human: "Visual appearance, color, and perceived responsiveness cannot be verified by static analysis. This specific scenario was never walked through live: 02-15's Task 3 checkpoint script (steps 1-10) exercises pilot-override, restore, multi-tab fan-out, disconnect and the unreachable-server state, but contains no step that induces a watchdog latch. The developer's 'approved' response to that checkpoint therefore cannot be read as covering this scenario — the mechanism is unit-tested (`web/tests/test_rest.py::test_status_reports_a_latched_watchdog_as_advisory_with_a_cause`, `AUTHORITY_REASON_TEXT['watchdog']` in app.js) but has not been observed live."
---

# Phase 2: Authority & Safety Layer Verification Report

**Phase Goal:** MERLIN's authority to act on the aircraft is explicit, bounded, and never ambiguous — a configurable level decides whether it may act at all, a detected pilot override or a dead command path drops it automatically, and the current level and its reason are visible
**Verified:** 2026-08-03T00:23:14Z
**Status:** human_needed
**Re-verification:** Yes — after gap closure (previous run 2026-08-01T23:39:23Z, `status: gaps_found`, 8/12)

## Summary

All three blocking gaps from the prior verification (false confirmation, unbounded authority, orphaned announcements) are closed in the codebase, not merely claimed in SUMMARY.md. Every fix was independently re-derived from source: `_was_transmitted` in `tools.py`, the mirrored predicate in `web/server.py::_on_tool_result`, the reordered `undo_last_command`, the `parking_brake` refusal table, six new `command_safety.py` rules, the bounded `OverrideDetector.events` queue, and both its consumers (`drain_authority_events` on the CLI, `_authority_event_pump` in the browser) all exist, are wired, and are covered by passing tests. Full suites were re-run rather than trusted: 1407 orchestrator (+2 xfailed), 111 web (+1 skipped), 38 telemetry-service, 5/5 `TestAuthorityEndToEnd`, CI-parity lint and format both clean — all match the measured baseline given for this verification.

Two things surfaced during this pass that the SUMMARYs did not fully account for:

1. **Two commits landed after plan 02-16 closed the phase, outside any plan (`4311487`, `f062bb4`).** They add a structural guard (`test_every_reachable_command_is_ruled_or_classified`, `test_safety_classification_tables_are_not_stale`) that forces every enum-reachable SimConnect event to be ruled, exempt-with-reason, or declared as a known gap — closing the exact class of silent gap that produced Gap 2 in the first place — and, in the process, found and fixed a real live defect (`GEAR_TOGGLE` was reachable with no rule, while `GEAR_UP` was blocked). `DEFAULT_RULES` is now 15, not the 13 that `CLAUDE.md`, `REQUIREMENTS.md` and `docs/SMART_CONTROLS.md` currently state. This is documentation drift introduced after the phase's own truth-up plan ran; it undersells the code's actual coverage rather than oversells it, and does not affect any must-have. Recorded as an INFO finding below.
2. **WR-08 (the only true end-to-end authority test never runs in CI) is still accurate — verified directly, not carried forward from the prior report.** `.github/workflows/python-ci.yml`'s "Integration Tests" job runs `cd orchestrator && pytest tests/ -m integration --override-ini="addopts="`. No test under `orchestrator/tests/` carries the `integration` marker (confirmed by grep and by running that exact command locally: `1409 deselected`). PR #79's own "Integration Tests" job log confirms `collected 1409 items / 1409 deselected / 0 selected` followed by the `|| echo "No integration tests found — skipping"` fallback — the job is a green no-op with respect to `tests/integration/test_tool_chain.py::TestAuthorityEndToEnd`, which lives in the *root* `tests/` directory and is never collected by any CI job. This is unchanged from the prior verification and remains a non-blocking WARNING.
3. **One human-verification item is genuinely still open, distinct from the two the developer already reviewed.** 02-15's blocking checkpoint (Task 3) was approved with a bare `approved` and no narrative — 02-15-SUMMARY.md and `.planning/REQUIREMENTS.md`'s AUTH-08 line both record this distinction explicitly, and this report preserves it: the checkpoint is **approved**, not **observed** or **confirmed**. Separately from that distinction, the checkpoint's own ten-step script never included a step that induces a watchdog latch — only pilot-override, restore, multi-tab fan-out, disconnect and the unreachable-server state were walked through. So the live visual behavior of the badge during a **watchdog** latch specifically was not exercised by anyone, approved or otherwise. That single item is carried forward in `human_verification:` below; the rest of what the checkpoint covered is treated as approved-not-observed and not re-demanded.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A configurable `authority_level` (advisory/assisted/full) governs whether MERLIN may act at all, enforced at the single point where `set_aircraft_control` reaches SimConnect (AUTH-01) | VERIFIED | Unchanged since last verification; re-confirmed: `authority.py` (338 lines, stdlib-only imports: `logging`, `time`, `collections.abc.Callable`, `enum.StrEnum`, `typing.Any`); `sim_client.py:518` re-reads `self._authority.level` at dispatch. |
| 2 | In `advisory`, `set_aircraft_control` describes the intended action and sends nothing, **and this now holds for the undo path too** (AUTH-02) | VERIFIED | Gap 1 closed. `tools.py:307` `_was_transmitted(result)` = `bool(result.get("success")) and "error" not in result`; gates `safety_note` at `tools.py:591`; `undo_last_command` (`tools.py:890-967`) peeks with `last_command`, calls `set_aircraft_control`, and only calls `pop_last()` at `:957` after `_was_transmitted(result)` is True — line order confirmed (`pop_last()` follows the `set_aircraft_control(` call). Untransmitted branch sets `undo_target` + `"Would reverse ..."`; never sets `undone_command`. |
| 3 | In `assisted`, a clean safety verdict executes, a `warning` verdict withholds, **and an absent verdict now withholds too rather than fail-open** (AUTH-03) | VERIFIED | `tools.py:475` `has_safety_verdict = safety_result is not None`; `:511` `safety_severity == "warning" or not has_safety_verdict`; `:556-559` sets `no_verdict: True` only on the absent-verdict branch, with its own message, never conflated with a fired warning. Confirmed the review's rejected form (`safety_severity in ("warning", "")`) is absent from the file. |
| 4 | In `full`, behaviour is unchanged — execute unless `blocked`, **and this is no longer vacuous for the surface CMD-07 widened** (AUTH-04) | VERIFIED | Gap 2 closed. `command_safety.py` `DEFAULT_RULES` now has entries for `FUEL_SELECTOR_OFF`, `FUEL_SELECTOR_SET` (index 0), `MIXTURE_SET` (cutoff), `CROSS_FEED_OPEN/OFF/TOGGLE`, `PARKING_BRAKES` (two rules) — all confirmed present in `command_safety.py:290-420`. `len(DEFAULT_RULES) == 15` (measured; see INFO-1 for the doc/code count mismatch). |
| 5 | Pilot override detection identifies manual input contradicting a MERLIN-issued command (AUTH-05) | VERIFIED | Unchanged; re-ran `test_override_detector.py` (38 tests incl. the new `TestAnnouncementQueueIsBounded` class) — all pass. |
| 6 | A detected override drops authority to advisory for a cooldown and MERLIN informs the pilot (AUTH-06) | VERIFIED | Gap 3 closed. `override_detector.py:66` `MAX_PENDING_ANNOUNCEMENTS = 32`; `:310` `_publish` (single `put_nowait` call site, confirmed by `grep -c`); CLI: `main.py` `drain_authority_events` (`:83`), wired via `_start_announcements` (`:294`), cancelled in `stop()`; browser: `web/server.py` `_authority_event_pump` (`:350`), `_authority_event_frame` (`:297`), `_broadcast_chat` (`:330`), started in `lifespan`, cancelled in shutdown; `AppState.chat_clients` registered on `ws.accept()` and removed in a `finally`. `app.js` `case 'authority_event':` at line 1001 calls `showCommandToast` and `renderAuthority(msg)`. |
| 7 | A watchdog bounds the dispatch→ack interval; on expiry MERLIN stops issuing commands and says so, **on both the CLI and the web path** (AUTH-07) | VERIFIED | Unchanged "stop" half; CLI "says so" gap (WR-07) closed by 02-13: `/status` prints `format_authority_status(self._authority.summary())`, new `/authority` command, `/authority` added to the `Commands:` help line — all confirmed present in `main.py`. |
| 8 | Authority level and reason are surfaced in `/api/status` and the web UI, **and the badge now moves at announcement time rather than up to 10s later** (AUTH-08) | VERIFIED (code); one live-visual scenario outstanding — see Human Verification | `web/server.py:644-683` unchanged; `app.js` `authority_event` case calls `renderAuthority(msg)` when the frame carries a level, closing IN-04 for override/restore. The watchdog-latch live-badge scenario specifically was never included in any checkpoint script — see `human_verification:`. |
| 9 | `CommandMap` registers a handler for every SimConnect event the enum-exposed systems can resolve to (CMD-07) | VERIFIED | Unchanged; `test_every_enum_exposed_event_has_an_adapter_handler` passes (adapter source present, so not skipped). |
| 10 | `carb_heat`/`fuel_pump` refuse `"on"`/`"off"` with an explicit cannot-confirm error; `"toggle"` still works, **and `parking_brake` — the one of the three that was actually reachable — now gets the same treatment** (CMD-08) | VERIFIED | Gap 2 closed. `tools.py:64-82` `UNCONFIRMABLE_POSITION_SYSTEMS` now includes `parking_brake`; `UNCONFIRMABLE_REFUSED_ACTIONS` maps `parking_brake` to `{on, off, release, set, apply, engage}`; resolver branch restricted to `if action == "toggle"` (`tools.py:192`); refusal lookup (`:412`) runs before the `Unknown control:` return (`:441`), confirmed by line order. |
| 11 | The six CMD-09 systems stay unregistered in the adapter | VERIFIED | Unchanged; `grep -n "MAGNETO_SET\|TOGGLE_STARTER1\|PRIMER\|CarbHeat\|FuelPump" SimConnectManager.cs` produces no output. |
| 12 | Semantic turn detection reaches the web path; degrades to fixed-silence when unavailable, **and the endpoint now honours its "never raises" contract with no ffmpeg present** (VARC-06) | VERIFIED | WR-01 closed by 02-12: `web/server.py:995-1010` wraps `decode_webm_to_samples` in `try/except Exception`, returns `_turn_probe_result("decode_failed", available=True)` on either a raise or a `None`. Live confirmation of the browser-visible symptom was part of 02-15's checkpoint (step 9) and is treated as approved, not observed — see Summary. |

**Score:** 12/12 truths VERIFIED at the code level. One narrower live-visual item (watchdog-latch badge behavior) was never exercised by any human step and is carried in `human_verification:`, which is why overall status is `human_needed` rather than `passed`.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `orchestrator/orchestrator/tools.py::_was_transmitted` | Single transmission predicate | VERIFIED | `tools.py:307-331`; docstring names `web/server.py::_on_tool_result` as the mirror site. |
| `orchestrator/orchestrator/tools.py` `safety_note` gate | Attached only on `_was_transmitted(result)` | VERIFIED | `tools.py:591`: `if command in CRITICAL_COMMANDS and _was_transmitted(result):` |
| `orchestrator/orchestrator/tools.py::undo_last_command` | Pops history only after transmission confirmed | VERIFIED | `pop_last()` at `:957`, strictly after the `set_aircraft_control(` call at `:940` and the `if not _was_transmitted(result):` guard at `:947`. |
| `orchestrator/orchestrator/tools.py` assisted no-verdict withhold | `no_verdict` marker, distinct wording | VERIFIED | `tools.py:475, 511, 556-559`. |
| `web/server.py::_on_tool_result` | Success computed from `result.get("success")`, not error-absence | VERIFIED | `web/server.py:1747`: `success = bool(result.get("success", False)) and "error" not in result`. |
| `web/server.py::turn_probe` | Guarded `decode_webm_to_samples` call | VERIFIED | `web/server.py:995-1010`, `try/except Exception` around the decode call. |
| `orchestrator/orchestrator/tools.py::UNCONFIRMABLE_REFUSED_ACTIONS` | Per-system refused-verb table incl. `parking_brake` | VERIFIED | `tools.py:79-83`. |
| `orchestrator/orchestrator/command_safety.py::DEFAULT_RULES` | Rules for fuel selector, mixture, crossfeed, parking brake | VERIFIED (exceeds spec) | 15 rules present (documentation says 13 — see INFO-1); all six Gap-2 rules confirmed by name (`fuel_selector_off_in_flight`, `fuel_selector_set_to_off_in_flight`, `mixture_cutoff_in_flight`, `crossfeed_change_in_flight`, `parking_brake_on_the_roll`, `parking_brake_in_flight`) plus two more added post-phase (`spoilers_deployed_low`, `flaps_retracted_low`) and a `GEAR_TOGGLE` fix folded into the two pre-existing gear rules. |
| `orchestrator/tests/test_command_coverage.py::test_every_reachable_command_is_ruled_or_classified` | Structural guard: every reachable event ruled, exempt, or declared | VERIFIED (new, post-phase) | Present and passing; `SAFETY_EXEMPT_EVENTS` measured at 31 entries, `UNGUARDED_KNOWN_GAPS` at 1 (`PROP_PITCH_SET`, with a documented aircraft-dependent-range rationale). |
| `orchestrator/orchestrator/override_detector.py::MAX_PENDING_ANNOUNCEMENTS` / `_publish` | Bounded queue, non-raising publish | VERIFIED | `:66` (`= 32`), `:310` (`_publish`); `grep -c "self._events.put_nowait"` → 1 (only inside `_publish`). |
| `orchestrator/orchestrator/main.py::drain_authority_events` / `format_authority_status` | CLI announcement consumer + status formatter | VERIFIED | `main.py:49, 83`; wired via `_start_announcements` (`:294`) and `_on_announce_task_done` (`:481`). |
| `web/server.py::_authority_event_pump` / `_authority_event_frame` / `_broadcast_chat` | Browser announcement consumer | VERIFIED | `web/server.py:297, 330, 350`; started in `lifespan` (`:550`), cancelled in shutdown (`:641-645`); `AppState.chat_clients` (`:165`) registered/discarded around `ws_chat`. |
| `web/static/app.js` `case 'authority_event':` | Chat-log message, toast, badge refresh | VERIFIED | `app.js:581-1005`; calls `showCommandToast` and `renderAuthority(msg)`; attaches text via `spanWithText`, no new `innerHTML` interpolation. |
| `CLAUDE.md` decision 26 | Names `_was_transmitted`, both announcement consumers, the refusal table | VERIFIED | Confirmed present via grep for `drain_authority_events`, `_authority_event_pump`, `_was_transmitted`, `UNCONFIRMABLE_REFUSED_ACTIONS`, `MAX_PENDING_ANNOUNCEMENTS`. |
| `.planning/REQUIREMENTS.md` Phase 2 ledger | Every AUTH/CMD box cites evidence | VERIFIED | AUTH-01…08, CMD-07, CMD-08 all checked with plan+artefact citations; CMD-09 remains unchecked with its sequencing sentence intact; non-goal paragraph reconciles the six new rules. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `tools.py::undo_last_command` | `tools.py::_was_transmitted` | branch on transmission before mutating history | WIRED | Confirmed by line order and by `grep`. |
| `tools.py::set_aircraft_control` | `CRITICAL_COMMANDS` | `safety_note` gated on `_was_transmitted` | WIRED | |
| `web/server.py::_on_tool_result` | `tools.py::_was_transmitted` (mirrored expression) | identical boolean expression, both docstrings cross-reference the other | WIRED | Confirmed both expressions are textually identical: `bool(result.get("success", False/None)) and "error" not in result`. |
| `override_detector.py::events` | `orchestrator/main.py::drain_authority_events` | `asyncio.create_task` in `_start_announcements` | WIRED | |
| `override_detector.py::events` | `web/server.py::_authority_event_pump` | `asyncio.create_task` in `lifespan` | WIRED | |
| `web/server.py::_authority_event_pump` | every `AppState.chat_clients` socket | `_broadcast_chat` iterating a snapshot copy | WIRED | Disconnect-tolerant (discards on send failure), confirmed by `test_authority_events.py`. |
| `app.js` `authority_event` case | `app.js::renderAuthority` | `msg.authority_level`/`authority_reason`/`authority` read directly from the frame | WIRED | No second reason-to-text mapping introduced (`AUTHORITY_REASON_TEXT` count unchanged). |
| `command_safety.py::DEFAULT_RULES` (Gap-2 rules) | authority gate (`assisted`/`full`) | `blocked` short-circuits before send; `warning` drives `assisted` withhold | WIRED | Confirmed via `test_command_safety.py` (fuel/mixture/crossfeed/parking-brake classes, all passing) and via the reachable-surface guard test. |
| `orchestrator/tests/test_command_coverage.py` guard | `command_safety.py::DEFAULT_RULES` + `SAFETY_EXEMPT_EVENTS` + `UNGUARDED_KNOWN_GAPS` | set-difference assertion at collection time | WIRED (new) | Silence now fails CI for any newly-reachable, unclassified event — this is the structural fix for how Gap 2 originally happened. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| Undo result `undo_description` | string built in `undo_last_command` | Now conditional on `_was_transmitted(result)`, computed after the real `set_aircraft_control` call | Yes — text now matches whether a reversal actually happened | FLOWING (was HOLLOW at prior verification) |
| Web `command_status` `success` field | `bool(result.get("success", False)) and "error" not in result` | `TelemetryClient.send_command` ack, real adapter response | Yes — computed field now agrees with `result["success"]` in every documented ack shape | FLOWING (was HOLLOW at prior verification) |
| `authority_event` browser frame | `event.data`, `state.authority.summary()` | Real `ProactiveEvent` from `OverrideDetector`, real `AuthorityState` | Yes | FLOWING (was DISCONNECTED — no consumer at all — at prior verification) |
| CLI authority announcement | `event.message` | Real `ProactiveEvent` via `drain_authority_events` | Yes | FLOWING (was DISCONNECTED at prior verification) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full orchestrator suite | `cd orchestrator && python3 -m pytest -q` | `1407 passed, 2 xfailed` | PASS — matches the measured baseline given for this verification |
| Full web suite | `cd web && python3 -m pytest -q` | `111 passed, 1 skipped` | PASS — matches baseline |
| Full telemetry-service suite | `cd telemetry-service && python3 -m pytest -q` | `38 passed` | PASS — matches baseline |
| End-to-end authority chain | `python3 -m pytest tests/integration/test_tool_chain.py -k TestAuthorityEndToEnd --override-ini="addopts=" -q` (repo root) | `5 passed, 20 deselected` | PASS — matches baseline |
| CI-parity lint | `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore SIM105,SIM117,F841,B008,B017,B007,UP041` | `All checks passed!` | PASS |
| CI-parity format | `ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml` | `111 files already formatted` | PASS |
| Gap 2 targeted rules | `pytest tests/test_command_safety.py tests/test_command_coverage.py tests/test_tools.py -q` | `222 passed` | PASS |
| Authority/override/watchdog regression | `pytest tests/test_authority.py tests/test_override_detector.py tests/test_sim_client.py tests/test_main_authority.py tests/test_claude_client.py -q` | `257 passed` | PASS |
| CMD09 deferral intact | `grep -n "MAGNETO_SET\|TOGGLE_STARTER1\|PRIMER\|CarbHeat\|FuelPump" adapters/msfs/SimConnectManager.cs` | no output | PASS |

### Probe Execution

Step 7c: SKIPPED — no `scripts/*/tests/probe-*.sh` files exist in this repository and no plan or SUMMARY for this phase declares a probe script. Verification relies on the pytest suites and the direct end-to-end integration test instead, all re-run above.

### CI Evidence (cannot be run locally)

`dotnet` is not installed in this environment, so the C# adapter suite (`SimConnectBridge.Tests`) could not be run directly and no local count is asserted, consistent with what 02-14's and 02-16's own SUMMARYs recorded. Checked GitHub Actions on PR #79 (`feat(authority): authority levels, override detection and command-path watchdog`) instead:

| CI Job | Result | Detail |
|--------|--------|--------|
| Build & Test (.NET 8) | PASS | `Passed! - Failed: 0, Passed: 119, Skipped: 0, Total: 119` (from the job's raw log) |
| Integration Tests | PASS, but collects nothing relevant | `collected 1409 items / 1409 deselected / 0 selected` → `No integration tests found — skipping` (fallback echo). This job's "pass" is not evidence `TestAuthorityEndToEnd` ran in CI — see WR-08 below. |
| Lint & Test | PASS | |
| Validate v2 Modules | PASS | |

This CI evidence is attributed to CI, not treated as a local run.

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|-----------------|--------------|--------|----------|
| AUTH-01 | 02-01, 02-04, 02-05, 02-08 | Configurable level enforced at the single SimConnect-reaching point | SATISFIED | Truth #1 |
| AUTH-02 | 02-04, 02-11, 02-12 | Advisory describes and sends nothing, including undo | SATISFIED (was BLOCKED) | Truth #2; Gap 1 closed |
| AUTH-03 | 02-04, 02-11, 02-14 | Assisted executes clean, withholds warning, withholds absent verdict | SATISFIED | Truth #3; residual WR-10 part 2 (stale-telemetry liveness) not scored — concerns freshness, not severity, and was deliberately deferred with a stated reason |
| AUTH-04 | 02-04, 02-14 | Full preserves current behavior, now non-vacuous for the widened surface | SATISFIED (was undermined) | Truth #4; Gap 2 closed |
| AUTH-05 | 02-06 | Override detection identifies manual input | SATISFIED | Truth #5; residual WR-05 (reconnect false-positive) not scored, deliberately deferred |
| AUTH-06 | 02-06, 02-13, 02-15 | Drop to advisory + inform the pilot, on CLI and browser | SATISFIED (was BLOCKED) | Truth #6; Gap 3 closed |
| AUTH-07 | 02-05, 02-08, 02-13 | Watchdog bounds dispatch→ack, stops issuing, says so on both interfaces | SATISFIED | Truth #7; WR-07 (CLI silence) closed |
| AUTH-08 | 02-09, 02-10, 02-15 | Level+reason surfaced in `/api/status` and web UI, badge reacts at announcement time | SATISFIED (code); one live scenario open | Truth #8; see `human_verification:` |
| CMD-07 | 02-02, 02-14 | Adapter registers every enum-exposed resolvable event, safely | SATISFIED | Truth #9; Gap 2's CMD-07 half closed |
| CMD-08 | 02-04, 02-14 | carb_heat/fuel_pump/parking_brake refuse unconfirmable actions | SATISFIED | Truth #10 |
| CMD-09 | — (explicitly deferred) | Six unreachable systems stay unregistered | SATISFIED (deferral honored) | Truth #11 |
| VARC-06 | 02-03, 02-12 | Semantic turn detection on web path, never-raises contract restored | SATISFIED | Truth #12 |

No orphaned requirement IDs: every ID in ROADMAP.md's "AUTH-01 through AUTH-08, CMD-07, CMD-08, VARC-06 (CMD-09 deferred)" line is present in `.planning/REQUIREMENTS.md`'s Phase 2 section, checked or explicitly deferred with citations. `.planning/REQUIREMENTS.md`'s own Phase 2 ledger cross-checked directly against source and tests in this pass — not merely read and trusted.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `CLAUDE.md`, `.planning/REQUIREMENTS.md`, `docs/SMART_CONTROLS.md` | test-count / rule-count bullets | Test counts (1,389/111/38) and `DEFAULT_RULES` count (13) are stale by 18 tests and 2 rules respectively, because two commits (`4311487`, `f062bb4`) landed after plan 02-16's truth-up ran | ℹ️ INFO | Documentation undersells actual coverage (real count is 1407/111/38 tests, 15 rules, plus a new structural guard and `GEAR_TOGGLE` fix not mentioned anywhere in the docs). Does not affect any must-have — the code is more protective than documented, not less. |
| `tests/integration/test_tool_chain.py` | 30 | `TestAuthorityEndToEnd` marked `pytest.mark.integration`; confirmed directly this pass that no CI job actually collects it (`orchestrator/tests/ -m integration` selects 0; the root `tests/` dir is never targeted by any workflow) | ⚠️ WARNING (unchanged from prior verification, independently re-confirmed via PR #79's raw job log) | The phase's own described "only place the whole chain runs together" still never runs in CI. Passes when run directly (5/5), which this verification re-ran. |
| `tests/integration/test_tool_chain.py` | ~409 | Comment still says the web layer's heuristic "depends on" the absence of an `error` key — that heuristic was deliberately removed by 02-12 | ⚠️ WARNING (unchanged, deliberately deferred per 02-14's notes to avoid a merge collision with 02-12) | Misleading comment only; no behavioral effect. |
| `web/server.py` | ~757-775 | Turn-probe throttle still does not bound a rotating source on an unauthenticated, CORS-open, ffmpeg-spawning endpoint (WR-09) | ⚠️ WARNING (unchanged, deliberately deferred — needs a deployment-posture decision) | Recorded, not newly discovered. |
| `orchestrator/orchestrator/claude_client.py` | ~767 | `execute_procedure`'s hardcoded 30s tool timeout can still pre-empt a 4-step procedure before the watchdog counter increments (WR-02) | ⚠️ WARNING (unchanged, deliberately deferred) | Recorded, not newly discovered. |
| `orchestrator/orchestrator/tools.py` | 174, 180 | `RUDDER_TRIM_SET`/`AILERON_TRIM_SET`/`FUEL_SELECTOR_SET` values still unclamped before reaching the adapter (WR-11) | ⚠️ WARNING (unchanged, deliberately deferred — needs per-event SimConnect ranges) | Recorded, not newly discovered. |
| `orchestrator/orchestrator/override_detector.py` | 94-100 | `AP_HDG_HOLD`/`AP_ALT_HOLD`/`AP_VS_HOLD`/`AP_AIRSPEED_HOLD` still map to non-empty tuples that do not correspond to a real telemetry field (IN-02) | ℹ️ INFO (unchanged, deliberately deferred) | Recorded, not newly discovered. |
| `web/server.py` | 1699 | `_on_tool_result`'s tool-name guard still excludes `undo_last_command`/`execute_procedure` from producing a browser command frame (IN-03) | ℹ️ INFO (unchanged, deliberately deferred) | Recorded, not newly discovered. |

No unresolved `TBD`/`FIXME`/`XXX` markers found in any file this phase (including the two post-phase commits) modified.

### Human Verification Required

1. **Watchdog latch — live authority badge behavior**

   **Test:** Induce a watchdog latch (three consecutive command-ack timeouts, or stop the mock/adapter mid-session so acks stop arriving) while a browser tab is open, and observe the authority badge.
   **Expected:** Badge moves to ADVISORY with reason "command path down" (or equivalent watchdog wording), visually distinguishable from a pilot-override advisory state and from a configured-advisory state.
   **Why human:** Visual/perceived-timing judgment cannot be verified statically. This scenario specifically was never included in 02-15's Task 3 checkpoint script (which covered override, restore, multi-tab, disconnect, and the unreachable-server state, but not a watchdog latch), so no developer approval — blanket or narrated — has ever covered it. The underlying mechanism is unit-tested (`test_status_reports_a_latched_watchdog_as_advisory_with_a_cause`, `AUTHORITY_REASON_TEXT['watchdog']`), which is why this is not scored as a blocking gap, only as an outstanding live check.

**Previously-approved items, not re-demanded here:** The pilot-override/restore live-badge behavior, multi-tab fan-out, client-disconnect resilience, the unreachable-server state, and the ffmpeg-absent voice-degradation fallback were all walked through in 02-15's Task 3 checkpoint and closed with a developer response of exactly `approved`. Per 02-15-SUMMARY.md and `.planning/REQUIREMENTS.md`'s AUTH-08 line, that approval is recorded as **approved**, not **observed** or **confirmed** — no narrative was given for the legibility/timing judgment (step 10) or the ffmpeg scenario (step 9). This verification preserves that distinction rather than upgrading it, and does not re-list those items as open, because a formal blocking gate already ran and the developer signed off on it.

### Gaps Summary

No blocking gaps remain. All three findings from the prior verification are closed at the code level, re-derived independently in this pass rather than trusted from SUMMARY.md:

1. **Command outcomes are now trustworthy under failure (Gap 1 closed).** `_was_transmitted` is the single predicate gating `safety_note`, the undo pop, and (mirrored) the browser's `success` computation. All three paths were read directly from source and confirmed to match their described fix.
2. **Authority is now uniformly bounded (Gap 2 closed, and then some).** `parking_brake` is refused outside an explicit toggle; the fuel/mixture/crossfeed surface CMD-07 made reachable now carries six rules with a severity rationale consistent with the `MAGNETO_SET` precedent. Two commits landed after the phase's own gap-closure work (outside any plan) went further and added a structural guard that fails CI if any future change reaches a new SimConnect event without a rule, an exemption, or a declared gap — closing the systemic cause of Gap 2, not just its two known instances — and used that guard to find and fix a real `GEAR_TOGGLE` gap this phase's own plans had missed.
3. **AUTH-06's pilot-facing half now exists on both interfaces (Gap 3 closed).** The announcement queue is bounded, cannot raise from a telemetry callback, and has exactly one named consumer per process on each of the CLI and the browser, both covered by tests exercising the frame shape, fan-out, and disconnect tolerance.

The phase goal — authority that is explicit, bounded, and never ambiguous, with level and reason visible — is achieved in the codebase. `status: human_needed` rather than `passed` reflects one narrow, honestly-scoped live-visual check (watchdog-latch badge behavior) that no human has yet exercised, distinguished carefully from the broader checkpoint that was already run and approved. This is a WARNING-level item for developer decision, not a blocker: the developer may close it with a two-minute live check, or explicitly accept the unit-test coverage as sufficient and note that decision for the record.

---

_Verified: 2026-08-03T00:23:14Z_
_Verifier: Claude (gsd-verifier)_
