"""Tests for distillery.mcp.gitlab_auth: GitLab OIDC authentication wiring."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from distillery.config import (
    DistilleryConfig,
    ServerAuthConfig,
    ServerConfig,
    StorageConfig,
    _validate,
)
from distillery.mcp.gitlab_auth import (
    GitLabProvider,
    build_gitlab_auth,
    matches_allowed_groups,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    provider: str = "gitlab",
    instance_url: str = "https://gitlab.example.com",
    allowed_groups: list[str] | None = None,
) -> DistilleryConfig:
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        server=ServerConfig(
            auth=ServerAuthConfig(
                provider=provider,
                client_id_env="GITLAB_CLIENT_ID",
                client_secret_env="GITLAB_CLIENT_SECRET",
                instance_url=instance_url,
                allowed_groups=allowed_groups or [],
            )
        ),
    )


_FAKE_OIDC_CONFIG = MagicMock(
    authorization_endpoint="https://gitlab.example.com/oauth/authorize",
    token_endpoint="https://gitlab.example.com/oauth/token",
    userinfo_endpoint="https://gitlab.example.com/oauth/userinfo",
    revocation_endpoint=None,
    service_documentation=None,
    jwks_uri="https://gitlab.example.com/oauth/discovery/keys",
    issuer="https://gitlab.example.com",
    scopes_supported=["openid", "profile", "email"],
    id_token_signing_alg_values_supported=["RS256"],
)


@pytest.fixture(autouse=True)
def _stub_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent OIDCProxy.__init__ from fetching the discovery document."""
    monkeypatch.setattr(
        GitLabProvider,
        "get_oidc_configuration",
        classmethod(lambda cls, *a, **kw: _FAKE_OIDC_CONFIG),
    )


def _make_provider(
    allowed_groups: list[str] | None = None,
    audit_cb: AsyncMock | None = None,
    machine_tokens: list[Any] | None = None,
) -> GitLabProvider:
    return GitLabProvider(
        instance_url="https://gitlab.example.com",
        client_id="app-id",
        client_secret="app-secret",
        base_url="https://distillery.example.com",
        allowed_groups=allowed_groups,
        audit_callback=audit_cb,
        machine_tokens=machine_tokens,
    )


def _mock_userinfo(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], status: int = 200):
    resp = MagicMock(status_code=status)
    resp.json.return_value = payload
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(httpx, "AsyncClient", MagicMock(return_value=client))
    return client


# ---------------------------------------------------------------------------
# Subtree matching
# ---------------------------------------------------------------------------


class TestMatchesAllowedGroups:
    def test_exact_match(self) -> None:
        assert matches_allowed_groups(["acme"], ["acme"])

    def test_subgroup_matches_parent(self) -> None:
        assert matches_allowed_groups(["acme/dev"], ["acme"])
        assert matches_allowed_groups(["acme/dev/platform"], ["acme"])

    def test_sibling_prefix_does_not_match(self) -> None:
        assert not matches_allowed_groups(["acme-corp"], ["acme"])

    def test_parent_membership_does_not_match_allowed_subgroup(self) -> None:
        assert not matches_allowed_groups(["acme"], ["acme/dev"])

    def test_no_groups_denied(self) -> None:
        assert not matches_allowed_groups([], ["acme"])

    def test_empty_allowed_is_open_access(self) -> None:
        assert matches_allowed_groups([], [])
        assert matches_allowed_groups(["anything"], [])

    def test_trailing_slashes_normalized(self) -> None:
        assert matches_allowed_groups(["acme/dev/"], ["acme"])


# ---------------------------------------------------------------------------
# Claims extraction and login-time gating
# ---------------------------------------------------------------------------


