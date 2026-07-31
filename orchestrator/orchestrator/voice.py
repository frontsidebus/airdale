"""Voice pipeline: microphone input and speech output via pluggable backends.

STT is delegated to a ``WhisperClient``; TTS is delegated to any client
satisfying the ``TTSClient`` protocol, so the synthesis backend is a config
choice rather than a code dependency. Includes audio preprocessing,
aviation-vocabulary-biased transcription, confidence scoring, and cancellable
playback for barge-in support.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from enum import StrEnum

import numpy as np

from .audio_processing import (
    SileroVAD,
    preprocess_audio,
    samples_to_wav_bytes,
)
from .tts import TTSClient
from .turn import SilenceTurnDetector, TurnDetector
from .whisper_client import WhisperClient, WhisperClientError

logger = logging.getLogger(__name__)


class InputMode(StrEnum):
    PUSH_TO_TALK = "push_to_talk"
    VOICE_ACTIVITY = "voice_activity"


class VoiceInput:
    """Handles microphone recording, VAD, and transcription via Docker Whisper service."""

    def __init__(
        self,
        whisper_client: WhisperClient,
        sample_rate: int = 16000,
        channels: int = 1,
        vad_threshold: float = 0.02,
        vad_silence_duration: float = 0.4,
        mode: InputMode = InputMode.PUSH_TO_TALK,
        turn_detector: TurnDetector | None = None,
    ) -> None:
        self._whisper_client = whisper_client
        self._sample_rate = sample_rate
        self._channels = channels
        self._vad_threshold = vad_threshold
        self._vad_silence_secs = vad_silence_duration
        self._mode = mode
        self._recording = False
        self._vad = SileroVAD(threshold=0.5, silence_ms=400)
        # Defaults to the pre-existing fixed-silence behaviour so constructing
        # VoiceInput without a detector changes nothing.
        self._turn_detector: TurnDetector = turn_detector or SilenceTurnDetector(
            silence_ms=int(vad_silence_duration * 1000)
        )

    @property
    def turn_detector(self) -> TurnDetector:
        return self._turn_detector

    @property
    def mode(self) -> InputMode:
        return self._mode

    @mode.setter
    def mode(self, value: InputMode) -> None:
        self._mode = value

    async def record_ptt(self) -> np.ndarray:
        """Record audio while push-to-talk is active."""
        import sounddevice as sd

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
        """Record audio using voice activity detection.

        Uses Silero VAD for neural speech endpoint detection when available.
        Falls back to RMS-based detection if torch is not installed.
        """
        import sounddevice as sd

        use_silero = self._vad.available
        detector = self._turn_detector
        detector.reset()
        if use_silero:
            logger.debug(
                "VAD recording started (Silero neural VAD, turn detector: %s)", detector.name
            )
            self._vad.reset()
        else:
            logger.debug("VAD recording started (RMS fallback, turn detector: %s)", detector.name)

        frames: list[np.ndarray] = []
        silence_frames = 0
        speech_detected = False
        blocksize = 1024
        chunk_duration_ms = int(blocksize / self._sample_rate * 1000)
        # RMS fallback uses the configured silence duration
        rms_silence_limit = int(self._vad_silence_secs * self._sample_rate / blocksize)
        # Acoustic VAD gates the turn detector: silence is cheap to spot, so it
        # decides *when* to ask, and the detector decides *whether* the turn is
        # over. Without this gate a semantic model would run on every chunk.
        probe_ms = detector.probe_silence_ms

        event = asyncio.Event()
        result_audio: list[np.ndarray | None] = [None]

        def callback(indata: np.ndarray, frame_count: int, time_info: dict, status: int) -> None:
            nonlocal silence_frames, speech_detected
            chunk = indata.copy()
            frames.append(chunk)
            flat = chunk.flatten()

            if use_silero:
                prob = self._vad.speech_probability(flat, self._sample_rate)
                is_speech = prob >= self._vad._threshold

                if is_speech:
                    speech_detected = True
                    silence_frames = 0
                elif speech_detected:
                    silence_frames += 1
                    accumulated_ms = silence_frames * chunk_duration_ms
                    if accumulated_ms >= probe_ms:
                        utterance = np.concatenate(frames, axis=0).flatten()
                        decision = detector.evaluate(utterance, self._sample_rate, accumulated_ms)
                        if decision.ended:
                            logger.debug(
                                "Turn ended after %dms silence (%s, p=%.3f)",
                                accumulated_ms,
                                decision.detector,
                                decision.probability,
                            )
                            result_audio[0] = utterance
                            event.set()
            else:
                # RMS fallback
                rms = np.sqrt(np.mean(flat**2))
                if rms > self._vad_threshold:
                    speech_detected = True
                    silence_frames = 0
                elif speech_detected:
                    silence_frames += 1
                    if silence_frames >= rms_silence_limit:
                        result_audio[0] = np.concatenate(frames, axis=0).flatten()
                        event.set()

        stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            blocksize=blocksize,
            callback=callback,
        )
        stream.start()
        await event.wait()
        stream.stop()
        stream.close()

        return result_audio[0] if result_audio[0] is not None else np.array([], dtype=np.float32)

    async def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio via the injected WhisperClient.

        Applies audio preprocessing (high-pass filter, silence trimming,
        normalization) before delegating to the shared WhisperClient for
        transcription with aviation-vocabulary biasing.
        """
        if audio.size == 0:
            return ""

        # Preprocess: filter noise, trim silence, normalize
        audio = preprocess_audio(audio, self._sample_rate)
        if audio.size == 0:
            logger.debug("Audio too short after preprocessing, skipping transcription")
            return ""

        wav_bytes = samples_to_wav_bytes(audio, self._sample_rate, self._channels)

        try:
            text = await self._whisper_client.transcribe(wav_bytes)
            logger.info("Transcribed: %s", text)
            return text
        except WhisperClientError as exc:
            logger.warning("Whisper transcription failed: %s", exc)
            return ""

    async def listen(self) -> str:
        """Record based on current mode and return transcription."""
        if self._mode == InputMode.PUSH_TO_TALK:
            audio = await self.record_ptt()
        else:
            audio = await self.record_vad()
        return await self.transcribe(audio)


