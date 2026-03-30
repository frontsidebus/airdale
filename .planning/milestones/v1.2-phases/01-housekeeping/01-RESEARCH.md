# Phase 1: Housekeeping - Research

**Researched:** 2026-03-26
**Domain:** Python config cleanup, asyncio concurrency, Docker image management
**Confidence:** HIGH

## Summary

Phase 1 is a set of independent, mechanical cleanup tasks: removing deprecated config fields, fixing a race condition, pinning Docker images, standardizing Python versions, and deleting dead files. All changes are well-scoped with clear before/after states. No new libraries or architectural patterns are introduced.

The primary risk is incomplete removal of deprecated references -- grep audits found references in 8 files across the codebase (config.py, sim_client.py, docker-compose.yml, .env.example, docs/API.md, test_config.py, conftest.py, and a previously unmentioned integration test). The race condition fix follows an existing pattern already used in the same class.

**Primary recommendation:** Treat each decision (D-01 through D-07) as an independent, parallelizable task. Grep-verify after each removal to confirm zero remaining references.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Full cleanup -- remove deprecated `simconnect_ws_host`, `simconnect_ws_port`, `simconnect_bridge_url` fields from `orchestrator/orchestrator/config.py`, the `SimConnectClient = TelemetryClient` alias from `orchestrator/orchestrator/sim_client.py`, `SIMCONNECT_BRIDGE_URL` from `docker-compose.yml`, references from `.env.example`, `docs/API.md`, test fixtures in `orchestrator/tests/test_config.py`, and `conftest.py`.
- **D-02:** The `_build_derived` model validator that constructs the legacy URL should be removed along with the fields it derives.
- **D-03:** Standardize all Dockerfiles on `python:3.12-slim`. The telemetry-service Dockerfile currently uses `python:3.11-slim` and must be updated to match the orchestrator's `python:3.12-slim`.
- **D-04:** Use minor-range version tags for third-party Docker images. Pin `chromadb/chroma` and `fedirz/faster-whisper-server` to minor versions instead of `:latest`.
- **D-05:** Pin both the CPU and GPU (commented-out) variants of the Whisper image.
- **D-06:** Fix the telemetry consumer list race condition using `asyncio.Lock`. Add a single `asyncio.Lock` to `AdapterManager` that protects `add_consumer`, `remove_consumer`, and `_broadcast_to_consumers`.
- **D-07:** Delete `adapters/msfs/SimConnectBridge.Tests/WebSocketServerTests.cs` (empty placeholder file).

### Claude's Discretion
- Exact minor version numbers for Docker image pins (determine current latest stable at implementation time)
- Whether to update `pyproject.toml` `requires-python` to `>=3.12` or leave at `>=3.11`
- How to handle the deprecated `SIMCONNECT_BRIDGE_URL` reference in docs/API.md (remove row vs mark as removed)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HSKP-01 | Deprecated SimConnect config fields and backward-compat alias removed from orchestrator | Grep audit found all 8 files containing references; D-01/D-02 cover removal |
| HSKP-02 | Race condition in telemetry consumer list fixed with asyncio.Lock | Existing `self._lock` pattern in AdapterManager; D-06 covers the fix |
| HSKP-03 | ChromaDB Docker image pinned to specific version tag | Current stable: 1.5.5 (March 2026); D-04 covers pinning |
| HSKP-04 | Whisper Docker image pinned to specific version tag | Current stable: 0.8.3; D-04/D-05 cover CPU and GPU variants |
| HSKP-05 | Python version standardized across all Dockerfiles | telemetry-service uses 3.11-slim, orchestrator uses 3.12-slim; D-03 covers update |
| HSKP-06 | Empty WebSocketServerTests.cs file removed | File confirmed empty (3-line comment); D-07 covers deletion |
| HSKP-07 | SIMCONNECT_BRIDGE_URL env var removed from docker-compose.yml | Line 127 of docker-compose.yml; covered by D-01 |
</phase_requirements>

## Architecture Patterns

