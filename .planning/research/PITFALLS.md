# Domain Pitfalls

**Domain:** Consolidation/quality milestone for a real-time voice AI co-pilot (FastAPI + WebSocket + streaming TTS)
**Researched:** 2026-03-26

## Critical Pitfalls

Mistakes that cause regressions, broken user experience, or require a second refactoring pass.

### Pitfall 1: Refactoring Barge-In Without a Safety Net

**What goes wrong:** The barge-in cancellation system (`web/server.py` lines 519-635) coordinates task cancellation, event signaling, and WebSocket message ordering across three nested async contexts. Refactoring the web server's global state into DI or wiring in the TTS abstraction layer touches every code path involved. A subtle change to task lifecycle or event ordering leaves orphaned TTS WebSocket connections, sends messages to closed browser WebSockets, or silently drops interruptions.

**Why it happens:** Barge-in is the intersection of every async subsystem -- Claude streaming, TTS WebSocket, and browser WebSocket -- and has zero test coverage. Developers assume they can refactor "just the state management" without affecting the cancellation flow, but `_cancel_active_response()` uses nonlocal closures over `active_response_task` and `interrupt_event`, which are tightly coupled to the current global-state architecture.

**Consequences:** Users experience frozen responses, audio that continues playing after interruption, or WebSocket disconnections mid-conversation. These bugs are intermittent and timing-dependent, making them extremely hard to reproduce.

**Prevention:**
1. Write characterization tests for the barge-in flow *before* refactoring. Use FastAPI `TestClient` with WebSocket to verify: (a) sending text during active response cancels it, (b) sending audio_start during active response cancels it, (c) `interrupted` message is sent to client, (d) no messages sent after WebSocket disconnect.
2. Refactor in two steps: first extract the barge-in state machine into its own class with explicit state transitions, then wire it into DI. Do not combine these changes.
3. Keep a manual smoke-test script that exercises interrupt timing until automated tests exist.

**Detection:** Users report audio continuing after they start speaking. Logs show "TTS WS receive error" or "Chat WebSocket error" during normal usage. Orphaned ElevenLabs WebSocket connections accumulate (visible in ElevenLabs dashboard usage).

**Phase relevance:** Web server refactor phase. This is the single highest-risk change in the milestone.

---

### Pitfall 2: TTS Abstraction Breaks Streaming Latency

**What goes wrong:** The existing `TTSClient` protocol (`tts/base.py`) defines `synthesize()` and `synthesize_stream()`, both accepting complete text. But the web server's actual TTS path uses ElevenLabs' *WebSocket streaming API* (`_tts_websocket_stream`), which accepts text chunks incrementally as Claude generates them. The abstraction does not model this incremental-input pattern. Wiring the abstraction into the web server means either (a) falling back to per-sentence REST calls (adding 200-500ms latency per sentence) or (b) bolting WebSocket streaming onto the protocol after the fact.

**Why it happens:** The TTS abstraction was designed for the simpler "text in, audio out" use case. The web server's streaming TTS path is more sophisticated: it opens one WebSocket connection per response, feeds text chunks from an `asyncio.Queue`, and receives audio chunks concurrently. This is fundamentally different from "call synthesize_stream with complete text."

**Consequences:** Switching to the abstraction layer without extending it increases time-to-first-audio by 200-500ms per sentence. Users perceive MERLIN as slower and less responsive. Alternatively, extending the protocol mid-milestone adds scope and delays.

**Prevention:**
1. Before integration, audit the web server's `_tts_websocket_stream` and the CLI's `VoiceOutput._synthesize` to catalog every TTS interaction pattern actually used.
2. Extend the `TTSClient` protocol to include an incremental streaming method (e.g., `stream_session()` that returns an async context manager accepting text chunks) before wiring it in.
3. Benchmark time-to-first-audio before and after the switch. Set a regression threshold (e.g., no more than 50ms increase).

**Detection:** Measure time between sending a message and hearing the first syllable of MERLIN's response. If this increases noticeably after TTS integration, the abstraction is adding latency.

**Phase relevance:** TTS integration phase. Must be resolved before wiring the abstraction into the web server.

---

### Pitfall 3: Testing WebSockets Causes Test Hangs and Flaky Suites

