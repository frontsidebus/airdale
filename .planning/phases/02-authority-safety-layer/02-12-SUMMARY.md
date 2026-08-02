---
phase: 02-authority-safety-layer
plan: 12
subsystem: ui
tags: [fastapi, websocket, authority, command-safety, turn-detection, ffmpeg]

# Dependency graph
requires:
  - phase: 02-authority-safety-layer
    provides: "The advisory/withheld outcome arms in `_on_tool_result` (plan 02-09) and the `/api/turn-probe` endpoint (plan 02-03) that this plan corrects"
  - phase: 02-authority-safety-layer
    provides: "`TelemetryClient.send_command`'s documented ack shapes -- the NACK, the ack timeout and the authority-floor refusal (plans 02-05, 02-08)"
provides:
  - "Browser command outcomes classified on the adapter's reported `success`, not on the absence of an `error` key -- Gap 1 / CR-01 closed on the web half"
  - "A fail-closed default: a tool result carrying neither marker renders as failed"
  - "`/api/turn-probe` honours its documented never-raises contract with no ffmpeg on PATH (WR-01)"
affects: [03-automated-maneuvers, phase-02-verification, web-ui]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Command success is read from the result, never inferred from the absence of an error key -- the same expression `procedures.py` already uses and `tools.py::_was_transmitted` mirrors"
    - "Endpoints that document a never-raises contract guard each raising call individually, so a decode failure and a model failure stay distinguishable in the logs"

key-files:
  created: []
  modified:
    - web/server.py
    - web/tests/test_chat_ws.py
    - web/tests/test_turn_probe.py

key-decisions:
  - "Both halves of `bool(result.get('success', False)) and 'error' not in result` are required: the first is absent from blocked/unresolvable results, the second lets the adapter NACK through as a success"
  - "A raise and a `None` from `decode_webm_to_samples` share the single `decode_failed` tag -- they are the same event to the browser, and a second tag would only fragment the signal"
  - "`available=True` on a decode failure is deliberate: `available=False` would permanently stop the browser probing for the session over what may be one bad blob"
  - "The guard covers only the decode call, not the throttle, size checks or detector call -- the detector has its own guard returning `error`, and conflating them would make a model failure indistinguishable from a decode failure"

patterns-established:
  - "Fail-closed classification: an unrecognised tool-result shape is never evidence the aircraft moved"
  - "Regression assertion messages name the finding ID, the concrete dict shape and the operational consequence in one clause"

requirements-completed: [AUTH-02, AUTH-08, VARC-06]

# Metrics
duration: 18min
completed: 2026-08-02
---

# Phase 2 Plan 12: Browser Command-Outcome Truthfulness and the Turn-Probe Never-Raises Contract Summary

**A command the adapter refused now renders as failed in the browser instead of a green tick, an unrecognised result shape fails closed, and `/api/turn-probe` answers 200 with a not-ended verdict when ffmpeg is missing rather than throwing a 500 per probe.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-08-02T01:00:31Z
- **Completed:** 2026-08-02T01:18:34Z
- **Tasks:** 2 (both TDD, four commits)
- **Files modified:** 3

## Accomplishments

- Closed the browser half of VERIFICATION Gap 1 / CR-01. `_on_tool_result`'s fall-through
  computed `success = "error" not in result`, and `TelemetryClient.send_command` returns a
  negative adapter ack as `{"success": False, "message": "Unknown command"}` with **no**
  `error` key — a shape `sim_client.py` documents as routine, because
  `SimConnectManager.ExecuteCommand` answers any unmapped command name or `COMException`
  with it. The browser painted a green `GEAR DOWN` on a gear the adapter refused to move.
  It now reads `bool(result.get("success", False)) and "error" not in result`.
- Made the browser fail closed. A result carrying neither `success` nor `error` is no longer
  evidence the aircraft moved (threat T-02-12-02).
- Restored the `/api/turn-probe` never-raises contract (WR-01). `decode_webm_to_samples`
  spawns ffmpeg and was called outside any `try`; with no ffmpeg on `PATH` it raises
  `FileNotFoundError`, and `np.frombuffer` raises `ValueError` on a truncated buffer. A
  browser probing at roughly 7 Hz during speech collected a traceback and a 500 per probe
  instead of degrading to its fixed-silence fallback.
- Added six tests, including the exact `{"success": False}`-with-no-`error` case the suite
  had never had, and the two decode-raises cases every prior probe test masked by patching
  the decode call.

## Task Commits

Each task was committed atomically, RED then GREEN:

1. **Task 1: Compute command success from the result** — `67fce13` (test), `7a77aa4` (fix)
2. **Task 2: Turn-probe never-raises contract** — `91ef07a` (test), `1090706` (fix)

