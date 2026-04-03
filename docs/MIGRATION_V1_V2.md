# MERLIN v1 to v2 Migration Guide

Step-by-step guide for migrating an existing MERLIN v1 installation to v2. Covers breaking changes, new dependencies, configuration updates, and verification steps.

---

## Summary of Changes

| Area | v1 | v2 | Impact |
|---|---|---|---|
| **STT (primary)** | faster-whisper batch (local Docker) | Deepgram Nova-3 streaming (cloud) | New API key required |
| **TTS (primary)** | ElevenLabs WebSocket | Cartesia Sonic-3 WebSocket | New API key required |
| **RAG chunking** | Character-based splitting (1000 chars, 200 overlap) | Aviation-aware semantic chunking | Re-ingest documents |
| **RAG retrieval** | Vector similarity only | Two-stage: vector + cross-encoder re-ranking | New dependency |
| **LLM temperature** | Static (0.7 default) | Dynamic by flight phase (0.1/0.3/0.5) | Config default changed |
| **LLM model routing** | Single model for all queries | Haiku for short queries, Sonnet for everything else | New config values |
| **Conversation history** | Trimmed and discarded | Rolling summary preserves key decisions | New config values |
| **Safety: Emergency** | None | Pre-validated emergency fast paths | New module |
| **Safety: Validation** | None | V-speed and frequency validation | New module |
| **Safety: Telemetry** | None | Sanity checks on incoming data | New module |
| **Safety: Timeouts** | None | Per-tool timeout enforcement | Behavioral change |
| **Tools** | 6 tools | 12 tools (6 new aviation tools) | New module |
| **TTS preprocessing** | 6 ICAO transformations | 12 ICAO transformations | Enhanced |
| **VAD** | Standalone Silero VAD | Deepgram endpointing (Silero retained for Whisper fallback) | Reduced dependencies |

---

## Breaking Changes

### 1. Default TTS backend changed: `elevenlabs` -> `cartesia`

The `TTS_BACKEND` default value changed from `elevenlabs` to `cartesia`. If you rely on ElevenLabs and do not set `TTS_BACKEND` explicitly, you must add it to your `.env`:

```bash
# To keep using ElevenLabs in v2:
TTS_BACKEND=elevenlabs
```

### 2. Default temperature changed: 0.7 -> 0.3

The `CLAUDE_TEMPERATURE` default dropped from 0.7 to 0.3. This is now the "normal" tier; actual temperature varies by flight phase (0.1 critical, 0.3 normal, 0.5 relaxed). If you had `CLAUDE_TEMPERATURE=0.7` in your `.env`, it now serves as the base for the normal tier only; dynamic phase logic overrides it during critical and relaxed phases.

### 3. Default STT backend changed: `whisper` -> `deepgram`

The `STT_BACKEND` default is now `deepgram`. If you want to continue using local Whisper without a Deepgram API key:

```bash
# To keep using Whisper in v2:
STT_BACKEND=whisper
```

### 4. RAG documents must be re-ingested

The v2 semantic chunker produces different chunk boundaries than the v1 character-based splitter. Existing ChromaDB collections will work but will not benefit from improved chunking. To get the full benefit:

```bash
# Clear and re-ingest
cd orchestrator
python -m tools.ingest --clear --source data/documents/
```

### 5. Query classification now returns four categories

`classify_query()` in `claude_client.py` now returns `'emergency'`, `'short'`, `'briefing'`, or `'normal'` (previously only `'short'`, `'briefing'`, `'normal'`). Code that matches on the return value should handle the new `'emergency'` category.

### 6. Tool execution now has timeouts

All tool calls are wrapped in `asyncio.wait_for()`. Tools that previously could run indefinitely will now timeout (default 5s, `get_sim_state` at 2s, external APIs at 10s). This is a behavioral change -- slow external APIs will now return timeout errors to Claude instead of blocking.

---

## New Environment Variables

Add these to your `.env` file. See `.env.example` for the complete template.

### Required for v2 Default Configuration

```bash
# Deepgram API key for streaming STT (required when STT_BACKEND=deepgram)
DEEPGRAM_API_KEY=your-deepgram-key

# Cartesia API key for low-latency TTS (required when TTS_BACKEND=cartesia)
CARTESIA_API_KEY=your-cartesia-key

# Cartesia voice ID for MERLIN
CARTESIA_VOICE_ID=your-voice-id
```

### Optional New Variables

```bash
# STT backend selection: 'deepgram' (default) or 'whisper'
STT_BACKEND=deepgram

# Deepgram model (nova-3 recommended for aviation)
DEEPGRAM_MODEL=nova-3

# Deepgram endpointing silence threshold in ms
DEEPGRAM_ENDPOINTING_MS=300

# TTS backend selection: 'cartesia' (default), 'elevenlabs', or 'local'
TTS_BACKEND=cartesia

# Cartesia model ID
CARTESIA_MODEL_ID=sonic-2

# Fast model for short queries (acknowledgments, yes/no)
CLAUDE_MODEL_FAST=claude-haiku-4-5-20251001

# Dynamic temperature tiers (override defaults)
CLAUDE_TEMP_CRITICAL=0.1    # Takeoff, approach, landing
CLAUDE_TEMP_NORMAL=0.3      # Climb, descent, taxi
CLAUDE_TEMP_RELAXED=0.5     # Preflight, cruise, landed

# Conversation summary settings
CLAUDE_SUMMARY_INTERVAL=10  # Summarize every N turns
CLAUDE_SUMMARY_MAX_TOKENS=256
```

