# Source: docs/specs/08-spec-infrastructure-improvements/08-spec-infrastructure-improvements.md
# Pattern: State + API + Error Handling
# Recommended test type: Integration

Feature: Hierarchical Tag Namespace

  Scenario: Valid hierarchical tag is accepted on entry creation
    Given an in-memory DuckDB store is initialized
    When a user stores an entry with tags ["project/billing-v2/decisions"]
    Then the entry is stored successfully and returns a valid UUID
    And the entry's tags list contains "project/billing-v2/decisions"

  Scenario: Valid flat tag continues to be accepted
    Given an in-memory DuckDB store is initialized
    When a user stores an entry with tags ["meeting-notes"]
    Then the entry is stored successfully and returns a valid UUID
    And the entry's tags list contains "meeting-notes"

  Scenario: Invalid tag with uppercase characters is rejected
    Given an in-memory DuckDB store is initialized
    When a user attempts to create an entry with tags ["Project/Billing"]
    Then a ValueError is raised
    And the error message indicates the tag format is invalid

  Scenario: Invalid tag with trailing slash is rejected
    Given an in-memory DuckDB store is initialized
    When a user attempts to create an entry with tags ["project/billing/"]
    Then a ValueError is raised
    And the error message indicates the tag format is invalid

  Scenario: Invalid tag with empty segment is rejected
    Given an in-memory DuckDB store is initialized
    When a user attempts to create an entry with tags ["project//billing"]
    Then a ValueError is raised
    And the error message indicates the tag format is invalid

  Scenario: Tag prefix filter returns only matching namespace entries
    Given an in-memory DuckDB store with the following entries:
      | tags                              |
      | project/billing-v2/decisions      |
      | project/billing-v2/api            |
      | project/billing-v3/api            |
      | project/payments/decisions        |
    When a user searches with tag_prefix "project/billing-v2"
    Then exactly 2 entries are returned
    And all returned entries have a tag starting with "project/billing-v2/"

  Scenario: Tag prefix filter does not match partial segment names
    Given an in-memory DuckDB store with the following entries:
      | tags                         |
      | project/billing/api          |
      | project/billing-v2/api       |
    When a user searches with tag_prefix "project/billing"
    Then exactly 1 entry is returned
    And the returned entry has the tag "project/billing/api"

  Scenario: Tag tree MCP tool returns nested hierarchy with counts
    Given entries are stored with the following tags:
      | tags                              |
      | project/billing-v2/decisions      |
      | project/billing-v2/api            |
      | project/payments/decisions        |
      | team/backend                      |
    When a user calls the distillery_tag_tree MCP tool with no prefix
    Then the response contains a nested tree structure
    And the "project" node has children "billing-v2" and "payments"
    And the "project/billing-v2" subtree shows a count of 2

  Scenario: Tag tree MCP tool filters by prefix
    Given entries are stored with hierarchical tags under "project/" and "team/"
    When a user calls the distillery_tag_tree MCP tool with prefix "project"
    Then the response contains only nodes under "project"
    And no "team" nodes appear in the result

  Scenario: MCP search tool accepts tag_prefix parameter
    Given entries are stored with tags under "domain/architecture" and "domain/security"
    When a user calls distillery_search with tag_prefix "domain/architecture"
    Then only entries tagged under "domain/architecture/" are returned
    And entries tagged under "domain/security/" are not included

  Scenario: MCP list tool accepts tag_prefix parameter
    Given entries are stored with tags under "source/bookmark" and "source/manual"
    When a user calls distillery_list with tag_prefix "source/bookmark"
    Then only entries tagged under "source/bookmark/" are returned