### Deprecated Config Field Removal (D-01, D-02)

**What:** Remove 3 deprecated fields from pydantic-settings `Settings` class, their model validator, a backward-compat alias, and all references across config, tests, docker-compose, docs, and .env.example.

**Complete file inventory (verified by grep):**

| File | What to Remove | Line(s) |
|------|---------------|---------|
| `orchestrator/orchestrator/config.py` | 3 Field declarations + legacy section comment | 61-73 |
| `orchestrator/orchestrator/config.py` | Legacy URL construction in `_build_derived` validator | 126-129 |
| `orchestrator/orchestrator/sim_client.py` | `SimConnectClient = TelemetryClient` alias | 526 |
| `orchestrator/tests/test_config.py` | `test_default_simconnect_url` test method | 15-18 |
| `orchestrator/tests/test_config.py` | `test_env_overrides_simconnect_url` test method | 69-71 |
| `orchestrator/tests/conftest.py` | `SIMCONNECT_BRIDGE_URL` entry in `mock_env_vars` dict | 49 |
| `tests/integration/test_orchestrator_e2e.py` | `simconnect_bridge_url=` kwarg in `tmp_settings` fixture | 40 |
| `docker-compose.yml` | `SIMCONNECT_BRIDGE_URL` env var line | 127 |
| `.env.example` | Commented-out legacy SimConnect settings block | 50-53 |
| `docs/API.md` | SimConnect Bridge env var table section | 533-541 |
| `docs/ARCHITECTURE.md` | `SimConnectClient` references (narrative text) | 116, 260 |

**Critical discovery not in CONTEXT.md:** The integration test `tests/integration/test_orchestrator_e2e.py` line 40 passes `simconnect_bridge_url=` as a kwarg to `Settings()`. This MUST be updated or the integration test will fail after field removal.

**Pattern for the model validator cleanup:** The `_build_derived` validator currently handles two things: (1) telemetry service URL construction and (2) legacy bridge URL construction. After removing the legacy fields, the validator should ONLY keep the telemetry service URL logic. The validator method itself should remain -- just strip the legacy block (lines 126-129).

```python
# AFTER cleanup -- _build_derived keeps only telemetry URL logic
@model_validator(mode="after")
def _build_derived(self) -> Settings:
    if not self.telemetry_service_url:
        self.telemetry_service_url = (
            f"ws://{self.telemetry_service_host}"
            f":{self.telemetry_service_port}/ws/telemetry"
        )
    return self
```

### docs/ARCHITECTURE.md References

`docs/ARCHITECTURE.md` has two narrative references to `SimConnectClient` at lines 116 and 260. These describe historical architecture decisions. **Recommendation:** Update the text to use `TelemetryClient` since that is the current canonical name. These are documentation-only changes with no runtime impact.

### Consumer Lock Fix (D-06)

**What:** The `AdapterManager` class already has `self._lock = asyncio.Lock()` for adapter state. Consumer operations (`add_consumer`, `remove_consumer`, `_broadcast_to_consumers`) currently operate on `self._consumers` without synchronization.

**The race condition:** When `_broadcast_to_consumers` iterates `self._consumers` and a consumer disconnects mid-iteration, `remove_consumer` mutates the list. The dead consumer cleanup at the end of `_broadcast_to_consumers` also calls `remove_consumer`, creating a nested mutation.

**Fix pattern -- use a dedicated consumer lock:**

```python
def __init__(self, stale_timeout: float = 15.0) -> None:
    self._adapters: dict[str, AdapterConnection] = {}
    self._consumers: list[ConsumerConnection] = []
    self._stale_timeout = stale_timeout
    self._lock = asyncio.Lock()          # existing -- for adapters
    self._consumer_lock = asyncio.Lock()  # NEW -- for consumers
```

**Why a separate lock:** Using the same `self._lock` for both adapters and consumers would create unnecessary contention. `update_telemetry` already holds `self._lock` when it calls `_broadcast_to_consumers` -- if broadcast also acquired `self._lock`, it would deadlock. A dedicated `self._consumer_lock` avoids this entirely.

