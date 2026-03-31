"""Tests for distillery.mcp.org_membership: OrgMembershipChecker and helpers."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from distillery.config import (
    DistilleryConfig,
    ServerAuthConfig,
    ServerConfig,
    StorageConfig,
    _parse_server,
)
from distillery.mcp.org_membership import OrgMembershipChecker, _try_decode_jwt_claims

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _try_decode_jwt_claims
# ---------------------------------------------------------------------------


class TestTryDecodeJwtClaims:
    def test_valid_jwt_returns_claims(self) -> None:
        import base64
        import json

        header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json.dumps({"login": "alice", "sub": "12345"}).encode()
        ).rstrip(b"=").decode()
        token = f"{header}.{payload}.fakesig"

        result = _try_decode_jwt_claims(token)
        assert result is not None
        assert result["login"] == "alice"

    def test_opaque_token_returns_none(self) -> None:
        assert _try_decode_jwt_claims("gho_notajwt") is None

    def test_two_part_token_returns_none(self) -> None:
        assert _try_decode_jwt_claims("header.payload") is None

    def test_invalid_base64_returns_none(self) -> None:
        assert _try_decode_jwt_claims("hdr.!!!invalid!!!.sig") is None

    def test_non_dict_payload_returns_none(self) -> None:
        import base64
        import json

        header = base64.urlsafe_b64encode(b"{}").rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(json.dumps([1, 2, 3]).encode()).rstrip(b"=").decode()
        token = f"{header}.{payload}.sig"
        assert _try_decode_jwt_claims(token) is None


# ---------------------------------------------------------------------------
# OrgMembershipChecker — disabled (no orgs configured)
# ---------------------------------------------------------------------------


class TestOrgMembershipCheckerDisabled:
    async def test_no_orgs_always_allowed(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=[])
        assert await checker.is_allowed("anyuser") is True

    def test_enabled_property_false_when_no_orgs(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=[])
        assert checker.enabled is False

    def test_enabled_property_true_when_orgs_set(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["acme"])
        assert checker.enabled is True


# ---------------------------------------------------------------------------
# OrgMembershipChecker — user token store
# ---------------------------------------------------------------------------


class TestUserTokenStore:
    def test_store_and_retrieve_token(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["acme"], cache_ttl_seconds=3600)
        checker.store_user_token("alice", "ghp_token123")
        assert checker._resolve_token("alice", None) == "ghp_token123"

    def test_hint_token_takes_priority(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["acme"], cache_ttl_seconds=3600)
        checker.store_user_token("alice", "ghp_stored")
        assert checker._resolve_token("alice", "ghp_hint") == "ghp_hint"

    def test_expired_user_token_removed(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["acme"], cache_ttl_seconds=1)
        checker.store_user_token("alice", "ghp_token")
        # Manually expire the entry.
        checker._user_tokens["alice"] = ("ghp_token", time.monotonic() - 10)
        assert checker._resolve_token("alice", None) is None
        assert "alice" not in checker._user_tokens

    def test_server_token_fallback(self) -> None:
        checker = OrgMembershipChecker(
            allowed_orgs=["acme"],
            cache_ttl_seconds=3600,
            server_token="ghp_server",
        )
        assert checker._resolve_token("alice", None) == "ghp_server"

    def test_no_token_returns_none(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["acme"], cache_ttl_seconds=3600)
        assert checker._resolve_token("alice", None) is None


# ---------------------------------------------------------------------------
# OrgMembershipChecker — API behaviour
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, json_body: object = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if json_body is not None:
        resp.json.return_value = json_body
    return resp


class TestOrgMembershipApiMember:
    async def test_204_returns_true(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["acme"])
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response(204))
            mock_client_cls.return_value = mock_client
            result = await checker.is_allowed("alice", hint_token="tok")
        assert result is True


class TestOrgMembershipApiNonMember:
    async def test_404_returns_false(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["acme"])
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response(404))
            mock_client_cls.return_value = mock_client
            result = await checker.is_allowed("alice", hint_token="tok")
        assert result is False


class TestOrgMembershipApiPrivateOrg:
    async def test_302_without_token_returns_false(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["private-corp"])
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response(302))
            mock_client_cls.return_value = mock_client
            result = await checker.is_allowed("alice")
        assert result is False

    async def test_302_with_token_falls_back_to_user_orgs_member(self) -> None:
        """302 on /members/{user} + user in /user/orgs → True."""
        checker = OrgMembershipChecker(allowed_orgs=["private-corp"])

        members_resp = _mock_response(302)
        user_orgs_resp = _mock_response(200, [{"login": "private-corp"}])

        with patch("httpx.AsyncClient") as mock_client_cls:
            call_count = 0

            async def fake_get(url: str, **kwargs: object) -> MagicMock:
                nonlocal call_count
                call_count += 1
                if "members" in url:
                    return members_resp
                return user_orgs_resp

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = fake_get
            mock_client_cls.return_value = mock_client

            result = await checker.is_allowed("alice", hint_token="ghp_tok")
        assert result is True

    async def test_302_with_token_falls_back_to_user_orgs_non_member(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["private-corp"])

        members_resp = _mock_response(302)
        user_orgs_resp = _mock_response(200, [{"login": "other-org"}])

        with patch("httpx.AsyncClient") as mock_client_cls:
            async def fake_get(url: str, **kwargs: object) -> MagicMock:
                if "members" in url:
                    return members_resp
                return user_orgs_resp

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = fake_get
            mock_client_cls.return_value = mock_client

            result = await checker.is_allowed("alice", hint_token="ghp_tok")
        assert result is False


class TestOrgMembershipApiErrorHandling:
    async def test_unexpected_status_returns_false(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["acme"])
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response(500))
            mock_client_cls.return_value = mock_client
            result = await checker.is_allowed("alice", hint_token="tok")
        assert result is False

    async def test_network_error_fails_closed(self) -> None:
        import httpx

        checker = OrgMembershipChecker(allowed_orgs=["acme"])
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
            mock_client_cls.return_value = mock_client
            result = await checker.is_allowed("alice", hint_token="tok")
        assert result is False

    async def test_unauthenticated_check_omits_auth_header(self) -> None:
        """When no token is available, no Authorization header should be sent."""
        checker = OrgMembershipChecker(allowed_orgs=["acme"])
        captured_headers: dict[str, str] = {}

        with patch("httpx.AsyncClient") as mock_client_cls:
            async def fake_get(url: str, headers: dict[str, str], **kw: object) -> MagicMock:
                captured_headers.update(headers)
                return _mock_response(204)

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = fake_get
            mock_client_cls.return_value = mock_client

            await checker.is_allowed("alice")

        assert "Authorization" not in captured_headers


# ---------------------------------------------------------------------------
# OrgMembershipChecker — multi-org short-circuit
# ---------------------------------------------------------------------------


class TestMultiOrgShortCircuit:
    async def test_first_positive_match_returns_true(self) -> None:
        """Member of second org after non-membership in first → True."""
        checker = OrgMembershipChecker(allowed_orgs=["acme", "partner"])
        call_count = 0

        with patch("httpx.AsyncClient") as mock_client_cls:
            async def fake_get(url: str, **kwargs: object) -> MagicMock:
                nonlocal call_count
                call_count += 1
                if "acme" in url:
                    return _mock_response(404)
                return _mock_response(204)

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = fake_get
            mock_client_cls.return_value = mock_client

            result = await checker.is_allowed("alice", hint_token="tok")
        assert result is True
        assert call_count == 2  # checked both orgs

    async def test_no_match_across_all_orgs_returns_false(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["acme", "partner"])
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_response(404))
            mock_client_cls.return_value = mock_client
            result = await checker.is_allowed("alice", hint_token="tok")
        assert result is False


# ---------------------------------------------------------------------------
# OrgMembershipChecker — TTL caching
# ---------------------------------------------------------------------------


class TestOrgMembershipCaching:
    async def test_cache_hit_avoids_second_api_call(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["acme"], cache_ttl_seconds=3600)
        api_call_count = 0

        with patch("httpx.AsyncClient") as mock_client_cls:
            async def fake_get(url: str, **kwargs: object) -> MagicMock:
                nonlocal api_call_count
                api_call_count += 1
                return _mock_response(204)

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = fake_get
            mock_client_cls.return_value = mock_client

            first = await checker.is_allowed("alice", hint_token="tok")
            second = await checker.is_allowed("alice", hint_token="tok")

        assert first is True
        assert second is True
        assert api_call_count == 1  # second call was served from cache

    async def test_cache_expires_after_ttl(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["acme"], cache_ttl_seconds=1)
        api_call_count = 0

        with patch("httpx.AsyncClient") as mock_client_cls:
            async def fake_get(url: str, **kwargs: object) -> MagicMock:
                nonlocal api_call_count
                api_call_count += 1
                return _mock_response(204)

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = fake_get
            mock_client_cls.return_value = mock_client

            await checker.is_allowed("alice", hint_token="tok")

            # Manually expire the cache entry.
            for key in list(checker._cache):
                entry = checker._cache[key]
                checker._cache[key].__class__.__init__(entry, entry.is_member, 0.0)
                entry.expires_at = 0.0

            await checker.is_allowed("alice", hint_token="tok")

        assert api_call_count == 2

    async def test_negative_result_is_cached(self) -> None:
        checker = OrgMembershipChecker(allowed_orgs=["acme"], cache_ttl_seconds=3600)
        api_call_count = 0

        with patch("httpx.AsyncClient") as mock_client_cls:
            async def fake_get(url: str, **kwargs: object) -> MagicMock:
                nonlocal api_call_count
                api_call_count += 1
                return _mock_response(404)

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = fake_get
            mock_client_cls.return_value = mock_client

            first = await checker.is_allowed("alice", hint_token="tok")
            second = await checker.is_allowed("alice", hint_token="tok")

        assert first is False
        assert second is False
        assert api_call_count == 1


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


class TestOrgMembershipConfig:
    def test_allowed_orgs_parsed_from_yaml(self) -> None:
        raw: dict[str, object] = {
            "auth": {
                "provider": "github",
                "allowed_orgs": ["acme", "partner"],
            }
        }
        server = _parse_server(raw)
        assert server.auth.allowed_orgs == ["acme", "partner"]

    def test_membership_cache_ttl_parsed(self) -> None:
        raw: dict[str, object] = {
            "auth": {
                "provider": "github",
                "membership_cache_ttl_seconds": 1800,
            }
        }
        server = _parse_server(raw)
        assert server.auth.membership_cache_ttl_seconds == 1800

    def test_defaults_when_fields_absent(self) -> None:
        server = _parse_server({"auth": {"provider": "github"}})
        assert server.auth.allowed_orgs == []
        assert server.auth.membership_cache_ttl_seconds == 3600

    def test_invalid_allowed_orgs_type_raises(self) -> None:
        with pytest.raises(ValueError, match="allowed_orgs must be a YAML list"):
            _parse_server({"auth": {"provider": "github", "allowed_orgs": "acme"}})

    def test_invalid_ttl_raises(self) -> None:
        with pytest.raises(ValueError, match="membership_cache_ttl_seconds"):
            _parse_server({"auth": {"provider": "github", "membership_cache_ttl_seconds": "bad"}})

    def test_allowed_orgs_requires_github_provider(self) -> None:
        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            server=ServerConfig(
                auth=ServerAuthConfig(
                    provider="none",
                    allowed_orgs=["acme"],
                )
            ),
        )
        from distillery.config import _validate

        with pytest.raises(ValueError, match="allowed_orgs requires"):
            _validate(config)

    def test_negative_ttl_raises(self) -> None:
        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            server=ServerConfig(
                auth=ServerAuthConfig(
                    provider="github",
                    membership_cache_ttl_seconds=-1,
                )
            ),
        )
        from distillery.config import _validate

        with pytest.raises(ValueError, match="membership_cache_ttl_seconds"):
            _validate(config)

    def test_empty_org_strings_stripped(self) -> None:
        raw: dict[str, object] = {
            "auth": {
                "provider": "github",
                "allowed_orgs": ["  acme  ", "", "  "],
            }
        }
        server = _parse_server(raw)
        assert server.auth.allowed_orgs == ["acme"]


# ---------------------------------------------------------------------------
# build_org_checker — env var merging
# ---------------------------------------------------------------------------


class TestBuildOrgChecker:
    def test_returns_none_when_no_orgs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DISTILLERY_ALLOWED_ORGS", raising=False)
        from distillery.mcp.auth import build_org_checker

        config = DistilleryConfig(storage=StorageConfig(database_path=":memory:"))
        assert build_org_checker(config) is None

    def test_returns_checker_with_yaml_orgs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DISTILLERY_ALLOWED_ORGS", raising=False)
        from distillery.mcp.auth import build_org_checker

        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            server=ServerConfig(
                auth=ServerAuthConfig(
                    provider="github",
                    allowed_orgs=["acme"],
                )
            ),
        )
        checker = build_org_checker(config)
        assert checker is not None
        assert checker.enabled
        assert checker._allowed_orgs == ["acme"]

    def test_env_var_orgs_merged_with_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISTILLERY_ALLOWED_ORGS", "extra-org, another-org")
        from distillery.mcp.auth import build_org_checker

        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            server=ServerConfig(
                auth=ServerAuthConfig(
                    provider="github",
                    allowed_orgs=["yaml-org"],
                )
            ),
        )
        checker = build_org_checker(config)
        assert checker is not None
        assert "yaml-org" in checker._allowed_orgs
        assert "extra-org" in checker._allowed_orgs
        assert "another-org" in checker._allowed_orgs

    def test_env_var_only_no_yaml_orgs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISTILLERY_ALLOWED_ORGS", "env-org")
        from distillery.mcp.auth import build_org_checker

        config = DistilleryConfig(storage=StorageConfig(database_path=":memory:"))
        checker = build_org_checker(config)
        assert checker is not None
        assert checker._allowed_orgs == ["env-org"]

    def test_server_token_read_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DISTILLERY_ALLOWED_ORGS", raising=False)
        monkeypatch.setenv("GITHUB_ORG_CHECK_TOKEN", "ghp_server_pat")
        from distillery.mcp.auth import build_org_checker

        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            server=ServerConfig(
                auth=ServerAuthConfig(
                    provider="github",
                    allowed_orgs=["acme"],
                )
            ),
        )
        checker = build_org_checker(config)
        assert checker is not None
        assert checker._server_token == "ghp_server_pat"

    def test_duplicate_orgs_deduplicated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISTILLERY_ALLOWED_ORGS", "acme,partner")
        from distillery.mcp.auth import build_org_checker

        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            server=ServerConfig(
                auth=ServerAuthConfig(
                    provider="github",
                    allowed_orgs=["acme"],
                )
            ),
        )
        checker = build_org_checker(config)
        assert checker is not None
        assert checker._allowed_orgs.count("acme") == 1
