---
phase: 05
phase_name: "Web Server Tests"
project: "MERLIN — Airdale"
generated: "2026-07-29"
counts:
  decisions: 11
  lessons: 10
  patterns: 9
  surprises: 6
missing_artifacts:
  - "05-VERIFICATION.md"
  - "05-UAT.md"
---

# Phase 05 Learnings: Web Server Tests

## Decisions

### Monkeypatch `web.server` module attributes instead of using `dependency_overrides`
`conftest.py` sets module attributes directly, with `dependency_overrides` retained only "as a fallback if DI functions exist."

**Rationale:** The executor recorded that "web/server.py uses module-level globals without FastAPI dependency injection" and that "the plan assumed get_app_state/get_ws_app_state DI functions from Phase 04, but the actual server architecture uses module globals directly." Logged as a Rule 3 blocking deviation. This is the mechanism that shipped, and the one the milestone later deferred — see Surprises.
**Source:** 05-01-SUMMARY.md, .planning/STATE.md

### A `MockAppState` dataclass mirrors the server's state surface
One dataclass with a `MagicMock`/`AsyncMock` field per subsystem: `settings` (with explicit attribute values, not bare mock attributes), `whisper_client`, `claude_client`, `tts_client`, `sim_client`, `context_store`, and an empty `tts_cache` dict for tests to populate.

**Rationale:** Giving `settings` explicit values (`elevenlabs_api_key="test-key"`, `voice_id="test-voice"`, …) rather than letting `MagicMock` auto-create them means a typo in a config attribute name fails loudly instead of silently returning a truthy mock.
**Source:** 05-01-PLAN.md, 05-01-SUMMARY.md

### Tests define their own `FakeTranscriptionResult` rather than importing `TranscriptionResult`
A local dataclass stands in for the orchestrator's real result type.

**Rationale:** Keeps the web tests decoupled from orchestrator implementation details — the web server only reads `.text` and `.confidence`, so that is all the fake needs to provide.
**Source:** 05-01-SUMMARY.md

### `web/` became a real Python package
An empty `web/__init__.py` was added.

**Rationale:** The directory had no `__init__.py`, so `import web.server` failed and no test could load the module under test. Logged as a Rule 3 blocking deviation because it was a hard prerequisite, not a preference.
**Source:** 05-01-SUMMARY.md

### Test dependencies go in a new `web/pyproject.toml`, never in `web/requirements.txt`
`[project.optional-dependencies] dev = ["httpx-ws>=0.9.0", "pytest>=8.0", "pytest-asyncio>=0.24"]`, installed via `pip install -e ".[dev]"` from `web/`.

**Rationale:** `requirements.txt` is the runtime contract for the web server. Test-only dependencies belong in an extras group so a production install never pulls `httpx-ws` or pytest.
**Source:** 05-01-PLAN.md

### `asyncio_mode = "auto"` plus a declared `integration` marker
Configured in `web/pyproject.toml` alongside `testpaths = ["tests"]`.

**Rationale:** Auto mode removes per-test `@pytest.mark.asyncio` boilerplate across an entirely async suite. The `integration` marker was declared up front — with its deselect syntax documented in the marker help text — so Docker-dependent tests have a home before any exist.
**Source:** 05-01-PLAN.md

### Kept `httpx-ws` with `ASGIWebSocketTransport`; no `TestClient` fallback
The plan explicitly authorized falling back to `TestClient.websocket_connect()` if `aconnect_ws` could not interoperate with the server's raw `ws.receive()` pattern. It did interoperate, so `httpx-ws` 0.9.0 stayed.

**Rationale:** One async client library for both REST and WebSocket tests. The plan's open question resolved in favor of the primary choice.
**Source:** 05-02-SUMMARY.md, 05-02-PLAN.md

### WTST-03 exercises `_tts_elevenlabs_stream` by mocking `state.tts_client.post`
The plan proposed patching `_tts_websocket_stream` to raise so `_stream_response` would fall through to `_tts_rest_fallback`.

**Rationale:** That fallback path no longer reflects the server. With `tts_enabled` true and `cartesia_client` None, `_stream_response` goes straight to `_tts_elevenlabs_stream`, which already synthesizes per sentence via `state.tts_client.post`. Mocking one method is both simpler and closer to production behavior than engineering an exception to trigger a dead branch.
**Source:** 05-02-SUMMARY.md

### The barge-in mock is stateful: slow on first call, fast on second
A `call_count` closure variable makes invocation one sleep between chunks and invocation two return immediately.

