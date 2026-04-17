"""Unit tests for scripts/hooks/session_start_briefing.py resolver."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Add scripts/hooks to the import path so we can import the module
HOOKS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "hooks"
sys.path.insert(0, str(HOOKS_DIR))

import session_start_briefing as briefing  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_cwd(tmp_path: Path) -> Path:
    """Return a temporary directory to use as cwd."""
    return tmp_path


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove Distillery env vars to start from a clean state."""
    for var in [
        "DISTILLERY_MCP_URL",
        "DISTILLERY_MCP_COMMAND",
        "DISTILLERY_BEARER_TOKEN",
        "DISTILLERY_BRIEFING_LIMIT",
    ]:
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Step 1: DISTILLERY_MCP_URL
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveEnvUrl:
    def test_returns_http_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISTILLERY_MCP_URL", "https://my-server.fly.dev/mcp")
        result = briefing.resolve_env_url()
        assert result is not None
        assert result.kind == "http"
        assert result.url == "https://my-server.fly.dev/mcp"
        assert result.source == "DISTILLERY_MCP_URL"

    def test_returns_none_when_unset(self, clean_env: None) -> None:
        result = briefing.resolve_env_url()
        assert result is None

    def test_returns_none_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISTILLERY_MCP_URL", "  ")
        result = briefing.resolve_env_url()
        assert result is None


# ---------------------------------------------------------------------------
# Step 2: DISTILLERY_MCP_COMMAND
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveEnvCommand:
    def test_returns_stdio_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISTILLERY_MCP_COMMAND", "distillery-mcp --db /tmp/test.db")
        result = briefing.resolve_env_command()
        assert result is not None
        assert result.kind == "stdio"
        assert result.command == ["distillery-mcp", "--db", "/tmp/test.db"]
        assert result.source == "DISTILLERY_MCP_COMMAND"

    def test_returns_none_when_unset(self, clean_env: None) -> None:
        result = briefing.resolve_env_command()
        assert result is None


# ---------------------------------------------------------------------------
# Step 3: .mcp.json
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveMcpJson:
    def test_finds_http_server(self, tmp_cwd: Path) -> None:
        mcp_json = tmp_cwd / ".mcp.json"
        mcp_json.write_text(
            json.dumps({"mcpServers": {"distillery-local": {"url": "http://localhost:9000/mcp"}}})
        )
        result = briefing.resolve_mcp_json(tmp_cwd)
        assert result is not None
        assert result.kind == "http"
        assert result.url == "http://localhost:9000/mcp"

    def test_finds_stdio_server(self, tmp_cwd: Path) -> None:
        mcp_json = tmp_cwd / ".mcp.json"
        mcp_json.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "distillery": {
                            "command": "distillery-mcp",
                            "args": ["--db", "/tmp/test.db"],
                        }
                    }
                }
            )
        )
        result = briefing.resolve_mcp_json(tmp_cwd)
        assert result is not None
        assert result.kind == "stdio"
        assert result.command == ["distillery-mcp", "--db", "/tmp/test.db"]

    def test_walks_up_directories(self, tmp_cwd: Path) -> None:
        mcp_json = tmp_cwd / ".mcp.json"
        mcp_json.write_text(
            json.dumps({"mcpServers": {"distillery": {"url": "http://localhost:8000/mcp"}}})
        )
        subdir = tmp_cwd / "src" / "deep"
        subdir.mkdir(parents=True)
        result = briefing.resolve_mcp_json(subdir)
        assert result is not None
        assert result.kind == "http"

    def test_returns_none_when_no_file(self, tmp_cwd: Path) -> None:
        result = briefing.resolve_mcp_json(tmp_cwd)
        assert result is None

    def test_returns_none_when_no_distillery(self, tmp_cwd: Path) -> None:
        mcp_json = tmp_cwd / ".mcp.json"
        mcp_json.write_text(
            json.dumps({"mcpServers": {"other-server": {"url": "http://other:8000"}}})
        )
        result = briefing.resolve_mcp_json(tmp_cwd)
        assert result is None

    def test_handles_malformed_json(self, tmp_cwd: Path) -> None:
        mcp_json = tmp_cwd / ".mcp.json"
        mcp_json.write_text("not json")
        result = briefing.resolve_mcp_json(tmp_cwd)
        assert result is None


