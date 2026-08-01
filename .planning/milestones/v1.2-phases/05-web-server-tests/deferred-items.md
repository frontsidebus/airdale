# Phase 05 Deferred Items

> **STATUS: ALL RESOLVED (verified 2026-07-29).** All four failures below were fixed in
> `8587ba5 fix: unblock python CI + close out v1.2 (#71)` — before v1.2 shipped, not after.
> The recommended "Plan 05-03" was never needed. `python3 -m pytest tests/` in `web/` now reports
> **38 passed, 1 skipped**. See `## Resolution` at the end for per-item evidence.
>
> The original entries are preserved unedited below as history.

Out-of-scope issues discovered during Plan 05-02 execution. These are pre-existing failures in files not touched by this plan — logged per GSD scope boundary rule.

## Pre-existing test failures (not caused by Plan 05-02)

Discovered when running `python3 -m pytest tests/` in `web/` after adding Plan 05-02 test files. Verified that all four failures reproduce against `main` without any new files loaded.

### 1. `web/tests/test_rest.py::test_tts_not_configured_returns_503`

- **Failure:** `assert 'not configured' in 'no tts backend configured'`
- **Cause:** Server message was changed to "No TTS backend configured" (Phase 4 cartesia work); the assertion still looks for the old substring `"not configured"`.
- **Fix:** Update assertion to `assert "tts backend" in err or "not configured" in err` (test-only change). Out of scope for 05-02 (test file owned by Plan 05-01).

### 2. `web/tests/test_websocket.py::test_chat_text_message_streams_response`
### 3. `web/tests/test_websocket.py::test_chat_interrupt_message`
### 4. `web/tests/test_websocket.py::test_chat_audio_start_marker`

- **Failure:** `TypeError: mock_chat() got an unexpected keyword argument 'on_tool_result'`
- **Cause:** `web/server.py::_stream_response` now calls `state.claude_client.chat(user_text, sim_state=..., on_tool_result=...)`. The mock `chat` generators in `test_websocket.py` were written against the older two-arg signature and have not been updated.
- **Fix:** Add `on_tool_result=None` to each mock chat generator in `test_websocket.py`. Out of scope for 05-02 (file belongs to an earlier phase and is not in this plan's `files_modified`).

### Why not fix here

Plan 05-02 is explicitly test-only and forbids modifying `web/server.py`. These failures are in `test_websocket.py` and `test_rest.py` — not in Plan 05-02's owned files (`test_chat_ws.py`, `test_telemetry_ws.py`). They were already failing on `main` prior to any work in this plan. Fixing them would expand scope.

Recommended follow-up: small cleanup plan (Plan 05-03 or similar) to align the legacy `test_websocket.py` mocks with the current `claude_client.chat` signature and refresh the REST assertion string.

---

## Resolution

_Added 2026-07-29. No Plan 05-03 was created — the fixes landed inside the CI-unblocking commit._

All four items were fixed in `8587ba5 fix: unblock python CI + close out v1.2 (#71)`, using exactly
the changes suggested above.

| # | Item | Fix in current code | Status |
|---|---|---|---|
| 1 | `test_rest.py::test_tts_not_configured_returns_503` — stale assertion string | `web/tests/test_rest.py:186` — `assert "not configured" in err or "no tts backend" in err` | RESOLVED |
| 2 | `test_websocket.py::test_chat_text_message_streams_response` | `on_tool_result=None` added to `mock_chat` at `test_websocket.py:50` | RESOLVED |
| 3 | `test_websocket.py::test_chat_interrupt_message` | `on_tool_result=None` added to `mock_chat` at `test_websocket.py:144` | RESOLVED |
| 4 | `test_websocket.py::test_chat_audio_start_marker` | `on_tool_result=None` added to `mock_chat` at `test_websocket.py:177` | RESOLVED |

A fourth generator at `test_websocket.py:256` (`mock_chat_error`) received the same parameter,
though it was not among the reported failures.

**Verification (2026-07-29):**

```
$ cd web && python3 -m pytest tests/ -q
38 passed, 1 skipped in 9.00s

$ python3 -m pytest tests/test_websocket.py::test_chat_text_message_streams_response \
    tests/test_websocket.py::test_chat_interrupt_message \
    tests/test_websocket.py::test_chat_audio_start_marker \
    tests/test_rest.py::test_tts_not_configured_returns_503 -v
4 passed in 2.53s
```

**Lesson worth carrying:** this is the same shape as the Phase 03 gaps — fixed incidentally by
unrelated work, with nothing linking the fix back to the record that tracked it. The knowledge was
preserved here but the resolution was not, so the record read as outstanding for three months. When
a commit closes a deferred item, annotate the item in the same commit.
