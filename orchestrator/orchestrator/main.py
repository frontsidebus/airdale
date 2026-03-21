"""MERLIN orchestrator main entry point.

Connects the SimConnect bridge, voice pipeline, context store, and Claude API
into a unified conversation loop.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

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

    def __init__(self, settings: Settings, text_only: bool = False) -> None:
        self._settings = settings
        self._text_only = text_only

        self._sim_client = SimConnectClient(settings.simconnect_bridge_url)
        self._context_store = ContextStore(settings.chromadb_url)
        self._phase_detector = FlightPhaseDetector()
        self._capture_manager = CaptureManager(
            fps=settings.screen_capture_fps,
            enabled=settings.screen_capture_enabled,
        )
        self._voice_input = VoiceInput(
            whisper_url=settings.whisper_url,
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
        self._sim_connected = False
        self._tts_enabled = bool(settings.elevenlabs_api_key and settings.voice_id)

    async def start(self) -> None:
        """Initialize all subsystems and enter the main loop."""
        logger.info("MERLIN orchestrator starting up")

        # Try connecting to the sim bridge (non-fatal if unavailable)
        if not self._text_only:
            try:
                await self._sim_client.connect()
                self._sim_connected = True
                self._sim_client.subscribe(self._on_state_update)
            except Exception:
                logger.warning(
                    "Could not connect to SimConnect bridge at %s; "
                    "running in text-only mode without live telemetry",
                    self._settings.simconnect_bridge_url,
                )
        else:
            logger.info("Text-only mode: skipping SimConnect bridge connection")

        await self._capture_manager.start()

        self._running = True
        logger.info("MERLIN is ready.")

        mode_label = "text-only" if not self._sim_connected else "sim-connected"
        tts_label = "TTS enabled" if self._tts_enabled else "TTS disabled"

        print(f"\n=== MERLIN AI Co-Pilot ({mode_label}, {tts_label}) ===")
        print("Type your message, or use /voice to toggle voice input.")
        print("Commands: /voice, /vad, /ptt, /capture, /tts, /clear, /status, /quit\n")

        await self._conversation_loop()

    async def stop(self) -> None:
        self._running = False
        await self._capture_manager.stop()
        if self._sim_connected:
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
                    cmd_lower = user_text.lower().strip()
                    handled = await self._handle_command(cmd_lower)
                    if handled:
                        if cmd_lower == "/voice":
                            use_voice = not use_voice
                        continue

                # Get current sim state and detect flight phase
                sim_state = self._get_current_sim_state()

                # Optionally grab screen capture for vision
                image_b64 = None
                if self._capture_manager.enabled:
                    image_b64 = await self._capture_manager.get_frame_base64()

                # Stream Claude response
                print("MERLIN: ", end="", flush=True)
                full_response = ""

                async for chunk in self._claude.chat(
                    user_text,
                    sim_state=sim_state,
                    image_base64=image_b64,
                ):
                    print(chunk, end="", flush=True)
                    full_response += chunk

                print()  # newline after response

                # TTS output (non-blocking) -- works in text mode too
                if self._tts_enabled and full_response:
                    asyncio.create_task(self._voice_output.speak(full_response))

            except KeyboardInterrupt:
                print("\nUse /quit to exit.")
            except Exception:
                logger.exception("Error in conversation loop")
                print("\n[MERLIN encountered an error. Check logs for details.]")

    def _get_current_sim_state(self) -> SimState:
        """Return the latest sim state, or a default empty state."""
        if self._sim_connected:
            state = self._sim_client.state
            detected_phase = self._phase_detector.update(state)
            state.flight_phase = detected_phase
            return state
        return SimState()

    async def _handle_command(self, cmd: str) -> bool:
        """Process slash commands. Returns True if command was handled."""
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

        if cmd == "/tts":
            self._tts_enabled = not self._tts_enabled
            state_label = "enabled" if self._tts_enabled else "disabled"
            print(f"TTS {state_label}.")
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
            if self._sim_connected:
                state = self._sim_client.state
                print(f"SimConnect: Connected | {state.telemetry_summary()}")
            else:
                print("SimConnect: Not connected (text-only mode)")
            print(f"Context store: {'available' if self._context_store.available else 'unavailable'}")
            print(f"Docs in store: {self._context_store.document_count}")
            print(f"TTS: {'enabled' if self._tts_enabled else 'disabled'}")
            print(f"Screen capture: {'on' if self._capture_manager.enabled else 'off'}")
            return True

        print(f"Unknown command: {cmd}")
        return True

    async def _on_state_update(self, state: SimState) -> None:
        """Callback for sim state updates from the bridge."""
        detected_phase = self._phase_detector.update(state)
        state.flight_phase = detected_phase


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MERLIN AI Co-Pilot Orchestrator")
    parser.add_argument(
        "--text-only",
        action="store_true",
        default=False,
        help="Skip SimConnect bridge connection (text chat only)",
    )
    return parser.parse_args()


async def async_main() -> None:
    args = _parse_args()
    settings = load_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    orchestrator = Orchestrator(settings, text_only=args.text_only)

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