class TestExtractUpstreamClaims:
    async def test_maps_nickname_to_login(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = _make_provider()
        _mock_userinfo(
            monkeypatch,
            {
                "nickname": "mark",
                "name": "Mark L",
                "email": "mark@example.com",
                "groups": ["acme/dev"],
            },
        )
        claims = await provider._extract_upstream_claims({"access_token": "tok"})
        assert claims is not None
        assert claims["login"] == "mark"
        assert claims["groups"] == ["acme/dev"]

    async def test_group_member_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        audit = AsyncMock()
        provider = _make_provider(allowed_groups=["acme"], audit_cb=audit)
        _mock_userinfo(monkeypatch, {"nickname": "mark", "groups": ["acme/dev"]})
        claims = await provider._extract_upstream_claims({"access_token": "tok"})
        assert claims is not None and claims["login"] == "mark"
        audit.assert_awaited_once_with("mark", "auth_login", "", "auth_login", "success")

    async def test_group_mismatch_denied_and_audited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        audit = AsyncMock()
        provider = _make_provider(allowed_groups=["acme"], audit_cb=audit)
        _mock_userinfo(monkeypatch, {"nickname": "eve", "groups": ["other"]})
        claims = await provider._extract_upstream_claims({"access_token": "tok"})
        assert claims is None
        audit.assert_awaited_once_with(
            "eve", "auth_group_denied", "", "auth_group_denied", "denied"
        )

    async def test_missing_access_token_fails(self) -> None:
        provider = _make_provider()
        assert await provider._extract_upstream_claims({}) is None

    async def test_userinfo_error_status_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = _make_provider()
        _mock_userinfo(monkeypatch, {}, status=401)
        assert await provider._extract_upstream_claims({"access_token": "tok"}) is None

    async def test_missing_nickname_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = _make_provider()
        _mock_userinfo(monkeypatch, {"groups": ["acme"]})
        assert await provider._extract_upstream_claims({"access_token": "tok"}) is None


# ---------------------------------------------------------------------------
# verify_token: flattening, fail-closed, machine tokens
# ---------------------------------------------------------------------------


def _access_token(claims: dict[str, Any] | None) -> Any:
    token = MagicMock()
    token.claims = claims
    return token


class TestVerifyToken:
    async def test_flattens_upstream_claims(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = _make_provider()
        inner = _access_token({"upstream_claims": {"login": "mark", "groups": ["acme"]}})
        monkeypatch.setattr(
            "fastmcp.server.auth.oidc_proxy.OIDCProxy.verify_token",
            AsyncMock(return_value=inner),
        )
        result = await provider.verify_token("bearer-token")
        assert result is not None
        assert result.claims["login"] == "mark"
        assert "upstream_claims" not in result.claims

    async def test_no_login_claim_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = _make_provider()
        # A group-denied login gets a token with no upstream claims embedded.
        inner = _access_token({})
        monkeypatch.setattr(
            "fastmcp.server.auth.oidc_proxy.OIDCProxy.verify_token",
            AsyncMock(return_value=inner),
        )
        assert await provider.verify_token("bearer-token") is None

    async def test_invalid_token_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = _make_provider()
        monkeypatch.setattr(
            "fastmcp.server.auth.oidc_proxy.OIDCProxy.verify_token",
            AsyncMock(return_value=None),
        )
        assert await provider.verify_token("bad") is None

    async def test_machine_token_bypasses_oidc_and_gate(self) -> None:
        from fastmcp.server.auth import AccessToken

        machine = AccessToken(
            token="pre-shared",
            client_id="ci-bot",
            scopes=["user"],
            expires_at=None,
            claims={"login": "ci-bot", "machine": True},
        )
        provider = _make_provider(allowed_groups=["acme"], machine_tokens=[("pre-shared", machine)])
        result = await provider.verify_token("pre-shared")
        assert result is machine


# ---------------------------------------------------------------------------
# build_gitlab_auth
# ---------------------------------------------------------------------------


class TestBuildGitlabAuth:
    def test_builds_provider_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITLAB_CLIENT_ID", "app-id")
        monkeypatch.setenv("GITLAB_CLIENT_SECRET", "app-secret")
        monkeypatch.setenv("DISTILLERY_BASE_URL", "https://distillery.example.com")
        provider = build_gitlab_auth(_make_config(allowed_groups=["acme"]))
        assert isinstance(provider, GitLabProvider)
        assert provider._allowed_groups == ["acme"]

    def test_missing_client_id_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITLAB_CLIENT_ID", raising=False)
        monkeypatch.setenv("GITLAB_CLIENT_SECRET", "s")
        monkeypatch.setenv("DISTILLERY_BASE_URL", "https://d.example.com")
        with pytest.raises(ValueError, match="GITLAB_CLIENT_ID"):
            build_gitlab_auth(_make_config())

    def test_missing_base_url_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITLAB_CLIENT_ID", "i")
        monkeypatch.setenv("GITLAB_CLIENT_SECRET", "s")
        monkeypatch.delenv("DISTILLERY_BASE_URL", raising=False)
        with pytest.raises(ValueError, match="DISTILLERY_BASE_URL"):
            build_gitlab_auth(_make_config())

    def test_no_secrets_in_logs(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("GITLAB_CLIENT_ID", "sekrit-id")
        monkeypatch.setenv("GITLAB_CLIENT_SECRET", "sekrit-value")
        monkeypatch.setenv("DISTILLERY_BASE_URL", "https://distillery.example.com")
        import logging

        with caplog.at_level(logging.DEBUG):
            build_gitlab_auth(_make_config(allowed_groups=["acme"]))
        assert "sekrit-value" not in caplog.text
        assert "sekrit-id" not in caplog.text


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestGitlabConfigValidation:
    def test_gitlab_provider_accepted(self) -> None:
        _validate(_make_config(allowed_groups=["acme"]))

    def test_self_hosted_empty_groups_allowed(self) -> None:
        _validate(_make_config(instance_url="https://gitlab.example.com"))

    def test_gitlab_com_requires_groups(self) -> None:
        with pytest.raises(ValueError, match="allowed_groups must be non-empty"):
            _validate(_make_config(instance_url="https://gitlab.com"))

    def test_gitlab_com_with_groups_ok(self) -> None:
        _validate(_make_config(instance_url="https://gitlab.com", allowed_groups=["acme"]))

    def test_allowed_groups_requires_gitlab_provider(self) -> None:
        config = _make_config(provider="github")
        config.server.auth.allowed_groups = ["acme"]
        with pytest.raises(ValueError, match="allowed_groups requires"):
            _validate(config)

    def test_invalid_instance_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="instance_url"):
            _validate(_make_config(instance_url="not-a-url"))
