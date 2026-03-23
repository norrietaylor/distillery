# Source: docs/specs/03-spec-distillery-classification/03-spec-distillery-classification.md
# Pattern: CLI/Process + State + Error handling
# Recommended test type: Unit

Feature: Classification Engine & Deduplication Logic

  # Classification Engine scenarios

  Scenario: Classification engine classifies content as a session entry
    Given a ClassificationEngine instance with default configuration
    And a mocked LLM response returning entry_type "session" with confidence 0.85
    When the engine classifies content "Explored the new auth module, tried OAuth2 flow"
    Then the returned ClassificationResult has entry_type "session"
    And the confidence score is 0.85
    And the reasoning field contains a non-empty explanation
    And the suggested_tags list is populated

  Scenario: Classification engine classifies content as a bookmark entry
    Given a ClassificationEngine instance with default configuration
    And a mocked LLM response returning entry_type "bookmark" with confidence 0.92
    When the engine classifies content "https://docs.python.org/3/library/asyncio.html - great async reference"
    Then the returned ClassificationResult has entry_type "bookmark"
    And the confidence score is 0.92

  Scenario: Classification engine classifies content as a meeting entry
    Given a ClassificationEngine instance with default configuration
    And a mocked LLM response returning entry_type "meeting" with confidence 0.78
    When the engine classifies content "Sprint planning with Alice and Bob, discussed Q3 roadmap"
    Then the returned ClassificationResult has entry_type "meeting"
    And the confidence score is 0.78

  Scenario: Low-confidence classification sets status to pending_review
    Given a ClassificationEngine instance with confidence_threshold 0.6
    And a mocked LLM response returning entry_type "idea" with confidence 0.45
    When the engine classifies the content
    Then the returned status is "pending_review"
    And the confidence score is 0.45

  Scenario: At-threshold confidence sets status to active
    Given a ClassificationEngine instance with confidence_threshold 0.6
    And a mocked LLM response returning entry_type "reference" with confidence 0.6
    When the engine classifies the content
    Then the returned status is "active"
    And the confidence score is 0.6

  Scenario: Above-threshold confidence sets status to active
    Given a ClassificationEngine instance with confidence_threshold 0.6
    And a mocked LLM response returning entry_type "reference" with confidence 0.88
    When the engine classifies the content
    Then the returned status is "active"

  Scenario: Classification engine handles LLM parse failure gracefully
    Given a ClassificationEngine instance with default configuration
    And a mocked LLM response returning malformed non-JSON text
    When the engine classifies the content
    Then the returned ClassificationResult has entry_type "inbox"
    And the confidence score is 0.0
    And the returned status is "pending_review"

  Scenario: Classification result includes suggested project when applicable
    Given a ClassificationEngine instance with default configuration
    And a mocked LLM response returning suggested_project "billing-v2"
    When the engine classifies content about the billing project
    Then the returned ClassificationResult has suggested_project "billing-v2"

  # Deduplication Logic scenarios

  Scenario: Content with similarity score at or above skip threshold returns skip action
    Given a DeduplicationChecker with default thresholds (skip=0.95, merge=0.80, link=0.60)
    And the store contains an existing entry with similarity score 0.97 to the input content
    When the checker evaluates the input content for deduplication
    Then the returned DeduplicationResult action is "skip"
    And the highest_score is 0.97
    And the reasoning mentions the content is a duplicate

  Scenario: Content with similarity score between merge and skip thresholds returns merge action
    Given a DeduplicationChecker with default thresholds (skip=0.95, merge=0.80, link=0.60)
    And the store contains an existing entry with similarity score 0.88 to the input content
    When the checker evaluates the input content for deduplication
    Then the returned DeduplicationResult action is "merge"
    And the similar_entries list contains the matching entry
    And the reasoning mentions merging with the existing entry

  Scenario: Content with similarity score between link and merge thresholds returns link action
    Given a DeduplicationChecker with default thresholds (skip=0.95, merge=0.80, link=0.60)
    And the store contains an existing entry with similarity score 0.72 to the input content
    When the checker evaluates the input content for deduplication
    Then the returned DeduplicationResult action is "link"
    And the similar_entries list contains the related entry

  Scenario: Content with similarity score below link threshold returns create action
    Given a DeduplicationChecker with default thresholds (skip=0.95, merge=0.80, link=0.60)
    And the store contains no entries with similarity score above 0.60
    When the checker evaluates the input content for deduplication
    Then the returned DeduplicationResult action is "create"
    And the similar_entries list is empty or contains only low-score matches

  Scenario: Deduplication checker respects configured dedup_limit
    Given a DeduplicationChecker with dedup_limit set to 3
    And the store contains 10 entries with varying similarity scores
    When the checker evaluates the input content for deduplication
    Then the similar_entries list contains at most 3 entries
