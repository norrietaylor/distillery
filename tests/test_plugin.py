"""Tests for the Claude Code plugin manifest (.claude-plugin/plugin.json) and plugin documentation (docs/plugin.md).

Covers:
  - .claude-plugin/plugin.json is valid JSON and contains all required top-level fields
  - Plugin metadata (name, version, author, homepage, repository, keywords)
  - Skills directory path and SKILL.md auto-discovery
  - MCP server configuration: presence, command, env
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
PLUGIN_JSON_PATH = REPO_ROOT / ".claude-plugin" / "plugin.json"
PLUGIN_DOC_PATH = REPO_ROOT / "docs" / "plugin.md"

EXPECTED_SKILL_NAMES = {"distill", "recall", "pour", "bookmark", "minutes", "classify", "watch", "radar", "tune", "setup"}


def load_plugin_manifest() -> dict:  # type: ignore[type-arg]
    """Load and parse .claude-plugin/plugin.json from the repository root."""
    return json.loads(PLUGIN_JSON_PATH.read_text(encoding="utf-8"))


def load_plugin_doc() -> str:
    """Load docs/plugin.md from the repository root."""
    return PLUGIN_DOC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# plugin.json — file-level tests
# ---------------------------------------------------------------------------


class TestPluginManifestFile:
    def test_plugin_json_exists(self) -> None:
        """.claude-plugin/plugin.json must exist."""
        assert PLUGIN_JSON_PATH.exists(), f".claude-plugin/plugin.json not found at {PLUGIN_JSON_PATH}"

    def test_plugin_json_is_valid_json(self) -> None:
        """.claude-plugin/plugin.json must be parseable as valid JSON."""
        content = PLUGIN_JSON_PATH.read_text(encoding="utf-8")
        manifest = json.loads(content)  # raises json.JSONDecodeError on failure
        assert isinstance(manifest, dict)

    def test_plugin_json_is_non_empty(self) -> None:
        """.claude-plugin/plugin.json must not be empty."""
        manifest = load_plugin_manifest()
        assert len(manifest) > 0


# ---------------------------------------------------------------------------
# plugin.json — top-level metadata fields
# ---------------------------------------------------------------------------


class TestPluginManifestMetadata:
    def test_no_schema_field(self) -> None:
        """$schema field must not be present (not supported by Claude Code plugin schema)."""
        manifest = load_plugin_manifest()
        assert "$schema" not in manifest

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
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"version '{version}' is not semver"

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

    def test_author_is_object(self) -> None:
        """author field must be an object with a 'name' key."""
        manifest = load_plugin_manifest()
        assert isinstance(manifest["author"], dict)
        assert "name" in manifest["author"]

    def test_author_name_is_norrietaylor(self) -> None:
        """author.name must be 'norrietaylor'."""
        manifest = load_plugin_manifest()
        assert manifest["author"]["name"] == "norrietaylor"

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
            "name", "version", "description",
            "author", "homepage", "repository", "keywords",
            "skills", "mcpServers",
        }
        for key in required_keys:
            assert key in manifest, f"Required key '{key}' missing from .claude-plugin/plugin.json"


# ---------------------------------------------------------------------------
# .claude-plugin/plugin.json — skills directory
# ---------------------------------------------------------------------------


class TestPluginSkills:
    def test_skills_is_a_directory_path(self) -> None:
        """skills field must be a relative directory path string."""
        manifest = load_plugin_manifest()
        assert isinstance(manifest["skills"], str)
        assert manifest["skills"].startswith("./")

    def test_skills_directory_value(self) -> None:
        """skills must point to './.claude/skills/'."""
        manifest = load_plugin_manifest()
        assert manifest["skills"] == "./.claude/skills/"

    def test_skills_directory_exists(self) -> None:
        """The skills directory referenced in the manifest must exist."""
        manifest = load_plugin_manifest()
        skills_path = manifest["skills"].removeprefix("./")
        skills_dir = REPO_ROOT / skills_path
        assert skills_dir.exists(), f"Skills directory not found at {skills_dir}"
        assert skills_dir.is_dir(), f"{skills_dir} is not a directory"

    def test_all_expected_skill_subdirectories_exist(self) -> None:
        """Each expected skill must have a subdirectory with a SKILL.md file."""
        manifest = load_plugin_manifest()
        skills_path = manifest["skills"].removeprefix("./")
        skills_dir = REPO_ROOT / skills_path
        for skill_name in EXPECTED_SKILL_NAMES:
            skill_file = skills_dir / skill_name / "SKILL.md"
            assert skill_file.exists(), f"Skill file missing: {skill_file}"

    def test_skill_files_have_yaml_frontmatter(self) -> None:
        """Each SKILL.md must start with YAML frontmatter."""
        manifest = load_plugin_manifest()
        skills_path = manifest["skills"].removeprefix("./")
        skills_dir = REPO_ROOT / skills_path
        for skill_name in EXPECTED_SKILL_NAMES:
            skill_file = skills_dir / skill_name / "SKILL.md"
            assert skill_file.read_text(encoding="utf-8").lstrip().startswith("---"), (
                f"Skill file missing YAML frontmatter: {skill_file}"
            )

    def test_exactly_ten_skill_subdirectories(self) -> None:
        """The skills directory must contain exactly ten skill subdirectories with SKILL.md files."""
        manifest = load_plugin_manifest()
        skills_path = manifest["skills"].removeprefix("./")
        skills_dir = REPO_ROOT / skills_path
        found = {
            d.name for d in skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        }
        assert found == EXPECTED_SKILL_NAMES


# ---------------------------------------------------------------------------
# .claude-plugin/plugin.json — MCP server configuration
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

    def test_distillery_server_has_type_http(self) -> None:
        """The distillery server must use HTTP transport."""
        manifest = load_plugin_manifest()
        server = manifest["mcpServers"]["distillery"]
        assert server.get("type") == "http"

    def test_distillery_server_has_url(self) -> None:
        """The distillery server must have a 'url' field."""
        manifest = load_plugin_manifest()
        server = manifest["mcpServers"]["distillery"]
        assert "url" in server

    def test_distillery_server_url_is_fly_endpoint(self) -> None:
        """The distillery server URL must point to the Fly.io hosted endpoint."""
        manifest = load_plugin_manifest()
        server = manifest["mcpServers"]["distillery"]
        assert server["url"] == "https://distillery-mcp.fly.dev/mcp"

    def test_distillery_server_no_unsupported_fields(self) -> None:
        """The distillery server must not contain fields unsupported by the plugin schema."""
        manifest = load_plugin_manifest()
        server = manifest["mcpServers"]["distillery"]
        unsupported = {"required", "description", "setup", "transports", "default_transport"}
        found = unsupported & set(server.keys())
        assert not found, f"Unsupported fields in mcpServers.distillery: {found}"


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
        first_non_empty = next(
            (line for line in content.splitlines() if line.strip()), None
        )
        assert first_non_empty is not None and first_non_empty.startswith("# "), (
            "docs/plugin.md has no H1 heading"
        )


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

    def test_contains_json_settings_snippet(self) -> None:
        """docs/plugin.md must contain a JSON settings snippet for MCP configuration."""
        content = load_plugin_doc()
        assert '"mcpServers"' in content

    def test_mentions_mcp_server_verification(self) -> None:
        """docs/plugin.md must describe how to verify the MCP server is running."""
        content = load_plugin_doc()
        assert "distillery_status" in content or "distillery health" in content

    def test_mentions_claude_plugin_install_command(self) -> None:
        """docs/plugin.md must show the 'claude plugin install' command."""
        content = load_plugin_doc()
        assert "claude plugin install" in content

    def test_mentions_marketplace_add_command(self) -> None:
        """docs/plugin.md must show the 'claude plugin marketplace add' command."""
        content = load_plugin_doc()
        assert "claude plugin marketplace add" in content

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
        assert "stdio" in content.lower(), "docs/plugin.md must mention stdio transport"
        assert "http" in content.lower(), "docs/plugin.md must mention http transport"

    def test_hosted_url_present(self) -> None:
        """docs/plugin.md must include the hosted MCP server URL."""
        content = load_plugin_doc()
        assert "distillery-mcp.fly.dev" in content

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
