"""Tests for POST /api/turn-probe and the endpointing fields on /api/status.

Covers VARC-06: the browser asks, the server decides.

The ONNX session is faked (the same ``_FakeSession`` shape used in
``orchestrator/tests/test_turn_detection.py``) so nothing here needs the 8 MB
model file or a network call -- which is also the state CI runs in.

Two properties matter more than the happy path and are pinned hardest:

* the endpoint never raises, because the browser's fallback is what keeps voice
  input working and a 5xx would only add latency to reaching it;
* the endpoint is throttled and size-bounded, because ``pollVAD`` calls it from
  a ~60 Hz ``requestAnimationFrame`` loop and each accepted probe spawns ffmpeg.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import numpy as np
import pytest
from httpx import ASGITransport
from orchestrator.turn.silence import SilenceTurnDetector
from orchestrator.turn.smart_turn import SmartTurnDetector

# ---------------------------------------------------------------------------
# ONNX-free detector scaffolding
# ---------------------------------------------------------------------------


class _FakeSession:
    """Stand-in for an onnxruntime InferenceSession returning a fixed probability."""

    def __init__(self, probability: float = 0.9, raises: Exception | None = None) -> None:
        self.probability = probability
        self.raises = raises
        self.calls: list[np.ndarray] = []

    def run(self, _outputs: object, feeds: dict[str, np.ndarray]) -> list[np.ndarray]:
        if self.raises is not None:
            raise self.raises
        self.calls.append(feeds["input_features"])
        return [np.array([[self.probability]], dtype=np.float32)]


def _detector_with(session: _FakeSession, **kwargs: Any) -> SmartTurnDetector:
    detector = SmartTurnDetector(**kwargs)
    detector._session = session
    detector._load_attempted = True
    return detector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Small but valid webm-ish payload. ffmpeg never sees it -- the decode helper is
# patched in every test that gets far enough to call it.
_FAKE_WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 512


@pytest.fixture
def probe_state(mock_app_state):
    """mock_app_state with a working semantic detector and explicit thresholds.

    The thresholds must be set explicitly: ``settings`` is a ``MagicMock``, so
    ``int(settings.turn_probe_silence_ms)`` silently yields 1 rather than raising.
    """
    mock_app_state.settings.turn_probe_silence_ms = 150
    mock_app_state.settings.vad_silence_ms = 400
    mock_app_state.turn_detector = _detector_with(_FakeSession(probability=0.9))
    return mock_app_state


@pytest.fixture
def patched_decode(monkeypatch):
    """Replace the ffmpeg decode with a recorder returning fixed samples."""
    import web.server as srv

    calls: list[bytes] = []
    result: dict[str, Any] = {"samples": np.zeros(16000, dtype=np.float32) + 0.1}

    async def _fake_decode(webm_bytes: bytes) -> np.ndarray | None:
        calls.append(webm_bytes)
        return result["samples"]

    monkeypatch.setattr(srv, "decode_webm_to_samples", _fake_decode)
    return {"calls": calls, "result": result}


async def _probe(app, silence_ms: int = 160, payload: bytes = _FAKE_WEBM) -> httpx.Response:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/api/turn-probe",
            files={"file": ("turn.webm", payload, "audio/webm")},
            data={"silence_ms": str(silence_ms)},
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_high_probability_ends_the_turn(test_app, probe_state, patched_decode):
    """A confident model verdict comes back as ended=True, available=True."""
    resp = await _probe(test_app)

    assert resp.status_code == 200
    data = resp.json()
    assert data["ended"] is True
    assert data["available"] is True
    assert data["detector"] == "smart_turn"
    assert data["probability"] == pytest.approx(0.9, abs=1e-5)
    assert len(patched_decode["calls"]) == 1


async def test_low_probability_keeps_the_turn_open(test_app, probe_state, patched_decode):
    """Mid-sentence pauses are the case this exists for -- do not end the turn."""
    probe_state.turn_detector = _detector_with(_FakeSession(probability=0.05))

    resp = await _probe(test_app)

    assert resp.status_code == 200
    data = resp.json()
    assert data["ended"] is False
    assert data["available"] is True
    assert data["probability"] == pytest.approx(0.05, abs=1e-5)


async def test_the_whole_uploaded_blob_reaches_the_decoder(test_app, probe_state, patched_decode):
    """The browser sends the whole accumulated blob; the server must not slice it."""
    payload = b"\x1a\x45\xdf\xa3" + bytes(range(256)) * 8

    await _probe(test_app, payload=payload)

    assert patched_decode["calls"] == [payload]


# ---------------------------------------------------------------------------
# Degradation -- the endpoint never raises
# ---------------------------------------------------------------------------


async def test_no_detector_reports_unavailable(test_app, probe_state, patched_decode):
    """available=False tells the browser to stop probing for the session."""
    probe_state.turn_detector = None

    resp = await _probe(test_app)

    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert data["ended"] is False
    assert data["detector"] == "unavailable"
    # The body was never decoded: no ffmpeg spawn for a detector we do not have.
    assert patched_decode["calls"] == []


async def test_unavailable_detector_reports_unavailable(test_app, probe_state, patched_decode):
    """A detector whose model failed to load is the same case as having none."""
    probe_state.turn_detector = _detector_with(_FakeSession())
    probe_state.turn_detector._session = None

    resp = await _probe(test_app)

    assert resp.status_code == 200
    assert resp.json()["available"] is False
    assert patched_decode["calls"] == []


async def test_decode_failure_is_transient_not_permanent(test_app, probe_state, patched_decode):
    """One bad blob must not disable probing for the rest of the session."""
    patched_decode["result"]["samples"] = None

    resp = await _probe(test_app)

    assert resp.status_code == 200
    data = resp.json()
    assert data["detector"] == "decode_failed"
    assert data["available"] is True
    assert data["ended"] is False


_WR01_REGRESSION = (
    "REGRESSION (VERIFICATION WR-01): the handler documents 'Never raises. Every "
    "failure path returns a not-ended answer', then called decode_webm_to_samples "
    "outside any try. With no ffmpeg on PATH that raises FileNotFoundError, so a "
    "browser probing at roughly 7 Hz during speech collected a 500 and a traceback "
    "per probe instead of degrading to its fixed-silence fallback."
)


def _raising_decode(exc: Exception):
    """A decode stand-in that raises rather than returning None."""

    async def _decode(webm_bytes: bytes):
        raise exc

    return _decode


async def test_missing_ffmpeg_returns_200_not_a_traceback(test_app, probe_state, monkeypatch):
    """WR-01: FileNotFoundError from create_subprocess_exec must not reach the browser."""
    import web.server as srv

    monkeypatch.setattr(
        srv,
        "decode_webm_to_samples",
        _raising_decode(FileNotFoundError("[Errno 2] No such file or directory: 'ffmpeg'")),
    )

    resp = await _probe(test_app)

    assert resp.status_code == 200, _WR01_REGRESSION
    data = resp.json()
    assert data["ended"] is False, _WR01_REGRESSION
    assert data["detector"] == "decode_failed"
    assert data["available"] is True, (
        "A decode failure is transient from the endpoint's point of view. "
        "available=False would stop the browser probing for the whole session "
        "over what may be one bad blob (WR-01)."
    )


async def test_truncated_ffmpeg_buffer_returns_200(test_app, probe_state, monkeypatch):
    """np.frombuffer raises ValueError on an odd-length buffer; same contract applies."""
    import web.server as srv

    monkeypatch.setattr(
        srv,
        "decode_webm_to_samples",
        _raising_decode(ValueError("buffer size must be a multiple of element size")),
    )

    resp = await _probe(test_app)

    assert resp.status_code == 200, _WR01_REGRESSION
    data = resp.json()
    assert data["ended"] is False
    assert data["detector"] == "decode_failed", (
        "A raise and a None return are the same event to the browser; one tag for "
        "both, because a second tag would only fragment the signal (WR-01)."
    )
    assert data["available"] is True


async def test_inference_failure_returns_error_shape(test_app, probe_state, patched_decode):
    """An exploding model yields a not-ended answer, never a 500."""
    probe_state.turn_detector = _detector_with(_FakeSession(raises=RuntimeError("onnx exploded")))

    resp = await _probe(test_app)

    assert resp.status_code == 200
    data = resp.json()
    assert data["ended"] is False
    assert data["available"] is True
    # SmartTurnDetector swallows inference errors itself and reports not-ended;
    # either its name or the server's "error" tag is an acceptable answer, but a
    # raised exception is not.
    assert data["detector"] in {"smart_turn", "error"}


class _ExplodingDetector:
    """A detector that violates the never-raise contract, to prove we hold it anyway."""

    name = "exploding"
    available = True
    probe_silence_ms = 150

    def evaluate(self, audio: np.ndarray, sample_rate: int, silence_ms: int) -> None:
        raise RuntimeError("detector contract violated")

    def reset(self) -> None:
        pass


async def test_a_raising_detector_still_returns_200(test_app, probe_state, patched_decode):
    """The endpoint owns the never-raise guarantee; it does not delegate it."""
    probe_state.turn_detector = _ExplodingDetector()

    resp = await _probe(test_app)

    assert resp.status_code == 200
    data = resp.json()
    assert data["detector"] == "error"
    assert data["ended"] is False
    assert data["available"] is True


# ---------------------------------------------------------------------------
# Abuse bounds
# ---------------------------------------------------------------------------


async def test_oversized_body_is_rejected_without_invoking_ffmpeg(
    test_app, probe_state, patched_decode
):
    """2 MiB is minutes of Opus; anything larger is a bug or abuse."""
    oversized = b"\x00" * (2 * 1024 * 1024 + 1)

    resp = await _probe(test_app, payload=oversized)

    assert resp.status_code == 200
    data = resp.json()
    assert data["detector"] == "too_large"
    assert data["ended"] is False
    assert patched_decode["calls"] == []


async def test_second_immediate_probe_is_throttled(test_app, probe_state, patched_decode):
    """pollVAD runs at ~60 Hz; the server does not take the browser's word for spacing."""
    probe_state.settings.turn_probe_silence_ms = 100_000  # 50 s minimum interval

    first = await _probe(test_app)
    second = await _probe(test_app)

    assert first.json()["detector"] == "smart_turn"
    assert second.json()["detector"] == "throttled"
    assert second.json()["available"] is True
    assert second.json()["ended"] is False
    # Throttling happens before the decode, so it costs no subprocess.
    assert len(patched_decode["calls"]) == 1


