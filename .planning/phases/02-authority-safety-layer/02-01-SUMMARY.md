---
phase: 02-authority-safety-layer
plan: 01
subsystem: safety
tags: [authority, state-machine, pydantic-settings, watchdog, strenum, fail-safe]

# Dependency graph
requires:
  - phase: 01-discrete-command-control
    provides: bidirectional command protocol and the set_aircraft_control tool that authority now has to gate
provides:
  - AuthorityLevel / AuthorityReason StrEnums (3 levels, 4 reasons incl. DEGRADED)
  - SUPPORTED_AUTHORITY_LEVELS + parse_authority_level (fails loudly, no fallback)
  - AuthorityState with degraded > watchdog > override-cooldown > config precedence
  - AuthorityState.degraded_fallback() for composition roots whose construction failed
  - Eight authority_* Settings fields with startup validation of the timeout budget
  - .env.example AUTHORITY & SAFETY section, plus the previously missing TURN DETECTION section
  - docs/CONFIGURATION.md reference for all 12 keys and the four authority reasons
affects: [02-02, 02-03, 02-04, 02-05, 02-06, 02-07, 02-08, 02-09, 02-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Clock injection (Callable[[], float]) for time-dependent state -- no fake-time library exists in any extra"
    - "Fail-safe constructor: degraded_fallback() builds from enum literals only, so it is safe inside the except block handling the failure it replaces"
    - "Level and reason travel together, so 'restricted' is never unattributable"

key-files:
  created:
    - orchestrator/orchestrator/authority.py
    - orchestrator/tests/test_authority.py
  modified:
    - orchestrator/orchestrator/config.py
    - orchestrator/tests/test_config.py
    - .env.example
    - docs/CONFIGURATION.md

key-decisions:
  - "DEGRADED is a fourth AuthorityReason, not a fourth AuthorityLevel -- a reason threads only through the display, a level would thread through gate, floor, status endpoint, UI and every test"
  - "Degraded is terminal: no override, watchdog clear, cooldown lapse or other method lifts it, because the code that would decide otherwise is the code that just failed"
  - "authority_level defaults to 'full' (D-08a) so upgrading changes no behaviour; restriction is opt-in"
  - "record_command_success() deliberately does not clear a watchdog latch (D-18); clear_watchdog() is the only clear path"
  - "The B3 timeout arithmetic is a startup invariant enforced by a model_validator, not a comment"
  - "Authority settings placed after the STT/whisper fields rather than splitting the turn-detection block from its neighbours"

patterns-established:
  - "Injected monotonic clock: AuthorityState(clock=...) makes a 120 s rolling cooldown testable in microseconds"
  - "Structural no-package-imports guard: test reads authority.py source and rejects `from .`/`from orchestrator` so the module stays importable at the base of the dependency graph"
  - "Config selector validation routes through the owning module's parse_* function, so the supported list has exactly one definition"

requirements-completed: [AUTH-01, AUTH-06, AUTH-07]

# Metrics
duration: 11min
completed: 2026-08-01
---

# Phase 02 Plan 01: Authority State Machine & Settings Summary

**A single clock-injected `AuthorityState` that carries both the effective authority level and the reason for it -- config, pilot override, command-path watchdog, or a degraded subsystem -- seeded by eight validated `authority_*` settings whose every failure mode resolves toward advisory.**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-08-01T03:02:00Z
- **Completed:** 2026-08-01T03:13:00Z
- **Tasks:** 2
- **Files modified:** 6 (2 created, 4 modified)

## Accomplishments

- `orchestrator/orchestrator/authority.py` implements the `<interfaces>` contract exactly, so plans 02-04 through 02-10 can be written against it without reinterpretation.
- The module imports nothing from the `orchestrator` package (stdlib only), so `sim_client.py` -- the base of the dependency graph -- can consume it without a cycle. A structural test pins that property.
- Precedence is ordered so no less-restrictive state can mask a more-restrictive one: degraded > watchdog latch > override cooldown > configured level.
- `degraded_fallback()` gives every composition root a constructible safe value, closing the fail-open-on-state-load-error class this phase is named for: a construction failure now *reduces* authority instead of leaving callers with no authority object (which reads as FULL to every consumer).
- Eight `authority_*` settings with rationale-carrying descriptions; an unknown `authority_level` raises a pydantic `ValidationError` at startup listing the supported values, with no silent fallback branch.
- The B3 arithmetic (`tool_timeout > command_timeout + verify_timeout`) is enforced by a `model_validator`, so the configuration that makes the watchdog blind cannot start.
- `.env.example` gained the authority block **and** the turn-detection section that had been undocumented there since VARC-01 shipped.
- 58 new tests (42 authority, 16 config). Orchestrator suite: 1147 passed, 2 xfailed. Web suite unaffected: 38 passed, 1 skipped.

## Task Commits

1. **Task 1: Create the authority state machine module** - `4017086` (feat)
2. **Task 2: Authority settings fields, .env.example section, configuration docs** - `f721222` (feat)

## Files Created/Modified

- `orchestrator/orchestrator/authority.py` (new) - `AuthorityLevel` (3 members), `AuthorityReason` (4, incl. `DEGRADED`), `SUPPORTED_AUTHORITY_LEVELS`, `parse_authority_level`, `AuthorityState` with rolling override cooldown, N-consecutive-timeout watchdog latch, one-shot `take_restore_event()`, `summary()`, and `degraded_fallback()`.
- `orchestrator/tests/test_authority.py` (new) - 42 tests over a `_FakeClock`: precedence, rolling extension, auto-restore, latch semantics, degraded terminality, enum member counts, `parse_authority_level` failure message, `summary()` key set, and the no-package-imports structural guard.
- `orchestrator/orchestrator/config.py` - eight `authority_*` fields, a `field_validator` routing `authority_level` through `parse_authority_level`, and a second `model_validator` enforcing the timeout budget.
- `orchestrator/tests/test_config.py` - `_settings()` helper (matching `test_turn_detection.py`) plus 16 tests: defaults, case-insensitive normalisation, unknown-level rejection, bound violations, and the cross-field timeout invariant.
- `.env.example` - `AUTHORITY & SAFETY` section documenting all eight keys with the `assisted` coverage caveat, and a new `TURN DETECTION` section for `TURN_DETECTOR`, `TURN_THRESHOLD`, `TURN_PROBE_SILENCE_MS`, `VAD_SILENCE_MS`.
- `docs/CONFIGURATION.md` - `Authority & Safety` reference (table, level semantics, the `assisted` gap, the four reasons and what each means to the pilot, the timeout budget) and a `Turn Detection` reference.

## Decisions Made

- **Settings block placement.** The plan said to place the authority block after the turn-detection block. Verbatim that would have split the STT section, because `whisper_model` / `whisper_url` trail the turn fields. The block went after `whisper_url` and before the TTS section instead -- still after turn detection, without orphaning the STT fields.
- **`.env.example` section style.** The plan and 02-PATTERNS.md describe a `# --- Section ---` convention; the file actually uses `# =====` banner headers with `# ---` sub-headers. Followed the file, so the new sections read like the eleven that precede them.
- **Both new sections use uncommented `KEY=value` lines.** The defaults are the documented values, so a copied `.env` is explicit about who may command the aircraft rather than relying on an invisible default.
- **`take_restore_event()` stays pending under a watchdog latch** rather than being consumed. The restore announcement then matches what actually happened -- authority genuinely restored -- instead of firing while MERLIN is still latched to advisory.
- **`cooldown_remaining_s` is a private helper, not a public property.** The `<interfaces>` contract lists seven properties; downstream plans read the value through `summary()`, so adding an eighth would have widened the contract for no consumer.
- **`SUPPORTED_AUTHORITY_LEVELS` referenced in the `authority_level` description** (f-string) as well as the validator, satisfying the plan's config→authority key link and keeping the supported list single-sourced.

## Deviations from Plan

None requiring a deviation rule. No bugs, missing critical functionality, or blocking issues were encountered; nothing was auto-fixed. The two placement/style judgments above are recorded under Decisions Made rather than as deviations because they concern where documented content lives, not what it says.

**Total deviations:** 0
**Impact on plan:** None. Every acceptance criterion in both tasks was verified as written.

## Issues Encountered

- **Ruff SIM300 (Yoda condition)** on the enum-sync assertion in `test_authority.py`. Caught by the CI-parity ruff run before commit and fixed by flipping the comparison. Worth noting that `ruff check .` from inside `orchestrator/` would still have caught this one, but the CI-parity command from the repo root is what was used, per CLAUDE.md.
- **Plan `<verify>` blocks `cd` to the main repo path** (`/mnt/c/Users/bould/source/airdale`). Run from the worktree root instead; the commands are otherwise unchanged.

## Verification

- `python3 -m pytest orchestrator/tests/test_authority.py -q` -- 42 passed
- `python3 -m pytest orchestrator/tests/test_config.py -q` -- 35 passed (19 pre-existing + 16 new)
- `python3 -m pytest orchestrator/tests/ -q` -- 1147 passed, 2 xfailed (baseline 1089; count increased, none decreased)
- `python3 -m pytest tests/ -q` in `web/` -- 38 passed, 1 skipped (unaffected by the `Settings` change)
- `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore SIM105,SIM117,F841,B008,B017,B007,UP041` -- All checks passed
- `ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml` -- 104 files already formatted
- `grep -nE "^from \.|^from orchestrator|^import orchestrator" orchestrator/orchestrator/authority.py` -- no output
- `SUPPORTED_AUTHORITY_LEVELS == ('advisory', 'assisted', 'full')`; `len(AuthorityLevel), len(AuthorityReason) == 3 4`
- `Settings(...)` defaults print `full 5.0 3.0 12.0`; `authority_level='banana'`, `authority_tool_timeout_s=5.0`, `authority_watchdog_max_timeouts=0` and `authority_override_cooldown_s=0` all raise `ValidationError`
- `grep -v '^#' .env.example | grep -c "AUTHORITY_"` -- 8; turn-detection keys -- 4
- `grep -c "authority_" orchestrator/orchestrator/config.py` -- 19

## Known Stubs

None. Every symbol in the `<interfaces>` contract is implemented and exercised by a test. The consumers (`tools.py` gate, `sim_client.py` floor, override detector, status endpoint, UI badge) are deliberately out of scope for this plan and land in 02-04 through 02-10.

## Threat Flags

None. This plan adds no network endpoint, auth path, file access or schema at a trust boundary. The two boundaries it does touch -- operator config → `Settings`, and `AuthorityState` → every command path -- are the ones the plan's threat register already covers, and all seven mitigate dispositions are implemented and tested (T-02-01-01 unknown-level rejection, -02 precedence order, -03 latch clear path, -04 no-package-imports guard, -05 reason attribution, -06 `degraded_fallback`, -07 `DEGRADED` distinct from a deliberate `advisory`).

## Notes for the Orchestrator

- STATE.md and ROADMAP.md were **not** modified (worktree mode; the orchestrator owns those writes post-wave).
- REQUIREMENTS.md was **not** modified either. AUTH-01, AUTH-06 and AUTH-07 are only partially delivered here -- this plan builds the state they all depend on, but the gate (02-04), the override detector (02-05) and the watchdog wiring (02-05) are what make them observable in flight. Marking them complete now would over-claim, and every plan in the wave touching the same file would conflict. Recommend deferring the mark-complete until the wave merges.

## Next Phase Readiness

Ready. Downstream plans can now:

- `from orchestrator.authority import AuthorityLevel, AuthorityReason, AuthorityState` anywhere, including `sim_client.py`.
- Construct the runtime state as `AuthorityState(parse_authority_level(settings.authority_level), override_cooldown_s=settings.authority_override_cooldown_s, watchdog_max_timeouts=settings.authority_watchdog_max_timeouts)`, and fall back to `AuthorityState.degraded_fallback(str(exc))` when that raises (02-09's web `lifespan`; 02-08's CLI fails closed by letting it propagate).
- Read `settings.authority_command_timeout_s` / `authority_verify_timeout_s` / `authority_tool_timeout_s` in place of the hardcoded `5.0` at `sim_client.py:364`, `3.0` at `command_verifier.py:184`, and `5.0` in `claude_client._TOOL_TIMEOUTS`.
- Render the badge from `state.summary()`, whose seven keys are fixed and tested.

One caution for 02-09/02-10: `AuthorityReason` now has **four** members. Any branch over it -- badge colour, status text, TTS phrasing -- needs a `degraded` arm, or a degraded start will render as a deliberate `advisory` configuration, which is exactly threat T-02-01-07.

## Self-Check: PASSED

- Files claimed created/modified: all 6 present on disk.
- Commits claimed: `4017086` and `f721222` both present in `git log`.

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-08-01*
