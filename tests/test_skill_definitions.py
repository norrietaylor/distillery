"""Tests for SKILL.md definitions and shared skill conventions.

Covers changes introduced in v0.4.0 / API consolidation PR:
  - No deprecated MCP tools in any skill's allowed-tools list
  - No deprecated scheduling tools (CronCreate, CronList, CronDelete, RemoteTrigger)
  - Context-fork skills carry the mandatory safety rules
  - CONVENTIONS.md health check uses distillery_list, not distillery_metrics
  - CONVENTIONS.md forked-context section lists the correct skills
  - skills/README.md documents 12 tools and the consolidated tool surface
  - gh-sync skill uses output_mode="summary" (not the removed "metadata")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
CONVENTIONS_MD = SKILLS_DIR / "CONVENTIONS.md"
README_MD = SKILLS_DIR / "README.md"

# ---------------------------------------------------------------------------
# Constants — deprecated / removed items
# ---------------------------------------------------------------------------

# MCP tools that were removed in v0.4.0 (absorbed into list or moved to webhooks)
DEPRECATED_MCP_TOOLS = {
    "distillery_metrics",
    "distillery_stale",
    "distillery_aggregate",
    "distillery_tag_tree",
    "distillery_interests",
    "distillery_type_schemas",
    "distillery_poll",
    "distillery_rescore",
}

# Scheduling primitives deprecated in v0.4.0 (replaced by Claude Code routines)
DEPRECATED_SCHEDULING_TOOLS = {
    "CronCreate",
    "CronList",
    "CronDelete",
    "RemoteTrigger",
}

# Skills that use context: fork (must carry safety rules)
FORK_CONTEXT_SKILLS = {
    "pour",
    "radar",
    "digest",
    "investigate",
    "briefing",
    "gh-sync",
}

ALL_SKILLS = {
    "distill",
    "recall",
    "pour",
    "bookmark",
    "minutes",
    "classify",
    "watch",
    "radar",
    "tune",
    "setup",
    "digest",
    "gh-sync",
    "investigate",
    "briefing",
}

# Mandatory safety rules for context: fork skills (exact text substrings)
FORK_SAFETY_RULES = [
    "NEVER use Bash, Python, or any tool not listed in allowed-tools",
    "If an MCP tool call fails, report the error to the user and STOP.",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_frontmatter(skill_name: str) -> dict:  # type: ignore[type-arg]
    """Parse the YAML frontmatter from a skill's SKILL.md file."""
    skill_file = SKILLS_DIR / skill_name / "SKILL.md"
    content = skill_file.read_text(encoding="utf-8")
    # Extract content between first and second ---
    if not content.startswith("---"):
        return {}
    end = content.index("---", 3)
    raw_yaml = content[3:end].strip()
    result = yaml.safe_load(raw_yaml)
    return result if isinstance(result, dict) else {}


def _get_allowed_tools(skill_name: str) -> list[str]:
    """Return the allowed-tools list from a skill's YAML frontmatter."""
    fm = _parse_frontmatter(skill_name)
    return fm.get("allowed-tools", [])


def _get_skill_body(skill_name: str) -> str:
    """Return the body (post-frontmatter) of a SKILL.md file."""
    skill_file = SKILLS_DIR / skill_name / "SKILL.md"
    content = skill_file.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return content
    end = content.index("---", 3)
    return content[end + 3:]


def _iter_all_skills() -> Iterator[str]:
    return iter(ALL_SKILLS)


# ---------------------------------------------------------------------------
# Deprecated MCP tool removal
# ---------------------------------------------------------------------------


