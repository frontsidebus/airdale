# Testing Strategy

**Analysis Date:** 2026-03-26

## Test Framework & Tools

### Python (Orchestrator + Telemetry Service)

**Runner:** pytest >= 8.0
- Config: `orchestrator/pyproject.toml` and `telemetry-service/pyproject.toml`
- Async mode: `asyncio_mode = "auto"` (no need to mark every async test)

**Assertion Library:** Built-in `assert` + `pytest.approx()` for float comparisons

**Mocking:**
- `unittest.mock.AsyncMock` for async methods (WebSocket connections, API calls)
- `unittest.mock.MagicMock` for sync objects (ChromaDB collections)
- `unittest.mock.patch` for module-level replacements
- `respx` >= 0.21 for mocking `httpx` HTTP requests (used in `test_tools.py`)
- `pytest.MonkeyPatch` for environment variable injection (used in `test_config.py`)

**Additional:**
- `pytest-asyncio` >= 0.24 for async test support
- `pytest-mock` >= 3.14 (available but most tests use `unittest.mock` directly)
- `pytest_asyncio` fixtures for integration test lifecycle (Docker containers)

### C# (MSFS Adapter)

**Runner:** xUnit 2.7.0
- Config: `adapters/msfs/SimConnectBridge.Tests/SimConnectBridge.Tests.csproj`
- Test SDK: Microsoft.NET.Test.Sdk 17.9.0

**Assertion Library:** FluentAssertions 6.12.0
```csharp
envelope.AdapterId.Should().Be("msfs-test-01");
envelope.Position!.Latitude.Should().Be(47.6);
client.IsConnected.Should().BeFalse();
act.Should().NotThrow();
```

**No mocking framework:** Tests use source file linking to avoid SimConnect SDK dependency. The test project includes `Models/SimState.cs` and `TelemetryServiceClient.cs` directly via `<Compile Include="..\..\..." />`.

## Test Organization

### Directory Layout

```
orchestrator/
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures: SimState factories, mock helpers
│   ├── test_claude_client.py    # Claude API wrapper, system prompt, token budgets
│   ├── test_config.py           # Settings loading and env var overrides
│   ├── test_context_store.py    # ChromaDB chunking, queries, phase-aware retrieval
│   ├── test_flight_phase.py     # State machine, hysteresis, full flight sequences
│   ├── test_screen_capture.py   # CaptureManager frame handling
│   ├── test_sim_client.py       # SimState parsing, TelemetryClient, reconnection
│   ├── test_tools.py            # Tool function implementations (airport, checklist, etc.)
│   ├── test_tts_client.py       # ElevenLabs TTS client
│   ├── test_tts_preprocessor.py # Aviation text-to-speech preprocessing (ICAO)
│   └── test_whisper_client.py   # Whisper HTTP client, retry logic, health check

telemetry-service/
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # TelemetryEnvelope fixtures
│   ├── test_adapter_manager.py  # Adapter registration and consumer broadcast
│   ├── test_schema.py           # Universal schema model tests
│   └── test_service.py          # FastAPI endpoint integration tests

tests/                           # Root-level integration tests
├── __init__.py
└── integration/
    ├── __init__.py
    ├── conftest.py              # Docker helpers, mock WS server, sample audio/docs
    ├── test_context_store.py    # ChromaDB integration (requires Docker)
    ├── test_orchestrator_e2e.py # End-to-end with mock Claude + mock telemetry
    ├── test_simconnect_websocket.py  # WebSocket reconnection tests
    ├── test_tool_chain.py       # Tool execution chain tests
    └── test_whisper_pipeline.py # Whisper transcription (requires Docker)

adapters/msfs/SimConnectBridge.Tests/
├── SimConnectBridge.Tests.csproj
├── FlightPhaseIntegrationTests.cs
├── SimDataStructTests.cs
├── SimStateSerializationTests.cs
├── TelemetryServiceClientTests.cs
├── TestDataStructs.cs
└── WebSocketServerTests.cs
```

### Naming Conventions

**Python test files:** `test_{module_name}.py` mirroring the source module
**Python test classes:** `class Test{Feature}:` using PascalCase descriptive names
**Python test methods:** `def test_{scenario}(self) -> None:` with snake_case descriptions
**C# test classes:** `{Component}Tests` (e.g., `TelemetryServiceClientTests`)
**C# test methods:** `PascalCase_WithUnderscores` describing scenario (e.g., `ConvertToEnvelope_MapsPositionCorrectly`)

### Test Markers

Defined in `orchestrator/pyproject.toml`:
```python
markers = [
    "integration: integration tests (require external services or network)",
    "docker: tests that require Docker containers running",
    "network: tests that require internet access",
    "slow: tests that take a long time to run",
]
```

**Default filter:** `addopts = "-m 'not integration'"` -- integration tests are excluded by default.

**Integration tests use `pytestmark`:**
```python
# At module level in integration test files
pytestmark = [pytest.mark.integration]
```

## Test Patterns

### Test Class Organization

Tests are grouped into classes by feature area, with section separators:

