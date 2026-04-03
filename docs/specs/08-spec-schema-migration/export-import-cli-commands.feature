# Source: docs/specs/08-spec-schema-migration/08-spec-schema-migration.md
# Pattern: CLI/Process + State
# Recommended test type: Integration

Feature: Export/Import CLI Commands

  Scenario: Export creates a valid JSON backup file
    Given a store with 5 entries and 2 feed sources
    When the user runs "distillery export --output backup.json"
    Then the command exits with code 0
    And a file "backup.json" is created
    And the JSON file contains a "version" key with value 1
    And the JSON file contains an "exported_at" key with an ISO timestamp
    And the "entries" array contains 5 items
    And the "feed_sources" array contains 2 items

  Scenario: Export excludes embeddings from output
    Given a store with entries that have computed embeddings
    When the user runs "distillery export --output backup.json"
    Then no entry in the exported JSON contains an "embedding" field

  Scenario: Export reports entry and feed source counts
    Given a store with 3 entries and 1 feed source
    When the user runs "distillery export --output backup.json"
    Then stdout contains "Exported 3 entries and 1 feed sources to backup.json"

  Scenario: Import in merge mode skips existing entries
    Given a store with 2 existing entries with IDs "aaa" and "bbb"
    And a backup file containing entries with IDs "bbb", "ccc", and "ddd"
    When the user runs "distillery import --input backup.json --mode merge"
    Then the store contains 4 entries with IDs "aaa", "bbb", "ccc", "ddd"
    And entry "bbb" retains its original content from the store
    And stdout reports 2 entries imported and 1 skipped

  Scenario: Import in replace mode drops existing entries and imports all
    Given a store with 2 existing entries
    And a backup file containing 3 entries
    When the user runs "distillery import --input backup.json --mode replace"
    Then the store contains exactly 3 entries from the backup
    And embeddings are recomputed for all 3 imported entries

  Scenario: Import re-computes embeddings for imported entries
    Given a backup file containing 2 entries with content
    When the user runs "distillery import --input backup.json --mode merge"
    Then both imported entries have non-null embeddings in the store
    And the embedding dimensions match the configured embedding provider

  Scenario: Import merges feed sources by URL and skips duplicates
    Given a store with a feed source at URL "https://example.com/feed"
    And a backup file containing feed sources at URLs "https://example.com/feed" and "https://other.com/feed"
    When the user runs "distillery import --input backup.json --mode merge"
    Then the store contains 2 feed sources
    And the original feed source at "https://example.com/feed" is unchanged

  Scenario: Import reports detailed counts
    Given a backup file with 5 entries and 2 feed sources
    And a store with 1 matching entry
    When the user runs "distillery import --input backup.json --mode merge"
    Then stdout contains "Imported 4 entries (1 skipped"
    And stdout contains "2 feed sources"

  Scenario: Export and import round-trip preserves data fidelity
    Given a store with 5 entries and 2 feed sources
    When the user runs "distillery export --output backup.json"
    And the user runs "distillery import --input backup.json --mode replace"
    Then all 5 entries are present with identical content, tags, metadata, and timestamps
    And both feed sources are present with identical configuration

  Scenario: Import rejects malformed JSON input
    Given a file "bad.json" containing invalid JSON
    When the user runs "distillery import --input bad.json"
    Then the command exits with a non-zero code
    And stderr contains an error message describing the JSON format issue

  Scenario: Import in replace mode prompts for confirmation
    Given a store with existing entries
    And a valid backup file
    When the user runs "distillery import --input backup.json --mode replace" without the --yes flag
    Then the command prompts for confirmation before proceeding
    And if the user declines, no entries are modified

  Scenario: Import in replace mode skips confirmation with --yes flag
    Given a store with existing entries
    And a valid backup file
    When the user runs "distillery import --input backup.json --mode replace --yes"
    Then the import proceeds without prompting for confirmation
    And all entries are replaced