# ---------------------------------------------------------------------------
# Step 4: ~/.claude.json project-scoped
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveClaudeJsonProject:
    def test_finds_project_server(self, tmp_cwd: Path, tmp_path: Path) -> None:
        claude_json = tmp_path / "home" / ".claude.json"
        claude_json.parent.mkdir(parents=True, exist_ok=True)
        claude_json.write_text(
            json.dumps(
                {
                    "projects": {
                        str(tmp_cwd): {
                            "mcpServers": {"distillery": {"url": "http://localhost:8000/mcp"}}
                        }
                    }
                }
            )
        )
        with patch.object(Path, "home", return_value=tmp_path / "home"):
            result = briefing.resolve_claude_json_project(tmp_cwd)
        assert result is not None
        assert result.kind == "http"

    def test_returns_none_when_no_file(self, tmp_cwd: Path, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path / "nonexistent"):
            result = briefing.resolve_claude_json_project(tmp_cwd)
        assert result is None


# ---------------------------------------------------------------------------
# Step 5: ~/.claude.json global
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveClaudeJsonGlobal:
    def test_finds_global_server(self, tmp_path: Path) -> None:
        claude_json = tmp_path / "home" / ".claude.json"
        claude_json.parent.mkdir(parents=True, exist_ok=True)
        claude_json.write_text(
            json.dumps({"mcpServers": {"distillery": {"command": "distillery-mcp", "args": []}}})
        )
        with patch.object(Path, "home", return_value=tmp_path / "home"):
            result = briefing.resolve_claude_json_global()
        assert result is not None
        assert result.kind == "stdio"
        assert result.command == ["distillery-mcp"]

    def test_returns_none_when_no_file(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path / "nonexistent"):
            result = briefing.resolve_claude_json_global()
        assert result is None


# ---------------------------------------------------------------------------
# Step 6: plugin.json
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolvePluginJson:
    def test_finds_plugin_server(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "home" / ".claude" / "plugins" / "distillery" / ".claude-plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "distillery": {
                            "command": "distillery-mcp",
                            "args": ["--transport", "stdio"],
                        }
                    }
                }
            )
        )
        with patch.object(Path, "home", return_value=tmp_path / "home"):
            result = briefing.resolve_plugin_json()
        assert result is not None
        assert result.kind == "stdio"

    def test_returns_none_when_no_plugins(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path / "nonexistent"):
            result = briefing.resolve_plugin_json()
        assert result is None


# ---------------------------------------------------------------------------
# Step 7: distillery-mcp on PATH
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolvePathCommand:
    def test_finds_command_on_path(self) -> None:
        with patch("shutil.which", return_value="/usr/local/bin/distillery-mcp"):
            result = briefing.resolve_path_command()
        assert result is not None
        assert result.kind == "stdio"
        assert result.command == ["distillery-mcp"]

    def test_returns_none_when_not_on_path(self) -> None:
        with patch("shutil.which", return_value=None):
            result = briefing.resolve_path_command()
        assert result is None


# ---------------------------------------------------------------------------
# Step 8: localhost fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveLocalhostFallback:
    def test_returns_http_localhost(self) -> None:
        result = briefing.resolve_localhost_fallback()
        assert result.kind == "http"
        assert result.url == "http://localhost:8000/mcp"
        assert result.source == "localhost fallback"


