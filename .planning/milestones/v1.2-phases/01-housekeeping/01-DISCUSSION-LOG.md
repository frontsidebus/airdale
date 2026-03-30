# Phase 1: Housekeeping - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 01-housekeeping
**Areas discussed:** Deprecated config removal, Python version standardization, Docker image pinning, Race condition fix approach

---

## Deprecated Config Removal

| Option | Description | Selected |
|--------|-------------|----------|
| Full cleanup (Recommended) | Remove fields from Settings, alias from sim_client.py, env var from docker-compose.yml, references from .env.example, docs/API.md, test fixtures, and conftest.py | ✓ |
| Code only | Remove from Settings and sim_client.py only. Leave docs and test fixtures for a separate pass | |
| You decide | Claude's discretion on scope | |

**User's choice:** Full cleanup
**Notes:** None — straightforward decision.

---

## Python Version Standardization

| Option | Description | Selected |
|--------|-------------|----------|
| 3.12-slim (Recommended) | Already used by orchestrator. Faster startup, better error messages, newer features. Both pyproject.toml files require >=3.11 so 3.12 is compatible. | ✓ |
| 3.11-slim | Conservative choice. Matches the minimum spec in pyproject.toml. Slightly smaller image. | |
| 3.13-slim | Latest stable. Free-threaded mode, improved error messages. May have fewer pre-built wheels for some deps. | |

**User's choice:** 3.12-slim
**Notes:** None — aligns with existing orchestrator Dockerfile.

---

## Docker Image Pinning

| Option | Description | Selected |
|--------|-------------|----------|
| Exact version tags (Recommended) | e.g., chromadb/chroma:0.5.23. Maximum reproducibility. Requires manual bumps. | |
| Minor-range tags | e.g., chromadb/chroma:0.5. Gets patch updates automatically but may break on minor changes. | ✓ |
| SHA digest pins | Pin by image digest. Most stable but hardest to read/update. | |

**User's choice:** Minor-range tags
**Notes:** User preferred automatic patch updates over maximum reproducibility.

---

## Race Condition Fix Approach

| Option | Description | Selected |
|--------|-------------|----------|
| asyncio.Lock (Recommended) | Wrap add_consumer, remove_consumer, and _broadcast_to_consumers with a single asyncio.Lock. Simple, correct, low risk. | ✓ |
| Copy-on-write snapshot | Take a snapshot of the consumer list before broadcast. Avoids holding lock during I/O. More complex. | |
| You decide | Claude's discretion on the approach | |

**User's choice:** asyncio.Lock
**Notes:** None — simple and correct for this use case.

---

## Claude's Discretion

- Exact minor version numbers for Docker image pins
- Whether to update pyproject.toml requires-python
- How to handle deprecated env var in docs/API.md

## Deferred Ideas

None — discussion stayed within phase scope.
