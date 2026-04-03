# MERLIN v2.0 -- Voice Pipeline Documentation

Complete reference for MERLIN's v2 voice pipeline: speech-to-text, text-to-speech, fallback chains, barge-in, and configuration.

---

## Overview

The v2 voice pipeline replaces the batch-oriented v1 architecture with end-to-end streaming. Audio flows from the browser microphone through streaming STT, to Claude's streaming API, through ICAO text preprocessing, and out via streaming TTS -- all without waiting for any stage to fully complete before the next begins.

```
Browser Mic -> WebSocket -> Deepgram Nova-3 (streaming STT)
                                |
                         partial transcripts
                                |
                         final transcript (speech_final)
                                |
                           Claude API (streaming)
                                |
                         text chunks (streaming)
                                |
                         TTS Preprocessor (ICAO)
                                |
                         Cartesia Sonic-3 (streaming TTS)
                                |
                         WebSocket -> Browser AudioContext
```

### Latency Comparison: v1 vs v2

| Stage | v1 | v2 | Improvement |
|---|---|---|---|
| STT (end-of-speech to transcript) | ~1500-2500ms (Whisper batch) | ~300ms (Deepgram streaming) | 5-8x faster |
| End-of-turn detection | ~400ms (Silero VAD) | ~300ms (Deepgram endpointing) | Integrated, no separate model |
| TTS time-to-first-byte | ~300-500ms (ElevenLabs) | ~90ms (Cartesia Sonic-3) | 3-5x faster |
| Total voice-to-voice | ~4-6 seconds | ~1-2 seconds | 3-4x faster |

The dominant v1 bottleneck was Whisper's batch mode: the entire utterance had to be captured, preprocessed (high-pass filter, silence trim, normalize), converted from WebM to WAV, and then sent as a single HTTP POST. Deepgram eliminates this by transcribing audio in real time as it arrives.

---

## Speech-to-Text (STT)

### Primary: Deepgram Nova-3 Streaming

**Source:** `orchestrator/orchestrator/stt/deepgram.py` (`DeepgramSTTClient`)

Deepgram Nova-3 provides real-time streaming transcription via a persistent WebSocket connection. The client satisfies the `STTClient` protocol defined in `orchestrator/orchestrator/stt/base.py`.

#### How It Works

1. **Connection:** A WebSocket is opened to `wss://api.deepgram.com/v1/listen` with model parameters in the query string.

2. **Audio streaming:** PCM audio chunks are sent to Deepgram as they arrive from the browser. Two async tasks run concurrently:
   - `_send_audio()`: forwards audio chunks to the WebSocket
   - `_receive_results()`: reads transcription results from the WebSocket

3. **Partial results:** Deepgram returns interim (non-final) transcription results while the user is still speaking. These can be used for real-time transcript display in the UI.

4. **Final results:** When Deepgram detects end-of-speech (via its endpointing algorithm), it returns a result with `is_final=True`.

5. **Utterance end:** The `speech_final=True` flag or an `UtteranceEnd` message signals that the user has finished their turn. This replaces the standalone Silero VAD from v1.

#### Aviation Keyword Boosting

Deepgram supports keyword boosting via the `keywords` query parameter. The client sends up to 50 aviation-specific keywords:

```python
_AVIATION_KEYWORDS = [
    "ATIS", "METAR", "TAF", "ILS", "VOR", "NDB", "DME", "GPS",
    "RNAV", "SID", "STAR", "squawk", "altimeter", "QNH",
    "roger", "wilco", "affirmative", "mayday", "pan-pan",
    "heading", "altitude", "airspeed", "vertical speed",
    "flaps", "gear", "trim", "throttle", "mixture",
    "Cessna", "Boeing", "Airbus", "Piper",
    "MERLIN", "Captain", "go-around", "missed approach",
    "V1", "VR", "V2", "rotate", "positive rate",
]
```

This biases the model toward recognizing aviation terminology without restricting its output vocabulary.

#### Endpointing and Turn Detection

Deepgram's endpointing replaces the standalone Silero VAD for end-of-turn detection:

| Parameter | Default | Description |
|---|---|---|
| `endpointing_ms` | 300 | Silence duration (ms) before Deepgram considers a phrase complete |
| `utterance_end_ms` | 1000 | Silence duration (ms) before Deepgram signals end-of-utterance |

