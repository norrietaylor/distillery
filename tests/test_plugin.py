"""Tests for the Claude Code plugin manifest (plugin.json) and plugin documentation (docs/plugin.md).

Covers:
  - plugin.json is valid JSON and contains all required top-level fields
  - Plugin metadata (name, version, author, homepage, repository, keywords)
  - Skills array: count, required fields, names, and path conventions
  - MCP server configuration: presence, required flag, transports, default_transport
  - stdio transport fields (command, env, install)
  - HTTP transport fields (url)
  - docs/plugin.md structure: file existence, required headings, skill coverage
  - docs/plugin.md content: code blocks, references to plugin.json, installation sections
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
PLUGIN_JSON_PATH = REPO_ROOT / "plugin.json"
PLUGIN_DOC_PATH = REPO_ROOT / "docs" / "plugin.md"

EXPECTED_SKILL_NAMES = {"distill", "recall", "pour", "bookmark", "minutes", "classify"}


def load_plugin_manifest() -> dict:  # type: ignore[type-arg]
    """Load and parse plugin.json from the repository root."""
    return json.loads(PLUGIN_JSON_PATH.read_text(encoding="utf-8"))


def load_plugin_doc() -> str:
    """Load docs/plugin.md from the repository root."""
    return PLUGIN_DOC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# plugin.json — file-level tests
# ---------------------------------------------------------------------------


class TestPluginManifestFile:
    def test_plugin_json_exists(self) -> None:
        """plugin.json must exist at the repository root."""
        assert PLUGIN_JSON_PATH.exists(), f"plugin.json not found at {PLUGIN_JSON_PATH}"

    def test_plugin_json_is_valid_json(self) -> None:
        """plugin.json must be parseable as valid JSON."""
        content = PLUGIN_JSON_PATH.read_text(encoding="utf-8")
        manifest = json.loads(content)  # raises json.JSONDecodeError on failure
        assert isinstance(manifest, dict)

    def test_plugin_json_is_non_empty(self) -> None:
        """plugin.json must not be empty."""
        manifest = load_plugin_manifest()
        assert len(manifest) > 0


# ---------------------------------------------------------------------------
# plugin.json — top-level metadata fields
# ---------------------------------------------------------------------------


class TestPluginManifestMetadata:
    def test_schema_field_present(self) -> None:
        """$schema field must be present."""
        manifest = load_plugin_manifest()
        assert "$schema" in manifest

    def test_schema_field_references_claude(self) -> None:
        """$schema must reference the Claude plugin schema."""
        manifest = load_plugin_manifest()
        assert "claude.ai" in manifest["$schema"]

    def test_name_is_distillery(self) -> None:
        """Plugin name must be 'distillery'."""
        manifest = load_plugin_manifest()
        assert manifest["name"] == "distillery"

    def test_version_present(self) -> None:
        """version field must be present."""
        manifest = load_plugin_manifest()
        assert "version" in manifest

    def test_version_follows_semver(self) -> None:
        """version must follow a MAJOR.MINOR.PATCH pattern."""
        manifest = load_plugin_manifest()
        version = manifest["version"]
        assert re.match(r"^\d+\.\d+\.\d+", version), f"version '{version}' is not semver"

    def test_version_value(self) -> None:
        """version must be '0.1.0'."""
        manifest = load_plugin_manifest()
        assert manifest["version"] == "0.1.0"

    def test_description_present_and_non_empty(self) -> None:
        """description field must be a non-empty string."""
        manifest = load_plugin_manifest()
        assert "description" in manifest
        assert isinstance(manifest["description"], str)
        assert len(manifest["description"]) > 0

    def test_author_is_norrietaylor(self) -> None:
        """author field must be 'norrietaylor'."""
        manifest = load_plugin_manifest()
        assert manifest["author"] == "norrietaylor"

    def test_homepage_is_github_url(self) -> None:
        """homepage must point to the GitHub repository."""
        manifest = load_plugin_manifest()
        assert manifest["homepage"] == "https://github.com/norrietaylor/distillery"

    def test_repository_matches_homepage(self) -> None:
        """repository and homepage must point to the same URL."""
        manifest = load_plugin_manifest()
        assert manifest["repository"] == manifest["homepage"]

    def test_keywords_is_list(self) -> None:
        """keywords must be a list."""
        manifest = load_plugin_manifest()
        assert isinstance(manifest["keywords"], list)

    def test_keywords_contains_expected_terms(self) -> None:
        """keywords must contain at minimum the core identifying terms."""
        manifest = load_plugin_manifest()
        keywords = manifest["keywords"]
        for term in ("knowledge-base", "mcp", "distillery"):
            assert term in keywords, f"keyword '{term}' missing from keywords"

    def test_all_required_top_level_keys_present(self) -> None:
        """All required top-level keys must be present in the manifest."""
        manifest = load_plugin_manifest()
        required_keys = {
            "$schema", "name", "version", "description",
            "author", "homepage", "repository", "keywords",
            "skills", "mcpServers",
        }
        for key in required_keys:
            assert key in manifest, f"Required key '{key}' missing from plugin.json"


# ---------------------------------------------------------------------------
# plugin.json — skills array
# ---------------------------------------------------------------------------


class TestPluginSkills:
    def test_skills_is_a_list(self) -> None:
        """skills field must be a list."""
        manifest = load_plugin_manifest()
        assert isinstance(manifest["skills"], list)

    def test_skills_has_exactly_six_entries(self) -> None:
        """There must be exactly six skills declared."""
        manifest = load_plugin_manifest()
        assert len(manifest["skills"]) == 6

    def test_each_skill_has_required_fields(self) -> None:
        """Every skill must have 'name', 'description', and 'path' fields."""
        manifest = load_plugin_manifest()
        for skill in manifest["skills"]:
            for field in ("name", "description", "path"):
                assert field in skill, f"Skill is missing required field '{field}': {skill}"

    def test_skill_names_match_expected_set(self) -> None:
        """Skill names must exactly match the expected set of six skill names."""
        manifest = load_plugin_manifest()
        names = {skill["name"] for skill in manifest["skills"]}
        assert names == EXPECTED_SKILL_NAMES

    def test_skill_paths_follow_convention(self) -> None:
        """Each skill path must follow the '.claude/skills/{name}/SKILL.md' pattern."""
        manifest = load_plugin_manifest()
        for skill in manifest["skills"]:
            expected_path = f".claude/skills/{skill['name']}/SKILL.md"
            assert skill["path"] == expected_path, (
                f"Skill '{skill['name']}' has unexpected path '{skill['path']}'; "
                f"expected '{expected_path}'"
            )

    def test_skill_descriptions_are_non_empty(self) -> None:
        """Each skill description must be a non-empty string."""
        manifest = load_plugin_manifest()
        for skill in manifest["skills"]:
            assert isinstance(skill["description"], str)
            assert len(skill["description"]) > 0, (
                f"Skill '{skill['name']}' has an empty description"
            )

    def test_distill_skill_trigger_phrases_mentioned(self) -> None:
        """The distill skill description must mention its trigger phrases."""
        manifest = load_plugin_manifest()
        distill = next(s for s in manifest["skills"] if s["name"] == "distill")
        desc = distill["description"].lower()
        assert "distill" in desc or "capture" in desc or "save knowledge" in desc

    def test_recall_skill_description_mentions_search(self) -> None:
        """The recall skill description must mention semantic search."""
        manifest = load_plugin_manifest()
        recall = next(s for s in manifest["skills"] if s["name"] == "recall")
        assert "search" in recall["description"].lower()

    def test_bookmark_skill_description_mentions_url(self) -> None:
        """The bookmark skill description must mention URLs."""
        manifest = load_plugin_manifest()
        bookmark = next(s for s in manifest["skills"] if s["name"] == "bookmark")
        desc = bookmark["description"].lower()
        assert "url" in desc or "link" in desc

    def test_skill_names_are_unique(self) -> None:
        """No two skills may share the same name."""
        manifest = load_plugin_manifest()
        names = [skill["name"] for skill in manifest["skills"]]
        assert len(names) == len(set(names)), "Duplicate skill names detected"

    def test_skill_paths_are_unique(self) -> None:
        """No two skills may share the same path."""
        manifest = load_plugin_manifest()
        paths = [skill["path"] for skill in manifest["skills"]]
        assert len(paths) == len(set(paths)), "Duplicate skill paths detected"


# ---------------------------------------------------------------------------
# plugin.json — MCP server configuration
# ---------------------------------------------------------------------------


class TestPluginMCPServers:
    def test_mcp_servers_key_present(self) -> None:
        """mcpServers field must be present."""
        manifest = load_plugin_manifest()
        assert "mcpServers" in manifest

    def test_distillery_server_declared(self) -> None:
        """The 'distillery' MCP server must be declared."""
        manifest = load_plugin_manifest()
        assert "distillery" in manifest["mcpServers"]

    def test_distillery_server_is_required(self) -> None:
        """The distillery MCP server must be marked as required=true."""
        manifest = load_plugin_manifest()
        server = manifest["mcpServers"]["distillery"]
        assert server.get("required") is True

    def test_distillery_server_has_description(self) -> None:
        """The distillery server must have a description."""
        manifest = load_plugin_manifest()
        server = manifest["mcpServers"]["distillery"]
        assert "description" in server
        assert len(server["description"]) > 0

    def test_distillery_server_has_setup_section(self) -> None:
        """The distillery server config must include a setup guidance section."""
        manifest = load_plugin_manifest()
        server = manifest["mcpServers"]["distillery"]
        assert "setup" in server
        assert "message" in server["setup"]
        assert "docs" in server["setup"]

    def test_setup_docs_url_references_mcp_setup(self) -> None:
        """The setup docs URL must point to the MCP setup documentation."""
        manifest = load_plugin_manifest()
        docs_url = manifest["mcpServers"]["distillery"]["setup"]["docs"]
        assert "mcp-setup" in docs_url

    def test_transports_is_list_with_two_entries(self) -> None:
        """The distillery server must declare exactly two transports."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        assert isinstance(transports, list)
        assert len(transports) == 2

    def test_default_transport_is_local(self) -> None:
        """default_transport must be 'local'."""
        manifest = load_plugin_manifest()
        assert manifest["mcpServers"]["distillery"]["default_transport"] == "local"

    def test_stdio_transport_present(self) -> None:
        """A stdio-type transport must be present."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        types = [t["type"] for t in transports]
        assert "stdio" in types

    def test_http_transport_present(self) -> None:
        """An http-type transport must be present."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        types = [t["type"] for t in transports]
        assert "http" in types

    def test_stdio_transport_has_required_fields(self) -> None:
        """The stdio transport must have 'command' and 'env' fields."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        stdio = next(t for t in transports if t["type"] == "stdio")
        assert "command" in stdio, "stdio transport missing 'command'"
        assert "env" in stdio, "stdio transport missing 'env'"

    def test_stdio_transport_command_is_distillery_mcp(self) -> None:
        """The stdio transport command must be 'distillery-mcp'."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        stdio = next(t for t in transports if t["type"] == "stdio")
        assert stdio["command"] == "distillery-mcp"

    def test_stdio_transport_env_has_jina_api_key(self) -> None:
        """The stdio transport env must declare JINA_API_KEY."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        stdio = next(t for t in transports if t["type"] == "stdio")
        assert "JINA_API_KEY" in stdio["env"]

    def test_stdio_transport_env_has_distillery_config(self) -> None:
        """The stdio transport env must declare DISTILLERY_CONFIG."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        stdio = next(t for t in transports if t["type"] == "stdio")
        assert "DISTILLERY_CONFIG" in stdio["env"]

    def test_stdio_transport_has_install_section(self) -> None:
        """The stdio transport must include an install guidance section."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        stdio = next(t for t in transports if t["type"] == "stdio")
        assert "install" in stdio
        assert "command" in stdio["install"]

    def test_stdio_transport_install_command_is_pip(self) -> None:
        """The stdio transport install command must be pip-based."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        stdio = next(t for t in transports if t["type"] == "stdio")
        assert "pip" in stdio["install"]["command"]

    def test_http_transport_has_url(self) -> None:
        """The http transport must have a 'url' field."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        http = next(t for t in transports if t["type"] == "http")
        assert "url" in http
        assert http["url"].startswith("https://")

    def test_transports_have_id_and_label(self) -> None:
        """Every transport must have 'id' and 'label' fields."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        for transport in transports:
            assert "id" in transport, f"Transport missing 'id': {transport}"
            assert "label" in transport, f"Transport missing 'label': {transport}"

    def test_transport_ids_are_unique(self) -> None:
        """Transport 'id' values must be unique."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        ids = [t["id"] for t in transports]
        assert len(ids) == len(set(ids)), "Duplicate transport ids detected"

    def test_local_transport_id_and_label(self) -> None:
        """The stdio transport must have id='local' and label='Local (stdio)'."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        stdio = next(t for t in transports if t["type"] == "stdio")
        assert stdio["id"] == "local"
        assert stdio["label"] == "Local (stdio)"

    def test_hosted_transport_id_and_label(self) -> None:
        """The http transport must have id='hosted' and label='Hosted (HTTP/SSE)'."""
        manifest = load_plugin_manifest()
        transports = manifest["mcpServers"]["distillery"]["transports"]
        http = next(t for t in transports if t["type"] == "http")
        assert http["id"] == "hosted"
        assert http["label"] == "Hosted (HTTP/SSE)"


