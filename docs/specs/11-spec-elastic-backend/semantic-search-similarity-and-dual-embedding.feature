# Source: docs/specs/11-spec-elastic-backend/11-spec-elastic-backend.md
# Unit: 2 — Semantic Search, Similarity, and Dual Embedding
# Pattern: Vector search + Filter logic + Embedding mode selection
# Recommended test type: Unit

Feature: Semantic Search, Similarity, and Dual Embedding

  # --- kNN Search ---

  Scenario: Search returns entries ranked by vector similarity
    Given an initialized ElasticsearchStore with embedding_mode "client"
    And the store contains 5 entries with embeddings
    When search() is called with query "async programming in Python"
    Then the EmbeddingProvider generates a query embedding
    And a kNN search is issued with the query_vector, k, and num_candidates
    And the results are returned as SearchResult objects ordered by descending score

  Scenario: Search applies entry_type filter
    Given an initialized ElasticsearchStore with entries of various types
    When search() is called with query "authentication" and filter entry_type="session"
    Then the kNN search includes a filter clause for entry_type "session"
    And all returned results have entry_type "session"

  Scenario: Search applies author filter
    Given an initialized ElasticsearchStore with entries by multiple authors
    When search() is called with query "deployment" and filter author="alice"
    Then the kNN search includes a filter clause for author "alice"
    And all returned results have author "alice"

  Scenario: Search applies project filter
    Given an initialized ElasticsearchStore with entries across multiple projects
    When search() is called with query "API design" and filter project="billing-v2"
    Then all returned results have project "billing-v2"

  Scenario: Search applies tags filter with any-match semantics
    Given an initialized ElasticsearchStore with entries having various tags
    When search() is called with query "testing" and filter tags=["python", "ci"]
    Then the kNN search includes a terms filter matching any of ["python", "ci"]
    And returned results have at least one of the specified tags

  Scenario: Search applies status filter
    Given an initialized ElasticsearchStore with active and archived entries
    When search() is called with query "patterns" and filter status="active"
    Then all returned results have status "active"
    And no archived entries appear in results

  Scenario: Search applies date_from and date_to filters
    Given an initialized ElasticsearchStore with entries spanning multiple dates
    When search() is called with query "release notes" and filter date_from="2026-01-01" and date_to="2026-03-01"
    Then all returned results have created_at between "2026-01-01" and "2026-03-01"

  Scenario: Search with multiple filters applies all simultaneously
    Given an initialized ElasticsearchStore with diverse entries
    When search() is called with query "refactoring" and filters entry_type="session", author="bob", status="active"
    Then the kNN search includes filter clauses for all three criteria
    And all returned results satisfy every filter

  # --- Score Conversion ---

  Scenario: ES cosine scores are converted to the 0-to-1 range
    Given an initialized ElasticsearchStore
    And the ES kNN search returns a hit with score 0.85
    When the score is converted for SearchResult
    Then the SearchResult score is 0.70
    # Conversion: cosine = 2 * 0.85 - 1 = 0.70

  Scenario: Perfect ES cosine score converts to 1.0
    Given an initialized ElasticsearchStore
    And the ES kNN search returns a hit with score 1.0
    When the score is converted for SearchResult
    Then the SearchResult score is 1.0

  Scenario: Orthogonal ES cosine score converts to 0.0
    Given an initialized ElasticsearchStore
    And the ES kNN search returns a hit with score 0.5
    When the score is converted for SearchResult
    Then the SearchResult score is 0.0

  # --- find_similar ---

  Scenario: find_similar returns entries above the similarity threshold
    Given an initialized ElasticsearchStore with multiple entries
    And entries exist with cosine similarities 0.97, 0.88, 0.72, and 0.45 to the input
    When find_similar() is called with threshold 0.80
    Then entries with similarities 0.97 and 0.88 are returned
    And entries with similarities 0.72 and 0.45 are excluded

  Scenario: find_similar with skip threshold identifies exact duplicates
    Given an initialized ElasticsearchStore with multiple entries
    And an entry exists with cosine similarity 0.97 to the input
    When find_similar() is called with threshold 0.95
    Then the entry with similarity 0.97 is returned
    And the result can be used for skip deduplication

  Scenario: find_similar with link threshold identifies related content
    Given an initialized ElasticsearchStore with multiple entries
    And entries exist with cosine similarities 0.72 and 0.65 to the input
    When find_similar() is called with threshold 0.60
    Then both entries are returned
    And entries below 0.60 similarity are excluded

  Scenario: find_similar with no entries above threshold returns empty list
    Given an initialized ElasticsearchStore with entries
    And no entries have cosine similarity above 0.80 to the input
    When find_similar() is called with threshold 0.80
    Then an empty list is returned

  # --- list_entries ---

  Scenario: list_entries returns entries sorted by created_at descending
    Given an initialized ElasticsearchStore with entries created at different times
    When list_entries() is called without filters
    Then entries are returned in descending created_at order

  Scenario: list_entries supports pagination with offset and limit
    Given an initialized ElasticsearchStore with 20 entries
    When list_entries() is called with offset 5 and limit 10
    Then the ES query uses from=5 and size=10
    And 10 entries are returned starting from position 5

  Scenario: list_entries applies metadata filters
    Given an initialized ElasticsearchStore with diverse entries
    When list_entries() is called with filter entry_type="bookmark" and status="active"
    Then all returned entries have entry_type "bookmark" and status "active"
    And a bool query with filter clauses is used

  # --- Dual Embedding: Client Mode ---

  Scenario: Client embedding mode uses EmbeddingProvider for queries
    Given an ElasticsearchStore with embedding_mode "client"
    And a configured EmbeddingProvider
    When search() is called with a query
    Then the EmbeddingProvider.embed() is called with the query text
    And the resulting vector is passed as query_vector to kNN search

  Scenario: Client embedding mode uses EmbeddingProvider for indexing
    Given an ElasticsearchStore with embedding_mode "client"
    And a configured EmbeddingProvider
    When store() is called with a new entry
    Then the EmbeddingProvider.embed() is called with the entry content
    And the embedding vector is stored in the entry document

  # --- Dual Embedding: Server Mode ---

  Scenario: Server embedding mode uses semantic_text field type
    Given an ElasticsearchStore with embedding_mode "server"
    When initialize() is called
    Then the index mapping includes a semantic_text field backed by an ES Inference endpoint
    And the dense_vector field may coexist for backward compatibility

  Scenario: Server embedding mode omits client-side embedding on store
    Given an ElasticsearchStore with embedding_mode "server"
    When store() is called with a new entry
    Then the EmbeddingProvider.embed() is NOT called
    And the entry content is indexed for server-side inference

  Scenario: Server embedding mode omits client-side embedding on search
    Given an ElasticsearchStore with embedding_mode "server"
    When search() is called with a query
    Then the EmbeddingProvider.embed() is NOT called
    And the query is sent for server-side semantic search

  # --- Dual Embedding: Auto Mode ---

  Scenario: Auto mode selects server embedding when inference endpoint is configured
    Given an ElasticsearchStore with embedding_mode "auto"
    And the ES cluster has an inference endpoint configured
    When initialize() is called
    Then the effective embedding mode is "server"

  Scenario: Auto mode selects client embedding when no inference endpoint exists
    Given an ElasticsearchStore with embedding_mode "auto"
    And the ES cluster has no inference endpoint configured
    When initialize() is called
    Then the effective embedding mode is "client"
