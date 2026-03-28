"""Shared fixtures for MERLIN web server test suite.

Sets ANTHROPIC_API_KEY before web.server is imported (module-level
``load_settings()`` runs at import time and requires this env var).
Provides a mock AppState via FastAPI dependency_overrides and a
``test_app`` fixture that yields the FastAPI app ready for
httpx.AsyncClient testing.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Environment setup -- must happen before web.server import
# ---------------------------------------------------------------------------

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-for-web-tests")


@pytest.fixture
def mock_app_state():
    """Create a fully mocked AppState with sensible test defaults."""
    import web.server as srv

    state = srv.AppState(settings=MagicMock())

    # Settings with explicit attributes matching web.server usage
    state.settings.elevenlabs_api_key = "test-key"
    state.settings.voice_id = "test-voice"
    state.settings.elevenlabs_model_id = "eleven_multilingual_v2"
    state.settings.claude_model = "claude-sonnet-4-20250514"
    state.settings.telemetry_service_url = "ws://localhost:8080/ws/telemetry"
    state.settings.whisper_url = "http://localhost:9090"
    state.settings.whisper_model = "large-v3-turbo"
    state.settings.chromadb_url = "http://localhost:8000"
    state.settings.log_level = "DEBUG"
    state.settings.tts_configured = True

    # Whisper client mocks
    state.whisper_client = AsyncMock()
    state.whisper_client.transcribe_with_confidence = AsyncMock()
    state.whisper_client.is_available = AsyncMock(return_value=True)

    # Claude client mocks
    state.claude_client = AsyncMock()

    # TTS client mocks
    state.tts_client = AsyncMock()

    # Context store
    state.context_store = MagicMock()
    state.context_store.available = True
    state.context_store.document_count = 42

    # Sim client
    state.sim_client = MagicMock()
    state.sim_client.state = MagicMock()

    return state


@pytest.fixture
def test_app(mock_app_state):
    """Yield the FastAPI app with AppState overridden via dependency_overrides.

    Uses FastAPI's dependency_overrides to inject mock AppState into all
    route handlers that use Depends(get_app_state) or Depends(get_ws_app_state).
    """
    import web.server as srv

    srv.app.dependency_overrides[srv.get_app_state] = lambda: mock_app_state
    srv.app.dependency_overrides[srv.get_ws_app_state] = lambda: mock_app_state

    yield srv.app

    srv.app.dependency_overrides.clear()