The 300ms endpointing threshold is tuned for cockpit communication, where pilots speak in short, deliberate phrases. The `utterance_end_ms` at 1000ms provides a longer window for detecting true end-of-turn versus a brief pause.

#### Batch Fallback

`DeepgramSTTClient.transcribe()` provides a synchronous batch transcription mode via the Deepgram REST API. This is used when streaming is not needed (e.g., pre-recorded audio uploads).

### Fallback: faster-whisper (Batch)

**Source:** `orchestrator/orchestrator/whisper_client.py` (`WhisperClient`)

When `stt_backend=whisper` is set in configuration, the system falls back to the v1 batch pipeline:

1. Browser captures audio as WebM/Opus
2. Audio is converted to WAV (if needed)
3. Audio preprocessing pipeline applies:
   - High-pass filter (remove low-frequency cockpit noise)
   - Silence trimming (strip leading/trailing dead air)
   - Amplitude normalization (consistent input levels)
4. Silero VAD detects end-of-speech (400ms silence timeout)
5. Complete audio buffer sent as HTTP POST to `localhost:9090/v1/audio/transcriptions`
6. faster-whisper (CTranslate2 backend, `large-v3-turbo` model) returns transcription
7. Aviation vocabulary `initial_prompt` biases recognition

The `WhisperClient` retries with exponential backoff on failure. The web server's transcription path does not retry.

### STT Protocol

Both backends satisfy the `STTClient` protocol (`orchestrator/orchestrator/stt/base.py`):

```python
@runtime_checkable
class STTClient(Protocol):
    async def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """Batch transcription."""
        ...

    async def stream_transcribe(
        self,
        audio_chunks: AsyncIterator[bytes],
    ) -> AsyncIterator[TranscriptionResult]:
        """Streaming transcription with partial results."""
        ...

    async def aclose(self) -> None:
        """Release resources."""
        ...
```

The `TranscriptionResult` dataclass:

```python
@dataclass
class TranscriptionResult:
    text: str
    confidence: float = 1.0
    is_final: bool = True
    speech_final: bool = False  # End-of-turn detected by STT
    duration_secs: float = 0.0
```

---

## Text-to-Speech (TTS)

### Primary: Cartesia Sonic-3

**Source:** `orchestrator/orchestrator/tts/cartesia.py` (`CartesiaClient`)

Cartesia Sonic-3 achieves ~90ms time-to-first-byte via WebSocket streaming. The client provides three synthesis modes:

#### REST Synthesis (`synthesize`)

Single-shot synthesis for short phrases. Used for phrase caching (common responses like "Roger." or "Copy that.").

```python
audio_bytes = await cartesia.synthesize("Roger, understood.")
```

#### REST Streaming (`synthesize_stream`)

Streams audio from the REST endpoint. Useful when WebSocket is unavailable.

```python
async for chunk in cartesia.synthesize_stream("Turning left heading two seven zero."):
    await send_audio(chunk)
```

#### WebSocket Streaming (`synthesize_ws_stream`)

Lowest latency mode. Opens a persistent WebSocket to `wss://api.cartesia.ai/tts/websocket` and streams text as it arrives from Claude's response. Text is buffered at sentence boundaries before sending:

```python
async for audio_chunk in cartesia.synthesize_ws_stream(claude_text_chunks):
    await send_audio(audio_chunk)
```

The sentence buffering ensures that Cartesia receives complete syntactic units, which produces more natural prosody than sending word-by-word. Sentence boundaries are detected by `.`, `!`, `?`, and `\n` characters.

#### Phase-Aware Emotion Control

Cartesia supports emotional voice characteristics. The `set_emotion()` method allows dynamic adjustment per flight phase:

| Flight Phase | Emotion | Effect |
|---|---|---|
| PREFLIGHT | `warm` | Friendly, conversational |
| TAKEOFF | `authoritative` | Confident, clipped |
| CRUISE | `calm` | Relaxed, even-paced |
| APPROACH | `authoritative` | Precise, focused |
| EMERGENCY | `urgent` | Elevated intensity |

#### Audio Format

