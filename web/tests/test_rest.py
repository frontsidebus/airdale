"""REST endpoint tests for the MERLIN web server.

Covers:
- WTST-07: Status endpoint reports subsystem health
- WTST-04: Transcription endpoint returns text and confidence
- WTST-05: TTS phrase cache hits/misses and not-configured handling
- AUTH-08: /api/status reports the authority level, the reason for it, and
  command-path health, and never reports an absent authority state as `full`
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport
from orchestrator.authority import AuthorityLevel, AuthorityReason, AuthorityState
from orchestrator.sim_client import HealthMonitor

# ---------------------------------------------------------------------------
# WTST-07: Status endpoint
# ---------------------------------------------------------------------------


async def test_status_returns_subsystem_health(test_app, mock_app_state):
    """GET /api/status returns 200 with correct subsystem health fields."""
    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")

    assert resp.status_code == 200
    data = resp.json()
    assert "sim_connected" in data
    assert "chromadb_available" in data
    assert "whisper_available" in data
    assert "elevenlabs_configured" in data
    assert "claude_model" in data
    assert data["chromadb_available"] is True
    assert data["whisper_available"] is True
    assert data["elevenlabs_configured"] is True
    assert data["claude_model"] == "claude-sonnet-4-20250514"


async def test_status_whisper_unavailable(test_app, mock_app_state):
    """When whisper_client.is_available returns False, whisper_available is False."""
    mock_app_state.whisper_client.is_available = AsyncMock(return_value=False)

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")

    assert resp.status_code == 200
    assert resp.json()["whisper_available"] is False


# ---------------------------------------------------------------------------
# WTST-04: Transcription endpoint
# ---------------------------------------------------------------------------


@dataclass
class _FakeTranscriptionResult:
    """Minimal stand-in for orchestrator.whisper_client.TranscriptionResult."""

    text: str
    confidence: float
    language: str = "en"
    duration: float = 1.0


async def test_transcribe_returns_text_and_confidence(test_app, mock_app_state):
    """POST /api/transcribe with WAV file returns {text, confidence} from mocked whisper."""
    mock_app_state.whisper_client.transcribe_with_confidence.return_value = (
        _FakeTranscriptionResult(text="check altimeter setting", confidence=0.92)
    )

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/transcribe",
            files={"file": ("audio.wav", b"RIFF" + b"\x00" * 100, "audio/wav")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "check altimeter setting"
    assert data["confidence"] == 0.92
    assert "low_confidence" not in data


async def test_transcribe_low_confidence_flag(test_app, mock_app_state):
    """When confidence < 0.4, response includes low_confidence=True."""
    mock_app_state.whisper_client.transcribe_with_confidence.return_value = (
        _FakeTranscriptionResult(text="garbled input", confidence=0.25)
    )

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/transcribe",
            files={"file": ("audio.wav", b"RIFF" + b"\x00" * 100, "audio/wav")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "garbled input"
    assert data["confidence"] == 0.25
    assert data["low_confidence"] is True


async def test_transcribe_webm_direct(test_app, mock_app_state):
    """POST with webm content type transcribes directly via whisper_client."""
    mock_app_state.whisper_client.transcribe_with_confidence.return_value = (
        _FakeTranscriptionResult(text="request flight following", confidence=0.88)
    )

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/transcribe",
            files={
                "file": (
                    "audio.webm",
                    b"\x1a\x45\xdf\xa3" + b"\x00" * 100,
                    "audio/webm",
                )
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "request flight following"
    assert data["confidence"] == 0.88


# ---------------------------------------------------------------------------
# WTST-05: TTS phrase cache and synthesis
# ---------------------------------------------------------------------------


async def test_tts_cache_hit(test_app, mock_app_state):
    """Pre-populated tts_cache returns cached audio without calling tts_client."""
    fake_mp3 = b"\xff\xfb\x90\x00" * 50
    mock_app_state.tts_cache["Roger."] = fake_mp3

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/tts", json={"text": "Roger."})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == fake_mp3
    # tts_client.post should NOT have been called
    mock_app_state.tts_client.post.assert_not_called()


async def test_tts_cache_miss_calls_client(test_app, mock_app_state):
    """POST /api/tts with uncached text calls tts_client.post and returns response."""
    fake_audio = b"fake-mp3-audio-bytes"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = fake_audio
    mock_response.raise_for_status = MagicMock()
    mock_app_state.tts_client.post = AsyncMock(return_value=mock_response)

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/tts",
            json={"text": "Climb and maintain flight level three five zero."},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == fake_audio
    mock_app_state.tts_client.post.assert_called_once()


async def test_tts_not_configured_returns_503(test_app, mock_app_state):
    """When elevenlabs_api_key is empty, TTS returns 503."""
    mock_app_state.settings.elevenlabs_api_key = ""

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/tts", json={"text": "Roger."})

    assert resp.status_code == 503
    err = resp.json()["error"].lower()
    assert "not configured" in err or "no tts backend" in err


# ---------------------------------------------------------------------------
# AUTH-08: the authority layer is never optional on the browser path
# ---------------------------------------------------------------------------

#: Repeated in the failure message of every test that pins the fail-safe wiring,
#: because this regression is silent: nothing raises, the endpoint keeps returning
#: 200, and the reported state is indistinguishable from a deliberate one.
_FAIL_OPEN_REGRESSION = (
    "REGRESSION (threat T-02-09-06): a swallowed AuthorityState construction error "
    "leaves state.authority None. tools.py reads a None authority as FULL, and the "
    "floor, the ack watchdog and the override cooldown in sim_client.py are all "
    "guarded on `is not None` -- so the whole authority layer would be off on the "
    "browser path regardless of AUTHORITY_LEVEL, while /api/status reported a "
    "deliberate `full` / `config` setup. On failure the lifespan MUST substitute "
    "AuthorityState.degraded_fallback(...), never None."
)


class _RaisingAuthorityState:
    """Stands in for ``AuthorityState`` when its construction is broken.

    ``degraded_fallback`` still works: the real one is built from enum literals
    only, precisely so it survives the failure it is replacing.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("authority construction exploded")

    @classmethod
    def degraded_fallback(cls, detail: str) -> AuthorityState:
        return AuthorityState.degraded_fallback(detail)


