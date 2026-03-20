"""Voice pipeline: microphone input with STT and TTS streaming output."""

from __future__ import annotations

import asyncio
import io
import logging
import struct
import wave
from enum import Enum
from typing import AsyncIterator

import httpx
import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


class InputMode(str, Enum):
    PUSH_TO_TALK = "push_to_talk"
    VOICE_ACTIVITY = "voice_activity"


class VoiceInput:
    """Handles microphone recording, voice activity detection, and transcription.

    Supports both push-to-talk (PTT) and continuous voice-activity-detection (VAD)
    modes. Uses OpenAI Whisper API or local model for speech-to-text.
    """

    def __init__(
        self,
        whisper_model: str = "base",
        sample_rate: int = 16000,
        channels: int = 1,
        vad_threshold: float = 0.02,
        vad_silence_duration: float = 1.5,
        mode: InputMode = InputMode.PUSH_TO_TALK,
    ) -> None:
        self._whisper_model = whisper_model
        self._sample_rate = sample_rate
        self._channels = channels
        self._vad_threshold = vad_threshold
        self._vad_silence_secs = vad_silence_duration
        self._mode = mode
        self._recording = False
        self._whisper = None  # lazy-loaded local model

    @property
    def mode(self) -> InputMode:
        return self._mode

    @mode.setter
    def mode(self, value: InputMode) -> None:
        self._mode = value

    async def record_ptt(self) -> np.ndarray:
        """Record audio while push-to-talk is active. Returns raw audio array."""
        logger.debug("PTT recording started")
        frames: list[np.ndarray] = []
        self._recording = True

        def callback(indata: np.ndarray, frame_count: int, time_info: dict, status: int) -> None:
            if self._recording:
                frames.append(indata.copy())

        stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            callback=callback,
        )
        stream.start()

        # Wait until recording flag is cleared externally
        while self._recording:
            await asyncio.sleep(0.05)

        stream.stop()
        stream.close()

        if not frames:
            return np.array([], dtype=np.float32)
        return np.concatenate(frames, axis=0).flatten()

    def stop_recording(self) -> None:
        self._recording = False

    async def record_vad(self) -> np.ndarray:
        """Record audio using voice activity detection. Returns audio once silence is detected."""
        logger.debug("VAD recording started")
        frames: list[np.ndarray] = []
        silence_frames = 0
        speech_detected = False
        silence_limit = int(self._vad_silence_secs * self._sample_rate / 1024)

        event = asyncio.Event()
        result_audio: list[np.ndarray | None] = [None]

        def callback(indata: np.ndarray, frame_count: int, time_info: dict, status: int) -> None:
            nonlocal silence_frames, speech_detected
            rms = np.sqrt(np.mean(indata**2))
            frames.append(indata.copy())

            if rms > self._vad_threshold:
                speech_detected = True
                silence_frames = 0
            elif speech_detected:
                silence_frames += 1
                if silence_frames >= silence_limit:
                    result_audio[0] = np.concatenate(frames, axis=0).flatten()
                    event.set()

        stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            blocksize=1024,
            callback=callback,
        )
        stream.start()
        await event.wait()
        stream.stop()
        stream.close()

        return result_audio[0] if result_audio[0] is not None else np.array([], dtype=np.float32)

    async def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio array to text using Whisper."""
        if audio.size == 0:
            return ""

        # Try local whisper first
        try:
            return await self._transcribe_local(audio)
        except ImportError:
            logger.info("Local whisper not available, falling back to API")
            return await self._transcribe_api(audio)

    async def _transcribe_local(self, audio: np.ndarray) -> str:
        import whisper

        if self._whisper is None:
            self._whisper = whisper.load_model(self._whisper_model)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._whisper.transcribe(audio, fp16=False),
        )
        text = result.get("text", "").strip()
        logger.info("Transcribed: %s", text)
        return text

    async def _transcribe_api(self, audio: np.ndarray) -> str:
        wav_bytes = self._audio_to_wav_bytes(audio)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": "Bearer ${OPENAI_API_KEY}"},
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data={"model": "whisper-1"},
            )
            resp.raise_for_status()
            text = resp.json().get("text", "").strip()
            logger.info("Transcribed (API): %s", text)
            return text

    def _audio_to_wav_bytes(self, audio: np.ndarray) -> bytes:
        buf = io.BytesIO()
        int16_audio = (audio * 32767).astype(np.int16)
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self._channels)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            wf.writeframes(int16_audio.tobytes())
        buf.seek(0)
        return buf.read()

    async def listen(self) -> str:
        """High-level method: record based on current mode and return transcription."""
        if self._mode == InputMode.PUSH_TO_TALK:
            audio = await self.record_ptt()
        else:
            audio = await self.record_vad()
        return await self.transcribe(audio)


class VoiceOutput:
    """Handles text-to-speech via ElevenLabs API with streaming playback."""

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        sample_rate: int = 24000,
        model_id: str = "eleven_monolingual_v1",
    ) -> None:
        self._api_key = api_key
        self._voice_id = voice_id
        self._sample_rate = sample_rate
        self._model_id = model_id
        self._playback_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._playing = False

    async def speak(self, text: str) -> None:
        """Convert text to speech and play it through the default audio output."""
        if not self._api_key or not self._voice_id:
            logger.warning("TTS not configured, skipping speech output")
            return

        audio_data = await self._synthesize(text)
        if audio_data:
            await self._play_audio(audio_data)

    async def speak_streamed(self, text_stream: AsyncIterator[str]) -> None:
        """Stream text chunks to TTS and play audio as it arrives."""
        if not self._api_key or not self._voice_id:
            logger.warning("TTS not configured, skipping speech output")
            return

        buffer = ""
        sentence_endings = {".", "!", "?", "\n"}

        async for chunk in text_stream:
            buffer += chunk
            # Send complete sentences to TTS
            for ending in sentence_endings:
                if ending in buffer:
                    idx = buffer.rindex(ending) + 1
                    sentence = buffer[:idx].strip()
                    buffer = buffer[idx:]
                    if sentence:
                        audio = await self._synthesize(sentence)
                        if audio:
                            await self._play_audio(audio)
                    break

        # Flush remaining buffer
        if buffer.strip():
            audio = await self._synthesize(buffer.strip())
            if audio:
                await self._play_audio(audio)

    async def _synthesize(self, text: str) -> bytes | None:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}"
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": self._model_id,
            "voice_settings": {
                "stability": 0.6,
                "similarity_boost": 0.8,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                return resp.content
            except httpx.HTTPError as e:
                logger.warning("TTS synthesis failed: %s", e)
                return None

    async def _play_audio(self, audio_data: bytes) -> None:
        """Play raw audio bytes through the default output device."""
        loop = asyncio.get_event_loop()
        try:
            # ElevenLabs returns MP3; decode with numpy for simplicity.
            # In production, use pydub or ffmpeg for proper decoding.
            # For now, attempt direct playback assuming PCM-compatible data.
            await loop.run_in_executor(None, self._play_sync, audio_data)
        except Exception:
            logger.exception("Audio playback failed")

    def _play_sync(self, audio_data: bytes) -> None:
        """Synchronous audio playback (runs in executor)."""
        try:
            # Attempt to treat as raw PCM int16
            samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32767.0
            sd.play(samples, samplerate=self._sample_rate)
            sd.wait()
        except Exception:
            logger.debug("Direct PCM playback failed; audio may require MP3 decoding")