```python
# ---------------------------------------------------------------------------
# Connection state and stats
# ---------------------------------------------------------------------------

class TestConnectionState:
    """Test connection state tracking and diagnostics."""

    def test_stats_default(self) -> None:
        client = TelemetryClient("ws://localhost:8080")
        stats = client.stats
        assert stats["connection_state"] == "DISCONNECTED"

    def test_last_message_age_infinity_when_no_messages(self) -> None:
        client = TelemetryClient("ws://localhost:8080")
        assert client.last_message_age == float("inf")
```

### Parametrized Tests

Use `@pytest.mark.parametrize` for data-driven tests, especially in TTS preprocessor and query classification:

```python
@pytest.mark.parametrize(
    "input_text,expected",
    [
        ("Climb to FL350", "Climb to flight level tree fife zero"),
        ("Descend FL180", "Descend flight level one eight zero"),
        ("Maintain FL045", "Maintain flight level zero four fife"),
    ],
)
def test_flight_level(self, input_text: str, expected: str) -> None:
    assert preprocess_for_tts(input_text) == expected
```

### Async Test Pattern

With `asyncio_mode = "auto"`, async tests just need `async def`:

```python
@pytest.mark.asyncio
async def test_connect_creates_listen_task(self) -> None:
    client = TelemetryClient("ws://localhost:8080")
    mock_ws = AsyncMock()
    mock_ws.__aiter__ = MagicMock(return_value=iter([]))
    with patch(
        "orchestrator.sim_client.websockets.connect",
        new_callable=AsyncMock,
        return_value=mock_ws,
    ):
        await client.connect()
        assert client._listen_task is not None
        await client.disconnect()
```

### Mocking WebSocket Connections

The standard pattern for mocking WebSocket message streams:

```python
async def fake_aiter():
    yield json.dumps(sample_data)

mock_ws = AsyncMock()
mock_ws.__aiter__ = lambda self: fake_aiter()
client._ws = mock_ws

await client._listen_loop()
```

### Mocking HTTP with respx

Used for external API calls (airport lookup, flight plan creation):

```python
@pytest.mark.asyncio
@respx.mock
async def test_successful_lookup_icao(self) -> None:
    respx.get("https://api.aviationapi.com/v1/airports", params={"apt": "KJFK"}).mock(
        return_value=httpx.Response(200, json={"KJFK": [{"facility_name": "JFK INTL"}]})
    )
    result = await lookup_airport("KJFK")
    assert result["identifier"] == "KJFK"
```

### Environment Variable Testing

Use `monkeypatch` (via the shared `mock_env_vars` fixture) to control settings:

```python
@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr("orchestrator.config.Settings.model_config", {
        "env_file": "", "env_file_encoding": "utf-8", "extra": "ignore",
    })
    env = {"ANTHROPIC_API_KEY": "sk-ant-test-key-000", ...}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return env
```

### C# Test Pattern

Uses `IDisposable` for test cleanup and static helper methods for test data:

```csharp
public class TelemetryServiceClientTests : IDisposable
{
    private readonly TelemetryServiceClient _client;

    public TelemetryServiceClientTests()
    {
        _client = new TelemetryServiceClient("ws://localhost:9999", "msfs-test-01", "msfs2024");
    }

    public void Dispose() => _client.Dispose();

    [Fact]
    public void ConvertToEnvelope_MapsAdapterMetadata()
    {
        var state = CreatePopulatedSimState();
        var envelope = _client.ConvertToEnvelope(state);
        envelope.AdapterId.Should().Be("msfs-test-01");
    }

    private static SimState CreatePopulatedSimState() => new SimState { ... };
}
```

## Fixtures and Test Data

### SimState Factory (conftest.py)

`orchestrator/tests/conftest.py` provides factory helpers and pre-built fixtures for every flight phase:

```python
def _make_sim_state(**overrides: Any) -> SimState:
    """Build a SimState with sensible defaults, applying overrides."""
    defaults = {"timestamp": "...", "connected": True, "aircraft": "Cessna 172 Skyhawk", ...}
    defaults.update(overrides)
    return SimState(**defaults)
```

**Available fixtures:**
- `sim_state_parked` -- engines off, on ramp
- `sim_state_taxiing` -- low speed, engines running
- `sim_state_takeoff_roll` -- accelerating on runway
- `sim_state_initial_climb` -- 500ft AGL, climbing
- `sim_state_cruise` -- FL065, level flight, AP on
- `sim_state_descent` -- descending from cruise
- `sim_state_approach` -- gear down, flaps, 1500ft AGL
- `sim_state_landing` -- short final, 50ft AGL

### Mock Helpers (conftest.py)

- `mock_websocket` -- `AsyncMock` with `send`/`recv`/`close`
- `mock_chromadb_collection` -- `MagicMock` with configurable query results
- `mock_env_vars` -- Environment variables for `Settings` without `.env` file
- `sample_bridge_broadcast` -- Raw JSON as broadcast by SimConnect bridge
- `sample_state_update_message` -- Serialized WebSocket message string