# ---------------------------------------------------------------------------
# Full resolution chain
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveTransport:
    def test_env_url_wins(self, monkeypatch: pytest.MonkeyPatch, tmp_cwd: Path) -> None:
        monkeypatch.setenv("DISTILLERY_MCP_URL", "https://custom.example.com/mcp")
        with patch("session_start_briefing.probe_transport", return_value=True):
            result = briefing.resolve_transport(tmp_cwd)
        assert result.kind == "http"
        assert result.url == "https://custom.example.com/mcp"
        assert result.source == "DISTILLERY_MCP_URL"

    def test_env_command_second(
        self, monkeypatch: pytest.MonkeyPatch, clean_env: None, tmp_cwd: Path
    ) -> None:
        monkeypatch.setenv("DISTILLERY_MCP_COMMAND", "my-distillery")
        with patch("session_start_briefing.probe_transport", return_value=True):
            result = briefing.resolve_transport(tmp_cwd)
        assert result.kind == "stdio"
        assert result.source == "DISTILLERY_MCP_COMMAND"

    def test_falls_through_to_localhost(self, clean_env: None, tmp_cwd: Path) -> None:
        with (
            patch("shutil.which", return_value=None),
            patch.object(Path, "home", return_value=tmp_cwd / "fakehome"),
        ):
            result = briefing.resolve_transport(tmp_cwd)
        assert result.kind == "http"
        assert result.url == "http://localhost:8000/mcp"
        assert result.source == "localhost fallback"

    def test_first_reachable_wins(
        self, monkeypatch: pytest.MonkeyPatch, clean_env: None, tmp_cwd: Path
    ) -> None:
        """If the first candidate exists but fails probing, the resolver must
        continue to later candidates rather than returning early."""
        # First candidate: DISTILLERY_MCP_URL (dead — probe will return False)
        monkeypatch.setenv("DISTILLERY_MCP_URL", "https://dead.example.com/mcp")
        # Second candidate: DISTILLERY_MCP_COMMAND (reachable — probe True)
        monkeypatch.setenv("DISTILLERY_MCP_COMMAND", "my-reachable-cmd")

        def fake_probe(transport: briefing.ResolvedTransport, _token: str = "") -> bool:
            # Only the stdio candidate is "reachable"
            return transport.source == "DISTILLERY_MCP_COMMAND"

        with patch("session_start_briefing.probe_transport", side_effect=fake_probe):
            result = briefing.resolve_transport(tmp_cwd)

        assert result.kind == "stdio"
        assert result.source == "DISTILLERY_MCP_COMMAND"
        assert result.command == ["my-reachable-cmd"]

    def test_all_candidates_unreachable_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, clean_env: None, tmp_cwd: Path
    ) -> None:
        """If every candidate fails probing, the localhost fallback is returned."""
        monkeypatch.setenv("DISTILLERY_MCP_URL", "https://dead.example.com/mcp")
        with (
            patch("session_start_briefing.probe_transport", return_value=False),
            patch("shutil.which", return_value=None),
            patch.object(Path, "home", return_value=tmp_cwd / "fakehome"),
        ):
            result = briefing.resolve_transport(tmp_cwd)
        assert result.source == "localhost fallback"


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractText:
    def test_extracts_text_from_response(self) -> None:
        resp = {"result": {"content": [{"type": "text", "text": "hello world"}]}}
        assert briefing.extract_text(resp) == "hello world"

    def test_returns_empty_for_none(self) -> None:
        assert briefing.extract_text(None) == ""

    def test_returns_empty_for_empty_content(self) -> None:
        assert briefing.extract_text({"result": {"content": []}}) == ""


# ---------------------------------------------------------------------------
# build_briefing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildBriefing:
    def test_basic_briefing(self) -> None:
        lines = briefing.build_briefing("myproject", "", "")
        assert lines == ["[Distillery] Project: myproject"]

    def test_with_recent_entries(self) -> None:
        recent = '{"id":"1","content":"first entry"},{"id":"2","content":"second"}'
        lines = briefing.build_briefing("proj", recent, "")
        assert len(lines) == 2
        assert lines[0] == "[Distillery] Project: proj"
        assert "Recent (2)" in lines[1]

    def test_max_20_lines(self) -> None:
        lines = briefing.build_briefing("p", "", "")
        assert len(lines) <= 20


# ---------------------------------------------------------------------------
# _server_entry_to_transport
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestServerEntryToTransport:
    def test_url_entry(self) -> None:
        entry = {"url": "http://example.com/mcp"}
        result = briefing._server_entry_to_transport(entry, "test")
        assert result is not None
        assert result.kind == "http"

    def test_command_entry(self) -> None:
        entry = {"command": "my-cmd", "args": ["--flag"], "env": {"FOO": "bar"}}
        result = briefing._server_entry_to_transport(entry, "test")
        assert result is not None
        assert result.kind == "stdio"
        assert result.command == ["my-cmd", "--flag"]
        assert result.env == {"FOO": "bar"}

    def test_empty_entry(self) -> None:
        result = briefing._server_entry_to_transport({}, "test")
        assert result is None


