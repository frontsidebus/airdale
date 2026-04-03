# Phase 6: CI/CD Pipeline - Research

**Researched:** 2026-03-26
**Domain:** GitHub Actions CI/CD for polyglot (Python + C# + Docker) project
**Confidence:** HIGH

## Summary

This phase creates three GitHub Actions workflow files from scratch -- no CI exists today. The project is a polyglot monorepo with Python (orchestrator, telemetry-service, web server), C# (MSFS adapter), and Docker (multi-service compose stack). The key technical challenge is the C# adapter's dependency on the SimConnect SDK, which is Windows-only and not available on Linux CI runners. The test project has already been architected to avoid this dependency by including source files directly rather than referencing the main project, so `dotnet test` on the test project alone will work on `ubuntu-latest`.

The three workflows map cleanly to the codebase's language boundaries: Python CI (lint + test + integration), .NET CI (test project only), and Docker CI (compose build verification). Native `paths:` triggers provide sufficient path filtering without third-party actions.

**Primary recommendation:** Use native GHA `paths:` triggers with three separate workflow files. The .NET CI must target only the test project (`SimConnectBridge.Tests/`), never the main `SimConnectBridge.csproj` which requires SimConnect SDK. The integration job should use `docker compose -f docker-compose.yml -f docker-compose.dev.yml` to get the `tiny` Whisper model for fast CI startup.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: Three separate GHA workflow files: `python-ci.yml`, `dotnet-ci.yml`, `docker-ci.yml`
- D-02: Path-based filtering using `paths:` in workflow `on:` triggers
- D-03: Python CI triggers on `orchestrator/**`, `telemetry-service/**`, `web/**`, `*.py`
- D-04: .NET CI triggers on `adapters/msfs/**`
- D-05: Docker CI triggers on `**/Dockerfile`, `docker-compose*.yml`, `.dockerignore`
- D-06: Python Job 1 -- lint-and-test (every push + PR): ruff check + ruff format --check, pytest for orchestrator/telemetry/web. Python 3.12 on ubuntu-latest
- D-07: Python Job 2 -- integration (PRs only): Whisper + ChromaDB via docker-compose, `pytest -m integration`
- D-08: Use Whisper `tiny` model in CI integration tests
- D-09: .NET CI: `dotnet build` + `dotnet test` on ubuntu-latest with .NET 8.0
- D-10: Docker CI: `docker compose build` to verify Dockerfiles. Don't start containers
- D-11: Use `docker compose config` to validate YAML before building
- D-12: No branch protection rules -- workflows report status only

### Claude's Discretion
- GHA runner versions (ubuntu-latest vs pinned)
- Cache strategy for pip/docker layers
- Whether to use `dorny/paths-filter` action or native `paths:` triggers
- Exact pytest markers and integration test fixtures

### Deferred Ideas (OUT OF SCOPE)
None.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CICD-01 | GHA workflow runs ruff lint on Python code | Python CI Job 1: `ruff check` + `ruff format --check` across all three Python dirs |
| CICD-02 | GHA workflow runs pytest for orchestrator tests | Python CI Job 1: `cd orchestrator && pytest` (default addopts excludes integration) |
| CICD-03 | GHA workflow runs pytest for telemetry-service tests | Python CI Job 1: `cd telemetry-service && pytest` |
| CICD-04 | GHA workflow runs dotnet test for MSFS adapter | .NET CI: `dotnet test adapters/msfs/SimConnectBridge.Tests/` on ubuntu-latest |
| CICD-05 | GHA workflow verifies Docker build succeeds | Docker CI: `docker compose config` then `docker compose build` |
| CICD-06 | Path-based filtering triggers only relevant workflows | Native `paths:` triggers in each workflow's `on:` block |
| CICD-07 | Web server tests included in CI pipeline | Python CI Job 1: `pytest web/tests/` alongside orchestrator and telemetry tests |
</phase_requirements>

## Standard Stack

### Core

| Library/Action | Version | Purpose | Why Standard |
|----------------|---------|---------|--------------|
| `actions/checkout` | v4 | Clone repository | Official GHA checkout action |
| `actions/setup-python` | v5 | Install Python 3.12 | Official Python setup; v5 is stable, v6 requires runner v2.327.1+ |
| `actions/setup-dotnet` | v4 | Install .NET 8.0 SDK | Official .NET setup |
| `actions/cache` | v4 | Cache pip packages, NuGet, Docker layers | Official cache action |

### Recommendations (Claude's Discretion)

| Decision | Recommendation | Rationale |
|----------|---------------|-----------|
| Runner version | `ubuntu-latest` (not pinned) | Project is not sensitive to runner OS version; latest gets security patches automatically |
| Path filtering | Native `paths:` triggers | Sufficient for this project's needs; avoids third-party action dependency. `dorny/paths-filter` adds value only when you need matrix-based conditional jobs within a single workflow |
| setup-python version | v5 not v6 | v6 requires runner v2.327.1+ which may not be available on all runner pools; v5 is broadly compatible |
| Pip caching | `actions/setup-python` built-in `cache: 'pip'` | Eliminates need for separate `actions/cache` step for Python deps |
| Docker layer caching | Not needed | Docker CI only builds, does not push; builds run infrequently on Dockerfile changes. Layer caching adds complexity without meaningful time savings |

## Architecture Patterns

### Workflow File Structure
```
.github/
└── workflows/
    ├── python-ci.yml     # Lint + unit tests + integration tests
    ├── dotnet-ci.yml     # .NET test project only
    └── docker-ci.yml     # Compose build verification
```

### Pattern 1: Multi-Job Python Workflow

**What:** Single workflow file with two jobs -- fast lint+test on every push/PR, slower integration tests on PRs only.

**When to use:** When you have fast unit tests that should run on every push plus slow service-dependent tests that only matter for PRs.

**Example:**
```yaml
name: Python CI

on:
  push:
    branches: [main]
    paths:
      - 'orchestrator/**'
      - 'telemetry-service/**'
      - 'web/**'
      - '*.py'
  pull_request:
    paths:
      - 'orchestrator/**'
      - 'telemetry-service/**'
      - 'web/**'
      - '*.py'

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      - name: Install orchestrator deps
        run: cd orchestrator && pip install -e ".[test]"
      - name: Install telemetry-service deps
        run: cd telemetry-service && pip install -e ".[dev]"
      - name: Install web deps
        run: pip install -r web/requirements.txt && pip install httpx-ws pytest pytest-asyncio
      - name: Ruff lint
        run: ruff check orchestrator/ telemetry-service/ web/
      - name: Ruff format check
        run: ruff format --check orchestrator/ telemetry-service/ web/
      - name: Orchestrator tests
        run: cd orchestrator && pytest
      - name: Telemetry service tests
        run: cd telemetry-service && pytest
      - name: Web server tests
        run: pytest web/tests/

  integration:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    needs: lint-and-test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      - name: Install deps
        run: cd orchestrator && pip install -e ".[test]"
      - name: Start services
        run: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d whisper chromadb
      - name: Wait for services
        run: |
          # Wait for Whisper health (tiny model ~30s startup)
          timeout 120 bash -c 'until docker compose exec whisper python3 -c "import urllib.request; urllib.request.urlopen(\"http://localhost:8000/health\")" 2>/dev/null; do sleep 5; done'
          # Wait for ChromaDB health
          timeout 30 bash -c 'until curl -sf http://localhost:8000/api/v1/heartbeat; do sleep 2; done'
      - name: Integration tests
        run: cd orchestrator && pytest -m integration
      - name: Stop services
        if: always()
        run: docker compose down
```

### Pattern 2: Test-Project-Only .NET CI

**What:** Build and test only the test project, which is self-contained and does not require SimConnect SDK.

**Why:** The main `SimConnectBridge.csproj` references `Microsoft.FlightSimulator.SimConnect.dll` via a local HintPath (`C:\MSFS 2024 SDK\...`). This DLL is Windows-only and not available on ubuntu-latest runners. The test project (`SimConnectBridge.Tests.csproj`) was specifically designed to avoid this -- it uses `<Compile Include>` to directly include source files (`SimState.cs`, `TelemetryServiceClient.cs`) and has its own `TestDataStructs.cs` mirror copies of the SimConnect data structs.

**Example:**
```yaml
name: .NET CI

on:
  push:
    branches: [main]
    paths:
      - 'adapters/msfs/**'
  pull_request:
    paths:
      - 'adapters/msfs/**'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '8.0.x'
      - name: Build test project
        run: dotnet build adapters/msfs/SimConnectBridge.Tests/SimConnectBridge.Tests.csproj --configuration Release
      - name: Run tests
        run: dotnet test adapters/msfs/SimConnectBridge.Tests/SimConnectBridge.Tests.csproj --configuration Release --no-build
```

### Pattern 3: Docker Compose Build Verification

**What:** Validate compose file syntax and verify all Dockerfiles build successfully, without starting containers.

**Example:**
```yaml
name: Docker CI

on:
  push:
    branches: [main]
    paths:
      - '**/Dockerfile'
      - 'docker-compose*.yml'
      - '.dockerignore'
  pull_request:
    paths:
      - '**/Dockerfile'
      - 'docker-compose*.yml'
      - '.dockerignore'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate compose config
        run: docker compose config --quiet
      - name: Build all services
        run: docker compose build
```

### Anti-Patterns to Avoid
- **Building the main SimConnectBridge.csproj in CI:** Will always fail on Linux due to missing SimConnect SDK DLL. Only build/test the test project.
- **Using `docker-compose` (v1 hyphenated command):** Deprecated. Use `docker compose` (v2 plugin syntax).
- **Using `services:` block for integration tests with custom images:** GHA `services:` requires images from a registry; it cannot build from local Dockerfiles. Use `docker compose up -d` instead.
- **Running integration tests without health check waits:** Whisper needs ~30s to download the tiny model on first run. Always wait for health endpoints.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Path-based filtering | Custom shell scripts to detect changed files | Native `paths:` in `on:` trigger | Built into GHA, zero maintenance, handles all edge cases |
| Python dependency caching | Manual `actions/cache` with pip cache dir | `actions/setup-python` with `cache: 'pip'` | Built-in feature, automatically hashes requirements files |
| Service health waiting | Custom retry loops with complex error handling | Simple `timeout` + `until curl` bash loop | Readable, debuggable, and sufficient for CI |
| Docker Compose installation | Manual install step | Pre-installed on ubuntu-latest | Docker Compose v2 is pre-installed; no setup needed |

## Common Pitfalls

### Pitfall 1: SimConnect SDK Missing on Linux Runners
**What goes wrong:** `dotnet build` on the main `.csproj` fails because `Microsoft.FlightSimulator.SimConnect.dll` is at a Windows-specific path.
**Why it happens:** The MSFS SDK is Windows-only. The main project hardcodes `HintPath` to `C:\MSFS 2024 SDK\...`.
**How to avoid:** Only build/test the `SimConnectBridge.Tests` project in CI. It was designed to be self-contained -- it includes source files directly and has mirror copies of data structs in `TestDataStructs.cs`.
**Warning signs:** Build error referencing `Microsoft.FlightSimulator.SimConnect` assembly.

### Pitfall 2: Whisper Model Download Timeout
**What goes wrong:** Integration tests fail because Whisper container is not ready -- the tiny model needs to download on first run.
**Why it happens:** No model cache in CI; every run starts fresh. Even `tiny` model takes 10-30 seconds to download and load.
**How to avoid:** Use a generous health check timeout (120s). The `docker-compose.dev.yml` overlay sets `WHISPER__MODEL=tiny` which is fastest. Consider caching the `whisper_cache` Docker volume between runs if startup time becomes a problem.
**Warning signs:** Integration tests fail with connection refused on port 9090.

### Pitfall 3: ChromaDB Port Conflict with Whisper Health Check
**What goes wrong:** Health check curls the wrong service because both ChromaDB and Whisper use port 8000 internally.
**Why it happens:** ChromaDB maps `8000:8000` and Whisper maps `9090:8000`. From the host (CI runner), ChromaDB is on port 8000 and Whisper is on port 9090.
**How to avoid:** Wait for ChromaDB at `localhost:8000` and Whisper at `localhost:9090`. Refer to the `docker-compose.yml` port mappings.
**Warning signs:** Health check passes instantly but integration tests fail connecting to the service.

### Pitfall 4: Ruff Not Installed for Telemetry/Web Lint
**What goes wrong:** `ruff check` fails because ruff is only in the orchestrator's dev dependencies, not telemetry-service or web.
**Why it happens:** Ruff config lives in `orchestrator/pyproject.toml` but ruff should lint all Python code.
**How to avoid:** Install ruff explicitly (`pip install ruff`) or ensure it comes from the orchestrator's dev/test deps. Run `ruff check` from the repo root with explicit paths, using the orchestrator's `pyproject.toml` config.
**Warning signs:** `ruff: command not found` in CI logs.

### Pitfall 5: Web Tests Need Orchestrator Package
**What goes wrong:** `pytest web/tests/` fails with import errors because `web/server.py` imports from `orchestrator`.
**Why it happens:** The web server imports orchestrator modules (TTS client, whisper client, config, etc.).
**How to avoid:** Install the orchestrator package before running web tests. The CI step order should install orchestrator deps first, then web deps.
**Warning signs:** `ModuleNotFoundError: No module named 'orchestrator'` in web test output.

### Pitfall 6: paths: Trigger Missing Workflow File Changes
**What goes wrong:** Workflow changes don't trigger their own workflow for testing.
**Why it happens:** The `paths:` filter only lists source code paths, not the workflow files themselves.
**How to avoid:** Add the workflow file itself to the `paths:` trigger: e.g., `.github/workflows/python-ci.yml` in the Python CI paths list. This lets you test workflow changes.
**Warning signs:** PR that only modifies a workflow file shows no CI checks.

## Code Examples

### Ruff Lint Across All Python Directories
```bash
# Install ruff (comes with orchestrator[test] deps, but install explicitly for clarity)
pip install ruff

# Check all Python dirs using orchestrator's ruff config
ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml
ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml
```

### Running Tests Per-Project
```bash
# Orchestrator (excludes integration by default via addopts = "-m 'not integration'")
cd orchestrator && pytest

# Telemetry service
cd telemetry-service && pytest

# Web server (needs orchestrator installed as dependency)
pytest web/tests/

# Integration (requires Docker services running)
cd orchestrator && pytest -m integration
```

### .NET Test Project Build and Run
```bash
# Build ONLY the test project (not the main project which needs SimConnect SDK)
dotnet build adapters/msfs/SimConnectBridge.Tests/SimConnectBridge.Tests.csproj --configuration Release

# Run tests
dotnet test adapters/msfs/SimConnectBridge.Tests/SimConnectBridge.Tests.csproj --configuration Release --no-build
```

### Docker Compose Validation and Build
```bash
# Validate compose file syntax (catches YAML errors, missing references)
docker compose config --quiet

# Build all service images without starting containers
docker compose build
```

### Integration Test Service Startup
```bash
# Use dev overlay for tiny Whisper model
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d whisper chromadb

# Wait for Whisper (port 9090 on host)
timeout 120 bash -c 'until curl -sf http://localhost:9090/health; do sleep 5; done'

# Wait for ChromaDB (port 8000 on host)
timeout 30 bash -c 'until curl -sf http://localhost:8000/api/v1/heartbeat; do sleep 2; done'
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `docker-compose` (v1) | `docker compose` (v2 plugin) | 2023 | v1 is deprecated; ubuntu-latest has v2 pre-installed |
| `actions/setup-python@v4` | `actions/setup-python@v5` | 2024 | v5 adds better caching; v6 exists but requires newer runners |
| Manual pip caching via `actions/cache` | `setup-python` built-in `cache: 'pip'` | 2023 | Simpler config, automatic cache key generation |
| `dorny/paths-filter` for path filtering | Native `paths:` triggers | Always available | Native is sufficient for separate workflow files; dorny adds value only for conditional jobs within one workflow |

## Open Questions

1. **Whisper health endpoint path**
   - What we know: The `docker-compose.yml` health check uses a Python script hitting `http://localhost:8000/health`. From the host, Whisper is on port 9090.
   - What's unclear: Whether the health endpoint is `/health` or something else (e.g., `/v1/models`).
   - Recommendation: Use `/health` based on the existing compose healthcheck. If it fails, try `curl http://localhost:9090/v1/models`.

2. **Integration test markers across projects**
   - What we know: Orchestrator uses `@pytest.mark.integration` with addopts excluding by default. Web's `pyproject.toml` also defines an `integration` marker.
   - What's unclear: Whether web server integration tests exist yet (Phase 5 may not be complete).
   - Recommendation: Integration job should run `pytest -m integration` in orchestrator only. Web integration tests can be added later without changing the workflow.

3. **Docker build context for orchestrator Dockerfile**
   - What we know: `orchestrator/Dockerfile` requires project root as build context (copies `web/`, `data/`, `orchestrator/`).
   - What's unclear: Nothing -- `docker compose build` handles this correctly via the compose file's `context: .` directive.
   - Recommendation: No action needed. `docker compose build` uses the contexts defined in `docker-compose.yml`.

## Sources

### Primary (HIGH confidence)
- Project source code: `SimConnectBridge.Tests.csproj` -- verified test project includes source files directly, no SimConnect dependency
- Project source code: `orchestrator/pyproject.toml` -- verified pytest markers and addopts config
- Project source code: `docker-compose.yml` / `docker-compose.dev.yml` -- verified port mappings and dev overlay config
- [GitHub - actions/setup-python](https://github.com/actions/setup-python) -- v5 stable, v6 available
- [GitHub - actions/setup-dotnet](https://github.com/actions/setup-dotnet) -- v4/v5 available
- [Docker Build GitHub Actions](https://docs.docker.com/build/ci/github-actions/) -- official Docker CI guidance

### Secondary (MEDIUM confidence)
- [GitHub Actions Docker Compose discussion](https://github.com/orgs/community/discussions/27185) -- docker compose v2 pre-installed on ubuntu-latest
- [GitHub Actions building and testing Python](https://docs.github.com/actions/guides/building-and-testing-python) -- official Python CI guide
- [GitHub Actions building and testing .NET](https://docs.github.com/en/actions/automating-builds-and-tests/building-and-testing-net) -- official .NET CI guide

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - using only official GHA actions with verified versions
- Architecture: HIGH - three separate workflows map directly to user decisions; SimConnect workaround verified by reading test project source
- Pitfalls: HIGH - all pitfalls identified from actual project source code analysis (port mappings, dependency chains, SDK requirements)

**Research date:** 2026-03-26
**Valid until:** 2026-06-26 (GHA actions are stable; project structure unlikely to change during this milestone)
