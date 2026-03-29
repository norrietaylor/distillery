# Source: docs/specs/11-spec-elastic-backend/11-spec-elastic-backend.md
# Unit: 1 — ElasticsearchStore: Config, Connection, and CRUD
# Pattern: Config validation + Connection lifecycle + CRUD operations
# Recommended test type: Unit

Feature: Elasticsearch Config, Connection, and CRUD Operations

  # --- Configuration and Validation ---

  Scenario: Valid elasticsearch config with url is accepted
    Given a distillery.yaml with backend "elasticsearch"
    And the config contains url "https://my-project.es.us-east-1.aws.elastic.cloud"
    And the config contains api_key_env "ELASTICSEARCH_API_KEY"
    And the environment variable "ELASTICSEARCH_API_KEY" is set to a non-empty value
    When the config is parsed
    Then the storage backend is "elasticsearch"
    And the index_prefix defaults to "distillery"
    And the embedding_mode defaults to "client"

  Scenario: Valid elasticsearch config with cloud_id_env is accepted
    Given a distillery.yaml with backend "elasticsearch"
    And the config contains cloud_id_env "ELASTICSEARCH_CLOUD_ID"
    And the config contains api_key_env "ELASTICSEARCH_API_KEY"
    And both environment variables are set to non-empty values
    When the config is parsed
    Then the storage backend is "elasticsearch"

  Scenario: Config with custom index_prefix and embedding_mode is accepted
    Given a distillery.yaml with backend "elasticsearch"
    And the config contains index_prefix "myteam"
    And the config contains embedding_mode "server"
    When the config is parsed
    Then the index_prefix is "myteam"
    And the embedding_mode is "server"

  Scenario: Config without url or cloud_id_env fails validation
    Given a distillery.yaml with backend "elasticsearch"
    And the config contains neither url nor cloud_id_env
    When the config is parsed
    Then a validation error is raised indicating url or cloud_id_env is required

  Scenario: Config with api_key_env referencing empty env var fails validation
    Given a distillery.yaml with backend "elasticsearch"
    And the config contains api_key_env "ELASTICSEARCH_API_KEY"
    And the environment variable "ELASTICSEARCH_API_KEY" is empty or unset
    When the config is parsed
    Then a validation error is raised indicating the API key env var is empty

  Scenario: Config without api_key_env fails validation
    Given a distillery.yaml with backend "elasticsearch"
    And the config does not contain api_key_env
    When the config is parsed
    Then a validation error is raised indicating api_key_env is required

  # --- Connection and Index Setup ---

  Scenario: Initialize creates versioned indices with aliases
    Given an ElasticsearchStore with index_prefix "distillery"
    And a mock AsyncElasticsearch client
    When initialize() is called
    Then the client creates index "distillery_entries_v1" with alias "distillery_entries"
    And the client creates index "distillery_search_log_v1" with alias "distillery_search_log"
    And the client creates index "distillery_feedback_log_v1" with alias "distillery_feedback_log"

  Scenario: Initialize sets bbq_hnsw mapping on the embedding field
    Given an ElasticsearchStore with a mock AsyncElasticsearch client
    And the configured EmbeddingProvider has dimension 768
    When initialize() is called
    Then the "distillery_entries_v1" index mapping contains a "embedding" field of type "dense_vector"
    And the dense_vector uses "bbq_hnsw" index options
    And the similarity is "cosine"
    And the dims is 768

  Scenario: Initialize skips index creation if indices already exist
    Given an ElasticsearchStore with a mock AsyncElasticsearch client
    And the indices "distillery_entries_v1", "distillery_search_log_v1", and "distillery_feedback_log_v1" already exist
    When initialize() is called
    Then no index creation calls are made
    And no error is raised

  # --- CRUD Operations ---

  Scenario: Store an entry and retrieve it by ID
    Given an initialized ElasticsearchStore with a mock ES client
    And a valid Entry with id "abc-123" and content "Python asyncio patterns"
    When store() is called with the entry
    Then the entry is indexed in "distillery_entries" with id "abc-123"
    And the embedding is generated via the configured EmbeddingProvider
    And the returned ID is "abc-123"
    When get() is called with id "abc-123"
    Then the returned Entry has content "Python asyncio patterns"

  Scenario: Get returns None for a non-existent entry
    Given an initialized ElasticsearchStore with a mock ES client
    And no entry exists with id "missing-id"
    When get() is called with id "missing-id"
    Then the result is None

  Scenario: Get returns None for an archived entry
    Given an initialized ElasticsearchStore with a mock ES client
    And an entry with id "archived-1" exists with status "archived"
    When get() is called with id "archived-1"
    Then the result is None

  Scenario: Update modifies allowed fields and increments version
    Given an initialized ElasticsearchStore with a mock ES client
    And an entry with id "entry-1" exists at version 1
    When update() is called with id "entry-1" and fields tags=["updated"] and entry_type="reference"
    Then the entry version is incremented to 2
    And the tags are ["updated"]
    And the entry_type is "reference"

  Scenario: Update re-embeds when content changes
    Given an initialized ElasticsearchStore with a mock ES client
    And an entry with id "entry-1" exists with content "old content"
    When update() is called with id "entry-1" and content "new content"
    Then the EmbeddingProvider is called to generate a new embedding
    And the stored embedding is updated

  Scenario: Update rejects immutable fields
    Given an initialized ElasticsearchStore with a mock ES client
    And an entry with id "entry-1" exists
    When update() is called with id "entry-1" and field "id" set to "new-id"
    Then a ValueError is raised indicating "id" is immutable
    When update() is called with id "entry-1" and field "created_at" set to a new timestamp
    Then a ValueError is raised indicating "created_at" is immutable
    When update() is called with id "entry-1" and field "source" set to "new-source"
    Then a ValueError is raised indicating "source" is immutable

  Scenario: Delete soft-deletes by setting status to archived
    Given an initialized ElasticsearchStore with a mock ES client
    And an entry with id "entry-1" exists with status "active"
    When delete() is called with id "entry-1"
    Then the entry status is updated to "archived"
    And the entry document still exists in the index

  Scenario: Store uses AsyncElasticsearch client for all operations
    Given an ElasticsearchStore configured with a mock AsyncElasticsearch client
    When any CRUD operation is performed
    Then all Elasticsearch API calls use the async client methods