class TestNoDeprecatedMCPTools:
    """No skill should reference deprecated MCP tools in its allowed-tools list."""

    def _extract_tool_names(self, tools: list[str]) -> list[str]:
        """Extract the bare tool name from patterns like 'mcp__*__distillery_foo'."""
        extracted = []
        for tool in tools:
            # Handle mcp__*__distillery_foo patterns
            if "__" in tool:
                parts = tool.split("__")
                extracted.append(parts[-1])
            else:
                extracted.append(tool)
        return extracted

    def test_no_deprecated_tools_in_any_skill(self) -> None:
        """No skill's allowed-tools must reference any v0.4.0-deprecated MCP tool."""
        violations: list[str] = []
        for skill in _iter_all_skills():
            raw_tools = _get_allowed_tools(skill)
            bare_names = self._extract_tool_names(raw_tools)
            for name in bare_names:
                if name in DEPRECATED_MCP_TOOLS:
                    violations.append(f"  {skill}: {name!r}")
        assert not violations, (
            "Deprecated MCP tools found in skill allowed-tools:\n"
            + "\n".join(violations)
        )

    @pytest.mark.parametrize("skill", sorted(ALL_SKILLS))
    def test_skill_has_no_distillery_metrics(self, skill: str) -> None:
        """distillery_metrics was removed in v0.4.0; must not appear in allowed-tools."""
        raw_tools = _get_allowed_tools(skill)
        for tool in raw_tools:
            assert "distillery_metrics" not in tool, (
                f"Skill '{skill}' still references 'distillery_metrics' in allowed-tools"
            )

    @pytest.mark.parametrize("skill", sorted(ALL_SKILLS))
    def test_skill_has_no_distillery_stale(self, skill: str) -> None:
        """distillery_stale was removed in v0.4.0; must not appear in allowed-tools."""
        raw_tools = _get_allowed_tools(skill)
        for tool in raw_tools:
            assert "distillery_stale" not in tool, (
                f"Skill '{skill}' still references 'distillery_stale' in allowed-tools"
            )

    @pytest.mark.parametrize("skill", sorted(ALL_SKILLS))
    def test_skill_has_no_distillery_aggregate(self, skill: str) -> None:
        """distillery_aggregate was removed in v0.4.0; must not appear in allowed-tools."""
        raw_tools = _get_allowed_tools(skill)
        for tool in raw_tools:
            assert "distillery_aggregate" not in tool, (
                f"Skill '{skill}' still references 'distillery_aggregate' in allowed-tools"
            )

    @pytest.mark.parametrize("skill", sorted(ALL_SKILLS))
    def test_skill_has_no_distillery_tag_tree(self, skill: str) -> None:
        """distillery_tag_tree was removed in v0.4.0; must not appear in allowed-tools."""
        raw_tools = _get_allowed_tools(skill)
        for tool in raw_tools:
            assert "distillery_tag_tree" not in tool, (
                f"Skill '{skill}' still references 'distillery_tag_tree' in allowed-tools"
            )

    @pytest.mark.parametrize("skill", sorted(ALL_SKILLS))
    def test_skill_has_no_distillery_interests(self, skill: str) -> None:
        """distillery_interests was removed in v0.4.0; must not appear in allowed-tools."""
        raw_tools = _get_allowed_tools(skill)
        for tool in raw_tools:
            assert "distillery_interests" not in tool, (
                f"Skill '{skill}' still references 'distillery_interests' in allowed-tools"
            )

    @pytest.mark.parametrize("skill", sorted(ALL_SKILLS))
    def test_skill_has_no_distillery_type_schemas(self, skill: str) -> None:
        """distillery_type_schemas was moved to MCP resource in v0.4.0."""
        raw_tools = _get_allowed_tools(skill)
        for tool in raw_tools:
            assert "distillery_type_schemas" not in tool, (
                f"Skill '{skill}' still references 'distillery_type_schemas' in allowed-tools"
            )

    @pytest.mark.parametrize("skill", sorted(ALL_SKILLS))
    def test_skill_has_no_distillery_poll(self, skill: str) -> None:
        """distillery_poll was moved to webhook-only in v0.4.0; must not appear in allowed-tools."""
        raw_tools = _get_allowed_tools(skill)
        for tool in raw_tools:
            assert "distillery_poll" not in tool, (
                f"Skill '{skill}' still references 'distillery_poll' in allowed-tools"
            )

    @pytest.mark.parametrize("skill", sorted(ALL_SKILLS))
    def test_skill_has_no_distillery_rescore(self, skill: str) -> None:
        """distillery_rescore was moved to webhook-only in v0.4.0; must not appear in allowed-tools."""
        raw_tools = _get_allowed_tools(skill)
        for tool in raw_tools:
            assert "distillery_rescore" not in tool, (
                f"Skill '{skill}' still references 'distillery_rescore' in allowed-tools"
            )


