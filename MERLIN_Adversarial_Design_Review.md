# MERLIN / Airdale — Adversarial Design Review

## Conversational AI Red-Team Exercise

**Date:** April 2, 2026
**Reviewer perspective:** Conversational AI systems engineer specializing in voice pipelines, low-latency speech, and aviation-domain NLP
**Scope:** Full architecture, tech stack, voice pipeline, RAG, tooling, and UX — with refactor recommendations

---

## Executive Summary

MERLIN is a well-architected first prototype with clean separation of concerns, solid prompt engineering, and thoughtful aviation-domain handling (ICAO phraseology, flight-phase awareness, TTS preprocessing). The codebase is production-grade Python with proper async patterns, graceful degradation, and good test coverage intentions.

However, the **voice pipeline is a full generation behind the current state of the art**, and several architectural decisions that were reasonable 6-12 months ago are now significant competitive liabilities. The core issue is that MERLIN uses a **cascading STT→LLM→TTS pipeline with batch-mode Whisper**, while the industry has moved to streaming ASR with integrated turn detection, sub-300ms TTS engines, and speech-to-speech models that eliminate the cascade entirely.

**Bottom line:** The orchestration layer, prompt engineering, tool architecture, and domain knowledge are strong. The voice I/O stack needs to be ripped out and replaced. The RAG system needs a meaningful upgrade. Several missing capabilities (NOTAM/weather tools, ADS-B, structured aviation data) need to be built.

---

## 1. Voice Pipeline — CRITICAL: Replace Entirely

### 1.1 STT: Whisper Is the Wrong Tool

**Current:** `faster-whisper-server` (fedirz) running `large-v3-turbo` on CPU via Docker, accessed over HTTP REST with batch transcription.

**Problems:**

The entire audio capture → encode WAV → HTTP POST → wait for full transcription → return text pipeline adds **1-3 seconds of latency per turn**. This is the single biggest UX problem. In a cockpit context where sub-second response matters, this is unacceptable.

Whisper is a batch transcription model. It was designed to transcribe recordings, not live speech. It has no streaming mode — you must send the complete utterance before getting any text back. The `faster-whisper-server` wraps this in an HTTP API, but the fundamental limitation remains: **zero partial results while the user is still speaking.**

The `medium` model default in docker-compose (overridden to `large-v3-turbo` in config) running on CPU adds further latency. Even on GPU, Whisper's architecture means you're waiting for the full utterance before processing begins.

The aviation vocabulary biasing via `initial_prompt` is a reasonable workaround but is fundamentally limited — it's a soft hint, not a constrained decoder. Whisper will still hallucinate on aviation terms it hasn't seen enough of in training data.

**Recommendation — Replace with Deepgram Nova-3 or Deepgram Flux:**

Deepgram Nova-3 provides sub-300ms streaming STT with WebSocket-based persistent connections. It sends partial transcripts *while the user is still speaking*, which means the LLM can start processing before the pilot finishes their sentence. Deepgram Flux goes further by integrating **end-of-turn detection directly into the STT model**, eliminating the need for separate VAD entirely. This alone can cut 200-600ms from the response loop.

Key advantages for the MERLIN use case: Deepgram has demonstrated performance in aviation and noisy-environment deployments (their docs explicitly mention aviation use cases). Their keyterm prompting feature is more robust than Whisper's initial_prompt for domain vocabulary. Cost is approximately $0.0043/min — trivial for a sim copilot.

**Alternative — OpenAI GPT-4o-Transcribe:** If you want to stay within the Anthropic+OpenAI ecosystem, OpenAI's latest transcription models have state-of-the-art accuracy and handle accents and noisy environments well. However, they're 2-3x more expensive than Deepgram and don't have the same streaming latency characteristics.

**Self-hosted alternative — Parakeet-TDT (NVIDIA):** If you want to stay self-hosted/local, NVIDIA's Parakeet-TDT models run on a single consumer GPU with competitive accuracy and true streaming support via NVIDIA Riva. This would replace the Docker Whisper container.

### 1.2 VAD: Silero Is Adequate but Misplaced

**Current:** Silero VAD in `audio_processing.py` with RMS fallback, running in the voice input pipeline.

The Silero VAD implementation is solid — 400ms silence detection, proper reset between utterances. But it's solving the wrong problem in the wrong place. With a streaming STT like Deepgram Flux, turn detection is integrated into the speech recognition model itself, which has access to **linguistic context** (not just acoustic energy) to determine when the speaker is done. A pure acoustic VAD can't distinguish "pause to think" from "finished speaking" — a speech-aware model can.

