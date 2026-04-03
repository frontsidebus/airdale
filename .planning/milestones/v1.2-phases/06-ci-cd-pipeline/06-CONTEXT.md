# Phase 6: CI/CD Pipeline - Context

**Gathered:** 2026-03-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Create GitHub Actions CI/CD workflows that automatically run lint, tests, and Docker build verification on every PR. Three separate workflow files with path-based filtering. Full integration testing with Docker services (Whisper + ChromaDB) on PRs.

</domain>

<decisions>
## Implementation Decisions

### Workflow Structure
- **D-01:** Three separate GHA workflow files:
  - `.github/workflows/python-ci.yml` — ruff lint + pytest for orchestrator, telemetry-service, and web server tests
  - `.github/workflows/dotnet-ci.yml` — dotnet test for MSFS adapter
  - `.github/workflows/docker-ci.yml` — Docker build verification (docker compose build)
- **D-02:** Path-based filtering using `paths:` in workflow `on:` triggers so only relevant workflows run on each PR.
- **D-03:** Python CI triggers on changes to `orchestrator/**`, `telemetry-service/**`, `web/**`, `*.py`
- **D-04:** .NET CI triggers on changes to `adapters/msfs/**`
- **D-05:** Docker CI triggers on changes to `**/Dockerfile`, `docker-compose*.yml`, `.dockerignore`

### Python CI — Two Jobs
- **D-06:** **Job 1: lint-and-test (every push + PR):** ruff check + ruff format --check across all Python dirs. pytest for orchestrator, telemetry-service, and web/tests (fast mock tests only). Runs on ubuntu-latest with Python 3.12.
- **D-07:** **Job 2: integration (PRs only):** Spins up Whisper + ChromaDB via docker-compose. Runs `pytest -m integration` for integration tests that need real services. Uses `services:` or `docker compose up` in the job.
- **D-08:** Use the Whisper `tiny` model in CI integration tests (fast startup, matches dev mode).

### .NET CI
- **D-09:** Run `dotnet build` and `dotnet test` on ubuntu-latest with .NET 8.0. SimConnect SDK won't be available on Linux runners — tests that require it should be skipped or mocked (existing xUnit tests already handle this).

### Docker CI
- **D-10:** Run `docker compose build` to verify all Dockerfiles build successfully. Don't start containers — just build.
- **D-11:** Use `docker compose config` to validate YAML before building.

### Branch Protection
- **D-12:** No branch protection rules for now. Set up manually later if needed. The workflows exist and report status — enforcement is a manual step.

### Claude's Discretion
- GHA runner versions (ubuntu-latest vs pinned)
- Cache strategy for pip/docker layers
- Whether to use `dorny/paths-filter` action or native `paths:` triggers
- Exact pytest markers and integration test fixtures

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Test Suites (what CI runs)
- `orchestrator/pyproject.toml` — pytest config, markers, ruff settings
- `telemetry-service/pyproject.toml` — pytest config
- `web/pyproject.toml` — pytest config for web server tests
- `web/tests/` — 33 web server tests (fast mock tier)
- `orchestrator/tests/` — Orchestrator tests
- `telemetry-service/tests/` — Telemetry service tests
- `adapters/msfs/SimConnectBridge.Tests/` — xUnit tests

### Docker Build Targets
- `orchestrator/Dockerfile` — Build context: project root
- `telemetry-service/Dockerfile` — Build context: ./telemetry-service
- `docker-compose.yml` — Production service stack
- `docker-compose.dev.yml` — Dev overrides (tiny Whisper model)

### Phase 5 Decisions (test tiers)
- D-05/D-06/D-07 from Phase 5: Tier 1 fast mocks (default), Tier 2 integration with `@pytest.mark.integration`

</canonical_refs>

<code_context>
## Existing Code Insights

### Current Test Commands
- Orchestrator: `cd orchestrator && pytest` (excludes integration by default via addopts)
- Telemetry: `cd telemetry-service && pytest`
- Web: `pytest web/tests/`
- C#: `cd adapters/msfs && dotnet test`
- Lint: `cd orchestrator && ruff check . && ruff format --check .`

### No Existing CI
- Zero `.github/workflows/` files exist
- No Jenkinsfile, no GitLab CI, no CI of any kind

### Docker Compose Services
- `whisper` — `fedirz/faster-whisper-server:0.5-cpu`
- `chromadb` — `chromadb/chroma:1.5.5`
- `telemetry-service` — built from `./telemetry-service`
- `orchestrator` — built from project root (`orchestrator/Dockerfile`)

</code_context>

<specifics>
## Specific Ideas

- Integration test job should use `docker-compose.dev.yml` overlay to get the `tiny` Whisper model (fast CI startup)
- SimConnect DLL won't be on Linux CI runners — .NET tests already mock it, but `dotnet build` may need the SDK reference skipped or stubbed

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 06-ci-cd-pipeline*
*Context gathered: 2026-03-28*
