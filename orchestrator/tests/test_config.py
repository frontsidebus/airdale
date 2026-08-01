"""Tests for orchestrator.config — Settings loading and validation."""

from __future__ import annotations

import pytest
from orchestrator.config import Settings, load_settings
from pydantic import ValidationError


def _settings(**overrides: object) -> Settings:
    """Build Settings without reading a real .env file."""
    base: dict[str, object] = {"anthropic_api_key": "sk-test", "_env_file": None}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestSettingsDefaults:
    """Verify default values when only required fields are provided."""

    def test_default_whisper_model(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("WHISPER_MODEL", raising=False)
        s = Settings(anthropic_api_key="sk-test")
        assert s.whisper_model == "large-v3-turbo"

    def test_default_whisper_url(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("WHISPER_URL", raising=False)
        s = Settings(anthropic_api_key="sk-test")
        assert s.whisper_url == "http://localhost:9090"

    def test_default_screen_capture_disabled(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SCREEN_CAPTURE_ENABLED", raising=False)
        s = Settings(anthropic_api_key="sk-test")
        assert s.screen_capture_enabled is False

    def test_default_screen_capture_fps(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SCREEN_CAPTURE_FPS", raising=False)
        s = Settings(anthropic_api_key="sk-test")
        assert s.screen_capture_fps == 1

    def test_default_claude_model(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CLAUDE_MODEL", raising=False)
        s = Settings(anthropic_api_key="sk-test")
        assert s.claude_model == "claude-sonnet-4-20250514"

    def test_default_chromadb_url(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CHROMADB_URL", raising=False)
        s = Settings(anthropic_api_key="sk-test")
        assert s.chromadb_url == "http://localhost:8000"

    def test_default_elevenlabs_key_empty(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        s = Settings(anthropic_api_key="sk-test")
        assert s.elevenlabs_api_key == ""

    def test_default_voice_id_empty(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
        s = Settings(anthropic_api_key="sk-test")
        assert s.voice_id == ""

    def test_default_claude_temperature(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CLAUDE_TEMPERATURE", raising=False)
        s = Settings(anthropic_api_key="sk-test")
        assert s.claude_temperature == 0.3  # v2 default (was 0.7)


class TestSettingsEnvOverrides:
    """Verify that environment variables override defaults."""

    def test_env_overrides_whisper_model(self, mock_env_vars: dict[str, str]) -> None:
        s = Settings()
        assert s.whisper_model == "tiny"

    def test_env_overrides_screen_capture_fps(self, mock_env_vars: dict[str, str]) -> None:
        s = Settings()
        assert s.screen_capture_fps == 2

    def test_env_overrides_claude_model(self, mock_env_vars: dict[str, str]) -> None:
        s = Settings()
        assert s.claude_model == "claude-sonnet-4-20250514"

    def test_env_overrides_chromadb_url(self, mock_env_vars: dict[str, str]) -> None:
        s = Settings()
        assert s.chromadb_url == "http://chromadb-test:9999"

    def test_env_overrides_api_key(self, mock_env_vars: dict[str, str]) -> None:
        s = Settings()
        assert s.anthropic_api_key == "sk-ant-test-key-000"

    def test_env_overrides_claude_temperature(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_TEMPERATURE", "0.3")
        s = Settings()
        assert s.claude_temperature == 0.3


class TestSettingsValidation:
    """Test that validation catches problems with required fields."""

    def test_missing_anthropic_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Prevent loading real .env file
        monkeypatch.setattr(
            "orchestrator.config.Settings.model_config",
            {
                "env_file": "",
                "env_file_encoding": "utf-8",
                "extra": "ignore",
            },
        )
        # Clear all potentially set env vars
        for key in ("ANTHROPIC_API_KEY",):
            monkeypatch.delenv(key, raising=False)
        with pytest.raises(Exception):  # noqa: B017 - any pydantic validation error is acceptable
            Settings()

    def test_screen_capture_enabled_parses_true(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SCREEN_CAPTURE_ENABLED", "true")
        s = Settings()
        assert s.screen_capture_enabled is True

    def test_screen_capture_enabled_parses_one(
        self, mock_env_vars: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SCREEN_CAPTURE_ENABLED", "1")
        s = Settings()
        assert s.screen_capture_enabled is True


class TestAuthoritySettings:
    """The eight authority fields and the invariants that keep them honest."""

    def test_defaults(self) -> None:
        s = _settings()
        # 'full' is today's behaviour: restriction is opt-in, so upgrading changes nothing.
        assert s.authority_level == "full"
        assert s.authority_override_grace_s == 30.0
        assert s.authority_override_settle_s == 2.0
        assert s.authority_override_cooldown_s == 120.0
        assert s.authority_watchdog_max_timeouts == 3
        assert s.authority_command_timeout_s == 5.0
        assert s.authority_verify_timeout_s == 3.0
        assert s.authority_tool_timeout_s == 12.0

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("ASSISTED", "assisted"), ("Advisory", "advisory"), ("  full  ", "full")],
    )
    def test_level_is_normalised_case_insensitively(self, raw: str, expected: str) -> None:
        assert _settings(authority_level=raw).authority_level == expected

    def test_unknown_level_fails_at_startup_listing_the_supported_values(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _settings(authority_level="banana")

        message = str(excinfo.value)
        for level in ("advisory", "assisted", "full"):
            assert level in message

    @pytest.mark.parametrize(
        "override",
        [
            {"authority_watchdog_max_timeouts": 0},
            {"authority_override_cooldown_s": 0},
            {"authority_override_grace_s": 0},
            {"authority_override_settle_s": -1.0},
            {"authority_command_timeout_s": 0},
            {"authority_verify_timeout_s": 0},
        ],
    )
    def test_bounds_are_enforced(self, override: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            _settings(**override)

    def test_tool_timeout_must_outlast_command_plus_verify(self) -> None:
        # B3: the outer tool deadline starts first, so an equal budget pre-empts the
        # real ack timeout and the command-path watchdog never observes it.
        with pytest.raises(ValidationError) as excinfo:
            _settings(
                authority_tool_timeout_s=5.0,
                authority_command_timeout_s=5.0,
                authority_verify_timeout_s=3.0,
            )

        message = str(excinfo.value)
        assert "authority_tool_timeout_s" in message
        assert "authority_command_timeout_s" in message
        assert "authority_verify_timeout_s" in message

    def test_tool_timeout_equal_to_the_sum_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _settings(
                authority_tool_timeout_s=8.0,
                authority_command_timeout_s=5.0,
                authority_verify_timeout_s=3.0,
            )

    def test_a_larger_tool_timeout_is_accepted(self) -> None:
        s = _settings(
            authority_tool_timeout_s=8.1,
            authority_command_timeout_s=5.0,
            authority_verify_timeout_s=3.0,
        )
        assert s.authority_tool_timeout_s == 8.1

    def test_env_var_overrides_the_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTHORITY_LEVEL", "advisory")
        assert _settings().authority_level == "advisory"

    def test_level_seeds_the_authority_state_machine(self) -> None:
        from orchestrator.authority import AuthorityLevel, parse_authority_level

        assert parse_authority_level(_settings().authority_level) is AuthorityLevel.FULL


class TestLoadSettings:
    """Test the load_settings() convenience function."""

    def test_load_settings_returns_settings_instance(self, mock_env_vars: dict[str, str]) -> None:
        s = load_settings()
        assert isinstance(s, Settings)
        assert s.anthropic_api_key == "sk-ant-test-key-000"
