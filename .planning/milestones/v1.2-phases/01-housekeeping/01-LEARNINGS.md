---
phase: 01
phase_name: "Housekeeping"
project: "MERLIN — Airdale"
generated: "2026-07-29"
counts:
  decisions: 7
  lessons: 6
  patterns: 5
  surprises: 3
missing_artifacts:
  - "01-UAT.md"
---

# Phase 01 Learnings: Housekeeping

## Decisions

### Scope deprecation removal to config fields only, not all SimConnect references
Removed `simconnect_ws_host`, `simconnect_ws_port`, `simconnect_bridge_url`, and the `SimConnectClient = TelemetryClient` alias. Left the health monitor subsystem name, test fixture names, and adapter documentation intact.

**Rationale:** Those surviving references point at the real SimConnect adapter component, not the dead direct-bridge config. A blanket `grep simconnect | delete` sweep would have broken working code.
**Source:** 01-01-SUMMARY.md

### Preserve the `_build_derived` validator while gutting its legacy branch
Deleted only the `if not self.simconnect_bridge_url:` block from the `@model_validator(mode="after")` method, keeping the `telemetry_service_url` construction.

**Rationale:** The validator still has a live job — deriving the telemetry service WebSocket URL from host and port. Removing the whole method to remove one branch would have taken working behavior with it.
**Source:** 01-01-PLAN.md

### Pin Docker images to full patch versions, not minor-range tags
`chromadb/chroma:1.5.5`, `fedirz/faster-whisper-server:0.8.3-cpu`, and the commented GPU variant `0.8.3-cuda`.

**Rationale:** The plan preferred minor-range tags (`1.5`, `0.8-cpu`) but made patch versions the documented fallback. Docker was unavailable in the WSL2 environment, so `docker manifest inspect` could not confirm the minor tags exist on Docker Hub. Patch versions are more precise and equally valid for reproducible builds.
**Source:** 01-02-SUMMARY.md

### Standardize on `python:3.12-slim` across all Dockerfiles
Moved `telemetry-service/Dockerfile` from `python:3.11-slim` to `python:3.12-slim` to match the orchestrator Dockerfile, which was already on 3.12.

**Rationale:** The orchestrator was the de facto standard; converging on it was a one-line change versus downgrading the orchestrator.
**Source:** 01-02-PLAN.md

### Use a dedicated `_consumer_lock` separate from the existing `_lock`
`AdapterManager` now holds two locks: `_lock` for adapter state, `_consumer_lock` for the consumer list.

**Rationale:** A single shared lock would let adapter operations and consumer operations block each other, creating deadlock potential between concurrent adapter registration and consumer connect/disconnect.
**Source:** 01-03-SUMMARY.md

### Dead-consumer cleanup mutates the list directly instead of calling `remove_consumer()`
Inside `_broadcast_to_consumers`, the cleanup loop calls `self._consumers.remove(consumer)` rather than the public `self.remove_consumer(consumer)`.

**Rationale:** `asyncio.Lock` is not reentrant. The broadcast method already holds `_consumer_lock`, so calling `remove_consumer()` — which acquires the same lock — would deadlock.
**Source:** 01-03-SUMMARY.md

### Delete the empty `WebSocketServerTests.cs` rather than populate it
Removed the file via `git rm`; it contained only a 3-line comment noting it had been replaced by `TelemetryServiceClientTests.cs`.

**Rationale:** The coverage already existed elsewhere. An empty file that looks like a test file misrepresents suite coverage.
**Source:** 01-03-PLAN.md

---

## Lessons

### Changing a method's sync/async signature silently breaks its test callers
Promoting `add_consumer` to `async def` left the existing tests calling it synchronously. The result was a "coroutine never awaited" warning and a test failure, not a clean error at the call site.

**Context:** Found during Task 1 of plan 03 and auto-fixed by adding `await` to both `add_consumer` calls in `test_adapter_manager.py`. The plan had specified updating the two `service.py` callers but did not anticipate the test callers.
**Source:** 01-03-SUMMARY.md

### `asyncio.Lock` is not reentrant — nested acquisition from the same task deadlocks
Wrapping a whole method body in `async with self._lock:` means every helper it calls must not re-acquire that lock.

**Context:** Surfaced when wrapping `_broadcast_to_consumers` in `_consumer_lock`, since its dead-consumer cleanup path previously delegated to `remove_consumer()`.
**Source:** 01-03-PLAN.md, 01-03-SUMMARY.md

### Touching a file makes its pre-existing lint violations yours
`TelemetryEnvelope` in `service.py` and `ConsumerConnection` in `test_adapter_manager.py` were already-unused imports, but ruff only became a gate once those files were modified in this phase.

**Context:** Two extra edits folded into the Task 1 commit as auto-fixes. Budget for pre-existing lint debt in any file a plan touches.
**Source:** 01-03-SUMMARY.md