# ---------------------------------------------------------------------------
# _find_distillery_server
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindDistilleryServer:
    def test_finds_exact_match(self) -> None:
        servers = {"distillery": {"url": "http://x"}}
        assert briefing._find_distillery_server(servers) == {"url": "http://x"}

    def test_finds_partial_match(self) -> None:
        servers = {"my-distillery-server": {"url": "http://y"}}
        result = briefing._find_distillery_server(servers)
        assert result == {"url": "http://y"}

    def test_case_insensitive(self) -> None:
        servers = {"Distillery": {"url": "http://z"}}
        result = briefing._find_distillery_server(servers)
        assert result == {"url": "http://z"}

    def test_returns_none_for_no_match(self) -> None:
        servers = {"other-server": {"url": "http://a"}}
        assert briefing._find_distillery_server(servers) is None

    def test_returns_none_for_non_dict(self) -> None:
        assert briefing._find_distillery_server("not a dict") is None
        assert briefing._find_distillery_server(None) is None


# ---------------------------------------------------------------------------
# probe_transport (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProbeTransport:
    def test_http_probe_success(self) -> None:
        transport = briefing.ResolvedTransport(kind="http", url="http://localhost:8000/mcp")
        with patch("session_start_briefing._http_health_check", return_value=True):
            assert briefing.probe_transport(transport) is True

    def test_http_probe_failure(self) -> None:
        transport = briefing.ResolvedTransport(kind="http", url="http://localhost:8000/mcp")
        with patch("session_start_briefing._http_health_check", return_value=False):
            assert briefing.probe_transport(transport) is False

    def test_stdio_probe_success(self) -> None:
        transport = briefing.ResolvedTransport(kind="stdio", command=["distillery-mcp"])
        with patch("session_start_briefing._stdio_health_check", return_value=True):
            assert briefing.probe_transport(transport) is True

    def test_unknown_kind(self) -> None:
        transport = briefing.ResolvedTransport(kind="unknown")
        assert briefing.probe_transport(transport) is False


# ---------------------------------------------------------------------------
# Real stdio subprocess (exercises Popen/communicate wiring)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStdioSubprocess:
    """Exercise the real _stdio_health_check / _stdio_call_tool subprocess flow.

    These tests guard against regressions in the Popen/communicate sequence —
    specifically the `flush of closed file` ValueError that surfaces when
    stdin is closed before `communicate()` is called on CPython.
    """

    def test_health_check_with_real_subprocess(self) -> None:
        """A trivial Python script that emits a valid initialize reply should
        cause _stdio_health_check to return True."""
        script = (
            "import sys, json\n"
            "sys.stdin.readline()  # initialize request\n"
            'reply = {"jsonrpc": "2.0", "id": 0, "result": {"capabilities": {}}}\n'
            'sys.stdout.write(json.dumps(reply) + "\\n")\n'
            "sys.stdout.flush()\n"
        )
        command = [sys.executable, "-c", script]
        assert briefing._stdio_health_check(command, timeout=5) is True

    def test_health_check_fails_on_nonzero_exit_with_no_reply(self) -> None:
        """A subprocess that exits without emitting an initialize result
        should cause _stdio_health_check to return False, not raise."""
        command = [sys.executable, "-c", "import sys; sys.exit(1)"]
        assert briefing._stdio_health_check(command, timeout=5) is False

    def test_call_tool_with_real_subprocess(self) -> None:
        """Drive the full two-round-trip flow against a fake MCP server."""
        script = (
            "import sys, json\n"
            "# initialize\n"
            "sys.stdin.readline()\n"
            'sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": 0, '
            '"result": {"capabilities": {}}}) + "\\n")\n'
            "# notifications/initialized (no reply)\n"
            "sys.stdin.readline()\n"
            "# tools/call\n"
            "sys.stdin.readline()\n"
            'sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": 1, '
            '"result": {"content": [{"type": "text", "text": "pong"}]}}) + "\\n")\n'
            "sys.stdout.flush()\n"
        )
        command = [sys.executable, "-c", script]
        resp = briefing._stdio_call_tool(command, "ping", {}, timeout=5)
        assert isinstance(resp, dict)
        assert resp.get("id") == 1
        assert resp.get("result", {}).get("content", [{}])[0].get("text") == "pong"

    def test_call_tool_handles_timeout(self) -> None:
        """A subprocess that never replies should time out cleanly and
        return None instead of hanging or raising."""
        # Read forever; never respond.
        script = "import sys\nwhile True:\n    if not sys.stdin.readline(): break\n"
        command = [sys.executable, "-c", script]
        assert briefing._stdio_call_tool(command, "noop", {}, timeout=1) is None


