"""MERLIN orchestrator main entry point.

Connects the SimConnect bridge, voice pipeline, context store, and Claude API
into a unified conversation loop.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .claude_client import ClaudeClient
from .config import Settings, load_settings
from .context_store import ContextStore
from .flight_phase import FlightPhaseDetector
from .screen_capture import CaptureManager
from .sim_client import SimConnectClient, SimState
from .voice import InputMode, VoiceInput, VoiceOutput

logger = logging.getLogger(__name__)


class Orchestrator:
    """Top-level coordinator that wires all subsystems together."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sim_client = SimConnectClient(settings.simconnect_bridge_url)
        self._context_store = ContextStore(settings.chromadb_path)
        self._phase_detector = FlightPhaseDetector()
        self._capture_manager = CaptureManager(
            fps=settings.screen_capture_fps,
            enabled=settings.screen_capture_enabled,
        )
        self._voice_input = VoiceInput(
            whisper_model=settings.whisper_model,
            mode=InputMode.PUSH_TO_TALK,
        )
        self._voice_output = VoiceOutput(
            api_key=settings.elevenlabs_api_key,
            voice_id=settings.voice_id,
        )
        self._claude = ClaudeClient(
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
            sim_client=self._sim_client,
            context_store=self._context_store,
        )
        self._running = False

    async def start(self) -> None:
        """Initialize all subsystems and enter the main loop."""
        logger.info("MERLIN orchestrator starting up")

        try:
            await self._sim_client.connect()
        except Exception:
            logger.warning(
                "Could not connect to SimConnect bridge at %s; "
                "running in text-only mode without live telemetry",
                self._settings.simconnect_bridge_url,
            )

        self._sim_client.subscribe(self._on_state_update)
        await self._capture_manager.start()

        self._running = True
        logger.info("MERLIN is ready. Type a message or speak (PTT mode).")
        print("\n=== MERLIN AI Co-Pilot ===")
        print("Type your message, or 'voice' to toggle voice input.")
        print("Commands: /voice, /vad, /ptt, /capture, /clear, /quit\n")

        await self._conversation_loop()

    async def stop(self) -> None:
        self._running = False
        await self._capture_manager.stop()
        await self._sim_client.disconnect()
        logger.info("MERLIN orchestrator shut down")

    async def _conversation_loop(self) -> None:
        """Main loop: gather input, build context, call Claude, output response."""
        use_voice = False

        while self._running:
            try:
                # Get user input
                if use_voice:
                    print("[Listening...]")
                    user_text = await self._voice_input.listen()
                    if user_text:
                        print(f"You: {user_text}")
                    else:
                        continue
                else:
                    try:
                        user_text = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: input("Captain> ")
                        )
                    except EOFError:
                        break

                user_text = user_text.strip()
                if not user_text:
                    continue

                # Handle commands
                if user_text.startswith("/"):
                    if await self._handle_command(user_text):
                        if user_text == "/voice":
                            use_voice = not use_voice
                        continue

                # Get current sim state and detect flight phase
                try:
                    sim_state = await self._sim_client.get_state()
                    detected_phase = self._phase_detector.update(sim_state)
                    sim_state.flight_phase = detected_phase
                except Exception:
                    sim_state = SimState()

                # Optionally grab screen capture for vision
                image_b64 = None
                if self._capture_manager.enabled:
                    image_b64 = await self._capture_manager.get_frame_base64()

                # Stream Claude response
                print("MERLIN: ", end="", flush=True)
                full_response = ""
                tts_chunks: list[str] = []

                async for chunk in self._claude.chat(
                    user_text,
                    sim_state=sim_state,
                    image_base64=image_b64,
                ):
                    print(chunk, end="", flush=True)
                    full_response += chunk
                    tts_chunks.append(chunk)

                print()  # newline after response

                # TTS output (non-blocking)
                if use_voice and full_response:
                    asyncio.create_task(self._voice_output.speak(full_response))

            except KeyboardInterrupt:
                print("\nUse /quit to exit.")
            except Exception:
                logger.exception("Error in conversation loop")
                print("\n[MERLIN encountered an error. Check logs for details.]")

    async def _handle_command(self, cmd: str) -> bool:
        """Process slash commands. Returns True if command was handled."""
        cmd = cmd.lower().strip()

        if cmd == "/quit":
            self._running = False
            print("Shutting down MERLIN...")
            return True

        if cmd == "/voice":
            print("Voice input toggled. (Handled by caller.)")
            return True

        if cmd == "/vad":
            self._voice_input.mode = InputMode.VOICE_ACTIVITY
            print("Switched to voice-activity-detection mode.")
            return True

        if cmd == "/ptt":
            self._voice_input.mode = InputMode.PUSH_TO_TALK
            print("Switched to push-to-talk mode.")
            return True

        if cmd == "/capture":
            if self._capture_manager.enabled:
                await self._capture_manager.stop()
                print("Screen capture disabled.")
            else:
                self._capture_manager._enabled = True
                await self._capture_manager.start()
                print("Screen capture enabled.")
            return True

        if cmd == "/clear":
            self._claude.clear_history()
            print("Conversation history cleared.")
            return True

        if cmd == "/status":
            try:
                state = await self._sim_client.get_state()
                print(f"SimConnect: Connected | {state.telemetry_summary()}")
            except Exception:
                print("SimConnect: Not connected")
            print(f"Docs in store: {self._context_store.document_count}")
            print(f"Screen capture: {'on' if self._capture_manager.enabled else 'off'}")
            return True

        print(f"Unknown command: {cmd}")
        return True

    async def _on_state_update(self, state: SimState) -> None:
        """Callback for sim state updates from the bridge."""
        detected_phase = self._phase_detector.update(state)
        state.flight_phase = detected_phase


async def async_main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    settings = load_settings()
    orchestrator = Orchestrator(settings)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(orchestrator.stop()))
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler

    try:
        await orchestrator.start()
    finally:
        await orchestrator.stop()


def run() -> None:
    """Entry point for the merlin console script."""
    asyncio.run(async_main())


if __name__ == "__main__":
    run()