# ---------------------------------------------------------------------------
# Deprecated scheduling tool removal
# ---------------------------------------------------------------------------


class TestNoDeprecatedSchedulingTools:
    """Scheduling was migrated from CronCreate/RemoteTrigger to Claude Code routines."""

    @pytest.mark.parametrize("skill", sorted(ALL_SKILLS))
    def test_skill_has_no_croncreate(self, skill: str) -> None:
        """CronCreate is deprecated; must not appear in any skill's allowed-tools."""
        raw_tools = _get_allowed_tools(skill)
        for tool in raw_tools:
            assert "CronCreate" not in tool, (
                f"Skill '{skill}' still references 'CronCreate' in allowed-tools"
            )

    @pytest.mark.parametrize("skill", sorted(ALL_SKILLS))
    def test_skill_has_no_cronlist(self, skill: str) -> None:
        """CronList is deprecated; must not appear in any skill's allowed-tools."""
        raw_tools = _get_allowed_tools(skill)
        for tool in raw_tools:
            assert "CronList" not in tool, (
                f"Skill '{skill}' still references 'CronList' in allowed-tools"
            )

    @pytest.mark.parametrize("skill", sorted(ALL_SKILLS))
    def test_skill_has_no_crondelete(self, skill: str) -> None:
        """CronDelete is deprecated; must not appear in any skill's allowed-tools."""
        raw_tools = _get_allowed_tools(skill)
        for tool in raw_tools:
            assert "CronDelete" not in tool, (
                f"Skill '{skill}' still references 'CronDelete' in allowed-tools"
            )

    @pytest.mark.parametrize("skill", sorted(ALL_SKILLS))
    def test_skill_has_no_remotetrigger(self, skill: str) -> None:
        """RemoteTrigger is deprecated; must not appear in any skill's allowed-tools."""
        raw_tools = _get_allowed_tools(skill)
        for tool in raw_tools:
            assert "RemoteTrigger" not in tool, (
                f"Skill '{skill}' still references 'RemoteTrigger' in allowed-tools"
            )

    def test_watch_skill_has_no_scheduling_tools(self) -> None:
        """The /watch skill specifically had CronCreate/CronList/CronDelete/RemoteTrigger removed."""
        raw_tools = _get_allowed_tools("watch")
        all_tools_str = " ".join(raw_tools)
        for deprecated in DEPRECATED_SCHEDULING_TOOLS:
            assert deprecated not in all_tools_str, (
                f"/watch still references deprecated scheduling tool '{deprecated}'"
            )

    def test_setup_skill_has_no_scheduling_tools(self) -> None:
        """The /setup skill had CronCreate/RemoteTrigger removed in favour of routines."""
        raw_tools = _get_allowed_tools("setup")
        all_tools_str = " ".join(raw_tools)
        for deprecated in DEPRECATED_SCHEDULING_TOOLS:
            assert deprecated not in all_tools_str, (
                f"/setup still references deprecated scheduling tool '{deprecated}'"
            )


# ---------------------------------------------------------------------------
# Setup skill: correct allowed-tools for v0.4.0
# ---------------------------------------------------------------------------


