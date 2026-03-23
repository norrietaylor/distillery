# Source: docs/specs/03-spec-distillery-classification/03-spec-distillery-classification.md
# Pattern: API + State + Error handling
# Recommended test type: Integration

Feature: MCP Server Extensions (classify & review_queue tools)

  # distillery_classify tool scenarios

  Scenario: Classify tool assigns type and metadata to an unclassified entry
    Given the MCP server is running with a test store
    And an entry exists with id "entry-001" and entry_type "inbox"
    When the distillery_classify tool is called with entry_id "entry-001"
    Then the response contains the classified entry_type
    And the entry's metadata.confidence contains a float between 0.0 and 1.0
    And the entry's metadata.classified_at contains an ISO 8601 timestamp
    And the entry's metadata.classification_reasoning contains a non-empty string

  Scenario: Classify tool merges suggested tags without duplicates
    Given the MCP server is running with a test store
    And an entry exists with id "entry-002" and tags ["python", "async"]
    And the classification engine suggests tags ["async", "concurrency"]
    When the distillery_classify tool is called with entry_id "entry-002"
    Then the entry's tags contain ["python", "async", "concurrency"]
    And no duplicate tags exist in the list

  Scenario: Classify tool sets suggested project when entry has no project
    Given the MCP server is running with a test store
    And an entry exists with id "entry-003" and project set to None
    And the classification engine suggests project "billing-v2"
    When the distillery_classify tool is called with entry_id "entry-003"
    Then the entry's project is "billing-v2"

  Scenario: Classify tool does not overwrite existing project
    Given the MCP server is running with a test store
    And an entry exists with id "entry-004" and project "infra"
    And the classification engine suggests project "billing-v2"
    When the distillery_classify tool is called with entry_id "entry-004"
    Then the entry's project remains "infra"

  Scenario: Classify tool sets status to pending_review for low confidence
    Given the MCP server is running with a test store and confidence_threshold 0.6
    And an entry exists with id "entry-005"
    And the classification engine returns confidence 0.45
    When the distillery_classify tool is called with entry_id "entry-005"
    Then the entry's status is "pending_review"

  Scenario: Classify tool sets status to active for high confidence
    Given the MCP server is running with a test store and confidence_threshold 0.6
    And an entry exists with id "entry-006"
    And the classification engine returns confidence 0.82
    When the distillery_classify tool is called with entry_id "entry-006"
    Then the entry's status is "active"

  Scenario: Reclassifying an already-classified entry notes reclassification
    Given the MCP server is running with a test store
    And an entry exists with id "entry-007" and metadata.confidence 0.75
    When the distillery_classify tool is called with entry_id "entry-007"
    Then the response indicates this is a reclassification
    And the entry's metadata.classified_at is updated to the current time

  Scenario: Classify tool returns error for nonexistent entry
    Given the MCP server is running with a test store
    And no entry exists with id "entry-999"
    When the distillery_classify tool is called with entry_id "entry-999"
    Then the response contains a structured error indicating the entry was not found

  # distillery_review_queue tool scenarios

  Scenario: Review queue returns entries with pending_review status
    Given the MCP server is running with a test store
    And 3 entries exist with status "pending_review"
    And 5 entries exist with status "active"
    When the distillery_review_queue tool is called with default parameters
    Then the response contains exactly 3 entries
    And each entry includes id, content preview, entry_type, confidence, author, created_at, and classification_reasoning

  Scenario: Review queue respects limit parameter
    Given the MCP server is running with a test store
    And 10 entries exist with status "pending_review"
    When the distillery_review_queue tool is called with limit 3
    Then the response contains exactly 3 entries

  Scenario: Review queue filters by entry_type
    Given the MCP server is running with a test store
    And 2 entries with status "pending_review" have entry_type "idea"
    And 3 entries with status "pending_review" have entry_type "session"
    When the distillery_review_queue tool is called with entry_type "idea"
    Then the response contains exactly 2 entries
    And all returned entries have entry_type "idea"

  Scenario: Review queue returns entries sorted by created_at descending
    Given the MCP server is running with a test store
    And entries exist with status "pending_review" created at different times
    When the distillery_review_queue tool is called
    Then the first entry in the response has the most recent created_at
    And entries are ordered from newest to oldest

  Scenario: Review queue truncates content to 200 characters
    Given the MCP server is running with a test store
    And an entry with status "pending_review" has content longer than 200 characters
    When the distillery_review_queue tool is called
    Then the content field in the response is at most 200 characters

  # distillery_resolve_review tool scenarios

  Scenario: Approve action sets entry status to active with review metadata
    Given the MCP server is running with a test store
    And an entry exists with id "entry-010" and status "pending_review"
    When the distillery_resolve_review tool is called with entry_id "entry-010" and action "approve"
    Then the entry's status is "active"
    And the entry's metadata.reviewed_at contains an ISO 8601 timestamp

  Scenario: Reclassify action updates entry_type and records old type
    Given the MCP server is running with a test store
    And an entry exists with id "entry-011" and entry_type "inbox" and status "pending_review"
    When the distillery_resolve_review tool is called with entry_id "entry-011", action "reclassify", and new_entry_type "session"
    Then the entry's entry_type is "session"
    And the entry's status is "active"
    And the entry's metadata.reclassified_from is "inbox"
    And the entry's metadata.reviewed_at contains an ISO 8601 timestamp

  Scenario: Archive action soft-deletes the entry
    Given the MCP server is running with a test store
    And an entry exists with id "entry-012" and status "pending_review"
    When the distillery_resolve_review tool is called with entry_id "entry-012" and action "archive"
    Then the entry's status is "archived"
    And the response confirms the entry was archived
