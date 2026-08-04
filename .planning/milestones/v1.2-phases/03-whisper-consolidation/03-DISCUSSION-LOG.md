# Phase 3: Whisper Consolidation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 03-whisper-consolidation
**Areas discussed:** STT alternatives, Endpoint divergence, Sync vs async, Confidence scoring, Retry strategy, Model upgrade

---

## STT Alternative Evaluation

**Research conducted:** Evaluated NVIDIA Parakeet TDT 0.6B v3, whisper.cpp server, Groq Whisper API, Distil-Whisper large-v3, and Whisper large-v3-turbo.

| Option | Speed | Accuracy | Aviation Prompt | Self-hosted | Verdict |
|--------|-------|----------|-----------------|-------------|---------|
| large-v3-turbo | 6x faster | ~7.75% WER | ✓ Works | ✓ | **Selected** |
| Parakeet | >2000x | ~6.3% WER | ✗ Ignored | ✓ | Deferred |
| Distil-Whisper | 6x faster | ~7.5% WER | ✓ Works | ✓ | Good alternative |
| whisper.cpp | Marginal | Same | ✓ Works | ✓ | Skip |
| Groq | Very fast | Good | ✓ Works | ✗ Cloud | Skip |

**User's choice:** Upgrade to large-v3-turbo + consolidate clients
**Notes:** Parakeet deferred due to prompt parameter being silently ignored by all API wrappers. User explored the issue in depth before deciding.

---

## Endpoint Divergence

| Option | Description | Selected |
|--------|-------------|----------|
| /v1/audio/transcriptions (Recommended) | OpenAI-compatible. Standard across faster-whisper, whisper.cpp, Groq. | ✓ |
| Support both, configurable | Default to OpenAI-compat but allow override | |

**User's choice:** /v1/audio/transcriptions only

---

## Sync vs Async

| Option | Description | Selected |
|--------|-------------|----------|
| Async only (Recommended) | Single async client. Both consumers already async. | ✓ |
| Keep both | Async primary + sync wrapper | |

**User's choice:** Async only

---

## Confidence Scoring

| Option | Description | Selected |
|--------|-------------|----------|
| whisper_client.py's approach (Recommended) | verbose_json with avg_logprob + no_speech_prob. Most complete. | ✓ |
| server.py's approach | Simpler calculation | |
| You decide | Claude's discretion | |

**User's choice:** whisper_client.py's approach

---

## Retry Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Always retry, 3 attempts (Recommended) | Exponential backoff. Resilient for cockpit environments. | ✓ |
| Configurable | max_retries parameter | |
| No retry | Fail fast | |

**User's choice:** Always retry, 3 attempts

---

## Claude's Discretion

- Aviation prompt location (client vs parameter)
- Confidence thresholds
- Protocol vs concrete class (only one backend currently)

## Deferred Ideas

- NVIDIA Parakeet integration — blocked by prompt parameter gap
- STT abstraction layer — premature with single backend