**Recommendation:** If you move to Deepgram Flux, remove the VAD entirely and let the STT handle turn detection. If you stay with a non-Flux STT, keep Silero but move it server-side and feed it streaming audio chunks rather than buffering entire utterances.

### 1.3 TTS: ElevenLabs Is Reasonable but Suboptimal

**Current:** ElevenLabs `eleven_multilingual_v2` via both REST and WebSocket streaming APIs, with Kokoro as a local fallback.

ElevenLabs is a defensible choice for voice quality, and the WebSocket streaming implementation in `server.py` is well-done — it pipes sanitized text chunks through a persistent connection and forwards audio to the browser as it arrives. The barge-in cancellation works correctly.

**Problems:**

`eleven_multilingual_v2` is not the latest model. ElevenLabs v3 with Audio Tags dropped in late 2025 and provides fine-grained emotional control — you could direct MERLIN to speak with urgency during emergencies or with relaxed warmth during cruise, matching the phase-based personality system you've already built. The current voice settings (`stability: 0.75, similarity_boost: 0.80, style: 0.15`) are static across all flight phases.

The sentence-boundary buffering in `_stream_response` (splitting at `.!?\n`) introduces unnecessary latency for short callouts. When MERLIN says "V1." — that's a two-character response that still has to wait for the sentence boundary detection, synthesis, MP3 encoding, WebSocket transmission, and browser playback. For time-critical callouts, this pipeline adds 500ms-1s of unnecessary delay.

The Kokoro fallback (`kokoro.py`) is a good idea for offline/local use, but the 82M parameter model will produce noticeably lower quality speech than ElevenLabs, especially for the kind of authoritative military-pilot persona MERLIN requires.

**Recommendations:**

1. Upgrade to ElevenLabs v3 and use Audio Tags to dynamically adjust voice characteristics per flight phase. Map your existing `_PHASE_STYLE` dict to ElevenLabs emotional presets.
2. For time-critical callouts (takeoff, approach, landing phases), bypass sentence buffering entirely. Send the text to TTS immediately without waiting for sentence boundaries.
3. Evaluate **Cartesia Sonic-3** as a potential replacement. It achieves 90ms TTS latency — roughly 3-5x faster than ElevenLabs — with fine-grained emotional control. For a latency-critical cockpit application, this could be transformative.
4. For the local fallback, evaluate **Microsoft VibeVoice-Realtime-0.5B** (182ms TTFB, 41 languages, runs on CPU) or **fish-speech-1.5** (200ms TTFB, MOS 4.70) as replacements for Kokoro.

### 1.4 The Nuclear Option: Speech-to-Speech

The elephant in the room is **OpenAI's Realtime API with `gpt-realtime`**. This is a single model that handles audio input → reasoning → audio output in one pass, eliminating the entire STT→LLM→TTS cascade. It supports function calling, interruption handling, and VAD natively.

**Why this matters for MERLIN:** The Realtime API handles barge-in, turn detection, tool calls, and natural speech in a single WebSocket connection. Your entire `voice.py`, `whisper_client.py`, `audio_processing.py`, and most of the TTS pipeline could be replaced with a single WebSocket connection to OpenAI.

**Why you probably shouldn't do this (yet):**

1. You lose Claude. MERLIN's prompt engineering is tuned for Claude's strengths — the persona, tool use patterns, and response quality are all built around the Anthropic API. GPT-realtime's instruction following is improving but isn't at Claude's level for complex procedural adherence.
2. You lose control over individual pipeline components. With the cascade, you can independently tune STT accuracy, LLM reasoning, and TTS quality. With speech-to-speech, it's a black box.
3. Latency in extended sessions degrades. Testing shows median turn latency of 2.24 seconds with spikes to 4+ seconds in long conversations — worse than a well-optimized cascade pipeline.
4. Function calling accuracy at 66.5% on ComplexFuncBench means tool use (your sim state queries, airport lookups, manual searches) will be less reliable than Claude's tool use.

**My recommendation:** Keep Claude as the brain. Replace the ears and mouth. The hybrid cascade with streaming STT + Claude + fast TTS will outperform speech-to-speech for your use case where tool calling accuracy and procedural adherence matter more than raw latency.

---

## 2. TTS Preprocessing — STRONG, Minor Gaps

### 2.1 What's Working Well

The `tts_preprocessor.py` module is genuinely impressive. The ICAO digit-to-word mapping (`tree`, `fife`, `niner`), flight level expansion, heading/frequency/squawk handling, runway designator parsing, and altitude-to-natural-number conversion are all correct and well-tested. The ordering of transformations (flight levels before general altitude, headings before general numbers) shows real domain understanding.