**Rationale:** The first response must stream slowly enough for the test to interrupt mid-stream; the second must complete fast enough not to race the 5s receive timeout. A single fixed delay cannot satisfy both.
**Source:** 05-02-SUMMARY.md

### Four pre-existing failures were logged, not fixed
`deferred-items.md` records them with cause, suggested fix, and an explicit "Why not fix here" section.

**Rationale:** Plan 05-02 is test-only and forbids touching `web/server.py`; the failing files (`test_websocket.py`, `test_rest.py`) are not in its `files_modified`. The executor verified all four reproduce on `main` before deferring — establishing they were pre-existing rather than caused by the new work.
**Source:** 05-02-SUMMARY.md, deferred-items.md

### The whole web suite must run under 30 seconds
Declared as D-11 and checked in the plan's verification block with `timeout 30 python -m pytest tests/`.

**Rationale:** A test suite for real-time streaming behavior is full of sleeps and timeouts and will creep toward minutes if unbudgeted. Actual: 9.90s for 34 tests.
**Source:** 05-02-PLAN.md, 05-02-SUMMARY.md

---

## Lessons

### For the second time in this milestone, an executor recorded a false premise about a prior phase's output
Plan 05-01's summary states the server "uses module-level globals without FastAPI dependency injection." Phase 04 had added `AppState`, `get_app_state`, and `get_ws_app_state`, verified by its own summaries and cited by `04-SECURITY.md` at `web/server.py:118` and `:123`.

**Context:** Structurally identical to plan 03-02's "Plan 01 implemented sync httpx.Client" error — a Rule 3 blocking deviation asserting a fact about upstream work that the artifact one directory over contradicts. Unlike Phase 03, this one caused no runtime defect: monkeypatching module attributes works, it just is not the mechanism Phase 04 was built to enable.
**Source:** 05-01-SUMMARY.md, 04-01-SUMMARY.md, 04-SECURITY.md

### A test plan can be stale about the code even when it is faithful to the phase summaries it was written from
The plan's WTST-03 strategy targeted `_tts_websocket_stream` → `_tts_rest_fallback`. By execution time the server routed ElevenLabs TTS through `_tts_elevenlabs_stream`, and a `cartesia_client` branch existed that no phase artifact mentions.

**Context:** The executor caught it, chose the simpler real path, and documented the difference as a pattern simplification rather than a bug. Reading the current code beat trusting the plan's description of it.
**Source:** 05-02-SUMMARY.md, 05-02-PLAN.md

### `httpx-ws`'s `aconnect_ws` interoperates cleanly with Starlette's raw `ws.receive()`
The plan hedged at length on this — "if httpx-ws aconnect_ws doesn't work cleanly with the raw ws.receive() pattern, fall back to TestClient" — and it turned out to be a non-issue in httpx-ws 0.9.0.

**Context:** Worth recording so the next WebSocket test does not re-litigate the client choice. The hedge was cheap insurance, but it was not needed.
**Source:** 05-02-SUMMARY.md

### Mocking `websockets.connect` needs a hand-written class, not `AsyncMock`
The mock must be both an async context manager (`__aenter__`/`__aexit__`) and an async iterable (`__aiter__`/`__anext__`), and must terminate via `StopAsyncIteration`.

**Context:** Plan 05-02 walked through two failed `AsyncMock` attempts inline — annotated "This won't work directly" and "BUT `__aiter__` must return an async iterator" — before recommending the `FakeUpstreamWS` class. Showing the dead ends is why Task 2 passed on first run.
**Source:** 05-02-PLAN.md, 05-02-SUMMARY.md

### Testing cancellation requires controlling timing per invocation, not globally
A uniformly slow mock lets you barge in but then makes the second response race the receive timeout; a uniformly fast mock finishes before you can barge in at all.

**Context:** Solved with the `call_count` stateful generator. Any interrupt, cancel, or debounce test has this same shape.
**Source:** 05-02-SUMMARY.md

### A protocol that interleaves JSON headers with binary bodies needs a dedicated frame-collection helper
`{"type": "tts_audio", "size": N}` followed by a raw binary frame cannot be consumed by a plain `receive_json()` loop.

**Context:** `_recv_all` in `test_chat_ws.py` collects mixed text and binary frames so the test can assert the header/body pairing rather than just the presence of audio.
**Source:** 05-02-SUMMARY.md

### Mock signatures rot silently until the production signature grows a parameter
`_stream_response` began passing `on_tool_result=` to `claude_client.chat(...)`. Three tests in `test_websocket.py` broke with `TypeError: mock_chat() got an unexpected keyword argument 'on_tool_result'`.