# ---------------------------------------------------------------------------
# docs/plugin.md — file-level tests
# ---------------------------------------------------------------------------


class TestPluginDocumentationFile:
    def test_plugin_doc_exists(self) -> None:
        """docs/plugin.md must exist."""
        assert PLUGIN_DOC_PATH.exists(), f"docs/plugin.md not found at {PLUGIN_DOC_PATH}"

    def test_plugin_doc_is_non_empty(self) -> None:
        """docs/plugin.md must not be empty."""
        content = load_plugin_doc()
        assert len(content.strip()) > 0

    def test_plugin_doc_starts_with_h1(self) -> None:
        """docs/plugin.md must start with an H1 heading."""
        content = load_plugin_doc()
        first_heading = next(
            (line for line in content.splitlines() if line.startswith("# ")), None
        )
        assert first_heading is not None, "docs/plugin.md has no H1 heading"


# ---------------------------------------------------------------------------
# docs/plugin.md — required section headings
# ---------------------------------------------------------------------------


class TestPluginDocumentationHeadings:
    def _get_headings(self) -> list[str]:
        content = load_plugin_doc()
        return [
            line.lstrip("#").strip()
            for line in content.splitlines()
            if line.startswith("#")
        ]

    def test_has_plugin_manifest_section(self) -> None:
        """docs/plugin.md must have a 'Plugin Manifest' section."""
        headings = self._get_headings()
        assert any("Plugin Manifest" in h for h in headings)

    def test_has_installation_section(self) -> None:
        """docs/plugin.md must have an 'Installation' section."""
        headings = self._get_headings()
        assert any("Installation" in h for h in headings)

    def test_has_mcp_configuration_section(self) -> None:
        """docs/plugin.md must have an 'MCP Configuration' section."""
        headings = self._get_headings()
        assert any("MCP Configuration" in h for h in headings)

    def test_has_available_skills_section(self) -> None:
        """docs/plugin.md must have an 'Available Skills' section."""
        headings = self._get_headings()
        assert any("Available Skills" in h for h in headings)

    def test_has_mcp_unavailability_section(self) -> None:
        """docs/plugin.md must have an 'MCP Unavailability' section."""
        headings = self._get_headings()
        assert any("MCP Unavailability" in h for h in headings)

    def test_has_troubleshooting_section(self) -> None:
        """docs/plugin.md must have a 'Troubleshooting' section."""
        headings = self._get_headings()
        assert any("Troubleshooting" in h for h in headings)


