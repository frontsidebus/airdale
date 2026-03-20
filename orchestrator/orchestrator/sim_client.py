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


class Position(BaseModel):
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0  # feet MSL
    altitude_agl: float = 0.0  # feet AGL


class Attitude(BaseModel):
    pitch: float = 0.0  # degrees
    bank: float = 0.0  # degrees
    heading: float = 0.0  # magnetic


class Speeds(BaseModel):
    indicated: float = 0.0  # knots
    true_airspeed: float = 0.0  # knots
    ground_speed: float = 0.0  # knots
    mach: float = 0.0
    vertical_speed: float = 0.0  # feet per minute


class EngineParams(BaseModel):
    rpm: list[float] = Field(default_factory=list)
    manifold_pressure: list[float] = Field(default_factory=list)
    fuel_flow: list[float] = Field(default_factory=list)
    egt: list[float] = Field(default_factory=list)
    oil_temp: list[float] = Field(default_factory=list)
    oil_pressure: list[float] = Field(default_factory=list)
    n1: list[float] = Field(default_factory=list)
    n2: list[float] = Field(default_factory=list)


class AutopilotState(BaseModel):
    master: bool = False
    heading_hold: bool = False
    altitude_hold: bool = False
    nav_hold: bool = False
    approach_hold: bool = False
    vertical_speed_hold: bool = False
    set_heading: float = 0.0
    set_altitude: float = 0.0
    set_speed: float = 0.0
    set_vertical_speed: float = 0.0


class RadioState(BaseModel):
    com1_active: float = 0.0
    com1_standby: float = 0.0
    com2_active: float = 0.0
    com2_standby: float = 0.0
    nav1_active: float = 0.0
    nav1_standby: float = 0.0
    nav2_active: float = 0.0
    nav2_standby: float = 0.0
    transponder: int = 1200
    adf: float = 0.0


class FuelState(BaseModel):
    quantities: list[float] = Field(default_factory=list)  # gallons per tank
    total: float = 0.0  # total gallons
    total_weight: float = 0.0  # total pounds


class Environment(BaseModel):
    wind_speed: float = 0.0  # knots
    wind_direction: float = 0.0  # degrees
    visibility: float = 0.0  # statute miles
    temperature: float = 0.0  # celsius
    pressure: float = 29.92  # inHg
    precipitation: str = "none"


class SurfaceState(BaseModel):
    gear_down: bool = True
    gear_retractable: bool = False
    flaps_position: int = 0  # 0-based index
    flaps_num_positions: int = 1
    spoilers_deployed: bool = False
    parking_brake: bool = False


class SimState(BaseModel):
    """Complete snapshot of the simulator state."""

    timestamp: float = 0.0
    aircraft_title: str = ""
    position: Position = Field(default_factory=Position)
    attitude: Attitude = Field(default_factory=Attitude)
    speeds: Speeds = Field(default_factory=Speeds)
    engine: EngineParams = Field(default_factory=EngineParams)
    autopilot: AutopilotState = Field(default_factory=AutopilotState)
    radios: RadioState = Field(default_factory=RadioState)
    fuel: FuelState = Field(default_factory=FuelState)
    environment: Environment = Field(default_factory=Environment)
    surfaces: SurfaceState = Field(default_factory=SurfaceState)
    flight_phase: FlightPhase = FlightPhase.PREFLIGHT
    on_ground: bool = True
    sim_paused: bool = False

    def telemetry_summary(self) -> str:
        """One-line summary of key flight parameters for context injection."""
        parts = [
            f"Phase: {self.flight_phase.value}",
            f"Alt: {self.position.altitude:.0f}ft",
            f"IAS: {self.speeds.indicated:.0f}kt",
            f"HDG: {self.attitude.heading:.0f}°",
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
        """Request and return the current sim state."""
        if self._ws is None:
            raise ConnectionError("Not connected to SimConnect bridge")
        await self._ws.send(json.dumps({"type": "get_state"}))
        raw = await self._ws.recv()
        data = json.loads(raw)
        self._state = SimState.model_validate(data)
        return self._state

    def subscribe(self, callback: StateCallback) -> None:
        self._subscribers.append(callback)

    async def _listen_loop(self) -> None:
        """Background loop that receives state updates from the bridge."""
        assert self._ws is not None
        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)
                    if data.get("type") == "state_update":
                        self._state = SimState.model_validate(data.get("data", {}))
                        for cb in self._subscribers:
                            try:
                                await cb(self._state)
                            except Exception:
                                logger.exception("Error in state subscriber callback")
                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON from bridge")
        except websockets.ConnectionClosed:
            logger.warning("SimConnect bridge connection closed")
        except asyncio.CancelledError:
            raise