class _TotallyBrokenAuthorityState(_RaisingAuthorityState):
    """Even the fallback fails; startup must abort rather than serve unrestricted."""

    @classmethod
    def degraded_fallback(cls, detail: str) -> AuthorityState:
        raise RuntimeError("fallback construction exploded too")


@asynccontextmanager
async def _started_web_app(monkeypatch, *, authority_cls=None, connected=True):
    """Run the real ``lifespan`` with every network-touching collaborator stubbed.

    ``httpx.ASGITransport`` does not run lifespan events, so the context manager is
    entered directly against a stand-in app object. That also keeps the real
    module-level ``app.state`` untouched; routes are pointed at the state startup
    produced through ``dependency_overrides``.
    """
    import web.server as srv

    if authority_cls is not None:
        monkeypatch.setattr(srv, "AuthorityState", authority_cls)

    sim_client = MagicMock()
    sim_client.connect = AsyncMock(
        side_effect=None if connected else ConnectionRefusedError("telemetry offline")
    )
    sim_client.disconnect = AsyncMock()
    sim_client.subscribe = MagicMock()
    telemetry_factory = MagicMock(return_value=sim_client)
    monkeypatch.setattr(srv, "TelemetryClient", telemetry_factory)

    claude_factory = MagicMock()
    monkeypatch.setattr(srv, "ClaudeClient", claude_factory)

    context_store = MagicMock()
    context_store.available = True
    context_store.document_count = 7
    monkeypatch.setattr(srv, "ContextStore", MagicMock(return_value=context_store))

    whisper = AsyncMock()
    whisper.is_available = AsyncMock(return_value=True)
    monkeypatch.setattr(srv, "WhisperClient", MagicMock(return_value=whisper))
    monkeypatch.setattr(srv, "DeepgramSTTClient", MagicMock(return_value=AsyncMock()))
    monkeypatch.setattr(srv, "CartesiaClient", MagicMock(return_value=AsyncMock()))

    turn_detector = MagicMock()
    turn_detector.available = True
    monkeypatch.setattr(srv, "create_turn_detector", MagicMock(return_value=turn_detector))

    # Never let a test reach the real TTS vendor.
    monkeypatch.setattr(srv, "_prepopulate_tts_cache", AsyncMock())

    holder = SimpleNamespace(state=SimpleNamespace())
    async with srv.lifespan(holder):
        yield SimpleNamespace(
            state=holder.state.app_state,
            telemetry_factory=telemetry_factory,
            claude_factory=claude_factory,
            sim_client=sim_client,
        )


