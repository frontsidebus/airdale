# Coding Conventions

**Analysis Date:** 2026-03-26

## Style & Formatting

**Python Linter/Formatter:** ruff (configured in `orchestrator/pyproject.toml`)
- Target version: Python 3.11
- Line length: 100 characters
- Rules enabled: `E` (pycodestyle), `F` (pyflakes), `I` (isort), `N` (pep8-naming), `UP` (pyupgrade), `B` (bugbear), `SIM` (simplify)

**Run linting and formatting:**
```bash
cd orchestrator && ruff check .
cd orchestrator && ruff format .
```

**C# (.NET 8):** Standard .NET conventions with nullable reference types enabled (`<Nullable>enable</Nullable>` in `adapters/msfs/SimConnectBridge.csproj`).

**JavaScript (web/):** No linter or formatter configured. Browser-target vanilla JS in `web/static/app.js`.

## Naming Conventions

**Python Files:**
- Use `snake_case.py` for all module files: `sim_client.py`, `claude_client.py`, `flight_phase.py`, `tts_preprocessor.py`
- Test files prefixed with `test_`: `test_sim_client.py`, `test_flight_phase.py`

**Python Functions and Variables:**
- `snake_case` for all functions and variables
- Private methods prefixed with underscore: `_build_system_prompt()`, `_detect_phase()`, `_trim_history()`
- Constants use `UPPER_SNAKE_CASE`: `TOOL_DEFINITIONS`, `STOP_SEQUENCES`, `DEFAULT_CHECKLISTS`, `PHASE_TOPICS`
- Module-level private constants use `_UPPER_SNAKE_CASE`: `_DEFAULT_WHISPER_URL`, `_MAX_RETRIES`, `_RETRY_BACKOFF`

**Python Classes:**
- `PascalCase`: `ClaudeClient`, `TelemetryClient`, `FlightPhaseDetector`, `ContextStore`, `WhisperClient`
- Pydantic models: `PascalCase`: `SimState`, `Position`, `Attitude`, `EngineData`, `TelemetryEnvelope`
- Enums: `PascalCase` class, `UPPER_SNAKE_CASE` members: `FlightPhase.PREFLIGHT`, `ConnectionState.CONNECTED`

**C# Naming:**
- `PascalCase` for public members, types, and methods: `ConvertToEnvelope()`, `IsConnected`
- `_camelCase` for private fields (inferred from test patterns)
- Properties: `PascalCase`: `Latitude`, `AltitudeMsl`, `IndicatedAirspeed`
- Namespace: `SimConnectBridge`, `SimConnectBridge.Models`, `SimConnectBridge.Tests`

## Code Patterns

### Module-Level Logger

Every Python module uses the standard library logger:
```python
import logging
logger = logging.getLogger(__name__)
```

### Future Annotations

All Python files use `from __future__ import annotations` as the first import for PEP 604 union syntax (`X | None`).

### Async/Await Throughout

The orchestrator is async-first. Use `async def` for any function that does I/O (WebSocket, HTTP, file). The event loop is the heartbeat of the system.

```python
# Correct: async for I/O operations
async def get_state(self) -> SimState:
    ...

# Correct: sync for pure computation
def update(self, state: SimState) -> FlightPhase:
    ...
```

### Error Handling

**Tool functions return error dicts rather than raising:**
```python
# From orchestrator/tools.py — tools return {"error": "..."} on failure
async def lookup_airport(identifier: str) -> dict[str, Any]:
    try:
        resp = await client.get(url, params={"apt": code})
        resp.raise_for_status()
    except httpx.HTTPError:
        return {"error": f"Lookup failed for {code}"}
```

**Retry with backoff for external services:**
```python
# From orchestrator/whisper_client.py — retries on connection/5xx, no retry on 4xx
for attempt in range(1, _MAX_RETRIES + 1):
    try:
        response = self._client.post(url, ...)
        response.raise_for_status()
        return response.text.strip()
    except httpx.ConnectError:
        if attempt == _MAX_RETRIES:
            raise WhisperClientError(f"failed after {_MAX_RETRIES} attempts")
        time.sleep(_RETRY_BACKOFF * attempt)
```

**Subscriber exceptions do not crash the event loop:**
```python
# From orchestrator/sim_client.py — callbacks are protected
for callback in self._subscribers:
    try:
        await callback(new_state)
    except Exception:
        logger.exception("Subscriber callback failed")
```

### Configuration