| Parameter | Default | Notes |
|---|---|---|
| Sample rate | 24000 Hz | Suitable for speech |
| Format | `pcm_s16le` | Raw PCM, 16-bit signed little-endian |
| Channels | Mono | Single channel |

### Fallback: ElevenLabs

**Config:** `tts_backend=elevenlabs`

The v1 ElevenLabs backend remains available as a fallback:

- WebSocket streaming via persistent connection per response
- `eleven_multilingual_v2` model
- TLS pre-warm at startup
- Phrase cache for common responses (zero-latency playback)
- Configurable: stability, similarity boost, style parameters

### Fallback: Kokoro (Local)

**Config:** `tts_backend=local`

For fully offline operation, Kokoro provides local TTS:

- Runs as a separate server at `TTS_LOCAL_URL` (default `http://localhost:8880`)
- No API key required
- Higher latency than cloud options
- Voice ID configurable via `TTS_VOICE_ID_LOCAL` (default `af_heart`)

---

## TTS Preprocessing

**Source:** `orchestrator/orchestrator/tts_preprocessor.py`

Before any TTS backend receives text, it passes through the ICAO-compliant preprocessor. This converts LLM output into speakable text following aviation phraseology standards.

### Processing Pipeline

The `preprocess_for_tts()` function applies transformations in a specific order to avoid interference between patterns:

1. Flight levels (FL350 -> "flight level tree five zero")
2. Headings (heading 270 -> "heading two seven zero")
3. Bearings/radials (the 270 radial -> "the two seven zero radial")
4. Squawk codes (squawk 7700 -> "squawk seven seven zero zero")
5. QNH/altimeter in inHg (29.92 -> "two niner niner two")
6. QNH in hectopascals/millibars (1013 hPa -> "one zero one tree hectopascals")
7. Frequencies with context words (contact tower 118.7 -> "one one eight point seven")
8. Standalone aviation frequencies (121.5 -> "one two one point five")
9. Zulu time (1430Z -> "one four tree zero Zulu")
10. DME/distance
11. Runway designators (27L -> "two seven left")
12. Speed (knots)
13. Altitudes (3,500 feet -> "tree thousand five hundred feet")
14. Temperature (digit-by-digit per ICAO)
15. ATIS information letters (Information A -> "Information Alpha")
16. Transponder modes (Mode C -> "Mode Charlie")
17. Aviation acronyms (ILS, VOR, NDB, etc.)
18. Markdown stripping (headers, bold, italic, code blocks, links)
19. Special character cleanup

### ICAO Digit Pronunciation

The preprocessor uses ICAO-standard digit pronunciation:

| Digit | Spoken |
|---|---|
| 0 | zero |
| 1 | one |
| 2 | two |
| 3 | tree |
| 4 | four |
| 5 | five |
| 6 | six |
| 7 | seven |
| 8 | eight |
| 9 | niner |

---

## Barge-In / Interruption

MERLIN supports barge-in at every stage of the pipeline. When the pilot sends new audio or text while MERLIN is responding:

1. **Claude stream cancelled:** The in-flight `messages.stream()` context manager is exited, stopping token generation.
2. **TTS pipeline cancelled:** Any pending audio synthesis is cancelled. The Cartesia/ElevenLabs WebSocket connection for the current response is closed.
3. **Audio playback stopped:** The browser's AudioContext is instructed to stop playing the current response.
4. **New input processed:** The new pilot input enters the pipeline immediately.

The web server (`web/server.py`) manages cancellation tokens per client. Each new chat message increments a generation counter; streaming tasks check this counter and abort if it has changed.

### Barge-In Flow

```
MERLIN speaking: "The weather at Kennedy is reporting..."
Pilot interrupts: "Actually, give me JFK NOTAMs instead"

1. Server receives new audio/text
2. Server cancels current Claude stream (asyncio.Task.cancel())
3. Server cancels current TTS stream
4. Server sends "stop_audio" message to browser WebSocket
5. Browser stops AudioContext playback
6. New input enters STT pipeline
7. New Claude request begins
```

---

## Configuration

All voice pipeline settings are configured via environment variables loaded by `pydantic-settings`.

### STT Configuration

