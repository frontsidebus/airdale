# Phase 1: Housekeeping - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Independent bug fixes, config cleanup, and dependency pinning to establish a clean, regression-detectable baseline. All items are parallelizable — no dependencies between housekeeping tasks. This phase produces point releases, not structural changes.

</domain>

<decisions>
## Implementation Decisions

### Deprecated Config Removal
- **D-01:** Full cleanup — remove deprecated `simconnect_ws_host`, `simconnect_ws_port`, `simconnect_bridge_url` fields from `orchestrator/orchestrator/config.py`, the `SimConnectClient = TelemetryClient` alias from `orchestrator/orchestrator/sim_client.py`, `SIMCONNECT_BRIDGE_URL` from `docker-compose.yml`, references from `.env.example`, `docs/API.md`, test fixtures in `orchestrator/tests/test_config.py`, and `conftest.py`.
- **D-02:** The `_build_derived` model validator that constructs the legacy URL should be removed along with the fields it derives.

### Python Version Standardization
- **D-03:** Standardize all Dockerfiles on `python:3.12-slim`. The telemetry-service Dockerfile currently uses `python:3.11-slim` and must be updated to match the orchestrator's `python:3.12-slim`.

### Docker Image Pinning
- **D-04:** Use minor-range version tags for third-party Docker images. Pin `chromadb/chroma` and `fedirz/faster-whisper-server` to minor versions (e.g., `chromadb/chroma:0.5`, `fedirz/faster-whisper-server:0.4-cpu`) instead of `:latest`. This gets patch updates automatically while avoiding breaking changes from major/minor bumps.
- **D-05:** Pin both the CPU and GPU (commented-out) variants of the Whisper image.

### Race Condition Fix
- **D-06:** Fix the telemetry consumer list race condition using `asyncio.Lock`. Add a single `asyncio.Lock` to `AdapterManager` that protects `add_consumer`, `remove_consumer`, and `_broadcast_to_consumers`. Lock contention is negligible for this use case (low consumer count, infrequent mutations).

### Dead File Cleanup
- **D-07:** Delete `adapters/msfs/SimConnectBridge.Tests/WebSocketServerTests.cs` (empty placeholder file).

### Claude's Discretion
- Exact minor version numbers for Docker image pins (determine current latest stable at implementation time)
- Whether to update `pyproject.toml` `requires-python` to `>=3.12` or leave at `>=3.11`
- How to handle the deprecated `SIMCONNECT_BRIDGE_URL` reference in docs/API.md (remove row vs mark as removed)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Config & Settings
- `orchestrator/orchestrator/config.py` — Settings class with deprecated fields (lines 62-73, 126-128)
- `orchestrator/orchestrator/sim_client.py` — SimConnectClient alias (line 526)

### Docker Infrastructure
- `docker-compose.yml` — Production service stack with unpinned images and deprecated env var (lines 21, 45, 59, 127)
- `docker-compose.dev.yml` — Dev overrides
- `orchestrator/Dockerfile` — Uses python:3.12-slim (lines 7, 30)
- `telemetry-service/Dockerfile` — Uses python:3.11-slim (line 1)

### Telemetry Service
- `telemetry-service/telemetry/adapter_manager.py` — Consumer list without synchronization (lines 49, 196-266)

### Test Fixtures
- `orchestrator/tests/test_config.py` — Tests referencing deprecated fields (lines 18, 71)
- `orchestrator/tests/conftest.py` — Fixture setting deprecated env var (line 49)

### Documentation
- `.env.example` — Documents deprecated SIMCONNECT_BRIDGE_URL
- `docs/API.md` — References deprecated env var (line 539)

### Dead Files
- `adapters/msfs/SimConnectBridge.Tests/WebSocketServerTests.cs` — Empty placeholder

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `AdapterManager` already has `self._lock` for adapter state — consumer lock follows the same pattern
- `TelemetryClient` in sim_client.py is the canonical name (alias just provides backward compat)

### Established Patterns
- pydantic-settings `BaseSettings` with `model_validator(mode="before")` for derived fields
- Docker multi-stage builds for orchestrator
- `asyncio.Lock` already used in telemetry service for adapter state

### Integration Points
- Config field removal affects: Settings class, docker-compose env, .env.example, API docs, test fixtures
- Consumer lock affects: adapter_manager.py only (isolated change)
- Python version change affects: telemetry-service/Dockerfile only
- Image pinning affects: docker-compose.yml only

</code_context>

<specifics>
## Specific Ideas

No specific requirements — all items are well-defined mechanical changes with clear before/after states.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-housekeeping*
*Context gathered: 2026-03-27*