**Context:** Hand-written mock generators do not track the real signature. All three failures share one root cause and one one-line fix (`on_tool_result=None` in each generator) — the failure count overstates the problem.
**Source:** deferred-items.md, 05-02-SUMMARY.md

### Asserting on user-facing message substrings makes tests fragile to copy edits
`test_tts_not_configured_returns_503` asserts `'not configured' in err`; the server message became "No TTS backend configured" during the Cartesia work.

**Context:** The endpoint still returns 503 correctly — only the wording moved. The suggested fix widens the assertion (`"tts backend" in err or "not configured" in err`), but asserting on the status code alone would have been immune.
**Source:** deferred-items.md

### Every mock async generator must be finite and every receive must have a timeout
Stated twice in the plan as an IMPORTANT directive: no infinite loops in mock generators, `asyncio.wait_for` with a 5–10s timeout on all receives.

**Context:** Called out as Pitfall 2. A streaming server plus an unbounded mock plus a bare `await ws.receive_json()` is a hung suite with no diagnostic.
**Source:** 05-02-PLAN.md

### The scope-boundary rule lets a plan finish green while the suite stays red
Plan 05-02 reports "all tests passed on first run" and `Self-Check: PASSED`, while the full run was "34 passed, 1 skipped, 4 pre-existing failures."

**Context:** Correct behavior under the rule, and honestly reported in the same summary. But it means "plan complete" and "suite green" are different claims, and the follow-up cleanup has to be scheduled deliberately — which it was not. See Surprises.
**Source:** 05-02-SUMMARY.md, deferred-items.md

---

## Patterns

### `ASGITransport` for REST, `ASGIWebSocketTransport` + `aconnect_ws` for WebSocket
```python
transport = ASGITransport(app=test_app)
async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
    resp = await client.get("/api/status")
```
and for WebSocket, `httpx.AsyncClient(transport=ASGIWebSocketTransport(test_app))` wrapping `aconnect_ws("http://test/ws/chat", client)`.

**When to use:** All in-process FastAPI testing in this project. No live server, no port binding, one client library for both protocols.
**Source:** 05-01-SUMMARY.md, 05-02-SUMMARY.md (`patterns-established`)

### `MockAppState` dataclass with one mock field per subsystem
A dataclass mirroring the server's state shape, with `AsyncMock` for async clients, `MagicMock` for sync ones, and real values for `settings` attributes.

**When to use:** Any app with a state container of heterogeneous service clients. Mirroring the real shape means a field added to production state produces an obvious gap in the fixture.
**Source:** 05-01-SUMMARY.md (`patterns-established`)

### `_recv_all` helper for mixed text/binary frame collection
One helper that drains a WebSocket into an ordered list of both frame types, so tests can assert on sequence and pairing.

**When to use:** Any protocol where a JSON header frame describes a following binary frame.
**Source:** 05-02-SUMMARY.md (`patterns-established`)

### `_FakeUpstreamWS`: a hand-written async context manager that is also an async iterator
```python
class FakeUpstreamWS:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def __aiter__(self): return self
    async def __anext__(self):
        if self._index >= len(self._messages): raise StopAsyncIteration
        ...
```

**When to use:** Standing in for `websockets.connect` or any `async with` + `async for` client. Reusable for the Deepgram STT proxy and Cartesia streaming tests the summary anticipates.
**Source:** 05-02-PLAN.md, 05-02-SUMMARY.md (`patterns-established`)

### Stateful multi-call async generator driven by a closure counter
`call_count` selects a slow path on first invocation and a fast path on subsequent ones.

**When to use:** Testing interruption, cancellation, retry, or debounce — anywhere the test needs invocation *n* to behave differently from invocation *n+1*.
**Source:** 05-02-SUMMARY.md (`patterns-established`)

### `asyncio.wait_for` on every receive, finite mocks everywhere
A hard rule for the suite, not a per-test judgment call.

**When to use:** Any streaming-protocol test suite. Converts a hang into a named failure.
**Source:** 05-02-PLAN.md

### `deferred-items.md` as the scope-boundary artifact
Per item: the exact failure output, the root cause, the concrete suggested fix, and a shared "Why not fix here" rationale — plus verification that each failure reproduces on `main`.

**When to use:** Whenever a test-only or file-scoped plan surfaces failures outside its ownership. Proving pre-existence is what separates "deferred" from "caused and hidden."
**Source:** deferred-items.md

### `<behavior>` blocks that group test names under their requirement ID
Tests were enumerated as "WTST-07 (status endpoint): test_status_returns_subsystem_health, …" before any implementation instruction.

