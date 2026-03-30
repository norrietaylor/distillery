# 11-spec-elastic-backend

## Introduction/Overview

Add an Elasticsearch 9 Serverless Cloud storage backend to Distillery, implementing the full `DistilleryStore` protocol. This enables team-scale deployments with shared state, leverages Elasticsearch's native BBQ (Better Binary Quantization) vector search for high-quality semantic retrieval at reduced memory cost, and positions Distillery for cloud-native operation. The backend supports both client-side embedding (via existing `EmbeddingProvider`) and server-side embedding (via the ES Inference API).

## Goals

1. Implement `ElasticsearchStore` satisfying every method of the `DistilleryStore` protocol (store, get, update, delete, search, find_similar, list_entries, log_search, log_feedback).
2. Use BBQ HNSW (`bbq_hnsw`) vector indexing for dense_vector fields — 32x compression with ~95% memory reduction while maintaining high recall.
3. Support dual embedding paths: client-side via `EmbeddingProvider` (Jina/OpenAI) and server-side via ES Inference API with `semantic_text` field type.
4. Extend `StorageConfig` and `distillery.yaml` parsing to support `elasticsearch` as a backend with ES-specific connection settings.
5. Wire `ElasticsearchStore` into the MCP server lifespan so backend selection is config-driven.

## User Stories

- As a **team lead**, I want to configure Distillery to use a shared Elasticsearch backend so that all team members share a single knowledge base.
- As a **platform engineer**, I want to deploy Distillery against Elastic Cloud Serverless so that I don't manage infrastructure.
- As an **operator**, I want to switch between DuckDB and Elasticsearch backends via config so that I can start local and graduate to cloud.
- As a **developer**, I want Distillery's semantic search to use BBQ vector quantization so that I get high-quality results with lower resource usage.

## Demoable Units of Work

### Unit 1: ElasticsearchStore — Config, Connection, and CRUD

**Purpose:** Establish the Elasticsearch backend with connection management, index setup, and basic CRUD operations. After this unit, entries can be stored, retrieved, updated, and deleted in Elasticsearch.

**Functional Requirements:**
- The system shall accept `backend: elasticsearch` in `distillery.yaml` with settings: `url`, `api_key_env`, `cloud_id_env`, `index_prefix` (default `distillery`), `embedding_mode` (`client` | `server` | `auto`).
- The system shall validate ES-specific config: `url` or `cloud_id_env` must be set; `api_key_env` must reference a non-empty env var.
- The system shall use the `elasticsearch` 9.x async client (`AsyncElasticsearch`) for all operations.
- The system shall authenticate via API key sourced from the configured environment variable.
- The system shall create versioned indices with aliases on `initialize()`: `{prefix}_entries_v1` aliased to `{prefix}_entries`, `{prefix}_search_log_v1` aliased to `{prefix}_search_log`, `{prefix}_feedback_log_v1` aliased to `{prefix}_feedback_log`.
- The system shall map the `embedding` field as `dense_vector` with `bbq_hnsw` index options and `cosine` similarity, dimensions matching the configured `EmbeddingProvider`.
- The system shall implement `store()` — index an entry document, generate embedding via `EmbeddingProvider`, return the entry ID.
- The system shall implement `get()` — retrieve by ID, return `None` for missing or archived entries.
- The system shall implement `update()` — partial update with version increment, reject immutable fields (`id`, `created_at`, `source`), re-embed if `content` changes.
- The system shall implement `delete()` — soft-delete by setting `status: archived`.

**Proof Artifacts:**
- Test: `tests/test_elasticsearch_store.py::test_crud_operations` passes — demonstrates store/get/update/delete round-trip against a mock ES client.
- Test: `tests/test_config.py::test_elasticsearch_config_validation` passes — demonstrates config parsing and validation for the `elasticsearch` backend.
- CLI: `mypy --strict src/distillery/store/elasticsearch.py` returns 0 exit code.

### Unit 2: Semantic Search, Similarity, and Dual Embedding

**Purpose:** Implement vector search operations with kNN + BBQ and support both client-side and server-side embedding. After this unit, semantic search and deduplication work against Elasticsearch.

**Functional Requirements:**
- The system shall implement `search()` using the ES `knn` top-level search option with `query_vector`, `k`, `num_candidates`, and metadata `filter` clauses.
- The system shall support all existing filter keys: `entry_type`, `author`, `project`, `tags` (any-match), `status`, `date_from`, `date_to`.
- The system shall implement `find_similar()` using kNN search with a `similarity` threshold parameter, mapping directly to the dedup thresholds (skip: 0.95, merge: 0.80, link: 0.60).
- The system shall implement `list_entries()` using a `bool` query with filters, sorted by `created_at` descending, with `from`/`size` pagination.
- When `embedding_mode` is `server`, the system shall use the `semantic_text` field type backed by an ES Inference endpoint, and omit client-side embedding calls.
- When `embedding_mode` is `client` (default), the system shall embed via the configured `EmbeddingProvider` and pass `query_vector` directly to kNN queries.
- When `embedding_mode` is `auto`, the system shall detect whether an inference endpoint is configured and choose accordingly.
- The system shall convert ES similarity scores to the `[0.0, 1.0]` cosine range used by `SearchResult` (ES cosine formula: `(1 + cosine) / 2`).

**Proof Artifacts:**
- Test: `tests/test_elasticsearch_store.py::test_search_with_filters` passes — demonstrates kNN search with metadata filtering.
- Test: `tests/test_elasticsearch_store.py::test_find_similar_threshold` passes — demonstrates similarity threshold enforcement.
- Test: `tests/test_elasticsearch_store.py::test_embedding_mode_selection` passes — demonstrates client/server/auto mode switching.
- CLI: `mypy --strict src/distillery/store/elasticsearch.py` returns 0 exit code.