**Methods to protect:**
- `add_consumer` -- wrap body in `async with self._consumer_lock`
- `remove_consumer` -- make async, wrap in `async with self._consumer_lock`
- `_broadcast_to_consumers` -- wrap the iteration + dead consumer cleanup in `async with self._consumer_lock`

**Caller impact of making `remove_consumer` async:** Check `telemetry-service/telemetry/service.py` for calls to `remove_consumer` -- they are in async WebSocket handler context, so `await` is straightforward.

### Docker Image Pinning (D-04, D-05)

**Current state:**
- `chromadb/chroma:latest` (line 59 of docker-compose.yml)
- `fedirz/faster-whisper-server:latest-cpu` (line 21 of docker-compose.yml)
- Commented GPU: `fedirz/faster-whisper-server:latest-cuda` (line 45)

**Recommended pins (minor-range per D-04):**

| Image | Current Tag | Pinned Tag | Rationale |
|-------|-------------|------------|-----------|
| `chromadb/chroma` | `latest` | `1.5` | Latest stable minor (1.5.5 released 2026-03-10). Gets patch updates, blocks breaking major/minor bumps. |
| `fedirz/faster-whisper-server` (CPU) | `latest-cpu` | `0.8-cpu` | Latest stable minor (0.8.3 released Sept 2024). Note: tag format uses `-cpu`/`-cuda` suffix. |
| `fedirz/faster-whisper-server` (GPU) | `latest-cuda` | `0.8-cuda` | Same version, GPU variant. |

**Tag verification note:** The faster-whisper-server image may not have a `0.8-cpu` shorthand tag -- it might only have `0.8.3-cpu` as a specific tag. The implementer should verify which tag formats exist on Docker Hub before committing. If minor-range tags are not published, use the full patch version (e.g., `0.8.3-cpu`).

### Python Version Standardization (D-03)

**Current state:**
- `orchestrator/Dockerfile`: `python:3.12-slim` (both build and runtime stages)
- `telemetry-service/Dockerfile`: `python:3.11-slim`

**Change:** Update `telemetry-service/Dockerfile` line 1 from `python:3.11-slim` to `python:3.12-slim`.

**Risk:** LOW. Python 3.12 is backward compatible with 3.11. The telemetry service uses standard FastAPI/Pydantic -- no 3.11-specific features.

