# Source: docs/specs/14-spec-briefing/14-spec-briefing.md
# Pattern: CLI/Process + API (skill orchestrating MCP tools with team detection)
# Recommended test type: Integration

Feature: Team mode

  Scenario: Team flag forces team mode regardless of author count
    Given a knowledge base with entries from a single author "alice"
    When the user invokes "/briefing --team --project distillery"
    Then the output header reads "# Briefing: distillery (team)"
    And the output contains a "Team Activity" section

  Scenario: Team mode auto-detects when multiple authors exist
    Given a knowledge base with entries from authors "alice" and "bob"
    When the user invokes "/briefing --project distillery"
    Then the output header reads "# Briefing: distillery (team)"

  Scenario: Solo mode remains when only one author exists and no team flag
    Given a knowledge base with entries from a single author "alice"
    When the user invokes "/briefing --project distillery"
    Then the output header reads "# Briefing: distillery (solo)"
    And the output does not contain a "Team Activity" section

  Scenario: Team activity section groups entries by author for the past 7 days
    Given a knowledge base with 5 entries from "alice" and 2 entries from "bob" in the past 7 days
    When the user invokes "/briefing --team --project distillery"
    Then the "Team Activity" section shows "alice" with 5 entries and entry type counts
    And the "Team Activity" section shows "bob" with 2 entries and entry type counts

  Scenario: Related from team section surfaces semantically relevant entries from other authors
    Given a knowledge base with project context entries from author "alice"
    And a knowledge base with semantically related entries from author "bob"
    When the user invokes "/briefing --team --project distillery"
    Then the "Related from Team" section lists entries from "bob"
    And each entry shows a similarity percentage

  Scenario: Pending review section shows entries awaiting classification
    Given a knowledge base with 3 entries in "pending_review" status
    When the user invokes "/briefing --team --project distillery"
    Then the "Pending Review" section lists up to 5 entries awaiting review

  Scenario: Solo sections remain present in team mode
    Given a knowledge base with entries from authors "alice" and "bob"
    And a knowledge base with recent entries, stale entries, and unresolved entries
    When the user invokes "/briefing --team --project distillery"
    Then the output contains the "Recent" section
    And the output contains the "Stale" section
    And the output contains the "Unresolved" section
    And the output contains the "Team Activity" section

  Scenario: Empty team sections are omitted
    Given a knowledge base with entries from authors "alice" and "bob"
    And no entries are in "pending_review" status
    When the user invokes "/briefing --team --project distillery"
    Then the output does not contain a "Pending Review" section
