# Phase 4: Web Server Refactor - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 04-web-server-refactor
**Areas discussed:** State container design, Barge-in preservation, Bridge connection tracking, Scope of refactor

---

## State Container Design

| Option | Description | Selected |
|--------|-------------|----------|
| Single AppState dataclass (Recommended) | One @dataclass with all mutable state as typed fields. Clean, type-safe, easy to mock. | ✓ |
| Individual app.state attributes | app.state.sim_client, etc. Simpler but no type safety. | |
| You decide | Claude's discretion | |

**User's choice:** Single AppState dataclass

---

## Barge-in Preservation Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal touch (Recommended) | Pass AppState as parameter. Don't restructure cancellation logic. | ✓ |
| Extract to ChatSession class | Cleaner but higher regression risk. | |
| You decide | Claude's discretion | |

**User's choice:** Minimal touch

---

## Bridge Connection Tracking

| Option | Description | Selected |
|--------|-------------|----------|
| Simple attrs on AppState (Recommended) | Move bools/float to AppState fields. No lock — asyncio is single-threaded. | ✓ |
| Dedicated ConnectionTracker | Encapsulated class with update()/is_alive(). | |
| You decide | Claude's discretion | |

**User's choice:** Simple attrs on AppState

---

## Scope of Refactor

| Option | Description | Selected |
|--------|-------------|----------|
| Full DI for route handlers (Recommended) | Every route gets AppState via Depends(). Internal helpers via parameter. No globals. | ✓ |
| Hybrid: app.state + Depends for tests | Direct access, Depends only for mocking. | |
| You decide | Claude's discretion | |

**User's choice:** Full DI

---

## Claude's Discretion

- dataclass vs attrs (standard is dataclass)
- Type narrowing approach for Optional fields
- Whether settings stays module-level or moves into AppState

## Deferred Ideas

None — discussion stayed within phase scope.