No refactor commits: neither change needed cleanup beyond the edit itself.

## Files Created/Modified

- `web/server.py` — `_on_tool_result` classifies on the reported `success`; the
  `decode_webm_to_samples` call in `turn_probe` is wrapped. Both docstrings extended with
  the concrete failure they now prevent, and `_on_tool_result`'s names
  `tools.py::_was_transmitted` as the expression it must stay identical to.
- `web/tests/test_chat_ws.py` — `_NACKED_RESULT`, `_TIMED_OUT_RESULT`, `_REFUSED_RESULT`,
  `_SHAPELESS_RESULT` literals plus `_CR01_REGRESSION`; four new tests.
- `web/tests/test_turn_probe.py` — `_WR01_REGRESSION`, a `_raising_decode` helper and two
  tests asserting HTTP 200 for `FileNotFoundError` and `ValueError`.

## Decisions Made

See `key-decisions` in the frontmatter. The load-bearing one: the success predicate needs
both halves. `result.get("success")` alone catches the NACK, the ack timeout and the
authority-floor refusal, but is absent entirely from a blocked or unresolvable result, which
carry only an `error`. `"error" not in result` alone lets the NACK through as a success —
that is the CR-01 defect verbatim.

Two of the four new chat tests (`_TIMED_OUT_RESULT`, `_REFUSED_RESULT`) passed at RED
because those shapes do carry an `error`. They were kept deliberately: they pin the
half of the predicate the fix could otherwise silently drop, and they are the shapes the
watchdog and the authority floor produce.

## Deviations from Plan

None — plan executed exactly as written.

The plan's Task 1 action asks for a docstring cross-reference to
`orchestrator/orchestrator/tools.py::_was_transmitted`, which is owned by sibling plan 02-11
in this wave. Only the reference was added, in `web/server.py`; no sibling-owned file was
opened or edited.

## Issues Encountered

`ruff format` reflowed two string literals in `web/tests/test_chat_ws.py` (a quote-style
change inside `_CR01_REGRESSION` and a joined line in `_REFUSED_RESULT`). Formatted and
folded into the GREEN commit; CI-parity `ruff format --check` is clean.

## Verification

| Check | Result |
|-------|--------|
| `cd web && python3 -m pytest -q` | 97 passed, 1 skipped (baseline 91 passed, 1 skipped — +6) |
| `cd orchestrator && python3 -m pytest -q` | 1302 passed, 2 xfailed (unchanged) |
| `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore ...` | All checks passed |
| `ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml` | 109 files already formatted |
| `grep -n 'success = "error" not in result' web/server.py` | no output (heuristic gone) |
| `grep -c "command_advisory\|command_withheld" web/server.py` | 2 — unchanged, the 02-09 arms were not disturbed |

## Known Stubs

None. Every value this plan writes to the wire is computed from a real result dict; no
placeholder, hardcoded empty, or unwired data path was introduced.

## User Setup Required

None — no external service configuration required. The turn-probe change is what makes an
environment *without* ffmpeg behave gracefully, so it removes a setup requirement rather
than adding one.

## Next Phase Readiness

- Gap 1 / CR-01 is closed on the web half. The orchestrator half (CR-02 `safety_note`,
  CR-03 `undo_last_command` pop-before-gate) is plan 02-11's scope in this same wave; the
  gap does not fully close until both land.
- WR-01 is closed. The `human_verification` item "run with no ffmpeg on PATH and speak
  through a full VAD cycle" is now expected to show no 500s — worth exercising live, since
  the tests prove the handler's contract but not the browser's fallback timing.
- Deliberately still open, with reasons recorded in the plan's `<notes>`: WR-09 (unbounded
  ffmpeg spawns on an unauthenticated `0.0.0.0` endpoint — needs a deployment decision),
  WR-03 (400 ms fixed-silence fallback is the default because the Smart Turn model is not
  vendored), WR-04 (no utterance token on the async probe), IN-03 (`undo_last_command` and
  `execute_procedure` emit no browser command frame at all), IN-05 (probe throttle keyed by IP).

## Threat Flags

None. No new network endpoint, auth path, file-access pattern or schema change at a trust
boundary was introduced; both edits narrow existing surface.

## Self-Check: PASSED

All four claimed files exist on disk (`web/server.py`, `web/tests/test_chat_ws.py`,
`web/tests/test_turn_probe.py`, this summary) and all five claimed commits are present in
`git log aab726f..HEAD` (`67fce13`, `7a77aa4`, `91ef07a`, `1090706`, `344e98f`). No file
deletions in any commit; working tree clean.

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-08-02*