class TestSetupSkillTools:
    def test_setup_has_distillery_list(self) -> None:
        """setup must include distillery_list (for the MCP health check)."""
        raw_tools = _get_allowed_tools("setup")
        assert any("distillery_list" in t for t in raw_tools), (
            "/setup must include distillery_list in allowed-tools"
        )

    def test_setup_has_distillery_watch(self) -> None:
        """setup must include distillery_watch (for listing sources in Step 3)."""
        raw_tools = _get_allowed_tools("setup")
        assert any("distillery_watch" in t for t in raw_tools), (
            "/setup must include distillery_watch in allowed-tools"
        )

    def test_setup_has_distillery_configure(self) -> None:
        """setup must include distillery_configure (for transport configuration)."""
        raw_tools = _get_allowed_tools("setup")
        assert any("distillery_configure" in t for t in raw_tools), (
            "/setup must include distillery_configure in allowed-tools"
        )


# ---------------------------------------------------------------------------
# Context-fork skills: mandatory safety rules
# ---------------------------------------------------------------------------


class TestForkContextSafetyRules:
    """Context-fork skills must declare the two mandatory safety rules at top of Rules section."""

    def _get_rules_section(self, skill_name: str) -> str:
        """Return the text of the ## Rules section from a skill body."""
        body = _get_skill_body(skill_name)
        # Find the ## Rules section
        match = re.search(r"^##\s+Rules\b(.+?)(?=^##|\Z)", body, re.MULTILINE | re.DOTALL)
        if not match:
            return ""
        return match.group(1)

    @pytest.mark.parametrize("skill", sorted(FORK_CONTEXT_SKILLS))
    def test_fork_skill_has_context_fork(self, skill: str) -> None:
        """Each skill that should have context: fork must declare it in frontmatter."""
        fm = _parse_frontmatter(skill)
        assert fm.get("context") == "fork", (
            f"Skill '{skill}' expected context: fork but got {fm.get('context')!r}"
        )

    @pytest.mark.parametrize("skill", sorted(FORK_CONTEXT_SKILLS))
    def test_fork_skill_has_never_use_bash_rule(self, skill: str) -> None:
        """Fork skills must include the 'NEVER use Bash' safety rule at top of ## Rules."""
        rules = self._get_rules_section(skill)
        assert "NEVER use Bash, Python, or any tool not listed in allowed-tools" in rules, (
            f"Skill '{skill}' (context: fork) is missing the 'NEVER use Bash' safety rule"
        )

    @pytest.mark.parametrize("skill", sorted(FORK_CONTEXT_SKILLS))
    def test_fork_skill_has_stop_on_failure_rule(self, skill: str) -> None:
        """Fork skills must include the 'STOP on MCP failure' safety rule at top of ## Rules."""
        rules = self._get_rules_section(skill)
        assert "If an MCP tool call fails, report the error to the user and STOP." in rules, (
            f"Skill '{skill}' (context: fork) is missing the 'STOP on failure' safety rule"
        )

    def test_non_fork_skills_do_not_have_fork_context(self) -> None:
        """Skills that are NOT in FORK_CONTEXT_SKILLS must not accidentally declare context: fork."""
        non_fork_skills = ALL_SKILLS - FORK_CONTEXT_SKILLS
        for skill in non_fork_skills:
            fm = _parse_frontmatter(skill)
            assert fm.get("context") != "fork", (
                f"Skill '{skill}' unexpectedly declares context: fork"
            )


# ---------------------------------------------------------------------------
# CONVENTIONS.md: health check and forked context
# ---------------------------------------------------------------------------