async def test_lifespan_degrades_to_advisory_when_authority_cannot_be_built(test_app, monkeypatch):
    """A broken AuthorityState construction restricts MERLIN; it does not free it."""
    import web.server as srv

    async with _started_web_app(monkeypatch, authority_cls=_RaisingAuthorityState) as started:
        state = started.state
        assert state.authority is not None, _FAIL_OPEN_REGRESSION
        assert state.authority.level is AuthorityLevel.ADVISORY, _FAIL_OPEN_REGRESSION
        assert state.authority.reason is AuthorityReason.DEGRADED, _FAIL_OPEN_REGRESSION

        srv.app.dependency_overrides[srv.get_app_state] = lambda: state
        transport = ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/status")

    assert resp.status_code == 200, "the server must still serve, just with less authority"
    data = resp.json()
    assert data["authority_level"] == "advisory", _FAIL_OPEN_REGRESSION
    assert data["authority_reason"] == "degraded", _FAIL_OPEN_REGRESSION
    assert data["subsystems"]["command_path"]["healthy"] is False


async def test_lifespan_still_hands_the_degraded_state_to_the_command_path(monkeypatch):
    """The degraded state reaches the floor and the gate, not just the status page."""
    async with _started_web_app(monkeypatch, authority_cls=_RaisingAuthorityState) as started:
        state = started.state
        assert started.telemetry_factory.call_args.kwargs["authority"] is state.authority
        assert started.claude_factory.call_args.kwargs["authority"] is state.authority


async def test_lifespan_aborts_when_even_the_degraded_fallback_fails(monkeypatch):
    """A fallback that fails the way the thing it replaces failed is not a fallback."""
    with pytest.raises(RuntimeError, match="fallback construction exploded"):
        async with _started_web_app(monkeypatch, authority_cls=_TotallyBrokenAuthorityState):
            pytest.fail(
                "startup must abort rather than serve with state.authority None. "
                + _FAIL_OPEN_REGRESSION
            )


async def test_lifespan_shares_one_authority_state_across_the_object_graph(monkeypatch):
    """Telemetry client, Claude client and override detector hold the same object."""
    async with _started_web_app(monkeypatch) as started:
        state = started.state
        assert state.authority is not None, _FAIL_OPEN_REGRESSION
        assert state.health is not None

        telemetry_kwargs = started.telemetry_factory.call_args.kwargs
        assert telemetry_kwargs["authority"] is state.authority
        assert telemetry_kwargs["health"] is state.health
        assert started.claude_factory.call_args.kwargs["authority"] is state.authority

        assert state.override_detector is not None
        # Identity, not equality: a copy would let the gate, the floor and the
        # detector disagree about the current level.
        assert state.override_detector._authority is state.authority

        # Its own subscriber, not a call from inside the phase-detector closure,
        # so a failure in one cannot suppress the other (D-11).
        subscribed = [call.args[0] for call in started.sim_client.subscribe.call_args_list]
        assert state.override_detector.on_telemetry_update in subscribed
        assert len(subscribed) >= 2


async def test_lifespan_registers_the_same_subsystem_set_as_the_cli(monkeypatch):
    """The browser and the CLI must not report different subsystem sets (D-17)."""
    async with _started_web_app(monkeypatch) as started:
        assert started.state.health is not None
        assert set(started.state.health.summary()) >= {
            "simconnect_bridge",
            "chromadb",
            "whisper",
            "claude_api",
            "command_path",
        }