### Integration Test Fixtures

`tests/integration/conftest.py` provides:
- `docker_whisper` / `docker_chromadb` -- Session-scoped Docker container lifecycle
- `sample_wav_bytes` / `silent_wav_bytes` / `long_wav_bytes` -- Generated WAV audio
- `sample_document` / `sample_document_metadata` -- C172 POH text for ChromaDB ingestion
- `mock_simconnect_server` -- `MockTelemetryServer` WebSocket server for integration tests

### Flight Phase Test Helpers

`orchestrator/tests/test_flight_phase.py` defines focused helpers:

```python
def _state(*, ground_speed=0, indicated_airspeed=0, vertical_speed=0,
           altitude_agl=0, gear_handle=True, flaps_percent=0, rpm=0) -> SimState:
    """Shorthand factory for building a SimState focused on phase-relevant params."""

def _repeat_update(detector, state, n=5) -> FlightPhase:
    """Call detector.update n times to satisfy hysteresis."""
```

## Coverage

**Requirements:** No coverage thresholds enforced. No coverage configuration detected.

**Total tests:** 361 tests across Python and C# test suites (per CLAUDE.md).

**View coverage (if needed):**
```bash
cd orchestrator && pytest --cov=orchestrator --cov-report=term-missing
cd telemetry-service && pytest --cov=telemetry --cov-report=term-missing
```

## Test Categories

### Unit Tests (run by default)

Scope: Individual functions and classes with all dependencies mocked.

**Orchestrator (`orchestrator/tests/`):**
- Config loading and validation (`test_config.py`)
- SimState model parsing and telemetry summary (`test_sim_client.py`)
- Flight phase state machine with hysteresis (`test_flight_phase.py`)
- Claude client system prompt building, token budgets, tool dispatch (`test_claude_client.py`)
- Tool implementations: airport lookup, manual search, checklists, flight plans (`test_tools.py`)
- Whisper client: transcription, retry logic, confidence scoring (`test_whisper_client.py`)
- Context store: text splitting, ingestion, queries, phase-aware retrieval (`test_context_store.py`)
- TTS preprocessor: ICAO phraseology, markdown stripping, aviation acronyms (`test_tts_preprocessor.py`)
- Screen capture manager (`test_screen_capture.py`)

**Telemetry Service (`telemetry-service/tests/`):**
- Schema model validation (`test_schema.py`)
- Adapter manager registration and broadcasting (`test_adapter_manager.py`)
- FastAPI endpoint integration using `TestClient` (`test_service.py`)

**MSFS Adapter (`adapters/msfs/SimConnectBridge.Tests/`):**
- SimState serialization and round-trip (`SimStateSerializationTests.cs`)
- TelemetryEnvelope conversion and JSON format (`TelemetryServiceClientTests.cs`)
- SimConnect data struct mapping (`SimDataStructTests.cs`)

### Integration Tests (excluded by default, require `-m integration`)

Scope: Multiple components wired together, may require Docker services.

**Root integration tests (`tests/integration/`):**
- End-to-end orchestrator flow with mock Claude + mock telemetry (`test_orchestrator_e2e.py`)
- WebSocket reconnection scenarios (`test_simconnect_websocket.py`)
- Tool execution chains (`test_tool_chain.py`)
- ChromaDB document ingestion and retrieval (requires Docker) (`test_context_store.py`)
- Whisper transcription pipeline (requires Docker) (`test_whisper_pipeline.py`)

## Running Tests

### Python Orchestrator
```bash
cd orchestrator

# Run unit tests (default, excludes integration)
pytest

# Run all tests including integration
pytest -m ""

# Run only integration tests
pytest -m integration

# Run a specific test file
pytest tests/test_flight_phase.py

# Run a specific test class
pytest tests/test_claude_client.py::TestQueryClassification

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=orchestrator --cov-report=term-missing
```

### Telemetry Service
```bash
cd telemetry-service
pytest
```

### MSFS Adapter (C#)
```bash
cd adapters/msfs
dotnet test
```

### All Python Tests
```bash
# From project root -- no unified test runner; run each separately
cd orchestrator && pytest && cd ../telemetry-service && pytest
```

## Key Testing Principles

1. **No simulator required for most tests.** Record telemetry snapshots as JSON fixtures and replay through the orchestrator.

2. **Mock external services at the boundary.** WebSocket connections, Claude API, ChromaDB, Whisper HTTP, and aviation API are all mocked in unit tests.

3. **Factory helpers over raw constructors.** Use `_make_sim_state()` and phase-specific fixtures rather than building `SimState` from scratch in every test.

4. **Test hysteresis explicitly.** Flight phase tests verify that single detections do not trigger transitions -- repeated updates through `_repeat_update()` are required.

5. **Error paths are first-class test subjects.** Every tool function tests error returns, every client tests connection failures, and retry logic is verified with specific backoff timing.

6. **C# tests avoid SimConnect SDK dependency.** The test project links source files directly rather than referencing the main project, so tests run without the MSFS SDK installed.

---

*Testing analysis: 2026-03-26*
