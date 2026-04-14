---
phase: 05-web-server-tests
plan: 02
subsystem: testing
tags: [pytest, websocket, httpx-ws, async-testing, tts, telemetry, barge-in]

requires:
  - phase: 05-web-server-tests
    plan: 01
    provides: "mock_app_state / test_app fixtures with dependency_overrides wiring"
provides:
  - "6 passing WebSocket tests (4 chat + 2 telemetry) for WTST-01/02/03/06"
  - "Pattern for httpx-ws aconnect_ws against FastAPI WS endpoints with ASGIWebSocketTransport"
  - "Pattern for patching websockets.connect via web.server.ws_lib.connect"
affects: [05-web-server-tests]

tech-stack:
  added: []
  patterns:
    - "httpx-ws aconnect_ws + ASGIWebSocketTransport for in-process WS tests"
    - "Mixed text/binary WS frame collection helper (_recv_all) for tts_audio header + binary body pairs"
    - "FakeUpstreamWS async context manager for mocking websockets.connect"
    - "Stateful multi-call async generator (call_count switch) to drive barge-in scenarios"

key-files:
  created:
    - web/tests/test_chat_ws.py
    - web/tests/test_telemetry_ws.py
    - .planning/phases/05-web-server-tests/deferred-items.md
  modified: []

key-decisions:
  - "Used ElevenLabs REST path (_tts_elevenlabs_stream) for WTST-03 instead of the plan's _tts_rest_fallback workaround — _tts_elevenlabs_stream already does per-sentence REST synthesis via state.tts_client.post, which is trivially mockable"
  - "Kept httpx-ws aconnect_ws (plan D-02) — no TestClient fallback needed; Starlette's raw ws.receive() handles httpx-ws text/binary frames correctly"
  - "Made the barge-in mock stateful (call_count) so the first invocation is slow and the second is fast, guaranteeing both responses can complete deterministically within the 5s receive timeout"
  - "Pre-existing failures in test_websocket.py and one assertion in test_rest.py were logged to deferred-items.md rather than fixed — they are out of scope per the test-only restriction on 05-02"

requirements-completed: [WTST-01, WTST-02, WTST-03, WTST-06]

duration: ~8 min
completed: 2026-04-14
---

# Phase 05 Plan 02: WebSocket Test Coverage Summary

**Six WebSocket tests proving chat round-trip, barge-in interruption, TTS audio streaming, and telemetry proxying — all in-process via httpx-ws over an ASGI transport, no sim or external services required.**

## Performance

- **Duration:** ~8 min
- **Tasks:** 2
- **Files created:** 3 (2 test files + deferred-items log)
- **New tests:** 6
- **Test runtime:** `test_chat_ws.py` 1.33s, `test_telemetry_ws.py` 4.04s, full `web/tests/` suite 9.90s (well under the 30s D-11 budget)

## Accomplishments
- Chat WebSocket round-trip (WTST-01): mocked `claude_client.chat` async generator yields text chunks; test asserts joined content equals `"Roger that."` and a `done` frame follows.
- Empty-text error path: sending `{"text": ""}` produces `{"type": "error", "content": "No text provided"}`.
- Barge-in (WTST-02): a stateful slow/fast mock lets the first response begin streaming, then a second client send forces `_cancel_active_response()`, which emits `{"type": "interrupted"}`. The second response then completes with its own `done`.
- TTS streaming (WTST-03): enabled ElevenLabs REST path with mocked `tts_client.post` returning fake MP3 bytes. Test parses the interleaved text and binary stream and asserts that a `{"type": "tts_audio", "size": N}` header frame is followed by the expected binary frame.
- Telemetry proxy (WTST-06): `_FakeUpstreamWS` async context manager stands in for `websockets.connect`; test asserts the initial `{connected: false, data: null}` frame is followed by a proxied `{connected: true, data: {...}}` frame with full telemetry payload.
- Telemetry fallback: patching `ws_lib.connect` to raise `ConnectionRefusedError` produces the expected offline-fallback frame.

## Task Commits

Each task committed atomically:

1. **Task 1 — Chat WebSocket tests:** `2766f1a` (test) — web/tests/test_chat_ws.py (263 lines, 4 tests)
2. **Task 2 — Telemetry proxy tests:** `78d4097` (test) — web/tests/test_telemetry_ws.py (102 lines, 2 tests) + deferred-items.md

## Files Created/Modified
- `web/tests/test_chat_ws.py` — 4 WebSocket chat tests, helper `_recv_all` for mixed text/binary frame collection
- `web/tests/test_telemetry_ws.py` — 2 telemetry proxy tests, `_FakeUpstreamWS` async context-manager class
- `.planning/phases/05-web-server-tests/deferred-items.md` — log of 4 pre-existing unrelated failures