| Variable | Default | Description |
|---|---|---|
| `STT_BACKEND` | `deepgram` | STT backend: `deepgram` (cloud streaming) or `whisper` (local batch) |
| `DEEPGRAM_API_KEY` | *(empty)* | Deepgram API key (required when `STT_BACKEND=deepgram`) |
| `DEEPGRAM_MODEL` | `nova-3` | Deepgram model name |
| `DEEPGRAM_ENDPOINTING_MS` | `300` | Silence threshold (ms) for phrase boundary detection |
| `WHISPER_MODEL` | `large-v3-turbo` | faster-whisper model size (fallback STT) |
| `WHISPER_URL` | `http://localhost:9090` | faster-whisper HTTP service URL (fallback STT) |

### TTS Configuration

| Variable | Default | Description |
|---|---|---|
| `TTS_BACKEND` | `cartesia` | TTS backend: `cartesia`, `elevenlabs`, or `local` |
| `CARTESIA_API_KEY` | *(empty)* | Cartesia API key (required when `TTS_BACKEND=cartesia`) |
| `CARTESIA_VOICE_ID` | *(empty)* | Cartesia voice ID for MERLIN's voice |
| `CARTESIA_MODEL_ID` | `sonic-2` | Cartesia model ID |
| `ELEVENLABS_API_KEY` | *(empty)* | ElevenLabs API key (required when `TTS_BACKEND=elevenlabs`) |
| `ELEVENLABS_VOICE_ID` | *(empty)* | ElevenLabs voice ID |
| `ELEVENLABS_MODEL_ID` | `eleven_multilingual_v2` | ElevenLabs model ID |
| `TTS_LOCAL_URL` | `http://localhost:8880` | Kokoro TTS server URL (when `TTS_BACKEND=local`) |
| `TTS_VOICE_ID_LOCAL` | `af_heart` | Local TTS voice ID |
| `TTS_STABILITY` | `0.75` | ElevenLabs voice stability |
| `TTS_SIMILARITY_BOOST` | `0.80` | ElevenLabs similarity boost |
| `TTS_STYLE` | `0.15` | ElevenLabs style expressiveness |

### Audio Preprocessing Configuration

Audio preprocessing (high-pass filter, silence trimming, normalization) applies to all STT backends. The Silero VAD is used only when `STT_BACKEND=whisper` (Deepgram handles VAD internally).

---

## Architecture: STT/TTS Abstraction

The voice pipeline uses a protocol-based abstraction layer so that STT and TTS backends are interchangeable:

```
STTClient Protocol (stt/base.py)
    |
    +-- DeepgramSTTClient (stt/deepgram.py)     [primary]
    +-- WhisperClient (whisper_client.py)         [fallback]

TTSClient Protocol
    |
    +-- CartesiaClient (tts/cartesia.py)          [primary]
    +-- ElevenLabs WS client (voice.py)           [fallback]
    +-- Kokoro HTTP client (voice.py)             [fallback]
```

Backend selection is driven by the `stt_backend` and `tts_backend` configuration values. The orchestrator instantiates the appropriate client at startup. Switching backends requires only a config change and restart -- no code changes.

---

## Troubleshooting

### Deepgram STT

| Symptom | Likely Cause | Fix |
|---|---|---|
| No transcriptions | Missing or invalid `DEEPGRAM_API_KEY` | Check API key in `.env` |
| Partial results but no final | `endpointing_ms` too high | Lower `DEEPGRAM_ENDPOINTING_MS` to 200-300 |
| Aviation terms misrecognized | Keyword list not effective | Check logs for Deepgram connection parameters |
| WebSocket connection failures | Network/firewall issue | Verify outbound WSS to `api.deepgram.com` |
| Falls back to Whisper | Deepgram unavailable | Check `STT_BACKEND` config and API connectivity |

### Cartesia TTS

| Symptom | Likely Cause | Fix |
|---|---|---|
| No audio output | Missing `CARTESIA_API_KEY` or `CARTESIA_VOICE_ID` | Check both values in `.env` |
| High latency | Falling back to REST instead of WebSocket | Ensure `websockets` package installed |
| Garbled speech | Aviation text not preprocessed | Check TTS preprocessor is in the pipeline |
| Falls back to ElevenLabs | Cartesia unavailable | Check `TTS_BACKEND` config and API connectivity |
