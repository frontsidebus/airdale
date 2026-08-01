# Phase 5: Web Server Tests - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-28
**Phase:** 05-web-server-tests
**Areas discussed:** Test infrastructure, Coverage priority, Mock strategy

---

## Test Infrastructure

| Option | Description | Selected |
|--------|-------------|----------|
| web/tests/ (Recommended) | Dedicated test directory alongside server.py | ✓ |
| tests/web/ | Under root tests/ directory | |

| Option | Description | Selected |
|--------|-------------|----------|
| httpx + httpx-ws (Recommended) | Async-native WebSocket testing | ✓ |
| starlette TestClient | Sync-only, simpler | |

---

## Coverage Priority

| Option | Description | Selected |
|--------|-------------|----------|
| All equal priority | No special ordering, test all 7 equally | ✓ |
| Barge-in first | Prioritize highest-risk path | |

---

## Mock Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Mock everything via AppState (branch) + external only (PR) | Two-tier: fast mocks for commits, integration for PRs | ✓ |
| Mock everything always | Simplest but less confidence | |
| Mock external only | Deeper but needs Docker always | |

**User's choice:** Two-tier strategy — full mock for branch commits, real clients for PRs
**Notes:** Aligns with Phase 6 CI/CD where PR jobs can spin up Docker services.

---

## Claude's Discretion

- Test file organization
- Barge-in simulation approach
- Integration test Docker health checks

## Deferred Ideas

None.
