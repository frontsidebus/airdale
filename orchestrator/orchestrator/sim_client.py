"""WebSocket client for the SimConnect bridge."""

from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum
from typing import Any, Callable, Coroutine

import websockets
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class FlightPhase(str, Enum):
    PREFLIGHT = "PREFLIGHT"
    TAXI = "TAXI"
    TAKEOFF = "TAKEOFF"
    CLIMB = "CLIMB"
    CRUISE = "CRUISE"
    DESCENT = "DESCENT"
    APPROACH = "APPROACH"
    LANDING = "LANDING"
    LANDED = "LANDED"


# ---------------------------------------------------------------------------
# Pydantic models matching the SimConnect bridge JSON field names exactly
# ---------------------------------------------------------------------------


class Position(BaseModel):
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_msl: float = 0.0  # feet MSL
    altitude_agl: float = 0.0  # feet AGL


class Attitude(BaseModel):
    pitch: float = 0.0  # degrees
    bank: float = 0.0  # degrees
    heading_true: float = 0.0  # degrees true
    heading_magnetic: float = 0.0  # degrees magnetic


class Speeds(BaseModel):
    indicated_airspeed: float = 0.0  # knots
    true_airspeed: float = 0.0  # knots
    ground_speed: float = 0.0  # knots
    mach: float = 0.0
    vertical_speed: float = 0.0  # feet per minute


class EngineData(BaseModel):
    """Single-engine parameter block as sent by the bridge."""
    rpm: float = 0.0
    manifold_pressure: float = 0.0
    fuel_flow_gph: float = 0.0
    egt: float = 0.0
    oil_temp: float = 0.0
    oil_pressure: float = 0.0


class Engines(BaseModel):
    """Engine section from the bridge, containing a count and array."""
    engine_count: int = 0
    engines: list[EngineData] = Field(default_factory=list)

    @property
    def active_engines(self) -> list[EngineData]:
        """Return only the engines that are actually installed (up to engine_count)."""
        return self.engines[: self.engine_count]


class AutopilotState(BaseModel):
    master: bool = False
    heading: float = 0.0
    altitude: float = 0.0
    vertical_speed: float = 0.0
    airspeed: float = 0.0


class RadioState(BaseModel):
    com1: float = 0.0
    com2: float = 0.0
    nav1: float = 0.0
    nav2: float = 0.0


class FuelState(BaseModel):
    total_gallons: float = 0.0
    total_weight_lbs: float = 0.0


class Environment(BaseModel):
    wind_speed_kts: float = 0.0
    wind_direction: float = 0.0  # degrees
    visibility_sm: float = 0.0  # statute miles
    temperature_c: float = 0.0  # celsius
    barometer_inhg: float = 29.92  # inHg


class SurfaceState(BaseModel):
    gear_handle: bool = False
    flaps_percent: float = 0.0
    spoilers_percent: float = 0.0


class SimState(BaseModel):
    """Complete snapshot of the simulator state.

    Field names match the SimConnect bridge broadcast JSON exactly.
    """

    timestamp: str = ""
    connected: bool = False
    aircraft: str = ""
    position: Position = Field(default_factory=Position)
    attitude: Attitude = Field(default_factory=Attitude)
    speeds: Speeds = Field(default_factory=Speeds)
    engines: Engines = Field(default_factory=Engines)
    autopilot: AutopilotState = Field(default_factory=AutopilotState)
    radios: RadioState = Field(default_factory=RadioState)
    fuel: FuelState = Field(default_factory=FuelState)
    environment: Environment = Field(default_factory=Environment)
    surfaces: SurfaceState = Field(default_factory=SurfaceState)
    # Computed / enriched by the orchestrator (not from bridge)
    flight_phase: FlightPhase = FlightPhase.PREFLIGHT

    @property
    def on_ground(self) -> bool:
        """Derived from altitude AGL — on the ground if below 10 feet."""
        return self.position.altitude_agl < 10

    def telemetry_summary(self) -> str:
        """One-line summary of key flight parameters for context injection."""
        parts = [
            f"Phase: {self.flight_phase.value}",
            f"Alt: {self.position.altitude_msl:.0f}ft",
            f"IAS: {self.speeds.indicated_airspeed:.0f}kt",
            f"HDG: {self.attitude.heading_magnetic:.0f}°",
            f"VS: {self.speeds.vertical_speed:+.0f}fpm",
        ]
        if not self.on_ground:
            parts.append(f"GS: {self.speeds.ground_speed:.0f}kt")
        if self.autopilot.master:
            parts.append("AP:ON")
        return " | ".join(parts)


StateCallback = Callable[[SimState], Coroutine[Any, Any, None]]


class SimConnectClient:
    """Manages the WebSocket connection to the SimConnect bridge."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._state = SimState()
        self._subscribers: list[StateCallback] = []
        self._listen_task: asyncio.Task[None] | None = None

    @property
    def state(self) -> SimState:
        return self._state

    async def connect(self) -> None:
        logger.info("Connecting to SimConnect bridge at %s", self._url)
        self._ws = await websockets.connect(self._url)
        self._listen_task = asyncio.create_task(self._listen_loop())
        logger.info("Connected to SimConnect bridge")

    async def disconnect(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("Disconnected from SimConnect bridge")

    async def get_state(self) -> SimState:
        """Return the cached sim state (updated continuously by the broadcast)."""
        return self._state

    def subscribe(self, callback: StateCallback) -> None:
        self._subscribers.append(callback)

    async def _listen_loop(self) -> None:
        """Background loop that receives state broadcasts from the bridge.

        The bridge sends the full state JSON directly (no wrapping ``type``
        field).  We identify state broadcasts by checking for the ``position``
        key.  Messages that contain a ``type`` field (e.g. ``state_response``)
        are logged and ignored — the broadcast is the authoritative source.
        """
        assert self._ws is not None
        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)

                    # The bridge broadcasts raw state JSON — identify it by
                    # the presence of the "position" key.
                    if "position" in data:
                        # Preserve the current flight_phase (set by the
                        # orchestrator's phase detector) across updates.
                        current_phase = self._state.flight_phase
                        self._state = SimState.model_validate(data)
                        self._state.flight_phase = current_phase

                        for cb in self._subscribers:
                            try:
                                await cb(self._state)
                            except Exception:
                                logger.exception("Error in state subscriber callback")
                    elif "type" in data:
                        # Informational response (e.g. state_response) — skip.
                        logger.debug(
                            "Received typed message from bridge: %s",
                            data.get("type"),
                        )
                    else:
                        logger.debug("Ignoring unrecognised bridge message")

                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON from bridge")
        except websockets.ConnectionClosed:
            logger.warning("SimConnect bridge connection closed")
        except asyncio.CancelledError:
            raise