class TestConventionsDoc:
    def _read_conventions(self) -> str:
        return CONVENTIONS_MD.read_text(encoding="utf-8")

    def test_conventions_exists(self) -> None:
        """skills/CONVENTIONS.md must exist."""
        assert CONVENTIONS_MD.exists()

    def test_health_check_uses_distillery_list(self) -> None:
        """CONVENTIONS.md MCP health check must use distillery_list(limit=1).

        In v0.4.0, distillery_metrics was removed; the health check was updated
        to use distillery_list(limit=1) instead.
        """
        content = self._read_conventions()
        assert "distillery_list(limit=1)" in content, (
            "CONVENTIONS.md must reference distillery_list(limit=1) as the MCP health check"
        )

    def test_health_check_does_not_use_distillery_metrics(self) -> None:
        """CONVENTIONS.md must not instruct skills to call distillery_metrics for the health check."""
        content = self._read_conventions()
        # distillery_metrics should NOT appear in the MCP Health Check section
        # Find the MCP Health Check section
        match = re.search(
            r"## MCP Health Check(.+?)(?=^##|\Z)",
            content,
            re.MULTILINE | re.DOTALL,
        )
        if match:
            health_check_section = match.group(1)
            assert "distillery_metrics" not in health_check_section, (
                "CONVENTIONS.md MCP Health Check section still references distillery_metrics"
            )

    def test_forked_context_section_exists(self) -> None:
        """CONVENTIONS.md must have a 'Forked Context Constraints' section (added v0.4.0)."""
        content = self._read_conventions()
        assert "## Forked Context Constraints" in content, (
            "CONVENTIONS.md is missing the 'Forked Context Constraints' section"
        )

    def test_forked_context_lists_all_fork_skills(self) -> None:
        """Forked Context Constraints section must list all context-fork skills."""
        content = self._read_conventions()
        match = re.search(
            r"## Forked Context Constraints(.+?)(?=^##|\Z)",
            content,
            re.MULTILINE | re.DOTALL,
        )
        assert match, "Forked Context Constraints section not found"
        section = match.group(1)
        # Each fork skill must be mentioned (as /skill-name or skill-name)
        for skill in FORK_CONTEXT_SKILLS:
            skill_trigger = f"/{skill}"
            assert skill_trigger in section or skill in section, (
                f"Forked Context Constraints section missing '{skill_trigger}'"
            )

    def test_forked_context_never_bash_rule(self) -> None:
        """Forked Context Constraints section must specify the 'NEVER use Bash' rule."""
        content = self._read_conventions()
        match = re.search(
            r"## Forked Context Constraints(.+?)(?=^##|\Z)",
            content,
            re.MULTILINE | re.DOTALL,
        )
        assert match
        section = match.group(1)
        assert "NEVER use Bash" in section, (
            "Forked Context Constraints section missing 'NEVER use Bash' rule"
        )

    def test_skills_registry_uses_distillery_list_for_pour(self) -> None:
        """CONVENTIONS.md skills registry must show /pour using distillery_list (not tag_tree)."""
        content = self._read_conventions()
        # Match the full table row for /pour (table rows end at newline)
        pour_match = re.search(r"^\|[^|]*`/pour`[^|]*\|.*$", content, re.MULTILINE)
        assert pour_match, "/pour row not found in skills registry"
        pour_row = pour_match.group(0)
        assert "distillery_list" in pour_row, (
            "/pour in CONVENTIONS.md skills registry must reference distillery_list"
        )
        assert "distillery_tag_tree" not in pour_row, (
            "/pour in CONVENTIONS.md skills registry must not reference distillery_tag_tree"
        )

    def test_skills_registry_uses_distillery_configure_for_tune(self) -> None:
        """CONVENTIONS.md skills registry must show /tune using distillery_configure."""
        content = self._read_conventions()
        tune_match = re.search(r"^\|[^|]*`/tune`[^|]*\|.*$", content, re.MULTILINE)
        assert tune_match, "/tune row not found in skills registry"
        tune_row = tune_match.group(0)
        assert "distillery_configure" in tune_row, (
            "/tune in CONVENTIONS.md skills registry must reference distillery_configure"
        )
        assert "distillery_metrics" not in tune_row, (
            "/tune in CONVENTIONS.md skills registry must not reference distillery_metrics"
        )

    def test_watch_skill_registry_mentions_routines(self) -> None:
        """CONVENTIONS.md registry for /watch must mention 'routines' (not CronCreate)."""
        content = self._read_conventions()
        watch_match = re.search(r"^\|[^|]*`/watch`[^|]*\|.*$", content, re.MULTILINE)
        assert watch_match, "/watch row not found in skills registry"
        watch_row = watch_match.group(0)
        assert "routine" in watch_row.lower() or "Claude Code routines" in watch_row, (
            "/watch in CONVENTIONS.md skills registry must mention Claude Code routines"
        )
        assert "CronCreate" not in watch_row, (
            "/watch in CONVENTIONS.md skills registry must not reference CronCreate"
        )


