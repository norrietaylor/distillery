"""Tests for distillery.mcp.auth: GitHub OAuth authentication wiring."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from distillery.config import (
    DistilleryConfig,
    ServerAuthConfig,
    ServerConfig,
    StorageConfig,
)
from distillery.mcp.auth import OrgRestrictedGitHubProvider, build_github_auth, build_org_checker
from distillery.mcp.server import create_server

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    provider: str = "github",
    client_id_env: str = "GITHUB_CLIENT_ID",
    client_secret_env: str = "GITHUB_CLIENT_SECRET",
    allowed_orgs: list[str] | None = None,
) -> DistilleryConfig:
    """Return a DistilleryConfig with the given server auth settings."""
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        server=ServerConfig(
            auth=ServerAuthConfig(
                provider=provider,
                client_id_env=client_id_env,
                client_secret_env=client_secret_env,
                allowed_orgs=allowed_orgs or [],
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


class TestBuildGithubAuthWithOrgChecker:
    def test_returns_org_restricted_provider_when_checker_provided(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """build_github_auth() returns OrgRestrictedGitHubProvider when org_checker is set."""
        monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
        monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv("DISTILLERY_BASE_URL", "https://example.com")

        from distillery.mcp.org_membership import OrgMembershipChecker

        checker = OrgMembershipChecker(allowed_orgs=["acme"])
        config = _make_config(allowed_orgs=["acme"])
        provider = build_github_auth(config, org_checker=checker)

        assert isinstance(provider, OrgRestrictedGitHubProvider)

    def test_returns_non_org_restricted_provider_when_no_checker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """build_github_auth() returns a non-org-restricted GitHubProvider when
        org_checker is None.

        The provider is a GitHubProvider (so OAuth works) but not an
        OrgRestrictedGitHubProvider. It is a _MachineTokenGitHubProvider so the
        pre-shared machine-token path is available even without org gating.
        """
        monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
        monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv("DISTILLERY_BASE_URL", "https://example.com")

        config = _make_config()
        provider = build_github_auth(config, org_checker=None)

        from fastmcp.server.auth.providers.github import GitHubProvider

        assert isinstance(provider, GitHubProvider)
        assert not isinstance(provider, OrgRestrictedGitHubProvider)


class TestBuildOrgCheckerIntegration:
    def test_returns_none_when_no_orgs_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """build_org_checker() returns None when allowed_orgs is empty."""
        monkeypatch.delenv("DISTILLERY_ALLOWED_ORGS", raising=False)
        config = _make_config()
        assert build_org_checker(config) is None

    def test_returns_checker_when_orgs_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """build_org_checker() returns OrgMembershipChecker when orgs are set."""
        monkeypatch.delenv("DISTILLERY_ALLOWED_ORGS", raising=False)
        from distillery.mcp.org_membership import OrgMembershipChecker

        config = _make_config(allowed_orgs=["my-company"])
        checker = build_org_checker(config)
        assert isinstance(checker, OrgMembershipChecker)
        assert checker.enabled

    def test_env_var_alone_produces_checker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DISTILLERY_ALLOWED_ORGS env var alone is sufficient to produce a checker."""
        monkeypatch.setenv("DISTILLERY_ALLOWED_ORGS", "env-company")
        from distillery.mcp.org_membership import OrgMembershipChecker

        config = _make_config()
        checker = build_org_checker(config)
        assert isinstance(checker, OrgMembershipChecker)
        assert "env-company" in checker._allowed_orgs


# ---------------------------------------------------------------------------
# Tests: Audit events on OrgRestrictedGitHubProvider
# ---------------------------------------------------------------------------


class TestAuthAuditEvents:
    """Verify audit callbacks are fired for login success/failure."""

    def _make_provider(self, audit_cb: AsyncMock | None = None) -> OrgRestrictedGitHubProvider:
        from distillery.mcp.org_membership import OrgMembershipChecker

        checker = OrgMembershipChecker(allowed_orgs=["acme"])
        return OrgRestrictedGitHubProvider(
            org_checker=checker,
            client_id="fake-id",
            client_secret="fake-secret",
            base_url="https://example.com",
            audit_callback=audit_cb,
        )

    async def test_audit_login_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Successful login fires audit callback with auth_login operation."""
        from unittest.mock import MagicMock

        cb = AsyncMock()
        provider = self._make_provider(audit_cb=cb)

        # Mock httpx to return a successful user response.
        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "login": "testuser",
            "name": "Test User",
            "email": "test@example.com",
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

        result = await provider._extract_upstream_claims({"access_token": "tok123"})
        assert result is not None
        assert result["login"] == "testuser"

        cb.assert_awaited_once_with("testuser", "auth_login", "", "auth_login", "success")

    async def test_audit_login_failed_bad_token(self) -> None:
        """Missing access token fires audit with auth_login_failed."""
        cb = AsyncMock()
        provider = self._make_provider(audit_cb=cb)

        result = await provider._extract_upstream_claims({})
        assert result is None

        cb.assert_awaited_once()
        args = cb.call_args[0]
        assert args[0] == "unknown"
        assert args[1] == "auth_login_failed"

    async def test_audit_login_failed_github_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-200 GitHub API response fires audit with auth_login_failed."""
        from unittest.mock import MagicMock

        cb = AsyncMock()
        provider = self._make_provider(audit_cb=cb)

        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

        result = await provider._extract_upstream_claims({"access_token": "bad"})
        assert result is None

        cb.assert_awaited_once()
        args = cb.call_args[0]
        assert args[0] == "unknown"
        assert args[1] == "auth_login_failed"
        assert "401" in args[4]

    async def test_audit_login_failed_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exception during claims extraction fires audit with auth_login_failed."""
        cb = AsyncMock()
        provider = self._make_provider(audit_cb=cb)

        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("network down"))

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

        result = await provider._extract_upstream_claims({"access_token": "tok"})
        assert result is None

        cb.assert_awaited_once()
        args = cb.call_args[0]
        assert args[1] == "auth_login_failed"
        assert "exception" in args[4]

    async def test_audit_callback_failure_does_not_break_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failing audit callback must not prevent a successful login."""
        from unittest.mock import MagicMock

        cb = AsyncMock(side_effect=RuntimeError("audit db down"))
        provider = self._make_provider(audit_cb=cb)

        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"login": "user1", "name": "U", "email": "u@e.com"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

        result = await provider._extract_upstream_claims({"access_token": "tok"})
        # Auth succeeds despite audit failure.
        assert result is not None
        assert result["login"] == "user1"

    async def test_no_audit_callback_is_safe(self) -> None:
        """Provider with no audit callback does not error."""
        provider = self._make_provider(audit_cb=None)
        result = await provider._extract_upstream_claims({})
        assert result is None  # no crash