class VoiceOutput:
    """TTS playback via the TTSClient protocol, with backend-aware decoding.

    Audio format is taken from ``tts_client.audio_content_type`` rather than
    assumed -- MP3 backends (ElevenLabs) are decoded via ffmpeg, while WAV/PCM
    backends (Kokoro, Cartesia in pcm mode) are played without a subprocess.

    Supports cancellation for barge-in: call cancel() to stop the current
    playback immediately when the user starts speaking.
    """

    def __init__(
        self,
        tts_client: TTSClient,
        sample_rate: int = 24000,
    ) -> None:
        self._tts = tts_client
        self._sample_rate = sample_rate
        self._cancelled = False
        self._playing = False

    @property
    def is_playing(self) -> bool:
        """Whether TTS audio is currently being played."""
        return self._playing

    def cancel(self) -> None:
        """Cancel current TTS playback for barge-in support."""
        self._cancelled = True
        if self._playing:
            try:
                import sounddevice as sd

                sd.stop()
            except Exception:
                pass
            self._playing = False
            logger.info("TTS playback cancelled (barge-in)")

    def reset(self) -> None:
        """Reset cancellation state for a new response."""
        self._cancelled = False

    async def speak(self, text: str) -> None:
        """Convert text to speech and play through default audio output."""
        if not text.strip():
            return

        self.reset()
        audio = await self._synthesize(text)
        if audio and not self._cancelled:
            await self._play_audio(audio)

    async def speak_streamed(self, text_stream: AsyncIterator[str]) -> None:
        """Buffer text into sentences, synthesize each, and play sequentially.

        Respects cancellation: stops synthesizing and playing if cancel() is called.
        """
        self.reset()
        buffer = ""
        sentence_endings = ".!?\n"

        async for chunk in text_stream:
            if self._cancelled:
                break

            buffer += chunk

            # Find the last sentence boundary
            last_boundary = -1
            for i, ch in enumerate(buffer):
                if ch in sentence_endings:
                    last_boundary = i

            if last_boundary >= 0:
                sentence = buffer[: last_boundary + 1].strip()
                buffer = buffer[last_boundary + 1 :]
                if sentence and not self._cancelled:
                    audio = await self._synthesize(sentence)
                    if audio and not self._cancelled:
                        await self._play_audio(audio)

        # Flush remaining
        if buffer.strip() and not self._cancelled:
            audio = await self._synthesize(buffer.strip())
            if audio and not self._cancelled:
                await self._play_audio(audio)

    async def _synthesize(self, text: str) -> bytes | None:
        """Delegate synthesis to the injected TTSClient.

        Voice settings, credentials, model selection, and endpoint URLs are all
        the backend's concern -- this method only handles degradation on failure.
        """
        try:
            audio = await self._tts.synthesize(text)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully, never crash the loop
            logger.warning("TTS synthesis failed: %s", exc)
            return None
        logger.info("TTS synthesized %d bytes for: %s", len(audio), text[:60])
        return audio

    async def _play_audio(self, audio: bytes) -> None:
        """Play synthesized audio, decoding first if the backend emits MP3."""
        loop = asyncio.get_running_loop()
        try:
            content_type = getattr(self._tts, "audio_content_type", "audio/mpeg")
            if "mpeg" in content_type or "mp3" in content_type:
                pcm_data = await self._decode_mp3(audio)
            else:
                pcm_data = self._decode_pcm(audio)
            if pcm_data is not None and not self._cancelled:
                self._playing = True
                await loop.run_in_executor(None, self._play_pcm, pcm_data)
                self._playing = False
        except Exception:
            self._playing = False
            logger.exception("Audio playback failed")

    @staticmethod
    def _decode_pcm(audio: bytes) -> np.ndarray | None:
        """Interpret WAV/PCM bytes as float32 samples without spawning ffmpeg.

        A 44-byte RIFF header is skipped when present; otherwise the payload is
        treated as raw signed 16-bit little-endian PCM.
        """
        payload = audio[44:] if audio[:4] == b"RIFF" else audio
        if not payload:
            return None
        # Guard against an odd trailing byte, which would break the int16 view.
        if len(payload) % 2:
            payload = payload[:-1]
        return np.frombuffer(payload, dtype=np.int16).astype(np.float32) / 32768.0

    async def _decode_mp3(self, mp3_data: bytes) -> np.ndarray | None:
        """Decode MP3 to PCM float32 array using ffmpeg."""
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(self._sample_rate),
            "-ac",
            "1",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=mp3_data)

        if proc.returncode != 0:
            logger.warning("ffmpeg decode failed: %s", stderr.decode()[:200])
            return None

        if len(stdout) == 0:
            return None

        samples = np.frombuffer(stdout, dtype=np.int16).astype(np.float32) / 32768.0
        return samples

    def _play_pcm(self, samples: np.ndarray) -> None:
        """Synchronous PCM playback via sounddevice."""
        import sounddevice as sd

        sd.play(samples, samplerate=self._sample_rate)
        sd.wait()
