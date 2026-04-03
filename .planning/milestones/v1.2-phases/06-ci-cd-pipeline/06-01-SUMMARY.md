---
phase: 06-ci-cd-pipeline
plan: 01
subsystem: infra
tags: [github-actions, ci, ruff, pytest, docker-compose]

requires:
  - phase: 05-web-server-tests
    provides: pytest test suites for orchestrator, telemetry-service, and web
provides:
  - Python CI workflow with ruff lint and pytest across all Python projects
  - Integration test job with Whisper and ChromaDB Docker services on PRs
affects: [06-02-PLAN]

tech-stack:
  added: [github-actions, actions/checkout@v4, actions/setup-python@v5]
  patterns: [path-based-triggers, pip-caching, docker-compose-in-ci]

key-files:
  created:
    - .github/workflows/python-ci.yml
  modified: []

key-decisions:
  - "Skipped web pip install -e .[dev] since web has no pyproject.toml; install requirements.txt only"
  - "Web tests step uses conditional (hashFiles check) since web/tests/ may not exist yet"

patterns-established:
  - "Path-based CI triggers: only run Python CI when Python-related files change"
  - "Two-job structure: fast lint-and-test on every push/PR, integration with Docker services on PRs only"

requirements-completed: [CICD-01, CICD-02, CICD-03, CICD-06, CICD-07]

duration: 1min
completed: 2026-03-28
---

# Phase 06 Plan 01: Python CI Summary

**GitHub Actions Python CI with ruff lint, pytest for orchestrator/telemetry-service/web, and Docker-based integration tests on PRs**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-28T22:14:57Z
- **Completed:** 2026-03-28T22:15:40Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Created Python CI workflow with path-based triggers for orchestrator, telemetry-service, web, and the workflow file itself
- Ruff lint and format check across all Python directories using orchestrator's ruff config
- Pytest runs for orchestrator and telemetry-service unit tests
- Integration job with Whisper (tiny model via dev overlay) and ChromaDB Docker services, gated to PRs only
- pip caching with multi-file dependency path for faster CI runs

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Python CI workflow with lint-and-test job** - `4d6db8d` (feat)

## Files Created/Modified
- `.github/workflows/python-ci.yml` - Python CI workflow with lint-and-test + integration jobs

## Decisions Made
- Skipped `pip install -e ".[dev]"` for web since it has no pyproject.toml; only `pip install -r web/requirements.txt` is run
- Web tests step is conditional via `hashFiles` since `web/tests/` directory may not exist yet
- Used orchestrator's `pyproject.toml` as the shared ruff config for all Python directories

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Adjusted web dependency installation**
- **Found during:** Task 1
- **Issue:** Plan specified `cd web && pip install -e ".[dev]"` but web has no pyproject.toml
- **Fix:** Only install `pip install -r web/requirements.txt` for web; skip editable install
- **Files modified:** .github/workflows/python-ci.yml
- **Verification:** YAML validates successfully
- **Committed in:** 4d6db8d

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary adaptation since web lacks pyproject.toml. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Python CI workflow ready; will trigger on next PR touching Python files
- Ready for 06-02 (C#/.NET CI workflow)

---
*Phase: 06-ci-cd-pipeline*
*Completed: 2026-03-28*
