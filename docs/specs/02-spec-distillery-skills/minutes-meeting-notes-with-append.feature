# Source: docs/specs/02-spec-distillery-skills/02-spec-distillery-skills.md
# Pattern: CLI/Process + State + Error Handling
# Recommended test type: Integration

Feature: /minutes — Meeting Notes with Append Updates

  Scenario: New meeting creates an entry with structured notes and generated meeting_id
    Given the Distillery MCP server is running and connected
    When the user invokes "/minutes" and provides meeting title "Architecture Review", attendees, discussion points, decisions, and action items
    Then the skill generates a meeting_id in the format "arch-review-2026-03-22"
    And the skill calls distillery_store with entry_type "minutes" and metadata containing the meeting_id and attendees
    And the user sees a confirmation with entry ID, meeting_id, and a preview of the stored content

  Scenario: Update mode appends new content to an existing meeting entry
    Given the Distillery MCP server is running and connected
    And a meeting entry with meeting_id "standup-2026-03-22" exists in the knowledge base
    When the user invokes "/minutes --update standup-2026-03-22" and provides additional notes
    Then the skill finds the existing entry by searching for the meeting_id
    And the skill calls distillery_update appending content under a "## Update — <timestamp>" heading
    And the version number is incremented
    And the user sees a confirmation with entry ID, meeting_id, and updated version number

  Scenario: Update mode reports missing meeting and offers to create new
    Given the Distillery MCP server is running and connected
    And no meeting entry with meeting_id "retro-2026-03-20" exists
    When the user invokes "/minutes --update retro-2026-03-20"
    Then the skill reports that no meeting with that ID was found
    And the skill offers to create a new meeting entry instead

  Scenario: List mode displays recent meetings
    Given the Distillery MCP server is running and connected
    And multiple meeting entries exist in the knowledge base
    When the user invokes "/minutes --list"
    Then the skill calls distillery_list with entry_type "minutes" and limit 10
    And a list of recent meetings is displayed with their meeting_ids and dates

  Scenario: Meeting notes include formatted sections for decisions and action items
    Given the Distillery MCP server is running and connected
    When the user invokes "/minutes" and provides decisions "Use PostgreSQL" and action items "Alice: set up DB by Friday"
    Then the stored content contains a "Decisions" section with "Use PostgreSQL"
    And the stored content contains an "Action Items" section with "Alice: set up DB by Friday"

  Scenario: Minutes displays setup message when MCP server is unavailable
    Given the Distillery MCP server is not configured or not running
    When the user invokes "/minutes"
    Then an error message is displayed indicating the MCP server is unavailable
    And a reference to "docs/mcp-setup.md" is included in the message