# ---------------------------------------------------------------------------
# docs/plugin.md — skill coverage
# ---------------------------------------------------------------------------


class TestPluginDocumentationSkillCoverage:
    def test_all_six_skill_triggers_mentioned(self) -> None:
        """docs/plugin.md must mention all six skill command triggers."""
        content = load_plugin_doc()
        for skill in ("/distill", "/recall", "/pour", "/bookmark", "/minutes", "/classify"):
            assert skill in content, f"Skill trigger '{skill}' not mentioned in plugin.md"

    def test_available_skills_table_contains_all_skills(self) -> None:
        """The Available Skills table must list all six skill names."""
        content = load_plugin_doc()
        for skill_name in EXPECTED_SKILL_NAMES:
            assert skill_name in content.lower(), (
                f"Skill '{skill_name}' not found in plugin.md"
            )

    def test_distill_trigger_phrases_documented(self) -> None:
        """docs/plugin.md must document trigger phrases for /distill."""
        content = load_plugin_doc()
        assert "capture this" in content or "save knowledge" in content

    def test_recall_trigger_phrases_documented(self) -> None:
        """docs/plugin.md must document trigger phrases for /recall."""
        content = load_plugin_doc()
        assert "search knowledge" in content or "what do we know about" in content

    def test_bookmark_trigger_phrases_documented(self) -> None:
        """docs/plugin.md must document trigger phrases for /bookmark."""
        content = load_plugin_doc()
        assert "bookmark" in content.lower()

    def test_minutes_trigger_phrases_documented(self) -> None:
        """docs/plugin.md must document trigger phrases for /minutes."""
        content = load_plugin_doc()
        assert "meeting notes" in content or "capture meeting" in content


