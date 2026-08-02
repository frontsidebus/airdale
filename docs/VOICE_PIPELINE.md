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

Both are still duration thresholds, with the structural weakness that implies. The `TurnDetector` layer described under [End-of-Turn Detection](#end-of-turn-detection) decides on content instead, and applies to this path and the Whisper path alike.

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

## End-of-Turn Detection

Voice activity detection asks "is there speech in this chunk". End-of-turn detection asks the narrower question: "has the pilot finished, and does he expect a reply". A pause is speech-absent but not turn-complete, and aviation phraseology is full of pauses -- "descend and maintain... one zero thousand".

So a fixed silence timer is structurally wrong, not merely mistuned: short enough to feel responsive means cutting people off mid-sentence, long enough to tolerate pauses means feeling sluggish. The architecture separates the two questions. A cheap acoustic gate finds *candidate* endpoints and decides **when** to ask; the `TurnDetector` (`orchestrator/orchestrator/turn/`) reads the waveform and decides **whether** the turn is over.

### Two paths, one detector

| | Acoustic gate (when to ask) | Decision (whether it ended) |
|---|---|---|
| Local / CLI (`voice.py`) | Silero VAD (neural) | `TurnDetector`, in-process |
| Web / browser (`app.js`) | JavaScript RMS energy gate | `TurnDetector`, over `POST /api/turn-probe` |

Only the gate differs. The browser has no turn model, no feature extraction, and no ONNX runtime -- it uploads audio and reads a verdict. Smart Turn v3 reads the waveform rather than a transcript, so the same detector serves the local Whisper path and the Deepgram streaming path identically.

### Browser endpointing thresholds

Both thresholds are served by `GET /api/status`, so the browser never hardcodes or duplicates configuration:

| Field | Default | Meaning |
|---|---|---|
| `turn_probe_available` | -- | Whether a semantic detector is loaded. False for the silence fallback, which would only re-derive what the browser already times locally. |
| `turn_probe_silence_ms` | 150 | Silence at which the browser first asks the server, and the minimum spacing between probes. |
| `vad_silence_ms` | 400 | Silence at which the browser ends the turn on its own. |

This replaces a hardcoded 1200 ms RMS silence timer. Endpointing now happens on a semantic decision at ~150 ms, or at 400 ms when degraded -- three times more responsive than the old fixed wait even in the fully degraded case.

The fallback stop is independent of every probe. If the endpoint is missing, the model is absent, the request hangs, or the answer is wrong, voice input still works; it just waits the full 400 ms. A probe can only make endpointing *sooner*, never later.

### Two constraints that shaped the design

**1. The browser uploads the whole accumulated blob, not a trailing slice.** `MediaRecorder` emits webm chunks where only the first carries the EBML header and codec-private data; every subsequent chunk is a bare cluster. A trailing slice will not decode at all. Sending everything costs nothing, because `turn.features.truncate_or_pad` already keeps only the last 8 seconds server-side. Recording is not stopped to take a probe -- `_vadChunks` is read while capture continues.

**2. The probe has its own decode path that does not preprocess.** `decode_webm_to_samples` in `orchestrator/orchestrator/audio_processing.py` runs ffmpeg to 16 kHz mono float32 and stops there. It deliberately does *not* call `preprocess_audio`, which the transcription path uses: that pipeline trims trailing silence, and trailing silence is precisely the signal the turn model judges. Its high-pass filter and normalisation also alter the waveform, while the feature path in `turn/features.py` is pinned against golden vectors captured from unmodified audio. Neither divergence would raise -- it would just make turn predictions quietly wrong. A structural test asserts `preprocess_audio` never appears in that function, and a behavioural test asserts a silent tail survives the decode.

### `POST /api/turn-probe`

Multipart request: `file` (the accumulated webm blob) and `silence_ms` (silence observed so far).

```json
{ "ended": true, "probability": 0.93, "detector": "smart_turn", "available": true }
```

`available` is separate from `ended` on purpose. `available: false` means stop asking for the rest of the session; a transient failure keeps it true so one bad blob does not permanently degrade responsiveness. The `detector` field names the outcome: `smart_turn`, `unavailable`, `decode_failed`, `throttled`, `too_large`, or `error`.

The endpoint never raises. Every failure returns a not-ended answer with HTTP 200, because the browser's fallback is what keeps voice input working and a 5xx would only add latency to reaching it.

It is also throttled and size-bounded, since `pollVAD` calls it from a `requestAnimationFrame` loop at roughly 60 Hz and each accepted probe spawns an ffmpeg process:

- **Server:** per-client minimum interval of `turn_probe_silence_ms / 2`, and a 2 MiB body cap rejected before ffmpeg runs (Opus at ~24 kbps puts a 15 s utterance near 45 KB).
- **Browser:** at most one probe in flight, at most one per `turn_probe_silence_ms`, and an `AbortController` timeout at twice that so a hung probe cannot block the next one.

The server does not take the browser's word for any of it.

### Configuration

| Variable | Default | Description |
|---|---|---|
| `TURN_DETECTOR` | `smart` | `smart` (Smart Turn v3 ONNX) or `silence` (fixed threshold). `smart` falls back to `silence` at startup if onnxruntime or the model file is missing. |
| `TURN_THRESHOLD` | `0.5` | Probability above which the turn is called complete. Raise it to make MERLIN wait through longer pauses. |
| `TURN_PROBE_SILENCE_MS` | `150` | Silence before consulting the semantic detector. |
| `VAD_SILENCE_MS` | `400` | Fixed-silence threshold and RMS fallback. |

The model is not vendored. Fetch it with `python3 tools/fetch_turn_model.py`; without it the system degrades to fixed-silence endpointing and logs the hint at startup, rather than failing.

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

## Command Execution Flow

When the pilot gives a voice command to control the aircraft, the request flows through every layer of the stack before reaching the simulator.

### End-to-End Pipeline

```
Pilot speaks: "Gear down"
        |
Browser Mic -> WebSocket -> Deepgram Nova-3 (streaming STT)
        |
   "gear down" (transcript)
        |
   Claude API (streaming, with set_aircraft_control tool)
        |
   Tool call: set_aircraft_control(system="gear", action="down")
        |
   _resolve_command() -> ("GEAR_DOWN", 0)
        |
   TelemetryClient.send_command("GEAR_DOWN", 0)
        |
   ConsumerCommand -> Telemetry Service (ws://localhost:8080)
        |
   ServiceCommand -> Adapter (SimConnect bridge or mock adapter)
        |
   SimConnect TransmitClientEvent / mock state update
        |
   AdapterCommandAck -> ServiceCommandAck -> tool result
        |
   Claude response: "Gear down, three green."
        |
   TTS Preprocessor -> Cartesia Sonic-3 -> WebSocket -> Browser AudioContext
```

### Controllable Systems

The `set_aircraft_control` tool exposes 11 aircraft systems to Claude. The tool translates human-friendly parameters into SimConnect event names and data values.

| System | Example Voice Command | SimConnect Events |
|---|---|---|
| flaps | "Give me full flaps" | FLAPS_UP, FLAPS_FULL, FLAPS_1/2/3, FLAPS_SET, FLAPS_INCR/DECR |
| gear | "Gear down" | GEAR_UP, GEAR_DOWN, GEAR_TOGGLE |
| autopilot | "Set heading to 270" | AP_MASTER, HEADING_BUG_SET, AP_ALT_VAR_SET_ENGLISH, AP_VS_VAR_SET_ENGLISH, AP_SPD_VAR_SET, AP_HDG_HOLD, AP_ALT_HOLD, AP_VS_HOLD, AP_AIRSPEED_HOLD, AP_NAV1_HOLD, AP_APR_HOLD |
| throttle | "Throttle to 75 percent" | THROTTLE_SET |
| radio | "Tune COM1 to 121.5" | COM_RADIO_SET_HZ, COM2_RADIO_SET_HZ, NAV1_RADIO_SET_HZ, NAV2_RADIO_SET_HZ |
| barometer | "Set altimeter 29.92" | KOHLSMAN_SET |
| trim | "Trim nose up" | ELEVATOR_TRIM_SET |
| parking_brake | "Set parking brake" | PARKING_BRAKES |
| spoilers | "Deploy spoilers" | SPOILERS_TOGGLE, SPOILERS_SET |
| mixture | "Mixture full rich" | MIXTURE_SET |
| propeller | "Prop to full forward" | PROP_PITCH_SET |

### How Confirmations Work

Claude is instructed to execute commands immediately when the pilot's order is unambiguous, then respond with a brief aviation-style confirmation. The confirmation flows through the same TTS pipeline as any other response:

1. Claude calls `set_aircraft_control` with the appropriate system, action, and value
2. The command routes through the telemetry service to the adapter
3. The adapter executes it (SimConnect event or mock state change) and returns an acknowledgment
4. Claude receives the tool result and generates a confirmation: "Gear down, three green."
5. The confirmation text passes through the TTS preprocessor (ICAO digit pronunciation, markdown stripping)
6. Cartesia Sonic-3 synthesizes the audio and streams it to the browser

Critical system commands (gear, autopilot master, parking brake) are flagged with a `safety_note` in the tool result, which Claude can use to add appropriate emphasis or caution to the confirmation. The note is attached only when the command was actually transmitted and acknowledged — one refused by the authority gate, NACKed by the adapter, or timed out carries no `safety_note`, so the confirmation never claims a critical change that did not reach the aircraft.

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

It does **not** apply to the turn-probe path, which decodes through `decode_webm_to_samples` instead. See "Two constraints that shaped the design" under End-of-Turn Detection: silence trimming would remove the exact signal the turn model reads.

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