# ---------------------------------------------------------------------------
# skills/README.md: tool surface documentation
# ---------------------------------------------------------------------------


class TestSkillsReadme:
    def _read_readme(self) -> str:
        return README_MD.read_text(encoding="utf-8")

    def test_readme_exists(self) -> None:
        """skills/README.md must exist."""
        assert README_MD.exists()

    def test_readme_reports_12_tools(self) -> None:
        """skills/README.md must state that the MCP server provides 12 tools (v0.4.0 count)."""
        content = self._read_readme()
        assert "12 tools" in content, (
            "skills/README.md must state '12 tools' (the v0.4.0 consolidated count)"
        )

    def test_readme_does_not_say_19_or_20_tools(self) -> None:
        """skills/README.md must NOT say '19 tools' or '20 tools' (pre-v0.4.0 counts)."""
        content = self._read_readme()
        assert "19 tools" not in content, (
            "skills/README.md still says '19 tools' — should be '12 tools'"
        )
        assert "20 tools" not in content, (
            "skills/README.md still says '20 tools' — should be '12 tools'"
        )

    def test_readme_documents_webhook_endpoints(self) -> None:
        """skills/README.md must document the webhook-only endpoints."""
        content = self._read_readme()
        assert "/hooks/poll" in content or "hooks/poll" in content, (
            "skills/README.md missing webhook endpoint /hooks/poll"
        )
        assert "/hooks/rescore" in content or "hooks/rescore" in content, (
            "skills/README.md missing webhook endpoint /hooks/rescore"
        )
        assert "/hooks/classify-batch" in content or "classify-batch" in content, (
            "skills/README.md missing webhook endpoint /hooks/classify-batch"
        )

    def test_readme_health_check_uses_distillery_list(self) -> None:
        """skills/README.md debugging section must recommend distillery_list(limit=1)."""
        content = self._read_readme()
        assert "distillery_list(limit=1)" in content, (
            "skills/README.md debugging section must recommend distillery_list(limit=1)"
        )

    def test_readme_does_not_reference_distillery_metrics_for_health(self) -> None:
        """skills/README.md must not recommend distillery_metrics for the health check."""
        content = self._read_readme()
        # Look specifically in the Debugging section
        debug_match = re.search(
            r"## Debugging(.+?)(?=^##|\Z)",
            content,
            re.MULTILINE | re.DOTALL,
        )
        if debug_match:
            debug_section = debug_match.group(1)
            assert "distillery_metrics" not in debug_section, (
                "skills/README.md Debugging section still mentions distillery_metrics"
            )

    def test_readme_lists_distillery_watch_as_feed_tool(self) -> None:
        """skills/README.md must list distillery_watch under Feeds."""
        content = self._read_readme()
        assert "distillery_watch" in content

    def test_readme_lists_distillery_configure_as_config_tool(self) -> None:
        """skills/README.md must list distillery_configure under Configuration."""
        content = self._read_readme()
        assert "distillery_configure" in content

    def test_readme_does_not_list_removed_tools(self) -> None:
        """skills/README.md tool surface section must not list removed tools."""
        content = self._read_readme()
        # Find the MCP Tools Available section
        tools_match = re.search(
            r"## MCP Tools Available(.+?)(?=^##|\Z)",
            content,
            re.MULTILINE | re.DOTALL,
        )
        if tools_match:
            tools_section = tools_match.group(1)
            for removed_tool in DEPRECATED_MCP_TOOLS:
                assert removed_tool not in tools_section, (
                    f"skills/README.md MCP Tools section still lists removed tool '{removed_tool}'"
                )


