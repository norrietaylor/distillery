"""Tests for distillery.mcp.auth: GitHub OAuth authentication wiring."""

from __future__ import annotations

import logging

import pytest

from distillery.config import (
    DistilleryConfig,
    ServerAuthConfig,
    ServerConfig,
    StorageConfig,
)
from distillery.mcp.auth import build_github_auth
from distillery.mcp.server import create_server

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    provider: str = "github",
    client_id_env: str = "GITHUB_CLIENT_ID",
    client_secret_env: str = "GITHUB_CLIENT_SECRET",
) -> DistilleryConfig:
    """Return a DistilleryConfig with the given server auth settings."""
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        server=ServerConfig(
            auth=ServerAuthConfig(
                provider=provider,
                client_id_env=client_id_env,
                client_secret_env=client_secret_env,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Tests: build_github_auth
# ---------------------------------------------------------------------------


class TestBuildGithubAuthReadsEnv:
    def test_build_github_auth_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """build_github_auth() reads correct env vars from config."""
        monkeypatch.setenv("GITHUB_CLIENT_ID", "test-client-id")
        monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-client-secret")
        monkeypatch.setenv("DISTILLERY_BASE_URL", "https://distillery.example.com")

        config = _make_config()
        provider = build_github_auth(config)

        # GitHubProvider is constructed -- verify it's the right type.
        from fastmcp.server.auth.providers.github import GitHubProvider

        assert isinstance(provider, GitHubProvider)

    def test_build_github_auth_custom_env_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """build_github_auth() respects custom env var names from config."""
        monkeypatch.setenv("MY_CLIENT_ID", "custom-id")
        monkeypatch.setenv("MY_CLIENT_SECRET", "custom-secret")
        monkeypatch.setenv("DISTILLERY_BASE_URL", "https://example.com")

        config = _make_config(
            client_id_env="MY_CLIENT_ID",
            client_secret_env="MY_CLIENT_SECRET",
        )
        provider = build_github_auth(config)

        from fastmcp.server.auth.providers.github import GitHubProvider

        assert isinstance(provider, GitHubProvider)


class TestBuildGithubAuthMissingClientId:
    def test_build_github_auth_missing_client_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raises ValueError with clear message when client ID env is missing."""
        monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
        monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv("DISTILLERY_BASE_URL", "https://example.com")

        config = _make_config()
        with pytest.raises(ValueError, match="GITHUB_CLIENT_ID"):
            build_github_auth(config)


class TestBuildGithubAuthMissingClientSecret:
    def test_build_github_auth_missing_client_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raises ValueError with clear message when client secret env is missing."""
        monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
        monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)
        monkeypatch.setenv("DISTILLERY_BASE_URL", "https://example.com")

        config = _make_config()
        with pytest.raises(ValueError, match="GITHUB_CLIENT_SECRET"):
            build_github_auth(config)


class TestStdioModeNoAuthRequired:
    def test_stdio_mode_no_auth_required(self) -> None:
        """create_server() with auth=None starts cleanly (stdio mode)."""
        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
        )
        server = create_server(config=config, auth=None)
        # The server should be constructed successfully without auth.
        assert server is not None
        assert server.name == "distillery"


class TestNoSecretsInLogs:
    def test_no_secrets_in_logs(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """With debug logging enabled, no secret values appear in log output."""
        client_secret = "super-secret-value-12345"
        client_id = "test-client-id-67890"

        monkeypatch.setenv("GITHUB_CLIENT_ID", client_id)
        monkeypatch.setenv("GITHUB_CLIENT_SECRET", client_secret)
        monkeypatch.setenv("DISTILLERY_BASE_URL", "https://example.com")

        config = _make_config()

        with caplog.at_level(logging.DEBUG, logger="distillery.mcp.auth"):
            build_github_auth(config)

        log_output = caplog.text
        assert client_secret not in log_output, f"Client secret found in logs: {log_output}"
        # The client ID value itself should also not be logged (only the env var name).
        assert client_id not in log_output, f"Client ID value found in logs: {log_output}"