### Unit 3: Search Logging, Feedback, and MCP Integration

**Purpose:** Complete the protocol with logging methods and wire the backend into the MCP server. After this unit, Distillery is fully operational on Elasticsearch via config switch.

**Functional Requirements:**
- The system shall implement `log_search()` — index a document in `{prefix}_search_log` with query, result IDs, scores, session ID, and timestamp.
- The system shall implement `log_feedback()` — index a document in `{prefix}_feedback_log` with search ID, entry ID, signal, and timestamp.
- The MCP server `lifespan()` shall instantiate `ElasticsearchStore` when `config.storage.backend == "elasticsearch"`, passing the async client, embedding provider, and config.
- The `distillery_status` tool shall report Elasticsearch-specific stats: index document counts, index size, embedding model, backend type.
- The `distillery health` CLI command shall verify ES connectivity via `client.info()` and report cluster health.
- The system shall gracefully close the async ES client on MCP server shutdown.

**Proof Artifacts:**
- Test: `tests/test_elasticsearch_store.py::test_log_search_and_feedback` passes — demonstrates search/feedback logging round-trip.
- Test: `tests/test_mcp_server.py::test_elasticsearch_backend_selection` passes — demonstrates MCP server starts with ES backend from config.
- CLI: `distillery health` with `backend: elasticsearch` config returns connection status.
- File: `src/distillery/store/elasticsearch.py` contains `class ElasticsearchStore` implementing all protocol methods.

## Non-Goals (Out of Scope)

- **ES|QL integration** — ES|QL cannot perform kNN vector search. Query DSL covers all needs. ES|QL may be added for analytics in a future spec.
- **Hybrid kNN + BM25 search** — Start with pure kNN for parity with DuckDB. Hybrid scoring is a future enhancement.
- **Data migration tooling** — No DuckDB-to-ES or ES-to-DuckDB migration in this spec.
- **Self-managed Elasticsearch** — Target is ES 9 Serverless Cloud only. Self-managed may work but is untested/unsupported.
- **OpenSearch compatibility** — Not in scope.
- **Elastic Connectors / feed ingestion** — Feed polling remains in the existing feed system.

## Design Considerations

No UI changes. All configuration is via `distillery.yaml`. The backend is transparent to MCP tool callers — same tool interface regardless of backend.

Example config:
```yaml
storage:
  backend: elasticsearch
  url: https://my-project.es.us-east-1.aws.elastic.cloud
  api_key_env: ELASTICSEARCH_API_KEY
  cloud_id_env: ELASTICSEARCH_CLOUD_ID  # alternative to url
  index_prefix: distillery
  embedding_mode: client  # client | server | auto
```

## Repository Standards

- Python 3.11+, `mypy --strict` on `src/`
- `ruff` line length 100, standard rule set
- `pytest-asyncio` auto mode with `@pytest.mark.unit` / `@pytest.mark.integration` markers
- Conventional Commits: `feat(store): ...`, `test(store): ...`, `refactor(config): ...`
- Protocol-based design (structural subtyping, not ABCs)
- All storage operations async

## Technical Considerations

- **Python client**: `elasticsearch` 9.x (`pip install elasticsearch[async]`). Add to `pyproject.toml` as optional dependency group `[elasticsearch]`.
- **BBQ HNSW**: Default for dims >= 384 in ES 9.1+. Use `bbq_hnsw` index options with `m: 16`, `ef_construction: 100`. Oversampling 3x is automatic.
- **Index versioning**: Use `{prefix}_entries_v1` with alias `{prefix}_entries` for zero-downtime schema migrations (pattern from Elastic best practices).
- **Score conversion**: ES cosine score = `(1 + cosine(q, v)) / 2`. Convert back: `cosine = 2 * es_score - 1`. The `SearchResult.score` field should use the `[0, 1]` range consistent with DuckDB backend.
- **Dense vectors excluded from `_source` by default** in ES 9 — use `fields` parameter or `exclude_vectors: false` when retrieving entries that need re-embedding.
- **Connection pooling**: `AsyncElasticsearch` manages its own HTTP connection pool. One client instance shared across the MCP server lifespan.
- **Error handling**: Map ES exceptions (`NotFoundError`, `ConflictError`, `ConnectionError`) to the same `KeyError`/`ValueError` semantics the protocol specifies.
- **Serverless constraints**: Max 15,000 indices per project, vector indices max 150GB. Not a concern for knowledge base scale.

## Security Considerations

- **API keys only** — stored in environment variables, never in config files or conversation history. Config references the env var name, not the key itself.
- **TLS** — ES 9 Serverless enforces HTTPS. The client defaults to TLS verification.
- **No cluster admin APIs** — Serverless blocks `_nodes/*`, `_cluster/*`. The backend must not depend on these.
- **Index-scoped access** — API keys should be scoped to the `{prefix}_*` index pattern for least-privilege access.

## Success Metrics

- All `DistilleryStore` protocol methods pass unit tests with mock ES client.
- Integration tests pass against a live ES 9 Serverless instance (CI-optional, requires API key).
- `mypy --strict` passes on the new module with zero errors.
- Backend switch via config is seamless — all 21 MCP tools work identically on both backends.
- Search quality (recall@10) is comparable to DuckDB backend on the same dataset.

## Open Questions

1. **Inference endpoint model**: When `embedding_mode: server`, which model should the ES inference endpoint use? Should the config specify the inference endpoint ID, or should Distillery create one?
2. **Index lifecycle**: Should Distillery manage index lifecycle (e.g., rollover for search_log), or leave that to Elastic Cloud's built-in data stream lifecycle?
3. **Bulk operations**: The current protocol has no `store_batch()`. Should we add one for ES bulk indexing, or handle batching internally in `store()`?
