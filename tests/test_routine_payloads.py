"""Tests for skills/setup/references/routine-payloads.md.

This file is new in v0.4.0 and replaces the CronCreate-based scheduling
in cron-payloads.md. It documents the three Claude Code routines that
replace the deprecated CronCreate / GitHub Actions webhook scheduling.

Covers:
  - File exists and is non-empty
  - All three routine tiers are defined (4a, 4b, 4c)
  - Correct routine names used (distillery-feed-poll, distillery-stale-check,
    distillery-weekly-maintenance)
  - Each routine uses only current MCP tools (no removed tools)
  - Each routine has a schedule and prompt
  - Migration note references cron-payloads.md deprecation
  - cron-payloads.md carries a DEPRECATED notice
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
ROUTINE_PAYLOADS = SKILLS_DIR / "setup" / "references" / "routine-payloads.md"
CRON_PAYLOADS = SKILLS_DIR / "setup" / "references" / "cron-payloads.md"

# The three expected routine names from the spec
EXPECTED_ROUTINE_NAMES = [
    "distillery-feed-poll",
    "distillery-stale-check",
    "distillery-weekly-maintenance",
]

# MCP tools that must NOT appear in routine prompts (removed in v0.4.0)
REMOVED_MCP_TOOLS = [
    "distillery_metrics",
    "distillery_stale",
    "distillery_aggregate",
    "distillery_tag_tree",
    "distillery_interests",
    "distillery_type_schemas",
    "distillery_poll",
    "distillery_rescore",
]


# ---------------------------------------------------------------------------
# File existence
# ---------------------------------------------------------------------------


class TestRoutinePayloadsFileExists:
    def test_routine_payloads_file_exists(self) -> None:
        """skills/setup/references/routine-payloads.md must exist (new in v0.4.0)."""
        assert ROUTINE_PAYLOADS.exists(), (
            f"routine-payloads.md not found at {ROUTINE_PAYLOADS}"
        )

    def test_routine_payloads_is_non_empty(self) -> None:
        """routine-payloads.md must not be empty."""
        content = ROUTINE_PAYLOADS.read_text(encoding="utf-8")
        assert len(content.strip()) > 0

    def test_routine_payloads_starts_with_heading(self) -> None:
        """routine-payloads.md must start with a markdown heading."""
        content = ROUTINE_PAYLOADS.read_text(encoding="utf-8")
        first_non_empty = next(
            (line for line in content.splitlines() if line.strip()), None
        )
        assert first_non_empty is not None and first_non_empty.startswith("#"), (
            "routine-payloads.md must start with a markdown heading"
        )


# ---------------------------------------------------------------------------
# Three routine tiers
# ---------------------------------------------------------------------------


class TestRoutineTiers:
    def _content(self) -> str:
        return ROUTINE_PAYLOADS.read_text(encoding="utf-8")

    def test_has_hourly_section(self) -> None:
        """routine-payloads.md must document the hourly tier (4a)."""
        content = self._content()
        assert "Hourly" in content or "hourly" in content, (
            "routine-payloads.md is missing the Hourly (4a) tier"
        )

    def test_has_daily_section(self) -> None:
        """routine-payloads.md must document the daily tier (4b)."""
        content = self._content()
        assert "Daily" in content or "daily" in content, (
            "routine-payloads.md is missing the Daily (4b) tier"
        )

    def test_has_weekly_section(self) -> None:
        """routine-payloads.md must document the weekly tier (4c)."""
        content = self._content()
        assert "Weekly" in content or "weekly" in content, (
            "routine-payloads.md is missing the Weekly (4c) tier"
        )

    def test_has_4a_section_marker(self) -> None:
        """routine-payloads.md must have a section marker for 4a."""
        content = self._content()
        assert "4a" in content or "## 4a" in content or "##4a" in content, (
            "routine-payloads.md is missing a 4a section marker"
        )

    def test_has_4b_section_marker(self) -> None:
        """routine-payloads.md must have a section marker for 4b."""
        content = self._content()
        assert "4b" in content, (
            "routine-payloads.md is missing a 4b section marker"
        )

    def test_has_4c_section_marker(self) -> None:
        """routine-payloads.md must have a section marker for 4c."""
        content = self._content()
        assert "4c" in content, (
            "routine-payloads.md is missing a 4c section marker"
        )


# ---------------------------------------------------------------------------
# Correct routine names
# ---------------------------------------------------------------------------


class TestRoutineNames:
    def _content(self) -> str:
        return ROUTINE_PAYLOADS.read_text(encoding="utf-8")

    @pytest.mark.parametrize("name", EXPECTED_ROUTINE_NAMES)
    def test_routine_name_present(self, name: str) -> None:
        """Each expected Claude Code routine name must appear in routine-payloads.md."""
        content = self._content()
        assert name in content, (
            f"Routine name '{name}' not found in routine-payloads.md"
        )

    def test_feed_poll_routine_is_hourly(self) -> None:
        """distillery-feed-poll routine must be configured as hourly."""
        content = self._content()
        # Find the section around distillery-feed-poll
        idx = content.find("distillery-feed-poll")
        assert idx != -1
        surrounding = content[max(0, idx - 50) : idx + 300]
        assert "hour" in surrounding.lower(), (
            "distillery-feed-poll routine must specify hourly schedule"
        )

    def test_stale_check_routine_is_daily(self) -> None:
        """distillery-stale-check routine must be configured as daily."""
        content = self._content()
        idx = content.find("distillery-stale-check")
        assert idx != -1
        surrounding = content[max(0, idx - 50) : idx + 300]
        assert "daily" in surrounding.lower() or "Daily" in surrounding, (
            "distillery-stale-check routine must specify daily schedule"
        )

    def test_maintenance_routine_is_weekly(self) -> None:
        """distillery-weekly-maintenance routine must be configured as weekly."""
        content = self._content()
        idx = content.find("distillery-weekly-maintenance")
        assert idx != -1
        surrounding = content[max(0, idx - 50) : idx + 300]
        assert "weekly" in surrounding.lower() or "Weekly" in surrounding, (
            "distillery-weekly-maintenance routine must specify weekly schedule"
        )


# ---------------------------------------------------------------------------
# Routine prompts use current tools only
# ---------------------------------------------------------------------------


class TestRoutinePrompts:
    def _content(self) -> str:
        return ROUTINE_PAYLOADS.read_text(encoding="utf-8")

    @pytest.mark.parametrize("removed_tool", REMOVED_MCP_TOOLS)
    def test_routine_prompts_do_not_use_removed_tools(self, removed_tool: str) -> None:
        """Routine prompts must not reference MCP tools removed in v0.4.0."""
        content = self._content()
        assert removed_tool not in content, (
            f"routine-payloads.md references removed tool '{removed_tool}' "
            f"in a routine prompt — use consolidated API instead"
        )

    def test_feed_poll_prompt_uses_distillery_watch(self) -> None:
        """Feed poll routine prompt must call distillery_watch (to list sources)."""
        content = self._content()
        # Find area around feed-poll routine
        idx = content.find("distillery-feed-poll")
        assert idx != -1
        # Search within the next 500 chars for the distillery_watch call
        surrounding = content[idx : idx + 500]
        assert "distillery_watch" in surrounding, (
            "distillery-feed-poll routine prompt must call distillery_watch"
        )

    def test_stale_check_prompt_uses_stale_days(self) -> None:
        """Stale check routine prompt must use stale_days parameter on distillery_list."""
        content = self._content()
        idx = content.find("distillery-stale-check")
        assert idx != -1
        surrounding = content[idx : idx + 500]
        assert "stale_days" in surrounding, (
            "distillery-stale-check routine prompt must use distillery_list(stale_days=...)"
        )

    def test_weekly_maintenance_prompt_uses_output_stats(self) -> None:
        """Weekly maintenance routine prompt must use output='stats' on distillery_list."""
        content = self._content()
        idx = content.find("distillery-weekly-maintenance")
        assert idx != -1
        surrounding = content[idx : idx + 800]
        assert "output='stats'" in surrounding or 'output="stats"' in surrounding, (
            "distillery-weekly-maintenance prompt must use distillery_list(output='stats')"
        )

    def test_weekly_maintenance_prompt_stores_digest(self) -> None:
        """Weekly maintenance routine prompt must store a digest entry."""
        content = self._content()
        idx = content.find("distillery-weekly-maintenance")
        assert idx != -1
        surrounding = content[idx : idx + 800]
        assert "distillery_store" in surrounding, (
            "distillery-weekly-maintenance prompt must call distillery_store to save the digest"
        )

    def test_no_croncreate_instructions_in_routine_payloads(self) -> None:
        """routine-payloads.md must not instruct users to call CronCreate.

        The file may mention CronCreate in the context of migration/deprecation,
        but must not include any CronCreate(...) function call instructions.
        """
        content = self._content()
        assert "CronCreate(" not in content, (
            "routine-payloads.md must not contain CronCreate() call instructions"
        )

    def test_no_webhook_calls_in_routine_payloads(self) -> None:
        """Routine prompts must use MCP tools, not HTTP webhook calls."""
        content = self._content()
        # Routines execute in Claude Code context with MCP access, no HTTP needed
        assert "requests.post" not in content and "curl" not in content, (
            "routine-payloads.md must not use HTTP calls in prompts — use MCP tools instead"
        )


# ---------------------------------------------------------------------------
# Migration note
# ---------------------------------------------------------------------------


class TestRoutineMigrationNote:
    def _content(self) -> str:
        return ROUTINE_PAYLOADS.read_text(encoding="utf-8")

    def test_migration_note_present(self) -> None:
        """routine-payloads.md must include a migration note referencing cron-payloads.md."""
        content = self._content()
        assert "cron-payloads" in content or "CronCreate" in content, (
            "routine-payloads.md must include a migration note for CronCreate users"
        )

    def test_migration_note_marks_old_approach_deprecated(self) -> None:
        """routine-payloads.md migration note must state that old scheduling is deprecated."""
        content = self._content()
        assert "deprecated" in content.lower(), (
            "routine-payloads.md must state that the old scheduling approach is deprecated"
        )


# ---------------------------------------------------------------------------
# cron-payloads.md must be marked as deprecated
# ---------------------------------------------------------------------------


class TestCronPayloadsDeprecated:
    def test_cron_payloads_still_exists_for_migration(self) -> None:
        """cron-payloads.md must still exist as a reference during migration."""
        assert CRON_PAYLOADS.exists(), (
            "cron-payloads.md is missing — it should be retained for migration reference"
        )

    def test_cron_payloads_marked_deprecated(self) -> None:
        """cron-payloads.md must be marked as DEPRECATED."""
        content = CRON_PAYLOADS.read_text(encoding="utf-8")
        assert "DEPRECATED" in content, (
            "cron-payloads.md must be marked as DEPRECATED (it was superseded by routine-payloads.md)"
        )

    def test_cron_payloads_references_routine_payloads(self) -> None:
        """cron-payloads.md must reference routine-payloads.md as the replacement."""
        content = CRON_PAYLOADS.read_text(encoding="utf-8")
        assert "routine-payloads" in content, (
            "cron-payloads.md must reference routine-payloads.md as the replacement"
        )

    def test_cron_payloads_uses_updated_maintenance_prompt(self) -> None:
        """cron-payloads.md maintenance prompt must use distillery_list not removed tools."""
        content = CRON_PAYLOADS.read_text(encoding="utf-8")
        # The maintenance prompt in cron-payloads was also updated to remove
        # distillery_metrics, distillery_stale, distillery_interests calls
        assert "distillery_metrics" not in content or "DEPRECATED" in content, (
            "cron-payloads.md maintenance prompt still references distillery_metrics"
        )