**When to use:** `tdd="true"` test-writing plans. It doubles as requirements-coverage bookkeeping — WTST-01 through WTST-07 are each traceable to named tests across the two plans.
**Source:** 05-01-PLAN.md, 05-02-PLAN.md

### Show the failed mock attempts in the plan, then the working one
Plan 05-02's Task 2 action block contains two annotated non-working `AsyncMock` sketches before the recommended class.

**When to use:** Tasks with a known-tricky mocking shape. It costs a few lines and stops the executor from spending its own attempts on the same dead ends.
**Source:** 05-02-PLAN.md

---

## Surprises

### The test phase concluded the server has no dependency injection, one phase after DI was added for this exact purpose
Phase 04's stated purpose: "Make the web server testable via dependency_overrides (Phase 5 depends on this)." Phase 05's plan was written against `get_app_state`/`get_ws_app_state`. Its executor concluded those functions do not exist and monkeypatched module attributes instead.

**Impact:** The tests work, but the DI seam Phase 04 built went unused. Closed at milestone level as a deferred item — "`web/server.py` early-boot module state — tests monkeypatch globals rather than use DI overrides — acknowledged (acceptable for v1.2; revisit if logging infra changes)" — rather than reconciled.
**Source:** 05-01-SUMMARY.md, 04-01-PLAN.md, .planning/STATE.md

### The two plans in this phase describe the same fixtures differently
Plan 05-02's frontmatter records its dependency as `provides: "mock_app_state / test_app fixtures with dependency_overrides wiring"` — but plan 05-01's deviation log says it used monkeypatching precisely *because* `dependency_overrides` was unavailable.

**Impact:** The phase's own artifacts disagree about how its test harness works. Anyone reading only 05-02's frontmatter would look for a DI override mechanism that the conftest keeps only as a dormant fallback.
**Source:** 05-02-SUMMARY.md, 05-01-SUMMARY.md

### The server had grown a Cartesia TTS branch that no phase plan or summary documents
Plan 05-02 found `_stream_response` routing on `cartesia_client is None` and going to `_tts_elevenlabs_stream` rather than the `_tts_websocket_stream` path Phase 02 built and Phase 04 threaded state through.

**Impact:** Third independent sighting of the same drift — `04-SECURITY.md` found `deepgram_client` and `cartesia_client` in lifespan teardown, and STATE.md's "Scope Divergence Note" flags uncaptured commits. The test suite was written against the real code, so no defect resulted, but the roadmap does not describe the system.
**Source:** 05-02-SUMMARY.md, 04-SECURITY.md, .planning/STATE.md

### All six WebSocket tests passed on first run with zero fixes
"Both test files ran green on the first invocation after creation" — no server changes, no fixture changes, no auto-fixed deviations. This covers barge-in cancellation and interleaved binary audio streaming, the two hardest things in the phase.

**Impact:** Attributable to the plan pre-solving the mocking shapes (including the dead ends) and pre-specifying the timeout discipline. Contrast with plan 05-01, which hit two blocking deviations on straightforward infrastructure.
**Source:** 05-02-SUMMARY.md

### The phase was declared test-complete with four red tests, and the follow-up plan it asked for was never written — the fixes arrived anyway, unattributed
05-02's summary says "Phase 5 scope is test-complete modulo the deferred legacy-test cleanup" and recommends "a small cleanup plan (Plan 05-03 or similar)."

**Impact:** No 05-03 was ever created. The four failures were nonetheless fixed inside `8587ba5 fix: unblock python CI + close out v1.2 (#71)` — before v1.2 shipped — using exactly the one-line fixes `deferred-items.md` had suggested. Nothing linked that commit back to the record, so the log continued to read as outstanding for three months until a 2026-07-29 re-check. This is the same shape as Phase 03's gaps: real work closed by unrelated work, with the tracking artifact never updated. The knowledge survived; the resolution did not.
**Source:** deferred-items.md (`## Resolution`), 05-02-SUMMARY.md, git `8587ba5`

### The phase that added the test suite has neither a verification report nor a UAT
`gsd-sdk` reports `has_verification: false` for Phase 05, and no `05-UAT.md` exists — coverage of WTST-01 through WTST-07 is asserted only in the plan summaries themselves.

**Impact:** Requirements coverage rests on executor self-report. Given that plan 05-01's self-report also contained the false DI premise, an independent verifier would have had something to catch — Phase 03 is the precedent for what self-check misses.
**Source:** 05-01-SUMMARY.md, 05-02-SUMMARY.md