Use `pydantic-settings` `BaseSettings` for all configuration. Never hardcode keys, URLs, or magic numbers.

```python
# From orchestrator/config.py
class Settings(BaseSettings):
    model_config = {"env_file": str(_ENV_FILE), "env_file_encoding": "utf-8", "extra": "ignore"}
    anthropic_api_key: str = Field(description="Anthropic API key for Claude")
    claude_model: str = Field(default="claude-sonnet-4-20250514", description="...")
```

Access settings via `load_settings()` from `orchestrator/config.py`. Derived URLs are computed in a `@model_validator(mode="after")`.

### Section Separators in Source Files

Use comment blocks with dashes to delineate logical sections:

```python
# ---------------------------------------------------------------------------
# Connection state tracking
# ---------------------------------------------------------------------------
```

This pattern is used consistently across all Python source and test files.

## Data Modeling

**Pydantic `BaseModel` for all data structures crossing boundaries:**
- Telemetry models: `Position`, `Attitude`, `Speeds`, `EngineData`, `SimState` in `orchestrator/sim_client.py`
- Universal schema: `TelemetryEnvelope`, `AircraftExtensions` in `telemetry-service/telemetry/schema.py`
- All models use default values (e.g., `latitude: float = 0.0`) so they can be constructed with minimal data

**Dataclasses for internal config:**
```python
# From orchestrator/flight_phase.py
@dataclass
class PhaseThresholds:
    taxi_ground_speed: float = 5.0
    takeoff_speed: float = 40.0
    ...
```

**StrEnum for enumerations:**
```python
# From orchestrator/sim_client.py
class FlightPhase(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    TAXI = "TAXI"
    ...
```

**Computed properties on models:**
```python
# From orchestrator/sim_client.py — derived from raw telemetry
@property
def on_ground(self) -> bool:
    return self.position.altitude_agl < 10

@property
def active_engines(self) -> list[EngineData]:
    return self.engines[:self.engine_count]
```

## Import Organization

**Order (enforced by ruff `I` rule / isort-compatible):**
1. `__future__` imports
2. Standard library (`asyncio`, `json`, `logging`, `time`)
3. Third-party (`pytest`, `httpx`, `pydantic`, `websockets`, `anthropic`)
4. Local/project imports (`from orchestrator.sim_client import ...`, `from .config import ...`)

**Relative imports within a package:**
```python
# Inside orchestrator/orchestrator/
from .sim_client import FlightPhase, SimState
from .context_store import ContextStore
```

**Absolute imports in tests:**
```python
# Inside orchestrator/tests/
from orchestrator.sim_client import SimState, FlightPhase
from orchestrator.claude_client import ClaudeClient
```

**Path aliases:** None configured. All imports are standard relative or absolute.

## Documentation Patterns

**Module docstrings:** Every Python module has a module-level docstring describing its purpose:
```python
"""WebSocket client for the telemetry service.

Connects to the universal telemetry service (or directly to a legacy
SimConnect bridge) and receives telemetry state broadcasts.
"""
```

**Test module docstrings:** Describe what the test file covers:
```python
"""Tests for orchestrator.flight_phase -- FlightPhaseDetector state machine.

This is the most critical test file. It exercises the phase detection logic
with realistic telemetry sequences and verifies hysteresis behaviour.
"""
```

**Class docstrings:** Present on public classes, especially Pydantic models and detectors:
```python
class FlightPhaseDetector:
    """Analyzes SimState telemetry to determine the current flight phase.

    Uses a state-machine approach with hysteresis to prevent rapid phase
    oscillation.
    """
```

**Inline comments:** Used for section headers (dash separators) and to explain non-obvious behavior. No JSDoc/TSDoc style.

**C# XML doc comments:** Used on public APIs:
```csharp
/// <summary>
/// Tests for TelemetryServiceClient serialization, conversion, and state logic.
/// </summary>
```

**Field descriptions in Pydantic:** Use `Field(description="...")` for all settings fields in `orchestrator/config.py`.

## JSON Serialization

**Python:** Pydantic `model_dump()` / `model_validate()` for JSON round-trips.

**C# to Python wire format:** `JsonNamingPolicy.SnakeCaseLower` in the C# adapter ensures JSON field names match Python's `snake_case` convention across the WebSocket boundary.

```csharp
private static readonly JsonSerializerOptions JsonOptions = new()
{
    PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
};
```

---

*Convention analysis: 2026-03-26*
