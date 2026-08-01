# Phase 2: TTS Integration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 02-tts-integration
**Areas discussed:** Voice settings values, Streaming protocol design, TTS phrase cache strategy, Config field naming

---

## Voice Settings Values

| Option | Description | Selected |
|--------|-------------|----------|
| Web server values (Recommended) | {0.75, 0.80, 0.15} — more stable, closer to original voice | |
| CLI voice values | {0.5, 0.75, 0.3} — more expressive | |
| Make configurable via .env | Add TTS_STABILITY, TTS_SIMILARITY_BOOST, TTS_STYLE to Settings | ✓ |

**User's choice:** Make configurable via .env
**Notes:** Follow-up: web server values {0.75, 0.80, 0.15} as defaults.

---

## Streaming Protocol Design

| Option | Description | Selected |
|--------|-------------|----------|
| Add synthesize_ws_stream() method | New protocol method for WebSocket streaming. Accepts async iterator of text chunks, returns async iterator of audio chunks. Fallback for non-WS backends. | ✓ |
| Keep REST streaming, optimize later | Wire synthesize_stream() now, accept small latency regression | |
| You decide | Claude's discretion | |

**User's choice:** Add synthesize_ws_stream() method
**Notes:** Critical for maintaining current latency characteristics.

---

## TTS Phrase Cache Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Keep in web server (Recommended) | Cache stays as web server concern. Client synthesizes, server caches. | ✓ |
| Move into TTSClient | Caching becomes protocol-level. Both consumers get it. | |
| Wrapper/decorator pattern | CachedTTSClient wraps any TTSClient. | |

**User's choice:** Keep in web server
**Notes:** Clean separation of concerns.

---

## Config Field Naming

| Option | Description | Selected |
|--------|-------------|----------|
| TTS_ prefix (Recommended) | TTS_BACKEND, TTS_LOCAL_URL, TTS_VOICE_ID_LOCAL, TTS_STABILITY, etc. | ✓ |
| ELEVENLABS_ prefix for voice settings | Mix of ELEVENLABS_ and TTS_ prefixes | |
| You decide | Claude's discretion | |

**User's choice:** TTS_ prefix
**Notes:** Groups all TTS config together in .env.

---

## Claude's Discretion

- Internal implementation of synthesize_ws_stream() for ElevenLabs
- Kokoro fallback buffering strategy
- Whether to add aclose() to protocol or just concrete classes

## Deferred Ideas

None — discussion stayed within phase scope.