async def test_status_reports_config_reason_on_a_healthy_start(test_app, monkeypatch):
    """A healthy start reports the configured level with reason `config`."""
    import web.server as srv

    async with _started_web_app(monkeypatch) as started:
        state = started.state
        srv.app.dependency_overrides[srv.get_app_state] = lambda: state
        transport = ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/status")
        expected_level = state.authority.level.value

    data = resp.json()
    assert data["authority_level"] == expected_level
    assert data["authority_reason"] == "config"
    assert data["authority"]["degraded_detail"] == ""
    # Registered but never seen: age must render as null, not Infinity. A verbatim
    # HealthMonitor.summary() would 500 here (allow_nan=False).
    assert data["subsystems"]["command_path"]["age_seconds"] is None


# ---------------------------------------------------------------------------
# AUTH-08 / D-17: /api/status renders level, reason and command-path health
# ---------------------------------------------------------------------------

#: The keys /api/status carried before this plan, including the three plan 02-03
#: added. The endpoint is extended, never replaced.
_LEGACY_STATUS_KEYS = (
    "sim_connected",
    "chromadb_available",
    "chromadb_documents",
    "stt_backend",
    "stt_available",
    "tts_backend",
    "tts_available",
    "whisper_available",
    "elevenlabs_configured",
    "claude_model",
    "telemetry_service_url",
    "turn_probe_available",
    "turn_probe_silence_ms",
    "vad_silence_ms",
)

_MISSING_BRANCH = (
    "A level or reason with no rendering path in /api/status. CLAUDE.md records "
    "what this costs: tts_configured was missing its Cartesia arm and reported a "
    "working setup as unconfigured for months -- a missing branch does not error, "
    "it silently reports the wrong thing. AuthorityLevel has 3 members and "
    "AuthorityReason 4, so read them out of AuthorityState.summary() rather than "
    "branching per level (threat T-02-09-04)."
)


class _StubAuthorityState:
    """Only what ``/api/status`` reads: a ``summary()`` returning a fixed pair.

    Driving the render off a stub rather than the real state machine is the point
    -- it exercises all 12 level-by-reason combinations regardless of which ones
    the machine can actually reach, because the guard being tested is "is there a
    rendering path", not "can this state occur".
    """

    def __init__(self, level: str, reason: str) -> None:
        self._summary = {
            "level": level,
            "reason": reason,
            "configured_level": "full",
            "cooldown_remaining_s": 0.0,
            "watchdog_latched": False,
            "consecutive_timeouts": 0,
            "degraded_detail": "",
        }

    def summary(self) -> dict:
        return dict(self._summary)


async def _get_status(test_app) -> dict:
    """GET /api/status through the ASGI transport and return the decoded body."""
    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.parametrize("reason", [member.value for member in AuthorityReason])
@pytest.mark.parametrize("level", [member.value for member in AuthorityLevel])
async def test_status_renders_every_level_by_reason_combination(
    test_app, mock_app_state, level, reason
):
    """All 3 levels x 4 reasons render; a missing arm fails loudly rather than lying."""
    mock_app_state.authority = _StubAuthorityState(level, reason)

    data = await _get_status(test_app)

    assert data["authority_level"] == level, _MISSING_BRANCH
    assert data["authority_reason"] == reason, _MISSING_BRANCH
    assert data["authority"]["level"] == level, _MISSING_BRANCH
    assert data["authority"]["reason"] == reason, _MISSING_BRANCH


async def test_status_reports_absent_authority_as_advisory_degraded(test_app, mock_app_state):
    """An absent authority state is never reported as a deliberate `full` setup."""
    mock_app_state.authority = None

    data = await _get_status(test_app)

    assert data["authority_level"] == "advisory", (
        "REGRESSION (threat T-02-09-07): reporting a missing authority state as "
        "`full` / `config` makes a crashed subsystem indistinguishable from an "
        "operator's own configuration, which is the exact ambiguity AUTH-08 exists "
        "to remove."
    )
    assert data["authority_reason"] == "degraded"
    assert data["authority"] == {}
    # Present, not omitted: a browser forced to tell "absent" from "advisory" has
    # the same ambiguity in a different costume.
    assert "authority_level" in data
    assert "authority_reason" in data