# ---------------------------------------------------------------------------
# CodeRabbit follow-ups: URL normalization, header passthrough, deepest project
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeMcpUrl:
    def test_bare_base_appends_mcp(self) -> None:
        mcp_url, health_url = briefing._normalize_mcp_url("https://host.example/")
        assert mcp_url == "https://host.example/mcp"
        assert health_url == "https://host.example/health"

    def test_already_mcp(self) -> None:
        mcp_url, health_url = briefing._normalize_mcp_url("https://host.example/mcp")
        assert mcp_url == "https://host.example/mcp"
        assert health_url == "https://host.example/health"

    def test_trailing_slash_on_mcp(self) -> None:
        mcp_url, _ = briefing._normalize_mcp_url("https://host.example/mcp/")
        assert mcp_url == "https://host.example/mcp"

    def test_health_url_input(self) -> None:
        mcp_url, health_url = briefing._normalize_mcp_url("https://host.example/health")
        assert mcp_url == "https://host.example/mcp"
        assert health_url == "https://host.example/health"


@pytest.mark.unit
class TestTransportHeaders:
    def test_server_entry_preserves_headers(self) -> None:
        entry = {
            "url": "https://team.example/mcp",
            "headers": {"X-Team-Token": "secret"},
        }
        transport = briefing._server_entry_to_transport(entry, "test")
        assert transport is not None
        assert transport.headers == {"X-Team-Token": "secret"}

    def test_server_entry_missing_headers_is_empty(self) -> None:
        transport = briefing._server_entry_to_transport({"url": "https://team.example/mcp"}, "test")
        assert transport is not None
        assert transport.headers == {}

    def test_http_call_tool_merges_transport_headers(self) -> None:
        captured: dict[str, Any] = {}

        class _FakeResp:
            status = 200

            def read(self) -> bytes:
                return b'{"jsonrpc":"2.0","id":1,"result":{}}'

            def __enter__(self) -> _FakeResp:
                return self

            def __exit__(self, *_: Any) -> None:
                return None

        def fake_urlopen(req: Any, timeout: int = 10) -> _FakeResp:
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            return _FakeResp()

        with patch.object(briefing.urllib.request, "urlopen", fake_urlopen):
            briefing._http_call_tool(
                "https://team.example",
                "ping",
                {},
                bearer_token="tok",
                transport_headers={"X-Team-Token": "secret"},
            )
        assert captured["url"] == "https://team.example/mcp"
        # header_items lowercases keys in urllib
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        assert headers["x-team-token"] == "secret"
        assert headers["authorization"] == "Bearer tok"
        assert headers["content-type"] == "application/json"


@pytest.mark.unit
class TestDeepestProjectMatch:
    def test_nested_subproject_wins(self, tmp_path: Path) -> None:
        parent = tmp_path / "workspace"
        child = parent / "packages" / "app"
        child.mkdir(parents=True)

        claude_json = tmp_path / "home" / ".claude.json"
        claude_json.parent.mkdir(parents=True, exist_ok=True)
        claude_json.write_text(
            json.dumps(
                {
                    "projects": {
                        str(parent): {
                            "mcpServers": {"distillery": {"url": "http://parent-server/mcp"}}
                        },
                        str(child): {
                            "mcpServers": {"distillery": {"url": "http://child-server/mcp"}}
                        },
                    }
                }
            )
        )
        with patch.object(Path, "home", return_value=tmp_path / "home"):
            result = briefing.resolve_claude_json_project(child)
        assert result is not None
        assert result.url == "http://child-server/mcp"

    def test_no_match_returns_none(self, tmp_path: Path) -> None:
        other = tmp_path / "other"
        other.mkdir()
        claude_json = tmp_path / "home" / ".claude.json"
        claude_json.parent.mkdir(parents=True, exist_ok=True)
        claude_json.write_text(
            json.dumps(
                {
                    "projects": {
                        str(tmp_path / "elsewhere"): {
                            "mcpServers": {"distillery": {"url": "http://x/mcp"}}
                        }
                    }
                }
            )
        )
        with patch.object(Path, "home", return_value=tmp_path / "home"):
            result = briefing.resolve_claude_json_project(other)
        assert result is None