async def test_probes_spaced_beyond_the_interval_are_accepted(
    test_app, probe_state, patched_decode
):
    probe_state.settings.turn_probe_silence_ms = 2  # 1 ms minimum interval

    first = await _probe(test_app)
    await asyncio.sleep(0.02)
    second = await _probe(test_app)

    assert first.json()["detector"] == "smart_turn"
    assert second.json()["detector"] == "smart_turn"
    assert len(patched_decode["calls"]) == 2


async def test_throttle_table_is_bounded(test_app, probe_state, patched_decode):
    """The table is keyed by client host on an unauthenticated endpoint."""
    import web.server as srv

    probe_state.turn_probe_seen = {f"10.0.0.{i}": 0.0 for i in range(srv._MAX_TURN_PROBE_CLIENTS)}

    await _probe(test_app)

    assert len(probe_state.turn_probe_seen) <= srv._MAX_TURN_PROBE_CLIENTS


# ---------------------------------------------------------------------------
# /api/status -- extended, not replaced
# ---------------------------------------------------------------------------


async def test_status_advertises_probe_availability_and_thresholds(test_app, probe_state):
    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["turn_probe_available"] is True
    assert data["turn_probe_silence_ms"] == 150
    assert data["vad_silence_ms"] == 400


async def test_status_keeps_every_pre_existing_key(test_app, probe_state):
    """This plan extends the status shape; nothing may be removed or renamed."""
    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")

    data = resp.json()
    for key in (
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
    ):
        assert key in data, f"/api/status lost pre-existing key {key!r}"


async def test_status_reports_silence_fallback_as_unavailable(test_app, probe_state):
    """The fixed-silence detector re-derives what the browser already times."""
    probe_state.turn_detector = SilenceTurnDetector(silence_ms=400)

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")

    assert resp.json()["turn_probe_available"] is False


async def test_status_reports_no_detector_as_unavailable(test_app, probe_state):
    probe_state.turn_detector = None

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")

    assert resp.json()["turn_probe_available"] is False


async def test_status_thresholds_are_integers_even_with_odd_settings(test_app, probe_state):
    """The browser does arithmetic with these; they must never arrive as objects."""
    del probe_state.settings.turn_probe_silence_ms
    probe_state.settings.vad_silence_ms = "not-a-number"

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/status")

    data = resp.json()
    assert isinstance(data["turn_probe_silence_ms"], int)
    assert data["vad_silence_ms"] == 400
