---
phase: 02
phase_name: "TTS Integration"
project: "MERLIN — Airdale"
generated: "2026-07-29"
counts:
  decisions: 10
  lessons: 9
  patterns: 8
  surprises: 5
missing_artifacts:
  - "02-UAT.md"
---

# Phase 02 Learnings: TTS Integration

## Decisions

### One persistent `httpx.AsyncClient` per TTS backend, created in `__init__`
Both `ElevenLabsClient` and `KokoroClient` create `self._http = httpx.AsyncClient(timeout=30.0)` in their constructor and expose `aclose()`. No `async with httpx.AsyncClient()` remains in either backend.

**Rationale:** Eliminates per-call TCP and TLS handshake overhead on every synthesis request — the dominant fixed cost when a response is synthesized sentence by sentence.
**Source:** 02-01-SUMMARY.md

### Voice settings live in config and flow config → factory → constructor
`tts_stability`, `tts_similarity_boost`, and `tts_style` were added to `Settings`; `create_tts_client()` passes them as constructor kwargs; `ElevenLabsClient` stores them as `self._stability` / `_similarity_boost` / `_style` and uses them in every synthesis path.

**Rationale:** Before this, four separate hardcoded `voice_settings` dicts existed across consumers with divergent values — the CLI used `{0.5, 0.75, 0.3}` while the web server used `{0.75, 0.80, 0.15}`. Defaults were set to the web server's values, making it the reference behavior.
**Source:** 02-01-PLAN.md, 02-01-SUMMARY.md

### Config properties are backend-aware rather than backend-specific
`voice_id` returns `tts_voice_id_local` when `tts_backend == "local"`, else `elevenlabs_voice_id`. `tts_configured` checks `tts_local_url` for local and `api_key and voice_id` for ElevenLabs.

**Rationale:** Consumers ask "is TTS configured?" and "what voice?" without knowing which backend answers. Keeps the backend conditional in exactly one place.
**Source:** 02-01-SUMMARY.md, 02-VERIFICATION.md

### `VoiceOutput` no longer guards on `api_key` / `voice_id`
The early-return checks in `speak()` and `speak_streamed()` were removed along with `self._api_key`, `self._voice_id`, and `self._model_id`.

**Rationale:** Readiness is the TTSClient's concern. If a client was constructed, it is usable; duplicating credential inspection in the consumer reintroduces backend knowledge into a layer that just got cleaned of it.
**Source:** 02-02-SUMMARY.md

### Web server holds the client in a module-level `_tts_client_instance`, not `app.state`
The plan suggested `app.state.tts_client`; execution used a module global instead.

**Rationale:** Consistency with the pre-existing pattern for `sim_client`, `claude_client`, and other server globals. Deliberately chose local convention over the plan's suggestion. (Phase 04 later revisited exactly this module-global pattern.)
**Source:** 02-02-SUMMARY.md

### Removed the TTS warmup pre-flight request
`_stream_response` previously fired a warmup HEAD request to prime the connection; this was deleted.

**Rationale:** Redundant once the backend holds a persistent `httpx.AsyncClient` — the connection is already warm and pooled.
**Source:** 02-02-SUMMARY.md

### ElevenLabs WebSocket streaming decouples send and receive via `asyncio.Queue[bytes | None]`
A receiver task drains WS messages into the queue while the main coroutine sends text chunks and then yields from the queue until a `None` sentinel.

**Rationale:** The ElevenLabs stream-input protocol deadlocks under a sequential send-all-then-receive-all pattern. The queue also matches an existing codebase idiom.
**Source:** 02-03-SUMMARY.md

### The phrase cache stays in the web server, not in the TTSClient
`_TTS_CACHE` lookup happens in the server's queue-to-iterator bridge; only uncached text reaches `synthesize_ws_stream()`.

**Rationale:** Per decision D-08 — the server caches, the client synthesizes. Keeps the TTSClient a pure synthesis boundary with no storage policy.
**Source:** 02-03-SUMMARY.md

### Kokoro fakes WebSocket streaming with sentence-boundary buffering
`KokoroClient.synthesize_ws_stream()` accumulates chunks, finds the last `.!?\n` via `max(buffer.rfind(ch) for ch in sentence_endings)`, and flushes complete sentences through `synthesize_stream()`.

**Rationale:** Kokoro has no WebSocket stream-input API. Rather than making the protocol method optional and forcing consumers to branch, every backend satisfies the full protocol — natively or by fallback.
**Source:** 02-03-SUMMARY.md, 02-03-PLAN.md

### `httpx` import stays in `voice.py` after removing all TTS httpx usage
Only the TTS calls were removed; the import remains.

