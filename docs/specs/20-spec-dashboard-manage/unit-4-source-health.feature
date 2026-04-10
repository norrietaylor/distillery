Feature: Source Health
  As an operator
  I want to see feed source operational status including last poll time, items stored, and error counts
  So that I can identify broken or stale sources

  Background:
    Given the Manage tab is displayed in the dashboard
    And the "Sources" sub-tab is selected
    And the MCP connection is established via callTool bridge

  # --- Table Display ---

  Scenario: Source health table displays feed sources from watch list call
    Then the Source Health section contains a DataTable
    And the table is populated by calling watch with action "list"
    And the table displays columns: Source, Type, Label, Last Poll, Items Stored, Errors, Status

  Scenario: Type column shows RSS or GitHub badge
    Given a source has type "rss"
    Then the Type column shows an "RSS" badge
    Given a source has type "github"
    Then the Type column shows a "GitHub" badge

  Scenario: Empty sources shows informational message with navigation
    Given the watch list call returns zero sources
    Then the table area shows "No feed sources configured. Add sources in the Capture tab."
    And a link or button to navigate to the Capture tab is displayed

  Scenario: Clicking the Capture tab link navigates to Capture
    Given the empty state message is displayed
    When the user clicks the link to the Capture tab
    Then the dashboard navigates to the Capture tab

  # --- Status Derivation ---

  Scenario: Source polled within interval shows green Healthy status
    Given a source has a poll interval of 60 minutes
    And the source was last polled 30 minutes ago
    Then the Status column shows a green "Healthy" badge

  Scenario: Source polled at exactly the interval shows green Healthy status
    Given a source has a poll interval of 60 minutes
    And the source was last polled 60 minutes ago
    Then the Status column shows a green "Healthy" badge

  Scenario: Source overdue beyond 1.5x interval shows yellow Overdue status
    Given a source has a poll interval of 60 minutes
    And the source was last polled 100 minutes ago
    Then the Status column shows a yellow "Overdue" badge

  Scenario: Source with errors shows red Error status
    Given a source has a poll interval of 60 minutes
    And the source's last poll had errors
    Then the Status column shows a red "Error" badge

  Scenario: Source older than 3x interval shows red Error status
    Given a source has a poll interval of 60 minutes
    And the source was last polled 200 minutes ago
    Then the Status column shows a red "Error" badge

  Scenario: Source never polled shows gray Never polled status
    Given a source has no recorded poll
    Then the Status column shows a gray "Never polled" badge

  # --- Relative Time Display ---

  Scenario: Last poll shows relative time in minutes
    Given a source was last polled 5 minutes ago
    Then the Last Poll column shows "5 minutes ago"

  Scenario: Last poll shows relative time in hours
    Given a source was last polled 2 hours ago
    Then the Last Poll column shows "2 hours ago"

  Scenario: Last poll shows relative time in days
    Given a source was last polled 3 days ago
    Then the Last Poll column shows "3 days ago"

  Scenario: Never polled source shows dash in Last Poll column
    Given a source has no recorded poll
    Then the Last Poll column shows "-"

  # --- Row Expansion ---

  Scenario: Row expansion shows full source details
    When the user expands a row for a source
    Then the expanded area shows the full URL
    And the expanded area shows the trust weight
    And the expanded area shows the poll interval
    And the expanded area shows the added date
    And the expanded area shows the last poll timestamp in absolute format

  Scenario: Expanded row provides Remove action
    When the user expands a row for a source
    Then a "Remove" button is displayed in the expanded area

  # --- Remove Source ---

  Scenario: Remove action requires confirmation
    Given the user has expanded a source row with URL "https://example.com/feed.xml"
    When the user clicks "Remove"
    Then a confirmation dialog is displayed

  Scenario: Confirmed remove calls watch remove and removes row
    Given the remove confirmation dialog is displayed for source "https://example.com/feed.xml"
    When the user confirms the remove action
    Then watch is called with action "remove" and url "https://example.com/feed.xml"
    And the source row is removed from the table
    And a success toast is displayed

  Scenario: Cancelled remove leaves source unchanged
    Given the remove confirmation dialog is displayed for source "https://example.com/feed.xml"
    When the user cancels the remove action
    Then the source row remains in the table

  # --- Refresh ---

  Scenario: Source health data refreshes on auto-refresh interval
    Given the source health table is displayed with current data
    When the auto-refresh interval fires
    Then the watch list call is made again
    And the table updates with new data including recalculated status badges

  # --- Error Handling ---

  Scenario: Failed remove shows error toast and retains row
    Given the user confirms removal of source "https://example.com/feed.xml"
    When the watch remove call fails with an error
    Then an error toast with the failure message is displayed
    And the source row remains in the table