**What goes wrong:** FastAPI's `TestClient.websocket_connect()` is synchronous and blocking. Tests that interact with the chat WebSocket (which runs an infinite `while True` loop) hang if the test doesn't explicitly close the connection or if the server-side handler raises an unexpected exception. Barge-in tests involving `asyncio.create_task` and `asyncio.Event` are timing-dependent and flake on CI runners with variable CPU load.

**Why it happens:** WebSocket endpoints are inherently stateful and long-lived, unlike REST endpoints. The Starlette `TestClient` runs the ASGI app in a background thread, so async race conditions manifest differently than in production. Teams write their first few WebSocket tests, get bitten by hangs, and either (a) add aggressive timeouts that cause flaky failures on slow CI, or (b) give up and skip WebSocket testing entirely.

**Consequences:** Test suite takes minutes to complete (or hangs indefinitely), CI becomes unreliable, team loses confidence in tests and stops running them.

**Prevention:**
1. Use `pytest-timeout` with a per-test timeout (e.g., 10 seconds) to prevent hangs from blocking the entire suite.
2. Structure WebSocket tests as short conversations: connect, send message, assert response, disconnect. Do not try to test the full infinite loop.
3. For barge-in tests, use explicit `asyncio.Event` synchronization rather than `asyncio.sleep()` timing. Mock the Claude client to return immediate responses.
4. Run WebSocket tests in a separate pytest marker (`@pytest.mark.websocket`) so they can be excluded during rapid iteration and included in CI.

**Detection:** CI runs take more than 60 seconds for the web test suite, or the same test passes/fails inconsistently across runs.

**Phase relevance:** Web server test coverage phase. Must establish patterns early; do not defer WebSocket test infrastructure to the end.

---

### Pitfall 4: Consolidating Whisper Logic Changes Transcription Behavior

**What goes wrong:** The three Whisper transcription implementations (`whisper_client.py`, `voice.py`, `web/server.py`) have *different* confidence calculations, retry logic, and error handling. Consolidating into one client seems straightforward, but each consumer relies on subtly different behavior. The CLI voice module expects synchronous blocking calls. The web server expects async with specific error recovery. The standalone `WhisperClient` has retry logic that the others lack.

**Why it happens:** The three implementations diverged organically as each consumer's needs evolved. The confidence scoring in `web/server.py` may weight segments differently than `whisper_client.py`. Picking one implementation as "the right one" and replacing the others silently changes transcription quality or error handling for the affected consumers.

**Consequences:** Transcription accuracy regresses in one mode (CLI vs web) without anyone noticing until a user reports it. Or error handling changes cause crashes on Whisper service unavailability that previously degraded gracefully.

**Prevention:**
1. Before consolidating, write comparison tests: feed the same audio fixtures through all three implementations and document the differences in confidence scores, transcribed text, and error behavior.
2. Consolidate incrementally: first make the async client, wire it into the web server, verify behavior parity, then wire into the CLI voice module.
3. Preserve the retry logic from `WhisperClient` in the consolidated version -- it exists for a reason (Whisper service can be slow to respond under load).
4. Add a `--whisper-test` CLI flag or integration test that transcribes known aviation phrases and asserts confidence thresholds.

**Detection:** Users report worse transcription in one mode. Logs show more "Low confidence" warnings after consolidation. Whisper errors that previously retried now surface as user-visible failures.

**Phase relevance:** Whisper consolidation phase. Should be done before or independently of the web server refactor to limit the blast radius of changes.

## Moderate Pitfalls

### Pitfall 5: Global State Extraction Breaks Lifespan Initialization Order

**What goes wrong:** The web server initializes `sim_client`, `claude_client`, `context_store`, and `phase_detector` in the `lifespan` async context manager. Moving these into `app.state` or a DI container changes when and how they are created. If the initialization order changes (e.g., `context_store` before `settings` is fully loaded, or `claude_client` before `context_store` is ready), startup fails silently or components get `None` dependencies.

**Why it happens:** Global variables with `lifespan` initialization have an implicit ordering guarantee -- the code runs top-to-bottom. DI containers and `app.state` assignments can obscure this ordering. FastAPI's `Depends()` system evaluates dependencies lazily on first request, not at startup, which can cause "works in dev, breaks in production" if the first request exercises an uninitialized dependency.