# ---------------------------------------------------------------------------
# gh-sync skill: output_mode changed from "metadata" to "summary"
# ---------------------------------------------------------------------------


class TestGhSyncSkill:
    def test_gh_sync_does_not_use_output_mode_metadata(self) -> None:
        """gh-sync SKILL.md must not use output_mode='metadata' (removed in v0.4.0).

        In v0.4.0, output_mode='metadata' was renamed/removed; gh-sync must use
        output_mode='summary' instead.
        """
        body = _get_skill_body("gh-sync")
        assert 'output_mode="metadata"' not in body, (
            "gh-sync SKILL.md still uses output_mode='metadata' which was removed in v0.4.0; "
            "use output_mode='summary' instead"
        )
        assert "output_mode='metadata'" not in body, (
            "gh-sync SKILL.md still uses output_mode='metadata' (single-quote form)"
        )

    def test_gh_sync_uses_output_mode_summary(self) -> None:
        """gh-sync SKILL.md must use output_mode='summary' when listing existing entries."""
        body = _get_skill_body("gh-sync")
        assert "summary" in body, (
            "gh-sync SKILL.md must reference output_mode='summary'"
        )

    def test_gh_sync_label_normalisation_rule(self) -> None:
        """gh-sync SKILL.md must describe normalised label-to-tag conversion (not just 'lowercase')."""
        body = _get_skill_body("gh-sync")
        # v0.4.0 changed the label rule to include hyphens, collapsing, stripping
        assert "hyphen" in body.lower() or "hyphens" in body.lower(), (
            "gh-sync SKILL.md must describe hyphen-based label normalisation"
        )


# ---------------------------------------------------------------------------
# Radar skill: removed distillery_interests reference
# ---------------------------------------------------------------------------


class TestRadarSkill:
    def _read_radar_body(self) -> str:
        return _get_skill_body("radar")

    def test_radar_does_not_call_distillery_interests(self) -> None:
        """radar SKILL.md must not call distillery_interests (removed in v0.4.0)."""
        body = self._read_radar_body()
        assert "distillery_interests" not in body, (
            "radar SKILL.md still references distillery_interests which was removed in v0.4.0"
        )

    def test_radar_uses_distillery_list_for_interest_profile(self) -> None:
        """radar SKILL.md must use distillery_list(group_by='tags') for interest discovery."""
        body = self._read_radar_body()
        assert "distillery_list" in body, (
            "radar SKILL.md must use distillery_list to derive interest profile"
        )
        assert "group_by" in body, (
            "radar SKILL.md must use group_by parameter on distillery_list"
        )

    def test_radar_suggests_hooks_poll_for_feed_polling(self) -> None:
        """radar SKILL.md fallback must reference /hooks/poll (not distillery_poll)."""
        body = self._read_radar_body()
        # When no feed entries found, radar should mention /hooks/poll or /setup
        assert "hooks/poll" in body or "setup" in body, (
            "radar SKILL.md fallback must reference /hooks/poll or /setup for feed polling"
        )


# ---------------------------------------------------------------------------
# Briefing skill: replaced stale + aggregate with list extensions
# ---------------------------------------------------------------------------