**pyproject.toml consideration (Claude's discretion):** The orchestrator's `pyproject.toml` likely has `requires-python = ">=3.11"`. Recommendation: leave it at `>=3.11` -- this documents the minimum supported version. Changing to `>=3.12` would be accurate for Docker but would unnecessarily restrict local development where 3.11 still works fine.

### Dead File Deletion (D-07)

**File:** `adapters/msfs/SimConnectBridge.Tests/WebSocketServerTests.cs`
**Content:** 3-line comment explaining the file is intentionally empty and replaced by `TelemetryServiceClientTests.cs`.
**Action:** `git rm` the file.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async list synchronization | Manual iteration guards | `asyncio.Lock` | Correct under all event loop scheduling; no manual copy-on-write needed |
| Docker version management | Shell scripts to check versions | Docker Compose pinned tags | Declarative, reproducible, zero maintenance |

## Common Pitfalls

### Pitfall 1: Incomplete Reference Removal
**What goes wrong:** A deprecated field is removed from config.py but a test or integration test still references it, causing test failures.
**Why it happens:** Grep audits miss files outside the obvious search scope, or miss indirect references (e.g., env var names vs field names).
**How to avoid:** After removal, run `grep -r "simconnect" --include="*.py" --include="*.yml" --include="*.md" --include="*.env*"` from repo root. Also run `pytest` and `dotnet test` to catch runtime breakage.
**Warning signs:** Any test importing or setting `SIMCONNECT_BRIDGE_URL`, `simconnect_bridge_url`, or `SimConnectClient`.

### Pitfall 2: asyncio.Lock Deadlock from Lock Reuse
**What goes wrong:** Using the existing `self._lock` for consumer operations causes deadlock because `update_telemetry` holds `self._lock` then calls `_broadcast_to_consumers` which would try to acquire the same lock.
**Why it happens:** asyncio.Lock is not reentrant.
**How to avoid:** Use a separate `self._consumer_lock` for consumer operations, not the existing `self._lock`.
**Warning signs:** The telemetry service hangs under load with no error output.

### Pitfall 3: Docker Tag Does Not Exist
**What goes wrong:** Pinning to a minor-range tag like `0.8-cpu` that the image publisher never created -- only `0.8.3-cpu` exists.
**Why it happens:** Not all Docker image publishers create shorthand minor tags.
**How to avoid:** Verify the exact tag exists with `docker pull` or check Docker Hub tags page before committing.
**Warning signs:** `docker compose build` or `docker compose pull` fails with "manifest unknown".

### Pitfall 4: Integration Test Missed in CONTEXT.md
**What goes wrong:** CONTEXT.md lists files to update but misses `tests/integration/test_orchestrator_e2e.py` which passes `simconnect_bridge_url=` to Settings.
**Why it happens:** The file is in a different test directory (`tests/integration/` at repo root, not `orchestrator/tests/`).
**How to avoid:** This research document has identified the gap. The planner must include this file in the removal task.
**Warning signs:** Integration tests fail after config field removal.

## Code Examples

### Config Field Removal -- Before and After

**Before (config.py lines 61-73):**
```python
# --- Legacy SimConnect bridge (deprecated, kept for backward compat) -----
simconnect_ws_host: str = Field(
    default="localhost",
    description="(Deprecated) WebSocket host for direct SimConnect bridge",
)
simconnect_ws_port: int = Field(
    default=8080,
    description="(Deprecated) WebSocket port for direct SimConnect bridge",
)
simconnect_bridge_url: str = Field(
    default="",
    description="(Deprecated) Full WebSocket URL for direct bridge connection",
)
```

**After:** Entire block removed. No replacement needed.

### Consumer Lock -- After Pattern

```python
async def add_consumer(self, ws: WebSocket) -> ConsumerConnection:
    """Register a new consumer connection."""
    conn = ConsumerConnection(websocket=ws)
    async with self._consumer_lock:
        self._consumers.append(conn)
    logger.info("Consumer connected [total: %d]", len(self._consumers))
    return conn

async def remove_consumer(self, conn: ConsumerConnection) -> None:
    """Remove a consumer connection."""
    async with self._consumer_lock:
        try:
            self._consumers.remove(conn)
        except ValueError:
            pass
    logger.info(
        "Consumer disconnected (sent %d msgs) [remaining: %d]",
        conn.messages_sent,
        len(self._consumers),
    )

async def _broadcast_to_consumers(
    self, envelope: TelemetryEnvelope
) -> None:
    """Send telemetry to all connected consumers."""
    async with self._consumer_lock:
        if not self._consumers:
            return

        full_data = envelope.to_legacy_simstate()
        full_data["adapter_id"] = envelope.adapter_id
        full_data["sim_name"] = envelope.sim_name
        full_data["vehicle_type"] = envelope.vehicle_type

        full_json: str | None = None
        dead_consumers: list[ConsumerConnection] = []

        for consumer in self._consumers:
            try:
                if consumer.subscribed_fields:
                    filtered = self._filter_state(
                        full_data, consumer.subscribed_fields
                    )
                    await consumer.websocket.send_text(
                        json.dumps(filtered)
                    )
                else:
                    if full_json is None:
                        full_json = json.dumps(full_data)
                    await consumer.websocket.send_text(full_json)
                consumer.messages_sent += 1
            except Exception:
                dead_consumers.append(consumer)

        for consumer in dead_consumers:
            try:
                self._consumers.remove(consumer)
            except ValueError:
                pass
```

**Note:** The dead consumer cleanup inside `_broadcast_to_consumers` should directly mutate `self._consumers` rather than calling `self.remove_consumer()` to avoid re-acquiring the lock. The lock is already held.

### Docker Compose Pinning -- After

```yaml
whisper:
    image: fedirz/faster-whisper-server:0.8-cpu  # or 0.8.3-cpu if minor tag unavailable
    # ...
    # GPU variant (commented out):
    # image: fedirz/faster-whisper-server:0.8-cuda

chromadb:
    image: chromadb/chroma:1.5
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Direct SimConnect bridge | Universal telemetry service | Already migrated | Legacy config fields are dead weight |
| `SimConnectClient` class | `TelemetryClient` class | Already renamed | Alias is dead weight |
| `:latest` Docker tags | Minor-pinned tags | This phase | Reproducible builds |
| Mixed Python 3.11/3.12 | Standardized 3.12 | This phase | Consistent runtime behavior |

## Open Questions

1. **faster-whisper-server minor tag availability**
   - What we know: Tags 0.8.3-cpu and 0.8.3-cuda exist. Tag 0.5-cuda was seen in search results.
   - What's unclear: Whether `0.8-cpu` shorthand exists, or only `0.8.3-cpu`.
   - Recommendation: Implementer should verify with `docker manifest inspect fedirz/faster-whisper-server:0.8-cpu` or check Docker Hub. Fall back to `0.8.3-cpu` if shorthand is unavailable.

2. **chromadb/chroma minor tag availability**
   - What we know: Version 1.5.5 is latest stable. Tags like `0.4.15.dev14` exist.
   - What's unclear: Whether `1.5` shorthand exists, or only `1.5.5`.
   - Recommendation: Same verification approach. Fall back to `1.5.5` if needed.

3. **Integration test fixture after removal**
   - What we know: `tests/integration/test_orchestrator_e2e.py:40` passes `simconnect_bridge_url=` to Settings.
   - What's unclear: Whether this test has other deprecated references or can simply have the kwarg removed.
   - Recommendation: The Settings class has `extra = "ignore"`, but once the field is removed, passing it as an explicit keyword argument will cause a TypeError. The kwarg must be removed.

## Project Constraints (from CLAUDE.md)

- **Linter/Formatter:** ruff (config in `pyproject.toml`) -- run `ruff check .` and `ruff format .` after changes
- **Line length:** 100 characters
- **Type hints:** Required on all function signatures
- **Async:** Use `async`/`await` throughout the orchestrator
- **Models:** Pydantic `BaseModel` for data crossing boundaries; `pydantic-settings` `BaseSettings` for config
- **Config:** Never hardcode keys or magic numbers
- **Python tests:** pytest + pytest-asyncio
- **C# tests:** xUnit, `dotnet test`
- **Docker:** `docker compose build` must succeed

## Sources

### Primary (HIGH confidence)
- Direct codebase grep audit -- all 8+ files with deprecated references verified
- `orchestrator/orchestrator/config.py` -- current Settings class structure
- `telemetry-service/telemetry/adapter_manager.py` -- current consumer management code
- `docker-compose.yml` -- current image tags and env vars

### Secondary (MEDIUM confidence)
- [ChromaDB GitHub Releases](https://github.com/chroma-core/chroma/releases) -- v1.5.5 latest stable (2026-03-10)
- [faster-whisper-server GitHub Releases](https://github.com/fedirz/faster-whisper-server/releases) -- v0.8.3 latest stable
- [ChromaDB Docker Hub](https://hub.docker.com/r/chromadb/chroma) -- tag availability
- [faster-whisper-server Docker Hub](https://hub.docker.com/r/fedirz/faster-whisper-server/tags) -- tag availability

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new libraries, all changes within existing codebase
- Architecture: HIGH -- patterns already established in the codebase (asyncio.Lock, pydantic-settings)
- Pitfalls: HIGH -- verified by direct code inspection and grep audit

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (stable -- no fast-moving dependencies)