**Prevention:**
1. Keep all initialization in the `lifespan` context manager -- do not split initialization between lifespan and `Depends()`.
2. Create an `AppState` dataclass that holds all shared state, instantiate it fully in lifespan, and assign it to `app.state.app_state`. This preserves explicit ordering while eliminating globals.
3. Add a startup assertion that all required fields on `AppState` are non-None before accepting requests.

**Detection:** Server starts successfully but first request raises `AttributeError: 'NoneType' has no attribute...` for a component that was not initialized.

**Phase relevance:** Web server refactor phase.

---

### Pitfall 6: CI Pipeline Runs Everything on Every Change

**What goes wrong:** A naive GitHub Actions workflow runs Python lint, Python tests, C# build, C# tests, and Docker builds on every push. With no change detection, a one-line fix to the MSFS adapter triggers a full Python test suite (including slow integration tests) and Docker builds. CI takes 10+ minutes and developers stop waiting for it.

**Why it happens:** Multi-language monorepos need path-based filtering, but teams often start with a single workflow file and add filtering "later." By the time CI is slow enough to be painful, the team has already formed the habit of ignoring CI results.

**Consequences:** Slow CI reduces developer velocity. Developers merge without waiting for CI, defeating its purpose.

**Prevention:**
1. Use `paths` filters in GitHub Actions from day one: separate jobs for `orchestrator/**`, `web/**`, `telemetry-service/**`, `adapters/msfs/**`.
2. Use `dorny/paths-filter` action for conditional job execution within a single workflow.
3. Keep a "quick" job (lint + unit tests, under 3 minutes) that always runs, and a "full" job (integration tests + Docker builds) that runs only on PRs to main or when relevant paths change.
4. Pin runner images (`ubuntu-22.04`, not `ubuntu-latest`) to avoid surprise breakage from runner updates.

**Detection:** Developers routinely merge PRs before CI completes. Average CI time exceeds 5 minutes for non-Docker changes.

**Phase relevance:** CI/CD phase.

---

### Pitfall 7: Docker Version Pins Create a False Sense of Security

**What goes wrong:** Pinning `fedirz/faster-whisper-server` and `chromadb/chroma` to specific tags prevents surprise breakage, but third-party community images can be deleted, re-tagged, or abandoned. The `faster-whisper-server` image is maintained by an individual, not an organization. Six months from now, the pinned tag may not exist.

**Why it happens:** Teams pin versions and consider the problem solved. They do not set up Dependabot or manual review processes for Docker image updates, so pinned versions become stale and eventually vulnerable or broken.

**Prevention:**
1. Pin to specific version tags (not `:latest`) as planned, but also document the image source and maintainer in `docker-compose.yml` comments.
2. Add a quarterly calendar reminder to check for new versions of third-party images.
3. Consider building a minimal Whisper service image from `faster-whisper` directly (it is a pip-installable package) to reduce dependency on a community Docker image.
4. For ChromaDB, pin in `pyproject.toml` AND in the Docker image tag.

**Detection:** Docker builds fail with "image not found" errors. Or the Whisper service starts returning different API responses after a rebuild pulls a cached-but-updated layer.

**Phase relevance:** Housekeeping phase (version pinning).

---

### Pitfall 8: Refactoring and Bug Fixing in the Same Commit

**What goes wrong:** The consolidation milestone includes both refactoring (global state to DI, Whisper consolidation, TTS integration) and bug fixes (race condition in telemetry consumer list, TTS voice setting inconsistencies). Mixing refactoring and bug fixes in the same commits makes it impossible to determine whether a regression came from the refactor or the fix.

**Why it happens:** When you are already touching a file for refactoring, it is tempting to fix the bug you see right there. Both changes ship together, and when something breaks, `git bisect` points to a commit that changed 15 files for two different reasons.

**Prevention:**
1. Fix known bugs (telemetry race condition, voice setting inconsistencies) in a separate phase *before* refactoring. This establishes a known-good baseline.
2. Each commit should be either a refactor (no behavior change) or a fix (behavior change), never both.
3. The roadmap should place housekeeping/bug fixes in Phase 1, before structural refactoring begins.

**Detection:** A regression appears and the team cannot determine which of several interleaved changes caused it.

**Phase relevance:** All phases, but especially critical to enforce in the web server refactor phase.

## Minor Pitfalls

### Pitfall 9: TTS Cache Invalidation After Voice Settings Change