async def test_status_was_extended_not_replaced(test_app, mock_app_state):
    """Every pre-plan key survives alongside the four new ones."""
    data = await _get_status(test_app)

    missing = [key for key in _LEGACY_STATUS_KEYS if key not in data]
    assert not missing, f"/api/status dropped pre-existing keys: {missing}"
    assert {"authority_level", "authority_reason", "authority", "subsystems"} <= set(data)


async def test_status_exposes_the_whole_authority_summary(test_app, mock_app_state):
    """The `authority` block is AuthorityState.summary() verbatim, not a subset."""
    authority = AuthorityState(AuthorityLevel.ASSISTED)
    mock_app_state.authority = authority

    data = await _get_status(test_app)

    assert set(data["authority"]) == set(authority.summary())
    assert data["authority"]["configured_level"] == "assisted"


async def test_status_subsystems_carry_command_path_health(test_app, mock_app_state):
    """subsystems.command_path carries healthy / age_seconds / message (D-17)."""
    health = HealthMonitor()
    health.register("command_path")
    health.update("command_path", True, "ack round trip nominal")
    mock_app_state.health = health

    data = await _get_status(test_app)

    entry = data["subsystems"]["command_path"]
    assert set(entry) == {"healthy", "age_seconds", "message"}
    assert entry["healthy"] is True
    assert entry["message"] == "ack round trip nominal"
    assert isinstance(entry["age_seconds"], (int, float))


async def test_status_reports_a_latched_watchdog_as_advisory_with_a_cause(test_app, mock_app_state):
    """A latched watchdog renders as advisory *and* explains itself (D-17)."""
    authority = AuthorityState(AuthorityLevel.FULL, watchdog_max_timeouts=1)
    authority.record_command_timeout()
    health = HealthMonitor()
    health.register("command_path")
    health.update("command_path", False, "no ack from the adapter; 1 consecutive")
    mock_app_state.authority = authority
    mock_app_state.health = health

    data = await _get_status(test_app)

    assert data["authority_level"] == "advisory"
    assert data["authority_reason"] == "watchdog"
    assert data["authority"]["watchdog_latched"] is True
    assert data["subsystems"]["command_path"]["healthy"] is False
    assert "no ack" in data["subsystems"]["command_path"]["message"]


async def test_status_renders_an_unseen_subsystem_age_as_null(test_app, mock_app_state):
    """A registered-but-unseen subsystem has age inf; the wire value must be null."""
    health = HealthMonitor()
    health.register("command_path")
    mock_app_state.health = health

    data = await _get_status(test_app)

    assert data["subsystems"]["command_path"]["age_seconds"] is None, (
        "HealthMonitor.summary() reports inf for a subsystem that has never been "
        "seen, and Starlette renders JSON with allow_nan=False -- emitting it "
        "verbatim 500s the route, and Infinity is not parseable by the browser."
    )


async def test_status_subsystems_empty_without_a_health_monitor(test_app, mock_app_state):
    """No health monitor yields an empty block, not a missing key."""
    mock_app_state.health = None

    data = await _get_status(test_app)

    assert data["subsystems"] == {}


async def test_status_subsystems_agree_with_the_top_level_fields(test_app, mock_app_state):
    """One response must not say chromadb_available: true beside chromadb: unhealthy."""
    health = HealthMonitor()
    for name in ("simconnect_bridge", "chromadb", "whisper", "claude_api", "command_path"):
        health.register(name)
    mock_app_state.health = health

    data = await _get_status(test_app)

    subsystems = data["subsystems"]
    assert subsystems["chromadb"]["healthy"] == data["chromadb_available"]
    assert subsystems["whisper"]["healthy"] == data["whisper_available"]
    assert subsystems["simconnect_bridge"]["healthy"] == data["sim_connected"]


async def test_status_does_not_write_the_authority_state(test_app, mock_app_state):
    """The route is read-only where authority is concerned (T-02-09-03)."""
    authority = AuthorityState(AuthorityLevel.FULL)
    mock_app_state.authority = authority
    before = authority.summary()

    await _get_status(test_app)
    await _get_status(test_app)

    assert authority.summary() == before, (
        "No endpoint added by this phase may set the authority level. Level changes "
        "come only from configuration at startup, override detection and the "
        "command-path watchdog."
    )
