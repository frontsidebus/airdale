---
phase: 02-tts-integration
verified: 2026-03-26T00:00:00Z
status: passed
score: 12/12 must-haves verified
re_verification: false
gaps: []
human_verification:
  - test: "TTS streaming latency check"
    expected: "Time-to-first-audio does not regress compared to previous inline ElevenLabs WebSocket implementation"
    why_human: "Cannot measure audio latency programmatically without a live ElevenLabs connection and audio output device"
---

# Phase 2: TTS Integration Verification Report

**Phase Goal:** All TTS consumers (web server and CLI voice module) use the TTSClient protocol with persistent connections, consistent voice settings from config, and streaming support
**Verified:** 2026-03-26
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | Web server produces TTS audio through TTSClient protocol — no inline httpx calls to ElevenLabs remain in `web/server.py` | ✓ VERIFIED | `create_tts_client(settings)` called in lifespan; `/api/tts` uses `_tts_client_instance.synthesize()`; grep for `api.elevenlabs.io`, `stability`, `stream-input` returns 0 matches |
| 2  | CLI voice module produces TTS audio through TTSClient protocol — no inline httpx calls remain in `orchestrator/orchestrator/voice.py` | ✓ VERIFIED | `VoiceOutput.__init__` accepts `tts_client: TTSClient`; `_synthesize()` delegates to `self._tts.synthesize()`; no ElevenLabs URLs or hardcoded voice settings found |
| 3  | Changing `tts_backend` in `.env` from `elevenlabs` to `kokoro` switches TTS engine without code changes | ✓ VERIFIED | `create_tts_client()` factory in `tts/__init__.py` branches on `settings.tts_backend`; `tts_backend`, `tts_local_url`, `tts_voice_id_local` all in `Settings`; `tts_configured` property is backend-aware |
| 4  | Voice settings (stability, similarity_boost, style) are defined once in config and used consistently by all consumers | ✓ VERIFIED | `tts_stability=0.75`, `tts_similarity_boost=0.80`, `tts_style=0.15` in `Settings`; factory passes `stability=settings.tts_stability` etc. to `ElevenLabsClient`; `ElevenLabsClient` stores as `self._stability/_similarity_boost/_style` and uses them in all synthesis methods |
| 5  | TTSClient protocol has `synthesize_ws_stream()` accepting `AsyncIterator[str]` and returning `AsyncIterator[bytes]` | ✓ VERIFIED | `base.py` lines 34-47 define the method on the protocol |
| 6  | ElevenLabsClient implements WebSocket streaming with concurrent send/receive, base64 decoding, flush signal | ✓ VERIFIED | `elevenlabs.py` opens `wss://api.elevenlabs.io/.../stream-input`, uses `asyncio.Queue`, concurrent `_receive_audio` task, base64 decoding, sends `{"text": ""}` flush |
| 7  | KokoroClient implements fallback via sentence-boundary buffering | ✓ VERIFIED | `kokoro.py` `synthesize_ws_stream()` buffers text to `sentence_endings`, flushes via `synthesize_stream()` |
| 8  | Web server chat TTS flow uses `tts_client.synthesize_ws_stream()` | ✓ VERIFIED | `_tts_stream_to_browser()` calls `tts_client.synthesize_ws_stream(_uncached_text_iter())` at line 692 |
| 9  | Both TTS backends use persistent `httpx.AsyncClient` (no per-call creation) | ✓ VERIFIED | `self._http = httpx.AsyncClient(timeout=30.0)` in both constructors; `grep "async with httpx.AsyncClient"` returns 0 matches in both backend files |
| 10 | Both TTS clients have `aclose()` for lifecycle cleanup | ✓ VERIFIED | `ElevenLabsClient.aclose()` calls `await self._http.aclose()`; `KokoroClient.aclose()` same; `TTSClient` protocol declares `aclose()` |
| 11 | `main.py` creates TTSClient via factory and calls `aclose()` on shutdown | ✓ VERIFIED | Line 60: `self._tts_client = create_tts_client(settings)`; line 160: `await self._tts_client.aclose()` in `stop()` |
| 12 | Web server lifespan creates TTSClient and calls `aclose()` on shutdown | ✓ VERIFIED | Lifespan line 193: `_tts_client_instance = create_tts_client(settings)`; shutdown lines 212-213: `await _tts_client_instance.aclose()` |