**What goes wrong:** The web server has a `_TTS_CACHE` dict that caches common TTS phrases at startup. When voice settings are consolidated into config (fixing the hardcoded inconsistencies), the cache entries were generated with the old settings. If settings change between restarts, cached audio sounds different from freshly synthesized audio.

**Prevention:** Invalidate the TTS cache when voice settings change, or include a hash of voice settings in the cache key. Better yet, regenerate the cache at startup using the current settings (which is already the behavior -- just ensure it stays that way after refactoring).

**Phase relevance:** TTS integration phase.

---

### Pitfall 10: Python Version Standardization Breaks Dependencies

**What goes wrong:** Standardizing from mixed 3.11/3.12 to a single version can break dependencies that have version-specific wheels or behavior. ChromaDB in particular has had issues with specific Python versions.

**Prevention:** Test `pip install` of all dependencies in the target Python version's Docker image before committing to the version change. Run the full test suite in a container with the standardized version.

**Phase relevance:** Housekeeping phase.

---

### Pitfall 11: Removing Deprecated Config Without Updating All Consumers

**What goes wrong:** Removing `simconnect_ws_host`, `simconnect_ws_port`, and the `SimConnectClient` alias from config/code breaks anyone who has these in their `.env` file or references them in scripts. Pydantic-settings raises a validation error on unknown fields by default only if `extra = "forbid"` is set; otherwise the removal is silent but the `docker-compose.yml` still sets `SIMCONNECT_BRIDGE_URL`.

**Prevention:** Search the entire codebase (including `docker-compose.yml`, `.env.example`, documentation, and any scripts in `tools/`) for references to the deprecated names before removing them. Check pydantic's `extra` setting behavior for the `Settings` class.

**Phase relevance:** Housekeeping phase (deprecated config removal).

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Housekeeping (version pins, deprecated config) | Removing config breaks `.env` files or docker-compose | Search all files for deprecated names before removal |
| Whisper consolidation | Behavior divergence between three implementations | Write comparison tests before consolidating |
| TTS integration | Abstraction does not model WebSocket streaming pattern | Extend protocol before wiring; benchmark latency |
| Web server refactor (global state to DI) | Breaks barge-in cancellation flow | Characterization tests first; extract barge-in state machine separately |
| Web server test coverage | WebSocket tests hang or flake | Use pytest-timeout; structure tests as short conversations |
| CI/CD pipeline | Runs everything on every change; slow CI gets ignored | Path-based filtering from day one; separate quick/full jobs |
| All phases | Mixing refactoring and bug fixes | Bugs first (Phase 1), refactoring second; never in same commit |

## Sources

- [FastAPI Dependency Injection Discussion #8968](https://github.com/fastapi/fastapi/discussions/8968) -- Global state vs DI patterns
- [FastAPI Dependencies Documentation](https://fastapi.tiangolo.com/tutorial/dependencies/) -- Official DI guidance
- [Production-Ready FastAPI Project Structure (2026)](https://dev.to/thesius_code_7a136ae718b7/production-ready-fastapi-project-structure-2026-guide-b1g) -- app.state patterns
- [FastAPI Testing WebSockets](https://fastapi.tiangolo.com/advanced/testing-websockets/) -- Official WebSocket test patterns
- [FastAPI WebSocket test hang issue #2637](https://github.com/fastapi/fastapi/issues/2637) -- Known TestClient WebSocket hang
- [GitHub Actions Monorepo CI/CD (2026)](https://dev.to/pockit_tools/github-actions-in-2026-the-complete-guide-to-monorepo-cicd-and-self-hosted-runners-1jop) -- Path filtering, change detection
- [Monorepo CI/CD with GitHub Actions](https://generalreasoning.com/blog/2025/03/22/github-actions-vanilla-monorepo.html) -- Vanilla monorepo patterns
- [6 Refactoring Mistakes That Introduce Bugs (2026)](https://medium.com/@ujjawalr/6-refactoring-mistakes-that-introduce-bugs-8b0a4987edb0) -- Refactoring anti-patterns
- [Code Refactoring Best Practices](https://www.techtarget.com/searchsoftwarequality/tip/When-and-how-to-refactor-code) -- Separate refactoring from debugging
- Direct codebase analysis: `web/server.py`, `orchestrator/orchestrator/tts/`, `orchestrator/orchestrator/voice.py`, `orchestrator/orchestrator/whisper_client.py`

---

*Concerns audit: 2026-03-26*
