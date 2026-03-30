---
phase: 01-housekeeping
plan: 01
subsystem: config
tags: [pydantic-settings, cleanup, deprecation-removal]

# Dependency graph
requires: []
provides:
  - Clean Settings class without deprecated SimConnect fields
  - Clean docker-compose.yml without legacy SIMCONNECT_BRIDGE_URL
  - Updated documentation referencing TelemetryClient instead of SimConnectClient
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - orchestrator/orchestrator/config.py
    - orchestrator/orchestrator/sim_client.py
    - orchestrator/tests/test_config.py
    - orchestrator/tests/conftest.py
    - tests/integration/test_orchestrator_e2e.py
    - docker-compose.yml
    - .env.example
    - docs/API.md
    - docs/ARCHITECTURE.md

key-decisions:
  - "Removed only the targeted deprecated config fields (simconnect_ws_host, simconnect_ws_port, simconnect_bridge_url, SimConnectClient alias); left legitimate SimConnect adapter references intact"

patterns-established: []

requirements-completed: [HSKP-01, HSKP-07]

# Metrics
duration: 3min
completed: 2026-03-27
---

# Phase 01 Plan 01: Remove Deprecated SimConnect Config Summary

**Removed all deprecated SimConnect config fields, backward-compat alias, and env var references from Python code, docker-compose, .env.example, and documentation**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-27T12:01:02Z
- **Completed:** 2026-03-27T12:03:34Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- Removed simconnect_ws_host, simconnect_ws_port, simconnect_bridge_url fields from Settings class
- Removed legacy bridge URL construction from _build_derived validator (kept telemetry_service_url logic)
- Removed SimConnectClient backward-compat alias from sim_client.py
- Removed deprecated tests and env var references from test suite
- Cleaned docker-compose.yml, .env.example, and docs

## Task Commits

Each task was committed atomically:

1. **Task 1: Remove deprecated SimConnect config fields and alias from Python code** - `5589216` (chore)
2. **Task 2: Remove deprecated references from config files and documentation** - `d58a02a` (chore)

## Files Created/Modified
- `orchestrator/orchestrator/config.py` - Removed 3 deprecated fields and legacy URL construction from validator
- `orchestrator/orchestrator/sim_client.py` - Removed SimConnectClient backward-compat alias
- `orchestrator/tests/test_config.py` - Removed 2 deprecated test methods
- `orchestrator/tests/conftest.py` - Removed SIMCONNECT_BRIDGE_URL from mock env vars
- `tests/integration/test_orchestrator_e2e.py` - Removed simconnect_bridge_url kwarg from Settings call
- `docker-compose.yml` - Removed SIMCONNECT_BRIDGE_URL env var from orchestrator service
- `.env.example` - Removed legacy SimConnect settings block
- `docs/API.md` - Removed SimConnect Bridge config table section
- `docs/ARCHITECTURE.md` - Replaced SimConnectClient with TelemetryClient in 2 locations

## Decisions Made
- Removed only the targeted deprecated config fields; legitimate SimConnect adapter references (health monitor subsystem name, test fixture names, adapter documentation) were left intact as they refer to the actual SimConnect adapter component, not the deprecated config

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Settings class is clean and ready for any future config additions
- No deprecated fields to confuse new developers or cause test fragility

---
*Phase: 01-housekeeping*
*Completed: 2026-03-27*