The aviation acronym dictionary is comprehensive and correctly distinguishes between pronounceable acronyms (NOTAM, SIGMET, ATIS) and those that need letter-by-letter expansion (IFR, VFR, GPS).

### 2.2 Gaps

**Missing transformations:**

- **Altimeter settings in millibars** (e.g., "QNH 1013" works, but "1013 hectopascals" or "1013 millibars" doesn't get expanded)
- **ATIS information letters** ("Information Alpha" vs "Information A")
- **Transponder modes** ("Mode Charlie" vs "Mode C")
- **Bearing/radial notation** ("the 270 radial" should be "the two seven zero radial")
- **Time references** — "1430 Zulu" should be "one four three zero Zulu" but isn't handled
- **Temperature** — "minus 12 degrees" doesn't get the "minus one two degrees" ICAO treatment

**Edge cases in existing transformations:**

- The frequency regex requires a context word prefix (`on`, `frequency`, `tower`, etc.). A bare "121.5" in text won't be expanded, but "emergency frequency 121.5" will. This is mostly correct behavior, but MERLIN might output a frequency without a context word.
- The altitude regex `\d{1,3}(?:,?\d{3})?\s*(ft|feet)` won't match "35,000 feet" (fails because `\d{1,3}` captures "35" and `,?\d{3}` captures ",000" but there's no provision for the full pattern). Test this.

---

## 3. RAG / Context Store — NEEDS UPGRADE

### 3.1 Current State

ChromaDB with `sentence-transformers` embeddings, character-based chunking (1000 chars, 200 overlap), cosine similarity, and an in-memory TTL cache per flight phase. Documents are stored in a single `merlin_docs` collection.

### 3.2 Problems

**Chunking strategy is naive.** Character-based splitting at 1000-char boundaries with 200-char overlap will regularly split mid-sentence, mid-paragraph, and mid-procedure. For aviation documents — where a checklist item, a limitation, or a procedure step is a semantically complete unit — this destroys retrieval quality. A checklist like "Before Starting Engine: 1. Preflight inspection COMPLETE 2. Passenger briefing COMPLETE 3. Seats, belts, harnesses ADJUSTED and LOCKED" could be split across two chunks, making neither chunk independently useful.

**Embedding model is unspecified/default.** ChromaDB's default embedding function uses `all-MiniLM-L6-v2`, which is a general-purpose sentence transformer with no aviation domain knowledge. Aviation terminology, abbreviations, and procedural language will have poor embedding quality. "V1" (a V-speed), "V1" (a version number), and "V-1" (a WWII rocket) will all embed similarly.

**No metadata-driven filtering beyond aircraft type.** The `ContextStore.query` method supports a `where` filter but only uses `aircraft_type`. There's no filtering by document type (checklist vs. manual vs. regulation), section (systems vs. procedures vs. limitations), or relevance category.

**No relevance scoring or re-ranking.** Results are returned purely by cosine distance with no cross-encoder re-ranking. For aviation queries where precision matters ("what's the Vfe for the Cessna 172?"), a two-stage retrieve→re-rank pipeline would significantly improve accuracy.

**Recommendations:**

1. **Switch to semantic chunking.** Use a recursive text splitter that respects document structure — split on headers, numbered lists, and paragraph boundaries rather than character counts. For aviation documents specifically, write a custom splitter that preserves checklist items, procedure steps, and limitation entries as atomic units.
2. **Upgrade the embedding model.** At minimum, use `all-mpnet-base-v2` or `bge-large-en-v1.5`. Ideally, fine-tune on aviation text (POHs, AIM, FAR) — even a small fine-tuning dataset dramatically improves domain retrieval.
3. **Add metadata fields:** `document_type` (POH, checklist, AIM, regulation), `section` (systems, limitations, procedures, performance), `aircraft_type`, `aircraft_variant`, `source_page`.
4. **Add a cross-encoder re-ranker** as a second stage. `cross-encoder/ms-marco-MiniLM-L-6-v2` is fast and dramatically improves precision for factual aviation queries.
5. **Consider replacing ChromaDB with a more capable vector store** if you're scaling. Qdrant or Weaviate both support hybrid search (vector + keyword), which is critical for aviation queries that include specific numbers, codes, or identifiers that pure semantic search struggles with.

---

## 4. Tool Architecture — GOOD Foundation, Missing Critical Tools

### 4.1 What's Working