### Docker is not available in the WSL2 native dev environment
Neither `docker manifest inspect` (to confirm image tags exist) nor `docker compose config` (to validate the edited YAML) could be run.

**Context:** Affected plan 02 twice — it forced the patch-version fallback and left the compose YAML validated only by inspection. Accepted as low risk because the edits were pure tag string substitutions with no structural change.
**Source:** 01-02-SUMMARY.md, 01-VERIFICATION.md

### Removing a pydantic field requires finding explicit keyword arguments, not just field references
`Settings` has `extra = "ignore"`, which handles stray env vars — but an explicit `Settings(simconnect_bridge_url=...)` keyword argument raises `TypeError` once the field is gone.

**Context:** `tests/integration/test_orchestrator_e2e.py` line 40 had to be edited for exactly this reason. `extra = "ignore"` gives false confidence that field removal is backward-compatible.
**Source:** 01-01-PLAN.md

### Untracked files from a later phase contaminate full-suite verification runs
The full orchestrator suite showed 1 failure in `tests/test_tts_client.py`, which referenced a not-yet-existent `settings.tts_backend`.

**Context:** `git status` confirmed the file was untracked and belonged to Phase 2 (requirement TTS-06). The 368 committed Phase 1 tests all passed. Verification had to check tracked-vs-untracked status before attributing the failure.
**Source:** 01-VERIFICATION.md

---

## Patterns

### Dedicated lock per protected resource
Name each lock after what it guards — `_lock` for adapter state, `_consumer_lock` for the consumer list — instead of one coarse lock over the whole manager.

**When to use:** Any async manager class holding two or more independently mutated collections where operations on one should not block operations on the other.
**Source:** 01-03-SUMMARY.md (`patterns-established`)

### Direct collection mutation inside an already-held lock
When code inside a locked region needs the effect of a public locking method, inline the raw mutation (wrapped in `try/except ValueError`) rather than calling the method.

**When to use:** Cleanup loops inside a broadcast or iteration that already holds the relevant non-reentrant lock.
**Source:** 01-03-SUMMARY.md

### Grep-expressible acceptance criteria for removal work
Every acceptance criterion for the deletion tasks was phrased as a string presence or absence check (`config.py does NOT contain "simconnect_ws_host"`), with the verify block a single `grep -rn ... ; echo "EXIT:$?"`.

**When to use:** Deprecation, rename, and dead-code-removal plans. It makes "done" mechanically checkable and gives the verifier the exact same command to re-run.
**Source:** 01-01-PLAN.md, 01-VERIFICATION.md

### Plan-embedded fallback for facts that need an unavailable tool to confirm
The plan wrote the decision procedure into the task: "Try `1.5` first. If that fails, use `1.5.5`," including the `docker manifest inspect ... || echo "Use 1.5.5 instead"` probe.

**When to use:** Any plan step that depends on external state (registry tags, API availability) the executor may not be able to query. Turns a blocker into a documented minor deviation.
**Source:** 01-02-PLAN.md

### One atomic commit per task with the type prefix matching the work
Plan 01 produced `5589216` (chore) and `d58a02a` (chore); plan 03 produced `12faa23` (fix) and `390d171` (chore). Auto-fixed deviations were folded into the commit of the task that surfaced them.

**When to use:** Standard for all GSD plan execution — keeps the phase revertible at task granularity.
**Source:** 01-01-SUMMARY.md, 01-03-SUMMARY.md

---

## Surprises

### The only failing test in the phase belonged to a different phase
Full-suite verification showed a failure in `tests/test_tts_client.py::TestTTSConfig::test_tts_configured_elevenlabs`, which looked like a Phase 1 regression until `git status` revealed the file was untracked Phase 2 work-in-progress.

**Impact:** Cost a verification detour and required an explicit note in the report to keep the phase status at PASSED rather than logging a false gap.
**Source:** 01-VERIFICATION.md

### Docker being absent from the environment shaped a code decision
The image-pinning plan assumed the executor could query Docker Hub. It could not, so the fallback path — full patch versions — became the shipped choice, and one of the plan's three verification steps was skipped entirely.

**Impact:** Minor deviation logged in 01-02-SUMMARY.md and a "Human Verification Required: none, but compose config unvalidated" note in the verification report. The outcome was arguably better than the plan's preference.
**Source:** 01-02-SUMMARY.md, 01-VERIFICATION.md

### A lock-addition task produced two unplanned edits before it could pass
Adding `_consumer_lock` was a 5-step, single-file plan on paper. It required editing `test_adapter_manager.py` for the sync/async break and removing two unrelated unused imports before ruff and pytest would both pass.

**Impact:** Two auto-fixed deviations on an otherwise deviation-free phase (plans 01 and 02 executed exactly as written). Both were judged necessary for correctness with no scope creep.
**Source:** 01-03-SUMMARY.md
