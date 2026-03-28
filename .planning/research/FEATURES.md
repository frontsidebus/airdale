# Feature Landscape

**Domain:** AI voice assistant codebase consolidation (v1.2 quality milestone)
**Researched:** 2026-03-26

## Table Stakes

Features users (and developers) expect from a well-maintained production voice AI codebase. Missing any of these means the codebase quality suffers and future development velocity degrades.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| TTS abstraction wired into all consumers | Existing protocol + two backends sit unused while inline httpx calls remain in web server and CLI. Industry consensus: "The TTS API you choose matters less than how cleanly you abstract over it." Provider lock-in and inconsistent voice output are unacceptable. | Medium | Protocol exists (`tts/base.py`). Work is integration, not design. Must replace inline calls in `voice.py` and `server.py`. |
| Unified Whisper client (async) | Three separate transcription implementations with subtle differences in confidence scoring and retry logic. Bug fixes must be applied in three places. Standard DRY violation. | Medium | Consolidate into single async client in `whisper_client.py`. Voice module and web server both consume it. |
| Consistent TTS voice settings from config | Voice settings hardcoded in 5+ locations with different values (`stability: 0.5` vs `0.75`). Users hear different voice quality between CLI and web modes. | Low | Add voice settings to `Settings` class. TTS backends read from config. |
| Web server DI / app.state refactor | Module-level globals with `global` statements in 5 places. FastAPI's own docs and community consensus (2025-2026): use `app.state` with lifespan context manager for shared singletons. Global state prevents testing, prevents multi-instance, creates implicit coupling. | Medium-High | Use `asynccontextmanager` lifespan to initialize clients, store on `app.state`, inject via `Depends()`. This is prerequisite for web server tests. |
| Web server test coverage | 1,057-line primary user-facing component with zero tests. This is the most critical gap. Industry standard for production Python: 75-85% coverage on business logic. WebSocket chat flow, barge-in, TTS streaming, transcription are all untested. | High | Requires DI refactor first (to make code testable). Use `TestClient` with `websocket_connect()` for WebSocket tests, `httpx.AsyncClient` for REST. |
| CI/CD pipeline (GitHub Actions) | 361+ tests exist but only run manually. No lint enforcement, no build verification on PRs. Any project with tests but no CI has a ticking regression bomb. This is non-negotiable for production quality. | Medium | Single workflow: ruff lint, pytest (Python), dotnet test (C#), Docker build verify. Use `actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-dotnet@v4`. |
| Deprecated config cleanup | Legacy `simconnect_ws_host`, `simconnect_ws_port`, backward-compat aliases confuse developers and add dead code. Clean config is table stakes for maintainability. | Low | Remove deprecated fields from `Settings`, remove `SimConnectClient` alias, clean docker-compose env vars. |
| Dependency version pinning | `chromadb>=0.5.0` with no upper bound, `faster-whisper-server:latest` Docker tag. Both have histories of breaking changes between versions. Unpinned dependencies in production are a reliability risk. | Low | Pin `chromadb>=0.5.0,<0.7.0`, pin Whisper server to specific tag, standardize Python version across Dockerfiles. |
| Telemetry consumer list race condition fix | `asyncio.Lock` needed for consumer list mutations. Race condition in production async code is a correctness bug. | Low | Add `asyncio.Lock` to `add_consumer`, `remove_consumer`, and broadcast iteration in `adapter_manager.py`. |

## Differentiators

Features that go beyond baseline quality expectations. Not required, but improve developer experience and long-term velocity.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Coverage threshold enforcement in CI | `pytest --cov --cov-fail-under=75` in the GitHub Actions workflow prevents coverage regression. Most Python CI pipelines (85% per JetBrains 2025 survey) enforce thresholds below 80%. Setting 75% as floor with critical-path focus is pragmatic. | Low | Add `pytest-cov` to dev dependencies. Configure in `pyproject.toml` and CI workflow. |
| TTS backend integration tests | Test that ElevenLabs and Kokoro backends satisfy the `TTSClient` protocol with actual synthesis calls (mocked HTTP). Validates the abstraction layer works end-to-end. | Medium | `test_tts_client.py` exists with 20 tests but backends are not wired in yet. Expand after integration. |
| Health/readiness endpoints on web server | `/health` and `/ready` endpoints for Docker orchestration. Not strictly needed for local use, but standard practice and costs almost nothing. | Low | Add to web server. Return subsystem status (telemetry connected, Claude API reachable, Whisper available). |
| Persistent HTTP clients in tools module | `tools.py` creates new `httpx.AsyncClient` per airport lookup. Persistent client eliminates redundant TCP/TLS handshakes. | Low | Accept shared client or use module-level singleton with lifespan management. |
| Pre-commit hooks (ruff + pytest) | Local quality gate before code reaches CI. Catches lint and test failures before push. | Low | `.pre-commit-config.yaml` with ruff and pytest hooks. |
| CORS restriction to localhost | Replace `allow_origins=["*"]` with `["http://localhost:3838", "http://127.0.0.1:3838"]` by default, with config override for custom origins. | Low | Security improvement that costs nothing. |
| Integration test schedule in CI | Run the 67 integration tests on a schedule (nightly) or on main merges, separate from the fast PR gate. Prevents silent rot. | Low | Add second GitHub Actions workflow or job triggered on `schedule` or `push` to main. |

## Anti-Features

Features to deliberately NOT build in this consolidation milestone. Each has been considered and rejected for stated reasons.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| New sim adapter support (X-Plane, DCS) | Architecture already supports it. Building adapters now would add surface area before the foundation is consolidated. | Keep adapter protocol stable. Defer to a dedicated future milestone. |
| Structured logging migration | Useful but not blocking anything. Adding `structlog` or `python-json-logger` touches every file and is best done after CI is enforcing quality. | Leave for post-v1.2 milestone. Current `logging` works. |
| Sentry / error tracking integration | Nice-to-have observability, but this is a local developer tool, not a SaaS product. Container logs suffice for now. | Out of scope per PROJECT.md. Revisit if user base grows. |
| Multi-backend STT abstraction | Whisper is the only STT backend and works well. Building an STT abstraction layer "for symmetry" with TTS is premature. | Keep single Whisper client. Abstract only if a second STT backend is needed. |
| WebSocket protocol changes | Telemetry service protocol must remain stable (adapters are out-of-process, potentially on different hosts). Any protocol change risks breaking the MSFS adapter. | Freeze protocol. Additive changes only if absolutely necessary. |
| Screen capture window targeting | Works "well enough" per PROJECT.md. Win32 window enumeration is platform-specific complexity for marginal improvement. | Leave as-is. Low priority. |
| Mobile app or multi-user auth | Local tool, single user. Adding auth adds complexity with no current user demand. | Web-first, single-user. |
| 100% test coverage target | Chasing 100% leads to brittle tests on implementation details. Focus coverage on critical paths: chat flow, TTS streaming, barge-in, telemetry pipeline. | Target 75% floor with emphasis on high-risk code paths. |
| Real-time / speech-to-speech architecture | The turn-based cascading STT/LLM/TTS architecture is correct for MERLIN's use case (cockpit comms are inherently turn-based with PTT). Speech-to-speech would add complexity without improving the interaction model. | Keep cascading architecture. |

## Feature Dependencies

```
Deprecated config cleanup -----> (independent, do first)
                                    |
Telemetry race condition fix --> (independent, do first)
                                    |
Dependency version pinning ----> (independent, do first)
                                    |
Consistent TTS voice settings -> TTS abstraction integration
                                    |
TTS abstraction integration ---> Web server DI refactor (web server needs DI to cleanly consume TTS client)
                                    |
Unified Whisper client --------> Web server DI refactor (web server needs DI to consume shared Whisper client)
                                    |
Web server DI refactor --------> Web server test coverage (must refactor before tests are meaningful)
                                    |
Web server test coverage ------> CI/CD pipeline (tests must exist before CI can enforce them)
                                    |
CI/CD pipeline ----------------> Coverage thresholds, integration test scheduling (CI must exist first)
```

Simplified critical path:
```
Config cleanup + Race fix + Pinning  (independent, parallel)
        |
TTS voice settings -> TTS integration -> Whisper consolidation  (sequential)
        |
Web server DI refactor -> Web server tests -> CI/CD pipeline  (sequential, critical path)
```

## MVP Recommendation

**Phase 1 -- Housekeeping (parallel, low-risk):**
1. Remove deprecated SimConnect config fields and aliases
2. Fix telemetry consumer list race condition
3. Pin dependency versions, standardize Python across Dockerfiles
4. Delete empty test file

**Phase 2 -- TTS integration + Whisper consolidation:**
1. Wire TTS abstraction into web server and CLI voice module
2. Consolidate voice settings into shared config
3. Consolidate Whisper client into single async implementation
4. Add persistent HTTP clients where missing

**Phase 3 -- Web server refactor + tests:**
1. Refactor web server globals into `app.state` with lifespan
2. Add test coverage for critical paths (chat, barge-in, TTS, transcription)
3. Add health/readiness endpoints
4. Restrict CORS to localhost

**Phase 4 -- CI/CD pipeline:**
1. GitHub Actions workflow: lint, test (Python + C#), Docker build
2. Coverage threshold enforcement (75% floor)
3. Integration test schedule (nightly or on main)
4. Pre-commit hooks

**Defer:** Structured logging, Sentry, new adapters, STT abstraction, screen capture targeting.

## Sources

- [The voice AI stack for building agents in 2026](https://www.assemblyai.com/blog/the-voice-ai-stack-for-building-agents) - TTS abstraction patterns
- [How to Choose STT and TTS for Voice Agents](https://softcery.com/lab/how-to-choose-stt-tts-for-ai-voice-agents-in-2025-a-comprehensive-guide) - Provider comparison and abstraction rationale
- [FastAPI Dependency Injection Discussion #8968](https://github.com/fastapi/fastapi/discussions/8968) - DI without global state patterns
- [Production-Ready FastAPI Project Structure 2026](https://dev.to/thesius_code_7a136ae718b7/production-ready-fastapi-project-structure-2026-guide-b1g) - Lifespan context manager pattern
- [FastAPI Testing WebSockets Tutorial](https://www.getorchestra.io/guides/fast-api-testing-websockets-a-detailed-tutorial-with-python-code-examples) - WebSocket test patterns
- [Coverage.py PyTest Plugin: Threshold Enforcement in CI 2026](https://johal.in/coverage-py-pytest-plugin-threshold-enforcement-in-ci-2026/) - Coverage threshold enforcement
- [GitHub Actions Complete Guide 2026](https://dev.to/_d7eb1c1703182e3ce1782/github-actions-complete-guide-build-your-first-cicd-pipeline-in-2026-6m6) - CI/CD pipeline structure
- [Automated Python Unit Testing with Pytest and GitHub Actions](https://pytest-with-eric.com/integrations/pytest-github-actions/) - pytest CI patterns

---

*Feature landscape audit: 2026-03-26*
