Feature: Inbox Triage
  As a curator
  I want to classify untyped inbox entries individually or in batch
  So that new feed items and imports are properly categorized and searchable

  Background:
    Given the Manage tab is displayed in the dashboard
    And the "Inbox" sub-tab is selected
    And the MCP connection is established via callTool bridge
    And the global project filter is set to "my-project"
    And the user has the "curator" role

  # --- Table Display ---

  Scenario: Inbox table displays entries from list call
    Then the Inbox section contains a DataTable
    And the table is populated by calling list with entry_type "inbox" and status "active" and project "my-project" and limit 50
    And the table displays columns: Preview, Source, Created Date, Tags, Actions

  Scenario: Preview column shows first 80 characters of content
    Given an inbox entry has content "This is a very long piece of content that definitely exceeds eighty characters in length and should be truncated"
    Then the Preview column shows "This is a very long piece of content that definitely exceeds eighty characters i..."

  Scenario: Empty inbox shows informational message
    Given the list call returns zero inbox entries
    Then the table area shows "Inbox is empty. New feed items and imports will appear here."

  # --- Badge Count ---

  Scenario: Inbox count badge appears on Manage tab navigation
    Given there are 7 inbox entries
    Then the Manage tab navigation item displays a badge with "7"

  Scenario: Inbox count badge refreshes on auto-refresh interval
    Given there are 7 inbox entries
    When the auto-refresh interval fires
    And the list stats call returns 5 inbox entries
    Then the Manage tab badge updates to "5"

  # --- Per-Row Actions: Classify ---

  Scenario: Classify action expands inline classification form
    Given the inbox table shows at least one entry
    When the user clicks "Classify" on a row
    Then an inline form expands below that row
    And the form contains a type selector with all entry types except "inbox"
    And the form contains a confidence slider ranging from 0.0 to 1.0 with step 0.05 and default 0.7
    And the form contains a reasoning text input
    And the form contains an "Apply" button

  Scenario: Only one inline classify form is open at a time
    Given the user has opened the classify form on the first row
    When the user clicks "Classify" on a different row
    Then the first row's inline form collapses
    And the second row's inline form expands

  Scenario: Apply classification calls classify tool and removes row
    Given the user has opened the classify form on an entry with ID "entry-123"
    And the user selects type "session" in the type selector
    And the user sets confidence to 0.85
    And the user enters "Meeting notes from standup" in the reasoning input
    When the user clicks "Apply"
    Then the classify tool is called with entry_id "entry-123" and entry_type "session" and confidence 0.85 and reasoning "Meeting notes from standup"
    And the row for "entry-123" is removed from the table

  Scenario: Success toast shows assigned type for active entry
    Given the classify call succeeds and the entry goes to active status
    Then a success toast "Classified as session (active)" is displayed

  Scenario: Success toast shows pending review for low-confidence classification
    Given the classify call succeeds and the entry goes to pending_review status
    Then a success toast "Classified as session (pending review)" is displayed

  # --- Per-Row Actions: Investigate ---

  Scenario: Investigate action navigates to Explore tab with entry loaded
    Given the inbox table shows an entry with ID "entry-456"
    When the user clicks "Investigate" on that row
    Then the dashboard navigates to the Explore tab
    And the entry "entry-456" is loaded in the detail panel

  # --- Per-Row Actions: Archive ---

  Scenario: Archive action requires confirmation
    Given the inbox table shows an entry with ID "entry-789"
    When the user clicks "Archive" on that row
    Then a confirmation dialog is displayed

  Scenario: Confirmed archive calls resolve_review and removes row
    Given the archive confirmation dialog is displayed for entry "entry-789"
    When the user confirms the archive action
    Then resolve_review is called with entry_id "entry-789" and action "archive" and reviewer matching the current user
    And the row for "entry-789" is removed from the table
    And a success toast is displayed

  Scenario: Cancelled archive leaves row unchanged
    Given the archive confirmation dialog is displayed for entry "entry-789"
    When the user cancels the archive action
    Then the row for "entry-789" remains in the table

  # --- Batch Mode ---

  Scenario: Batch mode provides checkbox selection and classify dropdown
    Then each row has a selection checkbox
    And a "Classify all as..." dropdown is displayed above the table

  Scenario: Batch classify applies type to all selected entries with default confidence
    Given the user selects checkboxes on 3 entries
    And the user selects "reference" from the "Classify all as..." dropdown
    When the batch classification starts
    Then classify is called for each selected entry with entry_type "reference" and confidence 0.7

  Scenario: Batch classify shows progress indicator
    Given the user has started a batch classification of 12 entries
    Then a progress indicator shows "Classifying 1 of 12..."
    And as each classification completes the counter increments
    And when all complete the progress indicator is replaced by a summary toast

  Scenario: Batch classify processes entries sequentially
    Given the user has started a batch classification of 3 entries
    Then the classify calls are made one at a time in sequence
    And each row is removed from the table as its classification succeeds

  # --- Error Handling ---

  Scenario: Failed classification shows error toast and retains row
    Given the user clicks "Apply" on the classify form for entry "entry-err"
    When the classify call fails with an error
    Then an error toast with the failure message is displayed
    And the row for "entry-err" remains in the table

  Scenario: Partial batch failure reports failures at the end
    Given the user starts a batch classification of 5 entries
    And the classify call fails for 2 of the 5 entries
    When the batch completes
    Then the 3 successful entries are removed from the table
    And the 2 failed entries remain in the table
    And a summary toast "3 classified, 2 failed" is displayed

  # --- Loading State ---

  Scenario: Classify apply button shows loading during call
    When the user clicks "Apply" on the classify form
    Then the "Apply" button shows a loading indicator
    And the type selector and confidence slider are disabled
