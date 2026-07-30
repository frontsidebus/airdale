# Tech Stack Review & Voice Architecture Research

**Date:** 2026-07-29
**Scope:** Full tech-stack review of `main` (`16a2401`), plus web research on open-source alternatives with emphasis on the voice agent space
**Constraints set by user:** hybrid deployment (local default, cloud fallback); speech-to-speech rearchitecture on the table
**Companion doc:** `.planning/v1.3-RECONCILIATION.md`

---

## Executive summary

Three findings, in priority order:

1. **The TTS abstraction layer was silently reverted four months ago.** `VoiceOutput` no longer uses the `TTSClient` protocol — Phase 03-02 undid Phase 02-02's verified work and documented the reverted state as if it were correct. The CLI voice path is back to inline ElevenLabs with hardcoded voice settings. This is a prerequisite fix for any voice work.

2. **Speech-to-speech is architecturally incompatible with keeping Claude.** Every speech-native option requires an open-weight LLM backbone to train an audio adapter against. Claude is API-only. So "adopt S2S" and "keep Claude as MERLIN's brain" are mutually exclusive — this is the decisive constraint, and no amount of engineering removes it.

3. **The biggest available latency win needs no model change.** MERLIN uses a fixed 400ms silence timeout for turn detection. Current-generation semantic turn detectors and adaptive interruption handling are the single largest improvement to *perceived* responsiveness, and they are orthogonal to which STT/TTS/LLM you run.

**Recommendation:** keep the cascade with Claude as the safety-critical path, fix the protocol layer, upgrade turn-taking, and swap in local STT/TTS behind the restored protocol. Treat speech-native models as a **flight-phase-routed fast path** for low-stakes conversation — never for numerical or procedural content. Details in §5–7.

---

## Part 1 — Current stack

### 1.1 As documented in `CLAUDE.md`

| Layer | Technology |
|---|---|
| Orchestrator | Python 3.11+ async, hatch |
| Web | FastAPI + WebSocket |
| Telemetry | Python/FastAPI hub, `/ws/ingest` + `/ws/telemetry` |
| MSFS adapter | C# / .NET 8, out-of-process, event-driven pump |
| Inference | Anthropic Claude with tool use |
| RAG | ChromaDB + sentence-transformers |
| STT | faster-whisper `medium` via Docker |
| TTS | ElevenLabs `eleven_multilingual_v2` streaming |
| VAD | Silero |

### 1.2 What is actually on `main`

Drift, all verified in code:

| Claim in `CLAUDE.md` | Reality |
|---|---|
| STT = faster-whisper only | `stt_backend` **defaults to `deepgram`**; `stt/` package has `base.py` + `deepgram.py`; Whisper is the fallback |
| TTS = ElevenLabs only | `tts_backend` **defaults to `cartesia`**; `tts/` has `cartesia.py`, `elevenlabs.py`, `kokoro.py` |
| Whisper `medium` | `whisper_model` default is `large-v3-turbo` (Phase 03) |
| 12 orchestrator modules | 25 modules; 13 (~3,900 lines) undocumented — see reconciliation §5 |
| 4 docs | 14 docs; 10 undocumented |
| 361 tests | 38 web + large orchestrator suite; `command_safety.py` untested |

Additions worth naming: `reranker.py` (RAG reranking), `chunking.py`, `aviation_tools.py` (558 lines), `validation.py`, `emergency.py`, plus the whole proactive-copilot cluster (`callouts.py`, `deviation_monitor.py`, `proactive_monitor.py`, `checklist_manager.py`).

### 1.3 Voice stack regression — the blocking finding

`c12dae9` (Phase 02-02) made `VoiceOutput` delegate to the `TTSClient` protocol. Verified: 12/12 truths, TTS-02 SATISFIED, "no ElevenLabs imports or httpx TTS calls in `voice.py`."

`a1b508a` (Phase 03-02) reverted it:

```diff
-        tts_client: TTSClient,
+        api_key: str,
-        self._tts = tts_client
+        self._api_key = api_key
-            return await self._tts.synthesize(text)
+        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}"
+            "xi-api-key": self._api_key,
+                "stability": 0.5,
```

