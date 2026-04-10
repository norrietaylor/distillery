Feature: Review Queue
  As a curator
  I want to review low-confidence classifications
  So that I can approve correct ones and reclassify incorrect ones before they pollute search results

  Background:
    Given the Manage tab is displayed in the dashboard
    And the "Review" sub-tab is selected
    And the MCP connection is established via callTool bridge
    And the global project filter is set to "my-project"
    And the user has the "curator" role

  # --- Table Display ---

  Scenario: Review queue table displays pending review entries
    Then the Review Queue section contains a DataTable
    And the table is populated by calling list with status "pending_review" and project "my-project" and limit 50
    And the table displays columns: Preview, Type, Confidence, Classified At, Actions

  Scenario: Preview column shows first 80 characters of content
    Given a pending review entry has content "A long content string that needs to be truncated to eighty characters for the preview column display"
    Then the Preview column shows the first 80 characters followed by an ellipsis

  Scenario: Empty review queue shows informational message
    Given the list call returns zero pending review entries
    Then the table area shows "No entries pending review."

  # --- Confidence Badge Colors ---

  Scenario: Confidence below 0.4 shows red badge
    Given a pending review entry has confidence 0.35
    Then the Confidence column displays "0.35" with a red badge

  Scenario: Confidence between 0.4 and 0.7 shows yellow badge
    Given a pending review entry has confidence 0.55
    Then the Confidence column displays "0.55" with a yellow badge

  Scenario: Confidence above 0.7 shows green badge
    Given a pending review entry has confidence 0.85
    Then the Confidence column displays "0.85" with a green badge

  # --- Badge Count ---

  Scenario: Pending review count badge appears on Review sub-tab
    Given there are 4 entries with status "pending_review"
    Then the "Review" sub-tab displays a badge with "4"

  # --- Row Expansion ---

  Scenario: Row expansion shows classification metadata
    When the user expands a row for a pending review entry
    Then the expanded area shows the confidence score
    And the expanded area shows the classification reasoning text
    And the expanded area shows the classified_at timestamp
    And the expanded area shows the suggested_project if present

  # --- Per-Row Actions: Approve ---

  Scenario: Approve action calls resolve_review and removes row
    Given the review queue shows an entry with ID "review-001" and type "session"
    When the user clicks "Approve" on that row
    Then resolve_review is called with entry_id "review-001" and action "approve" and reviewer matching the current user
    And the row for "review-001" is removed from the table
    And a success toast "Approved as session" is displayed

  # --- Per-Row Actions: Reclassify ---

  Scenario: Reclassify action expands inline type selector
    Given the review queue shows an entry with ID "review-002"
    When the user clicks "Reclassify" on that row
    Then an inline type selector expands below the row
    And the selector shows all entry types

  Scenario: Submitting reclassification calls resolve_review with new type
    Given the user has opened the reclassify form on entry "review-002"
    And the user selects type "reference" in the inline type selector
    When the user submits the reclassification
    Then resolve_review is called with entry_id "review-002" and action "reclassify" and new_entry_type "reference" and reviewer matching the current user
    And the row for "review-002" is removed from the table
    And a success toast "Reclassified as reference" is displayed

  Scenario: Only one inline reclassify form is open at a time
    Given the user has opened the reclassify form on the first row
    When the user clicks "Reclassify" on a different row
    Then the first row's inline form collapses
    And the second row's inline form expands

  # --- Per-Row Actions: Archive ---

  Scenario: Archive action requires confirmation
    Given the review queue shows an entry with ID "review-003"
    When the user clicks "Archive" on that row
    Then a confirmation dialog is displayed

  Scenario: Confirmed archive calls resolve_review and removes row
    Given the archive confirmation dialog is displayed for entry "review-003"
    When the user confirms the archive action
    Then resolve_review is called with entry_id "review-003" and action "archive" and reviewer matching the current user
    And the row for "review-003" is removed from the table
    And a success toast is displayed

  Scenario: Cancelled archive leaves row unchanged
    Given the archive confirmation dialog is displayed for entry "review-003"
    When the user cancels the archive action
    Then the row for "review-003" remains in the table

  # --- Batch Approve ---

  Scenario: Batch approve provides checkbox selection and approve button
    Then each row has a selection checkbox
    And an "Approve all selected" button is displayed above the table

  Scenario: Batch approve processes selected entries sequentially
    Given the user selects checkboxes on 4 entries
    When the user clicks "Approve all selected"
    Then resolve_review is called for each selected entry with action "approve" and reviewer matching the current user
    And the calls are made one at a time in sequence

  Scenario: Batch approve shows progress indicator
    Given the user has started a batch approval of 8 entries
    Then a progress indicator shows the current progress count
    And as each approval completes the counter increments
    And when all complete the progress indicator is replaced by a summary toast

  # --- Error Handling ---

  Scenario: Failed approve shows error toast and retains row
    Given the user clicks "Approve" on entry "review-err"
    When the resolve_review call fails with an error
    Then an error toast with the failure message is displayed
    And the row for "review-err" remains in the table

  Scenario: Partial batch approve failure reports failures at the end
    Given the user starts a batch approval of 5 entries
    And the resolve_review call fails for 1 of the 5 entries
    When the batch completes
    Then the 4 successful entries are removed from the table
    And the 1 failed entry remains in the table
    And a summary toast "4 approved, 1 failed" is displayed

  # --- Loading State ---

  Scenario: Approve button shows loading state during call
    When the user clicks "Approve" on a row
    Then the "Approve" button shows a loading indicator
    And the other action buttons on that row are disabled