**Rationale:** `VoiceInput.transcribe` still uses httpx for Whisper. Checking remaining usages before deleting an import avoided breaking the STT path.
**Source:** 02-02-SUMMARY.md

---

## Lessons

### Moving to a persistent HTTP client invalidates every context-manager-based test mock
Tests that patched `httpx.AsyncClient` at module level as a context manager stopped working once the client became a long-lived instance attribute. The fix is to mock `client._http` directly on the instance.

**Context:** The plan called this out in advance for Task 2 of plan 01 and the mocking pattern in `test_tts_client.py` was rewritten in the same commit. Anticipating it is why plan 01 recorded zero deviations.
**Source:** 02-01-PLAN.md, 02-01-SUMMARY.md

### The ElevenLabs stream-input WebSocket needs a priming message before real text
The connection requires an initial `{"text": " ", "voice_settings": {...}}` frame — a single space, not empty — or it does not work. Voice settings can only be supplied on this first frame.

**Context:** Documented as research PITFALL 3 and written directly into the plan's implementation steps.
**Source:** 02-03-PLAN.md, 02-VERIFICATION.md

### ElevenLabs sends audio as base64 inside JSON, not as binary WebSocket frames
Each message is JSON with an `"audio"` field to base64-decode and an `"isFinal"` field marking the end of the stream.

**Context:** Research PITFALL 2. The naive assumption — that a streaming audio WebSocket sends binary frames — would have produced silent garbage.
**Source:** 02-03-PLAN.md, 02-VERIFICATION.md

### A sequential send-then-receive loop deadlocks on ElevenLabs stream-input
The server does not buffer the full input before responding, so the client must read while it writes.

**Context:** Research PITFALL 6, and the direct cause of the `asyncio.Queue` design.
**Source:** 02-03-PLAN.md, 02-03-SUMMARY.md

### A `{"text": ""}` flush frame is required to get the final audio chunk
Without it, the tail of the utterance is never synthesized.

**Context:** Research PITFALL 5. Encoded as an explicit acceptance criterion: `grep -q '{"text": ""}' elevenlabs.py`.
**Source:** 02-03-PLAN.md

### Declaring an async generator on a `Protocol` needs an unreachable `yield`
The stub body requires `... ` followed by `if False: # pragma: no cover` / `yield  # type: ignore[misc]` for the method to type-check as an async generator rather than a coroutine.

**Context:** Written into the plan verbatim for `base.py`'s `synthesize_ws_stream` declaration.
**Source:** 02-03-PLAN.md

### ruff's UP041 rejects `asyncio.TimeoutError` in favor of the builtin `TimeoutError`
Caught only at lint time, not at import or test time.

**Context:** The single auto-fixed deviation in the entire phase, folded into commit `06c622d`.
**Source:** 02-03-SUMMARY.md

### Giving new constructor parameters defaults preserves existing call sites for free
`stability=0.75, similarity_boost=0.80, style=0.15` as defaults meant existing `ElevenLabsClient(api_key, voice_id, model_id)` constructions in tests kept working with no edits.

**Context:** Explicitly noted in the plan as the reason existing test constructors did not need changing — only the mocking pattern did.
**Source:** 02-01-PLAN.md

### Time-to-first-audio is not programmatically verifiable
The one item verification could not close was whether streaming latency regressed against the old inline implementation.

**Context:** Requires a live ElevenLabs WebSocket, a real audio output device, and subjective judgment. Logged as the phase's only `human_verification` entry with a concrete target of sub-500ms first chunk.
**Source:** 02-VERIFICATION.md

---

## Patterns

### Persistent HTTP client with explicit lifecycle
Create the client in `__init__`, expose `aclose()`, declare `aclose()` on the protocol so every implementation must provide it, and call it from every shutdown path (`Orchestrator.stop()` and the FastAPI lifespan teardown).

**When to use:** Any client wrapper making repeated calls to the same host. Putting `aclose()` on the protocol is what makes the leak impossible to forget.
**Source:** 02-01-SUMMARY.md (`patterns-established`)

### Backend-aware config properties
Put the `if backend == X` branch inside a `Settings` property rather than at each call site.

**When to use:** Whenever a config value has a different source depending on a mode or backend selector field.
**Source:** 02-01-SUMMARY.md

### Consumer delegation to a protocol
Consumers accept the protocol in their constructor and call its methods; they hold no URLs, credentials, or provider-specific settings. `VoiceOutput._synthesize` shrank to a `try`/`except` around `self._tts.synthesize(text)`.

**When to use:** Any time the same third-party integration appears in more than one consumer.
**Source:** 02-02-SUMMARY.md (`patterns-established`)

### Factory injection at startup
`create_tts_client(settings)` is called once per process — in the orchestrator constructor and in the web server lifespan — and the result is passed down.

