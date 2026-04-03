#!/usr/bin/env python3
"""Mock MSFS Adapter — simulates the SimConnect bridge for testing.

Connects to the telemetry service on /ws/ingest, registers as an adapter,
streams fake telemetry, and logs + acks any commands it receives. No MSFS,
no .NET, no Windows required.

Usage:
    python tools/mock_adapter.py
    python tools/mock_adapter.py --aircraft "Cessna 172 Skyhawk"
    python tools/mock_adapter.py --phase CRUISE --altitude 5000

Pair with the web server to test the full voice → Claude → command pipeline
without a running simulator.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mock-adapter")

# ANSI colors for terminal output
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
RED = "\033[0;31m"
NC = "\033[0m"


# ---------------------------------------------------------------------------
# Simulated aircraft state
# ---------------------------------------------------------------------------

@dataclass
class MockAircraftState:
    """Mutable simulated aircraft state. Commands modify this in-place."""

    aircraft: str = "Cessna 172 Skyhawk"
    latitude: float = 40.6413
    longitude: float = -73.7781
    altitude_msl: float = 3000.0
    altitude_agl: float = 2500.0
    heading_magnetic: float = 270.0
    heading_true: float = 268.0
    pitch: float = -2.0
    bank: float = 0.0
    indicated_airspeed: float = 110.0
    true_airspeed: float = 115.0
    ground_speed: float = 108.0
    mach: float = 0.17
    vertical_speed: float = -500.0
    engine_rpm: float = 2300.0
    manifold_pressure: float = 24.0
    fuel_flow_gph: float = 8.5
    egt: float = 1200.0
    oil_temp: float = 180.0
    oil_pressure: float = 60.0
    autopilot_master: bool = False
    autopilot_heading: float = 270.0
    autopilot_altitude: float = 3000.0
    autopilot_vs: float = 0.0
    autopilot_speed: float = 0.0
    com1: float = 121.5
    com2: float = 122.8
    nav1: float = 110.3
    nav2: float = 0.0
    total_fuel_gal: float = 40.0
    fuel_weight_lbs: float = 240.0
    wind_speed: float = 8.0
    wind_direction: float = 310.0
    visibility_sm: float = 10.0
    temperature_c: float = 15.0
    barometer_inhg: float = 29.92
    gear_handle: bool = True
    flaps_percent: float = 0.0
    spoilers_percent: float = 0.0
    # Track command history for debugging
    command_log: list[dict[str, Any]] = field(default_factory=list)

    def apply_command(self, command: str, value: int) -> str:
        """Apply a SimConnect command and return a human-readable description."""
        cmd = command.upper()
        desc = f"{command}({value})"

        # --- Flaps ---
        if cmd == "FLAPS_UP":
            self.flaps_percent = 0.0
            desc = "Flaps UP (0%)"
        elif cmd == "FLAPS_FULL":
            self.flaps_percent = 100.0
            desc = "Flaps FULL (100%)"
        elif cmd == "FLAPS_1":
            self.flaps_percent = 10.0
            desc = "Flaps 1 (10%)"
        elif cmd == "FLAPS_2":
            self.flaps_percent = 20.0
            desc = "Flaps 2 (20%)"
        elif cmd == "FLAPS_3":
            self.flaps_percent = 30.0
            desc = "Flaps 3 (30%)"
        elif cmd == "FLAPS_SET":
            self.flaps_percent = round(value / 16383 * 100, 1)
            desc = f"Flaps SET to {self.flaps_percent}%"
        elif cmd == "FLAPS_INCR":
            self.flaps_percent = min(100, self.flaps_percent + 10)
            desc = f"Flaps INCR to {self.flaps_percent}%"
        elif cmd == "FLAPS_DECR":
            self.flaps_percent = max(0, self.flaps_percent - 10)
            desc = f"Flaps DECR to {self.flaps_percent}%"

        # --- Gear ---
        elif cmd == "GEAR_DOWN":
            self.gear_handle = True
            desc = "Gear DOWN"
        elif cmd == "GEAR_UP":
            self.gear_handle = False
            desc = "Gear UP"
        elif cmd == "GEAR_TOGGLE":
            self.gear_handle = not self.gear_handle
            desc = f"Gear TOGGLE → {'DOWN' if self.gear_handle else 'UP'}"

        # --- Autopilot ---
        elif cmd == "AP_MASTER":
            self.autopilot_master = not self.autopilot_master
            desc = f"AP Master → {'ON' if self.autopilot_master else 'OFF'}"
        elif cmd == "HEADING_BUG_SET":
            self.autopilot_heading = value
            desc = f"HDG Bug → {value}°"
        elif cmd == "AP_ALT_VAR_SET_ENGLISH":
            self.autopilot_altitude = value
            desc = f"AP ALT → {value} ft"
        elif cmd == "AP_VS_VAR_SET_ENGLISH":
            self.autopilot_vs = value
            desc = f"AP VS → {value:+d} fpm"
        elif cmd == "AP_SPD_VAR_SET":
            self.autopilot_speed = value
            desc = f"AP SPD → {value} kt"
        elif cmd in ("AP_HDG_HOLD", "AP_ALT_HOLD", "AP_VS_HOLD",
                      "AP_AIRSPEED_HOLD", "AP_NAV1_HOLD", "AP_APR_HOLD"):
            desc = f"{cmd} engaged"

        # --- Throttle ---
        elif cmd == "THROTTLE_SET":
            pct = round(value / 16383 * 100, 1)
            desc = f"Throttle → {pct}%"
        elif cmd in ("THROTTLE1_SET", "THROTTLE2_SET"):
            pct = round(value / 16383 * 100, 1)
            desc = f"{cmd} → {pct}%"

        # --- Radio ---
        elif cmd == "COM_RADIO_SET_HZ":
            self.com1 = value / 1_000_000
            desc = f"COM1 → {self.com1:.3f} MHz"
        elif cmd == "COM2_RADIO_SET_HZ":
            self.com2 = value / 1_000_000
            desc = f"COM2 → {self.com2:.3f} MHz"
        elif cmd == "NAV1_RADIO_SET_HZ":
            self.nav1 = value / 1_000_000
            desc = f"NAV1 → {self.nav1:.3f} MHz"
        elif cmd == "NAV2_RADIO_SET_HZ":
            self.nav2 = value / 1_000_000
            desc = f"NAV2 → {self.nav2:.3f} MHz"

        # --- Other ---
        elif cmd == "KOHLSMAN_SET":
            self.barometer_inhg = value / 100
            desc = f"Altimeter → {self.barometer_inhg:.2f} inHg"
        elif cmd == "PARKING_BRAKES":
            desc = "Parking brake TOGGLE"
        elif cmd == "SPOILERS_TOGGLE":
            desc = "Spoilers TOGGLE"
        elif cmd == "SPOILERS_SET":
            self.spoilers_percent = round(value / 16383 * 100, 1)
            desc = f"Spoilers → {self.spoilers_percent}%"
        elif cmd == "MIXTURE_SET":
            desc = f"Mixture → {round(value / 16383 * 100, 1)}%"
        elif cmd == "PROP_PITCH_SET":
            desc = f"Prop → {round(value / 16383 * 100, 1)}%"
        elif cmd == "ELEVATOR_TRIM_SET":
            desc = f"Trim → {value}"
        else:
            desc = f"UNKNOWN: {command}({value})"

        self.command_log.append({
            "time": time.strftime("%H:%M:%S"),
            "command": command,
            "value": value,
            "description": desc,
        })
        return desc

    def to_telemetry_json(self) -> dict[str, Any]:
        """Build telemetry JSON matching the bridge format."""
        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "connected": True,
            "aircraft": self.aircraft,
            "position": {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "altitude_msl": self.altitude_msl,
                "altitude_agl": self.altitude_agl,
            },
            "attitude": {
                "pitch": self.pitch,
                "bank": self.bank,
                "heading_true": self.heading_true,
                "heading_magnetic": self.heading_magnetic,
            },
            "speeds": {
                "indicated_airspeed": self.indicated_airspeed,
                "true_airspeed": self.true_airspeed,
                "ground_speed": self.ground_speed,
                "mach": self.mach,
                "vertical_speed": self.vertical_speed,
            },
            "engines": {
                "engine_count": 1,
                "engines": [
                    {
                        "rpm": self.engine_rpm,
                        "manifold_pressure": self.manifold_pressure,
                        "fuel_flow_gph": self.fuel_flow_gph,
                        "egt": self.egt,
                        "oil_temp": self.oil_temp,
                        "oil_pressure": self.oil_pressure,
                    }
                ],
            },
            "autopilot": {
                "master": self.autopilot_master,
                "heading": self.autopilot_heading,
                "altitude": self.autopilot_altitude,
                "vertical_speed": self.autopilot_vs,
                "airspeed": self.autopilot_speed,
            },
            "radios": {
                "com1": self.com1,
                "com2": self.com2,
                "nav1": self.nav1,
                "nav2": self.nav2,
            },
            "fuel": {
                "total_gallons": self.total_fuel_gal,
                "total_weight_lbs": self.fuel_weight_lbs,
            },
            "environment": {
                "wind_speed_kts": self.wind_speed,
                "wind_direction": self.wind_direction,
                "visibility_sm": self.visibility_sm,
                "temperature_c": self.temperature_c,
                "barometer_inhg": self.barometer_inhg,
            },
            "surfaces": {
                "gear_handle": self.gear_handle,
                "flaps_percent": self.flaps_percent,
                "spoilers_percent": self.spoilers_percent,
            },
        }


# ---------------------------------------------------------------------------
# Mock adapter WebSocket client
# ---------------------------------------------------------------------------

async def run_mock_adapter(
    service_url: str = "ws://localhost:8080/ws/ingest",
    adapter_id: str = "msfs-adapter",
    telemetry_hz: float = 2.0,
    state: MockAircraftState | None = None,
) -> None:
    """Connect to the telemetry service and simulate an MSFS adapter."""
    if state is None:
        state = MockAircraftState()

    log.info(
        "%s[MOCK ADAPTER]%s Connecting to %s", CYAN, NC, service_url
    )

    try:
        async with websockets.connect(service_url) as ws:
            # --- Register ---
            register_msg = json.dumps({
                "type": "register",
                "adapter_id": adapter_id,
                "sim_name": "msfs2024",
                "vehicle_type": "aircraft",
                "version": "mock-1.0",
            })
            await ws.send(register_msg)
            log.info(
                "%s[  OK  ]%s Registered as '%s' (aircraft: %s)",
                GREEN, NC, adapter_id, state.aircraft,
            )

            # --- Start telemetry streaming + command listening ---
            telemetry_task = asyncio.create_task(
                _stream_telemetry(ws, state, telemetry_hz)
            )
            command_task = asyncio.create_task(
                _listen_for_commands(ws, state)
            )

            print()
            print(f"{CYAN}{'='*60}{NC}")
            print(f"{CYAN}  Mock MSFS Adapter Running — {state.aircraft}{NC}")
            print(f"{CYAN}{'='*60}{NC}")
            print(f"  Telemetry: {telemetry_hz} Hz")
            print(f"  Altitude:  {state.altitude_msl:.0f} ft MSL")
            print(f"  Airspeed:  {state.indicated_airspeed:.0f} kt")
            print(f"  Flaps:     {state.flaps_percent:.0f}%")
            print(f"  Gear:      {'DOWN' if state.gear_handle else 'UP'}")
            print()
            print(f"  Waiting for commands from MERLIN...")
            print(f"{CYAN}{'='*60}{NC}")
            print()

            await asyncio.gather(telemetry_task, command_task)

    except websockets.ConnectionClosed:
        log.warning("Connection to telemetry service closed")
    except ConnectionRefusedError:
        log.error(
            "%sCannot connect to telemetry service at %s%s",
            RED, service_url, NC,
        )
        log.error("Is the telemetry service running? Try: docker compose up -d telemetry-service")
    except KeyboardInterrupt:
        log.info("Shutting down mock adapter")


async def _stream_telemetry(
    ws: websockets.WebSocketClientProtocol,
    state: MockAircraftState,
    hz: float,
) -> None:
    """Periodically send telemetry snapshots."""
    interval = 1.0 / hz
    t = 0.0
    while True:
        # Subtle state drift to make telemetry look alive
        state.altitude_msl += state.vertical_speed / 3600 * interval
        state.altitude_agl = max(0, state.altitude_msl - 500)
        state.heading_magnetic += math.sin(t * 0.1) * 0.1
        state.indicated_airspeed += math.sin(t * 0.3) * 0.2

        telemetry = state.to_telemetry_json()
        await ws.send(json.dumps(telemetry))
        t += interval
        await asyncio.sleep(interval)


async def _listen_for_commands(
    ws: websockets.WebSocketClientProtocol,
    state: MockAircraftState,
) -> None:
    """Listen for commands from the telemetry service and ack them."""
    async for message in ws:
        try:
            data = json.loads(message)
            if data.get("type") == "command":
                command_id = data.get("command_id", "")
                command = data.get("command", "")
                value = data.get("value", 0)

                # Apply the command to our mock state
                desc = state.apply_command(command, value)

                # Log it prominently
                print(
                    f"  {GREEN}>>> COMMAND RECEIVED:{NC} {desc}"
                    f"  {CYAN}(id: {command_id[:8]}){NC}"
                )

                # Send ack
                ack = json.dumps({
                    "type": "command_ack",
                    "command_id": command_id,
                    "success": True,
                    "message": desc,
                })
                await ws.send(ack)
                log.debug("Sent ack for %s", command_id[:8])

        except json.JSONDecodeError:
            log.warning("Received invalid JSON")
        except Exception as exc:
            log.warning("Error processing message: %s", exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mock MSFS adapter for testing MERLIN command pipeline",
    )
    parser.add_argument(
        "--url",
        default="ws://localhost:8080/ws/ingest",
        help="Telemetry service ingest URL",
    )
    parser.add_argument(
        "--adapter-id",
        default="msfs-adapter",
        help="Adapter ID to register as",
    )
    parser.add_argument(
        "--aircraft",
        default="Cessna 172 Skyhawk",
        help="Aircraft name to simulate",
    )
    parser.add_argument(
        "--altitude",
        type=float,
        default=3000.0,
        help="Starting altitude MSL (feet)",
    )
    parser.add_argument(
        "--airspeed",
        type=float,
        default=110.0,
        help="Starting indicated airspeed (knots)",
    )
    parser.add_argument(
        "--hz",
        type=float,
        default=2.0,
        help="Telemetry update frequency",
    )
    args = parser.parse_args()

    state = MockAircraftState(
        aircraft=args.aircraft,
        altitude_msl=args.altitude,
        indicated_airspeed=args.airspeed,
    )

    asyncio.run(
        run_mock_adapter(
            service_url=args.url,
            adapter_id=args.adapter_id,
            telemetry_hz=args.hz,
            state=state,
        )
    )


if __name__ == "__main__":
    main()