### Variables No Longer Required (but still supported)

These variables are still functional for fallback configurations but are no longer required for default operation:

| Variable | Status | Notes |
|---|---|---|
| `ELEVENLABS_API_KEY` | Optional | Only needed when `TTS_BACKEND=elevenlabs` |
| `ELEVENLABS_VOICE_ID` | Optional | Only needed when `TTS_BACKEND=elevenlabs` |
| `WHISPER_MODEL` | Optional | Only needed when `STT_BACKEND=whisper` |
| `WHISPER_URL` | Optional | Only needed when `STT_BACKEND=whisper` |

---

## Deprecated / Removed

### Standalone Silero VAD (partially deprecated)

In v1, Silero VAD was the sole mechanism for detecting end-of-speech. In v2 with Deepgram as the primary STT backend, Deepgram's built-in endpointing handles turn detection. Silero VAD is retained in `audio_processing.py` for the Whisper fallback path only. If you only use Deepgram, Silero will not be loaded.

### Character-Based Chunking

The `_split_text()` method in `context_store.py` (which split documents by character count with overlap) has been replaced by the `AviationChunker` class in `chunking.py`. The old `chunk_size` and `chunk_overlap` parameters to `ingest_document()` have been removed. The new chunker uses semantic boundaries (sections, paragraphs, list items) with configurable `max_chunk_chars`, `min_chunk_chars`, and `overlap_chars`.

### Static Temperature

The static `CLAUDE_TEMPERATURE` value is no longer the sole temperature used. It is now the "normal" tier default. Dynamic temperature by flight phase overrides it for critical and relaxed phases. To disable dynamic temperature and use a single static value, set all three tiers to the same value:

```bash
CLAUDE_TEMP_CRITICAL=0.7
CLAUDE_TEMP_NORMAL=0.7
CLAUDE_TEMP_RELAXED=0.7
```

---

## Step-by-Step Migration

### Step 1: Update Code

```bash
git fetch origin
git checkout main
git pull
```

### Step 2: Install New Python Dependencies

```bash
cd orchestrator
pip install -e ".[dev]"
```

New dependencies include:
- `httpx` (may already be installed) -- used by Deepgram and Cartesia clients, and the new aviation tools
- `sentence-transformers` -- for cross-encoder re-ranking (optional; degrades gracefully if missing)

### Step 3: Obtain API Keys

