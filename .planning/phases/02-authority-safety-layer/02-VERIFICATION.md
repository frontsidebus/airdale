---
phase: 02-authority-safety-layer
verified: 2026-08-01T23:39:23Z
status: gaps_found
score: 8/12 must-haves verified
overrides_applied: 0
gaps:
  - truth: "Command outcomes are reported to the pilot without false confirmation ('never ambiguous')"
    status: failed
    reason: >
      Three separate paths still produce a false "it worked" signal for a command
      that was refused, NACKed, or never transmitted. This is the exact failure
      class the phase's own docstrings describe as fixed ("the pilot saw 'GEAR
      DOWN' for a gear that never moved"), but the fix did not reach all call
      sites.
    artifacts:
      - path: "web/server.py:1535"
        issue: >
          `success = "error" not in result` is unchanged in `_on_tool_result`'s
          fall-through arm. `TelemetryClient.send_command` returns a negative
          adapter ack as `{"success": False, "message": "..."}` with no `error`
          key (sim_client.py:576-579 documents this as routine), so a refused
          command renders as a green executed command in the browser.
      - path: "orchestrator/orchestrator/tools.py:469-470"
        issue: >
          `result["safety_note"] = "Critical system change executed"` is attached
          unconditionally for CRITICAL_COMMANDS, including on adapter NACKs and on
          authority-floor refusals where `result["error"]` simultaneously states
          nothing was sent. This payload goes to Claude on both the CLI and web
          paths.
      - path: "orchestrator/orchestrator/tools.py:789-818"
        issue: >
          `undo_last_command` calls `command_history.pop_last()` before invoking
          `set_aircraft_control`. At advisory (or any refusal), the undo record is
          destroyed but the returned dict still says
          `undo_description: "Reversed <cmd>: ..."` — a false confirmation in the
          past tense stacked on top of `advisory: True`.
    missing:
      - "web/server.py: success = bool(result.get('success', False)) and 'error' not in result"
      - "tools.py: gate safety_note on result.get('success') before attaching it"
      - "tools.py: undo_last_command must not pop_last() until set_aircraft_control confirms the command was actually sent"
      - "web/tests/test_chat_ws.py: a case for {'success': False} with no 'error' key"
      - "orchestrator/tests/test_tools.py: assert len(history) == 1 after an advisory/withheld undo"
  - truth: "Authority is bounded — commands this phase newly made reachable carry the same safety posture as the ones they replaced"
    status: failed
    reason: >
      The phase's own CMD-07 work made two classes of command reachable with
      strictly less protection than the systems deliberately held back for the
      identical reason (CMD-09 / D-01).
    artifacts:
      - path: "orchestrator/orchestrator/tools.py:167-168"
        issue: >
          `parking_brake` resolves every action ("on", "off", "release", "toggle")
          to the same `PARKING_BRAKES` toggle event. It is in `CRITICAL_COMMANDS`,
          in the `set_aircraft_control` enum, and registered in the adapter's
          CommandMap, but is absent from `UNCONFIRMABLE_POSITION_SYSTEMS` (which
          lists only `carb_heat`/`fuel_pump`, neither of which Claude can name or
          the adapter can execute) and absent from `command_safety.DEFAULT_RULES`
          (7 rules; none for PARKING_BRAKES). "Parking brake off" on landing
          rollout sets the brake.
      - path: "orchestrator/orchestrator/command_safety.py:123-179"
        issue: >
          `DEFAULT_RULES` has no entry for `FUEL_SELECTOR_OFF`, `CROSS_FEED_OPEN`,
          `CROSS_FEED_OFF`, `CROSS_FEED_TOGGLE`, or `MIXTURE_SET`. These were
          newly registered in `adapters/msfs/SimConnectManager.cs` by this
          phase's CMD-07 plan (confirmed: FuelSelectorOff/All/Left/Right/Set,
          CrossFeedOpen/Off/Toggle all present) and are reachable directly via
          the `fuel_selector`/`crossfeed` systems in the tool enum. Meanwhile
          `MAGNETO_SET` was deliberately deferred to CMD-09 with the stated
          reason that registering it "turns a named tool call into a working
          in-flight engine shutdown with nothing in front of it" — `fuel_selector
          off` in flight is the same failure by a different route, and at the
          default `AUTHORITY_LEVEL=full` with no rule, nothing stops it.
    missing:
      - "Add parking_brake to UNCONFIRMABLE_POSITION_SYSTEMS (or a blocking rule) plus a RESOLVER_BRANCH_TABLE row"
      - "Add a blocked SafetyRule for FUEL_SELECTOR_OFF/CROSS_FEED_OFF in flight, or defer them alongside CMD-09"
  - truth: "A detected pilot override drops authority to advisory and informs the pilot (AUTH-06)"
    status: partial
    reason: >
      The drop-to-advisory half works (AuthorityState.record_override is called
      and verified by test_override_detector.py). The "informs the pilot" half
      does not: OverrideDetector.events is an unbounded asyncio.PriorityQueue
      that both composition roots construct and subscribe to telemetry, but
      neither orchestrator/orchestrator/main.py nor web/server.py ever reads
      `.events`. The "You've taken the flaps..." and "Back to full authority..."
      ProactiveEvent objects are constructed and immediately orphaned. All three
      executors who touched this path (02-08, 02-09, 02-10 SUMMARYs) reached the
      same conclusion and declined to mark AUTH-06 complete for this reason.
    artifacts:
      - path: "orchestrator/orchestrator/override_detector.py:204-212"
        issue: "events property has no consumer anywhere in the codebase"
      - path: "orchestrator/orchestrator/main.py:108-114"
        issue: "constructs and subscribes OverrideDetector but never touches .events"
      - path: "web/server.py:382-392"
        issue: "constructs and subscribes OverrideDetector but never touches .events"
    missing:
      - "Drain detector.events in the CLI conversation loop and speak it via VoiceOutput, or in web/server.py into an authority_event chat-WS frame"
      - "Alternative: bound the queue (maxsize=32, drop-oldest put) and document it explicitly as a future hook rather than a delivered mechanism"
deferred: []
human_verification:
  - test: "Watch the authority badge in the browser during a pilot override (move flaps by hand while MERLIN is in full authority) and during a simulated watchdog latch."
    expected: "Badge changes color/label promptly and the reason text matches (override vs watchdog vs config vs degraded); an advisory dry-run and an assisted withhold render as visually distinct states from a successful command."
    why_human: "Visual appearance, color contrast, and real-time perceived responsiveness cannot be verified by static analysis; IN-04 notes up to 10s of poll lag that a human should judge as acceptable or not."
  - test: "Run the orchestrator with no ffmpeg on PATH and speak through a full VAD cycle in the browser during active speech."
    expected: "Voice input keeps working via the fixed-silence fallback with no visible error and no server-side 500 in the browser console/network tab."
    why_human: "WR-01 shows decode_webm_to_samples can raise outside any try/except in the /api/turn-probe handler; confirming the user-visible symptom (or absence of one) needs a live browser session."
---

# Phase 2: Authority & Safety Layer Verification Report

**Phase Goal:** MERLIN's authority to act on the aircraft is explicit, bounded, and never ambiguous — a configurable level decides whether it may act at all, a detected pilot override or a dead command path drops it automatically, and the current level and its reason are visible
**Verified:** 2026-08-01T23:39:23Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A configurable `authority_level` (advisory/assisted/full) governs whether MERLIN may act at all, enforced at the single point where `set_aircraft_control` reaches SimConnect (AUTH-01) | VERIFIED | `authority.py` (338 lines, stdlib-only import graph confirmed by grep); `config.py` 8 `authority_*` fields + cross-field validator; `tools.py:390` gate; `sim_client.py:518` level-only floor re-reads `self._authority.level` at dispatch, no caller-supplied level. |
| 2 | In `advisory`, `set_aircraft_control` describes the intended action and sends nothing (AUTH-02) | VERIFIED (direct calls) / FAILED (undo path) | `tools.py:394-418` returns `advisory: True`, `would_execute`, no transmission — correct for direct calls. But `undo_last_command` (`tools.py:789-818`) pops the history entry *before* the gate runs and unconditionally appends `undo_description: "Reversed ..."` even when nothing was sent — see Gap 1. |
| 3 | In `assisted`, a clean safety verdict executes and a `warning` verdict withholds (AUTH-03) | VERIFIED, with a caveat | `tools.py:420-450` implements the branch correctly. Caveat (WR-10, not a blocker): when `sim_client.get_state()` raises/returns None, `safety_severity` is `""`, which takes the same "execute" path as a clean verdict — a missing verdict is treated as a passing one. |
| 4 | In `full`, behaviour is unchanged — execute unless `blocked` (AUTH-04) | VERIFIED literally, undermined in practice | The branch itself is unchanged. But see Gap 2: several newly-reachable commands have no rule that could ever produce `blocked`, so "unless blocked" is vacuous for them. |
| 5 | Pilot override detection identifies manual input contradicting a MERLIN-issued command (AUTH-05) | VERIFIED | `override_detector.py` — `COMMAND_WATCHED_FIELDS` (6 observable systems), attribution against `TelemetryClient.recent_dispatches()` (one monotonic clock, confirmed no wall-clock mixing), epsilon/settle/grace windows; `orchestrator/tests/test_override_detector.py` (484 lines) passes. WR-05 (not a blocker): a mid-session orchestrator↔service reconnect is not recognized as a "everything moved at once" event the way an adapter reconnect is, so pilot inputs during an outage can register as a false override on resume. |
| 6 | A detected override drops authority to advisory for a cooldown and MERLIN informs the pilot (AUTH-06) | PARTIAL — see Gap 3 | Drop mechanism verified (`_record_override` → `AuthorityState.record_override`, confirmed called and covered by tests). "Informs the pilot" is dead code — `OverrideDetector.events` has no consumer in either composition root. |
| 7 | A watchdog bounds the dispatch→ack interval; on expiry MERLIN stops issuing commands and says so (AUTH-07) | VERIFIED (stop) / PARTIAL (says so) | `sim_client.py` — counter increments only on the future actually timing out (`except TimeoutError`, not a pre-empted tool timeout), latches after N consecutive timeouts, floor refuses every subsequent command, clears only via reconnect/out-of-band `clear_watchdog`. "Says so": surfaced on the web path via `/api/status` + badge; **not surfaced anywhere in the CLI** — `/status` and `/health` print SimConnect/context-store/TTS/capture/Whisper/HealthMonitor but never call `AuthorityState.summary()` (WR-07). Treated as a warning, not a blocker, because at least one interface (web) delivers it. |
| 8 | Authority level and reason are surfaced in `/api/status` and the web UI (AUTH-08) | VERIFIED | `web/server.py:644-683` — `authority_level`, `authority_reason`, full `authority` summary dict, `subsystems` (command_path health) all present; every pre-existing status key preserved (spot-checked `whisper_available`, `elevenlabs_configured`). `app.js` `renderAuthority`/`AUTHORITY_REASON_TEXT` (4 arms, `hasOwn` guard, no silent fallthrough) and `renderAuthorityUnknown()` for an unreachable server. `index.html`/`style.css` carry the `status-authority` element and per-level/per-reason classes. |
| 9 | `CommandMap` registers a handler for every SimConnect event the enum-exposed systems can resolve to; `trim`/`deice`/`fuel_selector`/`crossfeed` stop reporting phantom success (CMD-07) | VERIFIED | `test_every_enum_exposed_event_has_an_adapter_handler` and the C#-side `CommandMapTests.cs` (297 lines) both pass; confirmed `FuelSelectorOff/All/Left/Right/Set`, `CrossFeedOpen/Off/Toggle`, `RudderTrimLeft` etc. registered in `SimConnectManager.cs`. Side effect: this is what creates Gap 2 (CR-05). |
| 10 | `carb_heat`/`fuel_pump` refuse `"on"`/`"off"` with an explicit cannot-confirm error; `"toggle"` still works (CMD-08) | VERIFIED | `tools.py:55-58` `UNCONFIRMABLE_POSITION_SYSTEMS`, refusal block at `tools.py:340-360` returns `unresolvable: True` with the documented message; toggle path untouched. |
| 11 | The six CMD-09 systems (magnetos, carb_heat, fuel_pump, starter, primer, lights) stay unregistered in the adapter | VERIFIED | `test_cmd09_systems_are_not_registered` passes; direct grep of `SimConnectManager.cs` confirms zero `Magneto`/`Starter`/`Primer`/`Light`/`CarbHeat`/`FuelPump` event registrations. |
| 12 | Semantic turn detection reaches the web path; browser gates on short RMS silence and asks the server; degrades to fixed-silence when unavailable (VARC-06) | VERIFIED, with warnings | `web/server.py` `/api/turn-probe` + `AppState.turn_detector`; `audio_processing.decode_webm_to_samples`; `app.js` rate-limited probe loop with `vad_silence_ms` fallback. `web/tests/test_turn_probe.py` (364 lines) passes. WR-01 (not a blocker): the endpoint's documented "never raises" contract is violated — `decode_webm_to_samples` is called outside any try/except and can raise `FileNotFoundError`/`ValueError`, both untested (every test patches the decode call). WR-03/WR-04 (not blockers): the 400ms browser fallback is the *default* configuration since the Smart Turn model isn't vendored, and a late probe verdict can truncate the next utterance (no utterance token). |

**Score:** 8/12 truths fully VERIFIED; 3 truths FAILED or PARTIAL in ways that block the phase goal (Gaps 1-3); 1 additional truth (#7) carries a non-blocking CLI visibility gap noted for the record.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `orchestrator/orchestrator/authority.py` | AuthorityLevel/Reason, AuthorityState, degraded_fallback, ≥140 lines, stdlib-only | VERIFIED | 338 lines; import list is `logging`, `time`, `collections.abc.Callable`, `enum.StrEnum`, `typing.Any` only. |
| `orchestrator/orchestrator/config.py` | 8 `authority_*` fields + validation | VERIFIED | Confirmed 8 fields + `_normalise_authority_level` + `_check_authority_timeout_budget` validator. |
| `orchestrator/tests/test_authority.py` | ≥170 lines | VERIFIED | 391 lines. |
| `.env.example` | `AUTHORITY_LEVEL=` | VERIFIED (not independently re-checked beyond grep in plan review; not contested by REVIEW.md) | |
| `adapters/msfs/Models/SimDataStructs.cs`, `adapters/msfs/SimConnectManager.cs` | New CommandMap entries incl. `PITOT_HEAT_TOGGLE` | VERIFIED | Confirmed via REVIEW.md file list + direct grep of fuel/crossfeed entries. |
| `adapters/msfs/SimConnectBridge.Tests/CommandMapTests.cs` | ≥60 lines | VERIFIED | 297 lines. |
| `orchestrator/tests/test_command_coverage.py` | ≥80 lines | VERIFIED | 316 lines; both guard tests pass. |
| `orchestrator/orchestrator/audio_processing.py` | `decode_webm_to_samples` | VERIFIED | Present; see Gap-adjacent WR-01 for its unguarded call site in `web/server.py`. |
| `web/server.py` | `/api/turn-probe`, `AppState.turn_detector`, `/api/status` turn+authority fields, `_on_tool_result` advisory/withheld branches | VERIFIED, with the CR-01 defect in the fall-through arm (see Gap 1) | |
| `web/tests/test_turn_probe.py` | ≥90 lines | VERIFIED | 364 lines. |
| `web/static/app.js` | rate-limited probe, authority rendering, `command_advisory`/`command_withheld` handling | VERIFIED | `renderAuthority`, `AUTHORITY_REASON_TEXT`, `case 'command_advisory'`/`case 'command_withheld'` all present. |
| `orchestrator/orchestrator/tools.py` | authority parameter + gate + CMD-08 refusal | VERIFIED, with CR-02/CR-03/CR-04 defects (Gaps 1-2) | |
| `orchestrator/orchestrator/sim_client.py` | floor, watchdog, reconnect clear, `command_path` health, `recent_dispatches` | VERIFIED | |
| `orchestrator/orchestrator/override_detector.py` | `COMMAND_WATCHED_FIELDS`, `OverrideDetector`, ≥160 lines | VERIFIED structurally, ORPHANED for `.events` (Gap 3) | 318 lines. |
| `orchestrator/orchestrator/command_verifier.py` | `has_verification_rule` + expanded rule coverage | VERIFIED | |
| `orchestrator/tests/test_override_detector.py` | ≥200 lines | VERIFIED | 484 lines. |
| `orchestrator/orchestrator/procedures.py` | routes every step through `set_aircraft_control`, withheld-aborts | VERIFIED | `set_aircraft_control` imported and called; structural guard `"send_command" not in PROCEDURES_SOURCE` present and passing. |
| `orchestrator/orchestrator/claude_client.py`, `orchestrator/orchestrator/main.py` | authority thread-through, corrected `_TOOL_TIMEOUTS`, CLI construction fails closed, `OverrideDetector` subscribed | VERIFIED | Confirmed construction propagates on failure (no try/except around `AuthorityState(...)` in `main.py`); detector subscribed at `main.py:165`. |
| `CLAUDE.md` | Architectural decision + directory listing | VERIFIED | Decision 26 present; `authority.py`, `override_detector.py`, `command_verifier.py` listed in the tree. Test-count line is stale (IN-01, info-level, not a must-have). |
| `web/static/index.html`, `web/static/style.css` | `status-authority`, `cmd-advisory` | VERIFIED | Both present with per-level/per-reason/per-outcome classes. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `config.py` | `authority.py` | `SUPPORTED_AUTHORITY_LEVELS` | WIRED | |
| `authority.py` | stdlib only | no orchestrator imports | WIRED (verified negative) | |
| `tools.py` | `authority.py` | `AuthorityLevel` comparison in gate | WIRED | |
| `tools.py` | `command_safety.py` | `SafetyResult.severity` drives assisted branch | WIRED | with WR-10 caveat on absent verdict |
| `sim_client.py` | `authority.py` | injected `AuthorityState`, consulted in `send_command` | WIRED | |
| `sim_client.py` | HealthMonitor | `command_path` subsystem | WIRED | |
| `override_detector.py` | `sim_client.py` | `recent_dispatches()` | WIRED | |
| `override_detector.py` | `authority.py` | `record_override`, `take_restore_event` | WIRED | |
| `override_detector.py` | `command_verifier.py` | `has_verification_rule` | WIRED | |
| `override_detector.py` | pilot-facing surface | `.events` queue → CLI/web consumer | **NOT WIRED** | Gap 3 |
| `procedures.py` | `tools.py` | `set_aircraft_control` per step | WIRED | |
| `main.py` | `authority.py` | shared `AuthorityState` construction | WIRED | |
| `claude_client.py` | `tools.py` | `authority=self._authority` at dispatch | WIRED | |
| `main.py` | `override_detector.py` | `sim_client.subscribe(detector.on_telemetry_update)` | WIRED | |
| `web/server.py` | `authority.py` | `AuthorityState` construction + `degraded_fallback` | WIRED | |
| `web/server.py` | `sim_client.py` HealthMonitor | summarised into `/api/status` | WIRED | |
| `web/server.py` | `app.js` | `command_advisory`/`command_withheld` frames | WIRED | |
| `app.js` | `/api/status` | `authority_level`/`authority_reason` read in `pollStatus` | WIRED | |
| `web/server.py` | `orchestrator.turn.__init__` | `create_turn_detector(settings)` at startup | WIRED | |
| `web/server.py` | `audio_processing.py` | `decode_webm_to_samples` in probe handler | WIRED, unguarded (WR-01) | |
| `app.js` | `web/server.py` | `fetch POST` of accumulated VAD blob to `/api/turn-probe` | WIRED | |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| `/api/status` `authority_level`/`authority_reason` | `state.authority.summary()` | `AuthorityState` built from `settings.authority_level` in `lifespan`, mutated live by `TelemetryClient`/`OverrideDetector` | Yes | FLOWING |
| `app.js` authority badge | `data.authority_level` / `data.authority_reason` from `pollStatus()` JSON | Same `/api/status` response above | Yes | FLOWING |
| Undo result `undo_description` | string built in `undo_last_command` | Constructed unconditionally regardless of whether `set_aircraft_control` actually transmitted | No — text asserts an action that may not have happened | HOLLOW (Gap 1) |
| Web `command_status` `success` field | `"error" not in result` (fall-through arm) | `TelemetryClient.send_command` ack, which can be `{"success": False}` with no `error` key | No — computed field disagrees with the underlying `result["success"]` | HOLLOW (Gap 1) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full orchestrator suite passes | `cd orchestrator && python3 -m pytest -q` | `1302 passed, 2 xfailed in 19.39s` | PASS |
| Full web suite passes | `cd web && python3 -m pytest -q` | `91 passed, 1 skipped in 9.20s` | PASS |
| Full telemetry-service suite passes | `cd telemetry-service && python3 -m pytest -q` | `38 passed in 0.40s` | PASS |
| CI-parity lint is clean | `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore SIM105,SIM117,F841,B008,B017,B007,UP041` | `All checks passed!` (exit 0) | PASS |
| CMD-07/CMD-09 adapter parity guards pass | `pytest orchestrator/tests/test_command_coverage.py -q` (included in full run above) | included in the 1302 | PASS |
| The only true end-to-end authority test passes when run directly, but is invisible to CI | `python3 -m pytest tests/integration/test_tool_chain.py -k TestAuthorityEndToEnd --override-ini="addopts="` | `5 passed, 20 deselected in 1.98s` | PASS (execution) / WARNING (CI blindness, WR-08 — `pytestmark = [pytest.mark.integration]`, and no CI job collects root `tests/`) |
| CR-03 undo-before-gate defect reproduces from source reading (pop_last at tools.py:796 precedes the `set_aircraft_control` call at tools.py:801) | manual code trace, corroborated by `test_undo_at_advisory_sends_nothing` (tools.py:1133-1156) never asserting `len(history)` | confirmed | FAIL (defect present, not covered) |
| CR-01 false-success fall-through reproduces from source reading (`web/server.py:1535`) | manual code trace, corroborated by absence of a `{"success": False}`-no-`error` case in `web/tests/test_chat_ws.py` | confirmed | FAIL (defect present, not covered) |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|-----------------|--------------|--------|----------|
| AUTH-01 | 02-01, 02-04, 02-05, 02-08 | Configurable level enforced at the single SimConnect-reaching point | SATISFIED | Truth #1 |
| AUTH-02 | 02-04, 02-09, 02-10 | Advisory describes and sends nothing | **BLOCKED** | Truth #2 / Gap 1 (undo path false confirmation) |
| AUTH-03 | 02-04 | Assisted executes clean, withholds warning | SATISFIED (WR-10 caveat, non-blocking) | Truth #3 |
| AUTH-04 | 02-04 | Full preserves current behavior | SATISFIED literally; undermined by Gap 2 | Truth #4 |
| AUTH-05 | 02-06 | Override detection identifies manual input | SATISFIED (WR-05 caveat, non-blocking) | Truth #5 |
| AUTH-06 | 02-06, 02-08, 02-09, 02-10 | Drop to advisory + inform the pilot | **BLOCKED** (inform half) | Truth #6 / Gap 3 |
| AUTH-07 | 02-05, 02-08 | Watchdog bounds dispatch→ack, stops issuing, says so | SATISFIED (stop); CLI "says so" gap noted as WARNING (WR-07), not scored as a blocker since AUTH-08's literal scope is `/api/status` + web UI | Truth #7 |
| AUTH-08 | 02-09, 02-10 | Level+reason surfaced in `/api/status` and web UI | SATISFIED | Truth #8 |
| CMD-07 | 02-02 | Adapter registers every enum-exposed resolvable event | SATISFIED (introduces Gap 2 as a side effect — see below) | Truth #9 |
| CMD-08 | 02-04 | carb_heat/fuel_pump refuse on/off, toggle works | SATISFIED | Truth #10 |
| CMD-09 | — (explicitly deferred, not Phase 2) | Six unreachable systems stay unregistered | SATISFIED (deferral honored) | Truth #11 |
| VARC-06 | 02-03 | Semantic turn detection on web path | SATISFIED (WR-01/03/04 caveats, non-blocking) | Truth #12 |

No orphaned requirement IDs found: every ID in ROADMAP.md's "AUTH-01 through AUTH-08, CMD-07, CMD-08, VARC-06 (CMD-09 deferred)" line is claimed by at least one plan's `requirements:` frontmatter, and CMD-09 is explicitly and correctly left unregistered rather than silently dropped.

**Note on REQUIREMENTS.md checkboxes:** All AUTH/CMD-07/CMD-08 boxes remain unchecked in `.planning/REQUIREMENTS.md`; VARC-06 is checked. Executors declined to check AUTH-01, AUTH-02, AUTH-05, AUTH-06, AUTH-07, AUTH-08 pending composition-root wiring or the announcement gap — this verification confirms that caution was warranted for AUTH-02 and AUTH-06 specifically (both remain genuinely incomplete), while AUTH-01, AUTH-05, AUTH-07 (stop half), AUTH-08 are now fully wired and safe to check once Gaps 1-3 close. CMD-07/CMD-08 are functionally complete but CMD-07 shipped a live safety gap (Gap 2) that should block sign-off until resolved.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `web/server.py` | 1535 | `success = "error" not in result` heuristic survives in the fall-through arm | 🛑 BLOCKER | False success rendered to pilot for a refused/NACKed command (Gap 1 / CR-01) |
| `orchestrator/orchestrator/tools.py` | 469-470 | Unconditional `safety_note` attach with no `result.get("success")` guard | 🛑 BLOCKER | "Critical system change executed" attached to a command that was refused or NACKed (Gap 1 / CR-02) |
| `orchestrator/orchestrator/tools.py` | 789-818 | `pop_last()` before the authority gate runs; unconditional "Reversed" description | 🛑 BLOCKER | Undo record destroyed and false reversal reported at advisory/withheld (Gap 1 / CR-03) |
| `orchestrator/orchestrator/tools.py` | 167-168, 55-58 | `parking_brake` unguarded blind toggle; missing from `UNCONFIRMABLE_POSITION_SYSTEMS` and `DEFAULT_RULES` | 🛑 BLOCKER | Reachable, unprotected brake-set/release in a `CRITICAL_COMMANDS` system (Gap 2 / CR-04) |
| `orchestrator/orchestrator/command_safety.py` | 123-179 | No rule for `FUEL_SELECTOR_OFF`/`CROSS_FEED_*`/`MIXTURE_SET`, newly reachable via CMD-07 | 🛑 BLOCKER | Unguarded in-flight fuel-starvation path at default `full` authority (Gap 2 / CR-05) |
| `orchestrator/orchestrator/override_detector.py` | 204-212 | `events` queue constructed, populated, never drained | ⚠️ WARNING | AUTH-06 pilot announcements are dead code (Gap 3 / WR-06) |
| `orchestrator/orchestrator/main.py` | 437-460 | `/status`/`/health` never call `AuthorityState.summary()` | ⚠️ WARNING | CLI operator cannot see authority level/reason at all (WR-07) |
| `web/server.py` | 829 | `decode_webm_to_samples` called with no surrounding try/except | ⚠️ WARNING | Contradicts the endpoint's documented "never raises" contract (WR-01) |
| `web/static/app.js` | 1541, 1676 | Fixed-silence fallback dropped from 1200ms to 400ms as the *default* (model not vendored) | ⚠️ WARNING | Conflicts with CLAUDE.md decision 23's stated rationale (WR-03) |
| `web/static/app.js` | 1696-1744 | No utterance token on the async turn-probe resolution | ⚠️ WARNING | A late probe for utterance A can truncate utterance B (WR-04) |
| `orchestrator/orchestrator/override_detector.py` | 229-242 | Reconnect suppression keys on adapter `SimState.connected`, not the client's own WS reconnect | ⚠️ WARNING | False override on the frame after an orchestrator↔service reconnect (WR-05) |
| `tests/integration/test_tool_chain.py` | 30 | `TestAuthorityEndToEnd` marked `pytest.mark.integration`; no CI job collects root `tests/` | ⚠️ WARNING | The phase's own described "only place the whole chain runs together" never runs in CI (WR-08) |
| `orchestrator/orchestrator/tools.py` | 365-372, 420 | `assisted` treats an absent safety verdict (`sim_state is None`) the same as a clean one | ⚠️ WARNING | Fail-open at the one level whose job is to be conservative (WR-10, part 1) |
| `CLAUDE.md` | 340 | Stale test counts (`55 web` vs. measured 92) | ℹ️ INFO | Documentation accuracy only |

No unresolved `TBD`/`FIXME`/`XXX` markers found in the files this phase modified.

### Human Verification Required

See frontmatter `human_verification:`. Not scored into `status` (gaps_found already applies from the blocker-level findings above), but should be exercised once Gaps 1-3 are closed:

1. **Authority badge live behavior** — trigger a pilot override and a watchdog latch, confirm the badge updates with a correct reason and that advisory/withheld render as distinct visual states from a green success.
2. **Turn-probe graceful degradation** — run without ffmpeg installed and confirm voice input keeps working via fixed-silence fallback with no visible error in the browser.

### Gaps Summary

Three findings block the phase goal:

1. **Command outcomes are not trustworthy under failure** (CR-01/CR-02/CR-03). The phase's stated purpose — eliminating the false-confirmation class of bug — is achieved for the two new outcome types it added (`advisory`, `withheld`) but not for the pre-existing success/failure path or for `undo_last_command`, which is itself a command path. This is a direct violation of the phase goal's "never ambiguous" clause: a pilot can be told a gear command executed when it did not, told a critical command executed when it was refused, and told an undo reversed a command when the command was neither reversed nor still available to reverse later.

2. **Authority is not uniformly bounded** (CR-04/CR-05). `parking_brake` is a reachable, `CRITICAL_COMMANDS`-tagged blind toggle with zero protection, and this phase's own CMD-07 work made `FUEL_SELECTOR_OFF`/`CROSS_FEED_*` executable with zero protection — while a functionally identical command (`MAGNETO_SET`) was deliberately withheld for exactly the risk these two now carry unmitigated. This directly contradicts the phase goal's "bounded" clause.

3. **AUTH-06's pilot-facing half is unimplemented** (WR-06). The mechanical drop-to-advisory works; the promised announcement does not exist on any path. Three separate executors (02-08, 02-09, 02-10) independently reached this same conclusion and left AUTH-06 unchecked in REQUIREMENTS.md for it — this verification confirms their judgment was correct.

None of these are addressed by a later phase in the roadmap (Phase 3: Automated Maneuvers, Phase 4: Vision Cockpit Reading, Voice Architecture VARC-02...05) — they are regressions and gaps internal to Phase 2's own scope and must be closed here.

All three gaps are narrow, mechanical fixes (reorder two lines, add two table entries, wire one queue drain) rather than design failures — the surrounding architecture (AuthorityState precedence, the two-layer gate/floor design, override detection, watchdog latching, web/CLI fail-safe construction) is sound and thoroughly tested (1,432 tests green, CI-parity lint clean).

---

_Verified: 2026-08-01T23:39:23Z_
_Verifier: Claude (gsd-verifier)_
