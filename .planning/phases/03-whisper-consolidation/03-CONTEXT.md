# Phase 3: Whisper Consolidation - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace three divergent Whisper transcription implementations with a single async `WhisperClient`. Upgrade the Whisper model from `medium` to `large-v3-turbo` for better accuracy and speed. The unified client uses the OpenAI-compatible `/v1/audio/transcriptions` endpoint, `whisper_client.py`'s confidence scoring approach, and built-in retry logic.

</domain>

<decisions>
## Implementation Decisions

### Unified Client Architecture
- **D-01:** Single async `WhisperClient` class using `httpx.AsyncClient` (persistent). Replaces: sync `WhisperClient` in `whisper_client.py`, async `VoiceInput.transcribe()` in `voice.py`, async `_transcribe_with_confidence()` in `web/server.py`.
- **D-02:** Use `/v1/audio/transcriptions` endpoint exclusively (OpenAI-compatible). Drop the `/asr` endpoint used by voice.py.
- **D-03:** Async only — no sync client. Both consumers (voice.py, server.py) are already async. The existing sync `WhisperClient` is unused in production paths.
- **D-04:** Follow the TTS pattern from Phase 2: Protocol or clean class interface, persistent httpx client, `aclose()` for lifecycle management.

### Confidence Scoring
- **D-05:** Use `whisper_client.py`'s confidence scoring as canonical: request `verbose_json` response format, extract `avg_logprob` and `no_speech_prob` from segments, compute confidence score. Include proper fallback when verbose data is unavailable.
- **D-06:** Both `transcribe()` (text only) and `transcribe_with_confidence()` (text + score) methods on the unified client, matching the existing `whisper_client.py` pattern.

### Retry Strategy
- **D-07:** Always retry on failure, 3 attempts with exponential backoff. Matches the existing `whisper_client.py` retry logic. Resilient for cockpit environments where transient failures are expected.

### Model Upgrade
- **D-08:** Upgrade Whisper model from `medium` to `large-v3-turbo` via environment variable change in `docker-compose.yml`. Model: `deepdml/faster-whisper-large-v3-turbo-ct2`. Better accuracy (~7.75% vs ~8-9% WER) and ~3x faster inference than medium.
- **D-09:** Update `docker-compose.dev.yml` to document the model override for dev mode (keep `tiny` for fast startup).
- **D-10:** Update `.env.example` to document the `WHISPER_MODEL` setting and the recommended `large-v3-turbo` value.

### Consumer Wiring
- **D-11:** `voice.py` `VoiceInput` receives the `WhisperClient` via constructor (same pattern as `VoiceOutput` with `TTSClient` in Phase 2). Remove inline httpx transcription code.
- **D-12:** `web/server.py` receives the `WhisperClient` via lifespan/app.state (same pattern as TTSClient in Phase 2). Remove `_transcribe_with_confidence()` and inline httpx code.

### Claude's Discretion
- Whether to keep the `AVIATION_PROMPT` in the client or pass it as a parameter
- Internal structure of the confidence calculation (exact thresholds)
- Whether to expose a `WhisperClient` Protocol or just a concrete class (TTS needed a Protocol for multiple backends; Whisper currently has only one backend)
- Handling of the `_whisper_client` global in server.py (already partially addressed by Phase 4's DI refactor, but client creation should use the new class)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Whisper Implementations (to be replaced)
- `orchestrator/orchestrator/whisper_client.py` — Sync WhisperClient with retry, confidence scoring, verbose_json parsing. CANONICAL for confidence scoring logic.
- `orchestrator/orchestrator/voice.py` — `VoiceInput.transcribe()` using `/asr` endpoint, no retry, no confidence
- `web/server.py` — `_transcribe_with_confidence()` function, different confidence calculation, no retry

### Config
- `orchestrator/orchestrator/config.py` — Settings class (whisper_url field exists)
- `.env.example` — Documents WHISPER_URL
- `orchestrator/orchestrator/audio_processing.py` — `AVIATION_PROMPT` constant for decoder biasing

### Docker
- `docker-compose.yml` — Whisper service config (currently pinned to `0.8.3-cpu`)
- `docker-compose.dev.yml` — Dev override with `tiny` model

### Phase 2 Pattern (to follow)
- `orchestrator/orchestrator/tts/base.py` — TTSClient Protocol pattern
- `orchestrator/orchestrator/tts/__init__.py` — Factory pattern
- `orchestrator/orchestrator/main.py` — Client creation + injection into VoiceOutput

### STT Research
- NVIDIA Parakeet explored and deferred — prompt parameter ignored by API wrappers, blocks aviation vocabulary biasing. Revisit when NeMo word-boosting wrappers mature.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `whisper_client.py` confidence scoring logic — extract and async-ify
- `whisper_client.py` retry logic with exponential backoff — reuse pattern
- `AVIATION_PROMPT` in `audio_processing.py` — aviation vocabulary bias
- Phase 2's TTSClient pattern — Protocol, persistent client, aclose(), constructor injection

### Established Patterns
- Persistent `httpx.AsyncClient` (proven in TTS Phase 2)
- Constructor injection of clients into `VoiceInput`/`VoiceOutput` via `Orchestrator`
- Web server lifespan for client creation/cleanup

### Integration Points
- `orchestrator/orchestrator/main.py` — Create WhisperClient, inject into VoiceInput
- `web/server.py` — Create WhisperClient in lifespan, use from routes
- `docker-compose.yml` — Model env var change

</code_context>

<specifics>
## Specific Ideas

- The model upgrade is a one-line env var change with zero code impact — can be its own atomic commit
- NVIDIA Parakeet (>2000x RTFx, ~6.3% WER) was researched as a potential replacement but is blocked by the prompt parameter being ignored in all available API wrappers. Deferred to a future phase when the ecosystem matures. The unified async client makes a future Parakeet swap trivial (just change the URL).

</specifics>

<deferred>
## Deferred Ideas

- **NVIDIA Parakeet integration** — Superior speed/accuracy but `prompt` parameter ignored by API wrappers, blocking aviation vocabulary biasing. Revisit when NeMo word-boosting wrappers support OpenAI-compatible API.
- **STT abstraction layer** (like TTSClient Protocol for multiple backends) — Only one STT backend exists. Add when a second backend (Parakeet, Deepgram) is integrated.

</deferred>

---

*Phase: 03-whisper-consolidation*
*Context gathered: 2026-03-27*