class TestBriefingSkill:
    def _read_briefing_body(self) -> str:
        return _get_skill_body("briefing")

    def test_briefing_uses_stale_days_parameter(self) -> None:
        """briefing SKILL.md must use stale_days parameter on distillery_list."""
        body = self._read_briefing_body()
        assert "stale_days" in body, (
            "briefing SKILL.md must use stale_days parameter instead of distillery_stale"
        )

    def test_briefing_uses_group_by_author(self) -> None:
        """briefing SKILL.md must use group_by='author' for team-mode detection."""
        body = self._read_briefing_body()
        assert 'group_by="author"' in body or "group_by='author'" in body, (
            "briefing SKILL.md must use distillery_list(group_by='author') for team detection"
        )

    def test_briefing_does_not_call_distillery_stale(self) -> None:
        """briefing must not call distillery_stale (removed tool)."""
        body = self._read_briefing_body()
        assert "distillery_stale" not in body, (
            "briefing SKILL.md still calls distillery_stale which was removed in v0.4.0"
        )

    def test_briefing_does_not_call_distillery_aggregate(self) -> None:
        """briefing must not call distillery_aggregate (removed tool)."""
        body = self._read_briefing_body()
        assert "distillery_aggregate" not in body, (
            "briefing SKILL.md still calls distillery_aggregate which was removed in v0.4.0"
        )


# ---------------------------------------------------------------------------
# Digest skill: replaced aggregate + metrics with list extensions
# ---------------------------------------------------------------------------


class TestDigestSkill:
    def _read_digest_body(self) -> str:
        return _get_skill_body("digest")

    def test_digest_uses_group_by_author(self) -> None:
        """digest SKILL.md must use group_by='author' instead of distillery_aggregate."""
        body = self._read_digest_body()
        assert "group_by=" in body and "author" in body, (
            "digest SKILL.md must use distillery_list(group_by='author')"
        )

    def test_digest_does_not_call_distillery_aggregate(self) -> None:
        """digest must not call distillery_aggregate (removed tool)."""
        body = self._read_digest_body()
        assert "distillery_aggregate" not in body, (
            "digest SKILL.md still calls distillery_aggregate which was removed in v0.4.0"
        )

    def test_digest_does_not_call_distillery_metrics(self) -> None:
        """digest must not call distillery_metrics (removed tool)."""
        body = self._read_digest_body()
        assert "distillery_metrics" not in body, (
            "digest SKILL.md still calls distillery_metrics which was removed in v0.4.0"
        )


# ---------------------------------------------------------------------------
# Investigate skill: replaced tag_tree + metrics with list extensions
# ---------------------------------------------------------------------------


class TestInvestigateSkill:
    def _read_investigate_body(self) -> str:
        return _get_skill_body("investigate")

    def test_investigate_uses_group_by_tags(self) -> None:
        """investigate SKILL.md must use group_by='tags' instead of distillery_tag_tree."""
        body = self._read_investigate_body()
        assert "group_by" in body and "tags" in body, (
            "investigate SKILL.md must use distillery_list(group_by='tags')"
        )

    def test_investigate_does_not_call_distillery_tag_tree(self) -> None:
        """investigate must not call distillery_tag_tree (removed tool)."""
        body = self._read_investigate_body()
        assert "distillery_tag_tree" not in body, (
            "investigate SKILL.md still calls distillery_tag_tree which was removed in v0.4.0"
        )


# ---------------------------------------------------------------------------
# Pour skill: replaced tag_tree with list group_by
# ---------------------------------------------------------------------------


class TestPourSkill:
    def _read_pour_body(self) -> str:
        return _get_skill_body("pour")

    def test_pour_uses_group_by_tags(self) -> None:
        """pour SKILL.md must use group_by='tags' instead of distillery_tag_tree."""
        body = self._read_pour_body()
        assert "group_by" in body and "tags" in body, (
            "pour SKILL.md must use distillery_list(group_by='tags') for tag expansion"
        )

    def test_pour_does_not_call_distillery_tag_tree(self) -> None:
        """pour must not call distillery_tag_tree (removed tool)."""
        body = self._read_pour_body()
        assert "distillery_tag_tree" not in body, (
            "pour SKILL.md still calls distillery_tag_tree which was removed in v0.4.0"
        )