## Decisions Made
- **REST path instead of fallback patch for WTST-03.** The plan suggested patching `_tts_websocket_stream` to raise so that `_stream_response` falls through to `_tts_rest_fallback`. But the current server no longer uses `_tts_websocket_stream` — when `tts_enabled` is true and `cartesia_client` is None, `_stream_response` goes directly to `_tts_elevenlabs_stream`, which already does per-sentence REST synthesis via `state.tts_client.post`. Mocking that one method is simpler and maps more directly to how production runs today.
- **Stuck with `httpx-ws` per D-02.** Starlette's raw `ws.receive()` pattern in `ws_chat` interoperates cleanly with `aconnect_ws` in httpx-ws 0.9.0. No `TestClient.websocket_connect` fallback needed.
- **Stateful barge-in mock.** Using a `call_count` closure variable lets the first invocation of the async generator sleep between chunks (so the test can barge in mid-stream) while the second invocation returns immediately (so the assertion doesn't race the second `done`).
- **Pre-existing failures deferred, not fixed.** `test_websocket.py` has three failures from a stale `claude_client.chat(...)` mock signature missing `on_tool_result`, and `test_rest.py::test_tts_not_configured_returns_503` checks for a message string that has since changed. Both files belong to earlier plans. Plan 05-02 is explicitly test-only and forbids touching `web/server.py`, and the scope-boundary rule says unrelated pre-existing failures are logged, not fixed.

## Deviations from Plan

### Auto-fixed Issues
None — all tests passed on first run with no server changes and no fixture changes.

### Differences from Plan Pattern Text

**1. [Rule 3 — Simpler mock] Mocked `tts_client.post` instead of patching `_tts_websocket_stream`**
- **Found during:** Task 1 (WTST-03 TTS streaming test)
- **Issue:** The plan's alternative approach assumed `_stream_response` would fall through to `_tts_rest_fallback` when `_tts_websocket_stream` raises. In the current server, `_stream_response` routes ElevenLabs TTS directly to `_tts_elevenlabs_stream` (also REST-based). No exception/fallback needed.
- **Fix:** Mock `state.tts_client.post` to return fake MP3 bytes; `_tts_elevenlabs_stream` consumes them and emits the expected `tts_audio` header + binary frame.
- **Files modified:** web/tests/test_chat_ws.py only.
- **Committed in:** 2766f1a

**Total deviations:** 0 auto-fixed, 1 pattern simplification (not a bug fix)
**Impact on plan:** None — same requirement (WTST-03) satisfied with a more direct mock.

## Deferred Issues (pre-existing, out of scope)

See `.planning/phases/05-web-server-tests/deferred-items.md` for full detail. Summary:

- `web/tests/test_rest.py::test_tts_not_configured_returns_503` — stale assertion string ("not configured" vs "no tts backend configured")
- `web/tests/test_websocket.py::test_chat_text_message_streams_response`
- `web/tests/test_websocket.py::test_chat_interrupt_message`
- `web/tests/test_websocket.py::test_chat_audio_start_marker`

The three `test_websocket.py` failures are all the same root cause: mock `chat` async generators missing the `on_tool_result` keyword argument that `_stream_response` now passes. Suggested follow-up: a small cleanup plan to refresh these legacy mocks.

## Issues Encountered
None. Both test files ran green on the first invocation after creation.

## User Setup Required
None — tests run entirely in-process using httpx-ws `ASGIWebSocketTransport` and mocked subsystems. No sim, no ElevenLabs key, no telemetry service.

## Next Phase Readiness
- Phase 5 requirements WTST-01/02/03/06 all covered; Plan 05-01 already covered WTST-04/05/07. Phase 5 scope is test-complete modulo the deferred legacy-test cleanup.
- Established patterns (httpx-ws ASGI transport, stateful barge-in mocks, `_FakeUpstreamWS`) are reusable for any future WebSocket tests in this project (e.g., Cartesia v2 streaming, Deepgram STT proxy).

## Self-Check: PASSED

**Files verified to exist:**
- FOUND: /mnt/c/Users/bould/source/airdale/web/tests/test_chat_ws.py
- FOUND: /mnt/c/Users/bould/source/airdale/web/tests/test_telemetry_ws.py
- FOUND: /mnt/c/Users/bould/source/airdale/.planning/phases/05-web-server-tests/deferred-items.md

**Commits verified to exist:**
- FOUND: 2766f1a (test 05-02 chat WebSocket tests)
- FOUND: 78d4097 (test 05-02 telemetry proxy tests)

**Test run verified:**
- 4/4 chat WS tests pass (1.33s)
- 2/2 telemetry WS tests pass (4.04s)
- Full `web/tests/` suite: 34 passed, 1 skipped, 4 pre-existing failures, 9.90s total (under 30s budget)

---
*Phase: 05-web-server-tests*
*Completed: 2026-04-14*