# ---------------------------------------------------------------------------
# Tests: pre-shared machine-token auth
# ---------------------------------------------------------------------------


class TestMachineTokenAuth:
    """The opt-in pre-shared machine-token MCP auth path."""

    def test_load_machine_tokens_unset_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No DISTILLERY_MCP_MACHINE_TOKEN -> feature off, empty list."""
        from distillery.mcp.auth import _load_machine_tokens

        monkeypatch.delenv("DISTILLERY_MCP_MACHINE_TOKEN", raising=False)
        assert _load_machine_tokens() == []

    def test_load_machine_tokens_builds_access_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A configured token yields an AccessToken with the login claim."""
        from distillery.mcp.auth import _load_machine_tokens

        monkeypatch.setenv("DISTILLERY_MCP_MACHINE_TOKEN", "tok-secret-123")
        monkeypatch.setenv("DISTILLERY_MCP_MACHINE_IDENTITY", "spectacles-bot")

        loaded = _load_machine_tokens()
        assert len(loaded) == 1
        raw, access = loaded[0]
        assert raw == "tok-secret-123"
        assert access.client_id == "spectacles-bot"
        assert access.claims["login"] == "spectacles-bot"

    def test_load_machine_tokens_default_identity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Identity defaults when DISTILLERY_MCP_MACHINE_IDENTITY is unset."""
        from distillery.mcp.auth import _load_machine_tokens

        monkeypatch.setenv("DISTILLERY_MCP_MACHINE_TOKEN", "tok-x")
        monkeypatch.delenv("DISTILLERY_MCP_MACHINE_IDENTITY", raising=False)

        _, access = _load_machine_tokens()[0]
        assert access.client_id == "distillery-machine"

    async def test_verify_token_accepts_configured_machine_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A request bearing the machine token resolves to its identity."""
        monkeypatch.setenv("GITHUB_CLIENT_ID", "id")
        monkeypatch.setenv("GITHUB_CLIENT_SECRET", "secret")
        monkeypatch.setenv("DISTILLERY_BASE_URL", "https://distillery.example.com")
        monkeypatch.setenv("DISTILLERY_MCP_MACHINE_TOKEN", "machine-tok-abc")
        monkeypatch.setenv("DISTILLERY_MCP_MACHINE_IDENTITY", "ci-bot")

        provider = build_github_auth(_make_config())
        access = await provider.verify_token("machine-tok-abc")

        assert access is not None
        assert access.claims["login"] == "ci-bot"

    async def test_verify_token_unknown_falls_through_to_oauth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-machine token is delegated to the OAuth-proxy verifier."""
        monkeypatch.setenv("GITHUB_CLIENT_ID", "id")
        monkeypatch.setenv("GITHUB_CLIENT_SECRET", "secret")
        monkeypatch.setenv("DISTILLERY_BASE_URL", "https://distillery.example.com")
        monkeypatch.setenv("DISTILLERY_MCP_MACHINE_TOKEN", "machine-tok-abc")

        from fastmcp.server.auth.providers.github import GitHubProvider

        oauth_verify = AsyncMock(return_value=None)
        monkeypatch.setattr(GitHubProvider, "verify_token", oauth_verify)

        provider = build_github_auth(_make_config())
        result = await provider.verify_token("not-a-machine-token")

        assert result is None
        oauth_verify.assert_awaited_once_with("not-a-machine-token")

    async def test_verify_token_off_by_default_delegates_to_oauth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With the feature off, every token goes to the OAuth proxy."""
        monkeypatch.setenv("GITHUB_CLIENT_ID", "id")
        monkeypatch.setenv("GITHUB_CLIENT_SECRET", "secret")
        monkeypatch.setenv("DISTILLERY_BASE_URL", "https://distillery.example.com")
        monkeypatch.delenv("DISTILLERY_MCP_MACHINE_TOKEN", raising=False)

        from fastmcp.server.auth.providers.github import GitHubProvider

        oauth_verify = AsyncMock(return_value=None)
        monkeypatch.setattr(GitHubProvider, "verify_token", oauth_verify)

        provider = build_github_auth(_make_config())
        await provider.verify_token("anything")
        oauth_verify.assert_awaited_once_with("anything")