That summary claims *"httpx retained in voice.py because `VoiceOutput._synthesize()` still uses `httpx.AsyncClient` for ElevenLabs TTS"* — describing state it had just created as pre-existing. Same plan as the async-WhisperClient false premise.

**Undetected for four months** because Phase 03 verification only checked Whisper truths, Phase 02's had already passed, and `voice.py` has no test file.

Note the restored `stability: 0.5, similarity_boost: 0.75, style: 0.3` — the values recorded as causing volume inconsistency. The tuned `0.75/0.80/0.15` applies only on the web path.

### 1.4 Two divergent voice stacks

| | Web server | CLI (`voice.py` / `main.py`) |
|---|---|---|
| TTS | Cartesia, + ElevenLabs / Kokoro | ElevenLabs, hardcoded inline |
| STT | Deepgram, + Whisper | Whisper only |
| Voice settings | From config | Hardcoded `0.5/0.75/0.3` |
| Uses `TTSClient` protocol | Partially | No |

### 1.5 Config-layer defects (verified live with `.env` isolated)

```
tts_backend (code default) : cartesia
tts_configured            : False      <-- ignores cartesia entirely
voice_id                  : ''         <-- returns elevenlabs_voice_id
create_tts_client(...)    : ValueError: Unknown TTS backend: 'cartesia'.
                            Expected 'elevenlabs' or 'local'.
```

- `create_tts_client()` is **dead code** — no production caller; only its own docstring and tests reference it. It raises on the code-default backend.
- `Settings.tts_configured` / `Settings.voice_id` were never extended past Phase 02's ElevenLabs/Kokoro pair.
- `main.py:79` gates TTS on `elevenlabs_api_key` regardless of `tts_backend`.

Phase 02 established "backend-aware config properties" and "factory injection" as patterns. Both regressed when Cartesia and Deepgram were added; the web server grew a parallel path instead.

---

## Part 2 — The decisive constraint on speech-to-speech

Every speech-native architecture needs an LLM whose weights it can attach an audio encoder/adapter to. **Claude has no open weights.** Therefore:

> Adopting any speech-to-speech or speech-LLM architecture means replacing Claude as MERLIN's reasoning engine.

That is not an engineering obstacle to route around — it is a product decision about what MERLIN is. Everything below follows from it.

### 2.1 The three architectural bets

| | Audio-native full-duplex | Thinker–Talker | Cascade (current) |
|---|---|---|---|
| Models | Moshi (Kyutai, 7B), PersonaPlex (NVIDIA, Jan 2026, 7B) | Qwen2.5/3-Omni | Any STT + LLM + TTS |
| Latency | 160ms / 205ms | 211–257ms | 1.5–3s typical prod; sub-1s achievable streaming |
| Tool calling | **No** | **Yes** | **Yes** |
| Text reasoning | Degraded | Preserved (Thinker is text/hidden-state) | Fully preserved |
| RAG | Architecturally difficult — retrieval 50–300ms vs 160–200ms budget | Cleaner | Trivial |
| Duplex | True full-duplex | Near-duplex | None |
| Keeps Claude | No | No | **Yes** |

Moshi's task-adherence score is **1.26/5** (PersonaPlex 4.34/5) — audio-native models are tuned for conversational naturalness, not "rigid procedural adherence." For a checklist-driven aviation copilot that is disqualifying on its own.

### 2.2 Ultravox v0.7 — the most interesting near-miss

Genuinely notable, and the closest thing to a fit:

- **MIT licensed**, weights on HF (`fixie-ai/ultravox-v0_7-glm-4_6`), training code public, self-hostable
- Speech encoder (`whisper-large-v3-turbo`) + trained adapter + frozen LLM backbone (GLM 4.6)
- **Audio-in → text-out.** It is a speech *understanding* model, not audio-out — you still supply TTS
- v0.7 explicitly targeted **better instruction following and more reliable tool calling** in response to user demand; reported ~20% inference improvement
- On Ultravox's own Voice Agent Bench it "matched or exceeded the cascading setups they had been using"
- Can be retrained against any open-weight backbone

Why it is compelling for MERLIN specifically: **text output means `validation.py` survives.** It collapses STT+LLM into one model without blinding the numerical-accuracy layer.

Why it still is not the answer: the backbone is GLM 4.6. Using Ultravox replaces Claude. You would be trading Claude's aviation reasoning, the tuned MERLIN persona, and a working tool-use implementation for ~1 second of latency.

