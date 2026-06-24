# Source: docs/specs/18-spec-edge-by-default-and-link-suggestion/18-spec-edge-by-default-and-link-suggestion.md
# Pattern: State + CLI/Process
# Recommended test type: Integration

Feature: Edge-by-default at ingestion

  Scenario: A new entry auto-links to a close neighbour on default store
    Given the store uses default config with auto_link enabled
    And an existing entry whose embedding is within the 0.85 threshold of a new entry
    When the new entry is stored via store() with no explicit accept_action
    Then a "related" edge from the new entry to the existing entry is present in entry_relations
    And the edge was created without any manual accept_action being passed

  Scenario: Batch ingestion auto-links each entry
    Given the store uses default config with auto_link enabled
    And an existing entry within threshold of an entry in the incoming batch
    When the batch is stored via store_batch() with no explicit accept_action
    Then the batched entry has a "related" edge to its close neighbour after the batch completes

  Scenario: Feed-poll ingestion inherits auto-link by routing through store
    Given the store uses default config with auto_link enabled
    And the feed poller is configured to ingest an entry that is within threshold of an existing entry
    When the poller ingests the entry through its store() path
    Then the ingested entry has a "related" edge to the existing entry

  Scenario: Re-storing the same entry creates no duplicate edges
    Given an entry that already gained a "related" edge to a close neighbour on first store
    When the same entry is stored a second time
    Then the count of "related" edges from that entry is unchanged
    And no edge violates the (from_id, to_id, relation_type) unique index

  Scenario: Auto-link is capped at max_links edges per entry
    Given default config with max_links of 5
    And a new entry within threshold of more than 5 existing entries
    When the new entry is stored
    Then the number of "related" edges created for that entry does not exceed 5

  Scenario: Disabling auto_link restores no-edge write behaviour
    Given config with auto_link.enabled set to False
    And an existing entry within threshold of a new entry
    When the new entry is stored via store() with no explicit accept_action
    Then no "related" edge is created for the new entry
    And the entry is stored as an orphan