The five existing tools (`get_sim_state`, `lookup_airport`, `search_manual`, `get_checklist`, `create_flight_plan`) cover the basics well. The tool definitions use clear descriptions that guide Claude's tool selection. The agentic loop in `claude_client.py` correctly handles multi-turn tool use with streaming. The `create_flight_plan` tool properly chains `lookup_airport` calls.

### 4.2 Missing Tools (Required by Your Spec)

Your requirements explicitly call for FAA NOTAMs, weather reports, ADS-B data, and other aviation OSINT. None of these exist yet.

**Tools to build:**

1. **`get_notams(identifier)`** — Hit the FAA NOTAM API (https://notams.aim.faa.gov/notamSearch or the v2 API). Parse D-NOTAMs, FDC NOTAMs, TFRs. This is critical for preflight and descent phases. The TTS preprocessor will need NOTAM-specific handling (NOTAM format is dense with abbreviations).

2. **`get_weather(identifier)`** — Fetch METAR/TAF from aviationweather.gov (or the ADDS text server). Parse into structured data. Claude can interpret raw METAR, but providing parsed wind/visibility/ceiling/remarks reduces hallucination risk on critical weather data.

3. **`get_adsb_traffic(lat, lon, radius_nm)`** — Query ADS-B Exchange, OpenSky Network, or ADSBHub for nearby traffic. Return callsign, altitude, heading, distance, closure rate. This enables traffic advisories during cruise.

4. **`get_charts(identifier, chart_type)`** — Retrieve approach plates, airport diagrams, SID/STAR charts from the FAA's DTPP (Digital Terminal Procedures Publication). Return as an image or structured data.

5. **`calculate_performance(aircraft, weight, altitude, temperature)`** — Compute takeoff/landing distances, climb rates, fuel burn using performance tables from the POH (stored in RAG). This is where RAG + tool use combine — retrieve the relevant performance table, then compute.

6. **`get_airspace_info(lat, lon, altitude)`** — Query airspace classification, MOAs, restricted areas, TFRs for a given position and altitude. Critical for VFR flight planning.

### 4.3 Tool Execution Safety

The current `_execute_tool` method has no timeout handling. A hung HTTP call to `aviationapi.com` will block the entire response. Add `asyncio.wait_for` with reasonable timeouts per tool. For aviation data tools, 5-10 seconds is appropriate; for sim state queries, 1 second.

---

## 5. LLM Configuration — Minor Tuning Needed

### 5.1 Model Selection

`claude-sonnet-4-20250514` is a reasonable choice balancing speed and capability. For a cockpit copilot where response latency matters, Sonnet is the right call over Opus. However, you should evaluate whether Claude Haiku 4.5 could handle the simpler interactions (acknowledgments, short callouts, single-value queries) while reserving Sonnet for complex reasoning (flight planning, emergency procedures, teaching moments).

A two-model strategy — Haiku for `query_type == "short"` and Sonnet for `"normal"` and `"briefing"` — could cut LLM latency in half for 60%+ of interactions without sacrificing quality where it matters.

### 5.2 Temperature

`temperature: 0.7` is too high for a cockpit copilot. When MERLIN says "descend and maintain three thousand five hundred," that number needs to be deterministic, not creative. For aviation procedures, checklists, and numerical data, temperature should be 0.1-0.3. For cruise-phase banter and teaching, 0.5-0.7 is fine.

**Recommendation:** Make temperature dynamic based on flight phase and query type. Critical phases (takeoff, approach, landing, emergency) → `temperature: 0.1`. Cruise teaching/banter → `temperature: 0.5`. Default → `temperature: 0.3`.

### 5.3 Prompt Caching

The `cache_control: {"type": "ephemeral"}` on the static system prompt block is correct and good. This will significantly reduce time-to-first-token for the ~4KB MERLIN persona. Make sure the dynamic flight context block stays un-cached (it does currently).

### 5.4 Conversation History

The `_trim_history` method uses a simple sliding window (`max_history * 2` messages). This means older context — including important decisions like "we decided to divert to KJFK" — gets silently dropped. For a copilot that needs to maintain situational awareness across an entire flight, this is a problem.

**Recommendation:** Implement a rolling conversation summary. Every N turns, have Claude (or a cheaper model) summarize the key decisions, commitments, and flight-relevant facts from the oldest messages being trimmed. Inject that summary into the system prompt's dynamic block. This is the "compressed hot memory" pattern you explored in your Reveries post.

---

## 6. Architecture — Solid, With One Structural Risk

### 6.1 What's Working

The separation into orchestrator package / web server / telemetry service / sim adapter is clean. The telemetry service's adapter pattern means you could support X-Plane or DCS without changing the core. The Docker Compose orchestration with health checks and dependency ordering is production-grade. The WebSocket-based IPC between components is the right choice for real-time data.

### 6.2 The SimConnect Bridge Gap

The SimConnect bridge is a C# .NET process running on Windows that communicates with the Python stack via WebSocket. This is architecturally correct (SimConnect is a Windows-only COM-based API). However, the bridge is a single point of failure with no redundancy, and the WebSocket connection between WSL and Windows host is a known source of latency and reliability issues.

The new telemetry-service abstraction layer is the right architectural move — it decouples the sim adapter from the consumer. But the adapter→telemetry-service→orchestrator chain adds a hop. Measure this latency. If it's adding >50ms, consider having the adapter push directly to both the telemetry service (for recording/replay) and the orchestrator (for real-time use).

### 6.3 Frontend

The browser-based cockpit UI is a reasonable prototype choice. For a production version, consider a native overlay (Electron or Tauri) that can render on top of the sim window as a transparent HUD. The current workflow of alt-tabbing to a browser breaks immersion.

---

## 7. Accuracy & Safety — IMPORTANT

### 7.1 Number Handling

Your TTS preprocessor handles number *pronunciation* well, but there's no verification layer for number *accuracy*. When Claude says "descend to 3,500 feet," there's no check that 3,500 feet is a valid altitude for the current context (terrain clearance, airspace floor, etc.). The system should cross-reference altitude/heading/speed callouts against the current sim state and flag inconsistencies.

### 7.2 Hallucination Risk on Aviation Facts

Claude will occasionally hallucinate V-speeds, frequencies, or procedures that sound plausible but are wrong. The `search_manual` tool helps, but only if Claude uses it. The system prompt says "always prefer manual data over general knowledge" but there's no enforcement mechanism.

**Recommendation:** For aircraft-specific numerical data (V-speeds, limitations, frequencies), add a validation layer that compares Claude's output against a structured database (not RAG — a proper lookup table). If Claude says "Vfe is 110 knots" but the database says 85 knots for the current aircraft, flag it.

### 7.3 Emergency Procedures

The `merlin_emergency.md` prompt is a good addition. But emergency procedures are the *last* place you want RAG retrieval latency or LLM hallucination. For the most critical emergency flows (engine failure on takeoff, engine fire, rapid decompression), consider hardcoded response paths that bypass the LLM entirely — pre-written, validated checklists that are served directly from a structured data store when specific emergency conditions are detected from telemetry.

---

## 8. Recommended Refactor Priority

### Phase 1: Voice Pipeline (Highest Impact)

1. Replace Whisper with Deepgram Nova-3 or Flux (streaming STT)
2. Evaluate and potentially replace ElevenLabs with Cartesia Sonic-3 (90ms TTS)
3. Remove standalone VAD if using Flux
4. Add phase-aware TTS voice parameters (urgency, calm, etc.)
5. Optimize callout path to bypass sentence buffering during critical phases

### Phase 2: Missing Tools (Your Spec Requirements)

6. Build NOTAM, METAR/TAF, and ADS-B tools
7. Add chart retrieval
8. Add performance calculator

### Phase 3: RAG Upgrade

9. Switch to semantic chunking
10. Upgrade embedding model
11. Add cross-encoder re-ranking
12. Add structured metadata and hybrid search

### Phase 4: LLM Optimization

13. Dynamic temperature by flight phase
14. Haiku/Sonnet model routing
15. Rolling conversation summary for history management
16. Number accuracy validation layer

### Phase 5: Safety & Polish

17. Hardcoded emergency procedure fast paths
18. Cross-reference validation for critical numbers
19. Native overlay UI (stretch goal)

---

## Summary Verdict

The brain is smart. The ears are deaf. The mouth is slow.

MERLIN's prompt engineering, tool architecture, domain knowledge, and flight-phase awareness are genuinely strong — this is not a toy. The TTS preprocessor alone demonstrates deeper aviation-domain understanding than most aviation AI products I've seen. The orchestration layer is clean and extensible.

But the voice pipeline is running 2024-era batch transcription in a world where sub-300ms streaming STT and 90ms TTS are production-ready. Every conversation turn carries 1-3 seconds of unnecessary latency from the Whisper batch→HTTP→process→respond→synthesize→play chain. For a cockpit copilot where "V1" needs to arrive in milliseconds, not seconds, this is the critical path to fix.

Fix the ears and mouth first. Everything else is refinement.