# ---------------------------------------------------------------------------
# docs/plugin.md — content and references
# ---------------------------------------------------------------------------


class TestPluginDocumentationContent:
    def test_references_plugin_json(self) -> None:
        """docs/plugin.md must reference plugin.json."""
        content = load_plugin_doc()
        assert "plugin.json" in content

    def test_mentions_github_repository(self) -> None:
        """docs/plugin.md must mention the GitHub repository URL."""
        content = load_plugin_doc()
        assert "github.com/norrietaylor/distillery" in content

    def test_contains_bash_code_blocks(self) -> None:
        """docs/plugin.md must contain at least one bash code block."""
        content = load_plugin_doc()
        assert "```bash" in content

    def test_contains_json_code_blocks(self) -> None:
        """docs/plugin.md must contain at least one JSON code block."""
        content = load_plugin_doc()
        assert "```json" in content

    def test_contains_yaml_code_block(self) -> None:
        """docs/plugin.md must contain a YAML code block for the config example."""
        content = load_plugin_doc()
        assert "```yaml" in content

    def test_mentions_mcp_server_verification(self) -> None:
        """docs/plugin.md must describe how to verify the MCP server is running."""
        content = load_plugin_doc()
        assert "distillery_status" in content or "distillery health" in content

    def test_mentions_claude_plugin_install_command(self) -> None:
        """docs/plugin.md must show the 'claude plugin install' command."""
        content = load_plugin_doc()
        assert "claude plugin install" in content

    def test_mentions_pip_install(self) -> None:
        """docs/plugin.md must include pip install instructions."""
        content = load_plugin_doc()
        assert "pip install distillery" in content

    def test_mentions_jina_api_key(self) -> None:
        """docs/plugin.md must mention the JINA_API_KEY environment variable."""
        content = load_plugin_doc()
        assert "JINA_API_KEY" in content

    def test_mentions_both_transport_options(self) -> None:
        """docs/plugin.md must describe both stdio and HTTP transport options."""
        content = load_plugin_doc()
        assert "stdio" in content.lower() or "Transport A" in content
        assert "http" in content.lower() or "Transport B" in content

    def test_hosted_url_present(self) -> None:
        """docs/plugin.md must include the hosted MCP server URL."""
        content = load_plugin_doc()
        assert "fastmcp.app" in content

    def test_mcp_unavailability_warning_message_present(self) -> None:
        """docs/plugin.md must include the MCP unavailability warning text."""
        content = load_plugin_doc()
        assert "Warning: Distillery MCP Server Not Available" in content

    def test_further_reading_section_has_links(self) -> None:
        """docs/plugin.md must contain links in the Further Reading section."""
        content = load_plugin_doc()
        assert "Further Reading" in content
        # At least one markdown link must follow
        further_idx = content.index("Further Reading")
        after_heading = content[further_idx:]
        assert re.search(r"\[.+?\]\(.+?\)", after_heading), (
            "No markdown links found in Further Reading section"
        )

    def test_mcp_servers_settings_json_snippet_present(self) -> None:
        """docs/plugin.md must show a mcpServers settings.json configuration snippet."""
        content = load_plugin_doc()
        assert "mcpServers" in content
        assert "settings.json" in content