*(The HF card lists "0.7B params," which is inconsistent with a GLM-4.6 backbone — likely metadata describing the adapter. Don't size hardware off that number without checking.)*

---

## Part 3 — Why the cascade is right for MERLIN specifically

Three MERLIN-specific reasons, beyond the generic trade-offs.

### 3.1 `validation.py` operates on text and would die

```
"Response validation for aviation-critical numerical data.
 Scans Claude's responses for V-speeds, altitudes, frequencies..."
```

`ResponseValidator._check_vspeeds()`, `_check_frequency()`, per-aircraft `AircraftLimits` with `max_altitude`. This layer takes `response_text`. An audio-out model produces no text to scan. You would be deleting the numerical-hallucination guard from an aviation assistant.

### 3.2 The canonical S2S failure mode *is* MERLIN's problem domain

The literature's stock example of cascade ASR risk — *"a mis-transcription of 'transfer 100' instead of 'transfer 1000'"* — is precisely MERLIN's content: altitudes, headings, frequencies, squawk codes, flight levels. Note this cuts **both** ways:

- It argues *against* naive cascade (ASR errors propagate, 8–12% WER on noisy speech, and a cockpit is noisy)
- It argues *harder against* S2S, because in a cascade you can validate the text; in S2S there is nothing to validate

MERLIN's existing mitigations — `AVIATION_PROMPT` biasing, the ICAO `tts_preprocessor`, `validation.py`, audio preprocessing — all live at text or signal boundaries that S2S removes.

### 3.3 Independent guidance says keep cascade for exactly MERLIN's profile

Cascade is recommended for **high-stakes work needing line-by-line transcripts** and **debug-heavy environments where failure isolation is critical**. MERLIN is both. S2S failures are *"silent and hard to attribute"*; cascade lets you tell an ASR error from an LLM hallucination.

### 3.4 What survives either way

`emergency.py` is **telemetry-driven**, not audio-driven — it detects engine failure/fire/decompression from `SimState` deltas and emits pre-validated responses straight to TTS, bypassing the LLM. That fast path is architecture-independent and is genuinely good design. Keep it whatever else changes.

---

## Part 4 — The real latency picture

Worth being honest about where MERLIN's latency actually goes, because "adopt S2S for 200ms" compares against the wrong baseline.

Cascade latency is dominated by:

1. **Turn detection** — MERLIN waits a fixed **400ms of silence** (`SileroVAD(threshold=0.5, silence_ms=400)`) before it even starts. Pure dead time.
2. **STT** — batch Whisper vs streaming; a streaming transducer emits partials during speech
3. **LLM time-to-first-token** — Claude, network-bound
4. **TTS time-to-first-audio** — already optimized (Cartesia, WS streaming, phrase cache)

Items 1 and 2 are where the cheap wins are, and neither requires touching the LLM. The 400ms fixed timeout is the single biggest lever on *perceived* responsiveness.

---

## Part 5 — Recommendation: flight-phase-routed architecture

MERLIN already varies behavior by flight phase — `FlightPhaseDetector` with hysteresis injects a style directive per phase (PREFLIGHT allows banter, TAKEOFF demands brevity). **Extend that existing mechanism from response style to architecture selection.**

| Phase | Content profile | Path |
|---|---|---|
| PREFLIGHT, TAXI, CRUISE (idle chat) | Banter, general aviation Q&A, low stakes | **Fast path** — local speech-LLM or trimmed cascade; naturalness over precision |
| TAKEOFF, APPROACH, LANDING | Terse, numeric, procedural | **Validated cascade** — Claude, text in loop, `validation.py` enforced |
| Any emergency | Time-critical | **`emergency.py` fast path** — already bypasses the LLM entirely |
| Any command execution (`set_aircraft_control`) | Actuates the aircraft | **Validated cascade only** — plus `command_safety.py` |

The hard rule: **numerical, procedural, and command content never travels an unvalidated path.**

This is also where the industry has landed independently — hybrid deployments using S2S for simple fast exchanges and falling back to cascade for complex reasoning and tool-heavy interactions. The difference is that MERLIN has a *better routing signal than most*: it already knows the flight phase, which is a genuine proxy for stakes.

It also fits the restored protocol: phase-routing is a factory decision, not a rewrite.

---

## Part 6 — Component options for the hybrid

### STT

| Option | Notes | Verdict |
|---|---|---|
| **Parakeet TDT** (NVIDIA, open) | RTFx 2,000–2,800; streaming down to 240ms; RNN-T constant memory, emits during speech; ~25–30× Whisper throughput on same GPU; English-focused, mid-pack raw accuracy | **Local default candidate.** Streaming is the point, not WER. |
| Canary-Qwen 2.5B | #1 Open ASR Leaderboard, 5.63% WER; slower (Parakeet ~6.5× faster) | Accuracy fallback for non-realtime |
| Moonshine v2 | Purpose-built latency-critical streaming encoder | Watch; good on constrained hardware |
| faster-whisper `large-v3-turbo` | Current fallback; batch, 99+ languages | Keep as the accuracy/multilingual fallback |
| Deepgram (cloud) | Current default, already integrated | Keep as cloud fallback |

Aviation caveat: Whisper's `initial_prompt` vocabulary biasing (decision #12) is a real asset. Confirm any replacement offers equivalent domain biasing — transducer models often expose this differently or not at all. **Test aviation-term WER before switching, not general WER.**

### TTS

| Option | TTFA | Notes |
|---|---|---|
| **Piper** | ~40ms | Fastest local by a wide margin; RTF ~0.03; runs on a Pi 4; flatter/synthetic voice |
| **Kokoro-82M** | faster-than-realtime, ~2–3GB VRAM | **Already integrated.** Fixed voice set, no cloning. Best effort/quality balance for local |
| Orpheus (3B) | ~200ms | Near-ElevenLabs quality, inline emotion tags, zero-shot cloning; heavier |
| Cartesia (cloud) | current default | Keep as low-latency cloud path |

For a Navy-test-pilot persona, Kokoro or Orpheus fit the character better than Piper. Piper is the right choice only if you want a fallback that runs anywhere.

### Turn detection — the highest-value change

Current: fixed 400ms silence timeout. Available now:

- **Semantic turn detection** (Pipecat `SmartTurnDetection`) — an LLM-based classifier predicting whether the speaker has actually finished, instead of timing silence. Handles mid-sentence pauses, which a cockpit produces constantly.
- **Adaptive interruption + dynamic endpointing** (LiveKit Agents v1.5.6) — reported 86% precision / 100% recall on interruption handling, with preemptive generation on by default.

Either eliminates most of the 400ms dead time *and* reduces false-triggers on pauses. This is the change most likely to make MERLIN feel like current-generation voice AI, and it touches neither the model nor the persona.

### Frameworks

**Pipecat** (Daily, 100% OSS, v1.0.0 April 2026) and **LiveKit Agents** (v1.5.6) both keep providers swappable and support cascade and S2S behind one abstraction.

My read: **borrow the turn-detection and interruption components; do not adopt a framework wholesale.** MERLIN's differentiators — telemetry-driven proactive callouts, flight-phase state machine, `command_safety` gating, emergency fast paths — are not what these frameworks model, and a full port risks the same silent-revert class of failure this review just uncovered. Revisit if barge-in and turn-taking maintenance become a recurring cost.

---

## Part 7 — Sequencing

**Step 0 — Restore the protocol layer (prerequisite, small).**
Re-apply `c12dae9`'s `VoiceOutput(tts_client: TTSClient)`; register `cartesia` in `create_tts_client()` or delete the dead factory; extend `tts_configured` / `voice_id` to all backends; fix `main.py:79`; add an `STTClient` protocol mirroring `TTSClient` so Deepgram/Whisper are peers. **Write `test_voice.py`** — its absence is why this regressed silently.

**Step 1 — Turn detection upgrade.** Biggest perceived-latency win, no model change, no persona risk.

**Step 2 — Local STT behind the protocol.** Parakeet TDT streaming as local default, Deepgram cloud fallback, Whisper accuracy fallback. Gate on **aviation-term WER**, not general WER.

**Step 3 — Confirm local TTS parity.** Kokoro is already wired; verify TTFA and ICAO-preprocessor compatibility, then make it the local default with Cartesia as cloud fallback.

**Step 4 — Phase-routed fast path** (§5), only after 0–3 land and the protocol makes it a config decision.

**Step 5 — Spike, don't migrate.** Time-box an Ultravox v0.7 evaluation as a *transcription* front-end (audio → text → Claude), measuring aviation-term accuracy against Parakeet and Whisper. That tests the interesting part of speech-LLMs while keeping Claude. Full S2S adoption should require an explicit decision to give up Claude, `validation.py`, and failure attribution — recorded as an ADR, not arrived at incrementally.

---

## Sources

- [Speech-to-Speech Models in 2026: Three Architectural Bets](https://ai.ksopyla.com/posts/voice-to-voice-models-2026-review/) — architecture comparison, latency, tool-calling support, Moshi/PersonaPlex task adherence
- [Are Speech-to-Speech Models Ready to Replace Cascade Models? — Hamming AI](https://hamming.ai/blog/are-speech-to-speech-models-ready-to-replace-cascade-models) — Voice Agent Bench, cascade-retention cases
- [Introducing Ultravox v0.7 — Ultravox](https://www.ultravox.ai/blog/introducing-ultravox-v0-7-the-world-s-smartest-speech-understanding-model) — GLM 4.6 backbone, tool calling, instruction following
- [Ultravox v0.7 GLM-4.6 model card — Hugging Face](https://huggingface.co/fixie-ai/ultravox-v0_7-glm-4_6) — MIT license, audio-in/text-out, architecture
- [Ultravox: An open-weight alternative to GPT-4o Realtime](https://www.ultravox.ai/blog/ultravox-an-open-weight-alternative-to-gpt-4o-realtime) — self-hosting, backbone flexibility
- [Speech-to-Speech vs Cascade — Deepgram](https://deepgram.com/learn/speech-to-speech-vs-cascade-voice-agent-architecture) — error propagation, observability
- [Cascaded vs Speech-to-Speech — Inworld](https://inworld.ai/resources/cascaded-vs-speech-to-speech-voice-architecture) — latency and cost ranges
- [Cascaded Voice Agents vs Speech-to-Speech: Tradeoffs in 2026 — Gradium](https://gradium.ai/content/cascaded-voice-agent-vs-speech-to-speech-2026) — WER on noisy speech, domain-vocabulary compound failures
- [RealTime AI Agents frameworks comparison: LiveKit, Pipecat and TEN](https://medium.com/@ggarciabernardo/realtime-ai-agents-frameworks-bb466ccb2a09) — framework comparison
- [Pipecat vs LiveKit (2026) — Evalgent](https://www.evalgent.com/blog/pipecat-vs-livekit) — SmartTurnDetection, adaptive interruption, version/date facts
- [Voice agent frameworks — The Voice AI Wiki](https://soniox.com/wiki/voice-agent-frameworks) — provider swappability, hybrid deployment patterns
- [Best open source speech-to-text model in 2026 — Northflank](https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks) — Parakeet RTFx, Canary-Qwen WER
- [parakeet-unified-en-0.6b — Hugging Face](https://huggingface.co/nvidia/parakeet-unified-en-0.6b) — streaming latency, TDT architecture
- [Best open-source STT models — Gladia](https://www.gladia.io/blog/best-open-source-speech-to-text-models) — leaderboard positions
- [Kokoro vs Piper vs XTTS v2 — Contra Collective](https://contracollective.com/blog/kokoro-vs-piper-vs-xtts-local-text-to-speech-m5-max-2026) — Piper 40ms TTFA, RTF 0.03
- [Orpheus TTS Setup 2026 — Local AI Master](https://localaimaster.com/blog/orpheus-tts-setup-guide) — Orpheus ~200ms, emotion tags
- [Best Self-Hosted TTS Models in 2026 — Seven Labs](https://www.sevenlabs.site/blogs/best-self-hosted-tts-models-2026) — Kokoro VRAM/efficiency profile
- [Moshi Real-Time Speech-to-Speech — Local AI Master](https://localaimaster.com/blog/moshi-realtime-speech-guide) — Moshi latency, Mimi codec, serving stack
- [Qwen3-Omni on SiliconFlow](https://www.siliconflow.com/blog/qwen3-omni-now-on-siliconflow-alibaba-s-next-gen-multimodal-foundation-model) — Thinker-Talker, function calling, first-packet latency