1. **Deepgram:** Sign up at [deepgram.com](https://deepgram.com) and create an API key. The Nova-3 model is recommended for aviation accuracy.

2. **Cartesia:** Sign up at [cartesia.ai](https://cartesia.ai) and create an API key. Select or create a voice for MERLIN and note the voice ID.

If you prefer to keep using v1 backends, skip this step and set `STT_BACKEND=whisper` and `TTS_BACKEND=elevenlabs` in your `.env`.

### Step 4: Update `.env`

Add the new variables to your `.env` file:

```bash
# --- v2 additions ---

# STT
STT_BACKEND=deepgram
DEEPGRAM_API_KEY=your-deepgram-key
DEEPGRAM_MODEL=nova-3
DEEPGRAM_ENDPOINTING_MS=300

# TTS
TTS_BACKEND=cartesia
CARTESIA_API_KEY=your-cartesia-key
CARTESIA_VOICE_ID=your-voice-id
CARTESIA_MODEL_ID=sonic-2

# LLM routing
CLAUDE_MODEL_FAST=claude-haiku-4-5-20251001
CLAUDE_TEMPERATURE=0.3

# (Optional) Dynamic temperature tiers
# CLAUDE_TEMP_CRITICAL=0.1
# CLAUDE_TEMP_NORMAL=0.3
# CLAUDE_TEMP_RELAXED=0.5
```

### Step 5: Re-ingest RAG Documents (Recommended)

To benefit from aviation-aware semantic chunking and enhanced metadata:

```bash
cd orchestrator
python -m tools.ingest --clear --source data/documents/
```

If you skip this step, existing documents will continue to work with the old chunk boundaries. New documents ingested after the update will use the new chunker automatically.

### Step 6: Update Docker Services (If Using Docker)

```bash
docker compose pull
docker compose build --no-cache orchestrator
docker compose up -d
```

Note: The faster-whisper container is still needed if `STT_BACKEND=whisper` or as a fallback. If you are fully migrating to Deepgram, the Whisper container is optional but recommended to keep as a fallback.

### Step 7: Verify Installation

```bash
cd orchestrator

# Run tests (should pass all existing + new tests)
pytest

# Check that new modules import correctly
python -c "from orchestrator.stt.deepgram import DeepgramSTTClient; print('Deepgram STT: OK')"
python -c "from orchestrator.tts.cartesia import CartesiaClient; print('Cartesia TTS: OK')"
python -c "from orchestrator.emergency import EmergencyDetector; print('Emergency detector: OK')"
python -c "from orchestrator.validation import ResponseValidator; print('Response validator: OK')"
python -c "from orchestrator.chunking import AviationChunker; print('Semantic chunker: OK')"
python -c "from orchestrator.reranker import CrossEncoderReranker; print('Re-ranker: OK')"
python -c "from orchestrator.aviation_tools import get_weather; print('Aviation tools: OK')"
```

### Step 8: Test Voice Pipeline

1. Start the system:
   ```bash
   # Docker
   docker compose up -d

   # Or native
   cd web && python run.py
   ```

2. Open the browser UI at `http://localhost:3838`

3. Test STT: Press PTT (or use VAD) and speak an aviation phrase: "Merlin, what's the weather at Juliet Foxtrot Kilo?"
   - Verify transcription appears quickly (~300ms after speech ends)
   - Verify aviation terms are correctly recognized

4. Test TTS: Verify MERLIN's response plays back with low latency
   - Check that aviation numbers are spoken correctly (ICAO phraseology)
   - Check that there is no garbled speech from unprocessed markdown

5. Test barge-in: Start speaking while MERLIN is responding
   - MERLIN should stop speaking immediately
   - Your new input should be processed

---

## Rollback Procedure

If you need to revert to v1 behavior without rolling back code:

```bash
# In .env, set v1 defaults:
STT_BACKEND=whisper
TTS_BACKEND=elevenlabs
CLAUDE_TEMPERATURE=0.7
CLAUDE_TEMP_CRITICAL=0.7
CLAUDE_TEMP_NORMAL=0.7
CLAUDE_TEMP_RELAXED=0.7
```

This disables Deepgram, Cartesia, dynamic temperature, and model routing. The safety layer (emergency detection, response validation, telemetry sanity, tool timeouts) remains active as it has no configuration toggle -- it is always-on by design.

---

## New Files in v2

| File | Description |
|---|---|
| `orchestrator/orchestrator/stt/__init__.py` | STT package init |
| `orchestrator/orchestrator/stt/base.py` | `STTClient` protocol, `TranscriptionResult` dataclass |
| `orchestrator/orchestrator/stt/deepgram.py` | Deepgram Nova-3 streaming STT client |
| `orchestrator/orchestrator/tts/cartesia.py` | Cartesia Sonic-3 streaming TTS client |
| `orchestrator/orchestrator/chunking.py` | Aviation-aware semantic document chunker |
| `orchestrator/orchestrator/reranker.py` | Cross-encoder re-ranking for RAG |
| `orchestrator/orchestrator/emergency.py` | Emergency detection and fast-path responses |
| `orchestrator/orchestrator/validation.py` | Response validation and telemetry sanity checks |
| `orchestrator/orchestrator/aviation_tools.py` | 6 new aviation tools (NOTAM, METAR, ADS-B, charts, performance, airspace) |
| `orchestrator/tests/test_deepgram_stt.py` | Deepgram client tests |
| `orchestrator/tests/test_cartesia_tts.py` | Cartesia client tests |
| `orchestrator/tests/test_chunking.py` | Semantic chunker tests |
| `orchestrator/tests/test_reranker.py` | Re-ranker tests |
| `orchestrator/tests/test_emergency.py` | Emergency detector tests |
| `orchestrator/tests/test_validation.py` | Response validator tests |
| `orchestrator/tests/test_aviation_tools.py` | Aviation tools tests |
| `orchestrator/tests/test_llm_optimization.py` | Dynamic temperature and model routing tests |

### Modified Files in v2

| File | Changes |
|---|---|
| `orchestrator/orchestrator/config.py` | Added: `stt_backend`, `deepgram_*`, `cartesia_*`, `claude_model_fast`, `claude_temp_*`, `claude_summary_*`. Changed defaults: `tts_backend` (elevenlabs -> cartesia), `claude_temperature` (0.7 -> 0.3) |
| `orchestrator/orchestrator/claude_client.py` | Added: emergency query classification, dynamic temperature, model routing, rolling conversation summary, tool timeouts with `asyncio.wait_for()` |
| `orchestrator/orchestrator/context_store.py` | Replaced character-based splitting with `AviationChunker`. Added cross-encoder re-ranking. Enhanced metadata support. Two-stage retrieval (retrieve K=20, re-rank to N=5). |
| `orchestrator/orchestrator/tts_preprocessor.py` | Added 6 new transformations: bearing/radial, QNH in hPa/mb, standalone frequencies, Zulu time, ATIS information letters (NATO phonetic), transponder modes (NATO phonetic). Improved altitude regex. |
