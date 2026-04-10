Feature: Health Overview
  As an operator
  I want to see knowledge base health metrics and composition charts
  So that I can monitor growth and identify imbalances

  Background:
    Given the Manage tab is displayed in the dashboard
    And the "Health" sub-tab is selected
    And the MCP connection is established via callTool bridge
    And the global project filter is set to "my-project"

  # --- Metric Cards ---

  Scenario: Health section displays metric cards row
    Then a row of metric cards is displayed
    And the cards show: Total Entries, Active, Pending Review, Archived, Inbox

  Scenario: Metric cards are populated from list stats call
    Given the list call with output "stats" and project "my-project" returns total 150, active 120, pending_review 10, archived 15, inbox 5
    Then the "Total Entries" card shows "150"
    And the "Active" card shows "120"
    And the "Pending Review" card shows "10"
    And the "Archived" card shows "15"
    And the "Inbox" card shows "5"

  # --- Entry Type Pie Chart ---

  Scenario: Pie chart displays entries grouped by type
    Given the list call with group_by "entry_type" and project "my-project" returns session 40, reference 35, bookmark 25, feed_item 20
    Then a pie chart is displayed showing entries by type
    And the chart contains a segment for "session" with value 40
    And the chart contains a segment for "reference" with value 35
    And the chart contains a segment for "bookmark" with value 25
    And the chart contains a segment for "feed_item" with value 20

  Scenario: Type colors are consistent across all charts
    Given the pie chart is rendered with entry types
    Then the color for "session" in the pie chart matches the color used for "session" elsewhere in the dashboard

  # --- Entry Status Bar Chart ---

  Scenario: Bar chart displays entries grouped by status
    Given the list call with group_by "status" and project "my-project" returns active 120, pending_review 10, archived 15
    Then a bar chart is displayed showing entries by status
    And the chart contains a bar for "active" with value 120
    And the chart contains a bar for "pending_review" with value 10
    And the chart contains a bar for "archived" with value 15

  # --- Storage Display ---

  Scenario: Storage size displayed in kilobytes
    Given the stats response includes storage_bytes 512000
    Then the storage metric shows "500 KB"

  Scenario: Storage size displayed in megabytes
    Given the stats response includes storage_bytes 52428800
    Then the storage metric shows "50 MB"

  Scenario: Storage size displayed in gigabytes
    Given the stats response includes storage_bytes 2147483648
    Then the storage metric shows "2 GB"

  # --- Refresh ---

  Scenario: Health data refreshes on auto-refresh interval
    Given the health section is displayed with current data
    When the auto-refresh interval fires
    Then the list stats call is made again with project "my-project"
    And the metric cards update with the new values
    And the pie chart and bar chart re-render with new data

  Scenario: Health data refreshes on manual refresh
    When the user triggers a manual refresh
    Then the list stats call is made again
    And the charts and metric cards update with new data

  # --- Empty Knowledge Base ---

  Scenario: Empty knowledge base shows zero-state charts without errors
    Given the list stats call returns total 0
    Then all metric cards show "0"
    And the pie chart renders in an empty state without errors
    And the bar chart renders in an empty state without errors
    And no error toasts are displayed