**When to use:** Swappable backends selected by config. Keeps the backend conditional in the factory and nowhere else.
**Source:** 02-02-SUMMARY.md

### Queue-to-AsyncIterator bridge
Adapt an existing `asyncio.Queue` producer into the `AsyncIterator[str]` a protocol method expects, instead of changing the protocol to accept a queue.

**When to use:** Wiring a protocol whose signature you control into a producer whose shape you do not. Used twice here — inside `ElevenLabsClient` for audio out, and in the web server's `_uncached_text_iter()` for text in.
**Source:** 02-03-SUMMARY.md (`patterns-established`)

### Cache-aware streaming wrapper
The caller's iterator filters cached items and emits them directly, passing only cache misses through to the expensive backend call.

**When to use:** Streaming pipelines with a partial-hit cache, where the cache must not become the synthesis layer's responsibility.
**Source:** 02-03-SUMMARY.md

### Full protocol conformance via native implementation or documented fallback
Rather than marking `synthesize_ws_stream` optional, ElevenLabs implements it natively and Kokoro implements it by buffering. Consumers never branch on capability.

**When to use:** Extending a protocol with a capability only some backends have natively. The fallback belongs in the backend, not the consumer.
**Source:** 02-03-PLAN.md, 02-03-SUMMARY.md

### Negative grep acceptance criteria to prove extraction is complete
Criteria such as `! grep -q "api.elevenlabs.io" voice.py`, `! grep -q '"stability":' web/server.py`, and `! grep -q "stream-input" web/server.py` assert what must be *absent* from the consumer after the refactor.

**When to use:** Extract-to-abstraction refactors, where the risk is leaving half the old implementation behind. Absence checks catch that; presence checks do not.
**Source:** 02-02-PLAN.md, 02-03-PLAN.md, 02-VERIFICATION.md

---

## Surprises

### ~120 lines of inline WebSocket protocol code reduced to a single protocol call
The web server's `_tts_websocket_stream()` handled URL construction, init framing, concurrent send/receive, base64 decoding, `isFinal` detection, and flush signaling. After plan 03 the chat flow is one `tts_client.synthesize_ws_stream(_uncached_text_iter())` call.

**Impact:** `web/server.py` became fully backend-agnostic for TTS — flipping `tts_backend` in `.env` now switches every synthesis path, including streaming. It also cut a large amount of untested code out of the web server right before Phase 04 refactored it and Phase 05 tested it.
**Source:** 02-03-SUMMARY.md, 02-VERIFICATION.md

### Four separate hardcoded `voice_settings` dicts with inconsistent values
The CLI and the web server had silently diverged: `{stability: 0.5, similarity_boost: 0.75, style: 0.3}` in `voice.py` versus `{0.75, 0.80, 0.15}` in the server.

**Impact:** MERLIN's voice audibly differed between the CLI and the browser. Consolidating on the web server's values was a behavior change for CLI users that the artifacts record as a config-defaults decision, not as a user-facing note.
**Source:** 02-02-SUMMARY.md, 02-01-PLAN.md

### One `voice_settings` dict was deliberately left in place mid-phase
Plan 02 removed all four REST-path dicts but explicitly instructed "Do NOT touch `_tts_websocket_stream()` yet," leaving the fifth for plan 03.

**Impact:** Plan 02's summary had to close with a "Next Phase Readiness" note flagging the known-incomplete state. Staging the extraction by transport (REST first, WebSocket second) kept each plan independently verifiable at the cost of an intentionally inconsistent intermediate commit.
**Source:** 02-02-SUMMARY.md, 02-02-PLAN.md

### Zero deviations across two of three plans despite touching a live streaming protocol
Plans 01 and 02 executed exactly as written; plan 03 produced a single lint fix. Total execution time was 12 minutes for 7 requirements and 12 verified truths.

**Impact:** The research phase's numbered pitfall list (PITFALL 2, 3, 5, 6) being quoted inline in the plan actions appears to be why — the WebSocket failure modes were designed around rather than discovered.
**Source:** 02-01-SUMMARY.md, 02-02-SUMMARY.md, 02-03-SUMMARY.md, 02-03-PLAN.md

### The verification report is dated a day before the work it verifies
`02-VERIFICATION.md` frontmatter reads `verified: 2026-03-26T00:00:00Z`, while all three plan summaries record `completed: 2026-03-27`.

**Impact:** No effect on the findings — the report cites specific line numbers in the post-refactor files, so it clearly ran after the work. Worth knowing that verification timestamps in this phase cannot be used to order events.
**Source:** 02-VERIFICATION.md, 02-01-SUMMARY.md
