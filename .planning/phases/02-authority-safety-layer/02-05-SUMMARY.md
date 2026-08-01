---
phase: 02-authority-safety-layer
plan: 05
subsystem: safety
tags: [authority, floor, watchdog, circuit-breaker, health, toctou, provenance]

# Dependency graph
requires:
  - phase: 02-authority-safety-layer
    plan: 01
    provides: AuthorityState with level/reason, record_command_timeout, record_command_success, clear_watchdog
provides:
  - Level-only structural authority floor in TelemetryClient.send_command (D-05)
  - Consecutive-ack-timeout watchdog counter observing the real ack future (AUTH-07, D-15/D-16)
  - command_path HealthMonitor subsystem, registered at construction (D-17)
  - _on_connection_established() clearing the latch from both CONNECTED transitions (D-18)
  - TelemetryClient.recent_dispatches() -- bounded single-monotonic-clock dispatch ledger
  - TelemetryClient(authority=, health=, command_timeout=) keywords for the composition roots
affects: [02-06, 02-08, 02-09, 02-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two independent reads of the same authority level (gate, then floor) as the TOCTOU close -- not one cached verdict"
    - "collections.deque(maxlen=CLASS_CONSTANT) following the RECONNECT_* class-tunable convention"
    - "Single connection-established hook so a future third connect path cannot miss the watchdog clear"
    - "Guarded optional collaborators (authority/health None) make a feature inert, never permissive"

key-files:
  created: []
  modified:
    - orchestrator/orchestrator/sim_client.py
    - orchestrator/tests/test_sim_client.py

key-decisions:
  - "The three new __init__ parameters are keyword-only; the plan said 'keyword parameters', and a bare `*` also blocks TelemetryClient(url, True, health) silently binding health to authority"
  - "Latch/health bookkeeping factored into _record_command_failure() so the ack-timeout and send-exception outcome points cannot drift apart"
  - "The success path resets the counter after wait_for returns, regardless of result['success'] -- an ack is proof of life even when it carries a rejection"
  - "recent_dispatches() returns a tuple snapshot, so a consumer iterating it cannot be mutated out from under by a concurrent dispatch"

patterns-established:
  - "Floor placed after the not-connected guard and before command_id generation, so a refusal allocates no future and leaves _pending_commands untouched"
  - "Ledger appended only after `await self._ws.send(msg)` returns -- provenance means reached-the-wire, not attempted"

requirements-completed: []

# Metrics
duration: 15min
completed: 2026-08-01
---

# Phase 02 Plan 05: Authority Floor & Command-Path Watchdog Summary

**A level-only refusal at the last point before a command leaves the process, backed by a consecutive-ack-timeout circuit breaker that observes the real ack future, cannot deadlock, cannot re-latch through its own refusals, and cannot lift a degraded authority state.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 3
- **Files modified:** 2 (0 created, 2 modified)
- **Tests added:** 33 (48 → 81 in `test_sim_client.py`)

## Accomplishments

- `send_command` now refuses everything at `advisory` **before** allocating a command id, a future, or touching the socket. The refusal shape matches the plan's `<interfaces>` block exactly (`refused`, `authority_level`, `authority_reason`), so 02-09 can render it without reinterpretation.
- The floor re-reads `self._authority.level` at the instant of dispatch. `send_command` takes no `level` parameter and caches nothing between calls — verified by an explicit test — which structurally closes T-02-05-08 rather than arguing it away from asyncio scheduling.
- Ordering is enforced and pinned: the floor returns before any counter mutation, so a latched watchdog cannot re-arm through the very refusals it causes. A test asserts `consecutive_timeouts` is unchanged across five consecutive refusals.
- The watchdog counter is incremented **inside** `send_command` at the ack future and at a raising send — never inferred from a return dict — which is what RESEARCH B3 proved was necessary, since the tool layer's own timeout starts first and pre-empts this one.
- An ack that arrives carrying `success: false` resets the counter. This is not a nicety: 31 unregistered events currently produce exactly that ack shape, and counting them would latch the watchdog on a healthy system.
- The not-connected early return deliberately does not count, with a comment saying why (already visible through `ConnectionState` and the heartbeat; counting would double-report).
- `_on_connection_established()` is called from both `connect()` and `_reconnect()` — the only two places that set `CONNECTED` — so the CLI and web paths cannot diverge. A degraded state is not lifted by it, because `clear_watchdog()` returns False when degraded.
- `command_path` is registered on `HealthMonitor` at construction, so it appears in `summary()` from process start rather than materialising after the first command. It flips unhealthy on latch and healthy on clear.
- `recent_dispatches()` gives plan 02-06 a bounded, `time.monotonic()`-stamped record of every command that actually reached the wire — one clock, matching `CommandHistory.record`, with no cross-clock correlation against the adapter's ISO timestamps.
- All 48 pre-existing `test_sim_client.py` tests pass **unmodified**, and the ~40 `TelemetryClient(url)` constructions across the suite are untouched.

## Task Commits

1. **Task 1: Authority floor and dispatch ledger in `send_command`** — `3100898` (feat)
2. **Task 2: Watchdog counter, `command_path` health, reconnect clear** — `b48761a` (feat)
3. **Task 3: Floor, watchdog and ordering tests** — `c3d4a90` (test)

## Files Created/Modified

- `orchestrator/orchestrator/sim_client.py` — `from .authority import AuthorityLevel, AuthorityState`; `DISPATCH_LEDGER_SIZE = 64` class tunable; `__init__` gains keyword-only `authority` / `health` / `command_timeout` plus the no-authority WARNING and `command_path` registration; new `_on_connection_established()` and `_record_command_failure()` helpers; `recent_dispatches()`; `send_command` gains the floor, `timeout: float | None`, the ledger append after a successful send, and the three watchdog outcome hooks.
- `orchestrator/tests/test_sim_client.py` — five new classes (`TestAuthorityFloor`, `TestCommandWatchdog`, `TestWatchdogReconnectClear`, `TestCommandPathHealth`, `TestDispatchLedger`, plus `TestCommandTimeoutResolution`), a `_connected_client()` builder and an `_ack_pending()` helper that resolves the in-flight future the way an adapter ack would.

## Decisions Made

- **Keyword-only new parameters.** The plan called them "keyword parameters"; a bare `*` was added so `TelemetryClient(url, True, some_health)` cannot silently bind a `HealthMonitor` to `authority`. No existing call site passes more than two positional arguments, so nothing broke.
- **`_record_command_failure()` helper.** The ack-timeout and send-exception outcome points share identical latch-detection, ERROR logging and health bookkeeping. Factoring them mirrors the plan's own reasoning for `_on_connection_established` — two copies would eventually drift.
- **Health detail wording.** The plan suggested `"<n> consecutive ack timeouts"`; the helper emits `"<detail>; <n> consecutive"` so the send-exception case can carry the exception text (which the plan also asked for) through the same code path. Both carry the count.
- **Ledger tests use a client with no authority.** Sending 74 commands through an authority-bearing client would latch the watchdog on the third and then be refused by the floor, so nothing further would reach the ledger. The bound is a property of the deque, not of authority, so the inert client is the honest fixture.
- **Reconnect clear tested through both real paths.** One test drives `connect()` and another drives `_reconnect()` under a patched `websockets.connect`, rather than only calling the helper directly — the plan's concern was precisely that the two paths could diverge.

## Deviations from Plan

None requiring a deviation rule. No bugs, missing critical functionality, or blocking issues were encountered; nothing was auto-fixed. The judgments above are recorded under Decisions Made because they concern how the specified behaviour is expressed, not what it does.

**Total deviations:** 0
**Impact on plan:** None. Every acceptance criterion in all three tasks was verified as written.

## Issues Encountered

- **The orchestrator venv is not in the worktree.** `orchestrator/.venv/` is git-ignored and lives only in the main checkout, so `cd orchestrator && .venv/bin/python3 -m pytest` fails here. Tests were run with the system `python3` (which already has pytest 9.0.2 and an editable install pointing at the *main* repo) plus `PYTHONPATH=<worktree>/orchestrator`, which takes precedence over the `.pth` file and makes imports resolve to the worktree source. Verified explicitly before relying on it.
- **Plan `<verify>` blocks `cd` to the main repo path** (`/mnt/c/Users/bould/source/airdale`), same as plan 02-01 noted. Run from the worktree root instead; the commands are otherwise unchanged.
- **`ruff format` reformatted the new test file** on first pass (one call-site wrapping). Applied and re-verified; the CI-parity check is clean.
- **Integration tests under `tests/integration/` have pre-existing failures.** They are deselected by default (`addopts = -m "not integration"` in both `orchestrator/pyproject.toml` and `tests/pytest.ini`), so the plan's stated command exits 0. Forced with `-m integration` they report 20 failed / 16 passed / 31 errors — but running the identical command against the **base** `sim_client.py` (extracted with `git show 0dace39:...` into a scratch tree) produces exactly the same 20/16/31. The failures are stale v1-era expectations (`SimState.aircraft_title`, `get_state()` raising `ConnectionError`) and unavailable services (ChromaDB, Whisper). Not caused by this plan, and out of scope per the scope boundary.

## Verification

- `pytest tests/test_sim_client.py -q` — **81 passed** (baseline 48; +33, against a required floor of +14)
- `pytest tests/ -q` (orchestrator) — **1194 passed, 2 xfailed** (baseline 1161 passed / 2 xfailed; 1161 + 33 = 1194 exactly, no regressions)
- `pytest tests/ -q` (web) — 55 passed, 1 skipped — unchanged from baseline
- `pytest tests/ -q` (telemetry-service) — 38 passed — unchanged from baseline
- `pytest tests/integration/ -q` — exits 0 (67 deselected by default config)
- `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore SIM105,SIM117,F841,B008,B017,B007,UP041` — All checks passed
- `ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml` — 107 files already formatted
- `inspect.signature(TelemetryClient.__init__).parameters` → includes `authority`, `health`, `command_timeout`
- `hasattr(TelemetryClient, 'recent_dispatches'), TelemetryClient.DISPATCH_LEDGER_SIZE` → `True 64`
- `'level' not in inspect.signature(TelemetryClient.send_command).parameters` → `True`
- `grep -c "command_path" sim_client.py` → 7 (required ≥ 4)
- `grep -c "record_command_timeout\|record_command_success\|clear_watchdog" sim_client.py` → 4 (required ≥ 4)
- `grep -n "clear_watchdog\|_on_connection_established" sim_client.py` → clear reachable from `connect()` (:369) and `_reconnect()` (:642)
- `grep -c "15\.0\|15 seconds" tests/test_sim_client.py` → 0, unchanged (no wall-clock latch bound asserted)

## Known Stubs

None. Every contract in the plan's `<interfaces>` block is implemented and exercised by a test. The consumers are deliberately out of scope: 02-06 reads `recent_dispatches()`, 02-08 and 02-09 pass the new constructor keywords, and 02-09 renders `command_path` health in `/api/status`. Until those land, a `TelemetryClient` built by `main.py` or the web `lifespan` still has `authority=None` and logs the construction WARNING by design — that is the wiring signal this plan installed, not an unfinished edge.

## Threat Flags

None. This plan adds no network endpoint, auth path, file access or schema at a trust boundary. All eight `mitigate` dispositions in the plan's register are implemented and tested:

| Threat ID | Where it is closed |
|-----------|--------------------|
| T-02-05-01 | Level-only floor refuses at advisory regardless of caller; construction-time WARNING makes an inert client visible |
| T-02-05-02 | Counter incremented at the ack future inside `send_command`, never from a return dict |
| T-02-05-03 | `_on_connection_established()` clears the latch from both `CONNECTED` transitions |
| T-02-05-04 | Floor returns before any counter mutation; pinned by `test_floor_refusal_does_not_touch_the_watchdog_counter` |
| T-02-05-05 | Ack resets the counter regardless of its `success` field |
| T-02-05-06 | `command_path` registered at construction and updated on every outcome |
| T-02-05-07 | `deque(maxlen=DISPATCH_LEDGER_SIZE)`; event names and monotonic timestamps only — no values, no state snapshots |
| T-02-05-08 | Fresh re-read at dispatch, no `level` parameter, no cache; pinned by `test_floor_reads_the_level_fresh_at_dispatch` |

## Notes for the Orchestrator

- STATE.md, ROADMAP.md and REQUIREMENTS.md were **not** modified (worktree mode; the orchestrator owns those writes post-wave).
- **AUTH-01 and AUTH-07 should not be marked complete on this plan alone.** This plan delivers the enforcement floor and the watchdog mechanism, but neither is reachable in a running process until a composition root passes `authority=` — that is 02-08 (CLI) and 02-09 (web). Marking them now would over-claim, and every wave plan touching REQUIREMENTS.md would conflict. Recommend deferring until the wave merges.
- `verify.key-links` should now find the `command_path` HealthMonitor subsystem that was reported absent pre-merge.

## Next Phase Readiness

Ready. Downstream plans can now:

- **02-06:** call `sim_client.recent_dispatches()` for `(event_name, monotonic_ts)` pairs, oldest first, bounded at 64 — the same clock `CommandHistory.record` uses, so override detection needs no cross-clock correlation.
- **02-08 / 02-09:** construct `TelemetryClient(url, auto_reconnect=True, authority=..., health=..., command_timeout=settings.authority_command_timeout_s)`. The parameters are **keyword-only**. Passing `authority` is what activates the floor and silences the construction WARNING.
- **02-09:** read `health.summary()["command_path"]` to render "advisory (command path down)", and branch on the `authority_reason` field of a refusal — remembering it has **four** possible values, `degraded` included.

One caution for 02-08: the floor is inert when `authority is None`, and that is exactly what the CLI does today. Until `main.py` is wired, the structural protection this plan installed is not yet active in the CLI process — the WARNING at construction is the marker for that gap.

## Self-Check: PASSED

- Files claimed modified: `orchestrator/orchestrator/sim_client.py` and `orchestrator/tests/test_sim_client.py` — both present on disk with the described changes.
- Commits claimed: `3100898`, `b48761a`, `c3d4a90` — all three present in `git log`.
- No files created, none deleted (`git diff --diff-filter=D` empty for all three commits).

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-08-01*