**Score:** 12/12 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `orchestrator/orchestrator/config.py` | TTS config fields: `tts_backend`, `tts_local_url`, `tts_voice_id_local`, `tts_stability`, `tts_similarity_boost`, `tts_style`, `tts_configured` property | ✓ VERIFIED | All 6 fields present with correct defaults (0.75, 0.80, 0.15); `tts_configured` and `voice_id` properties both backend-aware |
| `.env.example` | TTS configuration documentation | ✓ VERIFIED | `TTS_BACKEND`, `TTS_LOCAL_URL`, `TTS_VOICE_ID_LOCAL`, `TTS_STABILITY`, `TTS_SIMILARITY_BOOST`, `TTS_STYLE` all documented with comments |
| `orchestrator/orchestrator/tts/base.py` | TTSClient protocol with `aclose` and `synthesize_ws_stream` | ✓ VERIFIED | Protocol defines `audio_content_type`, `synthesize`, `synthesize_stream`, `synthesize_ws_stream`, `aclose` |
| `orchestrator/orchestrator/tts/elevenlabs.py` | ElevenLabsClient with voice settings params, persistent httpx, `aclose`, `synthesize_ws_stream` | ✓ VERIFIED | Constructor accepts `stability/similarity_boost/style`; `self._http` created once; all four protocol methods implemented |
| `orchestrator/orchestrator/tts/kokoro.py` | KokoroClient with persistent httpx, `aclose`, `synthesize_ws_stream` fallback | ✓ VERIFIED | `self._http` created once; sentence-boundary buffering fallback implemented |
| `orchestrator/orchestrator/tts/__init__.py` | Factory passes `settings.tts_stability` to `ElevenLabsClient` | ✓ VERIFIED | Lines 57-59 pass `stability=settings.tts_stability`, `similarity_boost=settings.tts_similarity_boost`, `style=settings.tts_style` |
| `orchestrator/orchestrator/voice.py` | `VoiceOutput` using TTSClient for synthesis | ✓ VERIFIED | Constructor signature is `(self, tts_client: TTSClient, sample_rate: int = 24000)`; no ElevenLabs imports or httpx TTS calls |
| `orchestrator/orchestrator/main.py` | Orchestrator creating TTSClient via factory and passing to VoiceOutput | ✓ VERIFIED | `create_tts_client` imported and used; TTSClient stored on `self._tts_client` and closed in `stop()` |
| `web/server.py` | Web server using TTSClient for `/api/tts`, phrase cache, and WebSocket streaming | ✓ VERIFIED | All three paths use `_tts_client_instance`; no inline ElevenLabs httpx code remains |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `tts/__init__.py` | `config.py` | Factory passes `stability=settings.tts_stability` to `ElevenLabsClient` | ✓ WIRED | Lines 57-59 confirmed |
| `tts/elevenlabs.py` | `config.py` | Constructor receives voice settings from config | ✓ WIRED | `self._stability`, `self._similarity_boost`, `self._style` stored and used in all synthesis paths |
| `voice.py` | `tts/base.py` | `VoiceOutput._synthesize` calls `self._tts.synthesize()` | ✓ WIRED | Line 313 confirmed |
| `web/server.py` | `tts/__init__.py` | Lifespan creates TTSClient via `create_tts_client(settings)` | ✓ WIRED | Line 193 confirmed |
| `main.py` | `tts/__init__.py` | Orchestrator creates TTSClient via `create_tts_client(settings)` | ✓ WIRED | Line 60 confirmed |
| `tts/elevenlabs.py` | `wss://api.elevenlabs.io` | WebSocket connection to stream-input endpoint | ✓ WIRED | `ws_url` constructed with `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input` |
| `web/server.py` | `tts/base.py` | Chat flow calls `tts_client.synthesize_ws_stream()` | ✓ WIRED | `_tts_stream_to_browser()` line 692 confirmed |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `web/server.py` `/api/tts` | `audio` | `_tts_client_instance.synthesize(clean)` | Yes — delegates to backend HTTP call | ✓ FLOWING |
| `web/server.py` phrase cache | `_TTS_CACHE[sanitized]` | `tts.synthesize(sanitized)` at startup | Yes — populated via real backend call | ✓ FLOWING |
| `web/server.py` chat TTS | `audio_chunk` stream | `tts_client.synthesize_ws_stream(_uncached_text_iter())` | Yes — ElevenLabs WS or Kokoro HTTP | ✓ FLOWING |
| `voice.py` `VoiceOutput._synthesize` | `bytes` | `self._tts.synthesize(text)` | Yes — delegates to TTSClient backend | ✓ FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| TTS protocol methods present | `python3 -c "from orchestrator.tts.base import TTSClient; assert hasattr(TTSClient, 'synthesize_ws_stream'); assert hasattr(TTSClient, 'aclose'); print('OK')"` | `protocol OK` | ✓ PASS |
| ElevenLabsClient has all methods | `python3 -c "from orchestrator.tts.elevenlabs import ElevenLabsClient; assert hasattr(ElevenLabsClient, 'synthesize_ws_stream'); assert hasattr(ElevenLabsClient, 'aclose')"` | `elevenlabs OK` | ✓ PASS |
| KokoroClient has all methods | `python3 -c "from orchestrator.tts.kokoro import KokoroClient; assert hasattr(KokoroClient, 'synthesize_ws_stream'); assert hasattr(KokoroClient, 'aclose')"` | `kokoro OK` | ✓ PASS |
| All 20 TTS tests pass | `python3 -m pytest tests/test_tts_client.py -x -q` | `20 passed in 0.34s` | ✓ PASS |
| No per-call httpx in backends | `grep -c "async with httpx.AsyncClient" elevenlabs.py kokoro.py` | `0` for both | ✓ PASS |
| No ElevenLabs URLs in server.py | `grep -c "api.elevenlabs.io" web/server.py` | `0` | ✓ PASS |
| No hardcoded voice_settings in server.py | `grep -c '"stability"' web/server.py` | `0` | ✓ PASS |
| VoiceOutput imports clean | `python3 -c "from orchestrator.voice import VoiceOutput; print('OK')"` | `VoiceOutput import OK` | ✓ PASS |
| Orchestrator imports clean | `python3 -c "from orchestrator.main import Orchestrator; print('OK')"` | `Orchestrator import OK` | ✓ PASS |
| TTS streaming latency | Requires live ElevenLabs connection | N/A | ? SKIP (human needed) |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| TTS-01 | 02-02-PLAN.md | Web server uses `TTSClient` protocol instead of inline ElevenLabs httpx calls | ✓ SATISFIED | `create_tts_client` in lifespan; all synthesis paths use `_tts_client_instance`; no `api.elevenlabs.io` URLs remain in `server.py` |
| TTS-02 | 02-02-PLAN.md | CLI voice module uses `TTSClient` protocol instead of inline ElevenLabs httpx calls | ✓ SATISFIED | `VoiceOutput` accepts `TTSClient`; `_synthesize()` delegates to protocol; no inline ElevenLabs calls in `voice.py` |
| TTS-03 | 02-03-PLAN.md | TTS protocol extended to support incremental WebSocket streaming | ✓ SATISFIED | `synthesize_ws_stream(AsyncIterator[str]) -> AsyncIterator[bytes]` on protocol, ElevenLabsClient, KokoroClient, and wired into `web/server.py` chat flow |
| TTS-04 | 02-01-PLAN.md | Voice settings consolidated into single config source used by all consumers | ✓ SATISFIED | `tts_stability/similarity_boost/style` in `Settings`; factory passes from config to `ElevenLabsClient`; no hardcoded voice dicts remain anywhere |
| TTS-05 | 02-01-PLAN.md | Persistent httpx client used for TTS calls | ✓ SATISFIED | `self._http = httpx.AsyncClient(timeout=30.0)` in both backends; zero `async with httpx.AsyncClient` in TTS files |
| TTS-06 | 02-01-PLAN.md | `tts_backend`, `tts_local_url`, and `tts_voice_id_local` config fields added | ✓ SATISFIED | All three fields in `Settings` with defaults; `.env.example` documents all new fields |
| TTS-07 | 02-01-PLAN.md | Kokoro TTS backend selectable via config without code changes | ✓ SATISFIED | `create_tts_client()` branches on `settings.tts_backend`; `"local"` instantiates `KokoroClient(base_url=settings.tts_local_url, voice_id=settings.tts_voice_id_local)` |

**All 7 TTS requirements: SATISFIED**

No orphaned requirements — REQUIREMENTS.md maps TTS-01 through TTS-07 exclusively to Phase 2, all accounted for.

---

### Anti-Patterns Found

No anti-patterns detected. Scanned all 9 phase artifacts for TODO/FIXME, placeholder comments, empty implementations, hardcoded voice settings, per-call httpx creation, and ElevenLabs-specific code in consumer files. All clean.

---

### Human Verification Required

#### 1. TTS Streaming Latency

**Test:** Run the web server with a real ElevenLabs API key. Send a chat message that triggers a multi-sentence response. Measure time from message send to first audio chunk received in the browser.
**Expected:** Time-to-first-audio is comparable to the previous inline implementation (sub-500ms for first audio chunk after Claude begins streaming).
**Why human:** Requires a live ElevenLabs WebSocket connection, real audio output, and subjective latency measurement that cannot be done programmatically without external services.

---

### Gaps Summary

None. All 12 observable truths verified. All 7 requirements satisfied. All 9 artifacts exist, are substantive, are wired, and have data flowing through them. No blocker anti-patterns found.

---

_Verified: 2026-03-26_
_Verifier: Claude (gsd-verifier)_
